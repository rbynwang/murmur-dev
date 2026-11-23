"""The console's one way to the network's parts: every path of a part a console reads or posts is here, and nowhere else.

A Clean adapter drives parts of this repository's code through the runner's Evening (demo/runner/evening.py): its gates, its
orders, its meter and its own way of reaching each part by name. It adds what a console reads in each pass: the conductor's view,
the bus record's new messages, the sale's summary and snapshots, each followed node's new record rows, the meter's new quarter-hours,
and every post the evening made (an order or a surprise), each with its answer.
"""
from __future__ import annotations

import time
from typing import Any

from demo.runner.evening import Evening
from demo.runner.stack import COMMUNITY

ROWS_LIMIT = 200


class Played(Evening):
    """The runner's evening, keeping every order and surprise it posts, with the answer, for the console's story."""

    def __init__(self, *args: Any, **kw: Any):
        super().__init__(*args, **kw)
        self.posts: list[dict[str, Any]] = []

    def post(self, part: str, path: str, body: dict[str, Any]) -> dict[str, Any]:
        keep = path.endswith(("/needs", "/demo/scenario", "/alert"))
        try:
            got = super().post(part, path, body)
        except Exception as exc:
            if keep:
                status = getattr(getattr(exc, "response", None), "status_code", 0)
                self.posts.append({"part": part, "path": path, "body": body, "status": status, "answer": {}, "at_wall": time.time()})
            raise
        if keep:
            self.posts.append({"part": part, "path": path, "body": body, "status": 200, "answer": got, "at_wall": time.time()})
        return got


class Clean:
    """Reads and posts of one evening on parts of this repository's code."""
    leap_max_steps = 192

    def __init__(self, e: Played, follow: list[str]):
        self.e, self.follow = e, list(follow)
        self.bus_at = self.bus_next()
        self.rows_at = {n: 0 for n in self.follow}           # each log's present end: an earlier run's rows are not this one's
        for host in {self.host(n) for n in self.follow}:
            try:
                ends = self.e.get(host, "/agents/record").get("rows") or {}
            except Exception:
                ends = {}
            self.rows_at.update({n: int(ends.get(n) or 0) for n in self.follow if self.host(n) == host})
        self.fed_seen: set[str] = set()
        self.posts_seen = 0

    def host(self, node: str) -> str:
        return "buildings" if node.startswith("building-") else "homes"

    def conductor(self) -> dict[str, Any]:
        return self.e.get(COMMUNITY, "/demo/conductor")

    def conduct(self, **body: Any) -> dict[str, Any]:
        return self.e.post(COMMUNITY, "/demo/conductor", body)

    def summary(self) -> dict[str, Any]:
        return self.e.get(COMMUNITY, "/v2/summary")

    def snapshot(self, sale: str) -> dict[str, Any]:
        return self.e.get(COMMUNITY, f"/v2/events/{sale}")

    def bus_next(self) -> int:
        return int(self.e.get("bus", f"/runs/{self.e.s.run}/record?after={10 ** 9}").get("next") or 0)     # its end, and none of its messages

    def bus(self) -> list[dict[str, Any]]:
        """The messages the bus accepted since the last read."""
        got = self.e.get("bus", f"/runs/{self.e.s.run}/record?after={self.bus_at}")
        self.bus_at = int(got.get("next") or self.bus_at)
        return [x for x in got.get("events") or [] if x.get("event") == "accepted"]

    def rows(self, node: str) -> list[dict[str, Any]]:
        """A followed node's record rows since the last read. A log that begins again (a new run of the node) is read from its start."""
        out: list[dict[str, Any]] = []
        for _ in range(20):
            got = self.e.get(self.host(node), f"/agents/{node}/record?after={self.rows_at.get(node, 0)}&limit={ROWS_LIMIT}")
            nxt = int(got.get("next") or 0)
            if nxt < self.rows_at.get(node, 0):
                self.rows_at[node] = 0
                continue
            out += got.get("rows") or []
            self.rows_at[node] = nxt
            if len(got.get("rows") or []) < ROWS_LIMIT:
                break
        return out

    def meter(self) -> list[dict[str, Any]]:
        """The quarter-hours the runner's meter has fed since the last read: what homes and buildings drew against their no-sale twins."""
        new = sorted(q for q in list(self.e.fed) if q not in self.fed_seen)
        self.fed_seen |= set(new)
        return [{"ts": q, **self.e.fed[q]} for q in new]

    def posts(self) -> list[dict[str, Any]]:
        new = self.e.posts[self.posts_seen:]
        self.posts_seen += len(new)
        return new

    def post(self, part: str, path: str, body: dict[str, Any]) -> dict[str, Any]:
        return self.e.post(part, path, body)
