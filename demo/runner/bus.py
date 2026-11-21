"""A local message bus with the HTTP contract the participants speak (version 0.2.0), for a demo on one machine and for the tests.

  POST /runs/{run}/join          {"name", "token"} or {"name", "grant", "grant_signature", "session_proof"}  -> {"session"}
  POST /runs/{run}/messages      {"message_id", "to", "kind", "body"}: one id, one body. The same body again is a replay; another body under a
                                 taken id is refused (409) and goes nowhere
  GET  /runs/{run}/inbox/notify  {"hint": true} while the inbox holds a message to hand out (never a held long-poll)
  POST /runs/{run}/inbox/claim   the oldest message, leased with a fence (204 when there is none); a lease that runs out hands it out again
  POST /runs/{run}/inbox/ack     {"message_id", "fence", "status", "note"}: done; a stale fence is refused (409)
  GET  /runs/{run}/record        every accepted message and every ack, for a person or a feed to read

A grant is the one grants.py makes: {"agent_id", "run_id", "session_public", "permissions", "issued_at", "expires_at"}, signed by the
name's controller key, which the run pins; the session proves it holds the private half by signing {"purpose": "join", "run_id",
"name"}. Every route but join and record needs the X-Town-Session header.

runs_from({"run_id", "tokens", "controllers"}) makes the runs a bus serves from the file the runner writes (bus.json).
"""
from __future__ import annotations

import json
import secrets
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from fastapi import Body, FastAPI, Header, HTTPException, Response

from . import grants

LEASE_S = 30.0


