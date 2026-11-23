"""The community agent's service: its message-bus inbox, the market's tick, the waiting clock, and its HTTP doors.

One process stands for one community. It holds the community's signing key and the keys it pinned for its members, takes every signed message
from its inbox (market.Market.handle for the contract steps, Market.from_above for its aggregator's requests), ticks the market once a second
and at once when its clock is set, and, when the clock waits (cfg clock_waits), moves every participant's clock once nothing is still on its
way: one 15-minute step at a time, or, when it leaps (cfg clock_leap), over the quarter hours nothing is scheduled at in one move (conductor.py).

  python -m murmur.agents.community.service run       # the service, on <bind_host>:<community_port>
  python -m murmur.agents.community.service pubkey    # this community's public key
"""
from __future__ import annotations

import argparse
import json
import logging
import threading
import time
import traceback
from collections import deque
from typing import Any

from murmur.protocol import envelope as beckn
from murmur import config
from murmur import files
from murmur.protocol import signing
from murmur.agents.community.market import Market
from murmur.replay import Replay
from murmur.settlement import meter_check
from murmur.protocol.transport import TownSession
from murmur.protocol.inbox import InboxPoller
from murmur.protocol.inbox import LagMeter

log = logging.getLogger("murmur.community")
TS = "%Y-%m-%d %H:%M"
TICK_S = 1.0                    # the market loop's cadence: its next pass starts this long after the last, or at once when the clock is set


