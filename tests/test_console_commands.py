"""The console's commands: every field checked and its default filled in, each refusal in words of the one fixed list, and no
address, port, path, node id or error text in any sentence the console can say."""
from __future__ import annotations

import re

import pytest

from demo.console import commands as C

SAID = C.sentences()                                # every sentence the console can say


def facts(**over) -> dict:
    """What a driver knows in the middle of the example evening, held: three homes (one without a battery), two buildings."""
    return {"play": "held", "now": "2025-01-28 17:00", "span": ["2025-01-27 10:00", "2025-01-29 02:45"],
            "roster": {"homes": [{"id": "home-01", "name": "Home 1", "battery": True}, {"id": "home-02", "name": "Home 2", "battery": False},
                                 {"id": "home-03", "name": "Home 3", "battery": True}],
                       "buildings": [{"id": "building-01", "name": "the shops"}, {"id": "building-02", "name": "the office"}],
                       "buyers": ["utility", "grid-operator"]},
            "follow": {"home": "home-02", "building": "building-02"}} | over


def sure(body: dict, **over) -> dict:
    command, no = C.check(body, facts(**over))
    assert no is None, no
    return command


def refused(body, **over) -> str:
    command, no = C.check(body, facts(**over))
    assert command is None and no in SAID
    return no


# ---------------------------------------------------------------------- the commands
def test_the_plain_commands_are_taken_as_they_are():
    for do in ("hello", "hold", "go", "step"):
        assert sure({"do": do}) == {"do": do}
    assert sure({"do": "start"}) == {"do": "start", "run_to": None}
    assert sure({"do": "start", "run_to": "2025-01-28 17:00"}, play="idle", now=None) == {"do": "start", "run_to": "2025-01-28 17:00"}
    assert sure({"do": "run_to", "ts": "2025-01-28 18:00"}) == {"do": "run_to", "ts": "2025-01-28 18:00"}
    assert [sure({"do": "pace", "speed": s})["speed"] for s in C.SPEEDS] == ["0.5", "1", "2", "4", "max"]
    assert C.SPEEDS == {"0.5": 16000, "1": 8000, "2": 4000, "4": 2000, "max": 0}       # at 1, the replay's own 8 seconds a moment


@pytest.mark.parametrize("body", [None, 7, "start", [], ["start"], {}, {"do": None}, {"do": 1}, {"do": ["start"]}, {"do": "restart"},
                                  {"do": "Start"}, {"do": ""}, {"start": True}])
def test_what_is_no_command_is_refused(body):
    assert refused(body) == "The console does not know that command."


@pytest.mark.parametrize("body", [{"do": "hello", "who": "home-01"}, {"do": "hold", "run_to": "2025-01-28 18:00"}, {"do": "start", "ts": "2025-01-28 18:00"},
                                  {"do": "step", "n": 3}, {"do": "pace", "speed": "2", "leap": True}, {"do": "run_to", "ts": "2025-01-28 18:00", "run_to": 1},
                                  {"do": "surprise", "kind": "weather", "who": "home-01"}, {"do": "surprise", "kind": "note", "pv": 0.2},
                                  {"do": "surprise", "kind": "car_now", "text": "x"}, {"do": "surprise", "kind": "emergency", "at": "2025-01-28 18:00"}])
def test_a_field_the_command_does_not_take_is_refused(body):
    assert refused(body) == "The command carries a field the console does not take."


@pytest.mark.parametrize("play, taken", [("idle", ("hello", "start", "pace")), ("failed", ("hello", "start", "pace")), ("settled", ("hello", "start", "pace")),
                                         ("starting", ("hello", "pace", "hold", "go")), ("running", ("hello", "start", "pace", "hold", "go", "run_to", "surprise")),
                                         ("held", ("hello", "start", "pace", "hold", "go", "run_to", "surprise", "step")), (None, ("hello", "start", "pace"))])
def test_each_command_is_taken_only_while_the_evening_can_take_it(play, taken):
    bodies = {"hello": {}, "start": {}, "pace": {"speed": "max"}, "hold": {}, "go": {}, "step": {}, "run_to": {"ts": "2025-01-28 18:00"},
              "surprise": {"kind": "weather"}}
    for do, more in bodies.items():
        command, no = C.check({"do": do, **more}, facts(play=play))
        assert (no is None) == (do in taken), (play, do, no)
        if no:
            assert no == {"step": "Step works only while the clock is held.", "start": "The network is already starting."}.get(do, "No evening is running.")


