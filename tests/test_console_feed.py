"""The console's log and the feed's answer: the first form untouched without a cursor, the second by cursor, the caps, a run
change, the clock and the pins inside their fixed lists, and the leaps folded."""
from __future__ import annotations

import json
import random

import pytest

from demo.console import feed as F
from demo.console import timeline as T
from demo.runner import feed as runner_feed

EVENING = {"date": "2025-01-28", "window": ["18:00", "21:00"], "feed": {"2025-01-27 10:00": {}, "2025-01-29 02:45": {}},
           "battery_request": {"made_at": "2025-01-28 14:00", "rows": []}}
TL = T.build(EVENING, [])
NET = {"key": "one", "boxes": ["town", "co-market", "h-agent"]}
CLOCK = ["state", "tq", "speed", "dwell_ms", "fast", "waiting", "floor_ms", "leaps"]


def v1() -> dict:
    """The runner's own state of a running evening, from the parts' answers."""
    summary = {"now": "2025-01-28 18:15", "roster": 3, "events": {"e1": {"phase": "confirming", "window": ["2025-01-28 18:00", "2025-01-28 21:00"],
                                                                     "kw_requested": [4.0, 6.5], "offers": 4, "accepted": 3, "readings": 2}}}
    answers = {"bus": {"ok": True}, "community": {"ready": True, "code": "c1"}, "homes": {"code": "c1"}, "summary": summary,
               "homes_names": ["home-01", "home-02"], "buildings_names": ["building-01"]}
    return runner_feed.state(answers, {"bus": 99.0, "community": 98.0}, "c1", 100.0)


def step(tq: int, lines: int = 2, chars: int = 40, **more) -> dict:
    """A step in the wire's form, before the log numbers it."""
    return {"tq": tq, "n": "The call reaches a home", "w": "Home 2", "sd": "h", "b": ["town", "h-agent"],
            "l": [["note", "", [["", "x" * chars]], ["town"], 0] for _ in range(lines)]} | more


def moment(tq: int, **more) -> dict:
    return {"tq": tq, "id": "call", "n": "The community agent calls for offers", "b": "co-market", "w": "", "hero": ["14.4 kW", "asked for"], "tag": None,
            "p": ["co-market", "town"], "c": "call for offers", "lit": ["co-market", "town"], "tv": 1,
            "k": {"kind": "market", "cb": "co-market", "l": 3, "who": [], "in": [], "out": [], "did": "", "rule": "", "cd": [], "cols": "1fr", "term": ["", ""], "big": []}} | more


def log(run: int = 1, moments: int = 0, **each) -> F.Log:
    """A log of one run, past the pass it began in, with this many moments, one a quarter-hour, each of two steps."""
    lg = F.Log()
    lg.reset(run, NET, TL)
    lg.set({"state": "idle", "speed": "1"}, None)
    for q in range(1, moments + 1):
        assert lg.add([step(q, **each), step(q, **each)], moment(q)) == q
    return lg


def clock(**over) -> dict:
    return {"state": "live", "tq": 0, "speed": "1", "fast": False, "waiting": 0, "floor_ms": 1600, "leaps": [], "played": []} | over


def walk(lg: F.Log, since: int) -> tuple[list, list]:
    """Every moment and step a page is given that asks from `since` and follows `next` until nothing more waits."""
    moments, steps = [], []
    for _ in range(500):
        v2 = lg.answer(v1(), since)["v2"]
        assert v2["since"] == since and v2["next"] == since + len(v2["moments"]) and (v2["moments"] or not v2["more"])
        moments, steps, since = moments + v2["moments"], steps + v2["steps"], v2["next"]
        if not v2["more"]:
            return moments, steps
    raise AssertionError("the walk never ends")


# ---------------------------------------------------------------------- the two forms
@pytest.mark.parametrize("since", [None, "", " ", "-1", "+1", "1.0", "1e2", "0x1", "one", "1 ", " 1", "1_0", "١", "²", "1234567890", -1, 1.5, 10 ** 9,
                                   True, False, [1], {"since": 1}, b"1"])
def test_without_a_valid_since_the_answer_is_the_runners_state_exactly(since):
    state = v1()
    out = log(moments=3).answer(state, since)
    assert out is state and out == v1() and "v2" not in out
    assert F.text(out) == json.dumps(v1())                                           # written as the read-only feed writes it


