"""The wire log: one JSON line per signed message a service sends or receives, for a person to read the evening back."""
from __future__ import annotations

import json
import threading
import time
from typing import Any

_path: str | None = None
_lock = threading.Lock()


def open_log(path: str) -> None:
    global _path
    _path = path


def note(direction: str, frm: str, to: str, action: str, body: dict[str, Any], ok: bool = True,
         sim: str | None = None) -> None:
    if not _path:
        return
    try:
        ctx = body.get("context") or {}
        rec = {"t": round(time.time(), 3), "dir": direction, "from": frm, "to": to, "action": action, "ok": ok,
               "sim": sim, "mid": ctx.get("messageId"), "signer": str(body.get("signer") or "")[:16],
               "sig": str(body.get("sig") or "")[:16], "sent": ctx.get("sentWall"), "message": body.get("message")}
        line = json.dumps(rec, separators=(",", ":"), default=str) + "\n"
        with _lock, open(_path, "a") as f:
            f.write(line)
    except Exception:
        pass