@pytest.mark.parametrize("ts", [None, "", "18:00", "2025-01-28", "2025-01-28 18:10", "2025-01-28 18:00:00", "2025-01-28T18:00", " 2025-01-28 18:00",
                                "2025-01-28 17:00", "2025-01-28 16:45", "2025-01-29 03:00", "2025-02-30 18:00", "2025-01-28 24:00", 129, ["2025-01-28 18:00"],
                                "٢٠٢٥-٠١-٢٨ ١٨:٠٠"])
def test_a_run_to_wants_a_quarter_hour_of_this_evening_after_the_clocks(ts):
    assert refused({"do": "run_to", "ts": ts}) == "The time must be a quarter-hour of this evening, after the clock's."
    if ts is not None:
        assert refused({"do": "start", "run_to": ts}, now=None, span=["2025-01-28 17:00", "2025-01-29 02:45"]) == refused({"do": "run_to", "ts": ts})


def test_a_run_to_reaches_from_the_next_quarter_hour_to_the_evenings_last():
    assert sure({"do": "run_to", "ts": "2025-01-28 17:15"})["ts"] == "2025-01-28 17:15"
    assert sure({"do": "run_to", "ts": "2025-01-29 02:45"})["ts"] == "2025-01-29 02:45"
    assert sure({"do": "start", "run_to": "2025-01-27 10:15"})["run_to"] == "2025-01-27 10:15"          # a start counts from the evening's first
    assert refused({"do": "start", "run_to": "2025-01-27 10:00"}) and refused({"do": "run_to", "ts": "2025-01-28 18:00"}, now=None)
    assert refused({"do": "run_to", "ts": "2025-01-28 18:00"}, span=None) and refused({"do": "start", "run_to": "2025-01-28 18:00"}, span=[])


@pytest.mark.parametrize("speed", [None, 1, 2.0, "3", "fast", "MAX", "1.0", " 1", ["1"], {"1": 1}, True])
def test_a_pace_wants_one_of_the_five_speeds_as_the_page_writes_them(speed):
    assert refused({"do": "pace", "speed": speed}) == "The speed is one of 0.5, 1, 2, 4 and max."


# ---------------------------------------------------------------------- the eight surprises
def test_every_kind_of_surprise_is_taken_at_its_defaults():
    assert C.KINDS == ("note", "car_now", "weather", "building_closed", "building_need", "emergency", "battery_fault", "battery_low")
    got = {kind: sure({"do": "surprise", "kind": kind}) for kind in C.KINDS}
    assert got == {
        "note": {"do": "surprise", "kind": "note", "who": "home-02", "text": "Please keep the battery full tonight."},
        "car_now": {"do": "surprise", "kind": "car_now", "who": "home-02"},
        "weather": {"do": "surprise", "kind": "weather", "pv": 0.2, "load": 1.3, "dT": 6, "hours": 3},
        "building_closed": {"do": "surprise", "kind": "building_closed", "who": "building-02"},
        "building_need": {"do": "surprise", "kind": "building_need", "who": "building-02", "share": 0.25, "hours": 3.5},
        "emergency": {"do": "surprise", "kind": "emergency", "buyer": "utility", "kw": 20, "minutes": 60},
        "battery_fault": {"do": "surprise", "kind": "battery_fault", "who": "home-01", "on": True},
        "battery_low": {"do": "surprise", "kind": "battery_low", "who": "home-01", "pct": 10}}
    assert all(set(got[kind]) == {"do", "kind", *C.FIELDS[kind]} for kind in C.KINDS)


def test_a_field_that_is_given_is_kept_and_one_given_as_null_is_at_its_default():
    assert sure({"do": "surprise", "kind": "note", "who": "home-03", "text": "  Back at nine.  "}) == {"do": "surprise", "kind": "note", "who": "home-03", "text": "Back at nine."}
    assert sure({"do": "surprise", "kind": "weather", "pv": 0, "load": 2, "dT": -10, "hours": 24}) == {"do": "surprise", "kind": "weather", "pv": 0, "load": 2, "dT": -10, "hours": 24}
    assert sure({"do": "surprise", "kind": "emergency", "buyer": "grid-operator", "kw": 2000, "minutes": 15.0})["buyer"] == "grid-operator"
    assert sure({"do": "surprise", "kind": "battery_fault", "who": "home-03", "on": False}) == {"do": "surprise", "kind": "battery_fault", "who": "home-03", "on": False}
    assert sure({"do": "surprise", "kind": "battery_low", "who": None, "pct": None}) == {"do": "surprise", "kind": "battery_low", "who": "home-01", "pct": 10}
    assert sure({"do": "surprise", "kind": "note", "text": "é" * 200})["text"] == "é" * 200