def test_before_the_first_reset_the_log_has_no_second_form_to_give():
    lg = F.Log()
    assert lg.answer(v1(), "0") == v1() and lg.add([step(1)], moment(1)) is None and lg.set(clock(), []) is None
    assert lg.faults == {"form": 1, "over": 0, "full": 0, "set": 1}


@pytest.mark.parametrize("since, n", [("0", 0), ("2", 2), ("007", 7), (0, 0), (3, 3), ("999999999", 999999999)])
def test_with_a_since_the_answer_is_the_same_keys_and_v2(since, n):
    lg, state = log(run=3, moments=2), v1()
    out = lg.answer(state, since)
    assert list(out) == [*state, "v2"] and {k: out[k] for k in state} == state == v1()
    v2 = out["v2"]
    assert list(v2) == ["schema", "run", "since", "next", "more", "every_ms", "net", "clock", "timeline", "steps", "moments"]
    assert (v2["schema"], v2["run"], v2["since"], v2["more"], v2["every_ms"]) == ("murmur.live.v2", 3, n, False, 2000)
    assert v2["next"] == 2 and [m["q"] for m in v2["moments"]] == list(range(n + 1, 3))      # a cursor beyond the head comes back to it
    assert v2["net"] == NET and list(v2["clock"]) == CLOCK
    assert v2["timeline"] == {"t0": TL.t0, "n": TL.n, "parts": TL.parts, "pins": T.marked(TL.pins, 0, False)}
    assert json.loads(F.raw(F.text(out))) == out and ", " not in F.text({"v2": [1, 2]})


def test_add_sets_every_i_q_and_s_and_nothing_taken_ever_changes():
    lg = log()
    one, two = [step(1), step(1, lines=1)], [step(2, i=99)]
    first, second = moment(1), moment(2, q=77, s=[5, 6])
    assert (lg.add(one, first), lg.add(two, second)) == (1, 2)
    v2 = lg.answer(v1(), 0)["v2"]
    assert [s["i"] for s in v2["steps"]] == [0, 1, 2] and [(m["q"], m["s"]) for m in v2["moments"]] == [(1, [0, 1]), (2, [2])]
    assert list(v2["steps"][0]) == ["i", "tq", "n", "w", "sd", "b", "l"]
    assert list(v2["moments"][0]) == ["q", "tq", "id", "n", "b", "w", "hero", "tag", "p", "c", "lit", "tv", "k", "s"]
    assert "i" not in one[0] and "q" not in first and second["q"] == 77                # what was given is left as it was
    before = F.text(lg.answer(v1(), 0))
    one[0]["l"].clear(), first["k"].update(kind="hostile"), two.append(step(3))
    assert F.text(lg.answer(v1(), 0)) == before                                       # and what is given back later is what was taken


def test_any_split_of_cursors_gives_the_same_log():
    lg, rng, given = log(), random.Random(7), []
    for q in range(1, 41):
        steps = [step(q, lines=rng.randint(25, 40), chars=rng.randint(250, 320)) for _ in range(rng.randint(1, 4))]
        given.append((steps, moment(q)))
        assert lg.add(steps, given[-1][1]) == q
    moments, steps = walk(lg, 0)
    assert [m["q"] for m in moments] == list(range(1, 41)) and [s["i"] for s in steps] == list(range(len(steps)))
    for (own, m), got in zip(given, moments):
        assert got == {"q": got["q"], **m, "s": got["s"]} and [steps[i] for i in got["s"]] == [{"i": i, **s} for i, s in zip(got["s"], own)]
    for since in range(41):                                                           # from any cursor: the rest of the same log
        rest, theirs = walk(lg, since)
        assert rest == moments[since:] and theirs == [steps[i] for m in rest for i in m["s"]]
        v2 = lg.answer(v1(), str(since))["v2"]                                        # and any one answer: the moments next due, exactly their steps
        assert v2["moments"] == moments[since:since + len(v2["moments"])] and v2["steps"] == [steps[i] for m in v2["moments"] for i in m["s"]]
        assert v2["more"] == (v2["next"] < 40) and (v2["moments"] or since == 40)
    assert 1 < len({len(lg.answer(v1(), since)["v2"]["moments"]) for since in range(35)})        # the answers were cut by size as well as by count


