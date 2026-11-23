"""A node host's record door: each thinking node's own decision log (node/record.py), read from a place on.

  GET /agents/record                             {"rows": {node: how many rows its log holds}}, the place each log has reached
  GET /agents/{name}/record?after=N&limit=200    {"node", "rows", "next"}: the rows after row N, oldest first, 200 at most; `next` is the N to ask with next

A row is the log's own, numbered `n` by its place in the log from 1, as record.Log.add numbered it. Three things are changed on the way out, so that an
answer stays small and no hash, key or signature leaves whole:

  - a run of 48 or more hex characters, in a text or in a field's name, is cut to its first 16
  - a `model` row's `tools`, each one's whole definition in the log, are their names
  - a row that is still over 16,000 characters, as the log writes it, keeps `n`, `kind`, `node`, `ts` and `step` (those it has) and says `cut: true`

They are GET doors of the host's own app, so they ask of a caller what its other read doors ask (protocol/doors.py): nothing.
"""
from __future__ import annotations

import re
from typing import Any

from murmur.node import record

LIMIT = 200                                    # the most rows in one answer
ROW_MAX = 16_000                               # the longest row an answer holds whole, in characters
HEX = re.compile(r"[0-9a-fA-F]{48,}")          # as long as a hash, a key or a signature
HEX_KEPT = 16                                  # the characters of such a run that stay
HEAD = ("n", "kind", "node", "ts", "step")     # what is left of a row that is cut


def short(x: Any) -> Any:
    """x with every long run of hex cut short, in its texts and in the names of its fields."""
    if isinstance(x, str):
        return HEX.sub(lambda m: m.group()[:HEX_KEPT], x)
    if isinstance(x, dict):
        return {short(k): short(v) for k, v in x.items()}
    if isinstance(x, list):
        return [short(v) for v in x]
    return x


def tool_name(tool: Any) -> str:
    """The name of one tool a model was offered: {"type": "function", "function": {"name", ...}} in a model row."""
    f = tool.get("function", tool) if isinstance(tool, dict) else None
    return str(f.get("name") or "") if isinstance(f, dict) else ""


def served(row: dict[str, Any], n: int) -> dict[str, Any]:
    """The log's row at place n, as the door gives it."""
    row = {**row, "n": n}
    if row.get("kind") == "model":
        tools = row.get("tools")
        row["tools"] = [tool_name(t) for t in tools] if isinstance(tools, list) else []
    row = short(row)
    if len(record.dumps(row)) > ROW_MAX:
        return {**{k: row[k] for k in HEAD if k in row}, "cut": True}
    return row


def page(node: str, rows: list[dict[str, Any]], after: int, limit: int = LIMIT) -> dict[str, Any]:
    """The rows of a log after place `after`, `limit` at most. An `after` beyond the log's end reads from its end: `next` then says where the log is."""
    start = min(after, len(rows))
    got = [served(r, start + 1 + i) for i, r in enumerate(rows[start:start + limit])]
    return {"node": node, "rows": got, "next": start + len(got)}


def mount(app: Any, f: Any) -> None:
    """Adds the two doors to a host's app. f.logs holds each thinking node's record.Log; a node that runs on code alone has none."""
    from fastapi import HTTPException, Query

    @app.get("/agents/record")
    def records():
        """How many rows each node's log holds now: the place to read from when nothing old is wanted."""
        return {"rows": {name: len(log.rows) for name, log in f.logs.items()}}

    @app.get("/agents/{name}/record")
    def node_record(name: str, after: int = Query(0, ge=0), limit: int = Query(LIMIT, ge=1, le=LIMIT)):
        """One node's rows after place `after`, oldest first. A place or a limit outside its range is refused (422)."""
        log = f.logs.get(name)
        if log is None:
            raise HTTPException(404, "this node keeps no record here")
        return page(name, log.rows, after, limit)
