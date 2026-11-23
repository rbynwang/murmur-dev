"""The live shapers' base: each formatter against values worked by hand, the count of quarter-hours at the points the design
names, the keys of a step, the one place where a live id becomes its page id, and the fault path that lets no shaper raise."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from demo.page_builder.live import fmt
from demo.page_builder.live.shape import Row, Shaping, boxes
from demo.page_builder.replay import figures as F, moments as M
from demo.page_builder.replay.text import stamp

T0 = "2025-01-27 09:45"                 # the example evening's zero: 09:45 on the day before the sale's
KEYS = ["sim_time", "stage", "layer", "from", "to", "node", "title", "plain", "terminal", "values", "beat", "tq", "key", "say", "wall"]
OFFER = Row("home-model", "offers", "agent", "{node} sends its offer", "It offers {kw} kW from {start}.", True, False, "{side}-agent")
CALL = Row("call", "offers", "town", "The call for offers goes out", "One call goes to {n}.", True, True, "town")
DESK = Row("call-in", "exception", "market", "A buyer's call reaches the desk", "The desk takes the call.", True, True, "co-desk")
BOOK = Row("book", "offers", "market", "The book fills the order", "Sold: {sold} kW.", True, True, "co-market")
EVENT = {"event": "accepted", "message_id": "m-1", "from": "home-02", "to": "community", "kind": "on_discover",
         "body": {"kw": 1.25, "start": "18:00"}, "at": 12.5}


def shaping(alias: dict[str, str] | None = None) -> Shaping:
    return Shaping(None, ["home-02", "building-01"], alias, T0)


def offer(sh: Shaping, event: dict, tq: int) -> list[dict]:
    """A shaper as the bus steps write one: it reads the item's fields and makes its step."""
    body = event["body"]
    return [sh.step(OFFER, tq, event["at"], frm=event["from"], to=event["to"], node=event["from"], kw=fmt.n2(body["kw"]),
                    start=body["start"], lines=[fmt.T("in", fmt.J(body))], values={"offer_kw": body["kw"]})]


# ---------------------------------------------------------------------------------------------------- fmt
def test_a_line_is_of_one_of_the_nine_kinds():
    assert fmt.KINDS == ("in", "out", "think", "calc", "sign", "tool", "guard", "write", "note")
    assert fmt.T("in", "discover to community") == {"kind": "in", "text": "discover to community"}
    assert fmt.T("calc", 12) == {"kind": "calc", "text": "12"}
    with pytest.raises(ValueError):
        fmt.T("shout", "x")


def test_json_as_a_line_shows_it():
    assert fmt.J({"kw": 9.0, "to": ["home-02", "building-01"], "note": "café", "none": None, "ok": True}) == \
        '{"kw": 9.0, "to": ["home-02", "building-01"], "note": "café", "none": null, "ok": true}'
    assert fmt.J({"k": "x" * 50}, 59) == '{"k": "' + "x" * 50 + '"}'                    # 59 characters: whole
    assert fmt.J({"k": "x" * 50}, 20) == '{"k": "' + "x" * 13 + " … (59 characters in all)"
    assert fmt.J(["x" * 1500], 10) == '["xxxxxxxx … (1,504 characters in all)'
    assert fmt.J({"ids": {7}}) == '{"ids": "{7}"}'                                    # what JSON cannot say is said as text


def test_cuts():
    assert fmt.cut("abcdefghijklmnopqrstuvwxyz") == "abcdefghijklmnop…"
    assert fmt.cut("abcdefghijklmnop") == "abcdefghijklmnop"
    assert fmt.cut("abcdef", 3) == "abc…"
    assert fmt.cut(None) == "" and fmt.cut(1234567, 4) == "1234…"


def test_times():
    assert fmt.hm("2025-01-28 18:30") == "18:30" and fmt.hm(None) == "" and fmt.hm("") == ""
    assert fmt.dt("2025-01-28 18:30") == "28 Jan 18:30"
    assert fmt.dt("2025-12-05 07:05") == "5 Dec 07:05"
    assert fmt.dt(None) == "" and fmt.dt("") == ""


def test_kw_and_money():
    assert fmt.n0(1234.4) == "1,234" and fmt.n0(0.6) == "1" and fmt.n0("7") == "7"
    assert fmt.n1(1234.56) == "1,234.6" and fmt.n1(9) == "9.0" and fmt.n1(26.067) == "26.1"
    assert fmt.n2(26.067) == "26.07" and fmt.n2(0.126) == "0.13" and fmt.n2(5) == "5.00"
    assert fmt.usd(20.7893) == "$20.79" and fmt.usd(14.573) == "$14.57" and fmt.usd(0) == "$0.00"
    assert fmt.usd(1234567.5) == "$1,234,567.50"
    for f in (fmt.n0, fmt.n1, fmt.n2, fmt.usd):
        with pytest.raises(TypeError):
            f(None)
        with pytest.raises(ValueError):
            f("much")


