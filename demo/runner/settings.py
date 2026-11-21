"""The runner's configuration: one JSON file (config.example.json is the example). Every part listens on `host`.

  run           the run's id on the message bus
  host          the address every part listens on and is called at (the example: 127.0.0.1, this computer only)
  folder        the run folder: each participant's configuration, keys, state and logs. Made fresh: it must not exist yet
                ("{time}" in it stands for the start time, so that each run gets a folder of its own)
  ports         "free" (the system hands out free ports) or the first port of a block, 51000 or above
  data_dir      the dataset every participant reads (MURMUR_DATA_DIR); models_dir likewise (MURMUR_MODELS_DIR, may be "")
  evening       the evening's request: date, window, homes, buildings, order_kw, community_definition, feed, battery_request
  sites         the single sites that answer the aggregator ({"sites": {name: {"site", "feed", "requests"}}}), or ""
  step_seconds  the wall seconds of one 15-minute step of the simulated clock, 2 to 120
  quiet_s       how long after the last message a held step counts as finished (the community's clock_wait_quiet_s)
  devices       the homes' devices that take part besides batteries and cars (MURMUR_DEVICES): "all" or a comma list; a building's own
                fans, plug loads and car ports always take part
  model         {"stand_in": true} for the stand-in model, or {"url": "http://HOST:PORT", "name": "MODEL"} for a model server on `host`
  events        what happens at given steps: {"at": "YYYY-MM-DD HH:MM", "kind": "note" | "car_now" | "building_closed" |
                "zone_event" | "cloud" | "emergency", ...}
  feed_port     the port of the read-only state feed (0: a free one)

Relative paths are read from the configuration file's own folder.
"""
from __future__ import annotations

import json
import socket
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

LOOPBACK = "127.0.0.1"                                # `host` when the configuration names none
FIRST_PORT = 51000
KINDS = ("note", "car_now", "building_closed", "zone_event", "cloud", "emergency")


@dataclass
class Settings:
    run: str
    folder: Path
    data_dir: Path
    models_dir: Path | None
    evening: dict[str, Any]
    sites: dict[str, Any]
    step_seconds: float = 2.0
    quiet_s: float = 1.5
    ports: str | int = "free"
    devices: str = "all"
    model: dict[str, Any] = field(default_factory=lambda: {"stand_in": True})
    events: list[dict[str, Any]] = field(default_factory=list)
    feed_port: int = 0
    host: str = LOOPBACK

    @property
    def homes(self) -> list[str]:
        return list(self.evening["homes"])

    @property
    def buildings(self) -> list[str]:
        return list(self.evening.get("buildings") or [])

    @property
    def buyers(self) -> list[str]:
        return list(self.evening["order_kw"])


def _path(base: Path, value: str) -> Path:
    p = Path(value.format(time=datetime.now().strftime("%Y%m%d-%H%M%S")) if "{time}" in value else value)
    return p if p.is_absolute() else (base / p).resolve()


def load(path: str | Path) -> Settings:
    """The configuration in this file, checked: a bad value stops the run before anything starts."""
    path = Path(path).resolve()
    raw = json.loads(path.read_text())
    base = path.parent
    evening = json.loads(_path(base, raw["evening"]).read_text())
    sites = json.loads(_path(base, raw["sites"]).read_text())["sites"] if raw.get("sites") else {}
    s = Settings(run=str(raw["run"]), folder=_path(base, raw["folder"]), data_dir=_path(base, raw["data_dir"]),
                 models_dir=_path(base, raw["models_dir"]) if raw.get("models_dir") else None, evening=evening, sites=sites,
                 step_seconds=float(raw.get("step_seconds", 2.0)), quiet_s=float(raw.get("quiet_s", 1.5)), ports=raw.get("ports", "free"),
                 devices=str(raw.get("devices", "all")), model=dict(raw.get("model") or {"stand_in": True}), events=list(raw.get("events") or []), feed_port=int(raw.get("feed_port", 0)),
                 host=str(raw.get("host") or LOOPBACK))
    check(s)
    return s


def check(s: Settings) -> None:
    if not 2 <= s.step_seconds <= 120:
        raise ValueError("step_seconds must be 2 to 120")
    if s.ports != "free" and not (isinstance(s.ports, int) and s.ports >= FIRST_PORT):
        raise ValueError(f'ports must be "free" or a first port of {FIRST_PORT} or above')
    if s.folder.exists():
        raise ValueError(f"the run folder {s.folder} exists already: every run starts in a fresh one")
    if not (s.data_dir / "dataset.json").exists():
        raise ValueError(f"no dataset.json in data_dir {s.data_dir}")
    for k in ("date", "window", "homes", "order_kw", "community_definition", "feed"):
        if k not in s.evening:
            raise ValueError(f"the evening has no {k}")
    url = str(s.model.get("url") or "")
    if not s.model.get("stand_in") and not (url.startswith(f"http://{s.host}:") and s.model.get("name")):
        raise ValueError(f'model must be {{"stand_in": true}} or {{"url": "http://{s.host}:PORT", "name": ...}}')
    for e in s.events:
        try:
            datetime.strptime(str(e.get("at")), "%Y-%m-%d %H:%M")
        except ValueError:
            raise ValueError(f"an event's at must be YYYY-MM-DD HH:MM: {e}") from None
        if e.get("kind") not in KINDS:
            raise ValueError(f"an event's kind must be one of {KINDS}: {e}")


def ports(s: Settings, names: list[str]) -> dict[str, int]:
    """A port for each name: free ones the system hands out (all held until every one is known, so none repeats), or a block."""
    if s.ports != "free":
        return {n: int(s.ports) + i for i, n in enumerate(names)}
    socks = []
    try:
        for _ in names:
            k = socket.socket()
            k.bind((s.host, 0))
            socks.append(k)
        return {n: k.getsockname()[1] for n, k in zip(names, socks)}
    finally:
        for k in socks:
            k.close()


def url(s: Settings, port: int) -> str:
    return f"http://{s.host}:{port}"
