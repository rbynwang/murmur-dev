"""The control door: every POST to a service asks for the token in secrets/control_token, once that file exists.

The token says "one of this system's own tools". It frees no alarm and raises no limit: those take a person's signed word
(murmur.node.person). With no file nothing is asked: a test or a local run has none. /health says which ("token" or "open").
"""
import hmac
import logging
import secrets
import threading
from typing import Any

from murmur import config

log = logging.getLogger("murmur.protocol.doors")
HEADER, TOKEN_FILE = "X-Murmur-Token", "control_token"
READS = ("GET", "HEAD", "OPTIONS")       # what changes nothing: nothing is asked of these
_write = threading.Lock()                # one read-and-write at a time. Each is a person's word or an alarm, so nothing waits long


def token() -> str | None:
    """The control token, or None when this machine has none. A file that's there but empty or unreadable shuts every door: someone meant to turn them on."""
    try:
        return (config.CONFIG_DIR / "secrets" / TOKEN_FILE).read_text().strip()
    except FileNotFoundError:
        return None
    except (OSError, UnicodeDecodeError) as exc:
        log.error("the control token can't be read, so every door stays shut: %s", exc)
        return ""


def headers() -> dict[str, str]:
    """What a call to a control door sends, for this system's own services and nothing else: Town and the model never see this."""
    t = token()
    return {HEADER: t} if t else {}


def state() -> str:
    return "open" if token() is None else "token"


def door() -> Any:
    """One line per service, FastAPI(dependencies=[doors.door()]), so a route added later is covered too. It's read on each POST, and a POST is rare."""
    from fastapi import Depends, HTTPException, Request

    def asked(request: Request) -> None:
        want = None if request.method in READS else token()
        if want is None:
            return
        if not want or not hmac.compare_digest(request.headers.get(HEADER, "").encode("utf-8", "replace"), want.encode()):
            raise HTTPException(401, f"This door needs the control token, in the {HEADER} header.")
    return Depends(asked)