def test_plurals():
    assert fmt.pl(1, "member") == "1 member" and fmt.pl(3, "member") == "3 members" and fmt.pl(0, "reading") == "0 readings"
    assert fmt.pl(2, "battery", "batteries") == "2 batteries" and fmt.pl(1, "battery", "batteries") == "1 battery"


def test_a_table_sets_every_column_to_the_right():
    assert fmt.table(["half hour", "kW", "usd"], [["18:00", "9.0", "$1.20"], ["18:30", 12.5, "$10.00"]]) == [
        "half hour    kW     usd",
        "    18:00   9.0   $1.20",
        "    18:30  12.5  $10.00"]
    assert fmt.table(["a"], []) == ["a"]
    with pytest.raises(IndexError):
        fmt.table(["a", "b"], [["1"]])


def test_scrub_lets_nothing_private_out():
    seal = "ab12" * 16                                                  # 64 hex characters
    home = "/" + "Users" + "/ada/murmur/out/runs/7/homes/state"         # in pieces: no file of the repository holds such a path
    assert fmt.scrub(f"seal {seal} set") == "seal ab12ab12ab12ab12… set"
    assert fmt.scrub("sig " + "AB12" * 12) == "sig AB12AB12AB12AB12…"
    assert fmt.scrub("a" * 47) == "a" * 47
    assert fmt.scrub(f'{{"log": "{home}/home-02.jsonl", "n": 3}}') == '{"log": "<local path>", "n": 3}'
    assert fmt.scrub("kept in " + "/" + "home" + "/ada/run, then ~/run/7 (/private/tmp/run/7)") == "kept in <local path>, then <local path> (<local path>)"
    assert fmt.scrub("POST /demo/scenario and /b/building-01/demo/scenario") == "POST /demo/scenario and /b/building-01/demo/scenario"
    assert fmt.scrub("asked http://127.0.0.1:51020/v2/summary and 203.0.113.7") == "asked http://<network address>/v2/summary and <network address>"
    assert fmt.scrub("9.5 kW of 12.25, version 2.0.0") == "9.5 kW of 12.25, version 2.0.0"
    assert fmt.scrub({"sig": seal, "rows": [seal, 3, None, {"at": home}], "kw": 1.5}) == \
        {"sig": "ab12ab12ab12ab12…", "rows": ["ab12ab12ab12ab12…", 3, None, {"at": "<local path>"}], "kw": 1.5}
    assert fmt.scrub(fmt.scrub(f"seal {seal}")) == fmt.scrub(f"seal {seal}")


# ---------------------------------------------------------------------------------------------------- the clock
@pytest.mark.parametrize("ts, tq", [("2025-01-27 09:45", 0), ("2025-01-27 10:00", 1), ("2025-01-27 23:45", 56), ("2025-01-28 00:00", 57),
                                    ("2025-01-28 10:00", 97), ("2025-01-28 14:00", 113), ("2025-01-28 18:00", 129), ("2025-01-28 21:00", 141),
                                    ("2025-01-28 23:45", 152), ("2025-01-29 00:00", 153), ("2025-01-29 02:45", 164), ("2025-01-27 09:30", -1)])
def test_quarter_hours_since_the_day_before_at_0945(ts, tq):
    """D-1 10:00 is 1 and D 18:00 is 129; the count runs on over both midnights to the last row of the example's evening."""
    sh = shaping()
    assert sh.tq(ts) == tq and sh.ts(tq) == ts


def test_a_time_inside_a_quarter_hour_and_a_text_that_is_no_time():
    sh = shaping()
    assert sh.tq("2025-01-28 18:07") == 129 and sh.tq("2025-01-28 18:14:59") == 129 and sh.tq("2025-01-28T18:15:00") == 130
    assert isinstance(sh.tq("2025-01-28 18:00"), int)
    for bad in (None, "", "soon", 18.0, "2025-01-28"):
        with pytest.raises(ValueError):
            sh.tq(bad)
    with pytest.raises(ValueError):
        Shaping(None, [], None, "soon")