# ---------------------------------------------------------------------- the caps
def test_an_answer_holds_at_most_six_moments_and_200000_characters():
    v2 = log(moments=10).answer(v1(), 0)["v2"]
    assert len(v2["moments"]) == 6 == F.ANSWER_MOMENTS and (v2["next"], v2["more"]) == (6, True)
    lg = log(moments=9, lines=40, chars=560)                                          # each moment about 47,000 characters with its steps
    for since in range(9):
        out = lg.answer(v1(), since)
        sent = F.text(out)
        assert 1 <= len(out["v2"]["moments"]) <= 4 and len(sent) <= len(F.raw(sent)) <= 200_000 == F.ANSWER_CHARS
    assert len(lg.answer(v1(), 0)["v2"]["moments"]) == 4 and len(F.text(lg.answer(v1(), 0))) > 150_000


def test_characters_no_ascii_holds_count_as_the_bytes_they_travel_in():
    lg = log(moments=6, lines=40, chars=200, n="é" * 80)
    wide = log()
    for q in range(1, 7):
        assert wide.add([step(q) | {"l": [["note", "", [["", "é…" * 7500]], [], 0]]}], moment(q)) == q      # 15,000 characters in 37,500 bytes
    assert len(lg.answer(v1(), 0)["v2"]["moments"]) == 6
    out = wide.answer(v1(), 0)
    assert len(out["v2"]["moments"]) == 5 and len(F.text(out)) < 100_000 and 150_000 < len(F.raw(F.text(out))) <= 200_000


def test_the_next_moment_due_is_always_served():
    lg = log()
    for q in (1, 2, 3):
        assert lg.add([step(q, lines=40, chars=580) for _ in range(2)] + [step(q, lines=20, chars=440)], moment(q)) == q    # just under a moment's cap
    sizes = {}
    for pad in (64_000, 100_000, 150_000, 250_000):                                   # a first form at the most the page takes of one, and past it
        full = v1() | {"note": "x" * pad}
        for since in (0, 1, 2):
            out = lg.answer(full, since)
            assert out["v2"]["moments"][0]["q"] == since + 1 and out["v2"]["next"] == since + len(out["v2"]["moments"])
            assert [s["i"] for s in out["v2"]["steps"]] == [i for m in out["v2"]["moments"] for i in m["s"]]
        assert lg.answer(full, 3)["v2"]["moments"] == []
        sizes[pad] = (len(lg.answer(full, 0)["v2"]["moments"]), len(F.raw(F.text(lg.answer(full, 0)))))
    assert [n for n, _ in sizes.values()] == [2, 1, 1, 1]                             # one moment even where the cap leaves room for none
    assert sizes[64_000][1] < 200_000 and sizes[100_000][1] < 200_000 < sizes[150_000][1] < 262_144 < sizes[250_000][1]


@pytest.mark.parametrize("steps, m, fault", [
    ([step(5, lines=40, chars=600) for _ in range(3)], moment(5), "over"),               # with its steps over 60,000 characters
    ([step(5, lines=1) for _ in range(25)], moment(5), "form"), ([], moment(5), "form"), ("steps", moment(5), "form"),
    ([step(5), "a step"], moment(5), "form"), ([step(5)], None, "form"), ([step(5)], [moment(5)], "form"),
    ([step(5)], {k: v for k, v in moment(5).items() if k != "tq"}, "form"), ([step(5)], moment(401), "form"), ([step(5)], moment(-1), "form"),
    ([step(5)], moment(5.5), "form"), ([step(5)], moment(True), "form"), ([step(5)], moment("5"), "form"),
    ([step(5, w=float("nan"))], moment(5), "form"), ([step(5)], moment(5, hero=float("inf")), "form"),
    ([step(5, b={"town"})], moment(5), "form"), ([step(5)], moment(5, k=object()), "form")])
def test_what_is_not_a_moment_in_the_wires_form_or_is_over_its_cap_is_left_out_and_counted(steps, m, fault):
    lg = log(moments=2)
    assert lg.add(steps, m) is None and lg.faults == {"form": 0, "over": 0, "full": 0, "set": 0} | {fault: 1}
    assert lg.add([step(6)], moment(6)) == 3                                          # the numbers go on without a gap
    v2 = lg.answer(v1(), 2)["v2"]
    assert [m["q"] for m in v2["moments"]] == [3] and [s["i"] for s in v2["steps"]] == [4] and not lg.full


