"""The demo runner without starting a process: its configuration and refusals, run grants and the bus's grant join, the stand-in model's
answers, the state feed's schema, the run folder it writes with the keys and join tokens each part is told, and the synthetic data behind
the example."""
from __future__ import annotations

import hashlib
import json
import re
import stat
import threading
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from demo.runner import example, grants, settings
from demo.runner.bus import make_bus, runs_from
from demo.runner.feed import SCHEMA, state
from demo.runner.model import REPORT, StandIn
from demo.runner.stack import Stack
from demo.runner.synthetic import Community
from murmur.protocol import signing
from murmur.protocol.transport import join_proof

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def config(tmp: Path, **over) -> Path:
    """A runner configuration over the test fixtures: the fixture dataset, a two-line evening, the fixture sites."""
    ev = {"date": "2025-01-28", "window": ["18:00", "21:00"], "homes": ["home-01", "home-02"], "buildings": ["building-01"],
          "order_kw": {"utility": 3.0, "grid-operator": 2.0}, "feed": {}, "battery_request": None,
          "community_definition": {"id": "COMMUNITY_01", "limit_out_kw": 50.0, "meter": {}, "members": []}}
    (tmp / "evening.json").write_text(json.dumps(ev))
    raw = {"run": "run-t", "folder": str(tmp / "run"), "data_dir": str(FIXTURES / "data"), "evening": "evening.json",
           "sites": str(FIXTURES / "sites.json"), "step_seconds": 2, "ports": "free", "model": {"stand_in": True}, "events": []} | over
    path = tmp / "config.json"
    path.write_text(json.dumps(raw))
    return path


def test_a_good_configuration_loads_with_its_relative_paths_read_from_its_own_folder(tmp_path):
    s = settings.load(config(tmp_path, folder="run"))              # the run folder and the evening are named relative to the configuration file
    assert s.folder == tmp_path.resolve() / "run" and s.evening["date"] == "2025-01-28" and sorted(s.sites) == ["site-dc-01", "site-pv-01"]
    assert (s.homes, s.buildings, s.buyers, s.models_dir) == (["home-01", "home-02"], ["building-01"], ["utility", "grid-operator"], None)


@pytest.mark.parametrize("over, words", [({"step_seconds": 1}, "step_seconds must be 2 to 120"), ({"step_seconds": 121}, "step_seconds must be 2 to 120"),
                                         ({"ports": 50999}, 'ports must be "free" or a first port of 51000 or above'),
                                         ({"data_dir": "/nowhere"}, "no dataset.json in data_dir"),
                                         ({"model": {"url": "http://example.org:80", "name": "m"}}, "model must be"),
                                         ({"events": [{"at": "2025-01-28", "kind": "note"}]}, "an event's at must be YYYY-MM-DD HH:MM"),
                                         ({"events": [{"at": "2025-01-28 18:00", "kind": "earthquake"}]}, "an event's kind must be one of")])
def test_a_bad_value_stops_the_run_before_anything_starts(tmp_path, over, words):
    with pytest.raises(ValueError, match=words):
        settings.load(config(tmp_path, **over))


def test_a_run_folder_that_exists_is_refused_and_a_time_placeholder_makes_a_fresh_one(tmp_path):
    (tmp_path / "run").mkdir()
    with pytest.raises(ValueError, match="exists already"):
        settings.load(config(tmp_path))
    s = settings.load(config(tmp_path, folder=str(tmp_path / "runs" / "{time}")))
    assert s.folder.parent == tmp_path / "runs" and re.fullmatch(r"20\d{6}-\d{6}", s.folder.name)


def test_free_ports_are_distinct_and_a_block_counts_up_from_its_first(tmp_path):
    free = settings.ports(settings.load(config(tmp_path)), ["a", "b", "c", "d"])
    assert len(set(free.values())) == 4 and all(p > 0 for p in free.values())
    assert settings.ports(settings.load(config(tmp_path, ports=51000)), ["a", "b"]) == {"a": 51000, "b": 51001}     # the lowest block a configuration may name