class CommunityAgent:
    def __init__(self):
        self.cfg = c = config.load()
        self.name = c.get("agent_name") or "community"
        self.key = signing.load_or_create(config.CONFIG_DIR / "secrets" / "signing.key")
        self.pub = signing.public_hex(self.key)
        tok = config.secret("town_token")
        self.town = TownSession(c["town_url"], c["town_run_id"], self.name, tok) if c.get("town_run_id") and tok else None
        self.pins_path = config.state_dir() / "home_pins.json"
        self.pins: dict[str, str] = self.read_pins()
        self.events: deque = deque(maxlen=300)
        self.expired_skipped = 0                          # messages past their time-to-live: dropped, not acted on
        self.inbox_ready = False                          # True once the inbox has been empty: caught up
        self.lag = LagMeter(window=float(c.get("town_lag_window_s", 20.0)))   # how far behind the inbox is
        self.started_wall = time.time()
        self.lock = threading.RLock()
        roster = c.get("roster") or [h["name"] for h in json.loads(config.data_path("fleet_v2.json").read_text())["homes"]]
        from murmur.node import simulator_building as building  # the building members this config enables (cfg "buildings"): asked like a home
        self.buildings = building.enabled(c)
        roster = roster + [b["name"] for b in self.buildings if b["name"] not in roster]
        self.clock = Replay(c["clock_profile"], c["replay_start"], c["replay_step_seconds"], c["replay_loop_days"])
        self.market = Market(self.name, self.key, self._town_send, self.clock, roster, self.pins, self.save_pins, self.event, c)
        self.market.on_clear, self.market.on_settle = self.c3, self.c4
        self.market.town_lag = self.town_lag              # the real-time desk waits longer for answers when the bus is behind
        from murmur.agents.community import community
        self.market.community = community.for_agent(c, config.state_dir(), self.event)
        if self.market.pooled:                            # what each member may claim comes from its enrolment, not its word
            self.market.rated = meter_check.rated(roster)
            self.event("v2_nameplates", members=len(roster), on_file=len(self.market.rated))
        self.targets = self.clock_targets()

    def clock_targets(self) -> dict[str, str]:
        """Every participant that keeps the replay clock besides this one: the first buyer, the homes' host, each building, and the ones
        cfg clock_extra_targets names (the second buyer, the aggregator, each single site)."""
        from murmur.node import simulator_building as building
        c = self.cfg
        t = {"utility": c.get("utility_url"), "fleet": c.get("host_url")}
        for b in self.buildings:
            t[b["name"]] = building.service_url(b, c)
        t.update(c.get("clock_extra_targets") or {})
        return {k: v for k, v in t.items() if v}

    def read_pins(self) -> dict[str, str]:
        """A file that can't be read costs the pins, not the start: it is set aside, and each member is pinned again at its first message."""
        try:
            pins = json.loads(self.pins_path.read_text()) if self.pins_path.exists() else {}
            if not isinstance(pins, dict) or not all(isinstance(v, str) for v in pins.values()):
                raise ValueError("it isn't a table of keys")
            return pins
        except (OSError, ValueError, RecursionError) as exc:
            log.error("home pins: %s", exc)
            files.set_aside(self.pins_path)
            return {}

    def save_pins(self) -> None:
        """All or nothing: a file cut short by a crash costs every pin at the next start."""
        files.write_atomic(self.pins_path, json.dumps(self.pins, indent=1).encode())

    def _off_thread(self, step: str, event_id: str, phase: str, run) -> None:
        """A clearing or a settlement runs on its own thread, under the market's lock, if the sale is still in `phase`."""
        def go():
            with self.market.lock:
                ev = self.market.events.get(event_id)
                if ev is None or ev["phase"] != phase:
                    return
                try:
                    run(event_id)
                    self.event(f"{step}_inprocess", event_id=event_id)
                except Exception as exc:                  # noqa: BLE001  the sale says so: no tick picks these phases up again
                    ev["flow_failed"] = f"{type(exc).__name__}: {exc}"[:160]
                    self.event("v2_flow_failed", flow=step, event_id=event_id, error=ev["flow_failed"])
                    log.error("%s for %s: %s", step, event_id, traceback.format_exc())
        threading.Thread(target=go, daemon=True).start()

    def c3(self, event_id: str) -> None:
        """Offers are in: clear the pool and contract with the buyers."""
        ev = self.market.events[event_id]
        ev["phase"], ev["clearing_wall"] = "clearing", time.time()
        self._off_thread("c3", event_id, "clearing", self.market.clear_and_commit)

    def c4(self, event_id: str) -> None:
        """The buyers have settled: split and pay. Once per sale: a settlement that arrives again never sends the sale back to 'settling'."""
        ev = self.market.events[event_id]
        if ev.get("result") or ev["phase"] in ("settling", "done"):
            self.event("v2_settle_repeat_ignored", event_id=event_id, phase=ev["phase"])
            return
        ev["phase"] = "settling"
        self._off_thread("c4", event_id, "settling", self.market.settle)

    def _town_send(self, to: str, kind: str, body: dict[str, Any], message_id: str) -> dict[str, Any]:
        if not self.town:
            raise RuntimeError("no message bus session")
        out = self.town.send(to, kind, body, message_id)
        if isinstance(out, dict) and out.get("duplicate"):    # the bus refused it: see TownSession.send
            self.event("town_send_dropped", to=to, message_kind=kind, message_id=message_id)
        return out

    def market_loop(self) -> None:
        """The market's tick, once a second and at once when the clock is set. self.clock.ticked is the dataset time of its last whole pass since then:
        what the waiting clock can read here, in its own process, before it moves every clock on."""
        f = self.clock.follower
        while True:
            seen, now = f.moves, self.clock.ts(self.clock.current())
            try:
                self.market.tick()
                self.market.failing.pop("the tick", None)
                f.passed(seen, now)
            except Exception as exc:
                self.event("market_error", error=str(exc)[:200])
                log.error("market: %s", traceback.format_exc())
                self.market.failed("the tick", exc)
            f.wait(seen, TICK_S)

    def event(self, kind: str, **detail) -> None:
        try:
            sim = self.clock.ts(self.clock.current())            # dataset time, next to the wall time
        except Exception:
            sim = None
        self.events.append({"at": time.time(), "sim": sim, "kind": kind, **detail})
        log.info("%s %s", kind, json.dumps(detail, default=str)[:300])

    # ------------------------------------------------------------------ the inbox
    def town_lag(self) -> float:
        """Seconds the bus is behind: the median wait of the messages this service claimed lately. 0 when the inbox keeps up."""
        return self.lag.value()

    def handle(self, msg: dict[str, Any]) -> None:
        self.lag.seen(msg)
        body, kind, sender = msg.get("body") or {}, msg.get("kind"), msg.get("from")
        status, note = "processed", {}
        if str(kind).startswith(("beckn.", "community.")) and beckn.expired(body, default_ttl=float(self.cfg.get("max_message_age_s", 900))):
            self.expired_skipped += 1                     # waited in the inbox past its validity: dropped
            status, note = "rejected", {"skipped": "expired", "late_s": round(beckn.expired(body) or 0)}
        elif str(kind).startswith("beckn."):
            try:
                status, note = beckn.ack_of(self.market.handle(kind, sender, body), 300, "result")
            except Exception as exc:
                status, note = "rejected", {"error": str(exc)[:200]}
                log.error("v2: %s", traceback.format_exc())
        elif str(kind).startswith("community."):          # the level above the community: its aggregator's signed request
            try:
                status, note = beckn.ack_of(self.market.from_above(kind, sender, body), 300, "result")
            except Exception as exc:
                status, note = "rejected", {"error": str(exc)[:200]}
                log.error("community: %s", traceback.format_exc())
        else:
            status, note = "rejected", {"reason": "unknown_kind"}
        self.town.ack(msg["message_id"], msg["fence"], status, note)

    def inbox_loop(self) -> None:
        """The inbox, watched with short checks (protocol/inbox.py's InboxPoller): every `town_poll_seconds` while messages flow, every
        `town_poll_idle_seconds` after a quiet minute; a pass that finds a message brings in `inbox_workers` claimers
        (`catchup_workers` until the inbox has been empty once, to clear a backlog)."""
        while not self.town:
            time.sleep(5)
        cfg = self.cfg

        def ready() -> None:                              # the inbox was empty once: everything old is cleared
            if not self.inbox_ready:
                self.inbox_ready = True
                self.event("inbox_ready", expired_skipped=self.expired_skipped, seconds=round(time.time() - self.started_wall))
                self.poller.claimers = max(1, int(cfg.get("inbox_workers", 4)))

        def err(where: str, exc: Exception) -> None:
            self.event("town_error", error=f"{where}: {str(exc)[:200]}")
            log.debug(traceback.format_exc())

        self.poller = InboxPoller(self.town, self.handle, every=float(cfg.get("town_poll_seconds", 1.0)),
                                  idle_every=float(cfg.get("town_poll_idle_seconds", 3.0)),
                                  claimers=max(1, int(cfg.get("catchup_workers", 16))), on_error=err, on_empty=ready)
        self.poller.run()


