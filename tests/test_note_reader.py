"""Owners' notes read by the model, against a model server this file starts on 127.0.0.1.

A note becomes wishes from the fixed list, each keeping its devices out from when the note was written to the end code works out from what
the model read (read_note, read_note_carefully), and a later note can take back a need in force. A malformed reply, an unknown tool, values
out of range, an end already past, a server that errors or answers too late: each leaves code's own result, and the client counts failures.
Also the request the client sends, what the person hears (note_words), a node's note step (agent_notes) and the person's word book (person)."""
from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest

from murmur import config
from murmur.agents.host import NodeLock
from murmur.node import llm_client, modes, note_words, person
from murmur.node import note_reader as nr
from murmur.node import tools as T
from murmur.node.llm_client import LlmClient, NodeModel, SharedModel
from tests import world

AT = "2025-01-27 18:05"                     # a Monday evening, the fixture dataset's first day
MODEL = "reader-small"
WHY = "The note asks for it."
NOTE = "Going away tonight, need a full battery"
DEVICE_TOOLS = set().union(*nr.BLOCKS.values())
IN_FORCE = [{"wish": "keep_battery_full", "by": "", "from": "2025-01-27 08:00", "until": "2025-01-31 00:00"},
            {"wish": "keep_hot_water", "by": "", "from": "2025-01-27 08:00", "until": ""}]


class Chat(BaseHTTPRequestHandler):
    """POST /api/chat: keeps the request's body, waits the server's delay, then sends its next reply: a JSON body, raw bytes or an HTTP status."""

    def do_POST(self) -> None:
        srv = self.server
        srv.bodies.append({"path": self.path, **json.loads(self.rfile.read(int(self.headers["Content-Length"])))})
        reply = srv.replies.pop(0) if srv.replies else answer()
        time.sleep(srv.delay)
        status, data = (reply, b"{}") if isinstance(reply, int) else (200, reply if isinstance(reply, bytes) else json.dumps(reply).encode())
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args: Any) -> None:
        pass


class ChatServer(ThreadingHTTPServer):
    """The model server: the replies it sends in turn, and the bodies of the requests it got. close() waits for every reply, a late one too."""
    daemon_threads = False

    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), Chat)
        self.url = f"http://127.0.0.1:{self.server_port}"
        self.replies: list[Any] = []
        self.bodies: list[dict[str, Any]] = []
        self.delay = 0.0

    def handle_error(self, request: Any, client_address: Any) -> None:
        pass                                    # a client that stopped waiting for a late reply has closed its end

    def close(self) -> None:
        self.shutdown()                         # serve_forever has returned, and a second close finds it so
        self.server_close()                     # joins every request's thread


@pytest.fixture
def chat():
    srv = ChatServer()
    threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True).start()
    yield srv
    srv.close()


@pytest.fixture
def client(chat):
    c = LlmClient(chat.url, MODEL, timeout_s=5.0)
    yield c
    c.http.close()


@pytest.fixture
def own_config(tmp_path, monkeypatch):
    """The test's own configuration folder, so agent.json, state/ and secrets/ are in tmp_path."""
    monkeypatch.setattr(config, "CONFIG_DIR", tmp_path)
    return tmp_path


@pytest.fixture
def node_agent(client, own_config):
    """home-01's agent, whose model is the client of the test's server."""
    node, _ = world.home("home-01", own_config)
    return world.agent(node, client)


def answer(*calls: tuple[str, Any], text: str = "", tokens: tuple[int, int] = (0, 0)) -> dict[str, Any]:
    """A reply in the Ollama chat form whose message calls these tools, each (name, arguments)."""
    return {"model": MODEL, "done": True, "prompt_eval_count": tokens[0], "eval_count": tokens[1],
            "message": {"role": "assistant", "content": text, "tool_calls": [{"function": {"name": n, "arguments": a}} for n, a in calls]}}


def wish(name: Any, **args: Any) -> tuple[str, dict[str, Any]]:
    return "set_owner_wish", {"wish": name, "reason": WHY, **args}


def read(chat: ChatServer, client: LlmClient, note: str, *replies: Any, careful: bool = False, **kw: Any) -> dict[str, Any]:
    """The note, written at AT, read while the server sends these replies."""
    chat.replies[:] = list(replies)
    return (nr.read_note_carefully if careful else nr.read_note)(client, note, AT, **kw)