def test_a_grant_holds_only_for_its_name_run_controller_and_session_key(tmp_path):
    c = grants.Controllers(tmp_path)
    held = c.grant("home-01", "run-t", now=1000.0)
    proof = join_proof(held["session_private"], "run-t", "home-01")
    grants.verify(held["grant"], held["grant_signature"], c.public("home-01"), "run-t", "home-01", proof, now=1001.0)
    assert stat.S_IMODE((tmp_path / "home-01.controller.key").stat().st_mode) == 0o600
    cases = [(held["grant"], c.public("home-02"), "run-t", "home-01", proof, 1001.0, "controller"),
             (held["grant"], c.public("home-01"), "run-x", "home-01", proof, 1001.0, "another run"),
             (held["grant"], c.public("home-01"), "run-t", "home-01", proof, 1000.0 + grants.TTL_S + 1, "expired"),
             (held["grant"], c.public("home-01"), "run-t", "home-01", join_proof(held["session_private"], "run-t", "home-02"), 1001.0, "session proof"),
             ({**held["grant"], "permissions": "all"}, c.public("home-01"), "run-t", "home-01", proof, 1001.0, "permissions"),
             ({**held["grant"], "expires_at": 9e99}, c.public("home-01"), "run-t", "home-01", proof, 1001.0, "controller")]
    for grant, controller, run, name, pf, now, words in cases:
        with pytest.raises(grants.Refused, match=words):
            grants.verify(grant, held["grant_signature"], controller, run, name, pf, now=now)


def test_the_bus_lets_in_a_granted_name_and_refuses_a_grant_another_controller_signed_or_a_token_it_never_gave(tmp_path):
    c = grants.Controllers(tmp_path)
    client = TestClient(make_bus(runs_from({"run_id": "run-t", "tokens": {}, "controllers": c.pinned(["home-01", "home-02"])})))
    held = c.grant("home-01", "run-t")
    body = {"name": "home-01", "grant": held["grant"], "grant_signature": held["grant_signature"],
            "session_proof": join_proof(held["session_private"], "run-t", "home-01")}
    assert client.post("/runs/run-t/join", json=body).json()["session"]
    other = grants.Controllers(tmp_path / "other").grant("home-01", "run-t")
    forged = {**body, "grant": other["grant"], "grant_signature": other["grant_signature"],
              "session_proof": join_proof(other["session_private"], "run-t", "home-01")}
    for refused in ({**body, "name": "home-02"}, forged):
        r = client.post("/runs/run-t/join", json=refused)
        assert r.status_code == 403 and "not signed by this name's controller" in r.json()["detail"]
    assert client.post("/runs/run-t/join", json={"name": "home-01", "token": ""}).status_code == 403          # a run of grants takes no token


@pytest.fixture
def stand_in():
    srv = StandIn(0, ms=0)
    threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}", srv
    srv.shutdown()
    srv.server_close()


def tool(name: str, **props) -> dict:
    return {"type": "function", "function": {"name": name, "parameters": {"type": "object", "properties": props, "required": list(props)}}}


def ask(url: str, tools: list, text: str) -> dict:
    r = httpx.post(url + "/api/chat", json={"model": "stand-in", "messages": [{"role": "user", "content": text}], "tools": tools}, trust_env=False)   # no proxy
    return r.json()["message"]["tool_calls"][0]["function"]


