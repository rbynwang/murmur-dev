"""Live moments: the beats in rank order with their words, the evening made from facts, when an instance opens and closes, and
what the builder makes of one. Steps are made by hand in the live step's form: where the recorded evening has such a step it
is that step (the recorder's keys) with its beat, quarter-hour, key and say added; the kinds no recording has are written out."""
from __future__ import annotations

import copy
import json
import re
from datetime import datetime
from itertools import product
from typing import Any

import pytest

from demo.page_builder import recordings
from demo.page_builder.live import beats as B
from demo.page_builder.live.evening import LiveEvening
from demo.page_builder.live.story import LiveStory
from demo.page_builder.replay import figures as F, moments as M, panels as P
from demo.page_builder.replay.blocks import Map
from demo.page_builder.replay.evening import Evening

FACTS = {"day": "2025-01-28", "homes": 8, "buildings": 2, "sites": 3, "model": "qwen3.5:4b-q4_K_M",
         "follow": {"thinking_home": "home-04", "second_home": "home-06", "mall_or_office": "building-01"},
         "half_hours": ["18:00", "18:30", "19:00", "19:30", "20:00", "20:30"]}
RECORDED = Evening(recordings.load(recordings.evenings(recordings.ROOT / "evening_2025-01-28")[0]))
T0 = datetime(2025, 1, 27, 9, 45)
SURPRISES = {"note": ("people", "Owner's note"), "car_now": ("people", "Car needed now"), "weather": ("device", "Weather change"),
             "building_closed": ("people", "Building closes"), "building_need": ("people", "Building needs power"),
             "emergency": ("buyers", "Grid emergency"), "battery_fault": ("node", "Battery fault"), "battery_low": ("node", "Battery low")}
ORDER = ["orders", "ask", "call", "home-safe", "home-model", "bld-offer", "offers-in", "book", "buyer-contract", "node-contract", "frozen",
         "tomorrow", "battery-ask", "ask-refused", "site-ask", "site-answer", *(f"s-{k}" for k in SURPRISES), "note-read", "told",
         "watch-home", "watch-bld", "window", "community-report", "site-report", "exc-model", "exc-code", "report", "call-in", "desk",
         "call-desk", "readings", "settle", "pay"]