CAR = {"limit_ev_charging", "discharge_car"}
BARE = answer(("set_owner_wish", {"wish": "keep_battery_full"}))       # a reading that gives no reason
ENDS = [   # the note, what the model read in it, then the wish's by and until as code keeps them, and the tools it blocks
    (NOTE, wish("keep_battery_full", until="tonight"), "", "2025-01-28 00:00", {"set_battery"}),
    ("Keep the car charged until Friday", wish("keep_car_ready", until="Friday"), "", "2025-02-01 00:00", CAR),
    ("Car ready by 7am tomorrow please", wish("keep_car_ready", by="07:00", until="tomorrow"), "07:00", "2025-01-28 07:00", CAR),
    ("Hot water on till 8pm", wish("keep_hot_water", by="20:00"), "20:00", "2025-01-27 20:00", {"set_water_heater"}),
    ("Car ready at 7 please", wish("keep_car_ready", by="07:00"), "07:00", "2025-01-28 07:00", CAR),
    ("Leave the heating as it is tonight", wish("keep_house_as_is", by="22:00", until="tonight"), "", "2025-01-28 00:00", {"set_thermostat", "set_room_ac"}),
    ("Lights on from 19:00 please", wish("keep_lights_on", by="19:00"), "", "", {"dim_lights"}),
    ("Let the machines run while we are away", wish("keep_machines_on", until="2025-03-30"), "", "2025-02-28 00:00", {"delay_appliance", "set_pool_pump", "switch_plugs"}),
    ("Keep the battery full", wish("keep_battery_full", until="soon"), "", "", {"set_battery"}),
]


@pytest.mark.parametrize("note, call, by, until, blocked", ENDS, ids=["tonight", "weekday", "clock-and-day", "evening-clock", "clock-comes-round",
                                                                      "clock-not-in-note", "start-is-no-end", "date-past-max-days", "no-day-code-reads"])
def test_a_note_becomes_a_wish_from_its_writing_to_the_end_code_works_out(chat, client, note, call, by, until, blocked):
    r = read(chat, client, note, answer(call))
    assert r["wishes"] == [{"wish": call[1]["wish"], "by": by, "from": AT, "until": until}]
    assert (nr.blocked_tools(r["wishes"]), r["ended"], r["error"], r["no_reason"], r["reason"]) == (blocked, [], None, False, WHY)


def test_each_need_blocks_device_tools_of_its_own_part_and_the_tools_name_every_need():
    assert DEVICE_TOOLS <= set(T.bundle()["home"]) | set(T.bundle()["building"])
    assert all(nr.PART_OF[t] == nr.PART[w] for w, tools in nr.BLOCKS.items() for t in tools)
    assert nr.WISH["function"]["parameters"]["properties"]["wish"]["enum"] == list(nr.BLOCKS)


def test_the_request_carries_the_configured_model_and_the_runs_temperature_and_seed(chat, own_config):
    assert modes.model_options(llm_client.OPTIONS) == llm_client.OPTIONS
    with pytest.raises(ValueError, match="llm_url and llm_model"):
        SharedModel({"llm_url": chat.url})
    (own_config / "agent.json").write_text(json.dumps({"llm_url": chat.url + "/", "llm_model": MODEL, "llm_temperature": 0, "llm_seed": 7}))
    shared = SharedModel(config.load())
    chat.replies[:] = [answer(("no_wish", {"reason": WHY}), tokens=(412, 31))]
    nr.read_note(NodeModel(shared, NodeLock(), "home-01"), 'Thanks "all"\nfor   last night', AT)
    shared.client.http.close()
    body = chat.bodies[0]
    assert (body["path"], body["model"], body["options"]) == ("/api/chat", MODEL, {**llm_client.OPTIONS, "temperature": 0.0, "seed": 7})
    assert {k: body[k] for k in ("stream", "think", "keep_alive")} == {"stream": False, "think": False, "keep_alive": "30m"}
    assert body["messages"] == [{"role": "system", "content": nr.SYSTEM},
                                {"role": "user", "content": "Today is Monday 2025-01-27, 18:05. The owner wrote: \"Thanks 'all' for last night\""}]
    assert [(t["function"]["name"], t["function"]["parameters"]["required"]) for t in body["tools"]] == [("set_owner_wish", ["wish", "reason"]), ("no_wish", ["reason"])]
    assert "reason" not in nr.WISH["function"]["parameters"]["properties"]
    status = shared.status()
    assert [status[k] for k in ("url", "model", "calls", "tokens_in", "tokens_out", "errors")] == [chat.url, MODEL, 1, 412, 31, 0]