def test_the_stand_in_model_reads_a_note_by_its_words_and_words_a_report(stand_in):
    url, srv = stand_in
    note_tools = [tool("set_owner_wish", wish={"type": "string"}), tool("no_wish")]
    assert ask(url, note_tools, "Keep the battery full tonight") == {"name": "set_owner_wish",
                                                                    "arguments": {"wish": "keep_battery_full", "by": "", "until": "tonight"}}
    assert ask(url, note_tools, "The car needs to be ready")["arguments"]["wish"] == "keep_car_ready"
    assert ask(url, note_tools, "Thanks for everything") == {"name": "no_wish", "arguments": {}}
    assert ask(url, [tool("file_report", summary={"type": "string"})], "the facts") == {"name": "file_report", "arguments": {"summary": REPORT}}
    picked = ask(url, [tool("set_battery", action={"type": "string", "enum": ["hold", "charge"]}, kw={"type": "number"})], "anything")
    assert picked == {"name": "set_battery", "arguments": {"action": "hold", "kw": 1.0}}
    offered = [tool("set_battery", kw={"type": "number"}), tool("no_action", reason={"type": "string"})]
    assert ask(url, offered, "anything") == {"name": "no_action", "arguments": {"reason": "Nothing here needs a change, so code's plan stands."}}   # code's plan stands
    assert httpx.get(url + "/", trust_env=False).json()["chat"] == 6 and (srv.counts["note"], srv.counts["nothing"]) == (3, 1)


def test_the_state_feed_says_which_parts_answer_and_what_the_evening_has_reached():
    summary = {"now": "2025-01-28 18:20", "roster": 3, "events": {"e1": {"phase": "confirming", "window": ["2025-01-28 18:00", "2025-01-28 21:00"],
                                                                     "kw_requested": [4.0, 6.5, None], "offers": 4, "accepted": 3, "declined": 1,
                                                                     "capacity_offered_kw": 9.5, "readings": 2, "readings_expected": 18, "buyers": ["utility"]}}}
    answers = {"bus": {"ok": True}, "community": {"ready": True, "code": "c1"}, "homes": {"code": "c0"}, "buildings": None, "aggregator": None,
               "utility": {"code": "c1"}, "utility_contracts": 1, "summary": summary, "homes_names": ["home-01", "home-02"], "buildings_names": ["building-01"]}
    s = state(answers, {"bus": 99.0, "community": 98.0}, "c1", 100.0)
    assert s["schema"] == SCHEMA and s["clock"] == "2025-01-28 18:20" and s["events"] == 1
    p = s["parts"]
    assert p["town"]["up"] and p["town"]["seen_s"] == 1 and p["community"] == {"up": True, "seen_s": 2, "current": True, "ready": True, "nodes": 3}
    assert p["homes"]["current"] is False and p["homes"]["count"] == 2 and not p["buildings"]["up"] and not p["aggregator"]["up"]
    assert p["buyer_utility"]["contracts"] == 1 and not p["datacenter"]["up"]
    assert s["event"]["asked_kw"] == 6.5 and s["event"]["half_hours"] == 3 and s["event"]["offered_kw"] == 9.5 and s["event"]["buyers"] == 1


@pytest.fixture
def written(tmp_path):
    """The run folder the stack writes for the test configuration, and the stack that wrote it."""
    s = settings.load(config(tmp_path))
    s.folder.mkdir()
    k = Stack(s)
    k.write()
    return s, k


def read(s: settings.Settings, *path: str):
    return json.loads(s.folder.joinpath(*path).read_text())


def test_the_run_folder_holds_each_parts_configuration_and_grants_the_bus_will_accept(written):
    s, k = written
    community = read(s, "community", "agent.json")
    assert community["roster"] == ["home-01", "home-02"] and community["clock_waits"] is True
    assert set(community["clock_extra_targets"]) == {"grid-operator", "aggregator", "site-pv-01", "site-dc-01"}
    assert community["utility_url"] == k.url["utility"] and community["bind_host"] == s.host == "127.0.0.1"   # every address from the run's settings
    homes = read(s, "homes", "agent.json")
    assert homes["llm_enabled"] and homes["homes"] == ["home-01", "home-02"] and homes["llm_url"] == k.url["model"]
    bus = read(s, "bus.json")
    for part, names in (("community", ["community", "utility", "grid-operator"]), ("homes", ["home-01", "home-02"]), ("buildings", ["building-01"]),
                        ("aggregator", ["aggregator"]), ("site-pv-01", ["site-pv-01"]), ("site-dc-01", ["site-dc-01"])):
        held = read(s, part, "secrets", "town_grants.json")
        assert sorted(held) == sorted(names)
        assert stat.S_IMODE((s.folder / part / "secrets" / "town_grants.json").stat().st_mode) == 0o600
        for n in names:
            grants.verify(held[n]["grant"], held[n]["grant_signature"], bus["controllers"][n], "run-t", n, join_proof(held[n]["session_private"], "run-t", n))
    agg = read(s, "aggregator", "agent.json")
    assert sorted(agg["aggregator_communities"]) == ["community", "site-dc-01", "site-pv-01"]
    assert len(set(k.port.values())) == len(k.port) and min(k.port.values()) > 0      # a free port for every part, none shared


