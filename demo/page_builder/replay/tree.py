"""The whole picture's geometry: every box of the tree placed in pixels at 100%, so nothing in the tree can move once the page
has loaded. A box is as tall as its words or its terminal, whichever runs longer, and as wide as its terminal's columns.

The rows, top to bottom: the input; the aggregator's row (its reading cleaner, sharing-out, request agent and referee, with the
utility at the right) over the two buyers, with Where it stands on their left and the trade on their right; the community
agent's six boxes; NANDA Town across the tree; the home and building branches, box by box; the return path. The single sites
stand in a row of their own at the foot. Each level's name sits at the left, in the gap over its first row.
"""
from __future__ import annotations

import html
import math
import re
from typing import Any

from . import status
from .notes import notes_for
from .text import wrapped

COL, TGAP, ROW, ABOUT_W, PAD, HEAD, INPUT, VGAP = 860, 30, 18, 600, 30, 104, 92, 120
CPL = int((COL - TGAP - 34) / 7.8)
HOME_COLS, BLD_COLS, TARGET_ROWS = 3, 6, 46
GUTTER, RAIL = 420, 70
MARGIN = 2 * RAIL + 90
HOME = ["h-agent", "h-model", "h-tools", "h-guard", "h-seal", "h-driver", "h-dev", "h-person"]
BLD = ["b-agent", "b-model", "b-tools", "b-guard", "b-seal", "b-driver", "b-dev", "b-person"]
LEVELS = (("top", "The aggregator and the utility"), ("co", "Community agent"), ("nodes", "Home agents"), ("base", "People and devices"))


