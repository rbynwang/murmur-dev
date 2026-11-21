"""One evening's story: its steps in order, which moment each belongs to, and each moment's terminal, path, figures and card.

A moment's default terminal shows the one or two lines that matter (its stars) and the key steps' telling lines around them, as
far as the panel holds at reading size; the split view's narrower terminal shows fewer, and a line it leaves out stays a key
line in the whole picture. Every line keeps the record's own words, with each node's id turned into its name.
"""
from __future__ import annotations

import re
from typing import Any

from .. import names as N
from . import cards as K
from . import figures as F
from . import moments as M
from .panels import answer_step, largest_short
from .text import CLIP, in_scope, paint_row, stamp, wrapped

Step = dict[str, Any]
KEY_ROWS, KEY_CPL = 13, 84         # the rows of terminal a moment's default view aims for, at this many characters a row
SPLIT_ROWS, SPLIT_CPL = 11, 68     # the split view's terminal holds fewer rows, at fewer characters a row
# The lines that matter most in a moment's terminal, best first. A moment marks one or two; the rest recedes
STAR = [r"^to the (?:owner|manager):", r"^answer:", r"^guard says", r"^nodes paid", r"^total \$", r"^readings are in", r"^devices\.",
        r"^SimulatedDriver", r"^place_order", r"^discover to", r"^confirm to", r"short:", r"says:", r"^in all", r"^[a-z-]+: placed", r"^kW below"]


def star_rank(text: str) -> int:
    return next((i for i, p in enumerate(STAR) if re.search(p, text)), len(STAR))


def key_lines(s: Step, lines: list[dict[str, Any]]) -> list[int]:
    """Which of a step's lines tell the story at reading speed. The rest stay one click away, and in the whole picture."""
    lay = s.get("layer")
    reads = [i for i, x in enumerate(lines) if x["text"].startswith("device reads")]
    own = lay == "guard" and any("# step" in x["text"] for x in lines)      # the guard's own lines say more than the call restated
    keep = []
    for i, x in enumerate(lines):
        t, k = x["text"], x["k"]
        if lay == "town" and t.startswith(("context", "Town carries")):
            continue
        if lay == "guard" and not (k in ("tool", "out") or t.startswith(("run_call", "policy")) or "# step" in t):
            continue
        if own and (k == "tool" or t.startswith(("run_call", "policy"))):
            continue
        if lay == "device" and i in reads and i not in (reads[0], reads[-1]):
            continue
        keep.append(i)
    return keep


def rich_first(cand: list[tuple[dict, dict]], about_guard: bool) -> list[tuple[dict, dict]]:
    """The order a moment's key lines are offered to its terminal (they still show in the record's order): the first seal and the
    first device state go first, and a moment about the guard's answer then reads the guard's own lines."""
    first: list[tuple[dict, dict]] = []
    took: set[str] = set()
    for c in cand:
        t = c[1]["text"]
        what = "seal" if t.startswith("guard seals") else "state" if re.match(r"devices\.|no device fact moved", t) else ""
        if what and what not in took:
            took.add(what)
            first.append(c)
    own = [c for c in cand if about_guard and c[1]["k"] == "guard" and "# step" in c[1]["text"]]
    chosen = {id(c[1]) for c in first + own}
    return first + own + [c for c in cand if id(c[1]) not in chosen]