def main() -> None:
    from murmur.agents.community.doors import build_app
    ap = argparse.ArgumentParser(prog="murmur-community")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("run")
    sub.add_parser("pubkey")
    a = ap.parse_args()
    cfg = config.load()
    if a.cmd == "pubkey":
        print(signing.public_hex(signing.load_or_create(config.CONFIG_DIR / "secrets" / "signing.key")))
        return
    import uvicorn
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    port = int(cfg["community_port"])
    c = CommunityAgent()
    c.cfg.setdefault("readings_quiet_s", 30.0)            # readings still on their way through a busy bus aren't asked for twice
    from murmur.protocol import wire
    wire.open_log(str(config.log_dir() / "town_wire.jsonl"))       # every signed message sent or received
    print(f"community {c.name} pubkey {c.pub}; run {c.cfg.get('town_run_id')}; API http://{cfg['bind_host']}:{port}", flush=True)
    if c.town:                                            # joins in the background (again and again while the bus is down), then reads its inbox
        c.town.join_until_up(then=lambda: threading.Thread(target=c.inbox_loop, daemon=True).start(),
                             log=lambda m: (print(m, flush=True), c.event("town_error", error=m)))
    else:
        threading.Thread(target=c.inbox_loop, daemon=True).start()
    threading.Thread(target=c.market_loop, daemon=True).start()
    uvicorn.run(build_app(c), host=cfg["bind_host"], port=port, log_level="warning")


if __name__ == "__main__":
    main()