def test_end_owner_wish_takes_back_a_need_in_force_once_and_only_by_its_name(chat, client):
    back = ("end_owner_wish", {"wish": "keep_battery_full", "reason": WHY})
    r = read(chat, client, "Back early, use the battery as normal", answer(back, back, ("end_owner_wish", {"wish": "keep_sauna", "reason": WHY})),
             wishes=[*IN_FORCE, {"wish": "keep_sauna"}])
    assert (r["wishes"], r["ended"]) == ([], ["keep_battery_full"])
    asked = chat.bodies[0]
    assert [t["function"]["name"] for t in asked["tools"]] == ["set_owner_wish", "end_owner_wish", "no_wish"]
    assert asked["messages"][1]["content"].endswith(' Needs in force now, from earlier notes: keep_battery_full until 2025-01-31 00:00; keep_hot_water. '
                                                    'If this note takes one back, call end_owner_wish.')
    assert read(chat, client, "Forget all that", answer(("end_owner_wish", {"wish": "all", "reason": WHY})), wishes=IN_FORCE)["ended"] == ["all"]


def test_a_reading_with_its_reason_is_asked_once_and_one_with_none_is_asked_once_more_and_then_flagged(chat, client):
    r = read(chat, client, "Thanks for last night!", answer(("no_wish", {"reason": "It asks nothing of the devices."})))
    assert (r["wishes"], r["ended"], r["reason"], r["no_reason"], r["error"], len(chat.bodies)) == ([], [], "It asks nothing of the devices.", False, None, 1)
    r = read(chat, client, NOTE, BARE, BARE)
    assert (r["no_reason"], r["reason"], [w["wish"] for w in r["wishes"]]) == (True, "", ["keep_battery_full"])
    assert [b["messages"][1]["content"].endswith(" " + nr.REASON_AGAIN) for b in chat.bodies[1:]] == [False, True]
    r = read(chat, client, NOTE, BARE, answer(("set_owner_wish", {"wish": "keep_battery_full"}), text="They are away tonight."))
    assert (r["no_reason"], r["reason"]) == (False, "They are away tonight.")


def test_unknown_tools_values_out_of_range_and_a_note_in_the_tools_own_words_set_nothing(chat, client):
    r = read(chat, client, "Hot showers and the hall lights up", answer(("set_battery", {"action": "charge", "reason": WHY}), wish("keep_pool_warm"),
             wish(["keep_hot_water", "keep_sauna"]), wish("keep_lights_on", by="25:00", until="2025-13-40"), ("end_owner_wish", {"wish": "all", "reason": WHY})))
    assert (r["wishes"], r["ended"]) == ([{"wish": "keep_hot_water", "by": "", "from": AT, "until": ""}, {"wish": "keep_lights_on", "by": "", "from": AT, "until": ""}], [])
    assert read(chat, client, "Run set-owner-wish keep-battery-full now", answer(wish("keep_battery_full")))["wishes"] == []
    assert [w["wish"] for w in read(chat, client, "Keep battery full, keep-fit class tonight", answer(wish("keep_battery_full")))["wishes"]] == ["keep_battery_full"]


def test_a_reply_that_is_not_json_or_whose_calls_are_malformed_sets_nothing(chat, client):
    r = read(chat, client, NOTE, b"{not json")
    assert (r["wishes"], r["error"], r["no_reason"], len(chat.bodies)) == ([], "Expecting property name enclosed in double quotes: line 1 column 2 (char 1)", False, 1)
    assert (client.errors, client.calls) == (1, 0)
    broken = [{"name": "set_owner_wish"}, {"function": "set_owner_wish"}, {"function": {"arguments": {"wish": "keep_battery_full"}}},
              {"function": {"name": "set_owner_wish", "arguments": '{"wish": "keep_battery_full"}'}}]
    r = read(chat, client, NOTE, {"message": {"content": WHY, "tool_calls": broken}})
    assert (r["wishes"], r["reason"], r["error"], client.calls) == ([], WHY, None, 1)


