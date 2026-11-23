"""The evenings a console plays, each one configuration of the runner's (demo/runner/settings.py), and the stack of the one in hand.

A console that plays one configuration opens it once. A looping console (--loop-days) is given the turn of its days by the driver
each time an evening has ended (driver.Driver.turn):

  one configuration       the same evening again, on the same stack while every part of it still runs
  several configurations  the next one's evening, then the one after, then the first again: the stack of the day that ended is
                          stopped, and the next day's is started in a run folder of its own

Every stack after the first needs a fresh run folder, so the configurations of a loop of several days must have "{time}" in their
`folder`; with one configuration it is needed only when a part has stopped and the stack is started anew. A configuration's
`label` (at most 40 characters) is the day's name on the page, beside its date.

One thread reads the parts of the stack in hand for the feed's first form (watch); only stacks this object started are stopped.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any, Callable

from demo.runner import feed as runner_feed
from demo.runner.settings import Settings, load
from demo.runner.stack import Stack


class Days:
    def __init__(self, configs: list[str | Path], say: Callable[..., None] = print, stack: Callable[[Settings], Any] = Stack):
        self.paths = [Path(c) for c in configs]
        if not self.paths:
            raise ValueError("a console plays at least one configuration")
        if len(self.paths) > 1:
            for p in self.paths:
                if "{time}" not in str(json.loads(p.read_text()).get("folder")):
                    raise ValueError(f'{p.name}: a loop of several days starts each in a fresh run folder, so `folder` must hold "{{time}}"')
        self.say, self.make = say, stack
        self.i = 0
        self.s: Settings | None = None
        self.k: Any = None
        self.watcher: Any = None
        self.stop = threading.Event()

    def open(self) -> tuple[Settings, Any]:
        """Starts the stack of the day in hand in a fresh run folder, and reads its parts once."""
        s = load(self.paths[self.i])
        s.pace_s, s.leap = 0.0, True                    # the console's clock: as fast as the network, leaping; the page sets the pace
        s.folder.mkdir(parents=True)
        self.s, self.k = s, self.make(s)                # known before it starts, so that a stack that starts by half is still stopped
        self.k.write()
        self.k.start()
        self.watcher = runner_feed.Watcher(s.folder)
        self.watcher.read()
        self.say(f"day {self.i + 1} of {len(self.paths)}: {s.evening['date']} {s.label}".rstrip())
        return s, self.k

    def turn(self) -> tuple[Settings, Any] | None:
        """The next evening's settings and stack, started; None when it plays on the stack in hand."""
        if len(self.paths) == 1 and not self.k.stopped():
            return None
        self.k.stop()
        self.i = (self.i + 1) % len(self.paths)
        return self.open()

    def now(self) -> dict[str, Any]:
        """The day in hand, as the page is told it."""
        return {"day": self.i + 1, "days": len(self.paths), "date": str(self.s.evening["date"]) if self.s else "", "label": self.s.label if self.s else ""}

    def v1(self) -> dict[str, Any]:
        """The feed's first form, of the stack in hand."""
        w = self.watcher
        return runner_feed.state(w.answers, w.seen, w.code, time.time())

    def watch(self) -> None:
        """Until close(): the parts of the stack in hand are read every few seconds."""
        while not self.stop.wait(runner_feed.EVERY_S):
            w = self.watcher
            if w is not None:
                w.read()

    def close(self) -> None:
        self.stop.set()
        if self.k is not None:
            self.k.stop()