@pytest.mark.parametrize("kind", [None, "", "earthquake", "Note", 3, ["note"], {"note": 1}])
def test_a_surprise_of_no_known_kind_is_refused(kind):
    assert refused({"do": "surprise", "kind": kind}) == "The console does not know that surprise."
    assert refused({"do": "surprise"}) == "The console does not know that surprise."


def test_a_network_takes_only_the_surprises_it_offers():
    offered = [k for k in C.KINDS if k != "battery_low"]
    assert refused({"do": "surprise", "kind": "battery_low"}, surprises=offered) == "This network does not take that surprise."
    assert sure({"do": "surprise", "kind": "battery_fault"}, surprises=offered)["who"] == "home-01"
    assert refused({"do": "surprise", "kind": "weather"}, surprises=[]) == "This network does not take that surprise."


NUMBERS = [("weather", "pv", 0, 1), ("weather", "load", 0.5, 2), ("weather", "dT", -10, 10), ("weather", "hours", 0.5, 24),
           ("building_need", "share", 0.05, 1), ("building_need", "hours", 0.5, 6), ("emergency", "kw", 1, 2000), ("emergency", "minutes", 15, 240),
           ("battery_low", "pct", 5, 100)]


@pytest.mark.parametrize("kind, field, least, most", NUMBERS)
def test_a_number_stays_inside_its_limits(kind, field, least, most):
    words = f"The number {field} must be from {least} to {most}."
    for good in (least, most, (least + most) / 2):
        assert sure({"do": "surprise", "kind": kind, field: good})[field] == good
    for bad in (least - 0.01, most + 0.01, str(least), "", [least], {"x": 1}, True, False, float("nan"), float("inf"), -float("inf"), 10 ** 400, -(10 ** 400)):
        assert refused({"do": "surprise", "kind": kind, field: bad}) == words
    assert sorted((k, f, lo, hi) for k, fs in C.NUMBERS.items() for f, (lo, hi, _) in fs.items()) == sorted(NUMBERS)


@pytest.mark.parametrize("kind, who, words", [
    ("note", "home-09", "That home is not in this network."), ("note", "building-01", "That home is not in this network."),
    ("car_now", 2, "That home is not in this network."), ("car_now", ["home-01"], "That home is not in this network."),
    ("building_closed", "home-01", "That building is not in this network."), ("building_need", "", "That building is not in this network."),
    ("battery_fault", "home-02", "That home has no battery."), ("battery_low", "home-02", "That home has no battery."),
    ("battery_low", "home-09", "That home is not in this network."), ("battery_fault", "building-01", "That home is not in this network.")])
def test_a_surprise_is_for_a_node_of_this_network_and_a_batterys_for_a_home_that_has_one(kind, who, words):
    assert refused({"do": "surprise", "kind": kind, "who": who}) == words


def test_without_a_name_a_surprise_goes_to_the_followed_node_or_the_first_that_will_do():
    roster = facts()["roster"]
    assert sure({"do": "surprise", "kind": "car_now"}, follow={})["who"] == "home-01"
    assert sure({"do": "surprise", "kind": "building_closed"}, follow={"building": "building-09"})["who"] == "building-01"
    assert sure({"do": "surprise", "kind": "battery_low"}, follow={"home": "home-03"})["who"] == "home-03"       # the followed home, when it has a battery
    assert sure({"do": "surprise", "kind": "battery_low"})["who"] == "home-01"                                  # else the first that has one
    flat = {**roster, "homes": [{**h, "battery": False} for h in roster["homes"]]}
    assert refused({"do": "surprise", "kind": "battery_fault"}, roster=flat) == "No home of this network has a battery."
    assert refused({"do": "surprise", "kind": "battery_low", "who": "home-01"}, roster=flat) == "That home has no battery."
    assert refused({"do": "surprise", "kind": "note"}, roster={}) == "That home is not in this network."
    assert refused({"do": "surprise", "kind": "building_need"}, roster={"homes": roster["homes"]}) == "That building is not in this network."
    assert refused({"do": "surprise", "kind": "battery_low"}, roster={}) == "That home is not in this network."


@pytest.mark.parametrize("text", ["", "   ", "x" * 201, "two\nlines", "a\ttab", "bell\x07", "‮right to left", 7, ["a note"], {"text": "x"}, True])
def test_a_note_is_one_printable_line_of_1_to_200_characters(text):
    assert refused({"do": "surprise", "kind": "note", "text": text}) == "The note is one printable line of 1 to 200 characters."


