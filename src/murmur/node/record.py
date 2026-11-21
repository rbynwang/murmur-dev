"""The decision record: what a node decided and why, one chained line per decision, so any decision can be read back and checked.

Each line holds what went in (the question's hash, the facts), what came out and who decided, and the hash of the line before it, so a line
changed or taken out of the middle breaks the chain from there on. The chain shows accidents, not forgery: there is no key, and a cut at the
very end leaves a good chain, because nothing after it says there should be more.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import threading
from pathlib import Path
from typing import Any, Callable

import httpx


def clean(x: Any) -> Any:
    """Plain JSON, the same every time: numpy numbers become numbers, sets are sorted, NaN and text that isn't real text can't break the file."""
    if isinstance(x, str):
        return x if x.isascii() else x.encode("utf-8", "replace").decode("utf-8")     # a lone surrogate from a JSON escape can't be written
    if isinstance(x, dict):
        return {clean(str(k)): clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [clean(v) for v in x]
    if isinstance(x, (set, frozenset)):
        return sorted(clean(v) for v in x)
    if hasattr(x, "item") and not isinstance(x, (str, bytes)):
        x = x.item()
    if isinstance(x, float) and not math.isfinite(x):
        return str(x)
    if x is None or isinstance(x, (str, int, float, bool)):
        return x
    return str(x)


def dumps(x: Any) -> str:
    return json.dumps(clean(x), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha(*parts: Any) -> str:
    return hashlib.sha256(dumps(list(parts)).encode()).hexdigest()


class Log:
    """In memory, and in a file if it has a path. A file that exists is read back, so a restarted node keeps its record.

    A power cut can tear the last line. That line goes to a .torn file beside the log and the node comes back: a row that was never whole
    wrote nothing that once() relied on. A bad line in the middle isn't an accident, so it stays as an unreadable row, and the chain breaks there.
    """

    def __init__(self, node: str, path: str | Path | None = None):
        self.node = node
        self.path = Path(path) if path else None
        self.rows: list[dict[str, Any]] = []
        self._lock = threading.Lock()
        if self.path and self.path.exists():
            self.rows = self._read(self.path)

    def _read(self, path: Path) -> list[dict[str, Any]]:
        raw = path.read_bytes()
        *lines, tail = raw.split(b"\n")
        rows: list[dict[str, Any]] = []
        for x in lines:
            if x.strip():
                try:
                    r = json.loads(x)
                    if not isinstance(r, dict) or not {"kind", "hash"} <= set(r):
                        raise ValueError("not a row")
                    rows.append(r)
                except (ValueError, RecursionError):
                    rows.append({"n": len(rows) + 1, "kind": "unreadable", "node": self.node, "text": x[:200].decode("utf-8", "replace"), "hash": ""})
        if tail.strip():
            with path.with_name(path.name + ".torn").open("ab") as f:
                f.write(tail + b"\n")
            with path.open("r+b") as f:
                f.truncate(len(raw) - len(tail))
        return rows

    def add(self, kind: str, **fields: Any) -> dict[str, Any]:
        with self._lock:
            r = {"n": len(self.rows) + 1, "kind": kind, "node": self.node, **clean(fields), "prev": self.rows[-1]["hash"] if self.rows else ""}
            r["hash"] = sha(r)
            self.rows.append(r)
            if self.path:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8") as f:
                    f.write(dumps(r) + "\n")
                    f.flush()
                    os.fsync(f.fileno())               # once() counts on this row being there after a power cut
            return r

    def all(self, kind: str | None = None) -> list[dict[str, Any]]:
        return [r for r in self.rows if kind is None or r["kind"] == kind]

    def decision(self, rec: dict[str, Any]) -> None:
        """agent.py's own summary of a step: pass this as its `record`."""
        self.add("decision", **rec)


class Steps:
    """The workflow's states. Each once() writes before it runs, so a crash in the middle is never run again by mistake."""

    UNKNOWN = {"status": "unknown", "why": "This started before a restart and its end wasn't recorded, so it isn't run again.",
               "view": "This started before a restart and its end wasn't recorded, so it isn't run again."}

    def __init__(self, log: Log):
        self.log = log
        self.done: dict[str, Any] = {}
        for r in log.rows:
            if r["kind"] == "started":
                self.done.setdefault(r["key"], dict(self.UNKNOWN))
            elif r["kind"] == "finished":
                self.done[r["key"]] = r["result"]
            elif r["kind"] == "not_final":
                self.done.pop(r["key"], None)
            elif r["kind"] == "new_run":
                self.done.clear()

    def new_run(self) -> None:
        """A run over the same days again, on the same log. A restart keeps what was done. A new run must not: its calls have to happen."""
        self.log.add("new_run")
        self.done.clear()

    def once(self, key: Any, fn: Callable[[], Any], final: Callable[[Any], bool] | None = None) -> Any:
        """fn runs the first time only, and later the same answer comes back. final(answer) False means nothing happened, so it may be tried again."""
        k = key if isinstance(key, str) else sha(key)
        if k in self.done:
            self.log.add("repeat", key=k)
            return self.done[k]
        self.log.add("started", key=k)
        self.done[k] = dict(self.UNKNOWN)
        out = clean(fn())
        if final is not None and not final(out):
            del self.done[k]
            self.log.add("not_final", key=k)
            return out
        self.done[k] = out
        self.log.add("finished", key=k, result=out)
        return out

    def enter(self, step: str, ts: str, **info: Any) -> None:
        self.log.add("step", step=step, ts=ts, state="entered", **info)

    def leave(self, step: str, ts: str, outcome: str = "done") -> None:
        self.log.add("step", step=step, ts=ts, state=outcome)


def model_version(name: str, url: str) -> dict[str, str]:
    """The model's name and digest, so "the same model" means the same weights."""
    try:
        tags = httpx.get(url + "/api/tags", timeout=5).json().get("models", [])
        return {"name": name, "digest": next((m.get("digest", "") for m in tags if m.get("name") == name), "")}
    except (httpx.HTTPError, ValueError):
        return {"name": name, "digest": ""}


class RecordingBrain:
    """Has the model's ask() (llm_client.NodeModel) and writes every question and answer to the node's log. Everything else, such as .model,
    comes from the model inside."""

    def __init__(self, inner: Any, log: Log, prompt: str = "", model: dict[str, str] | None = None, options: dict[str, Any] | None = None):
        self.inner, self.log, self.prompt, self.options = inner, log, prompt, options
        self.version = model or {"name": getattr(inner, "model", ""), "digest": ""}

    def __getattr__(self, name: str) -> Any:
        if name == "inner":                       # copy.copy asks a new, empty one for __setstate__: with no inner this would ask itself until the stack runs out
            raise AttributeError(name)
        return getattr(self.inner, name)

    def ask(self, system: str, tools: list[dict[str, Any]], text: str, **kw: Any) -> dict[str, Any]:
        a = self.inner.ask(system, tools, text, **kw)
        self.log.add("model", asked=sha(system, tools, text), prompt=self.prompt, model=self.version, options=self.options, system=system, text=text, tools=tools, answer=a)
        return a
