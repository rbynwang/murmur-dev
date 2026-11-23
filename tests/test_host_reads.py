"""The hosts' record door (agents/host_reads.py), on a node host's own app: each thinking node's decision log read from a place on, the cuts that keep an
answer small and a long run of hex out of it, and the 404 of a node that keeps no log. The door asks of a caller what the host's other read doors ask, which
is nothing: as /agents/{name}/receipts, it is a GET of an app whose one door (protocol/doors.py) asks the control token of POSTs only."""
from __future__ import annotations

import json
import re
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from murmur import config
from murmur.agents import host, host_doors, host_reads
from murmur.agents.building import BuildingHost
from murmur.node import record
from murmur.protocol import doors

HOMES = ["home-01", "home-02", "home-03"]
THINKING = ["home-01", "home-02"]              # home-03 runs on code alone, so it keeps no log
TS = "2025-01-27 17:00"                        # a Monday of the fixture dataset
NOTE = "Please keep the battery full tonight."
HASH, KEY = "0123456789abcdef" * 4, "FEDCBA9876543210" * 3          # 64 hex characters, as a hash is written, and 48
LONG_HEX = re.compile(r"[0-9a-fA-F]{48,}")
KINDS = ("step", "step_io", "decision", "started", "act", "finished", "tool", "receipt", "told", "report", "report_sent", "new_run", "repeat")
READ_AS = {"calls": [{"name": "set_owner_wish", "args": {"wish": "keep_battery_full", "until": "tonight", "by": "", "reason": "The note asks for it."}}],
           "text": "", "ms": 3, "error": None, "tokens": {"in": 100, "out": 10}}