def canonical(x: Any) -> str:
    return json.dumps(x, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


@dataclass
class Run:
    run_id: str
    tokens: dict[str, str] = field(default_factory=dict)       # name -> join token
    controllers: dict[str, str] = field(default_factory=dict)  # name -> the pinned controller public key (hex) that signs its grants
    lease_s: float = LEASE_S
    sessions: dict[str, str] = field(default_factory=dict)     # session -> name
    messages: dict[str, dict[str, Any]] = field(default_factory=dict)
    inbox: dict[str, deque] = field(default_factory=dict)      # name -> message ids, oldest first
    record: list[dict[str, Any]] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def join(self, req: dict[str, Any]) -> str:
        name = str(req.get("name") or "")
        if req.get("grant") is not None:
            try:
                grants.verify(req["grant"], str(req.get("grant_signature") or ""), self.controllers.get(name, ""), self.run_id, name,
                              str(req.get("session_proof") or ""))
            except grants.Refused as exc:
                raise HTTPException(403, f"the grant doesn't hold for this name on this run: {exc}") from None
        elif not name or self.tokens.get(name) is None or not secrets.compare_digest(self.tokens[name], str(req.get("token") or "")):
            raise HTTPException(403, "unknown name or token")
        with self.lock:
            for s in [s for s, n in self.sessions.items() if n == name]:     # a join ends the name's earlier session
                del self.sessions[s]
            session = secrets.token_hex(16)
            self.sessions[session] = name
            self.inbox.setdefault(name, deque())
        return session

    def who(self, session: str | None) -> str:
        name = self.sessions.get(session or "")
        if name is None:
            raise HTTPException(401, "no such session")
        return name

    def send(self, sender: str, req: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        mid, to, body = str(req.get("message_id") or ""), str(req.get("to") or ""), req.get("body")
        if not mid or not to:
            raise HTTPException(400, "a message needs message_id and to")
        with self.lock:
            had = self.messages.get(mid)
            if had is not None:                       # a replay is the same message again: sender, receiver, kind and body
                if had["from"] == sender and had["to"] == to and had["kind"] == str(req.get("kind") or "") and canonical(had["body"]) == canonical(body):
                    return 200, {"message_id": mid, "accepted": True, "replay": True}
                return 409, {"message_id": mid, "accepted": False, "why": "this id holds another message"}
            self.messages[mid] = {"message_id": mid, "from": sender, "to": to, "kind": str(req.get("kind") or ""), "body": body, "state": "queued",
                                  "fence": "", "lease_until": 0.0, "at": time.time()}
            self.inbox.setdefault(to, deque()).append(mid)
            self.record.append({"event": "accepted", "message_id": mid, "from": sender, "to": to, "kind": req.get("kind"), "body": body, "at": time.time()})
        return 200, {"message_id": mid, "accepted": True, "replay": False}

    def _ready(self, name: str) -> list[dict[str, Any]]:
        now = time.time()
        return [m for m in (self.messages[i] for i in self.inbox.get(name, ())) if m["state"] == "queued" or (m["state"] == "leased" and m["lease_until"] < now)]

    def notify(self, name: str) -> bool:
        with self.lock:
            return bool(self._ready(name))

    def claim(self, name: str) -> dict[str, Any] | None:
        with self.lock:
            ready = self._ready(name)
            if not ready:
                return None
            m = ready[0]
            m.update(state="leased", fence=secrets.token_hex(8), lease_until=time.time() + self.lease_s)
            return {k: m[k] for k in ("message_id", "kind", "body", "fence")} | {"from": m["from"], "to": m["to"]}

    def ack(self, name: str, req: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        with self.lock:
            m = self.messages.get(str(req.get("message_id") or ""))
            if m is None or m["to"] != name or m["state"] != "leased" or m["fence"] != req.get("fence"):
                return 409, {"stale_fence": True}
            m["state"] = "done"
            self.inbox[name].remove(m["message_id"])
            self.record.append({"event": "ack", "message_id": m["message_id"], "by": name, "status": req.get("status"), "note": req.get("note") or {}, "at": time.time()})
        return 200, {"ok": True}


def runs_from(spec: dict[str, Any]) -> dict[str, Run]:
    """The one run a runner's bus.json describes: its id, each name's join token and each name's pinned controller key."""
    run = Run(str(spec["run_id"]), tokens=dict(spec.get("tokens") or {}), controllers=dict(spec.get("controllers") or {}))
    return {run.run_id: run}


def make_bus(runs: dict[str, Run]) -> FastAPI:
    app = FastAPI(title="murmur-bus", version="0.2.0")

    def run_of(run_id: str) -> Run:
        if run_id not in runs:
            raise HTTPException(404, "no such run")
        return runs[run_id]

    @app.get("/health")
    def health():
        return {"ok": True, "runs": sorted(runs)}

    @app.post("/runs/{run_id}/join")
    def join(run_id: str, body: dict = Body(...)):
        return {"session": run_of(run_id).join(body)}

    @app.post("/runs/{run_id}/messages")
    def send(run_id: str, response: Response, body: dict = Body(...), x_town_session: str | None = Header(default=None)):
        r = run_of(run_id)
        code, out = r.send(r.who(x_town_session), body)
        response.status_code = code
        return out

    @app.get("/runs/{run_id}/inbox/notify")
    def notify(run_id: str, wait: float = 0.0, x_town_session: str | None = Header(default=None)):
        r = run_of(run_id)
        return {"hint": r.notify(r.who(x_town_session))}

    @app.post("/runs/{run_id}/inbox/claim")
    def claim(run_id: str, x_town_session: str | None = Header(default=None)):
        r = run_of(run_id)
        m = r.claim(r.who(x_town_session))
        return Response(status_code=204) if m is None else m

    @app.post("/runs/{run_id}/inbox/ack")
    def ack(run_id: str, response: Response, body: dict = Body(...), x_town_session: str | None = Header(default=None)):
        r = run_of(run_id)
        code, out = r.ack(r.who(x_town_session), body)
        response.status_code = code
        return out

    @app.get("/runs/{run_id}/record")
    def record(run_id: str, after: int = 0):
        r = run_of(run_id)
        with r.lock:
            return {"events": r.record[after:], "next": len(r.record)}

    return app
