"""Typed configuration, from files and the environment only.

  $MURMUR_CONFIG_DIR   a node's configuration folder: agent.json (its settings) and secrets/ (keys and tokens, never in the repository)
  $MURMUR_DATA_DIR     the dataset folder the node replays: dataset.json, fleet_v2.json, homes/, buildings/, devices/
  $MURMUR_MODELS_DIR   the folder of trained forecast models (used only with forecast = "trained")
  $MURMUR_LOG_DIR      where a service writes its logs (default: logs/ in the configuration folder)

A node's settings are the built-in DEFAULTS, then the dataset's own agent_defaults, then its agent.json. Every network address is a
setting: the message bus (town_url), the model server (llm_url), the other services a part calls (host_url, building_urls, utility_url,
clock_extra_targets), its own port (community_port, host_port, buildings_port, aggregator_port, site_port) and the address it listens on
(bind_host, the loopback address unless a deployment sets another).
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

CODE_DIR = Path(__file__).resolve().parent
CONFIG_DIR = Path(os.environ.get("MURMUR_CONFIG_DIR") or Path.home() / ".config" / "murmur")
DATA_DIR = Path(os.environ.get("MURMUR_DATA_DIR") or CODE_DIR.parent / "data")
MODELS_DIR = Path(os.environ.get("MURMUR_MODELS_DIR") or CODE_DIR.parent / "models")
LOG_DIR = Path(os.environ.get("MURMUR_LOG_DIR") or CONFIG_DIR / "logs")

DEFAULTS: dict[str, Any] = {
    "agent_name": "home",                # the participant's name on the message bus
    "role": "home",                      # home | building | community | aggregator | site | buyer
    "adapter": "simulated",              # the device driver behind a node: simulated (the dataset's replay)
    "battery_kwh": 13.5, "battery_kw": 5.0, "reserve_pct": 20.0, "soc_max_pct": 100.0, "soc0_pct": 55.0,
    "ev_max_kw": 7.2, "export_limit_kw": 10.0, "eta": 0.95,
    "control": "auto",                   # auto | advisory (advisory: recommend, the person applies)
    "replay_start": "",                  # dataset time the clock starts at: the dataset's own when unset
    "replay_step_seconds": 60,           # wall seconds per 15-minute dataset step
    "replay_loop_days": 1,               # loop the replay after N days (0 = run on)
    "town_url": "",                      # the message bus (required)
    "town_run_id": "",
    "bind_host": "127.0.0.1",            # the address every service listens on
    "community_port": 0, "host_port": 0,
    "utility_url": "",                   # the first buyer's service, which the community's clock moves with the rest
    "utility_name": "utility",           # the first buyer's name on the bus
    "clear_margin": 0.10,                # members are asked for this much more than the community promises upward
    "clear_lead_minutes": 180,           # clear at the latest this long before the buyer's commit deadline
    "coordinator_fee_share": 0.0,
    "send_workers": 8,                   # parallel sends when the community agent writes to every member
    "inbox_workers": 4, "catchup_workers": 16,
    "max_message_age_s": 900,            # a message without its own time-to-live is dropped this long after sending
    "discover_retry_wall_seconds": 30,
    "utility_retry_minutes": 30, "utility_retry_wall_seconds": 60, "utility_retries": 5,
    "readings_wait_minutes": 120,        # dataset minutes after the window to wait for every member's readings
    "utility_settle_wait_minutes": 30,   # a buyer settles this long after "readings are in", even if some are missing
    "host_poll_workers": 8, "host_poll_seconds": 5.0,
    "opt_out_days": {},                 # {node: [day, ...]}: days a person opted out
    "buildings": [],                     # the building members that take part, by name in the dataset's buildings.json
    "forecast": "temp_regression",       # temp_regression (a straight-line fit on temperature) | trained (node/forecast.py's HomeForecaster)
    "rebound_tolerance": 0.0,
    "llm_enabled": False,                # the node's agent reads notes and words reports with a model
    "llm_url": "",                       # the model server (required when llm_enabled)
    "llm_model": "",
}
_META: dict[str, Any] | None = None


def dataset_meta() -> dict[str, Any]:
    """The dataset's own settings (dataset.json in $MURMUR_DATA_DIR)."""
    global _META
    if _META is None:
        f = DATA_DIR / "dataset.json"
        _META = json.loads(f.read_text()) if f.exists() else {}
    return _META


def load() -> dict[str, Any]:
    """DEFAULTS, then the dataset's agent_defaults, then the node's agent.json. A replay start outside the dataset's range takes the dataset's."""
    cfg = json.loads(json.dumps(DEFAULTS))
    meta = dataset_meta()
    cfg.update(meta.get("agent_defaults", {}))
    path = CONFIG_DIR / "agent.json"
    if path.exists():
        for k, v in json.loads(path.read_text()).items():
            if k in meta.get("agent_defaults", {}) and v == DEFAULTS.get(k):
                continue                     # a default saved in agent.json: the dataset's own default wins
            cfg[k] = v
    if meta.get("range"):
        lo, hi = meta["range"]
        if not lo <= str(cfg.get("replay_start", ""))[:10] <= hi:
            cfg["replay_start"] = meta["replay_start"]
    return cfg


def secret(name: str) -> str:
    p = CONFIG_DIR / "secrets" / name
    return p.read_text().strip() if p.exists() else ""


def write_secret(name: str, value: str) -> None:
    d = CONFIG_DIR / "secrets"
    d.mkdir(parents=True, exist_ok=True)
    os.chmod(d, 0o700)
    p = d / name
    p.write_text(value.strip() + "\n")
    os.chmod(p, 0o600)


def data_path(name: str) -> Path:
    """A file of the dataset."""
    return DATA_DIR / name


def model_path(name: str) -> Path:
    """A file of the trained models. The dataset names its model folders as "models/<folder>"."""
    return MODELS_DIR / name.removeprefix("models/")


def events_file() -> Path:
    """The grid-event catalog the stand-in buyer publishes."""
    return data_path(dataset_meta()["events_file"])


def state_dir() -> Path:
    d = CONFIG_DIR / "state"
    d.mkdir(parents=True, exist_ok=True)
    return d


def log_dir() -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    return LOG_DIR