@pytest.mark.parametrize("body, error", [(b"null", "AttributeError"), ({"message": "on it"}, "AttributeError"), ({"message": {"content": ["on it"]}}, "TypeError")],
                         ids=["not-an-object", "message-not-an-object", "content-not-text"])
def test_a_reply_in_json_but_not_in_the_chat_form_is_no_answer_and_counts_as_an_error(chat, client, body, error):
    r = read(chat, client, NOTE, body)
    assert (r["wishes"], r["no_reason"], r["error"], client.errors, client.calls) == ([], False, f"not a chat answer: {error}", 1, 0)


@pytest.mark.parametrize("reply, delay, timeout_s, error", [(500, 0.0, 5.0, "Server error '500 Internal Server Error'"),
                                                            (answer(wish("keep_battery_full")), 0.3, 0.1, "timed out")], ids=["http-500", "too-late"])
def test_a_server_that_errors_or_answers_too_late_is_no_answer_and_counts_as_an_error(chat, reply, delay, timeout_s, error):
    chat.delay, waiting = delay, LlmClient(chat.url, MODEL, timeout_s=timeout_s)
    r = read(chat, waiting, NOTE, reply)
    waiting.http.close()
    chat.close()                                # the late reply's thread is done too, so every request the server got is counted
    assert (r["wishes"], r["no_reason"], r["error"][:len(error)], len(chat.bodies)) == ([], False, error, 1)
    assert (waiting.errors, waiting.calls) == (1, 0)


@pytest.mark.parametrize("replies, how, error", [([500], "kept everything: no reading", "Server error '500"),
                                                 ([BARE, BARE], "kept everything: no reason given", "no reason given")], ids=["server-error", "no-reason-twice"])
def test_the_careful_step_keeps_every_device_until_tonight_when_no_reading_can_stand(chat, client, replies, how, error):
    r = read(chat, client, NOTE, *replies, careful=True)
    assert r["wishes"] == [{"wish": w, "by": "", "from": AT, "until": "2025-01-28 00:00", "why": nr.NO_READING} for w in nr.BLOCKS]
    assert (r["how"], r["tell"], r["no_reason"], r["ended"], r["error"][:len(error)]) == (how, nr.FAILED, False, [], error)


def test_the_careful_step_asks_with_examples_and_moves_an_end_already_past_to_when_it_comes_round(chat, client):
    r = read(chat, client, "Car ready by 7 today, and the battery full", answer(wish("keep_car_ready", by="07:00", until="today"),
                                                                                  wish("keep_battery_full", until="2025-01-20")), careful=True)
    assert chat.bodies[0]["messages"][0]["content"] == nr.SYSTEM + nr.HELP
    assert r["wishes"] == [{"wish": "keep_car_ready", "by": "07:00", "from": AT, "until": "2025-01-28 07:00", "end_moved": True},
                           {"wish": "keep_battery_full", "by": "", "from": AT, "until": "2025-01-28 00:00", "end_moved": True}]
    assert (r["how"], r["ends_moved"], r["tell"], r["error"], r["readings"]) == ("read with examples", 2, None, None, {"reader": ["keep_car_ready", "keep_battery_full"]})


def test_the_person_hears_what_a_note_keeps_and_when_it_was_not_kept():
    ws = [{"wish": "keep_battery_full"}, {"wish": "keep_car_ready"}, {"wish": "keep_battery_full"}, {"wish": "keep_sauna"}]
    assert note_words.heard(ws) == "Got it: keeping the battery full and keeping the car ready, as you asked."
    assert note_words.not_kept('Going away "tonight",\n need   a full battery') == "I couldn't act on your note, so nothing has changed: \"Going away 'tonight', need a full battery\""
    assert note_words.not_kept("x" * 500) == f'I couldn\'t act on your note, so nothing has changed: "{"x" * 120}"'
    assert note_words.got_it(ws[:1], 1.0, 3.5, note_words.when_of("2025-01-28 18:00", AT), "{:.1f}".format) == \
        "Got it: keeping the battery full, as you asked, so I'm giving 1.0 kW tomorrow night instead of 3.5."


