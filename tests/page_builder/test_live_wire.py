"""The wire forms of a live step and a live moment: lines as pieces that draw exactly what the builder paints, the fixed lists
the page takes, and every cap and cut, checked on the recorded evening and on values made to be too big."""
from __future__ import annotations

import datetime as dt
import html
import json
import re
from functools import lru_cache
from typing import Any

import pytest

from demo.page_builder import names as N, recordings, templating as T
from demo.page_builder.live import wire
from demo.page_builder.live.evening import LiveEvening
from demo.page_builder.live.story import LiveStory
from demo.page_builder.replay import figures as F, moments as M
from demo.page_builder.replay.evening import Evening
from demo.page_builder.replay.story import Story
from demo.page_builder.replay.text import CLIP, paint_row

CARD_KINDS = {"aggpart", "buyers", "market", "node", "model", "chain", "device", "people", "ret", "desk"}
COLS = re.compile(r"^(repeat\([1-8],minmax\(0,1fr\)\)|\d(\.\d{1,2})?fr( \d(\.\d{1,2})?fr){0,7})$")          # the page's own rule
EVENINGS = ("evening_2025-01-28", "whole_evening_2025-01-28")
RECORDER_KEYS = ("sim_time", "stage", "layer", "from", "to", "node", "title", "plain", "terminal", "values")
# The card each beat gives (the design's table of beats), for the beats a recording has
KIND = {"orders": "buyers", "ask": "market", "call": "market", "home-safe": "node", "home-model": "node", "bld-offer": "node",
        "offers-in": "market", "book": "market", "buyer-contract": "market", "node-contract": "market", "frozen": "buyers",
        "battery-ask": "market", "ask-refused": "market", "site-ask": "aggpart", "site-answer": "aggpart", "told": "people",
        "watch-home": "chain", "watch-bld": "chain", "window": "device", "community-report": "desk", "site-report": "aggpart",
        "exc-model": "node", "exc-code": "chain", "report": "model", "desk": "desk", "readings": "ret", "settle": "ret", "pay": "ret"}


@lru_cache(maxsize=None)
def recorded(name: str) -> tuple[Evening, Story, list[tuple[dict, list[dict]]]]:
    """A recorded evening, its story, and every moment as the builder makes it with its steps' records before line_row."""
    ev = Evening(recordings.load(recordings.evenings(recordings.ROOT / name)[0]))
    st, bidx = Story(ev), ev.map.index
    recs = []
    for s in st.steps:
        ls = st.lines(s)
        own = sorted({b for x in ls for b in x["b"]}, key=bidx.get) or M.block_of(s)
        recs.append({"n": str(s.get("title") or ""), "m": 0, "wn": N.fixed_name(s.get("node")), "sd": M.side(s),
                     "b": [bidx[b] for b in own], "_l": ls})
    rec_of = {id(s): i for i, s in enumerate(st.steps)}
    st.tv_prev = {k: v for k, v in F.trade_all(ev, st.seen).items() if v}
    made = [st.moment(mi, mo, [st.steps[i] for i in idx], recs, rec_of) for mi, (mo, idx) in enumerate(zip(st.table, st.groups))]
    return ev, st, [(m, [recs[i] for i in m["s"]]) for m in made]


def drawn(ps: list[list[str]]) -> str:
    """Pieces as the page draws them, through the builder's own paint snippets: a span only for a class."""
    esc = lambda t: html.escape(t, quote=False)  # noqa: E731
    return "".join(str(T.render(f"replay/paint.html#{c}", text=T.Markup(esc(t)))) if c else esc(t) for c, t in ps)


def text_of(ps: list[list[str]]) -> str:
    return "".join(t for _, t in ps)


def a_line(text: str, kind: str = "calc", key: int = 0, box: str = "h-agent") -> dict[str, Any]:
    return {"k": kind, "cl": "", "text": text, "b": [box], "key": key}


def a_rec(lines: list[dict[str, Any]]) -> dict[str, Any]:
    return {"n": "Guard: set_battery done", "m": 0, "wn": "Home 71", "sd": "h", "b": [19], "_l": lines}


