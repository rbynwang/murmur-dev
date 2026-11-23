"""A single site's service: the site's agent (agents/site.py) with its own bus session, signing key, inbox and HTTP doors.

  python -m murmur.agents.site_service run | pubkey
"""
from __future__ import annotations

import argparse
import logging
import re
import threading
import time
import traceback
from typing import Any

from murmur.protocol import envelope as beckn
from murmur.agents.community import community
from murmur import config
from murmur.protocol import doors
from murmur.protocol import signing
from murmur.protocol import wire
from murmur.replay import Replay
from murmur.agents.site import Limits, Site
from murmur.protocol.transport import TownSession
from murmur.protocol.inbox import InboxPoller

log = logging.getLogger("murmur.site")
REQUEST, ANSWER, REPORT = "community.request", "community.answer", "community.report"
TIME = re.compile(r"\d{4}-\d{2}-\d{2} ([01]\d|2[0-3]):[0-5]\d")    # a request row's time: a quarter hour of the dataset's clock
ANSWER_RETRY_S = 5.0                                                # an answer the bus didn't take goes again this long after
TICK_S = 0.25                                                       # the loop's cadence: its next pass starts this long after the last, or at once when its clock is set


class SiteNode:
    def __init__(self) -> None:
        c = self.cfg = config.load()
        self.name = c.get("agent_name") or "site"
        self.key = signing.load_or_create(config.CONFIG_DIR / "secrets" / "site.key")
        self.pub = signing.public_hex(self.key)
        tok = config.secret("town_token")
        self.town = TownSession(c["town_url"], c["town_run_id"], self.name, tok) if c.get("town_run_id") and tok else None
        self.clock = Replay(c["clock_profile"], c["replay_start"], c["replay_step_seconds"], c["replay_loop_days"])
        d, lim = c["site"], c.get("site_limits") or {}
        self.site = Site(d["id"], d["kind"], float(d["rating_kw"]), float(d["energy_kwh"]), float(d.get("out_factor", 1.0)), float(d["limit_out_kw"]) if d.get("limit_out_kw") is not None else float("inf"),
                         wait_h=float(d.get("wait_h", 0.0)), limits=Limits(lim.get("give_max_kw"), bool(lim.get("hold")), lim.get("pause_max_kw"), str(lim.get("why") or "")))
        self.agg = c["site_aggregator"]["name"]
        self.agg_key = c["site_aggregator"]["public_key"]
        self.feed: dict[str, dict[str, float]] = c.get("site_feed") or {}
        self.lock = threading.RLock()
        self.done: list[str] = []                             # quarter hours stepped, in order
        self.outbox: list[dict[str, Any]] = []                # rows still to go up
        self.sent_up = 0
        self.asked: dict[str, dict[str, Any]] = {}            # request id -> what was asked and answered
        self.refused: dict[str, int] = {}
        self.poller: InboxPoller | None = None
        self.started = False

    def now(self) -> str:
        return self.clock.ts(self.clock.current())

    def _no(self, why: str) -> beckn.Refused:
        self.refused[why] = self.refused.get(why, 0) + 1
        return beckn.Refused(f"rejected: {why}")

    # ------------------------------------------------------------------ the request, and the site's own answer
    def take(self, kind: str, sender: str, body: Any) -> str:
        with self.lock:
            if sender != self.agg or kind != REQUEST:
                return self._no("only its aggregator asks this site, and only with a request")
            if not isinstance(body, dict) or not isinstance(body.get("context"), dict) or not isinstance(body.get("message"), dict) or not beckn.check(body, self.agg_key):
                return self._no("bad signature")
            ctx = body["context"]
            if ctx.get("bapId") != self.agg or ctx.get("bppId") != self.name:
                return self._no("not made for this site")
            req = body["message"].get("request")
            if not (isinstance(req, dict) and isinstance(req.get("id"), str) and req.get("community") == self.site.id and isinstance(req.get("rows"), list) and req["rows"]):
                return self._no("not a request for this site")
            if req["id"] in self.asked:
                if not self.asked[req["id"]]["sent"]:        # asked again while its answer hasn't gone: it goes now, under the same id
                    threading.Thread(target=self._answer, args=(req["id"],), daemon=True).start()
                return "request noted before"
            now, by_hour, pause = self.now(), {}, {}
            try:
                for r in req["rows"]:
                    ts, kw, pk = str(r.get("ts"))[:16], r.get("battery_kw"), r.get("pause_kw")
                    if not (TIME.fullmatch(ts) and community.amount(kw) and (pk is None or community.amount(pk))):
                        raise community.Refused("a request's rows are a time and numbers that aren't negative")
                    h = int(ts[11:13])
                    by_hour[h] = max(by_hour.get(h, 0.0), float(kw))
                    if pk:                                      # a data center may also be asked to pause work that can wait
                        pause[h] = max(pause.get(h, 0.0), float(pk))
                ans = self.site.ask(by_hour, pause or None)
                why = sorted({v["why_less"] for v in ans["battery"].values() if v.get("why_less")})
                out = {"request": req["id"], "community": self.site.id, "taken": True, "rows": len(req["rows"]), "why": "; ".join(why) or None, "at": now}
                text = f"request taken: {len(req['rows'])} quarter hours"
            except community.Refused as exc:
                ans, out, text = None, {"request": req["id"], "community": self.site.id, "taken": False, "why": str(exc), "at": now}, beckn.Refused(f"request refused: {exc}")
            msg = beckn.make("on_request", sender=self.name, receiver=self.agg, transaction_id=str(ctx.get("transactionId") or req["id"]), key=self.key, sender_role="bpp",
                             message_id=f"{self.name}:{self.agg}:on_request:{req['id']}", message={"answer": out}, ttl_s=beckn.TTL_EVIDENCE_S)
            self.asked[req["id"]] = {"at": now, "answer": ans, "taken": out["taken"], "msg": msg, "sent": False, "tried": 0.0}
        threading.Thread(target=self._answer, args=(req["id"],), daemon=True).start()       # off the inbox's thread: it acknowledges its bus message first
        return text

    def _answer(self, rid: str) -> None:
        """Sends a request's signed answer. One that doesn't go is sent again, under the same id, when the request comes again or on a
        later tick (ANSWER_RETRY_S apart), until the bus has it."""
        with self.lock:
            a = self.asked.get(rid)
            if a is None or a["sent"]:
                return
            a["tried"], msg = time.time(), a["msg"]
        if self._send(ANSWER, msg):
            with self.lock:
                a["sent"] = True

    def _send(self, kind: str, body: dict[str, Any]) -> bool:
        try:
            self.town.send(self.agg, kind, body, body["context"]["messageId"])
            wire.note("send", self.name, self.agg, str(body["context"].get("action")), body, sim=self.now())
            return True
        except Exception as exc:
            log.error("send %s: %s", kind, str(exc)[:200])
            return False

    def handle(self, msg: dict[str, Any]) -> None:
        try:
            text: str = self.take(str(msg.get("kind")), str(msg.get("from")), msg.get("body"))
        except Exception:
            log.error("inbox: %s", traceback.format_exc())
            text = self._no("that message can't be read")
        status, note = beckn.ack_of(text, 300, "result")
        self.town.ack(msg["message_id"], msg["fence"], status, note)

    # ------------------------------------------------------------------ the quarter hours
    def tick(self) -> bool:
        """One pass: every quarter hour that is due is stepped, and its row goes up. True for a whole pass: the play has started and no row is left
        for the next pass."""
        if not self.started or self.town is None:
            return False
        now = self.now()
        q = now[:14] + f"{int(now[14:16]) // 15 * 15:02d}"
        with self.lock:
            due = [t for t in sorted(self.feed) if t <= q and (not self.done or t > self.done[-1])]
            for t in due:                                       # in order, none skipped: a clock that moved two steps at once still gets both
                x = self.feed[t]
                if not self.done and x.get("store_before_kwh") is not None:
                    self.site.store_kwh = min(max(float(x["store_before_kwh"]), self.site.emin), self.site.emax)
                r = self.site.step(t, float(x["base_kw"]), float(x["recorded_kw"]), float(x["own_kwh"]), float(x.get("share") or 0.0), x.get("price_usd_kwh"))
                self.done.append(t)
                self.outbox.append(r["row"])
            rows = list(self.outbox)
            unsent = [rid for rid, a in self.asked.items() if not a["sent"] and time.time() - a["tried"] >= ANSWER_RETRY_S]
        for rid in unsent:                                      # an answer that didn't go the first time
            self._answer(rid)
        for row in rows:                                        # signed and sent off the lock, oldest first; a row that can't go now is tried again on the next tick
            msg = beckn.make("report", sender=self.name, receiver=self.agg, transaction_id=f"report:{self.site.id}:{row['timestamp'][:10]}", key=self.key, sender_role="bpp",
                             message_id=f"{self.name}:{self.agg}:report:{self.site.id}:{row['timestamp']}", message={"report": row}, ttl_s=beckn.TTL_EVIDENCE_S)
            if not self._send(REPORT, msg):
                break
            with self.lock:
                if self.outbox and self.outbox[0] is row:
                    self.outbox.pop(0)
                    self.sent_up += 1
        return not self.outbox

    def tick_loop(self) -> None:
        f = self.clock.follower
        while True:
            seen, now = f.moves, self.now()
            try:
                if self.tick():
                    f.passed(seen, now)
            except Exception:
                log.error("tick: %s", traceback.format_exc())
            f.wait(seen, TICK_S)

    def inbox_loop(self) -> None:
        self.poller = InboxPoller(self.town, self.handle, every=float(self.cfg.get("town_poll_seconds", 1.0)), idle_every=float(self.cfg.get("town_poll_idle_seconds", 3.0)), claimers=1,
                                  on_error=lambda where, exc: log.error("town %s: %s", where, str(exc)[:200]))
        self.poller.run()

    def view(self) -> dict[str, Any]:
        with self.lock:
            return {"agent": self.name, "pubkey": self.pub, "now": self.now(), "site": self.site.id, "kind": self.site.kind, "store_kwh": round(self.site.store_kwh, 3), "work_still_owed_kwh": round(self.site.owed_kwh(), 3), "limits": {"give_max_kw": self.site.limits.give_max_kw, "hold": self.site.limits.hold, "pause_max_kw": self.site.limits.pause_max_kw}, "quarter_hours_run": len(self.done),
                    "first": self.done[0] if self.done else None, "last": self.done[-1] if self.done else None, "rows_sent_up": self.sent_up, "rows_waiting": len(self.outbox),
                    "requests": {rid: {"at": a["at"], "answer": a["answer"], "taken": a["taken"]} for rid, a in self.asked.items()},
                    "gaps": list(self.site.gaps), "not_kept": dict(self.refused)}