def test_a_moment_at_its_cap_is_taken_whole():
    lg = log()
    steps = [step(1, lines=40, chars=580) for _ in range(2)] + [step(1, lines=20, chars=440)]
    assert 59_000 < sum(len(F.wire(s)) for s in steps) + len(F.wire(moment(1))) < 59_400 == 60_000 - 600      # what the wire leaves the log room for
    assert lg.add(steps, moment(1)) == 1 and lg.add([step(2, n="\ud83d half a pair"), step(2, n="\U0001f50b")], moment(2)) == 2
    assert b"? half a pair" in F.raw(F.text(lg.answer(v1(), 1)))


def test_a_run_keeps_400_moments_then_takes_nothing_more_and_says_so():
    lg = F.Log()
    lg.reset(1, NET, TL)
    assert [lg.add([step(q % 400)], moment(q % 400)) for q in range(1, 401)] == list(range(1, 401)) and not lg.full
    assert lg.add([step(1)], moment(1)) is None and lg.full and lg.faults["full"] == 1
    assert lg.add([step(1)], moment(1)) is None and lg.faults["full"] == 2
    assert len(walk(lg, 0)[0]) == 400 == F.RUN_MOMENTS
    lg.reset(2, NET, TL)                                                              # a new run takes again
    assert not lg.full and lg.add([step(1)], moment(1)) == 1


def test_a_run_keeps_3000_steps_then_takes_nothing_more():
    lg = F.Log()
    lg.reset(1, NET, TL)
    twenty_four = [step(1, lines=1, chars=1) for _ in range(24)]
    assert [lg.add(twenty_four, moment(1)) for _ in range(124)] == list(range(1, 125))                # 2,976 steps
    assert lg.add(twenty_four + [step(1)], moment(1)) is None and lg.faults["form"] == 1 and not lg.full
    assert lg.add(twenty_four, moment(1)) == 125 and not lg.full                                       # 3,000: the last that fits
    assert lg.add([step(1)], moment(1)) is None and lg.full and F.RUN_STEPS == 3000
    assert len(walk(lg, 0)[1]) == 3000
    other = log(moments=1)
    other.steps += [step(1)] * 2990                                                                    # a log 8 steps short of full
    assert other.add(twenty_four, moment(2)) is None and other.full and other.add([step(2)], moment(2)) is None    # once full, nothing more


# ---------------------------------------------------------------------- a run change
def test_a_new_run_empties_the_log_and_raises_run():
    lg = log(run=1, moments=5)
    lg.set(clock(state="held", tq=130, speed="2", waiting=2, leaps=[{"from": 1, "to": 97, "ms": 180}]), TL.pins + [{"tq": 131, "kind": "surprise", "id": "note"}])
    assert lg.answer(v1(), 5)["v2"]["run"] == 1 and len(lg.answer(v1(), 5)["v2"]["timeline"]["pins"]) == 7
    lg.reset(2, NET | {"key": "standby"}, vars(TL))                                   # the timeline as a dict is the same timeline
    v2 = lg.answer(v1(), 5)["v2"]                                                     # a page that holds the old run asks with its old cursor
    assert (v2["run"], v2["since"], v2["next"], v2["more"], v2["moments"], v2["steps"]) == (2, 5, 0, False, [], [])
    assert v2["clock"] == {"state": "held", "tq": 0, "speed": "2", "dwell_ms": 4000, "fast": False, "waiting": 0, "floor_ms": 1600, "leaps": []}
    assert v2["net"]["key"] == "standby" and v2["timeline"]["pins"] == T.marked(TL.pins, 0, False)
    assert lg.add([step(1)], moment(1)) == 1 and lg.answer(v1(), 0)["v2"]["steps"][0]["i"] == 0


@pytest.mark.parametrize("net, line", [
    ({"key": "three", "boxes": []}, vars(TL)), ({"boxes": ["town"]}, vars(TL)), ({"key": "one", "boxes": ["town", 7]}, vars(TL)), (None, vars(TL)),
    (NET, None), (NET, {}), (NET, vars(TL) | {"t0": "soon"}), (NET, vars(TL) | {"n": None}), (NET, vars(TL) | {"n": "145"}),
    (NET, vars(TL) | {"parts": TL.parts + [{"id": "settle", "from": 1, "to": 2}] * 4}), (NET, vars(TL) | {"parts": [{"id": "night", "from": 0, "to": 9}]}),
    (NET, vars(TL) | {"parts": [{"id": "window", "from": "0", "to": 9}]}), (NET, vars(TL) | {"parts": [{"id": "window"}]}), (NET, vars(TL) | {"parts": 5})])