def a_moment(**more: Any) -> dict[str, Any]:
    """A moment in the builder's form (Story.moment), small."""
    k = {"kind": "node", "cb": "h-agent", "l": 4, "who": [["Home 71", ""], ["", "code"]], "in": [], "out": [], "did": "Code offers.",
         "rule": "", "cd": [], "cols": "1fr 1fr 1fr", "term": ["Home 71", "home_agent: every step as recorded"], "rev": None,
         "gap": None, "big": None, **more.pop("k", {})}
    return {"id": "home-model", "n": "Code makes the home's offer", "b": "h-agent", "bn": "Home agent", "w": "Home 71", "wn": "Home 71",
            "t": "Mon 10:00", "y": "Code offers.", "hero": None, "nt": "", "tag": None, "gap": None, "p": ["h-agent", "town"], "c": "offer",
            "lit": ["town", "h-agent"], "s": [0], "tr": [], "tv": {}, "ms": 8000, "k": k, **more}


# ------------------------------------------------------------------------------------------------ pieces
@pytest.mark.parametrize("name", EVENINGS)
def test_pieces_draw_what_paint_row_paints_on_every_recorded_line(name: str):
    _, st, _ = recorded(name)
    lines = [x for s in st.steps for x in st.lines(s)]
    assert len(lines) > 1500
    seen = set()
    for x in lines:
        ps = wire.pieces(x["text"], x["k"])
        assert drawn(ps) == str(paint_row(x["text"], x["k"])), x["text"][:80]
        seen |= {c for c, _ in ps}
        if len(x["text"]) > CLIP:                                   # the cut form a long key line is sent with
            cut = x["text"][:CLIP].rsplit(" ", 1)[0]
            more = len(x["text"]) - len(cut)
            assert drawn(wire.pieces(cut, "", more)) == str(paint_row(cut, "", more))
    assert seen == set(wire.PIECE_CLASSES)                          # the evening uses every class, and no other


def test_innermost_span_wins_and_no_markup_is_left():
    answer = 'answer: set_owner_wish({"wish": "keep_battery_full", "for": "home-04"})'
    ps = wire.pieces(answer, "think")
    assert ps == [["q", 'answer: set_owner_wish({"wish": "keep_battery_full", "for": "'], ["h", "Home 71"], ["q", '"})']]
    painted = str(paint_row(answer, "think"))
    assert painted.count("<span") == 2 and text_of(ps) == html.unescape(re.sub(r"<[^>]+>", "", painted))
    hostile = 'note: <img src=x onerror="a=1"> & </span><script>x</script> building-01 pays $3.50'
    ps = wire.pieces(hostile, "in")
    assert ps == [["", 'note: <img src=x onerror="a=1"> & </span><script>x</script> '], ["b", "the shopping center"], ["", " pays "],
                  ["n", "$3.50"]]
    assert wire.pieces("guard.py:120  if a < b:   # step 3 range -> no", "guard") == \
        [["d", "guard.py:120"], ["", "  if a < b:   "], ["w", "# step 3 range"], ["", " "], ["d", "-> no"]]
    assert wire.pieces("", "note") == [] and wire.line(a_line(""))[2] == []


