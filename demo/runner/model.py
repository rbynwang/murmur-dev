"""A stand-in model server for a demo or a check without a language model. It answers the chat endpoint the nodes call
(POST /api/chat, the Ollama wire form) at once, and nothing it says decides an amount: code plans every amount, and the model
is asked only to read an owner's note and to word a report.

  a note     set_owner_wish with the need the note's words name (battery, car, cooling), until tonight if the note says
             tonight; no_wish when it names none
  a report   file_report with two plain sentences and no numbers
  any other  no_action with a reason when it is offered, else the first tool with allowed values

  python -m demo.runner.model [--host 127.0.0.1] --port 0 [--ms 50] [--log FILE]      prints "listening on PORT" once it is up
"""
from __future__ import annotations

import argparse
import json
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

NAME = "stand-in"
REPORT = "The sale ran as the plan said. Nothing went wrong that the facts show."


def fill(schema: dict[str, Any], hints: dict[str, Any]) -> dict[str, Any]:
    """Every required field of a tool's parameters, with an allowed value."""
    out: dict[str, Any] = {}
    props = schema.get("properties") or {}
    for k in schema.get("required") or list(props):
        v = props.get(k) or {}
        if k in hints:
            out[k] = hints[k]
        elif v.get("enum"):
            out[k] = v["enum"][0]
        elif v.get("type") in ("number", "integer"):
            out[k] = v.get("minimum", 0) if v.get("minimum", 0) > 0 else 1.0
        elif v.get("type") == "boolean":
            out[k] = True
        elif v.get("type") == "array":
            out[k] = []
        else:
            out[k] = NAME
    return out


def note_call(text: str) -> dict[str, Any]:
    low = text.lower()
    wish = ("keep_battery_full" if "battery" in low else "keep_house_as_is" if "chiller" in low or "cooling" in low else
            "keep_car_ready" if re.search(r"\bcar\b", low) else None)
    if wish is None:
        return {"name": "no_wish", "arguments": {}}
    return {"name": "set_owner_wish", "arguments": {"wish": wish, "by": "", "until": "tonight" if "tonight" in low else ""}}


def answer(tools: list[dict[str, Any]], text: str) -> tuple[str, dict[str, Any]]:
    """(what was asked, the one tool call that answers it)."""
    by = {t["function"]["name"]: t["function"] for t in tools}
    if "set_owner_wish" in by:
        return "note", note_call(text)
    if "file_report" in by:
        return "report", {"name": "file_report", "arguments": {"summary": REPORT}}
    if "no_action" in by:
        args = fill(by["no_action"].get("parameters") or {}, {"reason": "Nothing here needs a change, so code's plan stands."})
        return "nothing", {"name": "no_action", "arguments": args}
    first = next(iter(by.values()))
    return "first", {"name": first["name"], "arguments": fill(first.get("parameters") or {}, {"reason": NAME})}


class StandIn(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, port: int, ms: float = 50.0, log: str = "", host: str = "127.0.0.1"):
        super().__init__((host, port), Handler)
        self.ms, self.log = ms, log
        self.counts: dict[str, int] = {"chat": 0}
        self.lock = threading.Lock()

    def count(self, kind: str, t0: float) -> None:
        with self.lock:
            self.counts["chat"] += 1
            self.counts[kind] = self.counts.get(kind, 0) + 1
            if self.log:
                with open(self.log, "a", encoding="utf-8") as f:
                    f.write(json.dumps({"wall": round(t0, 3), "kind": kind, "ms": round(1000 * (time.time() - t0))}) + "\n")


class Handler(BaseHTTPRequestHandler):
    server: StandIn

    def log_message(self, *args: Any) -> None:
        return

    def reply(self, body: dict[str, Any]) -> None:
        data = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        self.reply({"models": [{"name": NAME, "digest": NAME}], "version": NAME, "chat": self.server.counts["chat"]})

    def do_POST(self) -> None:
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        t0 = time.time()
        time.sleep(self.server.ms / 1000)
        text = " ".join(str(m.get("content") or "") for m in body.get("messages") or [])
        if body.get("tools"):
            kind, call = answer(body["tools"], text)
            message = {"role": "assistant", "content": "", "tool_calls": [{"function": call}]}
        else:
            kind, message = "text", {"role": "assistant", "content": "The sale ran as the plan said."}
        self.server.count(kind, t0)
        self.reply({"message": message, "prompt_eval_count": 100, "eval_count": 10, "done": True})


def main() -> None:
    ap = argparse.ArgumentParser(description="a stand-in model server")
    ap.add_argument("--host", default="127.0.0.1", help="the address it listens on")
    ap.add_argument("--port", type=int, default=0, help="0 takes a free port")
    ap.add_argument("--ms", type=float, default=50.0, help="how long each answer takes")
    ap.add_argument("--log", default="", help="a file to log one line per answer to")
    a = ap.parse_args()
    server = StandIn(a.port, a.ms, a.log, a.host)
    print(f"listening on {server.server_address[1]}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