def test_each_part_is_told_the_keys_and_the_join_tokens_of_those_it_must_trust(written):
    s, _ = written

    def key(part: str, file: str) -> str:
        """The public half of the key a part signs with, as it lies in the part's own secrets."""
        return signing.public_hex(signing.load_or_create(s.folder / part / "secrets" / file))

    def secret(part: str, name: str) -> str:
        return (s.folder / part / "secrets" / name).read_text()
    community, aggregator, tokens = key("community", "signing.key"), key("aggregator", "aggregator.key"), read(s, "bus.json")["tokens"]
    assert read(s, "homes", "agent.json")["community_pubkeys"] == read(s, "buildings", "agent.json")["community_pubkeys"] == [community]
    assert read(s, "community", "agent.json")["community"]["aggregator"] == {"id": "aggregator", "public_key": aggregator}
    assert {n: c["public_key"] for n, c in read(s, "aggregator", "agent.json")["aggregator_communities"].items()} == {
        "community": community, "site-pv-01": key("site-pv-01", "site.key"), "site-dc-01": key("site-dc-01", "site.key")}
    for n in ("site-pv-01", "site-dc-01"):
        assert read(s, n, "agent.json")["site_aggregator"] == {"name": "aggregator", "public_key": aggregator} and secret(n, "town_token") == tokens[n]
    assert [secret("community", f) for f in ("town_token", "utility_town_token", "grid-operator_town_token")] + [secret("aggregator", "town_token")] == \
        [tokens["community"], tokens["utility"], tokens["grid-operator"], tokens["aggregator"]]
    assert json.loads(secret("homes", "host_tokens.json")) == {h: tokens[h] for h in ("home-01", "home-02")}
    assert json.loads(secret("buildings", "host_tokens.json")) == {"building-01": tokens["building-01"]} and len(set(tokens.values())) == len(tokens) == 9


def digest(folder: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(folder.rglob("*")):
        if p.is_file():
            h.update(str(p.relative_to(folder)).encode())
            h.update(p.read_bytes())
    return h.hexdigest()


def test_the_synthetic_community_over_the_fixtures_two_days_is_the_committed_fixtures(tmp_path):
    Community(("2025-01-27", "2025-01-28")).write(tmp_path / "data", tmp_path / "sites.json")
    assert digest(tmp_path / "data") == digest(FIXTURES / "data")
    assert (tmp_path / "sites.json").read_bytes() == (FIXTURES / "sites.json").read_bytes()


def test_the_example_evening_covers_its_clock_from_the_day_before_to_the_morning_after(tmp_path):
    example.write(tmp_path)
    ev = json.loads((tmp_path / "evening.json").read_text())
    meta = json.loads((tmp_path / "data" / "dataset.json").read_text())
    assert meta["range"] == ["2025-01-05", "2025-01-29"] and meta["default_event"] == ev["date"] == "2025-01-28"
    assert min(ev["feed"]) == "2025-01-27 10:00" and max(ev["feed"]) == "2025-01-29 02:45"
    assert max(ev["community_definition"]["meter"]) < min(ev["feed"])
    assert {m["member"] for m in ev["community_definition"]["members"]} == set(ev["homes"]) | set(ev["buildings"])