def build_app(n: SiteNode):
    from fastapi import Body, FastAPI

    app = FastAPI(title="murmur-site", version="0.1.0", dependencies=[doors.door()])

    @app.get("/health")
    def health():
        return {"ok": True, "agent": n.name, "pubkey": n.pub, "now": n.now(), "label": "Single site", "town": n.town is not None, "doors": doors.state(), "town_calls": n.poller.stats() if n.poller else None}

    @app.get("/site")
    def view():
        return n.view()

    @app.post("/demo/reset")
    def demo_reset(body: dict = Body(default={})):
        """A new play starts: what was asked, done and sent in the last one is put away. The site and its feed stay."""
        with n.lock:
            n.done.clear(); n.outbox.clear(); n.asked.clear(); n.refused.clear(); n.sent_up = 0; n.site.asked_kw.clear(); n.site.pause_kw.clear(); n.site.queue.clear(); n.site.gaps.clear(); n.started = False
        return {"ok": True}

    @app.get("/demo/clock")
    def demo_clock_get():
        return n.clock.clock()

    @app.post("/demo/clock")
    def demo_clock(body: dict = Body(default={})):
        n.clock.configure(body.get("start", n.clock.start), float(body.get("step_seconds", n.clock.step_seconds)), int(body.get("loop_days", n.clock.loop_days)), body.get("at"), body.get("at_wall"), hold=bool(body.get("hold")))
        if not n.started:                                       # the play starts here. The pass the set clock began may have come before this line and done nothing: the loop looks again
            n.started = True
            n.clock.follower.moved()
        return n.clock.clock()

    return app


def main() -> None:
    ap = argparse.ArgumentParser(prog="murmur-site")
    ap.add_argument("cmd", choices=["run", "pubkey"])
    args = ap.parse_args()
    if args.cmd == "pubkey":
        print(signing.public_hex(signing.load_or_create(config.CONFIG_DIR / "secrets" / "site.key")))
        return
    import uvicorn
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    n = SiteNode()
    if not n.cfg.get("site_port"):
        raise SystemExit("murmur-site: no site_port in its config, and it takes no port it wasn't given")
    if n.town is None:
        raise SystemExit("murmur-site: no message-bus run or token in its config")
    logs = config.log_dir()
    logs.mkdir(exist_ok=True)
    wire.open_log(str(logs / f"town_wire_{n.name}.jsonl"))
    n.town.join_until_up(then=lambda: threading.Thread(target=n.inbox_loop, daemon=True).start(), log=lambda m: print(m, flush=True))
    threading.Thread(target=n.tick_loop, daemon=True).start()
    uvicorn.run(build_app(n), host=n.cfg["bind_host"], port=int(n.cfg["site_port"]), log_level="warning")


if __name__ == "__main__":
    main()
