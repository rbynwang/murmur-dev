"""A participant's inbox on the message bus: watched with short checks (never a held long-poll), claimed by a few workers, and how far behind it is."""
from __future__ import annotations

import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable
import httpx
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from murmur.protocol.transport import TownSession


def _once_more(f: Callable, *a, **k):
    """A Town call tried once more at once when the connection drops (a kept-alive connection the server had already
    closed). Safe for notify, claim and ack: a claim whose answer was lost comes back after its lease, an ack repeated
    gets a stale-fence answer."""
    try:
        return f(*a, **k)
    except httpx.TransportError:
        return f(*a, **k)


class LagMeter:
    """How far behind an inbox is: the median delay (claimed minus the sender's sentWall) of the messages it claimed in
    the last `window` s, counting first deliveries only (a message handed out again waited out a lease, which says
    nothing about a backlog) and only once at least `min_n` came (one late message is not a backlog). 0 when nothing
    came lately: an empty inbox is not behind."""

    def __init__(self, window: float = 20.0, min_n: int = 3):
        self.window, self.min_n = window, min_n
        self._seen: deque = deque(maxlen=600)
        self._lock = threading.Lock()

    def seen(self, msg: dict[str, Any], now: float | None = None) -> float | None:
        try:
            if int(msg.get("attempt") or 1) > 1 or msg.get("duplicate"):
                return None
            sent = float(((msg.get("body") or {}).get("context") or {}).get("sentWall") or 0.0)
            if sent <= 0:
                return None
            now = time.time() if now is None else now
            lag = max(0.0, now - sent)
            with self._lock:
                self._seen.append((now, lag))
            return lag
        except (TypeError, ValueError):
            return None

    def value(self, now: float | None = None) -> float:
        now = time.time() if now is None else now
        with self._lock:
            lags = sorted(lag for t, lag in self._seen if now - t <= self.window)
        return lags[len(lags) // 2] if len(lags) >= self.min_n else 0.0


class InboxPoller:
    """Watches one Town inbox with short checks and claims until it is empty; `handle(msg)` processes a claimed message
    and acknowledges it (a message it raises on is not acknowledged: Town hands it out again after its lease).

    Cadence: a check every `every` s while mail flows, every `idle_every` s once nothing has come for `idle_after` s
    (the first message of a quiet spell waits at most `idle_every`). Town keeps one wake-up hint per message (a hint
    is only a wake-up call, never the message itself):
      * a hint: claim until the inbox is empty. A pass that handled n messages leaves n - 1 hints for messages already
        handled: they are popped (the light call) without another claim pass. If the hints run out early, some were
        lost: one more pass, in case a message came meanwhile
      * a hint but nothing to claim, or a claim that failed on the way: the message may be held by a claim whose answer
        was lost, which Town hands out again after its lease: one more pass when the lease is over
      * a check that failed on the way may have used up a hint: one pass at once
      * while hints of messages already handled are popped, still a pass every `every` s: after a pass of 400
        messages, popping their hints one call at a time takes a minute, and new mail must not wait for it (the homes'
        answers to a grid call would otherwise reach the community agent a minute after they were sent)
      * a pass every `sweep` s anyway
    `claimers` > 1: a pass that finds a message brings in that many claimers in parallel (bursts: 100 offers, 400 meter
    readings). An empty inbox costs Town one claim, not `claimers`."""

    def __init__(self, town: TownSession, handle: Callable[[dict[str, Any]], Any], *, every: float = 1.0,
                 idle_every: float = 4.0, idle_after: float = 60.0, sweep: float = 30.0, lease: float = 30.0,
                 claimers: int = 1, on_error: Callable[[str, Exception], None] | None = None,
                 on_empty: Callable[[], None] | None = None, alive: Callable[[], bool] | None = None,
                 timed: Callable[[str, float], None] | None = None):
        self.town, self.handle = town, handle
        self.every, self.idle_every, self.idle_after, self.sweep = every, idle_every, idle_after, sweep
        self.lease = lease * 1.1 + 0.2                  # Town hands a lost claim out again after its lease
        self.claimers = max(1, int(claimers))
        self.on_error = on_error or (lambda where, exc: None)
        self.on_empty = on_empty or (lambda: None)
        self.alive = alive or (lambda: True)
        self.timed = timed or (lambda op, t0: None)
        self.pool = ThreadPoolExecutor(max_workers=self.claimers) if self.claimers > 1 else None
        self.handled = self.recovered = self.checks = self.claims = 0
        self.last_mail = 0.0
        self.fresh = 0                                  # messages of the last pass handed out for the first time
        self._flock = threading.Lock()

    def start(self, name: str = "town-inbox") -> threading.Thread:
        t = threading.Thread(target=self.run, name=name, daemon=True)
        t.start()
        return t

    def run(self) -> None:
        credit, recheck, sweep = 0, float("inf"), time.time()      # a first pass at once: whatever came while away
        last_pass = 0.0
        while self.alive():
            t0 = time.time()
            if t0 < self.town.conflict_until:               # another process holds this name: wait it out
                time.sleep(min(5.0, self.town.conflict_until - t0))
                continue
            tried = self.town.retried
            try:
                hint = self.town.notify(wait=0)
                self.timed("notify", t0)
                self.checks += 1
            except Exception as exc:
                self.on_error("notify", exc)
                hint = None                                  # unknown: a hint may have been used up
            if hint is False and self.town.retried != tried:
                hint = None                                  # the check had to be tried again: the first try may
                                                             # have popped a hint whose answer was lost
            if hint and credit > 0:
                credit -= 1                                  # a message the last pass already handled: pop the next
                if credit == 0:                              # hint at once. The count can be one too many (a hint
                    n, trouble = self.drain()                # lost on the way): the last one gets a pass, so a new
                    last_pass = time.time()                  # message whose hint was popped as stale is not left
                    if n:                                    # for the sweep
                        self.recovered += n
                    credit = max(0, self.fresh - 1) if n else 0
                    if trouble:
                        recheck = min(recheck, t0 + self.lease)
                elif t0 - last_pass >= self.every:           # popping many stale hints: mail that came meanwhile
                    n, trouble = self.drain()                # gets a pass every `every` s; its hints wait behind the
                    last_pass = time.time()                  # stale ones, so they join the count
                    credit += self.fresh
                    if trouble:
                        recheck = min(recheck, t0 + self.lease)
                continue
            if hint:
                n, trouble = self.drain()
                last_pass = time.time()
                credit = max(0, self.fresh - 1)              # hints left behind: one per message seen the first time
                if n == 0 or trouble:
                    recheck = min(recheck, t0 + self.lease)
            elif hint is None or credit > 0 or t0 >= recheck or t0 >= sweep:
                n, trouble = self.drain()
                last_pass = time.time()
                if n:
                    self.recovered += n
                credit, sweep = 0, t0 + self.sweep
                recheck = t0 + self.lease if trouble else float("inf")
            self._pause(t0)

    def _pause(self, t0: float) -> None:
        quiet = time.time() - self.last_mail > self.idle_after
        time.sleep(max(0.05, (self.idle_every if quiet else self.every) - (time.time() - t0)))

    def drain(self) -> tuple[int, bool]:
        """Claims until the inbox is empty: (messages claimed and handed to the handler, whether a claim failed on the way;
        a handler that raised is counted too: stats()["handled"] counts only those it finished). self.fresh: how many
        of them were handed out for the first time (attempt 1). Only those left a wake-up hint behind; a message Town
        hands out again (its lease ran out: a claim whose answer was lost, a machine that slept) brought none, and
        counting it would make the next new message's hint look stale, so that message would wait for a later pass (a
        contract answered after its deadline)."""
        with self._flock:
            self.fresh = 0
        got = self._claim_one()
        if got <= 0:
            if got == 0:
                self.on_empty()
            return 0, got < 0
        if self.pool is None:
            n, bad = self._claim_all()
        else:
            futs = [self.pool.submit(self._claim_all) for _ in range(self.claimers - 1)]
            n, bad = self._claim_all()
            for f in futs:
                m, b = f.result()
                n, bad = n + m, bad or b
        if not bad:
            self.on_empty()
        return 1 + n, bad

    def _claim_all(self) -> tuple[int, bool]:
        n = 0
        while self.alive():
            got = self._claim_one()
            if got <= 0:
                return n, got < 0
            n += 1
        return n, False

    def _claim_one(self) -> int:
        """1 if a message was claimed and handed over, 0 if the inbox was empty, -1 if the claim failed on the way."""
        t0, tried = time.time(), self.town.retried
        try:
            msg = _once_more(self.town.claim)
            self.timed("claim", t0)
            self.claims += 1
        except Exception as exc:
            self.on_error("claim", exc)
            return -1
        if not msg:                                   # empty; but if the call had to be tried again, the first try
            return -1 if self.town.retried != tried else 0   # may have claimed a message whose answer was lost
        self.last_mail = time.time()
        if int(msg.get("attempt") or 1) <= 1 and not msg.get("duplicate"):
            with self._flock:
                self.fresh += 1
        try:
            self.handle(msg)
            self.handled += 1
        except Exception as exc:                      # not acknowledged: Town hands it out again after its lease
            self.on_error("handle", exc)
        return 1

    def stats(self) -> dict[str, Any]:
        return {"checks": self.checks, "claims": self.claims, "handled": self.handled,
                "recovered_without_hint": self.recovered, "every_s": self.every, "idle_every_s": self.idle_every}