def plain_of(h: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", h))


def block_rows(story: dict[str, Any], bi: int) -> int:
    """How many terminal rows a box's own lines take, a moment's heading and a step's heading included."""
    rows = 0
    for m in story["moments"]:
        head = False
        for si in m["s"]:
            own = [x for x in story["steps"][si]["l"] if (bi in x[3] if isinstance(x[3], list) else bi == x[3])]
            if own:
                if not head:
                    rows += 2
                    head = True
                rows += 1 + sum(wrapped(plain_of(x[2]), CPL) for x in own)
    return rows


def about_h(ev: Any, b: str) -> int:
    """How tall a box's words run, at the world's sizes: its paragraph, its list, and its notes on what changed and what it lacks."""
    cpl = 62
    h = 20 + math.ceil(len(ev.map.about.get(b, "")) / cpl) * 30
    if b in ("h-agent", "b-agent"):
        h += 3 * 58 + 24
    if b in ("h-guard", "b-guard"):
        h += 6 * 40 + 24
    if b in ("h-person", "b-person"):
        h += 6 * 60 + 90
    revs, gaps = notes_for(ev, b)
    for _, _, was, now in revs:
        h += 56 + math.ceil((len(was) + 5) / cpl) * 28 + math.ceil((len(now) + 5) / cpl) * 28
    for _, a in gaps:
        h += 56 + math.ceil(len(a) / cpl) * 28
    return h


def layout(ev: Any, d: dict[str, Any], min_w: int = 0) -> dict[str, Any]:
    """The tree's geometry. min_w: a set of evenings asks for one width for all, so a short evening's tree still holds the
    community agent's row."""
    story = d["stories"]["main"]
    ids = ev.map.ids
    rows = {b: block_rows(story, i) for i, b in enumerate(ids)}
    rows["input"] = block_rows(story, len(ids))
    note_h = 32 + math.ceil(len(f'{story.get("note") or ""} {story.get("ends") or ""}'.strip()) / 62) * 30
    out: dict[str, list[int]] = {}

    def size(b: str, cols: int) -> tuple[int, int, int]:
        term = (math.ceil(rows[b] / cols * 1.05) + 2) * ROW + 24
        return PAD * 2 + ABOUT_W + TGAP + cols * COL, HEAD + INPUT + max(note_h if b == "input" else about_h(ev, b), term) + PAD * 2, term

    def cols_for(b: str, most: int) -> int:
        return max(1, min(most, math.ceil(rows[b] / TARGET_ROWS)))

    wide_h = max(size(b, cols_for(b, HOME_COLS))[0] for b in HOME)
    wide_b = max(size(b, cols_for(b, BLD_COLS))[0] for b in BLD)
    gutter = max(GUTTER, min_w - MARGIN * 2 - wide_h - wide_b)
    W = MARGIN * 2 + wide_h + gutter + wide_b
    hx, bx = MARGIN + wide_h / 2, MARGIN + wide_h + gutter + wide_b / 2
    y = 60
    w, h, t = size("input", 1)
    out["input"] = [int(W / 2 - w / 2), y, w, h, 1, t]
    y2 = y + h + VGAP
    bw = [size(b, 1) for b in ("buy-u", "buy-g")]
    x = W / 2 - (bw[0][0] + bw[1][0] + 60) / 2
    out["buy-u"] = [int(x), y2, bw[0][0], bw[0][1], 1, bw[0][2]]
    out["buy-g"] = [int(x + bw[0][0] + 60), y2, bw[1][0], bw[1][1], 1, bw[1][2]]
    side_h = y2 + max(bw[0][1], bw[1][1]) - y
    left_edge, right_edge = int(x) - 150, int(x + bw[0][0] + 60 + bw[1][0]) + 150
    stat_h = max(min(side_h, 1360), status.height(ev, left_edge - MARGIN))      # Where it stands shows every word of its statement
    out["status"] = [MARGIN, y, left_edge - MARGIN, stat_h, 0, 0]
    out["trade"] = [right_edge, y, W - MARGIN - right_edge, min(side_h, 1360), 0, 0]
    y = co_y = max(y2 + max(bw[0][1], bw[1][1]), y + stat_h) + VGAP
    cs = {"co-fc": 1, "co-agent": 1, "co-market": 2, "co-desk": 2}
    sz = [size(b, n) for b, n in cs.items()]
    x = W / 2 - (sum(s[0] for s in sz) + 60 * 3) / 2
    for (b, n), s in zip(cs.items(), sz):
        out[b] = [int(x), y, s[0], s[1], n, s[2]]
        x += s[0] + 60
    y += max(s[1] for s in sz) + VGAP
    tc = max(1, int((W - 2 * MARGIN - 2 * PAD - ABOUT_W - TGAP) / COL))           # Town spans the tree, and the branches hang from it
    w, h, t = size("town", tc)
    out["town"] = [int(W / 2 - w / 2), y, w, h, tc, t]
    y += h + VGAP
    for hb, bb in zip(HOME, BLD):
        ch, cb = cols_for(hb, HOME_COLS), cols_for(bb, BLD_COLS)
        (wh, h1, t1), (wb, h2, t2) = size(hb, ch), size(bb, cb)
        out[hb] = [int(hx - wh / 2), y, wh, h1, ch, t1]
        out[bb] = [int(bx - wb / 2), y, wb, h2, cb, t2]
        y += max(h1, h2) + VGAP
    rc = {"r-read": 2, "r-check": 1, "r-settle": 2, "r-pay": 2}
    sz = [size(b, n) for b, n in rc.items()]
    x, y = W / 2 - (sum(s[0] for s in sz) + 60 * 3) / 2, y + 40
    for (b, n), s in zip(rc.items(), sz):
        out[b] = [int(x), y, s[0], s[1], n, s[2]]
        x += s[0] + 60
    H = y + max(s[1] for s in sz) + 80
    rest = [b for b in ids if b not in out and b not in ("mkt", "utl")]          # the aggregator's parts, the six, the single sites
    sz = [size(b, 1) for b in rest]
    x = W / 2 - (sum(s[0] for s in sz) + 60 * (len(sz) - 1)) / 2
    for b, s in zip(rest, sz):
        out[b] = [int(x), H, s[0], s[1], 1, s[2]]
        x += s[0] + 60
    H += max(s[1] for s in sz) + 80
    geo = {"railL": MARGIN - 90, "railR": W - MARGIN + 90, "skipH": hx + wide_h / 2 + 60, "skipB": bx - wide_b / 2 - 60,
           "sensH": hx - wide_h / 2 - 60, "sensB": bx + wide_b / 2 + 60, "persH": hx - wide_h / 2 - 130, "persB": bx + wide_b / 2 + 130,
           "retX": hx + wide_h / 2 + GUTTER / 2, "retY": y - 70, "railY": co_y - 60}
    T = {"W": int(W), "H": int(H), "b": out, "geo": {k: int(v) for k, v in geo.items()}, "cols": {"col": COL, "gap": TGAP}}
    return levels(ev, story, T)


def levels(ev: Any, story: dict[str, Any], T: dict[str, Any]) -> dict[str, Any]:
    """The aggregator's row and the community agent's six boxes put in their places, and each level's name at its left."""
    b, W, geo = T["b"], T["W"], T["geo"]

    def size(x: str) -> tuple[int, int, int]:
        term = (math.ceil(block_rows(story, ev.map.index[x]) * 1.05) + 2) * ROW + 24
        return PAD * 2 + ABOUT_W + TGAP + COL, HEAD + INPUT + max(about_h(ev, x), term) + PAD * 2, term

    def shift(test: Any, by: int) -> None:
        for k in ("retY", "railY"):
            if test(geo[k]):
                geo[k] += by

    inp, old_co = b["input"], b["co-fc"][1]
    y1 = inp[1] + inp[3] + VGAP
    sz = {x: size(x) for x in ("mkt", "utl")}
    w, h, t = sz["mkt"]
    b["mkt"] = [int(W / 2 - w / 2), y1, w, h, 1, t]
    w, h, t = sz["utl"]
    b["utl"] = [int(W - MARGIN - w), y1, w, h, 1, t]
    y2 = y1 + max(h for _, h, _ in sz.values()) + VGAP
    for x in ("buy-u", "buy-g", "status", "trade"):
        b[x][1] = y2
    b["trade"][2] -= 120                                   # the lane the utility's limit runs down, right of the trade
    d = y2 + max(b[x][3] for x in ("buy-u", "buy-g", "status", "trade")) + VGAP - old_co
    for x, g in b.items():
        if x not in ("input", "mkt", "utl", "buy-u", "buy-g", "status", "trade") and g[1] >= old_co:
            g[1] += d
    T["H"] += d
    shift(lambda v: True, d)
    geo["limX"] = int(W - MARGIN - 60)
    geo["lv"] = 1                                          # the utility stands on the right, so both buyers' orders run down the left rail
    six, parts = ("co-cover", "co-report"), ("agg-clean", "agg-share", "agg-ref")
    order = ["co-fc", "co-cover", "co-agent", "co-market", "co-desk", "co-report"]
    for x in six:
        w_, h_, t_ = size(x)
        b[x] = [0, b["co-fc"][1], w_, h_, 1, t_]
    old_h = max(b[x][3] for x in order if x not in six)
    gap6 = 60
    total = sum(b[x][2] for x in order) + gap6 * (len(order) - 1)
    for x in ("co-market", "co-desk"):                     # six in a row are wider than the tree: these two take one column, and stand taller
        if total > W - 2 * MARGIN and b[x][4] > 1:
            w_, h_, t_ = size(x)
            b[x] = [0, b[x][1], w_, h_, 1, t_]
            total = sum(b[y][2] for y in order) + gap6 * (len(order) - 1)
    if total > W - 2 * MARGIN:                             # still a little wide: the boxes stand closer
        gap6 = 44
        total = sum(b[y][2] for y in order) + gap6 * (len(order) - 1)
    x0 = W / 2 - total / 2
    for x in order:
        b[x][0] = int(x0)
        x0 += b[x][2] + gap6
    co = b["co-fc"][1]
    grow6 = max(0, max(b[x][3] for x in order) - old_h)
    for x, g in b.items():
        if x not in order and x not in parts and g[1] > co:
            g[1] += grow6
    shift(lambda v: v > co, grow6)
    T["H"] += grow6
    low = max(b[x][1] for x in parts)                      # the parts had a row of their own at the foot: that row is given back
    gone = max(size(x)[1] for x in parts + six) + 80
    mk, gap = b["mkt"], 140
    psz = {x: size(x) for x in parts}
    b["agg-share"] = [mk[0] - gap - psz["agg-share"][0], mk[1], psz["agg-share"][0], psz["agg-share"][1], 1, psz["agg-share"][2]]
    b["agg-clean"] = [b["agg-share"][0] - gap - psz["agg-clean"][0], mk[1], psz["agg-clean"][0], psz["agg-clean"][1], 1, psz["agg-clean"][2]]
    b["agg-ref"] = [mk[0] + mk[2] + gap, mk[1], psz["agg-ref"][0], psz["agg-ref"][1], 1, psz["agg-ref"][2]]
    grow = max(0, max(b[x][3] for x in parts) - mk[3])     # a part taller than the request agent's box pushes everything below it down
    for x, g in b.items():
        if x not in ("input", "mkt", "utl", *parts) and g[1] > mk[1]:
            g[1] += grow
    shift(lambda v: True, grow)
    T["H"] += grow - (gone if low >= T["H"] - gone - 5 else 0)
    tops = {"top": min(b["mkt"][1], b["utl"][1]), "co": b["co-fc"][1], "nodes": min(b["h-agent"][1], b["b-agent"][1]),
            "base": min(b["h-dev"][1], b["b-dev"][1])}
    T["lv"] = [[MARGIN, tops[key] - 92, name] for key, name in LEVELS]
    return T