def test_a_network_or_a_timeline_that_cannot_be_sent_is_refused_at_the_reset(net, line):
    lg = log(run=4, moments=1)
    with pytest.raises(ValueError):
        lg.reset(5, net, line)
    assert lg.answer(v1(), 0)["v2"]["run"] == 4 and len(lg.answer(v1(), 0)["v2"]["moments"]) == 1      # and the run in hand stands
    assert F.NETS == ("one", "first", "standin", "standby", "rehearsal")


# ---------------------------------------------------------------------- the clock
@pytest.mark.parametrize("speed, dwell, every", [("0.5", 16000, 400), ("1", 8000, 400), ("2", 4000, 400), ("4", 2000, 400), ("max", 0, 250)])
def test_the_clock_leaves_in_its_fixed_form_with_the_speeds_dwell(speed, dwell, every):
    lg = log()
    lg.set(clock(state="live", tq=129, speed=speed, fast=speed == "max", waiting=3, floor_ms=1612.7), None)
    v2 = lg.answer(v1(), 0)["v2"]
    assert v2["clock"] == {"state": "live", "tq": 129, "speed": speed, "dwell_ms": dwell, "fast": speed == "max", "waiting": 3, "floor_ms": 1612, "leaps": []}
    assert v2["every_ms"] == every and list(v2["clock"]) == CLOCK
    lg.set(clock(state="idle", speed=speed), None)
    assert lg.answer(v1(), 0)["v2"]["every_ms"] == 2000                               # before a start the page asks slowly


def test_every_state_of_the_fixed_list_is_sent_and_nothing_else():
    lg = log()
    assert F.STATES == ("idle", "starting", "leaping", "live", "held", "settled", "failed")
    for state in F.STATES:
        lg.set(clock(state=state), None)
        assert lg.answer(v1(), 0)["v2"]["clock"]["state"] == state
    lg.set(clock(state="held", tq=77, speed="4", floor_ms=900), None)
    for bad in ({"state": "paused", "speed": "4"}, {"state": None, "speed": "4"}, {"state": ["live"], "speed": "4"}, {"speed": "4"}, {"state": "held", "speed": 2},
                {"state": "held", "speed": "3"}, {"state": "held"}, "live"):
        lg.set(bad, None)                                                             # the last good state and speed stand
        assert lg.answer(v1(), 0)["v2"]["clock"] == {"state": "held", "tq": 77, "speed": "4", "dwell_ms": 2000, "fast": False, "waiting": 0, "floor_ms": 900, "leaps": []}
    assert lg.faults["set"] == 8


@pytest.mark.parametrize("given, sent", [({"tq": 999}, {"tq": 400}), ({"tq": -3}, {"tq": 0}), ({"tq": "129"}, {"tq": 77}), ({"tq": None}, {"tq": 77}),
                                         ({"tq": float("nan")}, {"tq": 77}), ({"dwell_ms": 99_999}, {"dwell_ms": 20_000}), ({"dwell_ms": 750}, {"dwell_ms": 750}),
                                         ({"floor_ms": -5}, {"floor_ms": 0}), ({"floor_ms": 10 ** 9}, {"floor_ms": 120_000}), ({"floor_ms": "fast"}, {"floor_ms": 900}),
                                         ({"fast": "yes"}, {"fast": False}), ({"fast": 1}, {"fast": False}), ({"waiting": 10 ** 6}, {"waiting": 999}),
                                         ({"waiting": -1}, {"waiting": 0}), ({"waiting": None}, {"waiting": 0})])
def test_a_number_of_the_clock_stays_inside_its_cap(given, sent):
    lg = log()
    lg.set(clock(state="held", tq=77, speed="2", floor_ms=900), None)
    lg.set(clock(state="held", speed="2", floor_ms=900) | {"tq": 77} | given, None)
    assert lg.answer(v1(), 0)["v2"]["clock"] == {"state": "held", "tq": 77, "speed": "2", "dwell_ms": 4000, "fast": False, "waiting": 0, "floor_ms": 900, "leaps": []} | sent