def test_tq_is_the_consoles_timeline_tq():
    """The console counts the same quarter-hours from the same zero (demo/console/timeline.py), on the hour and inside it."""
    from demo.console import timeline
    tl = timeline.build({"date": "2025-01-28", "window": ["18:00", "21:00"]}, [])
    sh = Shaping(None, [], None, tl.t0)
    assert tl.t0 == T0 and sh.tq("2025-01-28 18:00") == tl.tq("2025-01-28 18:00") == 129
    first = datetime(2025, 1, 27, 8, 0)
    for i in range(700):                                                # every 4 minutes, from before the zero to after the last row
        ts = (first + timedelta(minutes=4 * i)).strftime("%Y-%m-%d %H:%M")
        assert sh.tq(ts) == tl.tq(ts) == timeline.tq(ts, T0), ts


# ---------------------------------------------------------------------------------------------------- a step
def test_a_step_has_the_recorders_keys_and_five_more():
    s = offer(shaping(), EVENT, 1)[0]
    assert list(s) == KEYS
    assert s == {"sim_time": "2025-01-27 10:00", "stage": "offers", "layer": "home_agent", "from": "home-02", "to": "coordinator",
                 "node": "home-02", "title": "home-02 sends its offer", "plain": "It offers 1.25 kW from 18:00.",
                 "terminal": [{"kind": "in", "text": '{"kw": 1.25, "start": "18:00"}'}], "values": {"offer_kw": 1.25},
                 "beat": "home-model", "tq": 1, "key": True, "say": False, "wall": 12.5}


def test_the_builder_reads_a_step_as_it_reads_a_recorded_one():
    s, seen = offer(shaping(), EVENT, 1)[0], {}
    F.take_facts(s, seen)
    assert seen == {"_offer_kw": {"home-02": 1.25}} and stamp(s["sim_time"]) == "Mon 10:00" and M.side(s) == "h"
    assert M.block_of(s) == ["h-agent"] and M.line_blocks(s, "in", s["terminal"][0]["text"]) == ["h-agent"]


def test_a_step_with_nothing_but_its_row():
    s = shaping().step(DESK, 130, 71.0)
    assert list(s) == KEYS and (s["from"], s["to"], s["node"], s["terminal"], s["values"]) == ("", "", "", [], {})
    assert (s["sim_time"], s["title"], s["plain"], s["key"], s["say"]) == ("2025-01-28 18:15", DESK.title, DESK.plain, True, True)


def test_a_delivery_step_keeps_its_half_hour_and_a_step_may_take_key_and_say():
    sh = shaping()
    s = sh.step(DESK, 131, 80.0, sim_time="2025-01-28 18:00", key=False, say=False, values={"live_kw": 9.5})
    assert (s["sim_time"], s["tq"], s["key"], s["say"], s["values"]) == ("2025-01-28 18:00", 131, False, False, {"live_kw": 9.5})
    assert sh.step(OFFER, 1, 0.0, node="home-02", kw="1", start="18:00", say=True)["say"] is True


def test_the_agent_layer_follows_the_steps_node():
    sh = shaping({"building-01": "building-02"})
    words = {"kw": "30", "start": "18:00"}
    assert sh.step(OFFER, 1, 0.0, node="home-03", **words)["layer"] == "home_agent"
    assert sh.step(OFFER, 1, 0.0, node="building-01", **words)["layer"] == "building_agent"
    assert sh.step(CALL, 1, 0.0, node="building-01", n="4 members")["layer"] == "town"


def test_a_line_of_no_known_kind_and_a_word_not_given_raise_in_step():
    sh = shaping()
    with pytest.raises(KeyError):
        sh.step(OFFER, 1, 0.0, node="home-02", kw="1.25")
    with pytest.raises(ValueError):
        sh.step(DESK, 1, 0.0, lines=[{"kind": "shout", "text": "x"}])