class Story:
    """The evening's story, from its first order to its last payment."""

    def __init__(self, ev: Any):
        self.ev = ev
        self.steps = ev.steps
        self.table, self.groups = M.place(self.steps, M.table(ev.sites), ev.ctx, ev.map.edge_set)
        self.seen: dict[str, Any] = {}
        self.tv_prev: dict[str, str] = {}

    def lines(self, s: Step) -> list[dict[str, Any]]:
        out = []
        for x in s.get("terminal") or []:
            k = x.get("kind") or "note"
            text = in_scope(str(x.get("text") or ""))
            if not text:
                continue
            cl = ""
            if k in ("guard", "out") and re.search(r"\b(guard says blocked|refused|failed|overruled)\b", text):
                cl = "no"
            if k == "calc" and "\n" not in text and len(re.findall(r"\S {2,}\S", text)) >= 2:
                cl = "tbl"
            out.append({"k": k, "cl": cl, "text": text, "b": M.line_blocks(s, k, text)})
        return out

    def compile(self) -> dict[str, Any]:
        ev, bidx = self.ev, self.ev.map.index
        recs: list[dict[str, Any]] = []
        rec_of: dict[int, int] = {}
        for s in self.steps:
            ls = self.lines(s)
            rec_of[id(s)] = len(recs)
            own = sorted({b for x in ls for b in x["b"]}, key=lambda b: bidx[b]) or M.block_of(s)
            recs.append({"t": stamp(s.get("sim_time")), "n": str(s.get("title") or ""), "m": 0, "p": str(s.get("plain") or ""),
                         "f": N.name_of(s.get("from"), start=True), "o": N.named(s.get("to") or ""), "w": N.named(s.get("node") or ""),
                         "wn": N.fixed_name(s.get("node")), "sd": M.side(s), "b": [bidx[b] for b in own], "_l": ls})
        self.tv_prev = {k: v for k, v in F.trade_all(ev, self.seen).items() if v}
        base = dict(self.tv_prev)
        moments = [self.moment(mi, mo, [self.steps[i] for i in idx], recs, rec_of)
                   for mi, (mo, idx) in enumerate(zip(self.table, self.groups))]
        touched = sorted({b for m in moments for b in m["lit"]}, key=lambda b: bidx[b])
        nums = F.block_nums(ev, self.steps, self.tv_prev)
        for r in recs:
            r["l"] = [self.line_row(x) for x in r.pop("_l")]
        return {"id": "main", "name": "ENGIE evening", "one": "The aggregator's request, to the last payment", "sent": self.sent(),
                "note": self.note(), "own": True, "ends": "", "moments": moments, "steps": recs, "touched": touched, "nums": nums,
                "followed": self.followed(), "base": base, "ledger": F.ledger_rows(ev.ledger), "effect": [], "vs": "Normal day",
                "k0": K.start_card(ev)}

    def followed(self) -> list[int]:
        """How many homes and buildings this story follows."""
        names = [str(n) for n in (self.ev.home, self.ev.code_home, self.ev.second, self.ev.uni, self.ev.other) if n]
        return [len([n for n in names if N.is_home(n)]), len([n for n in names if N.is_building(n)])]

    def line_row(self, x: dict[str, Any]) -> list[Any]:
        """[kind, extra class, html, box or boxes, key mark, the cut html of a long key line]. The key mark is 0 for evidence,
        1 shown by default, 2 the line that matters, 3 shown by default in the whole picture only."""
        b = [self.ev.map.index[y] for y in x["b"]]
        t = x["text"]
        row: list[Any] = [x["k"], x["cl"], paint_row(t, x["k"]), b[0] if len(b) == 1 else b, x.get("key", 0)]
        if x.get("key") and len(t) > CLIP:
            cut = t[:CLIP].rsplit(" ", 1)[0]                              # at a space, so no name is cut in two
            row.append(paint_row(cut, "", more=len(t) - len(cut)))
        return row

    def sent(self) -> dict[str, str]:
        """What goes in, as the sent message: the buyer's real call."""
        s0 = self.steps[0]
        first_in = next((str(x.get("text")) for x in (s0.get("terminal") or []) if x.get("kind") == "in"), str(s0.get("plain") or ""))
        return {"who": N.name_of(s0.get("from"), start=True), "text": first_in, "full": first_in, "plain": str(s0.get("plain") or ""),
                "t": stamp(s0.get("sim_time"))}

    def note(self) -> str:
        m = self.ev.meta
        com = m.get("community") or {}
        return f'One recorded day: {com.get("homes")} homes, {com.get("buildings")} buildings, {m.get("model_calls")} model answers. {self.ev.sentence}'

    def moment(self, mi: int, mo: M.Mo, ms: list[Step], recs: list[dict[str, Any]], rec_of: dict[int, int]) -> dict[str, Any]:
        ev = self.ev
        kr = re.compile(mo.key, re.I)
        keys = [s for s in ms if kr.search(str(s.get("title") or ""))]
        sr = re.compile(mo.say, re.I)
        say_s = next(s for s in ms if sr.search(str(s.get("title") or "")))
        if say_s.get("layer") == "model":
            say_s = answer_step(ms, say_s)
        chars = self.mark(mo, keys, recs, rec_of)
        idx = [rec_of[id(s)] for s in ms]
        for i in idx:
            recs[i]["m"] = mi
        lit = {b for i in idx for x in recs[i]["_l"] for b in x["b"]} | set(mo.also)
        for i in idx:
            lit |= {ev.map.ids[b] for b in recs[i]["b"] if b < len(ev.map.ids)}
        for s in ms:
            self.seen.update({k: v for k, v in (s.get("values") or {}).items() if v is not None})
            F.take_facts(s, self.seen)
        allv = {k: v for k, v in F.trade_all(ev, self.seen).items() if v}
        fresh = {k: v for k, v in allv.items() if self.tv_prev.get(k) != v}
        self.tv_prev = allv
        hero = self.hero(mo, allv, ms)
        path = self.travel(mo, ms, say_s, hero)
        lit |= set(path)
        chips = [[ev.tv_label(k), allv[k]] for k in mo.trade or ("sold", "nodes", "reserve")
                 if allv.get(k) and (k.startswith("hh") or not hero or allv[k] != hero[0])]
        if not chips:
            chips = [[ev.tv_label(k), allv[k]] for k in ("sold", "nodes", "reserve") if allv.get(k) and not (hero and allv[k] == hero[0])]
        node = str(say_s.get("node") or "")
        block = mo.block.replace("{side}", M.side(say_s)) or (M.receiver(say_s) if say_s.get("layer") == "town" else next(
            (b for x in recs[rec_of[id(say_s)]]["_l"] for b in x["b"]), None) or M.block_of(say_s)[0])
        parts = re.split(r"(?<=[.!?])\s+", str(say_s.get("plain") or "").strip())
        say = parts[min(mo.pick, len(parts) - 1)]
        dwell = 3500 + (len(say) + len(mo.title)) * 45 + chars * 9
        return {"id": mo.id, "n": mo.title, "b": block, "bn": ev.map.full(block), "w": N.named(node), "wn": N.fixed_name(node),
                "t": stamp(say_s.get("sim_time")), "y": say, "hero": hero, "nt": mo.note, "tag": None, "gap": ev.gap(mo.gap),
                "p": path, "c": mo.carry, "lit": self.lit(lit), "s": idx, "tr": chips, "tv": fresh,
                "ms": int(min(15000, max(8000, dwell))),
                "k": K.moment_card(ev, mo, ms, keys, say_s, block, node, allv, fresh, self.seen, hero, say, path)}

    def lit(self, boxes: set[str]) -> list[str]:
        """The boxes a moment lights, in the map's order. A single site's messages travel over NANDA Town like everyone's, so
        its band is lit with them, last."""
        out = sorted(boxes, key=lambda b: self.ev.map.index[b])
        return out + ["town"] if any(b.startswith("site-") for b in out) and "town" not in out else out

    @staticmethod
    def travel(mo: M.Mo, ms: list[Step], say_s: Step, hero: list[str] | None) -> list[str]:
        """The message's way along the map's lines: none when the moment says nothing was sent, and from the node the big figure
        names when that figure is a shortfall."""
        if mo.alt and hero == list(mo.alt):
            return []
        short = largest_short(ms) if "{short_now}" in mo.big else None
        return list(M.path_of(mo, short or say_s))

    def mark(self, mo: M.Mo, keys: list[Step], recs: list[dict[str, Any]], rec_of: dict[int, int]) -> int:
        """Marks the moment's key lines (see line_row) and gives how many characters they hold, for the moment's dwell time."""
        cand: list[tuple[dict, dict]] = []
        for s in keys:
            rec = recs[rec_of[id(s)]]
            cand += [(rec, rec["_l"][i]) for i in key_lines(s, rec["_l"])]
        about_guard = "{guard}" in mo.big
        rank = lambda t: -1 if about_guard and t.startswith("guard says") else star_rank(t)  # noqa: E731
        ranked = sorted(cand, key=lambda c: rank(c[1]["text"]))
        stars = [c for c in ranked if rank(c[1]["text"]) < len(STAR)][:2] or ranked[:1]
        rows = chars = 0
        used: set[int] = set()
        for rec, x in stars:
            x["key"] = 2
            rows += wrapped(x["text"][:CLIP], KEY_CPL) + (0 if id(rec) in used else 1)
            used.add(id(rec))
            chars += min(len(x["text"]), CLIP)
        fill = rich_first(cand, about_guard)
        for rec, x in fill:
            if x.get("key"):
                continue
            need = wrapped(x["text"][:CLIP], KEY_CPL) + (0 if id(rec) in used else 1)
            if rows + need > KEY_ROWS:
                continue
            x["key"] = 1
            rows += need
            used.add(id(rec))
            chars += min(len(x["text"]), CLIP)
        self.fit_split(stars, fill)
        return chars

    @staticmethod
    def fit_split(stars: list[tuple[dict, dict]], cand: list[tuple[dict, dict]]) -> None:
        """The split view's default terminal: the marked lines first, then the key lines that fit, so the marked line is in sight
        with no scrolling. A line left out here stays a key line in the whole picture (key 3)."""
        rows = 0
        used: set[int] = set()
        for rec, x in stars:
            rows += wrapped(x["text"][:CLIP], SPLIT_CPL) + (0 if id(rec) in used else 1)
            used.add(id(rec))
        for rec, x in cand:
            if x.get("key") != 1:
                continue
            need = wrapped(x["text"][:CLIP], SPLIT_CPL) + (0 if id(rec) in used else 1)
            if rows + need > SPLIT_ROWS:
                x["key"] = 3
                continue
            rows += need
            used.add(id(rec))

    def hero(self, mo: M.Mo, allv: dict[str, str], ms: list[Step]) -> list[str] | None:
        """The number or decision that matters at this moment, with its caption. Every {name} comes from the recording; a figure
        the recording lacks leaves the moment without one, or with its stated alternative."""
        lines = [str(x.get("text") or "") for s in ms for x in s.get("terminal") or []]
        extra: dict[str, str] = {"other_place": self.ev.other_place}
        g = next((m.group(1) for t in lines for m in [re.match(r"guard says (\w+)", t)] if m), None)
        if g:
            extra["guard"] = g
        biggest = largest_short(ms)
        if biggest is not None:
            extra["short_now"] = f'{re.search(r"short by up to ([\d,.]+) kW", str(biggest.get("plain"))).group(1)} kW'
        vals = {**allv, **extra}
        if [k for t in (mo.big, mo.cap) for k in re.findall(r"\{(\w+)\}", t) if not vals.get(k)]:
            return list(mo.alt) if mo.alt else None
        fill = lambda t: re.sub(r"\{(\w+)\}", lambda g: vals[g.group(1)], t)  # noqa: E731
        cap = fill(mo.cap)
        if "{short_now}" in mo.big and biggest is not None and biggest.get("node"):      # who is short goes under the figure
            cap = f'{cap}, by {N.fixed_name(biggest.get("node"))}'
        return [fill(mo.big), cap]
