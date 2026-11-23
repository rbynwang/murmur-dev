"""The parts of one demo run, each its own process on the configuration's host: the message bus, the stand-in model, the community agent and the
buyers beside it, the homes' host, the buildings' host, the aggregator and each single site.

Each part gets a folder in the run folder (its configuration agent.json, its keys under secrets/, its state and logs), a join
token and a grant for the bus, and the public keys of those it must trust. Only processes this stack starts are ever stopped.
"""
from __future__ import annotations

import json
import os
import secrets
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import httpx

from murmur.protocol import signing

from . import settings as S
from .grants import Controllers

ROOT = Path(__file__).resolve().parents[2]          # the repository: demo.runner and the package are imported from here
AGGREGATOR = "aggregator"
COMMUNITY = "community"
KEY_FILE = {COMMUNITY: "signing.key", AGGREGATOR: "aggregator.key", "site": "site.key"}
IDLE_S = 600.0                                       # the community's clock_wait_idle_s: waits that stand unchanged this long let the clock go on, and that is on the record


class Stack:
    def __init__(self, s: S.Settings):
        self.s = s
        self.names = [COMMUNITY, *s.buyers, *s.homes, *s.buildings, AGGREGATOR, *s.sites]       # every name on the bus
        self.port = S.ports(s, ["bus", "model", COMMUNITY, *s.buyers, "homes", "buildings", AGGREGATOR, *s.sites, "feed"])
        self.url = {k: S.url(s, p) for k, p in self.port.items()}
        self.tokens = {n: secrets.token_hex(16) for n in self.names}
        self.controllers = Controllers(s.folder / "controllers")
        self.procs: dict[str, subprocess.Popen] = {}
        self.folders: dict[str, Path] = {}

    # ------------------------------------------------------------------ configuration
    def common(self) -> dict[str, Any]:
        wall = self.s.step_seconds / 60.0                 # the services' own waits, at the run's pace
        return {"town_url": self.url["bus"], "town_run_id": self.s.run, "replay_start": f"{self.s.evening['date']} 00:00", "replay_loop_days": 0,
                "replay_step_seconds": self.s.step_seconds, "control_mode": "rolling", "forecast": "temp_regression", "bind_host": self.s.host,
                "buyers": self.s.buyers, "report_rule": "exception", "call_settle_after_min": 120,
                "town_poll_seconds": 0.5, "town_poll_idle_seconds": 0.5, "host_poll_seconds": 0.5, "host_poll_idle_seconds": 0.5,
                "utility_retry_wall_seconds": 60 * wall, "discover_retry_wall_seconds": 30 * wall, "confirm_retry_wall_seconds": 120 * wall,
                "offers_retry_wall_seconds": 120 * wall, "readings_chase_wall_seconds": 120 * wall, "readings_quiet_s": 30 * wall,
                "utility_settle_quiet_s": 30 * wall}

    def model(self) -> dict[str, Any]:
        """For the homes and buildings: every node an agent, plans by code, the model asked only to read notes and word reports."""
        m = self.s.model
        return {"llm_enabled": True, "llm_url": self.url["model"] if m.get("stand_in") else m["url"], "llm_model": "stand-in" if m.get("stand_in") else m["name"],
                "llm_slots": 1, "llm_temperature": 0.0, "llm_seed": 7, "thinking_homes": self.s.homes}

    def folder(self, part: str, cfg: dict[str, Any], names: list[str], extra: dict[str, str] | None = None) -> Path:
        """A part's folder: agent.json, and under secrets/ (mode 700) its bus grants and join tokens."""
        d = self.s.folder / part
        (d / "secrets").mkdir(parents=True, exist_ok=True)
        os.chmod(d / "secrets", 0o700)
        (d / "agent.json").write_text(json.dumps(cfg, indent=1))
        held = {n: self.controllers.grant(n, self.s.run) for n in names}
        for name, text in {"town_grants.json": json.dumps(held), **(extra or {})}.items():
            (d / "secrets" / name).write_text(text)
            os.chmod(d / "secrets" / name, 0o600)
        self.folders[part] = d
        return d

    def key(self, part: str, file: str) -> str:
        """The public key of a part's signing key, made now so that every part that trusts it can be told it before anything starts."""
        return signing.public_hex(signing.load_or_create(self.s.folder / part / "secrets" / file))

    def write(self) -> None:
        s, c, u = self.s, self.common(), self.url
        for part in (COMMUNITY, AGGREGATOR, "homes", "buildings", *s.sites):
            (s.folder / part / "secrets").mkdir(parents=True, exist_ok=True)
        community_pub, aggregator_pub = self.key(COMMUNITY, KEY_FILE[COMMUNITY]), self.key(AGGREGATOR, KEY_FILE[AGGREGATOR])
        site_pub = {n: self.key(n, KEY_FILE["site"]) for n in s.sites}
        targets = {**{b: u[b] for b in s.buyers if b != "utility"}, AGGREGATOR: u[AGGREGATOR], **{n: u[n] for n in s.sites}}
        definition = {**s.evening["community_definition"], "aggregator": {"id": AGGREGATOR, "public_key": aggregator_pub}}
        community = {**c, "role": "community", "agent_name": COMMUNITY, "community_port": self.port[COMMUNITY], "utility_url": u["utility"],
                     "buildings": s.buildings, "host_url": u["homes"], "building_urls": {b: f"{u['buildings']}/b/{b}" for b in s.buildings},
                     "roster": s.homes, "clock_waits": True, "clock_wait_idle_s": IDLE_S, "clock_extra_targets": targets,
                     "clock_wait_quiet_s": s.quiet_s, "clock_leap": s.leap, "clock_leap_max_steps": s.leap_max_steps, "clock_wait_meter": True,
                     "community": definition}
        self.folder(COMMUNITY, community, [COMMUNITY, *s.buyers], {"town_token": self.tokens[COMMUNITY],
                                                                    **{f"{b}_town_token": self.tokens[b] for b in s.buyers}})
        nodes = {**c, "community_pubkeys": [community_pub], "send_workers": 4, "host_sweep_seconds": 10 * s.step_seconds, **self.model()}
        self.folder("homes", {**nodes, "role": "host", "agent_name": "host", "host_port": self.port["homes"], "host_poll_workers": 4, "homes": s.homes},
                    s.homes, {"host_tokens.json": json.dumps({h: self.tokens[h] for h in s.homes})})
        self.folder("buildings", {**nodes, "role": "buildings", "agent_name": "buildings", "buildings_port": self.port["buildings"], "host_poll_workers": 3,
                                  "buildings": s.buildings}, s.buildings, {"host_tokens.json": json.dumps({b: self.tokens[b] for b in s.buildings})})
        request = s.evening.get("battery_request")
        communities = {COMMUNITY: {"id": s.evening["community_definition"]["id"], "limit_out_kw": s.evening["community_definition"].get("limit_out_kw"),
                                   "public_key": community_pub},
                       **{n: {"id": sp["site"]["id"], "limit_out_kw": None, "public_key": site_pub[n]} for n, sp in s.sites.items()}}
        requests = ([{"id": f"battery-{s.evening['date']}", "to": COMMUNITY, **request}] if request else []) + [r for sp in s.sites.values() for r in sp["requests"]]
        self.folder(AGGREGATOR, {**c, "role": "aggregator", "agent_name": AGGREGATOR, "aggregator_port": self.port[AGGREGATOR],
                                 "aggregator_requests": requests, "aggregator_communities": communities}, [AGGREGATOR], {"town_token": self.tokens[AGGREGATOR]})
        for n, sp in s.sites.items():
            self.folder(n, {**c, "role": "site", "agent_name": n, "site_port": self.port[n], "site": sp["site"], "site_feed": sp["feed"],
                            "site_limits": sp.get("limits") or {}, "site_aggregator": {"name": AGGREGATOR, "public_key": aggregator_pub}},
                        [n], {"town_token": self.tokens[n]})
        (s.folder / "bus.json").write_text(json.dumps({"run_id": s.run, "tokens": self.tokens, "controllers": self.controllers.pinned(self.names)}))
        (s.folder / "run.json").write_text(json.dumps({"run": s.run, "urls": self.url, "homes": s.homes, "buildings": s.buildings}, indent=1))

    # ------------------------------------------------------------------ processes
    def env(self, part: str | None) -> dict[str, str]:
        keep = ("PATH", "LANG", "LC_ALL", "TMPDIR", "HOME", "SYSTEMROOT")
        e = {k: os.environ[k] for k in keep if k in os.environ}
        e |= {"PYTHONPATH": os.pathsep.join([str(ROOT), str(ROOT / "src")]), "PYTHONUNBUFFERED": "1", "PYTHONDONTWRITEBYTECODE": "1",
              "MURMUR_DATA_DIR": str(self.s.data_dir), "MURMUR_DEVICES": self.s.devices}
        if self.s.models_dir:
            e["MURMUR_MODELS_DIR"] = str(self.s.models_dir)
        if part:
            e["MURMUR_CONFIG_DIR"] = str(self.s.folder / part)
        return e

    def launch(self, name: str, args: list[str], part: str | None) -> None:
        logs = self.s.folder / "logs"
        logs.mkdir(exist_ok=True)
        out = open(logs / f"{name}.log", "ab", buffering=0)
        self.procs[name] = subprocess.Popen([sys.executable, "-m", *args], env=self.env(part), cwd=str(ROOT), stdout=out, stderr=subprocess.STDOUT,
                                            stdin=subprocess.DEVNULL, start_new_session=True)

    def start(self) -> None:
        s = self.s
        self.launch("bus", ["demo.runner", "bus", "--host", s.host, "--port", str(self.port["bus"]), "--runs", str(s.folder / "bus.json")], None)
        if s.model.get("stand_in"):
            self.launch("model", ["demo.runner.model", "--host", s.host, "--port", str(self.port["model"]), "--log", str(s.folder / "logs" / "model_answers.jsonl")], None)
        self.wait("bus", self.url["bus"] + "/health")
        self.launch(COMMUNITY, ["murmur.agents.community.service", "run"], COMMUNITY)
        for b in s.buyers:
            self.launch(b, ["demo.runner.buyers", b, "--port", str(self.port[b])], COMMUNITY)
        self.launch("homes", ["murmur.agents.host_doors", "run"], "homes")
        if s.buildings:
            self.launch("buildings", ["murmur.agents.host_doors", "run", "--buildings"], "buildings")
        self.launch(AGGREGATOR, ["murmur.agents.aggregator", "run"], AGGREGATOR)
        for n in s.sites:
            self.launch(n, ["murmur.agents.site_service", "run"], n)
        for name in [COMMUNITY, *s.buyers, "homes", *(["buildings"] if s.buildings else []), AGGREGATOR, *s.sites]:
            self.wait(name, self.url[name] + "/health")

    def wait(self, name: str, url: str, seconds: float = 180.0) -> None:
        end = time.time() + seconds
        while time.time() < end:
            p = self.procs.get(name)
            if p is not None and p.poll() is not None:
                raise RuntimeError(f"{name} stopped with {p.returncode}: see {self.s.folder / 'logs' / (name + '.log')}")
            try:
                if httpx.get(url, timeout=2).status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            time.sleep(0.3)
        raise RuntimeError(f"{name} did not answer at {url} within {seconds:.0f} s")

    def stopped(self) -> list[str]:
        return [n for n, p in self.procs.items() if p.poll() is not None]

    def stop(self) -> None:
        """Ends every process this stack started (each in a session of its own), and nothing else."""
        for p in self.procs.values():
            if p.poll() is None:
                p.terminate()
        end = time.time() + 10
        for p in self.procs.values():
            try:
                p.wait(timeout=max(0.1, end - time.time()))
            except subprocess.TimeoutExpired:
                p.kill()
