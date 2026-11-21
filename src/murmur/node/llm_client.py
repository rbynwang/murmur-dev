"""The small model client. The model only reads what people write and words reports; code decides every amount.

  LlmClient   one answer with tools from a model server's chat endpoint (POST {url}/api/chat, the Ollama wire form). The address and
              the model come from the node's configuration (llm_url, llm_model). A server that fails or refuses is no answer: the
              caller keeps code's own result.
  SharedModel the process's one door to the model: `llm_slots` requests at a time, an exception before a sale step before a report.
              Waiting at the door doesn't count against a request's own time limit.
  NodeModel   what one node's agent holds: the shared model, in its turn, with the node's lock let go while it waits.
"""
from __future__ import annotations

import contextlib
import heapq
import itertools
import threading
import time
from typing import Any

import httpx

from murmur.node import modes

OPTIONS = {"temperature": 0.3, "top_p": 0.8, "top_k": 20, "num_predict": 300, "num_ctx": 32768}
TIMEOUT_S = 120.0


class LlmClient:
    def __init__(self, url: str, model: str, timeout_s: float = TIMEOUT_S):
        if not url or not model:
            raise ValueError("a model needs llm_url and llm_model in the node's configuration")
        self.url, self.model = url.rstrip("/"), model
        self.http = httpx.Client(timeout=timeout_s)
        self.options = modes.model_options(OPTIONS)      # the run's temperature and seed, if its configuration sets them
        self.calls = 0
        self.ms = 0.0
        self.tokens_in = 0
        self.tokens_out = 0
        self.errors = 0

    def ask(self, system: str, tools: list[dict[str, Any]], text: str) -> dict[str, Any]:
        """{calls: [{name, args}], text, ms, error, tokens}. error is set, and calls empty, when no usable answer came."""
        t0 = time.time()
        body = {"model": self.model, "stream": False, "think": False, "keep_alive": "30m", "truncate": False, "shift": False, "tools": tools,
                "options": self.options, "messages": [{"role": "system", "content": system}, {"role": "user", "content": text}]}
        try:
            r = self.http.post(self.url + "/api/chat", json=body)
            r.raise_for_status()
            j = r.json()
        except (httpx.HTTPError, ValueError) as e:
            self.errors += 1
            return {"calls": [], "text": "", "error": str(e)[:200], "ms": 0}
        try:                                                 # an answer not in the chat form is no answer, like a server that fails
            m = j.get("message") or {}
            calls = [{"name": c["function"]["name"], "args": c["function"].get("arguments") or {}} for c in (m.get("tool_calls") or [])
                     if isinstance(c, dict) and isinstance(c.get("function"), dict) and c["function"].get("name")]
            text = m.get("content") or ""
            if not isinstance(text, str):
                raise TypeError("the answer's content is not text")
            text = text[:300]
            tokens = {"in": int(j.get("prompt_eval_count") or 0), "out": int(j.get("eval_count") or 0)}
        except (AttributeError, TypeError, ValueError) as e:
            self.errors += 1
            return {"calls": [], "text": "", "error": f"not a chat answer: {type(e).__name__}", "ms": 0}
        ms = (time.time() - t0) * 1000
        self.calls += 1
        self.ms += ms
        self.tokens_in += tokens["in"]
        self.tokens_out += tokens["out"]
        return {"calls": calls, "text": text, "ms": round(ms), "error": None, "tokens": tokens}


class SharedModel:
    """The process's one door to the model."""
    RANK = {"exception": 0, "sale": 1, "report": 2}

    def __init__(self, cfg: dict[str, Any]):
        self.client = LlmClient(str(cfg.get("llm_url") or ""), str(cfg.get("llm_model") or ""))
        self.free = max(1, int(cfg.get("llm_slots", 1)))
        self.line: list[tuple[int, int]] = []
        self.seq = itertools.count()
        self.cv = threading.Condition()

    @contextlib.contextmanager
    def turn(self, kind: str, node: str):
        me = (self.RANK.get(kind, 1), next(self.seq))
        with self.cv:
            heapq.heappush(self.line, me)
            while self.free <= 0 or self.line[0] != me:
                self.cv.wait(1.0)
            heapq.heappop(self.line)
            self.free -= 1
            self.cv.notify_all()
        try:
            yield
        finally:
            with self.cv:
                self.free += 1
                self.cv.notify_all()

    def status(self) -> dict[str, Any]:
        c = self.client
        return {"url": c.url, "model": c.model, "calls": c.calls, "seconds": round(c.ms / 1000, 1), "tokens_in": c.tokens_in, "tokens_out": c.tokens_out,
                "errors": c.errors, "waiting": len(self.line)}


class NodeModel:
    """The model as one node's agent holds it: ask() waits its turn at the shared door, with the node's lock let go."""

    def __init__(self, shared: SharedModel, lock: Any, node: str):
        self.shared, self.lock, self.node = shared, lock, node
        self.model = shared.client.model
        self.agent: Any = None

    def kind(self) -> str:
        """The door's kind, from the step the agent's workflow is in."""
        steps = getattr(self.agent, "steps", None)
        step = steps[-1][0] if steps else ""
        return "exception" if step.startswith("8") else "report" if step.startswith("9") else "sale"

    def ask(self, system: str, tools: list[dict[str, Any]], text: str) -> dict[str, Any]:
        with self.lock.let_go(), self.shared.turn(self.kind(), self.node):
            return self.shared.client.ask(system, tools, text)