def test_waiting_is_a_count_and_nothing_of_what_is_waited_on_leaves():
    lg = log(moments=1)
    waits = ["http://127.0.0.1:51234: has still to catch up", "home-02: still deciding", "call gap-7: answers to come"]
    lg.set(clock(waiting=waits), None)
    assert lg.answer(v1(), 0)["v2"]["clock"]["waiting"] == 3
    lg.set(clock(waiting=waits[1]), None)                                             # a text is no count
    assert lg.answer(v1(), 0)["v2"]["clock"]["waiting"] == 0
    lg.set(clock(waiting=2, waiting_on=waits, went_on=[{"without": waits}], now="2025-01-28 18:00", at_gate=waits[0]) | {waits[1]: waits[2]},
           TL.pins + [{"tq": 5, "kind": "surprise", "id": "note", "about": "home-02", "from": waits[0]}])
    sent = F.text(lg.answer({"schema": "murmur.live.v1"}, 0))
    assert lg.answer(v1(), 0)["v2"]["clock"]["waiting"] == 2 and '"waiting":2' in sent and '{"tq":5,"kind":"surprise","id":"note","state"' in sent
    assert not [w for w in ("51234", "home-02", "gap-7", "waiting_on", "went_on", "at_gate", "still", "about") if w in sent]


# ---------------------------------------------------------------------- the leaps
HOPS = [{"from": "2025-01-27 10:00", "to": "2025-01-27 13:00", "steps": 12, "wall_ms": 40}, {"from": "2025-01-27 13:00", "to": "2025-01-27 16:00", "steps": 12, "wall_ms": 35},
        {"from": "2025-01-27 16:00", "to": "2025-01-27 19:00", "steps": 12, "wall_ms": 30}]
PLAYED = [{"sim": "2025-01-27 10:00", "wall_ms": 1600, "waited_on": []}]


def leaps(lg: F.Log) -> list:
    return lg.answer(v1(), 0)["v2"]["clock"]["leaps"]


def test_leaps_with_no_played_quarter_hour_and_no_moment_between_them_are_sent_as_one():
    lg = log()
    lg.set(clock(tq=37, leaps=HOPS, played=PLAYED), None)                             # as the conductor gives them: three hops over an empty night
    assert leaps(lg) == [{"from": 1, "to": 37, "ms": 105}]
    lg.set(clock(tq=37, leaps=[], played=[{"sim": "2025-01-27 16:00", "wall_ms": 1500}]), None)        # the landing at 16:00 was played after all
    assert leaps(lg) == [{"from": 1, "to": 25, "ms": 75}, {"from": 25, "to": 37, "ms": 30}]
    assert lg.add([step(13)], moment(13)) == 1                                        # and a moment stands at the landing at 13:00
    lg.set(clock(tq=37), None)
    assert leaps(lg) == [{"from": 1, "to": 13, "ms": 40}, {"from": 13, "to": 25, "ms": 35}, {"from": 25, "to": 37, "ms": 30}]
    assert all(list(x) == ["from", "to", "ms"] for x in leaps(lg))


def test_the_pass_a_run_begins_in_still_read_the_run_before_and_nothing_of_that_is_taken():
    lg = log(moments=2)
    lg.set(clock(state="settled", tq=145, leaps=HOPS, played=PLAYED), None)
    lg.reset(2, NET, TL)
    lg.set(clock(state="starting", tq=145, speed="2", waiting=4, floor_ms=1700, leaps=HOPS, played=PLAYED), TL.pins)       # read before the start
    v2 = lg.answer(v1(), 0)["v2"]
    assert v2["clock"] == {"state": "starting", "tq": 0, "speed": "2", "dwell_ms": 4000, "fast": False, "waiting": 0, "floor_ms": 1700, "leaps": []}
    assert [p["state"] for p in v2["timeline"]["pins"]] == ["next"] + ["ahead"] * 5
    lg.set(clock(tq="2025-01-27 13:00", speed="2", waiting=1, leaps=HOPS[:1]), None)                    # the next pass reads the run itself
    assert lg.answer(v1(), 0)["v2"]["clock"] == {"state": "live", "tq": 13, "speed": "2", "dwell_ms": 4000, "fast": False, "waiting": 1, "floor_ms": 1600,
                                                 "leaps": [{"from": 1, "to": 13, "ms": 40}]}


