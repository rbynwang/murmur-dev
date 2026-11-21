"""The aggregator's agent: the level above the communities and the single sites (an aggregator such as ENGIE).

It sends each participant its signed requests for the evening (the battery rows it asks for, by quarter hour), checks every signed
report row that comes back against the participant's enrolled key, and keeps the rows by participant. It asks; it never orders: a
participant's own limits stand.

  python -m murmur.agents.aggregator run | pubkey
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
from murmur import config
from murmur.protocol import doors
from murmur.protocol import signing
from murmur.protocol import wire
from murmur.replay import Replay
from murmur.protocol.transport import TownSession
from murmur.protocol.inbox import InboxPoller

log = logging.getLogger("murmur.aggregator")
REQUEST, ANSWER, REPORT = "community.request", "community.answer", "community.report"
ROW = frozenset({"entity_id", "timestamp", "reported_p_net_kw", "reported_soc_percent", "quote_side", "quote_price_usd_kwh", "text", "meter_p_net_kw"})   # ENGIE's layout, and the community's own meter beside it
QUARTER = re.compile(r"\d{4}-\d\d-\d\d \d\d:(00|15|30|45)$")
ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$")
SOC_LOW, SOC_HIGH = 10.0, 90.0          # the referee's band for a battery's charge
STUCK = 4                               # the same power this many quarter hours running, and not zero, reads as a stuck value
TEXT_MAX = 400                          # a report's line is short. A longer one is cut where it is kept, and is never read as an instruction


def is_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v == v and abs(v) != float("inf")


def row_faults(row: Any, community_id: str, limit_out_kw: float | None, before: list[dict[str, Any]], asked: dict[str, float] | None = None) -> tuple[list[str], list[str]]:
    """One report row against what needs only the row. Returns (why it can't be kept at all, what is wrong with a row that is kept).
    `before`: this community's kept rows so far, in time order. `asked`: what this participant was asked to give, kW by quarter hour, where a request is in force.
    A participant that follows a flat request sends out the same power quarter hour after quarter hour (a battery in the dark has nothing else moving), so the same power
    is not held against it while it is asked for the same amount throughout: an honest site that does as asked is not distrusted for it."""
    if not isinstance(row, dict) or set(row) - ROW or not {"entity_id", "timestamp"} <= set(row):
        return ["not a report row"], []
    if row["entity_id"] != community_id:
        return ["the row is for another community"], []
    ts = row["timestamp"]
    if not (isinstance(ts, str) and QUARTER.match(ts)):
        return ["the row's time is not a quarter hour"], []
    net, soc, price = row.get("reported_p_net_kw"), row.get("reported_soc_percent"), row.get("quote_price_usd_kwh")
    if any(v is not None and not is_number(v) for v in (net, soc, price, row.get("meter_p_net_kw"))) or not isinstance(row.get("text", ""), str):
        return ["the row holds something that is not a number where a number goes"], []
    flags = []
    if soc is not None and not SOC_LOW <= soc <= SOC_HIGH:
        flags.append(f"charge outside {SOC_LOW:.0f} to {SOC_HIGH:.0f}%")
    if net is not None and limit_out_kw is not None and net > limit_out_kw * 1.001:
        flags.append("more sent out than the connection allows")
    last = [r for r in before if r["timestamp"] < ts][-(STUCK - 1):]
    if net is not None and abs(net) > 1e-9 and len(last) == STUCK - 1 and all(r.get("reported_p_net_kw") == net for r in last) \
            and [r["timestamp"] for r in last] == [beckn.add_minutes(ts, -15 * k) for k in range(STUCK - 1, 0, -1)]:
        flat = [(asked or {}).get(t) for t in [r["timestamp"] for r in last] + [ts]]
        if not (flat[0] and all(v == flat[0] for v in flat)):          # not while it is asked for one and the same amount in all of them
            flags.append(f"the same power {STUCK} quarter hours running")
    return [], flags


class Aggregator:
    def __init__(self) -> None:
        c = self.cfg = config.load()
        self.name = c.get("agent_name") or "aggregator"
        self.key = signing.load_or_create(config.CONFIG_DIR / "secrets" / "aggregator.key")
        self.pub = signing.public_hex(self.key)
        tok = config.secret("town_token")
        self.town = TownSession(c["town_url"], c["town_run_id"], self.name, tok) if c.get("town_run_id") and tok else None
        self.clock = Replay(c["clock_profile"], c["replay_start"], c["replay_step_seconds"], c["replay_loop_days"])
        self.communities: dict[str, dict[str, Any]] = {}
        for name, d in (c.get("aggregator_communities") or {}).items():
            if not (ID.match(str(name)) and isinstance(d, dict) and isinstance(d.get("id"), str) and ID.match(d["id"])
                    and (d.get("limit_out_kw") is None or is_number(d["limit_out_kw"]) and d["limit_out_kw"] > 0)
                    and (d.get("public_key") is None or isinstance(d["public_key"], str) and re.fullmatch(r"[0-9a-f]{64}", d["public_key"]))):
                raise ValueError(f"aggregator_communities: {name!r} is not a community's id, the limit at its connection and, if enrolled with one, its key")
            self.communities[str(name)] = {"id": d["id"], "limit_out_kw": d.get("limit_out_kw"), "public_key": d.get("public_key")}
        self.plan: list[dict[str, Any]] = []
        for r in c.get("aggregator_requests") or []:
            if not (isinstance(r, dict) and isinstance(r.get("id"), str) and ID.match(r["id"]) and r.get("to") in self.communities and isinstance(r.get("made_at"), str)
                    and isinstance(r.get("rows"), list) and r["rows"]):
                raise ValueError("aggregator_requests: each is an id, the community it goes to, when it is made and its rows")
            self.plan.append(r)
        if len({r["id"] for r in self.plan}) != len(self.plan):
            raise ValueError("aggregator_requests: two requests share an id")
        self.lock = threading.RLock()
        self.pins: dict[str, str] = {}                       # a community enrolled without a key: its first signed message pins it
        self.sent: dict[str, dict[str, Any]] = {}            # request id -> when it went out and to whom
        self.answers: dict[str, dict[str, Any]] = {}         # request id -> the community's signed answer
        self.rows: dict[str, list[dict[str, Any]]] = {n: [] for n in self.communities}     # kept report rows, by community, in time order
        self.flags: list[dict[str, Any]] = []                # what was wrong with a row that was kept
        self.refused: dict[str, int] = {}                    # messages not kept, by reason. Their content is not kept either
        self.events: list[dict[str, Any]] = []
        self.poller: InboxPoller | None = None
        self.started = not c.get("aggregator_waits_for_start", True)   # a replayed day: the play's clock has been set

    # ------------------------------------------------------------------ helpers
    def now(self) -> str:
        return self.clock.ts(self.clock.current())

    def event(self, kind: str, **detail: Any) -> None:
        self.events = (self.events + [{"at": time.time(), "sim": self.now(), "kind": kind, **detail}])[-300:]
        log.info("%s %s", kind, str(detail)[:300])

    def _no(self, why: str) -> beckn.Refused:
        self.refused[why] = self.refused.get(why, 0) + 1
        return beckn.Refused(f"rejected: {why}")

    def key_of(self, sender: str, body: dict[str, Any]) -> str:
        """The key a community's messages must verify under: its enrolled key, or the key pinned from its first good message, or (for the
        first message of a community enrolled without one) the key it claims, which is pinned only once that message verifies under it."""
        com = self.communities[sender]
        if com["public_key"]:
            return com["public_key"]
        if sender in self.pins:
            return self.pins[sender]
        return body["signer"] if isinstance(body.get("signer"), str) else ""

    def pin(self, sender: str, body: dict[str, Any]) -> None:
        """After a message has verified: a community enrolled without a key is held to the one it signed with, from now on."""
        if not self.communities[sender]["public_key"] and sender not in self.pins:
            self.pins[sender] = body["signer"]

    # ------------------------------------------------------------------ the request, at its time
    def request_body(self, r: dict[str, Any]) -> dict[str, Any]:
        com = self.communities[r["to"]]
        return beckn.make("request", sender=self.name, receiver=r["to"], transaction_id=r["id"], key=self.key, sender_role="bap", message_id=f"{self.name}:{r['to']}:request:{r['id']}",
                          message={"request": {"id": r["id"], "community": com["id"], "made_at": r["made_at"], "rows": r["rows"]}})

    def tick(self) -> None:
        now = self.now()
        for r in self.plan:
            with self.lock:
                if r["id"] in self.sent or not self.started or now < r["made_at"][:16] or self.town is None:
                    continue
                body = self.request_body(r)
                try:
                    out = self.town.send(r["to"], REQUEST, body, body["context"]["messageId"])
                except Exception as exc:                          # tried again on the next tick
                    self.event("request_not_sent", request=r["id"], error=str(exc)[:160])
                    continue
                self.sent[r["id"]] = {"to": r["to"], "at": now, "made_at": r["made_at"], "rows": len(r["rows"]), "wall": time.time(), "town": "duplicate" if isinstance(out, dict) and out.get("duplicate") else "accepted"}
                wire.note("send", self.name, r["to"], "request", body, sim=now)
                self.event("request_sent", request=r["id"], to=r["to"], rows=len(r["rows"]))

    def tick_loop(self) -> None:
        while True:
            try:
                self.tick()
            except Exception:
                log.error("tick: %s", traceback.format_exc())
            time.sleep(0.25)

    # ------------------------------------------------------------------ what comes back
    def take(self, kind: str, sender: str, body: Any) -> str:
        """One message from a community, checked before anything of it is kept."""
        with self.lock:
            if sender not in self.communities:
                return self._no("not a community on this aggregator's list")
            if not isinstance(body, dict) or not isinstance(body.get("context"), dict) or not isinstance(body.get("message"), dict):
                return self._no("not a signed message")
            ctx, act = body["context"], str(body["context"].get("action"))
            if not beckn.check(body, self.key_of(sender, body)):
                wire.note("recv", sender, self.name, act, body, ok=False, sim=self.now())
                return self._no("bad signature")
            self.pin(sender, body)
            wire.note("recv", sender, self.name, act, body, sim=self.now())
            if ctx.get("bppId") != sender or ctx.get("bapId") != self.name:
                return self._no("not made for this aggregator")
            com, m = self.communities[sender], body["message"]
            if kind == ANSWER and act == "on_request":
                a = m.get("answer")
                rid = a.get("request") if isinstance(a, dict) else None
                if not isinstance(a, dict) or rid not in self.sent or self.sent[rid]["to"] != sender or a.get("community") != com["id"] or not isinstance(a.get("taken"), bool):
                    return self._no("an answer to nothing this aggregator asked")
                if rid in self.answers:
                    return "answer noted before"
                self.answers[rid] = {"from": sender, "taken": a["taken"], "rows": a.get("rows") if is_number(a.get("rows")) else None, "too_late": a.get("too_late") if is_number(a.get("too_late")) else None,
                                     "first": str(a.get("first") or "")[:16] or None, "last": str(a.get("last") or "")[:16] or None, "why": str(a.get("why") or "")[:200] or None, "at": str(a.get("at") or "")[:16] or None,
                                     "heard_at": self.now()}
                self.event("answer", request=rid, taken=a["taken"])
                return f"answer noted: {'taken' if a['taken'] else 'refused'}"
            if kind == REPORT and act == "report":
                row = m.get("report")
                asked = {str(x.get("ts"))[:16]: float(x["battery_kw"]) for r in self.plan if r["to"] == sender and r["id"] in self.sent for x in r["rows"] if is_number(x.get("battery_kw"))}     # what this participant was asked: doing as a flat request says is not a stuck report
                bad, flags = row_faults(row, com["id"], com["limit_out_kw"], self.rows[sender], asked)
                if bad:
                    return self._no(bad[0])
                same = next((r for r in self.rows[sender] if r["timestamp"] == row["timestamp"]), None)
                if same is not None:
                    if {k: same.get(k) for k in ROW} == {k: (str(row.get(k))[:TEXT_MAX] if k == "text" and row.get(k) is not None else row.get(k)) for k in ROW}:
                        return "report row noted before"
                    self.flags.append({"community": sender, "timestamp": row["timestamp"], "what": "a second, different row for the same quarter hour: the first stands"})
                    return self._no("a second, different row for the same quarter hour")
                kept = {k: row.get(k) for k in ROW}
                if kept["text"] is not None:
                    kept["text"] = str(kept["text"])[:TEXT_MAX]
                self.rows[sender] = sorted(self.rows[sender] + [kept], key=lambda r: r["timestamp"])[-96 * 14:]
                self.flags += [{"community": sender, "timestamp": row["timestamp"], "what": f} for f in flags]
                return "report row noted" + (f", {len(flags)} flagged" if flags else "")
            return self._no("unknown kind")

    def handle(self, msg: dict[str, Any]) -> None:
        try:
            text: str = self.take(str(msg.get("kind")), str(msg.get("from")), msg.get("body"))
        except Exception:                                         # one sender's junk must not stop the inbox
            log.error("inbox: %s", traceback.format_exc())
            text = self._no("that message can't be read")
        status, note = beckn.ack_of(text, 300, "result")
        self.town.ack(msg["message_id"], msg["fence"], status, note)

    def inbox_loop(self) -> None:
        cfg = self.cfg
        self.poller = InboxPoller(self.town, self.handle, every=float(cfg.get("town_poll_seconds", 1.0)), idle_every=float(cfg.get("town_poll_idle_seconds", 3.0)),
                                  claimers=1, on_error=lambda where, exc: self.event("town_error", error=f"{where}: {str(exc)[:200]}"))
        self.poller.run()

    def view(self) -> dict[str, Any]:
        with self.lock:
            return {"agent": self.name, "pubkey": self.pub, "now": self.now(), "stand_in": True,
                    "communities": {n: {"id": c["id"], "limit_out_kw": c["limit_out_kw"], "key": "enrolled" if c["public_key"] else "pinned at its first message" if n in self.pins else "none yet",
                                        "report_rows": len(self.rows[n]), "first": self.rows[n][0]["timestamp"] if self.rows[n] else None, "last": self.rows[n][-1]["timestamp"] if self.rows[n] else None}
                                    for n, c in self.communities.items()},
                    "requests": [{"id": r["id"], "to": r["to"], "made_at": r["made_at"], "rows": len(r["rows"]), "sent": self.sent.get(r["id"]), "answer": self.answers.get(r["id"])} for r in self.plan],
                    "flags": list(self.flags[-200:]), "flagged": len(self.flags), "not_kept": dict(self.refused)}


def build_app(a: Aggregator):
    from fastapi import Body, FastAPI, HTTPException

    app = FastAPI(title="murmur-aggregator", version="0.1.0", dependencies=[doors.door()])

    @app.get("/health")
    def health():
        return {"ok": True, "agent": a.name, "pubkey": a.pub, "now": a.now(), "label": "Aggregator (stand-in)", "town": a.town is not None, "doors": doors.state(),
                "town_calls": a.poller.stats() if a.poller else None}

    @app.get("/aggregator")
    def view():
        return a.view()

    @app.get("/aggregator/rows")
    def rows(community: str, n: int = 2000):
        if community not in a.rows:
            raise HTTPException(404, "no such community on this aggregator's list")
        with a.lock:
            return {"community": community, "rows": a.rows[community][-max(1, min(int(n), 2000)):]}

    @app.post("/demo/reset")
    def demo_reset(body: dict = Body(default={})):
        """A new play starts: what was asked and heard in the last one is put away. Its list of requests stays."""
        with a.lock:
            a.sent.clear(); a.answers.clear(); a.flags.clear(); a.refused.clear()
            a.rows = {n: [] for n in a.communities}
            a.started = not a.cfg.get("aggregator_waits_for_start", True)
        return {"ok": True}

    @app.get("/demo/clock")
    def demo_clock_get():
        return a.clock.clock()

    @app.post("/demo/clock")
    def demo_clock(body: dict = Body(default={})):
        a.clock.configure(body.get("start", a.clock.start), float(body.get("step_seconds", a.clock.step_seconds)), int(body.get("loop_days", a.clock.loop_days)), body.get("at"), body.get("at_wall"),
                          hold=bool(body.get("hold")))
        a.started = True
        return a.clock.clock()

    return app


def main() -> None:
    ap = argparse.ArgumentParser(prog="murmur-aggregator")
    ap.add_argument("cmd", choices=["run", "pubkey"])
    args = ap.parse_args()
    if args.cmd == "pubkey":
        print(signing.public_hex(signing.load_or_create(config.CONFIG_DIR / "secrets" / "aggregator.key")))
        return
    import uvicorn
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    a = Aggregator()
    if not a.cfg.get("aggregator_port"):
        raise SystemExit("murmur-aggregator: no aggregator_port in its config, and it takes no port it wasn't given")
    if a.town is None:
        raise SystemExit("murmur-aggregator: no message-bus run or token in its config")
    logs = config.log_dir()
    logs.mkdir(exist_ok=True)
    wire.open_log(str(logs / "town_wire_aggregator.jsonl"))
    a.town.join_until_up(then=lambda: threading.Thread(target=a.inbox_loop, daemon=True).start(), log=lambda m: (print(m, flush=True), a.event("town_error", error=m)))
    threading.Thread(target=a.tick_loop, daemon=True).start()
    uvicorn.run(build_app(a), host=a.cfg["bind_host"], port=int(a.cfg["aggregator_port"]), log_level="warning")


if __name__ == "__main__":
    main()
