"""A person's word at a node host: the one way an alarm ends and a limit goes up, kept on disk before anyone hears it was taken."""
from __future__ import annotations

import math
from datetime import datetime

import time
from typing import Any, Callable
from murmur.node import control as rt_control
from murmur.agents.host_common import TEXT_MAX, UNREAD, log
from murmur.node import person


def code_channel(h: Any, kind: str, keys: dict[str, str], seq: dict[str, int] | None = None, save: Callable[[dict[str, int]], Any] | None = None) -> Any:
    """A person's channel on a node with no agent: an alarm's end, and a limit, which the controller holds by itself. Closing a group isn't here. Without levers the controller
    uses every device it has, and an offer would go on counting what a person closed, so a closed group needs an agent."""
    from murmur.node import policy as P

    def apply(verb: str, group: str, name: str, value: float | None) -> dict[str, Any]:
        ov = h.adapter.overrides
        if verb == "set_limit":
            rt_control.write_limit(h.adapter, group, name, value)
            return {"status": "done"}
        if verb != "clear_alarm":
            return {"status": "blocked", "why": "This node has no agent, so it takes a limit or an alarm's end, and nothing else yet."}
        if ov.get("alarm"):
            return {"status": "blocked", "why": "The alarm is still on."}
        if "alarm_hold" not in ov:
            return {"status": "blocked", "why": "No alarm is holding this node."}
        ov.pop("alarm_hold")
        h.adapter.rt_override("stop", False)
        return {"status": "done"}
    return P.OwnerChannel(h.name, P.Policy("building" if kind == "buildings" else "home"), keys, apply, h.log, seq, save)


def comfort_ok(value: Any) -> bool:
    """A comfort limit from outside, inside the range policy.py gives a person. The controller takes these numbers as they come, and this
    door isn't the signed owner channel, so nothing here may go past that range or carry another name."""
    from murmur.node.policy import LIMITS
    rng = LIMITS["hvac_zones"]
    return isinstance(value, dict) and bool(value) and all(k in rng and isinstance(v, (int, float)) and not isinstance(v, bool) and rng[k][0] <= v <= rng[k][1] for k, v in value.items())


def raises_a_limit(a: Any, kind: str, value: Any) -> bool:
    """Would this value take a person's limit up? A limit goes up only by that person's signed word, because the guard trusts this number. This door may only bring one down, token
    or no token: what's lower can't hurt anyone, and a clear goes back to what the file or a signed word says."""
    if kind == "comfort" and getattr(a, "ctl", None) is not None:
        return any(float(v) > rt_control.person_limit(a, k) for k, v in value.items())
    return kind == "lights" and float(value) > a.light_limit()


def plain(value: Any) -> bool:
    """Plain text someone might say: a signal's name, a note. Not empty, and short enough to go on the record."""
    return isinstance(value, str) and bool(value.strip()) and len(value) <= TEXT_MAX


def override_ok(kind: str, value: Any) -> bool:
    """What each override may carry through this door. A switch is true or plain text, and false or null to end it. Anything else is refused and changes nothing,
    so what reaches rt_override means what it says: a value that is neither, such as "", [] or {}, would free an alarm."""
    if kind == "comfort":
        return comfort_ok(value)
    if kind == "lights":
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
    if kind == "note":
        return value is None or value is False or plain(value)
    if kind == "depart_at":
        try:
            return plain(value) and bool(datetime.strptime(value, "%Y-%m-%d %H:%M"))
        except ValueError:
            return False
    return value is None or isinstance(value, bool) or plain(value)