@pytest.mark.parametrize("field, bad, words", [("buyer", "aggregator", "That buyer is not in this network."), ("buyer", 1, "That buyer is not in this network."),
                                               ("buyer", ["utility"], "That buyer is not in this network.")])
def test_an_emergency_is_called_by_a_buyer_of_this_network(field, bad, words):
    assert refused({"do": "surprise", "kind": "emergency", field: bad}) == words
    assert refused({"do": "surprise", "kind": "emergency"}, roster={"buyers": []}) == words
    assert sure({"do": "surprise", "kind": "emergency"}, roster={"buyers": [{"id": "grid-operator", "name": "Grid operator"}]})["buyer"] == "grid-operator"


@pytest.mark.parametrize("on", [0, 1, "true", "on", [], {}])
def test_a_battery_fault_is_switched_by_true_or_false(on):
    assert refused({"do": "surprise", "kind": "battery_fault", "on": on}) == "On must be true or false."


# ---------------------------------------------------------------------- what the console says
PRIVATE = [r"\d{1,3}(\.\d{1,3}){3}", r"localhost", r"https?:", r"://", r":\d{2,5}\b", r"(^|[\s\"'(])[~.]?/[\w.~-]", r"\\", r"\b(home|building|site)-[\w-]*\d",
           r"\b\w+(Error|Exception)\b", r"Traceback", r"\bline \d+", r"\bErrno\b", r"[<>{}\[\]]", r"\b[0-9a-f]{12,}\b"]


def test_no_sentence_of_the_console_holds_an_address_a_port_a_path_a_node_id_or_an_errors_text():
    said = SAID
    assert len(said) > len(C.SAY) and all(s == s.strip() and s[0].isupper() and s.endswith(".") and len(s) <= 90 for s in said)
    for s in said:
        assert not [p for p in PRIVATE if re.search(p, s)], s
    assert all(any(re.search(p, bad) for p in PRIVATE) for bad in (                                              # the patterns do find what they look for
        "No answer from 127.0.0.1:51234.", "No answer from http://localhost/x.", "Could not read /tmp/run/key.", "home-02 refused it.",
        "ConnectError: all attempts failed.", "Traceback (most recent call last)", "File x, line 12", "waiting on site-dc-01"))


def test_a_sentences_only_variables_are_a_parts_role_and_a_surprises_page_word():
    assert C.say("no_answer", role="community") == "No answer from the community agent."
    assert C.say("refused", role="homes", word="battery_low") == "Battery low was not posted: the homes' host refused it."
    assert C.say("not_posted", role="buyer", word="emergency") == "Grid emergency was not posted: no answer from the buyer."
    assert C.say("surprise_waits", word="weather") == "Weather change: waiting for the clock to stand."
    assert C.say("log_full") == "This run's log is full: no more moments are shown."
    assert {C.WORDS[k] for k in C.KINDS} == {"Owner's note", "Car needed now", "Weather change", "Building closes", "Building needs power",
                                             "Grid emergency", "Battery fault", "Battery low"}
    hostile = "http://203.0.113.7:51080/x home-02 ConnectError('boom')"
    for said in (C.say("no_answer", role=hostile), C.say("refused", role=hostile, word=hostile), C.say(hostile), C.say(None), C.say(["log_full"]),
                 C.say("surprise_waits", word=hostile), C.say("no_answer", role=7), C.say("refused", word={"a": 1})):
        assert said in SAID and "home-02" not in said and "203.0" not in said and "boom" not in said
    assert C.say(hostile) == C.say("unknown") == "The console cannot say more."


@pytest.mark.parametrize("body", [{"do": "run_to", "ts": "http://203.0.113.9:51009/x"}, {"do": "surprise", "kind": "javascript:alert(1)"},
                                  {"do": "surprise", "kind": "note", "who": "/etc/passwd"}, {"do": "surprise", "kind": "note", "text": "x\n127.0.0.1:51000"},
                                  {"do": "pace", "speed": "home-02"}, {"do": "/etc/passwd"}, {"do": "surprise", "kind": "emergency", "buyer": "ValueError: boom"},
                                  {"do": "hello", "home-02": 1}, {"do": "surprise", "kind": "weather", "pv": "127.0.0.1"}])
def test_a_refusal_repeats_nothing_of_what_was_sent(body):
    no = refused(body)
    for sent in ("203.0.113.9", "script", "passwd", "127.0.0.1", "51000", "home-02", "boom", "ValueError"):
        assert sent not in no