def test_a_class_or_a_box_the_page_does_not_know_never_leaves(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(wire, "PIECE_CLASSES", ("", "n"))               # as if the painter had a class the page's list lacks
    assert wire.pieces("home-04 offers 3.5 kW", "in") == [["", "Home 71"], ["", " offers "], ["n", "3.5 kW"]]
    rec, st, _ = recorded(EVENINGS[0])
    asked = next(s for s in as_live(st) if s["beat"] == "site-ask")     # a single site's step, on an evening whose map draws no site
    live = LiveStory(LiveEvening({"day": rec.meta["day"], "homes": 8, "buildings": 2, "sites": 0, "half_hours": ["18:00"]}))
    live.take([asked], asked["tq"])
    (steps, m), = live.close(asked["tq"], "held")
    assert "site-pv" not in live.ev.map.ids and (m["id"], m["b"], m["lit"], steps[0]["b"]) == ("other", "town", ["town"], [])
    assert len(steps[0]["l"]) == 8 and all(l[3] == [] for l in steps[0]["l"]) and live.faults["cards"] == 1


def test_a_line_is_the_builders_row_in_pieces():
    assert wire.line(a_line("home-04 offers 3.5 kW", "in", 2)) == ["in", "", [["h", "Home 71"], ["", " offers "], ["n", "3.5 kW"]], ["h-agent"], 2]
    assert len(wire.line(a_line("x " * 200, key=0))) == 5                    # only a key line carries its cut form
    long = "answer: file_report(" + "the home kept its battery full for the evening as its owner asked, " * 5 + "and gave 3.5 kW)"
    row = wire.line(a_line(long, "think", key=1))
    cut = long[:CLIP].rsplit(" ", 1)[0]
    assert len(row) == 6 and row[2] == [["q", long]] and drawn(row[2]) == str(paint_row(long, "think"))
    assert row[5] == [["", cut + " "], ["d", f"… {len(long) - len(cut)} more characters"]]          # cut, it is painted as plain words,
    assert drawn(row[5]) == str(paint_row(cut, "", more=len(long) - len(cut)))                   # as the builder's line_row does
    odd = wire.line({"k": "shout", "cl": "blink", "text": "x", "b": ["town", "h-agent"]})
    assert odd == ["note", "", [["", "x"]], ["town", "h-agent"], 0]                      # a kind or class the page does not take
    assert wire.line({"k": "guard", "cl": "no", "text": "guard says blocked", "b": ["h-guard"]})[:2] == ["guard", "no"]


# ------------------------------------------------------------------------------------------------ cuts
def test_a_line_is_cut_at_600_before_it_is_painted():
    text = "a" * 554 + " 12.5 kW is the figure, and then " + "more words " * 200
    assert wire.pieces(text, "calc")[1] == ["n", "12.5 kW"]                     # painted whole, the figure is picked out
    ps = wire.line(a_line(text))[2]
    assert ps == [["", "a" * 554 + " 12.5 "], ["d", f"… {len(text) - 559:,} more characters"]]     # cut at a space, then painted
    assert wire.chars(ps) <= 600 and wire.chars(ps) > 570
    many = "readings: " + " ".join(f"home-04 gave {i}.5 kW," for i in range(150))
    ps = wire.line(a_line(many))[2]                                             # too long and too many pieces at once
    assert wire.chars(ps) <= 600 and len(ps) == 24 and re.search(r" … [\d,]+ more characters$", ps[-1][1]) and ps[-1][0] == ""
    grows = " ".join(["building-01"] * 49)                                      # 587 characters; each id is named in 19
    assert len(grows) <= 600 and wire.chars(wire.pieces(grows, "note")) > 900
    ps = wire.line(a_line(grows, "note"))[2]
    assert wire.chars(ps) <= 600 and ps[-1][1].endswith("more characters") and ps[0] == ["b", "The shopping center"]
    exact = "x" * 600
    assert wire.line(a_line(exact))[2] == [["", exact]] and wire.chars(wire.line(a_line(exact + "x"))[2]) < 600


def test_a_line_over_24_pieces_keeps_23_and_joins_the_rest():
    text = ", ".join(f"{i} kW" for i in range(40))
    whole = wire.pieces(text, "calc")
    assert len(whole) == 79
    ps = wire.line(a_line(text))[2]
    assert len(ps) == 24 and ps[:23] == whole[:23]
    assert ps[23] == ["", text_of(whole[23:])] and text_of(ps) == text
    assert len(wire.line(a_line(", ".join(f"{i} kW" for i in range(12))))[2]) == 23       # under the cap: as painted


def test_a_step_over_40_lines_keeps_its_key_lines_and_its_last():
    lines = [a_line(f"guard.py:{i}  check {i}", "guard", box="h-guard") for i in range(60)]
    for i, key in ((0, 1), (29, 2), (30, 1), (31, 3)):
        lines[i]["key"] = key
    lines[59] = a_line("guard says done: applied {}, expected 3.2 kW", "out", box="h-guard")
    ids = recorded(EVENINGS[0])[0].map.ids
    step = wire.step(a_rec(lines), 129, ids)
    ls = step["l"]
    assert step == {"tq": 129, "n": "Guard: set_battery done", "w": "Home 71", "sd": "h", "b": ["h-guard"], "l": ls} and len(ls) == 40
    assert wire.step({**a_rec(lines[:2]), "b": [15, 16, len(ids)]}, 1, ids)["b"] == ["town", "h-agent"]         # the page's "input" is no box
    texts = [text_of(l[2]) for l in ls]
    assert [t for t in texts if "check 0" == t[-7:] or t.endswith(("check 29", "check 30"))] == \
        ["guard.py:0  check 0", "guard.py:29  check 29", "guard.py:30  check 30"]
    assert texts[-1].startswith("guard says done") and [l[4] for l in ls].count(2) == 1
    notes = [(i, l) for i, l in enumerate(ls) if l[0] == "note"]
    assert len(notes) == 1 and notes[0][1] == ["note", "", [["d", "… 21 more lines"]], ["h-guard"], 0]
    at = notes[0][0]
    assert texts[:at] == [f"guard.py:{i}  check {i}" for i in range(at)] and 15 < at < 25      # the others went from the middle
    assert "guard.py:31  check 31" not in texts                                                 # key 3 is not kept for its key
    assert len(wire.step(a_rec(lines[:40]), 1, ids)["l"]) == 40 and not any(l[0] == "note" for l in wire.step(a_rec(lines[:40]), 1, ids)["l"])
    crowded = [a_line(f"line {i}", key=1) for i in range(50)]
    ls = wire.step(a_rec(crowded), 1, ids)["l"]                                                 # more key lines than a step holds
    assert len(ls) == 40 and text_of(ls[-1][2]) == "line 49" and text_of(ls[0][2]) == "line 0" and ls[38][2] == [["d", "… 11 more lines"]]


def big_steps(marks: list[int], n_steps: int, width: int = 590) -> list[dict[str, Any]]:
    """Steps whose lines are `width` characters each and carry the key marks given; the last step holds one line more."""
    out = []
    for si in range(n_steps):
        keys = marks + ([0] if si == n_steps - 1 else [])
        ls = [wire.line(a_line(f"step {si} line {i:02d} " + "x" * (width - 16), key=k)) for i, k in enumerate(keys)]
        out.append({"tq": 1, "n": f"Step {si}", "w": "", "sd": "h", "b": ["h-agent"], "l": ls})
    return out


def marks_left(steps: list[dict[str, Any]]) -> list[list[int]]:
    return [sorted({l[4] for l in s["l"] if l[0] != "note"}) for s in steps]


def test_a_moment_over_60000_drops_key_0_from_the_longest_step_first():
    m = wire.moment(a_moment(), 1)
    steps = big_steps([2, 1, 3] + [0] * 36, 3)
    assert wire.size(steps) + wire.size(m) > 70_000
    wire.fit(steps, m)
    assert wire.size(steps) + wire.size(m) <= wire.MOMENT_CHARS - wire.LOG_ROOM
    assert marks_left(steps) == [[0, 1, 2, 3], [0, 1, 2, 3], [1, 2, 3]]                 # only the longest step lost its key 0
    assert [l for l in steps[2]["l"] if l[0] == "note"] == [["note", "", [["d", "… 37 more lines"]], ["h-agent"], 0]]
    assert [len(s["l"]) for s in steps] == [39, 39, 4]
    small = big_steps([2, 1, 3, 0], 2)
    before = json.dumps(small)
    wire.fit(small, m)
    assert json.dumps(small) == before                                                  # under the cap nothing is touched
    width = next(w for w in range(300, 600) if 59_400 < wire.size(big_steps([2] + [0] * 31, 3, w)) + wire.size(m) <= 60_000)
    tight = big_steps([2] + [0] * 31, 3, width)                         # inside 60,000, but with no room for the log's numbers
    wire.fit(tight, m)
    assert marks_left(tight) == [[0, 2], [0, 2], [2]] and wire.size(tight) + wire.size(m) <= 59_400


def test_then_key_3_then_key_1_and_never_key_2():
    m = wire.moment(a_moment(), 1)
    steps = big_steps([2] + [1] * 19 + [3] * 19 + [0], 4)
    wire.fit(steps, m)
    assert marks_left(steps) == [[1, 2]] * 4 and wire.size(steps) + wire.size(m) <= 59_400      # every key 0, then every key 3
    assert [text_of(s["l"][-1][2]) for s in steps] == ["… 20 more lines", "… 20 more lines", "… 20 more lines", "… 21 more lines"]
    steps = big_steps([2] + [1] * 27 + [3] * 11 + [0], 4)
    wire.fit(steps, m)
    left = marks_left(steps)
    assert left.count([2]) == 1 and left.count([1, 2]) == 3 and wire.size(steps) + wire.size(m) <= 59_400
    assert all([l[4] for l in s["l"]].count(2) == 1 for s in steps)
    assert sorted(len(s["l"]) for s in steps) == [2, 29, 29, 29]                        # one note line a step, never two
    stars = big_steps([2] * 5, 24)                                      # more than a moment may hold, all of it lines that matter
    wire.fit(stars, m)
    assert marks_left(stars) == [[2]] * 24 and sum(len(s["l"]) for s in stars) == 121 and wire.size(stars) > 60_000      # they all stay


def test_a_long_step_cut_twice_says_so_once():
    ids = recorded(EVENINGS[0])[0].map.ids
    lines = [a_line(f"line {i:02d} " + "x" * 580, key=1 if i < 3 else 0) for i in range(50)]
    steps = [wire.step(a_rec(lines), 1, ids), wire.step(a_rec(lines[:30]), 1, ids), wire.step(a_rec(lines[:30]), 1, ids)]
    assert text_of(steps[0]["l"][20][2]) == "… 11 more lines" and len(steps[0]["l"]) == 40
    wire.fit(steps, wire.moment(a_moment(), 1))
    assert [(text_of(l[2]), l[4]) for l in steps[0]["l"][3:]] == [("… 47 more lines", 0)] and len(steps[0]["l"]) == 4


# ------------------------------------------------------------------------------------------------ a moment
def test_a_moment_is_the_builders_without_what_the_page_fills():
    m = wire.moment(a_moment(), 129)
    assert list(m) == ["tq", "id", "n", "b", "w", "hero", "tag", "p", "c", "lit", "tv", "k"]
    assert list(m["k"]) == ["kind", "cb", "l", "who", "in", "out", "did", "rule", "cd", "cols", "term", "big"]
    assert (m["tq"], m["hero"], m["tag"], m["tv"], m["k"]["big"]) == (129, None, None, 0, [])
    m = wire.moment(a_moment(hero=["3.5 kW", "offered"], tag=["Surprise", "Owner's note"], tv={"sold": "9 kW"}, wn="the office",
                             k={"big": ["3.5 kW", "offered"]}), 1)
    assert (m["w"], m["hero"], m["tag"], m["tv"], m["k"]["big"]) == ("the office", ["3.5 kW", "offered"], ["Surprise", "Owner's note"], 1, ["3.5 kW", "offered"])


def test_a_moment_is_cut_to_its_caps():
    long = "word " * 200
    cards = [{"h": f"Card {i} " + long, "rows": [[f"label {j} " + long, long, j == 0] for j in range(12)], "hot": 1} for i in range(10)]
    cards[0].update({"q": long, "says": [[long, long]] * 12, "six": [[i, long, "ok"] for i in range(1, 7)],
                     "tbl": [["kW"] + [f"{18 + h // 2}:{'30' if h % 2 else '00'}" for h in range(12)]] + [[f"row {r}"] + [None, long] * 6 for r in range(9)]})
    m = wire.moment(a_moment(n=long, p=["town", "h-agent"] * 6, lit=["town"] * 50, c=long, hero=[long, long],
                             k={"cd": cards, "cols": "repeat(4,minmax(0,1fr))", "did": long, "rule": long, "who": [[long, ""]] * 6,
                                "in": [long, long, "3"], "big": [long, long]}), 1)
    k = m["k"]
    assert len(m["n"]) <= 90 and len(m["p"]) == 8 and len(m["lit"]) == 40 and len(m["c"]) <= 60
    assert all(len(x) <= 220 for x in m["hero"] + k["big"]) and len(k["did"]) <= 400 and len(k["rule"]) <= 400
    assert len(k["who"]) == 4 and all(len(x) <= 90 for x in k["in"] + [r[0] for r in k["who"]]) and k["in"][2] == "3"
    assert len(k["cd"]) == 8 and all(len(c["rows"]) == 8 and len(c["h"]) <= 60 for c in k["cd"])
    assert all(len(a) <= 60 and len(b) <= 60 and mk in (0, 1) for c in k["cd"] for a, b, mk in c["rows"])
    first = k["cd"][0]
    assert len(first["q"]) <= 220 and len(first["says"]) == 8 and first["rows"][0][2] == 1 and first["hot"] == 1
    assert len(first["tbl"]) == 6 and all(len(r) == 9 for r in first["tbl"])
    assert first["tbl"][0] == ["kW", "20:00", "20:30", "21:00", "21:30", "22:00", "22:30", "23:00", "23:30"]     # the newest columns
    assert first["tbl"][1][0] == "row 0" and first["tbl"][1][1] is None and len(first["tbl"][1][2]) <= 60
    assert m["k"]["cols"] == "repeat(4,minmax(0,1fr))"
    assert wire.moment(a_moment(k={"cd": cards[:1], "cols": "1fr 1.72fr 1.1fr"}), 1)["k"]["cols"] == "1fr"        # the columns of the cards left
    assert wire.cap("One sentence. " * 20, 60) == "One sentence. One sentence. One sentence. One sentence."
    assert wire.cap("x" * 90, 90) == "x" * 90 and len(wire.cap("x" * 91, 90)) <= 90


# ------------------------------------------------------------------------------------------------ the fixed lists
def test_the_caps_are_the_feed_contracts():
    assert (wire.LINE_CHARS, wire.PIECES, wire.LINES, wire.MOMENT_CHARS, wire.STEPS, wire.HOPS, wire.LIT) == (600, 24, 40, 60_000, 24, 8, 40)
    assert (wire.CARDS, wire.ROWS, wire.TBL_ROWS, wire.TBL_COLS, wire.CELL, wire.BUBBLE, wire.DID, wire.TITLE) == (8, 8, 6, 9, 60, 220, 400, 90)
    assert wire.KINDS == ("in", "out", "think", "calc", "sign", "tool", "guard", "write", "note") and wire.LINE_CLASSES == ("", "no", "tbl")
    assert wire.PIECE_CLASSES == ("", "n", "d", "w", "q", "h", "b") and wire.CARD_KEYS == ("h", "hot", "q", "rows", "six", "nine", "tbl", "says")


def inside(ev: Evening, steps: list[dict[str, Any]], wm: dict[str, Any]) -> None:
    """What the page refuses (4.1, 4.2 and the shapes of 6.3), held against one moment with its steps."""
    two = lambda x: isinstance(x, list) and len(x) == 2 and all(isinstance(y, str) for y in x)  # noqa: E731
    assert wire.size(steps) + wire.size(wm) <= 60_000 - wire.LOG_ROOM and 0 < len(steps) <= 24
    for s in steps:
        assert list(s) == ["tq", "n", "w", "sd", "b", "l"] and s["sd"] in "hb" and len(s["l"]) <= 40 and len(s["n"]) <= 90
        assert set(s["b"]) <= set(ev.map.ids)
        for l in s["l"]:
            assert l[0] in wire.KINDS and l[1] in wire.LINE_CLASSES and l[4] in (0, 1, 2, 3) and set(l[3]) <= set(ev.map.ids)
            for ps in [l[2]] + l[5:]:
                assert 0 < len(ps) <= 24 and wire.chars(ps) <= 600 and all(c in wire.PIECE_CLASSES and isinstance(t, str) for c, t in ps)
    k = wm["k"]
    assert list(wm) == ["tq", "id", "n", "b", "w", "hero", "tag", "p", "c", "lit", "tv", "k"] and "rev" not in k and "gap" not in k
    assert k["kind"] in CARD_KINDS and k["cb"] in ev.map.ids and 1 <= k["l"] <= 8 and COLS.match(k["cols"]), wm["id"]
    assert wm["b"] in ev.map.ids and set(wm["p"]) | set(wm["lit"]) <= set(ev.map.ids) and wm["tv"] in (0, 1)
    assert all(hop in ev.map.edge_set for hop in zip(wm["p"], wm["p"][1:])) and len(wm["p"]) <= 8 and len(wm["lit"]) <= 40
    assert (wm["hero"] is None or two(wm["hero"])) and (wm["tag"] is None or two(wm["tag"])) and (k["big"] == [] or two(k["big"])) and two(k["term"])
    assert len(k["who"]) <= 4 and all(two(r) for r in k["who"]) and len(k["cd"]) <= 8
    assert all(x == [] or (len(x) == 3 and all(isinstance(y, str) for y in x)) for x in (k["in"], k["out"]))
    for c in k["cd"]:
        assert set(c) <= set(wire.CARD_KEYS) and len(c.get("rows", [])) <= 8
        assert all(len(r) == 3 and isinstance(r[0], str) and isinstance(r[1], str) and r[2] in (0, 1) for r in c.get("rows", []))
        assert all(isinstance(r[0], int) for r in c.get("six", []) + c.get("nine", []))
        assert len(c.get("tbl", [])) <= 6 and all(len(r) <= 9 for r in c.get("tbl", []))


@pytest.mark.parametrize("name", EVENINGS)
def test_every_recorded_moment_is_inside_the_fixed_lists_and_the_caps(name: str):
    ev, _, moments = recorded(name)
    for m, recs in moments:
        steps = [wire.step(r, 1, ev.map.ids) for r in recs[:wire.STEPS]]
        wm = wire.moment(m, 1)
        wire.fit(steps, wm)
        inside(ev, steps, wm)


def as_live(st: Story) -> list[dict[str, Any]]:
    """The recorded evening's steps as live ones: each with its recorded moment as its beat, key and say by that moment's own
    rules, and its quarter-hour. What a live evening does not shape (bare step rows, the day's totals, the aggregator's own
    parts) is left out; the book's side moments are steps of the book, and every word with the desk is the desk's."""
    out = []
    for mo, idx in zip(st.table, st.groups):
        for i in idx:
            s, title = st.steps[i], str(st.steps[i]["title"])
            desk, book = bool(re.search(r"the desk|takes a dispatch", title)), mo.id in ("reserve", "cover", "limit", "split")
            beat = "desk" if desk else "book" if book else mo.id
            if beat not in KIND or re.fullmatch(r"Step \d \w+", title) or title.endswith("in totals"):
                continue
            when = dt.datetime.fromisoformat(s["sim_time"]) - dt.datetime(2025, 1, 27, 9, 45)
            key = bool(re.search(r"tells the desk|^The desk", title)) if desk else not book and bool(re.search(mo.key, title, re.I))
            out.append({**{k: s.get(k) or ({} if k == "values" else "") for k in RECORDER_KEYS}, "beat": beat, "key": key, "wall": 0.0, "at": i,
                        "say": not desk and not book and bool(re.search(mo.say, title, re.I)), "tq": int(when.total_seconds() // 900) + 2 * (beat == "window")})
    return sorted(out, key=lambda s: (s["tq"], s.pop("at")))


def test_the_recorded_evening_told_live_gives_each_beat_its_card():
    rec, st, _ = recorded(EVENINGS[0])
    ev = LiveEvening({"day": rec.meta["day"], "homes": 8, "buildings": 2, "sites": 3, "model": rec.meta["model"],
                      "follow": {k: v["node"] for k, v in rec.cast["follow"].items()}, "half_hours": [h["start"] for h in rec.ledger["half_hours"]]})
    ev.totals(deposits={"utility": 51.83, "grid-operator": 31.1}, sold_kwh=294.1, delivered_kwh=293.9)
    steps, live, given = as_live(st), LiveStory(ev), []
    for tq in sorted({s["tq"] for s in steps}):
        live.take([s for s in steps if s["tq"] == tq], tq)
        given += live.close(tq, "held")
    assert live.faults == {"orphans": 10, "cards": 0, "ahead": 0} and sum(len(ws) for ws, _ in given) == len(steps) - 10 == 208
    for ws, m in given:
        inside(ev, ws, m)
        assert m["k"]["kind"] == KIND[m["id"]] and all(s["tq"] == m["tq"] for s in ws), m["id"]
    told = [m["id"] for _, m in given]
    assert {i: told.count(i) for i in KIND} == {**{i: 1 for i in KIND}, "desk": 6, "window": 6, "community-report": 6, "exc-model": 12,
                                                "exc-code": 2, "told": 3, "report": 3, "watch-home": 2}
    hero = {(m["id"], m["w"]): m["hero"] for _, m in given}
    assert hero[("bld-offer", "the shopping center")] == ["9 kW", "offered by the shopping center"]
    assert hero[("watch-bld", "the shopping center")] == ["5", "device calls at the shopping center"]
    assert hero[("watch-home", "Home 90")] == ["5", "device calls at this home"] and hero[("node-contract", "")] == ["10", "contracts, one per node"]
    assert hero[("book", "")] == ["100 kW", "sold in the fullest half hour, firm power first"]
    assert hero[("buyer-contract", "")] == ["100 kW", "in the fullest half hour, at $2.04 per kWh"]
    assert hero[("settle", "")] == ["$497.07", "buyers pay for 294 kWh on the meters"] and hero[("told", "Home 71")][1] == "what the node told its person"
    assert [m["hero"][1][-14:] for _, m in given if m["id"] == "window"][::5] == ["18:00 to 18:30", "20:30 to 21:00"]
    assert [len(m["k"]["cd"][0]["tbl"][0]) for _, m in given if m["id"] == "window"] == [2, 3, 4, 5, 6, 7]         # the evening so far
