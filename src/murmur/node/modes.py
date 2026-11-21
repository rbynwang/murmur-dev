"""The node's fixed modes and the model's settings, read from the node's own configuration.

Every node is an agent, and code decides every plan: the model is asked only to read a person's note and to word the report. A note
still sets a wish, the offer leaves out what a wish keeps, and the guard has the last word.

  careful_notes    true: a person's note goes through the careful step (node/note_reader.py)
  llm_temperature  the sampling temperature of every answer; 0 for runs that must repeat
  llm_seed         a fixed seed for every answer, or none
"""
from __future__ import annotations

import os
from typing import Any


def _cfg() -> dict[str, Any]:
    from murmur import config
    try:
        return config.load()
    except Exception:                               # noqa: BLE001  a node with no readable config takes the defaults
        return {}


def _flag(v: Any) -> bool:
    return str(v).strip().lower() not in ("", "0", "false", "no", "none", "off")


BY_CODE = "plans are decided by code"     # the record's word for a plan step the model wasn't asked about, by design and not by failure
BY_CODE_SAYS = "Code decides the plans on this node, so this is code's own answer. The model wasn't asked."      # the same, as a receipt's reason: no model failed, and no reason is missing


def careful_notes() -> bool:
    """True: a person's note goes through the careful step (node/note_reader.py, read_note_carefully): the reader's question carries examples of how
    people write, and a reading that can't stand keeps everything until tonight is over, tells the person, and is read again at the next step.
    For a small reader on the site. False (the default): the plain note step."""
    env = os.environ.get("MURMUR_CAREFUL_NOTES")
    return _flag(env) if env is not None else bool(_cfg().get("careful_notes"))


def model_options(base: dict[str, Any]) -> dict[str, Any]:
    """base with the run's temperature and seed, if the config sets them."""
    c = _cfg()
    out = dict(base)
    if c.get("llm_temperature") is not None:
        out["temperature"] = float(c["llm_temperature"])
    if c.get("llm_seed") is not None:
        out["seed"] = int(c["llm_seed"])
    return out