def test_a_node_holds_the_wish_its_note_sets_and_drops_the_calls_it_blocks(chat, node_agent):
    a = node_agent
    a.calls = [{"tool": "limit_ev_charging", "target": "home-car"}, {"tool": "set_battery", "target": "home-battery"}]
    chat.replies[:] = [answer(wish("keep_car_ready", until="tomorrow"))]
    assert a.take_note("Need the car ready tomorrow", AT, AT) == ("The owner needs the car ready.", True)
    assert a.guard.wishes == [{"wish": "keep_car_ready", "by": "", "from": AT, "until": "2025-01-29 00:00"}]
    assert (a.calls, a.sim.overrides.get("ev_now")) == ([{"tool": "set_battery", "target": "home-battery"}], True)
    assert {k: a.receipts[-1][k] for k in ("by", "reason", "chose")} == {"by": "agent", "reason": WHY, "chose": {"needs": ["keep_car_ready"], "ended": []}}


def test_a_node_ends_the_wish_a_later_note_takes_back(chat, node_agent):
    node_agent.guard.wishes = [dict(w) for w in IN_FORCE]
    chat.replies[:] = [answer(("end_owner_wish", {"wish": "keep_battery_full", "reason": WHY}))]
    assert node_agent.take_note("Back early, use the battery as normal", AT, AT) == (note_words.TAKEN_BACK, True)
    assert [w["wish"] for w in node_agent.guard.wishes] == ["keep_hot_water"]


def test_a_node_holds_nothing_of_a_wish_whose_end_has_already_passed(chat, node_agent):
    chat.replies[:] = [answer(wish("keep_car_ready", by="07:00", until="today"))]
    assert node_agent.take_note("Car ready by 7 today", AT, AT) == (None, True)
    assert (node_agent.guard.wishes, node_agent.sim.overrides.get("ev_now")) == ([], None)


def test_a_node_tells_the_owner_it_could_not_act_on_a_note_read_without_a_reason(chat, node_agent):
    chat.replies[:] = [BARE, BARE]
    assert node_agent.take_note(NOTE, AT, AT) == (None, True)
    assert (node_agent.guard.wishes, node_agent.told[-1]["text"]) == ([], f'I couldn\'t act on your note, so nothing has changed: "{NOTE}"')
    r = node_agent.receipts[-1]
    assert (r["by"], r["reason"], r["flags"], r["chose"]["read_as"]) == ("rule: no reason given", nr.NO_REASON, [nr.NO_REASON], ["keep_battery_full"])


def test_a_door_note_is_read_once_and_again_only_while_the_model_gives_no_answer(chat, node_agent):
    a = node_agent
    a.sim.overrides.update(note=NOTE, note_at=AT)
    chat.replies[:] = [500, answer(wish("keep_battery_full", until="tonight"))]
    assert (a.read_note(AT), a.guard.wishes, a.receipts[-1]["by"]) == (None, [], "deferred: the model did not answer, so the note is read again at the next step")
    assert a.read_note(AT) == "The owner needs the battery kept full."
    assert (a.read_note(AT), len(chat.bodies), [w["wish"] for w in a.guard.wishes]) == (None, 2, ["keep_battery_full"])


def test_the_notes_on_file_are_read_once_each_and_only_the_last_two(chat, client, own_config):
    (own_config / "home-01_wishes.json").write_text(json.dumps({"notes": ["Skip the first", "Keep the battery full tonight", "Hot water on till 8pm"]}))
    a = world.agent(world.home("home-01", own_config)[0], client)
    chat.replies[:] = [answer(wish("keep_battery_full", until="tonight")), answer(wish("keep_hot_water", by="20:00"))]
    assert (a.read_note(AT), a.read_note(AT), len(chat.bodies)) == ("The owner needs the battery kept full.", None, 2)
    assert [w["until"] for w in a.guard.wishes] == ["2025-01-28 00:00", "2025-01-27 20:00"]
    assert chat.bodies[1]["messages"][1]["content"] == ('Today is Monday 2025-01-27, 18:05. The owner wrote: "Hot water on till 8pm" Needs in force now, from '
                                                        'earlier notes: keep_battery_full until 2025-01-28 00:00. If this note takes one back, call end_owner_wish.')