# ---------------------------------------------------------------------------------------------------- alias
def test_a_live_id_becomes_its_page_id_in_one_place():
    sh = shaping({"building-01": "building-02", "building-02": "building-01", "comm-1": "community", "home-02": "home-02"})
    assert sh.alias == {"building-01": "building-02", "building-02": "building-01", "comm-1": "community"}
    assert [sh.name(x) for x in ("building-01", "building-02", "comm-1", "community", "home-02", "utility", None)] == \
        ["building-02", "building-01", "coordinator", "coordinator", "home-02", "utility", ""]
    row = Row("bld-offer", "offers", "agent", "{node} answers {to}", "{frm} offers {kw} kW.", True, True, "b-agent")
    s = sh.step(row, 1, 0.0, frm="building-01", to="comm-1", node="building-01", kw="30",
                lines=[fmt.T("out", "building-01 and building-02, not building-011 or xbuilding-01; id=m1:building-01:offer:0"),
                       fmt.T("in", fmt.J({"from": "building-01", "to": "comm-1", "community": "COMMUNITY_01"}))],
                values={"site_cards": [["building-01", [["asked", "9 kW"]]]], "offer_kw": 30.0, "note": None})
    assert (s["from"], s["to"], s["node"], s["layer"]) == ("building-02", "coordinator", "building-02", "building_agent")
    assert (s["title"], s["plain"]) == ("building-02 answers community", "building-02 offers 30 kW.")
    assert [x["text"] for x in s["terminal"]] == ["building-02 and building-01, not building-011 or xbuilding-01; id=m1:building-02:offer:0",
                                                  '{"from": "building-02", "to": "community", "community": "COMMUNITY_01"}']
    assert s["values"] == {"site_cards": [["building-02", [["asked", "9 kW"]]]], "offer_kw": 30.0, "note": None}


def test_without_an_alias_every_id_is_its_own_page_id_and_every_text_is_still_scrubbed():
    s = shaping().step(DESK, 1, 0.0, frm="building-01", to="community", lines=[fmt.T("sign", "sig " + "0f" * 64)],
                       values={"key": "c3" * 32})
    assert (s["from"], s["to"]) == ("building-01", "coordinator")
    assert s["terminal"] == [{"kind": "sign", "text": "sig 0f0f0f0f0f0f0f0f…"}] and s["values"] == {"key": "c3c3c3c3c3c3c3c3…"}


# ---------------------------------------------------------------------------------------------------- what a run keeps
def test_follow_set_snapshot_marks_and_counters():
    ev = object()
    sh = Shaping(ev, ("home-02", "home-03"), None, T0)
    assert sh.ev is ev and sh.follow == {"home-02", "home-03"} and (sh.alias, sh.t0, sh.snap, sh.faults, sh.why) == ({}, T0, {}, {"shape": 0}, [])
    sh.follow.add("building-01")
    assert "building-01" in sh.follow
    assert sh.once("sale-1", "confirm") is True and sh.once("sale-1", "confirm") is False
    assert sh.once("sale-2", "confirm") is True and sh.once("sale-1", "select") is True and sh.once("sale-1", "select") is False
    sh.count["community.report"] += 2
    assert sh.count["community.report"] == 2 and sh.count["rt_confirm"] == 0


# ---------------------------------------------------------------------------------------------------- the fault path
def test_shaped_gives_what_the_shaper_made():
    sh = shaping()
    one = sh.step(DESK, 1, 3.0)
    assert sh.shaped(OFFER, EVENT, 1, 12.5, offer, sh, EVENT, 1) == offer(sh, EVENT, 1)
    assert sh.shaped(DESK, {"kind": "rt_call"}, 1, 3.0, lambda: one) == [one]
    assert sh.shaped(DESK, {"kind": "rt_call"}, 1, 3.0, lambda: None) == []
    assert sh.shaped(DESK, {"kind": "rt_call"}, 1, 3.0, lambda a, b: (x for x in (a, b)), one, one) == [one, one]
    assert sh.faults == {"shape": 0} and sh.why == []


@pytest.mark.parametrize("body, why, text", [
    ({"kw": 1.25}, "KeyError: 'start'", '"body": {"kw": 1.25}'),
    ({"kw": None, "start": "18:00"}, "TypeError", '"body": {"kw": null, "start": "18:00"}'),
    ({"kw": "much", "start": "18:00"}, "ValueError", '"body": {"kw": "much", "start": "18:00"}'),
    (None, "TypeError", '"body": null'),
    ([], "TypeError", '"body": []')])
def test_an_item_lacking_a_field_gives_one_step_titled_by_its_kind(body, why, text):
    sh = shaping()
    event = {**EVENT, "body": body}
    out = sh.shaped(OFFER, event, 1, 12.5, offer, sh, event, 1, node="home-02")
    line = '{"event": "accepted", "message_id": "m-1", "from": "home-02", "to": "community", "kind": "on_discover", ' + text + ', "at": 12.5}'
    assert out == [{"sim_time": "2025-01-27 10:00", "stage": "offers", "layer": "home_agent", "from": "home-02", "to": "coordinator",
                    "node": "home-02", "title": "on_discover", "plain": "", "terminal": [{"kind": "note", "text": line}], "values": {},
                    "beat": "home-model", "tq": 1, "key": True, "say": False, "wall": 12.5}]
    assert sh.faults == {"shape": 1} and len(sh.why) == 1 and sh.why[0].startswith("on_discover: " + why)


