"""A person's word to a node, and what must outlive everything else: the alarm holding it and the limits a person signed.

  book     one small file per node, state/person/<node>.json: the alarm holding it, the limits a person signed, the numbers their messages have
           used. It is written before the door answers, and no restart, new run or set-aside file can take an alarm with it.
  floor    beside it, <node>.floor: when that file was last lost. Its numbers went with it, so from then on a word's number must be later than this.

Only a person's signed word ends an alarm, so a deployed node needs a person's public key in its agent.json. What a deploy runs, each in its
own configuration folder ($MURMUR_CONFIG_DIR):

  python -m murmur.node.person token                              makes secrets/control_token, if there's none
  python -m murmur.node.person key owner                          makes secrets/person_owner.key, if there's none, and prints the public half
  python -m murmur.node.person trust owner <public key>           on a node's machine: person_keys in its agent.json
  python -m murmur.node.person word home-01 clear_alarm --url URL  a person's signed word, sent to the node's host
  python -m murmur.node.person word home-01 set_limit --group hvac_zones --name max_rise_c --value 1.5 --url URL

None of these prints a token or a private key.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import sys
import time
from pathlib import Path
from typing import Any

from murmur import config
from murmur.protocol.doors import TOKEN_FILE, _write, headers, log, token

def book_path(node: str) -> Path:
    return config.state_dir() / "person" / f"{node}.json"

def floor_path(node: str) -> Path:
    return book_path(node).with_suffix(".floor")

def floor(node: str) -> int:
    """No number at or below this is taken on this node: the moment its file was lost, in the milliseconds a word's number counts in. 0 if it never was."""
    try:
        return int(floor_path(node).read_text().strip())
    except (OSError, ValueError):
        return 0

def lost(node: str) -> None:
    """This node's file couldn't be read, and the numbers it held went with it. Any word signed before now could have been used already, so none is taken from now on: a person signs
    again. On a code-only node the file is the only copy of those numbers: without the floor, a clear signed earlier could free a newer alarm."""
    from murmur.files import write_atomic
    try:
        write_atomic(floor_path(node), str(max(floor(node), int(time.time() * 1000))).encode())
    except OSError as exc:                                 # a second fault at once: it's in the log, and the node is held all the same
        log.error("%s: the floor for a person's numbers can't be written: %s", node, exc)

def book(node: str) -> dict[str, Any] | None:
    """What this node's file says, or None if it has none. A file that can't be read is moved aside and comes back as {"bad": why}: it may have held an alarm, so the caller holds the node.
    Its numbers went with it, so lost() sets the floor."""
    p = book_path(node)
    try:
        d = json.loads(p.read_text())
        limits = d.get("limits", {}) if isinstance(d, dict) else None
        if not isinstance(d, dict) or not isinstance(d.get("seq", {}), dict) or not all(isinstance(v, int) for v in d.get("seq", {}).values()) \
                or not isinstance(limits, dict) or not all(isinstance(x, dict) and all(isinstance(v, (int, float)) for v in x.values()) for x in limits.values()):
            raise ValueError("not this file's shape")
        return d
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        try:
            p.replace(p.with_suffix(".bad"))
        except OSError:
            pass
        lost(node)
        log.error("%s: a person's file can't be read: %s", node, exc)
        return {"bad": f"{type(exc).__name__}: {str(exc)[:120]}"}

def limit_said(node: str, msg: dict[str, Any]) -> dict[str, Any]:
    """A signed set_limit that went through, as a change to note(): {"limits": ...} with this one on top of what the file holds. Nothing for any other word."""
    if msg.get("verb") != "set_limit":
        return {}
    limits = (book(node) or {}).get("limits") or {}
    return {"limits": {**limits, msg["group"]: {**limits.get(msg["group"], {}), msg["name"]: msg["value"]}}}

def numbers(node: str, keys: Any = ()) -> dict[str, int]:
    """The last number each signer's key has used on this node. keys: the signers this node takes. Each starts above the floor, if the file was ever lost."""
    seq = dict((book(node) or {}).get("seq") or {})
    low = floor(node)
    return {**seq, **{k: max(int(seq.get(k, 0)), low) for k in keys}} if low else seq