class HostPeople:
    """A person's word at a node host: the one way an alarm ends and a limit goes up, kept on disk before anyone hears it was taken."""

    def person_word(self, name: str, msg: Any) -> dict[str, Any]:
        """A person's signed word: the one way an alarm ends on a live node, and the one way a limit goes up. cfg person_keys names each role's public key. With none on file nothing passes here."""
        keys = self.cfg.get("person_keys") or {}
        if not keys:
            return {"status": "blocked", "why": "No person's key is on file here."}
        with self.locks[name]:
            ch = self.channels.get(name)
            if ch is None:
                ctx = getattr(self.agents.get(name), "ctx", None)
                seq, save = person.numbers(name, keys.values()), lambda n: person.note(name, seq=n)
                ch = self.channels[name] = ctx.owner_channel(keys, seq, save) if ctx is not None else code_channel(self.homes[name], self.kind, keys, seq, save)
            out = ch.receive(msg)
            if out.get("status") == "done":
                self.alarm_kept(name, **person.limit_said(name, msg))
            return out

    def alarm_kept(self, name: str, **more: Any) -> None:
        """What the node's overrides say of an alarm, in the node's own file (person.note) before anyone hears it was taken. A disk that won't take it doesn't stop the
        alarm: it stands in memory, /health says so, and each pass of the tick tries again."""
        ov = self.homes[name].adapter.overrides
        more = {**self.alarm_unsaved.get(name, {}), **more}
        try:
            person.note(name, hold=ov.get("alarm_hold"), signal=ov.get("alarm"), **more)
            self.alarm_unsaved.pop(name, None)
        except OSError as exc:
            if name not in self.alarm_unsaved:
                log.error("%s: an alarm isn't reaching the disk: %s", name, exc)
                self.events.append({"at": time.time(), "home": name, "kind": "alarm_not_saved", "error": str(exc)[:160]})
            self.alarm_unsaved[name] = more

    def person_back(self) -> None:
        """At the start, before any tick: what holds each node and the limits a person set come from the node's own file (person.book), and once that file exists it's the
        whole truth. With no file yet, the node's overrides stand as they are. A thinking node's log counts as well, because it's on disk at once. A file that can't be read
        may have held an alarm, so the node stays held until a person says. Whatever is wrong with one node, the others come back and the service starts."""
        for name, h in self.homes.items():
            if not hasattr(h.adapter, "overrides"):
                continue
            try:
                self._person_back(name, h.adapter)
            except Exception as exc:                      # noqa: BLE001
                log.exception("%s: what a person said didn't come back", name)
                self.events.append({"at": time.time(), "home": name, "kind": "state_set_aside", "file": f"person/{name}", "why": f"{type(exc).__name__}: {str(exc)[:120]}"})
                h.adapter.hold_alarm(UNREAD)

    def _person_back(self, name: str, a: Any) -> None:
        ctx = getattr(self.agents.get(name), "ctx", None)
        b = person.book(name)
        if b and "bad" in b:
            self.events.append({"at": time.time(), "home": name, "kind": "state_set_aside", "file": f"person/{name}", "why": b["bad"]})
            hold, signal = UNREAD, None
        elif b is None:
            hold, signal = a.overrides.get("alarm_hold"), a.overrides.get("alarm")
        else:
            hold, signal = b.get("hold"), b.get("signal")
        hold = hold or getattr(ctx, "stopped", None)
        if hold:
            a.overrides.pop("alarm", None)
            if ctx is not None:
                ctx.alarm(hold)
            a.hold_alarm(hold)
            if signal:
                a.overrides["alarm"] = signal
            self.alarm_kept(name)
        elif "alarm_hold" in a.overrides:                 # nothing holds the node by its own file: the overrides' alarm goes
            for k in ("alarm", "alarm_hold", "stop"):
                a.overrides.pop(k, None)
        for group, limits in ((b or {}).get("limits") or {}).items():
            for k, v in limits.items():
                rt_control.write_limit(a, group, k, v)

    def held(self) -> bool:
        """cfg kept_days: the days the benchmark keeps unseen. The clock runs on after a debug day, and the nodes don't step into one.
        The benchmark's own config leaves the list out."""
        h = next(iter(self.homes.values()), None)
        return bool(self.kept) and h is not None and h.now_ts()[:10] in self.kept