@pytest.fixture
def hosts(tmp_path, monkeypatch):
    """Makes a node host over the fixture dataset in the test's own configuration folder, set up as the demo runner sets one up, with no bus and no model
    server: make(kind, thinking) gives (the host, its doors). A thinking node's model is scripted: it reads every note as "keep the battery full".
    A second make() in one test is the host started again over the same folder."""
    monkeypatch.setattr(config, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(record, "model_version", lambda name, url: {"name": name, "digest": "scripted"})
    (tmp_path / "secrets").mkdir()
    made = []

    def make(kind: str = "homes", thinking: bool = True):
        names = HOMES if kind == "homes" else ["building-01"]
        (tmp_path / "secrets" / "host_tokens.json").write_text(json.dumps(dict.fromkeys(names, "t")))
        (tmp_path / "agent.json").write_text(json.dumps({
            "agent_name": kind, "homes": HOMES, "buildings": ["building-01"], "town_url": "http://testserver", "town_run_id": "run", "replay_start": TS,
            "replay_loop_days": 0, "control_mode": "rolling", "buyers": ["utility"], "report_rule": "exception", "llm_enabled": thinking,
            "llm_url": "http://model.invalid", "llm_model": "scripted", "thinking_homes": THINKING}))
        f = (host.NodeHost if kind == "homes" else BuildingHost)()
        if f.mind:
            f.mind.client.ask = lambda system, tools, text: dict(READ_AS)
        made.append(f)
        return f, TestClient(host_doors.build_app(f))
    yield make
    for f in made:
        f.pool.shutdown(wait=False)
        f.http.close()
        if f.mind:
            f.mind.client.http.close()


def read(door: TestClient, name: str = "home-01", **params) -> dict:
    r = door.get(f"/agents/{name}/record", params=params)
    assert r.status_code == 200
    return r.json()


def fill(log: record.Log, n: int) -> record.Log:
    """n more rows in a node's log, of every kind in turn, each written as a node writes a row."""
    for i in range(n):
        log.add(KINDS[i % len(KINDS)], ts=TS, i=i)
    return log


def shown(row: dict) -> dict:
    """A row of the log as the door gives it when nothing but its chain is long hex."""
    return {**row, "prev": row["prev"][:16], "hash": row["hash"][:16]}


# ---------------------------------------------------------------------------------------------------------------- which nodes, and the 404
@pytest.mark.parametrize("kind, node, reset", [("homes", "home-01", "/demo/reset"), ("buildings", "building-01", "/b/building-01/demo/reset")])
def test_both_hosts_serve_the_door_and_a_log_with_no_row_answers_empty_at_place_0(hosts, kind, node, reset):
    f, door = hosts(kind)
    assert node in f.logs and door.get("/agents/record").json() == {"rows": dict.fromkeys(f.logs, 0)}
    assert read(door, node) == {"node": node, "rows": [], "next": 0}
    assert read(door, node, after=7) == {"node": node, "rows": [], "next": 0}          # a place beyond the log's end: `next` says where the log is
    assert door.post(reset).status_code == 200                                         # a new run: the first row the node itself writes
    log = f.logs[node]
    assert read(door, node) == {"node": node, "next": 1, "rows": [{"n": 1, "kind": "new_run", "node": node, "prev": "", "hash": log.rows[0]["hash"][:16]}]}
    assert door.get("/agents/record").json()["rows"][node] == 1 and log.path == config.state_dir() / "decisions" / f"{node}.jsonl"


def test_a_node_that_keeps_no_log_is_404_where_the_receipts_door_is_404_too(hosts):
    f, door = hosts()
    assert sorted(f.logs) == THINKING and door.get("/agents/record").json() == {"rows": {"home-01": 0, "home-02": 0}}
    for name in ("home-03", "home-99", "record"):                  # one that runs on code alone, and two the host does not run
        r = door.get(f"/agents/{name}/record", params={"after": 0, "limit": 5})
        assert (r.status_code, r.json()) == (404, {"detail": "this node keeps no record here"})
        assert door.get(f"/agents/{name}/receipts").status_code == 404
    f, door = hosts(thinking=False)                                # no node thinks: no log at all
    assert f.logs == {} and door.get("/agents/record").json() == {"rows": {}} and door.get("/agents/home-01/record").status_code == 404


def test_mount_adds_two_get_doors_and_the_hosts_other_agent_doors_answer_as_before(hosts):
    app = FastAPI()
    host_reads.mount(app, SimpleNamespace(logs={}))
    assert {(r.path, tuple(r.methods)) for r in app.routes if r.path.startswith("/agents")} == {("/agents/record", ("GET",)), ("/agents/{name}/record", ("GET",))}
    f, door = hosts()
    paths = [r.path for r in door.app.routes]
    assert paths.count("/agents/record") == paths.count("/agents/{name}/record") == 1
    assert sorted(door.get("/agents").json()["nodes"]) == THINKING and door.get("/agents/home-01/receipts").json()["receipts"] == []


# ---------------------------------------------------------------------------------------------------------------- the cursor and the limit
def test_the_cursor_reads_from_any_place_on_with_no_gap_and_no_repeat_and_follows_a_log_that_grows(hosts):
    f, door = hosts()
    log = fill(f.logs["home-01"], 13)
    whole = read(door)
    assert [(r["n"], r["kind"], r["i"]) for r in whole["rows"]] == [(i + 1, k, i) for i, k in enumerate(KINDS)] and whole["next"] == 13       # every kind: none is left out
    assert whole["rows"] == [shown(r) for r in log.rows]
    for after in range(16):
        for limit in (1, 2, 5, 13, 200):
            want = whole["rows"][after:after + limit]              # the rows with n > after, `limit` at most
            assert read(door, after=after, limit=limit) == {"node": "home-01", "rows": want, "next": want[-1]["n"] if want else min(after, 13)}
    pages, at = [], 0
    while (got := read(door, after=at, limit=5))["rows"]:          # a reader's loop: ask with the last answer's `next` until nothing comes
        pages.append([r["n"] for r in got["rows"]])
        at = got["next"]
    assert pages == [[1, 2, 3, 4, 5], [6, 7, 8, 9, 10], [11, 12, 13]] and at == 13 and read(door, after=at) == {"node": "home-01", "rows": [], "next": 13}
    log.add("told", ts=TS, point="note", to="owner", text="Got it.")
    log.add("report", ts=TS, summary="The sale ran as the plan said.")
    got = read(door, after=at)                                     # the log grew: the old place gives the new rows and nothing else
    assert [(r["n"], r["kind"]) for r in got["rows"]] == [(14, "told"), (15, "report")] and got["next"] == 15
    assert door.get("/agents/record").json() == {"rows": {"home-01": 15, "home-02": 0}}
    assert read(door, "home-02", after=15) == {"node": "home-02", "rows": [], "next": 0}       # each node its own log and its own place


def test_an_answer_holds_200_rows_at_most_and_a_place_or_a_limit_that_cannot_be_read_is_refused(hosts):
    f, door = hosts()
    f.logs["home-01"] = fill(record.Log("home-01"), 205)           # the door reads the host's logs as they are when it is asked
    first = read(door)
    assert host_reads.LIMIT == 200 and [r["n"] for r in first["rows"]] == list(range(1, 201)) and first["next"] == 200
    assert read(door, limit=200) == first and [r["n"] for r in read(door, limit=1)["rows"]] == [1]
    rest = read(door, after=first["next"])
    assert [r["n"] for r in rest["rows"]] == [201, 202, 203, 204, 205] and rest["next"] == 205
    for bad in ({"limit": 201}, {"limit": 0}, {"limit": -1}, {"limit": "many"}, {"after": -1}, {"after": "x"}, {"after": 1.5}):
        assert door.get("/agents/home-01/record", params=bad).status_code == 422


def test_a_log_file_with_a_broken_line_is_served_by_place_so_the_cursor_holds(hosts):
    f, door = hosts()
    path = fill(f.logs["home-01"], 3).path
    lines = path.read_text().splitlines()
    path.write_text("\n".join([lines[0], lines[1][:60], lines[1][60:], lines[2]]) + "\n")      # the second row's line broken in two
    f, door = hosts()                                              # the host starts again and reads the file back
    assert [r["n"] for r in f.logs["home-01"].rows] == [1, 2, 3, 3]                            # the last row still says its old place
    got = door.get("/agents/home-01/record")
    assert [(r["n"], r["kind"]) for r in got.json()["rows"]] == [(1, "step"), (2, "unreadable"), (3, "unreadable"), (4, "decision")] and got.json()["next"] == 4
    assert read(door, after=3)["rows"] == got.json()["rows"][3:] and not LONG_HEX.search(got.text)      # the broken line's text held a hash


# ---------------------------------------------------------------------------------------------------------------- the cuts
def test_a_run_of_48_hex_characters_or_more_is_cut_to_its_first_16_wherever_it_stands_and_a_shorter_one_stays(hosts):
    f, door = hosts()
    log, under = f.logs["home-01"], "ab" * 23 + "c"                # 47 hex characters: not long enough to cut
    seal = {"nonce": "0c9341a0a8c7e0b0", "seal": "e7d63f0139ab4ad7"}
    log.add("receipt", ts=TS, asked={"question": HASH}, facts=[{"says": f"signed {KEY} by the owner"}, [HASH, under, 7, None]], seal=seal, joined=f"{HASH}-{KEY}z{under}",
            **{HASH: "under a field's long name"})
    got = door.get("/agents/home-01/record")
    assert got.json()["rows"] == [{"n": 1, "kind": "receipt", "node": "home-01", "ts": TS, "asked": {"question": "0123456789abcdef"},
                                   "facts": [{"says": "signed FEDCBA9876543210 by the owner"}, ["0123456789abcdef", under, 7, None]], "seal": seal,
                                   "joined": f"0123456789abcdef-FEDCBA9876543210z{under}", "0123456789abcdef": "under a field's long name", "prev": "",
                                   "hash": log.rows[0]["hash"][:16]}]
    assert len(log.rows[0]["hash"]) == 64 and log.rows[0]["asked"] == {"question": HASH}       # the log's own row is whole, as it was
    fill(log, 12)
    got = door.get("/agents/home-01/record")
    assert len(got.json()["rows"]) == 13 and not LONG_HEX.search(got.text) and not LONG_HEX.search(door.get("/agents/record").text)


def test_a_note_a_thinking_node_reads_comes_out_with_the_models_tools_as_names_and_the_log_itself_stays_whole(hosts):
    f, door = hosts()
    door.post("/demo/clock", json={"start": TS, "at": TS, "step_seconds": 2.0, "loop_days": 0, "keep": False, "hold": True})
    door.post("/demo/reset")
    assert door.post("/demo/scenario", json={"override": {"home": "home-01", "kind": "note", "value": NOTE, "source": "owner's phone"}}).status_code == 200
    f.agent_step("home-01", TS)                                    # the node's own step: its note reader asks the model, and its agent writes what it did
    path = f.logs["home-01"].path
    before = path.read_bytes()
    file = [json.loads(x) for x in before.splitlines()]
    got = read(door)
    assert [(r["n"], r["kind"], r.get("ts")) for r in got["rows"]] == [(1, "new_run", None), (2, "model", None), (3, "decision", TS), (4, "receipt", TS)] and got["next"] == 4
    model = got["rows"][1]
    assert model["tools"] == ["set_owner_wish", "no_wish"] == [t["function"]["name"] for t in file[1]["tools"]] and all("parameters" in t["function"] for t in file[1]["tools"])
    assert model == {**shown(file[1]), "tools": ["set_owner_wish", "no_wish"], "asked": file[1]["asked"][:16]} and len(file[1]["asked"]) == 64
    assert model["system"].startswith("You read a note") and NOTE in model["text"] and model["answer"] == READ_AS
    assert [got["rows"][i] for i in (0, 2, 3)] == [shown(file[i]) for i in (0, 2, 3)] and got["rows"][2]["why"] == "owner's note" and got["rows"][3]["point"] == "note"
    assert path.read_bytes() == before                             # a read changes nothing on disk
    f, door = hosts()                                              # started again over the same folder: the same rows, read back from the file
    assert read(door) == got and path.read_bytes() == before


def test_a_model_row_whose_tools_are_no_definitions_still_comes_out_and_another_kinds_tools_are_its_own(hosts):
    f, door = hosts()
    log, report = f.logs["home-01"], {"type": "function", "function": {"name": "file_report", "description": "Files the report.", "parameters": {"type": "object"}}}
    log.add("model", system="s", text="t", tools=[report, {"name": "bare"}, {"function": {}}, {"function": "words"}, "words", 7], answer={"calls": []})
    log.add("model", tools=None)
    log.add("model")
    log.add("tool", tools=[report])
    assert [r["tools"] for r in read(door)["rows"]] == [["file_report", "bare", "", "", "", ""], [], [], [report]]


def test_a_row_over_16000_characters_keeps_its_head_and_says_it_is_cut_and_the_place_goes_on_past_it(hosts):
    f, door = hosts()
    log = f.logs["home-01"]
    log.add("step", step="7 watch", ts=TS, state="entered")
    log.add("act", step="7 watch", ts=TS, tool="set_battery", guard_lines=[{"file": "guard.py", "text": "x" * 80}] * 200)      # a device call with its guard's lines
    log.add("model", system="s" * 9000, text="t" * 9000, tools=[], answer={"calls": []})       # a model row has no ts and no step to keep
    log.add("step", step="7 watch", ts=TS, state="done")
    assert [len(record.dumps(r)) > 16_000 for r in log.rows] == [False, True, True, False]
    got = read(door)
    assert got["rows"] == [shown(log.rows[0]), {"n": 2, "kind": "act", "node": "home-01", "ts": TS, "step": "7 watch", "cut": True},
                           {"n": 3, "kind": "model", "node": "home-01", "cut": True}, shown(log.rows[3])] and got["next"] == 4
    assert read(door, after=1, limit=2) == {"node": "home-01", "rows": got["rows"][1:3], "next": 3}


def test_the_size_is_the_served_rows_own_16000_stays_whole_and_what_the_other_cuts_bring_under_it_is_served(hosts):
    base = {"kind": "tool", "node": "home-01", "ts": TS, "step": "8 exception", "pad": "", "prev": "", "hash": "h"}
    room = 16_000 - len(record.dumps({**base, "n": 3}))
    assert host_reads.ROW_MAX == 16_000 and len(record.dumps(host_reads.served({**base, "pad": "x" * room}, 3))) == 16_000
    assert host_reads.served({**base, "pad": "x" * room}, 3) == {**base, "pad": "x" * room, "n": 3}
    assert host_reads.served({**base, "pad": "x" * (room + 1)}, 3) == {"n": 3, "kind": "tool", "node": "home-01", "ts": TS, "step": "8 exception", "cut": True}
    f, door = hosts()
    log = f.logs["home-01"]
    log.add("model", system="s", text="t", tools=[{"type": "function", "function": {"name": "set_owner_wish", "description": "d" * 20_000}}], answer={"calls": []})
    log.add("finished", key=HASH, result={"hashes": [HASH] * 400})
    assert all(len(record.dumps(r)) > 16_000 for r in log.rows)    # over the size in the log: the definitions of one, the hashes of the other
    rows = read(door)["rows"]
    assert rows == [{**shown(log.rows[0]), "tools": ["set_owner_wish"]}, {**shown(log.rows[1]), "key": HASH[:16], "result": {"hashes": [HASH[:16]] * 400}}]


# ---------------------------------------------------------------------------------------------------------------- what the door asks of a caller
def test_the_door_asks_of_a_caller_what_the_receipts_door_asks_which_is_nothing_while_a_post_door_asks_the_control_token(hosts):
    f, door = hosts()
    fill(f.logs["home-01"], 3)
    token, reads = config.CONFIG_DIR / "secrets" / doors.TOKEN_FILE, ("/agents/home-01/receipts", "/agents/record", "/agents/home-01/record")
    clock, callers = {"start": TS, "loop_days": 0, "hold": True}, ({}, {doors.HEADER: "not-the-token"}, {doors.HEADER: "door-token"})
    plain = [door.get(p).json() for p in reads]
    assert door.get("/health").json()["doors"] == "open" and plain[0]["receipts"] == [] and plain[1] == {"rows": {"home-01": 3, "home-02": 0}} and plain[2]["next"] == 3
    token.write_text("door-token\n")
    assert door.get("/health").json()["doors"] == "token"
    assert [door.post("/demo/clock", json=clock, headers=h).status_code for h in callers] == [401, 401, 200]         # a POST door asks the token now
    for headers in callers:                                        # of a read nothing is asked, whatever it sends
        got = [door.get(p, headers=headers) for p in reads]
        assert [r.status_code for r in got] == [200, 200, 200] and [r.json() for r in got] == plain
    token.write_text("")                                           # an empty token file shuts every POST door, and a read is still not asked
    assert [door.post("/demo/clock", json=clock, headers=h).status_code for h in callers] == [401, 401, 401]
    assert [door.get(p).json() for p in reads] == plain
    assert [door.request(m, p).status_code for m in ("POST", "PUT", "DELETE") for p in reads[1:]] == [405] * 6       # a read door only