def test_leaps_are_kept_from_pass_to_pass_and_read_in_either_form():
    lg = log()
    lg.set(clock(leaps=HOPS[:1]), None)
    lg.set(clock(leaps=[{"from": 13, "to": 25, "ms": 35}], played=[40]), None)        # the conductor has forgotten the first; this one in quarter-hours
    lg.set(clock(leaps=[{"from": 41, "to": 97, "ms": 22.9}, {"from": 13, "to": 25, "ms": 35}]), None)
    assert leaps(lg) == [{"from": 1, "to": 25, "ms": 75}, {"from": 41, "to": 97, "ms": 22}]
    for junk in ([{"from": 97, "to": 97, "ms": 5}], [{"from": 99, "to": 98}], [{"from": "soon", "to": "later"}], [{"to": 120}], ["1-97"], [None], "leaps", 7,
                 [{"from": 97, "to": 113, "ms": "quick"}]):
        lg.set(clock(leaps=junk, played=junk), None)
    assert leaps(lg) == [{"from": 1, "to": 25, "ms": 75}, {"from": 41, "to": 113, "ms": 22}]       # a leap with no time read takes none


def test_beyond_24_leaps_the_oldest_are_joined_with_their_neighbours():
    lg = log()
    hops = [{"from": 4 * k + 1, "to": 4 * k + 3, "ms": 10 + k} for k in range(30)]    # thirty leaps, a played quarter-hour after each
    lg.set(clock(leaps=hops[:24], played=[h["to"] for h in hops]), None)
    assert leaps(lg) == [{"from": h["from"], "to": h["to"], "ms": h["ms"]} for h in hops[:24]]
    lg.set(clock(leaps=hops[20:]), None)
    assert len(leaps(lg)) == 24 == F.LEAPS and leaps(lg)[1:] == [{"from": h["from"], "to": h["to"], "ms": h["ms"]} for h in hops[7:]]
    assert leaps(lg)[0] == {"from": 1, "to": hops[6]["to"], "ms": sum(h["ms"] for h in hops[:7])}


# ---------------------------------------------------------------------- the pins
def test_pins_are_marked_by_the_clock_and_kept_to_the_fixed_lists():
    lg = log()
    note = {"tq": 126, "kind": "surprise", "id": "note"}
    junk = [{"tq": 127, "kind": "surprise", "id": "earthquake"}, {"tq": 1, "kind": "gate", "id": "sale"}, {"tq": "129", "kind": "stop", "id": "delivery"},
            {"tq": 3, "kind": "stop", "id": "note"}, {"tq": 3, "kind": ["stop"], "id": "sale"}, {"kind": "stop", "id": "sale"}, "a pin", None]
    lg.set(clock(tq=125), TL.pins + [note, dict(note), *junk])
    pins = lg.answer(v1(), 0)["v2"]["timeline"]["pins"]
    assert [(p["tq"], p["kind"], p["id"], p["state"], p["jump"]) for p in pins] == [
        (1, "stop", "sale", "past", False), (113, "stop", "request", "past", False), (125, "stop", "before", "past", False),
        (126, "surprise", "note", "next", False), (129, "stop", "delivery", "ahead", True), (141, "stop", "end", "ahead", True),
        (144, "stop", "readings", "ahead", True)]
    assert lg.faults["set"] == len(junk) and all(list(p) == ["tq", "kind", "id", "state", "jump"] for p in pins)
    lg.set(clock(tq=130), None)                                                       # None: the pins in hand, marked by the clock again
    assert [p["state"] for p in lg.answer(v1(), 0)["v2"]["timeline"]["pins"]] == ["past"] * 5 + ["next", "ahead"]
    for state in ("idle", "starting", "settled", "failed"):                           # no stop is run to while no clock runs
        lg.set(clock(tq=130, state=state), None)
        assert not any(p["jump"] for p in lg.answer(v1(), 0)["v2"]["timeline"]["pins"])
    lg.set(clock(tq=130), [])
    assert lg.answer(v1(), 0)["v2"]["timeline"]["pins"] == []


def test_at_most_48_pins_the_stops_and_the_newest_surprises():
    lg = log()
    surprises = [{"tq": 130 + k // 8, "kind": "surprise", "id": F.KINDS[k % 8]} for k in range(60)]
    lg.set(clock(tq=129), surprises[:30] + TL.pins + surprises[30:])
    pins = lg.answer(v1(), 0)["v2"]["timeline"]["pins"]
    assert len(pins) == 48 == F.PINS and [p["id"] for p in pins if p["kind"] == "stop"] == list(T.STOPS)
    assert sorted((p["tq"], p["id"]) for p in pins if p["kind"] == "surprise") == sorted((p["tq"], p["id"]) for p in surprises[18:])
    assert pins == sorted(pins, key=lambda p: p["tq"])
