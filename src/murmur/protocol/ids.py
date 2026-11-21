"""Message ids: one logical message, one id. A retry or a redelivery names a message again with the same id, and so does an answer made again
after a restart, so the bus takes it once; a message nobody asked for takes its id from the sender's key, its play and what the message is.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from murmur.protocol import signing


def new_play() -> str:
    """A new tag: a sender's first, and at each /demo/start or /demo/reset. Nobody else needs to know it: every id names its sender, so each sender's tag only has to change."""
    return uuid.uuid4().hex[:8]


def digest(*parts: Any) -> str:
    """A short stable name for what a message says. Nothing here is secret: it keeps ids short and tells two different things apart."""
    return hashlib.sha1(json.dumps(parts, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()[:10]


def message_id(scope: str, sender: str, to: str, kind: str, *key: Any) -> str:
    return ":".join(str(x) for x in (scope, sender, to, kind.removeprefix("beckn."), *key))


def sealed(key: Any, scope: str, sender: str, to: str, kind: str, *more: Any) -> str:
    """The id of a message nobody asked for. It's a pure function of the sender's key file, its play and what the message is, so a retry in the same play names it again
    and nobody else can name it first. The sender holds its play in memory: a new one at each start and at each reset. key None: a message that needs no seal, as an
    answer doesn't."""
    plain = message_id(scope, sender, to, kind, *more)
    return f"{plain}:{signing.seal(key, plain)}" if key is not None else plain


def asked(body: Any) -> str:
    """The scope of an answer: the message it answers. Its messageId stays the same however often Town hands it out, and is new when the asker asks again."""
    ctx = body.get("context") if isinstance(body, dict) else None
    made = ctx.get("messageId") if isinstance(ctx, dict) else None
    return "a" + digest(made if made else body)


def readings(bodies: list[Any]) -> str:
    """The name of a batch: the readings in it, whatever order they were held in. The same slots sent again after a restart are the same batch."""
    def one(b: Any) -> tuple:
        r = ((b.get("message") or {}).get("performance") or {}) if isinstance(b, dict) else {}
        return str(r.get("contract_id")), str(r.get("slot_id"))
    return digest(sorted(one(b) for b in bodies))