def test_a_car_now_note_holds_the_car_whatever_the_model_reads_and_the_owner_hears_it(chat, node_agent):
    chat.replies[:] = [answer(("no_wish", {"reason": WHY}))]
    assert node_agent.take_note(nr.CAR_NOW, AT, AT) == ("The owner needs the car ready.", True)
    assert node_agent.guard.wishes == [{"wish": "keep_car_ready", "by": "", "from": AT, "until": ""}]
    assert node_agent.told[-1]["text"] == "Got it: keeping the car ready, as you asked."


def test_a_careful_node_keeps_everything_while_its_note_cant_be_read_and_then_holds_only_what_it_asks(chat, node_agent, monkeypatch):
    monkeypatch.setenv("MURMUR_CAREFUL_NOTES", "1")
    a = node_agent
    a.sim.overrides.update(note=NOTE, note_at=AT)
    chat.replies[:] = [500, answer(wish("keep_battery_full", until="tonight"))]
    a.read_note(AT)                                             # no reading: every device is kept until tonight is over, the car first, and the owner hears so
    assert ([(w["wish"], w["until"], w["why"]) for w in a.guard.wishes], a.told[-1]["text"], a.sim.overrides.get("ev_now")) == \
        ([(w, "2025-01-28 00:00", nr.NO_READING) for w in nr.BLOCKS], nr.FAILED, True)
    assert a.read_note(AT) == "The owner needs the battery kept full."      # read at the next step: what was kept in its place goes back
    assert (a.guard.wishes, len(a.told), a.sim.overrides.get("ev_now")) == ([{"wish": "keep_battery_full", "by": "", "from": AT, "until": "2025-01-28 00:00"}], 1, None)
    assert [b["messages"][0]["content"] for b in chat.bodies] == [nr.SYSTEM + nr.HELP] * 2


def test_a_signed_set_limit_goes_on_top_of_the_limits_on_file_and_no_other_word_changes_them(own_config):
    said = {"verb": "set_limit", "group": "hvac_zones", "name": "max_rise_c", "value": 1.5}
    assert person.limit_said("home-01", said) == {"limits": {"hvac_zones": {"max_rise_c": 1.5}}}
    person.note("home-01", limits={"hvac_zones": {"max_rise_c": 2.0, "max_rise_away_c": 3.0}, "energy_storage": {"reserve_pct": 30}})
    assert person.limit_said("home-01", said) == {"limits": {"hvac_zones": {"max_rise_c": 1.5, "max_rise_away_c": 3.0}, "energy_storage": {"reserve_pct": 30}}}
    assert person.limit_said("home-01", {"verb": "clear_alarm"}) == {}


def test_a_signers_number_only_goes_up_and_after_a_lost_file_starts_above_its_floor(own_config):
    person.note("home-01", seq={"owner": 5})
    person.note("home-01", seq={"owner": 3, "facility_manager": 2}, alarm="smoke")
    assert person.book("home-01") == {"alarm": "smoke", "seq": {"owner": 5, "facility_manager": 2}}
    assert person.numbers("home-01", ["owner"]) == {"owner": 5, "facility_manager": 2}
    person.book_path("home-01").write_text(json.dumps({"seq": {"owner": "5"}}))
    assert person.book("home-01") == {"bad": "ValueError: not this file's shape"}
    low = person.floor("home-01")
    assert low > 0 and person.book_path("home-01").with_suffix(".bad").exists()
    assert person.numbers("home-01", ["owner"]) == {"owner": low}


def test_trust_adds_a_persons_public_key_to_agent_json_and_refuses_anything_else(own_config):
    path = own_config / "agent.json"
    path.write_text(json.dumps({"llm_model": MODEL, "person_keys": {"owner": "a" * 64}}))
    person.trust("facility_manager", "b" * 64)
    assert json.loads(path.read_text()) == {"llm_model": MODEL, "person_keys": {"owner": "a" * 64, "facility_manager": "b" * 64}}
    with pytest.raises(SystemExit, match="64 hex characters"):
        person.trust("owner", "B" * 64)
    assert json.loads(path.read_text())["person_keys"]["owner"] == "a" * 64