def note(node: str, **changes: Any) -> None:
    """Changes this node's file, on disk when it returns: files.write_atomic, so the file is the old one or the new one, whatever happens. A number only ever goes up."""
    from murmur.files import write_atomic
    with _write:
        d = book(node) or {}
        d.pop("bad", None)
        seq = {**(d.get("seq") or {})}
        for k, v in (changes.pop("seq", None) or {}).items():
            seq[k] = max(int(seq.get(k, 0)), int(v))
        write_atomic(book_path(node), json.dumps({**d, **changes, "seq": seq}, sort_keys=True).encode())

# ---------------------------------------------------------------------- what a deploy and a person run
def key_path(role: str) -> Path:
    return config.CONFIG_DIR / "secrets" / f"person_{role}.key"

def trust(role: str, public: str) -> None:
    """This machine's nodes take this person's word: agent.json's person_keys, and nothing else in the file changes."""
    from murmur.files import write_atomic
    if not re.fullmatch(r"[0-9a-f]{64}", public):
        sys.exit("a public key is 64 hex characters: what `key` printed")
    p = config.CONFIG_DIR / "agent.json"
    cfg = json.loads(p.read_text()) if p.exists() else {}
    write_atomic(p, json.dumps({**cfg, "person_keys": {**(cfg.get("person_keys") or {}), role: public}}, indent=2).encode())

def word(a: argparse.Namespace) -> dict[str, Any]:
    """A person's word, signed here. Its number is the time, so this needs no count of its own and each word goes above the last."""
    import httpx

    from murmur.protocol import signing
    from murmur.node import policy as P
    role = a.role or ("facility_manager" if a.node.startswith("building-") else "owner")
    if not key_path(role).exists():
        sys.exit(f"no key for {role} here: `key {role}` makes one, and `trust` on the node's machine takes it")
    msg = P.signed(signing.load_or_create(key_path(role)), role, a.node, int(time.time() * 1000), a.verb, a.group or P.SITE, a.name, a.value)
    try:
        r = httpx.post(f"{a.url.rstrip('/')}/person/{a.node}", json=msg, headers=headers(), timeout=30)
    except httpx.HTTPError as exc:
        return {"status": "blocked", "why": f"the door didn't answer: {type(exc).__name__}"}
    return r.json() if r.status_code == 200 else {"status": "blocked", "why": f"the door answered {r.status_code}: {r.text[:200]}"}

def main(argv: list[str] | None = None) -> int:
    from murmur.node import policy as P
    ap = argparse.ArgumentParser(prog="python -m murmur.node.person", description="The control token and a person's key. Nothing here prints a secret.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("token", help="make secrets/control_token, if there's none")
    k = sub.add_parser("key", help="make a person's key, if there's none, and print its public half")
    t = sub.add_parser("trust", help="this machine's nodes take this person's word")
    for x in (k, t):
        x.add_argument("role", choices=["owner", "facility_manager"])
    t.add_argument("public_key")
    w = sub.add_parser("word", help="send a person's signed word to a node")
    w.add_argument("node")
    w.add_argument("verb", choices=[v for v in P.PERSON_VERBS if v != "read"])
    w.add_argument("--url", required=True, help="the status API of the node host, for homes or for buildings")
    w.add_argument("--role", choices=["owner", "facility_manager"], help="owner for a home, facility_manager for a building, unless you say")
    w.add_argument("--group", default="")
    w.add_argument("--name", default="")
    w.add_argument("--value", type=float)
    a = ap.parse_args(argv)
    os.umask(0o077)                                      # what's written here is nobody else's, from its first byte
    if a.cmd == "token":
        made = token() is None
        if made:
            config.write_secret(TOKEN_FILE, secrets.token_urlsafe(32))
        print(f"{config.CONFIG_DIR / 'secrets' / TOKEN_FILE}: {'made' if made else 'already there'}")
    elif a.cmd == "key":
        from murmur.protocol import signing
        print(signing.public_hex(signing.load_or_create(key_path(a.role))))
    elif a.cmd == "trust":
        trust(a.role, a.public_key)
        print(f"{a.role} is on file in {config.CONFIG_DIR / 'agent.json'}: nodes here read it at their next start")
    else:
        out = word(a)
        print(json.dumps(out))
        return 0 if out.get("status") == "done" else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