def live(beat: str, tq: int | None, key: bool = True, say: bool = False, **s: Any) -> dict[str, Any]:
    """A step in the live form: the recorder's ten keys, and beat, tq, key, say, wall."""
    tq = int((datetime.fromisoformat(s["sim_time"]) - T0).total_seconds() // 900) if tq is None else tq
    lines = [x if isinstance(x, dict) else {"kind": x[0], "text": x[1]} for x in s.get("terminal") or []]
    return {"sim_time": s.get("sim_time") or "2025-01-28 18:00", "stage": s.get("stage") or "exception", "layer": s.get("layer") or "market",
            "from": s.get("from") or "", "to": s.get("to") or "", "node": s.get("node") or "", "title": s.get("title") or "", "plain": s.get("plain") or "",
            "terminal": lines, "values": dict(s.get("values") or {}), "beat": beat, "tq": tq, "key": key, "say": say, "wall": 0.0}


def rec(beat: str, title: str, tq: int | None = None, key: bool = True, say: bool = False, node: str | None = None, nth: int = 0) -> dict[str, Any]:
    """A step of the recorded evening, by its title, as a live step. tq: its own quarter-hour unless another is given."""
    found = [s for s in RECORDED.steps if s["title"] == title and node in (None, s.get("node"))]
    return live(beat, tq, key, say, **copy.deepcopy(found[nth]))


def story(**facts: Any) -> LiveStory:
    return LiveStory(LiveEvening({**FACTS, **facts}))


def ids(given: list) -> list[str]:
    return [m["id"] for _, m in given]


def ask(tq: int, key: bool = True) -> dict[str, Any]:
    return rec("ask", "The utility answers with its order", tq, key)


def call(tq: int) -> dict[str, Any]:
    return rec("call", "The call for offers goes to every member", tq)


def model_reads(answer: str, said: str) -> dict[str, Any]:
    return live("note-read", 125, layer="model", stage="prepare", node="home-04", to="model", title="The model reads the note",
                plain=f"The note goes to the small model on its own short step. The model answers: {said}.", **{"from": "home-04"},
                terminal=[("think", "system: You read a note a person wrote to their home."), ("think", "tools offered: set_owner_wish, no_wish"),
                          ("think", f"answer: {answer}"), ("note", "212 tokens read, 14 written, 640 ms.")])


def buyer_calls(tq: int = 133, buyer: str = "grid-operator") -> dict[str, Any]:
    return live("call-in", tq, layer="buyer", to="coordinator", title="The buyer calls the community", values={"call_kw": 20},
                plain="The grid operator calls for 20 kW from 19:00 to 20:00 at $3.0 per kWh: grid emergency.", **{"from": buyer},
                terminal=[("in", '{"call_id": "c-1", "call_kind": "emergency", "kw": 20, "start": "19:00", "end": "20:00", "price": 3.0}')])


def desk_answers(tq: int = 133) -> list[dict[str, Any]]:
    return [live("call-desk", tq, layer="coordinator", to="members", title="The desk dispatches", values={"call_confirmed_kw": 9.0},
                 plain="2 members are told what they owe on top. Confirmed 9.0 kW, short 11.0 kW.", **{"from": "coordinator"},
                 terminal=[("out", "confirmed 9.0 kW, short 11.0 kW, at $3.0 per kWh")]),
            live("call-desk", tq, say=True, layer="buyer", to="grid-operator", title="The desk answers the buyer", values={"call_confirmed_kw": 12.5},
                 plain="The desk tells the grid operator it has 12.5 kW of the 20 kW called, and is 7.5 kW short.", **{"from": "coordinator"},
                 terminal=[("in", 'confirm: {"id": "c-1", "kw": 12.5, "short_kw": 7.5}')])]


def watch(node: str = "home-04", tq: int = 127) -> list[dict[str, Any]]:
    """A node's opening of the sale: its receipt, then one call through the guard, the seal and the device."""
    return [rec("watch-home", "Step 7: code's opening, on a receipt", tq, say=True, node=node),
            rec("watch-home", "Guard: set_battery done", tq, node=node), rec("watch-home", "Seal and write to home-battery", tq, node=node),
            rec("watch-home", "home-battery takes the write", tq, key=False, node=node)]


def delivery(half: str, tq: int) -> dict[str, Any]:
    return rec("window", next(s["title"] for s in RECORDED.steps if s["title"].startswith(f"Delivery, {half}")), tq)


# ------------------------------------------------------------------------------------------------ beats
def test_the_beats_stand_in_rank_order():
    table = B.beats(True)
    assert [b.id for b in table] == ORDER and [b.rank for b in table] == sorted(b.rank for b in table) and table[0].rank == 0
    rank = {b.id: b.rank for b in table}
    assert rank["battery-ask"] == rank["ask-refused"] and rank["site-ask"] == rank["site-answer"] and rank["watch-home"] == rank["watch-bld"]
    assert len({rank[f"s-{k}"] for k in SURPRISES}) == 1 and len(set(rank.values())) == 30 and rank["call-in"] < rank["desk"] < rank["call-desk"]
    per = {b.id: b.per for b in table}
    by_node = {"home-safe", "home-model", "bld-offer", "note-read", "told", "watch-home", "watch-bld", "exc-model", "exc-code", "report"}
    assert {i for i, p in per.items() if p == "node"} == by_node and [i for i, p in per.items() if p == "half"] == ["window"]
    assert set(per.values()) == {"tq", "node", "half"}
    assert {b.id for b in table} - {b.id for b in B.beats(False)} == {"site-ask", "site-answer", "site-report"}
    assert all(b.mo.id == b.id for b in table)


def test_the_words_of_a_live_evening_are_on_copies():
    mo = {b.id: b.mo for b in B.beats(True)}
    words = {i: (m.title, m.block, m.path or m.side_path, m.big, m.cap) for i, m in mo.items()}
    assert words["tomorrow"] == ("The community agent asks about tomorrow", "buy-u", ("co-market", "town", "buy-u"), "", "")
    assert words["note-read"] == ("The small model reads the note", "{side}-model", ("person", "agent", "model", "agent"), "{note_need}",
                                  "read from the note by the small model")
    assert words["call-in"] == ("A buyer calls on short notice", "co-desk", ("{buyer}", "town", "co-desk"), "{call_kw}", "called for at short notice")
    assert words["desk"] == ("A shortfall reaches the desk", "co-desk", ("agent", "town", "co-desk"), "{short_now}", "reported short")
    assert words["call-desk"] == ("The desk answers the call", "co-desk", ("co-desk", "town", "{buyer}"), "{call_got}", "confirmed of {call_kw} called")
    assert {i: w[:3] for i, w in words.items() if i.startswith("s-")} == {
        "s-note": ("An owner writes to their home", "h-person", ("person", "agent")), "s-car_now": ("An owner needs the car now", "h-person", ("person", "agent")),
        "s-building_closed": ("A building closes early", "b-person", ()), "s-building_need": ("A building needs its power back", "b-person", ()),
        "s-weather": ("The weather changes", "h-dev", ()), "s-battery_fault": ("A battery fails", "h-agent", ()),
        "s-battery_low": ("A battery runs low", "h-agent", ()), "s-emergency": ("A grid emergency is called", "{buyer}", ())}
    assert {i: (m.big, m.cap) for i, m in mo.items() if i in B.CHANGES} == {
        "bld-offer": ("{other_offer}", "offered by {other_place}"), "watch-home": ("{calls_here}", "device calls at this home"),
        "watch-bld": ("{calls_here}", "device calls at {other_place}"), "window": ("{hh_now}", "below the no-sale twin, {hh_span}"),
        "book": ("{sold}", "sold in the fullest half hour, firm power first"), "buyer-contract": ("{sold}", "in the fullest half hour, at {price}"),
        "node-contract": ("{contracts}", "contracts, one per node"), "told": ("In plain words", "what the node told its person")}
    own = {m.id: m for m in M.table(True)}                              # the replay's table says what it said
    assert (own["window"].big, own["book"].cap, own["node-contract"].big) == ("{hh0}", "sold, firm power first", "{members}")
    assert mo["window"] is not {b.id: b.mo for b in B.beats(True)}["window"] and all(len(m.title) <= 48 for m in mo.values())
    assert B.WORDS == {f"s-{k}": words for k, (_, words) in SURPRISES.items()}


def test_every_path_runs_along_the_maps_lines():
    drawn = Map(True).edge_set
    for b, buyer, sd in product(B.beats(True), ("buy-u", "buy-g"), "hb"):
        path = [buyer if x == "{buyer}" else x for x in (M.on_side(b.mo.side_path, sd) if b.mo.side_path else b.mo.path)]
        assert all(hop in drawn for hop in zip(path, path[1:])) and len(path) <= 8, b.id


# ------------------------------------------------------------------------------------------------ the evening
def test_a_live_evening_is_made_from_facts_and_filled_as_the_run_goes():
    ev = LiveEvening(FACTS)
    assert (ev.total, ev.window, ev.home, ev.second, ev.other, ev.other_place, ev.sites, ev.model_short, ev.ctx["day"]) == \
        (10, "18:00 to 21:00", "home-04", "home-06", "building-01", "the shopping center", True, "Qwen 3.5 4B", "2025-01-28")
    assert ev.steps == [] and ev.orders == {} and "site-pv" in ev.map.ids and set(ev.followed) == {"home-04", "home-06", "building-01"}
    bare = LiveEvening({**FACTS, "sites": [], "homes": ["a", "b", "c"], "half_hours": ["2025-01-28 18:00", {"start": "18:30"}], "follow": {}})
    assert (bare.total, bare.window, bare.sites, bare.home, bare.other_place, "site-pv" in bare.map.ids) == (5, "18:00 to 19:00", False, None, "the office", False)
    for s in RECORDED.steps[:2]:                                        # each recorded order, placed again from its own figures
        o = json.loads(re.match(r"place_order\((.*)\)$", s["terminal"][0]["text"]).group(1))
        ev.order(s["from"], o["kw"], f'{o["date"]} {o["start"]}', o["end"], o["price_usd_per_kwh"], o["deposit_usd"])
    assert ev.orders == RECORDED.orders and ev.orders["utility"]["worth"] == "$518.30"
    ev.order("night", 2, "22:00", "12:30", 0.5, 0)                      # over midnight: 14 and a half hours
    assert ev.orders.pop("night") == {"kw": "2 kW", "win": "22:00 to 12:30", "price": "$0.50 per kWh", "worth": "$14.50", "dep": ""}
    ev.totals(deposits={"utility": 51.83, "grid-operator": {"placed_usd": 31.1, "held_usd": 12.28}}, delivered_kwh=293.9)
    ev.totals(sold_kwh=294.1)                                           # merged: what was known stays
    shown = F.trade_all(ev, {"deposit_usd": 82.93, "buyer_utility_usd": 310.68})
    assert (shown["deposits"], shown["sold_kwh"], shown["delivered"]) == ("$82.93", "294 kWh", "294 kWh")
    ev.node("home-04", kind="home", battery_kwh=13.5, devices=["battery", "car"], shelf=["set_battery", "set_thermostat"], firm_kw=[9.78, 9.5],
            tentative_kw=[4.71], offered_kw=[14.49])
    ev.node("home-04", battery_kwh=10.0)                                # merged: what was known stays
    assert P.node_card(ev, "home-04")["rows"] == [["Kind", "home", 0], ["Plans", "by code", 0], ["Battery", "10.0 kWh", 0],
                                                  ["Devices", "battery, car", 0], ["Shelf", "2 tools", 0]]
    shown = F.trade_all(ev, {"_safe_offer_kw": {"home-04": [14.49]}})
    assert (shown["home_safe"], shown["home_firm"], shown["home_tent"]) == ("14.49 kW", "9.78 kW", "4.71 kW")
    ev.node("home-07", kind="home")
    assert ev.followed["home-07"] == {"node": "home-07", "kind": "home"} and ev.home == "home-04"


# ------------------------------------------------------------------------------------------------ opening and closing
def test_an_instance_closes_when_the_clock_leaves_its_quarter_hour_or_stands():
    st = story()
    st.take([call(1)], 1)
    assert st.close(1, "playing") == [] and st.close(1, "waiting") == [] and list(st.open) == [("call", 1)]
    st.take([ask(2)], 2)
    assert ids(st.close(2, "playing")) == ["call"] and list(st.open) == [("ask", 2)]    # (1) the clock has left; a higher beat of
    assert ids(st.close(3, "waiting")) == ["ask"] and st.open == {}                     # another quarter-hour closes nothing
    for mode in ("held", "at_gate", "ended"):                                           # (2) the clock stands at it
        st.take([ask(5)], 5)
        assert ids(st.close(5, mode)) == ["ask"]
    assert st.faults == {"orphans": 0, "cards": 0, "ahead": 0}


def test_a_higher_rank_open_when_the_pass_began_closes_the_lower_one():
    st = story()
    st.take([ask(3)], 3)
    st.close(3, "waiting")
    st.take([call(3)], 3)
    assert st.close(3, "waiting") == []                                 # the call opened in this pass
    st.take([ask(3, key=False)], 3)
    (steps, m), = st.close(3, "waiting")                                # (3): and the step that came in that pass is in it
    assert m["id"] == "ask" and len(steps) == 2 and st.close(3, "waiting") == [] and list(st.open) == [("call", 3)]
    st.take([rec("desk", "Home 90 tells the desk", 3), *desk_answers(3)], 3)
    assert st.close(3, "waiting") == []
    st.take([rec("readings", "Readings are in", 3)], 3)
    assert ids(st.close(3, "waiting")) == ["call"]                      # the desk outranks the call
    assert st.close(3, "waiting") == [] and st.close(3, "waiting") == []                # readings outrank the desk's two, and they stay
    assert ids(st.close(4, "waiting")) == ["desk", "call-desk", "readings"]


def test_eight_quiet_passes_close_an_instance_but_never_inside_a_running_step():
    st = story()
    st.take([ask(1)], 1)
    assert all(st.close(1, mode) == [] for mode in ["waiting", "playing"] * 20)
    assert [ids(st.close(1, "leaping")) for _ in range(8)] == [[]] * 7 + [["ask"]]              # (4)
    st.take([ask(1)], 1)
    assert [ids(st.close(1, "idle")) for _ in range(5)] == [[]] * 5
    st.close(1, "waiting")                                              # a pass inside a running step starts the count again
    assert [ids(st.close(1, "idle")) for _ in range(7)] == [[]] * 7
    st.take([ask(1, key=False)], 1)                                     # and so does a step
    assert [ids(st.close(1, "idle")) for _ in range(9)] == [[]] * 8 + [["ask"]]


def test_at_24_steps_an_instance_closes_at_once_and_its_beat_may_open_again():
    st = story()
    st.take([ask(1) for _ in range(30)], 1)
    assert [(m["id"], len(steps)) for steps, m in st.close(1, "playing")] == [("ask", 24)]
    assert [(m["id"], len(steps)) for steps, m in st.close(2, "playing")] == [("ask", 6)]


def test_a_step_that_opens_nothing_joins_its_beats_instance_or_is_an_orphan():
    st = story()
    st.take([rec("home-model", "Home 71 sends its offer", 1, key=False), rec("home-model", "Home 90 sends its offer", 1, key=False)], 1)
    assert st.close(1, "waiting") == [] and st.open == {}               # nothing opens on them
    st.take([rec("home-model", "Step 5: code's offer, on a receipt", 1, node="home-04")], 1)
    (steps, m), = st.close(1, "held")
    assert [s["n"] for s in steps] == ["Step 5: code's offer, on a receipt", "Home 71 sends its offer"]     # behind the step that opened it
    assert (m["id"], m["w"], st.faults["orphans"]) == ("home-model", "Home 71", 1)                          # home 90's found no instance
    st.take([ask(2, key=False)], 2)
    assert st.close(2, "leaping") == [] and st.faults["orphans"] == 1 and st.close(3, "waiting") == [] and st.faults["orphans"] == 2


def test_a_step_ahead_of_the_clock_waits_until_the_clock_reaches_it():
    st = story()
    st.take([ask(3), call(2)], 2)
    assert list(st.open) == [("call", 2)] and ids(st.close(2, "held")) == ["call"] and st.open == {}
    st.take([], 3)
    assert list(st.open) == [("ask", 3)] and ids(st.close(3, "held")) == ["ask"]
    st.take([ask(9)], 4)
    for n in range(12):
        assert st.close(4, "waiting") == [] and st.faults["ahead"] == (n >= 8)          # counted once, when it has waited over eight passes
    assert ids(st.close(9, "held")) == ["ask"] and st.faults["ahead"] == 1              # and told all the same


def test_what_closes_together_is_given_out_by_quarter_hour_rank_and_opening():
    st = story()
    told = lambda node: rec("told", "The owner is told", 2, node=node)  # noqa: E731
    st.take([told("home-06"), rec("frozen", "The deal is frozen", 2), ask(2), told("home-04"), call(1)], 2)
    given = st.close(2, "ended")
    assert [(m["tq"], m["id"], m["w"]) for _, m in given] == [(1, "call", ""), (2, "ask", ""), (2, "frozen", ""), (2, "told", "Home 90"), (2, "told", "Home 71")]
    assert all(s["tq"] == m["tq"] for steps, m in given for s in steps)


def evening_stream() -> list[dict[str, Any]]:
    """Two days' worth of beats in the order a network sends them: by quarter-hour, and inside one by rank."""
    return [rec("orders", "The utility places its order"), rec("orders", "The grid operator places its order"), ask(1), call(1),
            rec("home-safe", "Steps 1 to 4: the safe figure", node="home-04"), rec("home-model", "Home 71 sends its offer", key=False),
            rec("home-model", "Step 5: code's offer, on a receipt", node="home-04"),
            rec("bld-offer", "Step 5: code's offer, on a receipt", node="building-01"), rec("home-model", "The call reaches home 71", 1, key=False),
            rec("buyer-contract", "The coordinator names the meters and the kW"), rec("buyer-contract", "The contract is active", say=True),
            rec("node-contract", "Each node gets its contract"), watch("home-04")[0], watch("home-06")[0], *watch("home-04")[1:],
            *watch("home-06")[1:], rec("exc-model", "Step 8: code's answer, on a receipt", 133, node="home-06"), buyer_calls(),
            rec("desk", "Home 90 tells the desk", 133), desk_answers()[0], rec("desk", "The desk asks who can add", 133),
            rec("desk", "The desk dispatches", 133), desk_answers()[1], delivery("18:00", 135), delivery("18:30", 137)]


def told_by(plan: list[tuple[list[dict[str, Any]], int]]) -> tuple[str, dict[str, int]]:
    st = story()
    given = []
    for steps, now in plan:
        st.take(copy.deepcopy(steps), now)
        given += st.close(now, "playing")
    end = max(s["tq"] for steps, _ in plan for s in steps) + 1
    given += st.close(end, "ended") + st.close(end, "ended")
    return json.dumps(given, ensure_ascii=False), st.faults


def test_fed_singly_or_in_bursts_the_same_moments():
    stream = evening_stream()
    chunks = lambda n: [stream[i:i + n] for i in range(0, len(stream), n)]  # noqa: E731
    singly = told_by([([s], s["tq"]) for s in stream])
    told, faults = singly
    order = [(m["tq"], m["id"], len(steps)) for steps, m in json.loads(told)]
    assert order == [(0, "orders", 2), (1, "ask", 1), (1, "call", 1), (1, "home-safe", 1), (1, "home-model", 3), (1, "bld-offer", 1),
                     (1, "buyer-contract", 2), (1, "node-contract", 1), (127, "watch-home", 4), (127, "watch-home", 4), (133, "exc-model", 1),
                     (133, "call-in", 1), (133, "desk", 3), (133, "call-desk", 2), (135, "window", 1), (137, "window", 1)]
    assert faults == {"orphans": 0, "cards": 0, "ahead": 0}
    for n in (2, 3, 5, 9, len(stream)):
        assert told_by([(c, c[-1]["tq"]) for c in chunks(n)]) == singly, n              # bursts, the clock read after them
        assert told_by([(c, c[0]["tq"]) for c in chunks(n)]) == singly, n               # the clock read at the pass's start: some wait
    by_step = [[s for s in stream if s["tq"] == tq] for tq in sorted({s["tq"] for s in stream})]
    assert told_by([(c, c[0]["tq"]) for c in by_step]) == singly                        # a quarter-hour a pass


def test_nothing_given_out_ever_changes():
    st = story()
    st.take(evening_stream()[:9], 1)
    first = st.close(1, "held")
    kept = copy.deepcopy(first)
    st.take(evening_stream()[9:], 137)
    assert len(st.close(137, "ended")) == 10 and first == kept


# ------------------------------------------------------------------------------------------------ building one
def given_for(steps: list[dict[str, Any]], st: LiveStory | None = None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    st = st or story()
    st.take(steps, max(s["tq"] for s in steps))
    return st.close(max(s["tq"] for s in steps), "ended")[-1]


def test_the_key_steps_and_the_say_step_are_the_instances_own():
    named = rec("buyer-contract", "The coordinator names the meters and the kW")
    active = rec("buyer-contract", "The contract is active", say=True)
    drafts = rec("buyer-contract", "The buyer drafts the contract", key=False)
    steps, m = given_for([named, drafts, active])
    assert m["k"]["did"] == "The contract is active." and [max(l[4] for l in s["l"]) > 0 for s in steps] == [True, False, True]
    assert (m["n"], m["k"]["kind"], m["b"], m["p"], m["c"]) == ("Each buyer signs", "market", "co-market", ["co-market", "town", "buy-u"], "contract")
    named["say"], active["say"] = False, False                          # with no say step, the first key step says it
    assert given_for([named, drafts, active])[1]["k"]["did"] == "The community agent names the meters and this buyer's share of the capacity sold."


def test_the_big_figures_only_a_live_moment_has():
    st = story()
    st.ev.order("utility", 84.69, "18:00", "21:00", 2.04, 51.83)
    hero = lambda steps: given_for(steps, st)[1]["hero"]  # noqa: E731
    assert hero([rec("node-contract", "Each node gets its contract")]) == ["10", "contracts, one per node"]
    m = given_for([rec("tomorrow", "The coordinator asks what's wanted tomorrow", 97)], st)[1]
    assert (m["hero"], m["k"]["kind"], m["b"], m["p"], m["k"]["big"]) == (None, "buyers", "buy-u", ["co-market", "town", "buy-u"], [])
    assert hero([model_reads('set_owner_wish({"wish": "keep_battery_full", "until": "2025-01-29 06:00"})', "set_owner_wish")]) == \
        ["Keep the battery full", "read from the note by the small model"]
    blocked = {**watch()[1], "title": "Guard: set_thermostat blocked"}
    assert hero(watch() + [blocked]) == ["1", "device calls at this home"]              # the calls that ran, not the ones refused
    steps, m = given_for([buyer_calls()], st)
    assert (m["hero"], m["p"], m["k"]["kind"], m["b"]) == (["20 kW", "called for at short notice"], ["buy-g", "town", "co-desk"], "desk", "co-desk")
    assert given_for([buyer_calls(134, "utility")], st)[1]["p"] == ["buy-u", "town", "co-desk"]         # each moment by its own buyer
    steps, m = given_for(desk_answers(134), st)
    assert (m["hero"], m["p"], m["k"]["kind"]) == (["12.5 kW", "confirmed of 20 kW called"], ["co-desk", "town", "buy-g"], "desk")
    steps, m = given_for([rec("desk", "Home 90 tells the desk", 135), rec("desk", "The desk asks who can add", 135),
                          rec("desk", "The desk dispatches", 135), rec("desk", "Home 71 answers the desk", 135, key=False)], st)
    assert m["hero"] == ["18.74 kW", "reported short, by Home 90"] and m["p"] == ["h-agent", "town", "co-desk"] and len(steps) == 4
    cards = {c["h"]: {r[0]: r[1] for r in c["rows"]} for c in m["k"]["cd"]}         # the report and the desk's answer to it, on one card
    assert cards["Reported"] == {"Node": "Home 90", "Short by": "18.74 kW", "From": "18:45"} and cards["What the desk did"]["Asked"] == "3 members"
    assert cards["What the desk did"]["Confirmed"] == "11.9 kW" and m["k"]["kind"] == "desk"     # the builder's running total: 9.0 and 2.9
    no_wish = given_for([model_reads("no_wish({})", "no_wish")])[1]
    assert no_wish["hero"] == ["No need", "read from the note by the small model"] and no_wish["b"] == "h-model" and no_wish["k"]["kind"] == "model"
    assert no_wish["p"] == ["h-person", "h-agent", "h-model", "h-agent"]


def test_the_window_shows_its_half_hour_and_the_evening_so_far():
    st = story()
    steps, first = given_for([delivery("18:00", 131)], st)
    steps, second = given_for([delivery("18:30", 133)], st)
    kw = [s["values"]["live_kw"] for s in RECORDED.steps if s["title"].startswith("Delivery")][:2]
    assert first["hero"] == [f"{kw[0]:,.0f} kW", "below the no-sale twin, 18:00 to 18:30"] and second["hero"][1] == "below the no-sale twin, 18:30 to 19:00"
    table = lambda m: m["k"]["cd"][0]["tbl"]  # noqa: E731
    assert table(first)[0] == ["kW", "18:00"] and table(second)[0] == ["kW", "18:00", "18:30"] and second["k"]["cd"][0]["h"] == "Below the no-sale twin"
    assert table(second)[3] == ["All", f"{kw[0]:,.0f}", f"{kw[1]:,.0f}"] and len(steps) == 1 and (second["k"]["kind"], second["b"]) == ("device", "h-dev")
    assert second["k"]["cd"][1]["rows"][0] == ["Below the twin", f"{sum(kw) / 2:,.0f} kWh", 1]
    both = story()
    both.take([delivery("18:00", 133), delivery("18:30", 133)], 133)                # two half hours shaped in one pass: an instance each
    assert [m["hero"][1][-14:] for _, m in both.close(133, "held")] == ["18:00 to 18:30", "18:30 to 19:00"]


@pytest.mark.parametrize("kind", sorted(SURPRISES))
def test_a_surprise_is_tagged_and_carded_by_its_box(kind: str):
    node, sender = ("building-01" if kind.startswith("building") else "home-04"), ("grid-operator" if kind == "emergency" else "console")
    post = live(f"s-{kind}", 125, layer="person", stage="prepare", node=node, to=node, title="The console posts a surprise",
                plain="The presenter's console posts it to the part it is for.", **{"from": sender},
                terminal=[("in", '{"kind": "%s", "at": "2025-01-28 17:15"}' % kind), ("out", '{"ok": true}')])
    steps, m = given_for([post])
    box = {"people": "b-person" if kind.startswith("building") else "h-person", "device": "h-dev", "buyers": "buy-g", "node": "h-agent"}[SURPRISES[kind][0]]
    assert (m["id"], m["tag"], m["k"]["kind"], m["b"], m["hero"], m["k"]["big"]) == (f"s-{kind}", ["Surprise", SURPRISES[kind][1]], SURPRISES[kind][0], box, None, [])
    assert m["p"] == (["h-person", "h-agent"] if kind in ("note", "car_now") else []) and len(steps) == 1 and steps[0]["l"][0][4] > 0
    assert all(len(c.get("tbl", [0, 0])) > 1 for c in m["k"]["cd"]) and len(m["k"]["cols"].split()) == max(1, len(m["k"]["cd"]))
    if kind == "weather":                                               # the half hours' table has no half hour yet: its card is left out
        assert [c["h"] for c in m["k"]["cd"]] == ["So far"] and m["k"]["cols"] == "2.2fr"


def test_a_moment_the_builder_cannot_make_is_given_out_as_other():
    st = story()
    guard = rec("watch-home", "Guard: set_battery done", 127, node="home-04")
    guard["terminal"] = [x for x in guard["terminal"] if not x["text"].startswith("set_battery(")]          # the card reads the call from this line
    guard["plain"] = "The guard reads the call against the node's facts. " * 4
    steps, m = given_for([guard, rec("watch-home", "Seal and write to home-battery", 127, node="home-04")], st)
    assert (m["id"], m["n"], m["b"], m["w"], m["p"], m["hero"], m["tag"], m["tv"]) == ("other", "Guard: set_battery done", "h-guard", "Home 71", [], None, None, 0)
    assert m["k"] == {"kind": "aggpart", "cb": "h-guard", "l": 5, "who": [], "in": [], "out": [], "did": guard["plain"][:124], "rule": "", "cd": [],
                      "cols": "1fr", "term": ["aggregator", "what this part read and worked out for the day"], "big": []}
    assert [s["n"] for s in steps] == ["Guard: set_battery done", "Seal and write to home-battery"] and st.faults["cards"] == 1
    assert set(m["lit"]) == {"h-tools", "h-guard", "h-seal", "h-driver"} and sum(l[4] == 1 for l in steps[0]["l"]) == 6
    steps, m = given_for([live("no-such-beat", 128, title="rt_strange", plain="A message of a kind nobody shapes.", layer="town", to="coordinator")], st)
    assert (m["id"], m["n"], m["b"], m["k"]["did"], st.faults["cards"]) == ("other", "rt_strange", "co-market", "A message of a kind nobody shapes.", 2)
    assert given_for(watch(), st)[1]["id"] == "watch-home" and st.faults["cards"] == 2             # the story goes on