def test_a_word_the_row_names_and_a_line_of_no_kind_are_faults_too():
    sh = shaping()
    out = sh.shaped(OFFER, EVENT, 1, 12.5, lambda: sh.step(OFFER, 1, 12.5, node="home-02", kw="1.25"))
    out += sh.shaped(DESK, {"kind": "rt_call", "from": "utility", "to": "community"}, 130, 70.0,
                     lambda: [sh.step(DESK, 130, 70.0, lines=[{"kind": "shout", "text": "x"}])])
    assert [(s["title"], s["beat"], s["stage"], s["layer"], s["from"], s["to"], s["node"], s["key"], s["say"]) for s in out] == [
        ("on_discover", "home-model", "offers", "home_agent", "home-02", "coordinator", "", True, False),
        ("rt_call", "call-in", "exception", "market", "utility", "coordinator", "", True, True)]
    assert sh.faults == {"shape": 2} and [w.split(":")[1].strip() for w in sh.why] == ["KeyError", "ValueError"]


def test_the_fault_step_of_a_nodes_row_and_of_an_item_with_no_kind():
    sh = shaping({"building-01": "building-02"})
    row = {"n": 7, "kind": "receipt", "node": "building-01", "ts": "2025-01-28 18:15", "step": 7, "receipt": {"kind": "opening"}}
    s = sh.shaped(OFFER, row, sh.tq(row["ts"]), 64.0, lambda: row["receipt"]["calls"][0])[0]
    assert (s["title"], s["node"], s["layer"], s["tq"], s["sim_time"], s["wall"]) == ("receipt", "building-02", "building_agent", 130, "2025-01-28 18:15", 64.0)
    assert s["terminal"] == [{"kind": "note", "text": '{"n": 7, "kind": "receipt", "node": "building-02", "ts": "2025-01-28 18:15", "step": 7, '
                                                      '"receipt": {"kind": "opening"}}'}]
    snap = {"orders": [], "alloc": None}
    assert sh.shaped(BOOK, snap, 1, 2.0, lambda: BOOK.plain.format(), kind="snapshot")[0]["title"] == "snapshot"
    assert sh.shaped(BOOK, snap, 1, 2.0, lambda: 1 / 0)[0]["title"] == "book"
    assert sh.shaped(BOOK, "not a mapping", 1, 2.0, lambda: 1 / 0)[0]["terminal"] == [{"kind": "note", "text": '"not a mapping"'}]
    assert sh.faults == {"shape": 4}


def test_a_fault_steps_json_is_cut_at_600_named_for_the_page_and_scrubbed():
    sh = shaping({"building-01": "building-02"})
    item = {"kind": "on_status", "from": "building-01", "body": {"sig": "ab12" * 32, "pad": "x" * 700}}
    text = sh.shaped(BOOK, item, 141, 9.0, lambda: item["body"]["batch"])[0]["terminal"][0]["text"]
    head = '{"kind": "on_status", "from": "building-02", "body": {"sig": "ab12ab12ab12ab12…", "pad": "'
    assert len(fmt.J(item)) == 904                    # 201 characters before the pad as the item came, so the cut falls 399 into it
    assert text == head + "x" * 399 + " … (904 characters in all)"


def test_only_the_first_twenty_faults_keep_their_reason():
    sh = shaping()
    for i in range(25):
        sh.shaped(DESK, {"kind": "rt_call", "i": i}, 1, 0.0, lambda: 1 / 0)
    assert sh.faults == {"shape": 25} and len(sh.why) == 20 and sh.why[0] == "rt_call: ZeroDivisionError: division by zero"


# ---------------------------------------------------------------------------------------------------- where a step lands
def test_the_boxes_the_builder_gives_a_step():
    sh = shaping({"building-01": "building-02"})
    assert boxes(sh.step(DESK, 130, 0.0)) == [DESK.box]
    assert boxes(sh.step(BOOK, 1, 0.0, sold="14.4")) == [BOOK.box]
    for node, side in (("home-02", "h"), ("building-01", "b")):
        assert boxes(sh.step(OFFER, 1, 0.0, node=node, kw="1", start="18:00")) == [OFFER.box.replace("{side}", side)]
    call = sh.step(CALL, 1, 0.0, frm="community", to="building-01", n="4 members",
                   lines=[fmt.T("out", "envelope  from=community  to=building-01"), fmt.T("in", "discover to building-01")])
    assert boxes(call) == ["b-agent", "town"] and CALL.box in boxes(call)
