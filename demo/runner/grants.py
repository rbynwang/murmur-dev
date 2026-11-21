"""Run grants, in the form the message network's HTTP contract (version 0.2.0) uses for a join without a token.

Each participant has a controller key that stays with the runner. For one run it signs a grant
{"agent_id", "run_id", "session_public", "permissions", "issued_at", "expires_at"} naming a fresh session key; only the
session's private half goes to the participant, which proves it holds it by signing {"purpose": "join", "run_id", "name"}
(protocol.transport.join_proof). The bus pins each name's controller public key and checks the whole chain at the join.

  Controllers(folder)   one controller key per name, made on first use and kept in the folder (mode 600)
  verify(...)           raises Refused unless the grant holds for this name on this run, now
"""
from __future__ import annotations

import hashlib
import math
import time
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from murmur.protocol.signing import canonical, load_or_create, public_hex

PERMISSIONS = ["ack", "claim", "join", "send"]
TTL_S = 3600.0


class Refused(ValueError):
    """The grant doesn't hold: wrong run, bad permissions, expired, not signed by the pinned controller, or no session proof."""


def agent_id(public: str) -> str:
    return "did:town:" + hashlib.sha256(canonical(public).encode()).hexdigest()[:24]


def _private_hex(key: Ed25519PrivateKey) -> str:
    return key.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption()).hex()


def _signed(public: str, payload: Any, signature: str) -> bool:
    try:
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(public)).verify(bytes.fromhex(signature), canonical(payload).encode())
        return True
    except (InvalidSignature, ValueError, TypeError):
        return False


class Controllers:
    """The runner's controller keys, one file per participant name in its folder."""

    def __init__(self, folder: Path):
        self.folder = Path(folder)

    def key(self, name: str) -> Ed25519PrivateKey:
        return load_or_create(self.folder / f"{name}.controller.key")

    def public(self, name: str) -> str:
        return public_hex(self.key(name))

    def pinned(self, names: list[str]) -> dict[str, str]:
        """name -> controller public key (hex), for the bus."""
        return {n: self.public(n) for n in names}

    def grant(self, name: str, run_id: str, ttl_s: float = TTL_S, now: float | None = None) -> dict[str, Any]:
        """What one participant holds for one run: the grant, its signature and the session's private key."""
        key, session = self.key(name), Ed25519PrivateKey.generate()
        now = time.time() if now is None else now
        grant = {"agent_id": agent_id(public_hex(key)), "run_id": run_id, "session_public": public_hex(session), "permissions": list(PERMISSIONS),
                 "issued_at": now, "expires_at": now + ttl_s}
        return {"grant": grant, "grant_signature": key.sign(canonical(grant).encode()).hex(), "session_private": _private_hex(session)}


def _when(value: Any, what: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise Refused(f"the grant's {what} is not a time")
    return float(value)


def verify(grant: Any, signature: str, controller: str, run_id: str, name: str, proof: str, now: float | None = None) -> None:
    now = time.time() if now is None else now
    if not isinstance(grant, dict) or grant.get("run_id") != run_id:
        raise Refused("the grant names another run")
    permissions = grant.get("permissions")
    if not isinstance(permissions, list) or not all(isinstance(p, str) for p in permissions):
        raise Refused("the grant's permissions are not a list of names")
    _when(grant.get("issued_at"), "issued_at")
    if now > _when(grant.get("expires_at"), "expires_at"):
        raise Refused("the grant has expired")
    if not controller or not _signed(controller, grant, signature):
        raise Refused("the grant is not signed by this name's controller")
    if not _signed(str(grant.get("session_public") or ""), {"purpose": "join", "run_id": run_id, "name": name}, proof):
        raise Refused("the session proof does not match the grant's session key")
