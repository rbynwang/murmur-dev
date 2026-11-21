"""The sheet's eight layers, top to bottom: each with its name, what it is, its status, its own blocks, its terminal, what
changed in it and what it doesn't do."""
from __future__ import annotations

from typing import Any

from ..templating import Markup, join, render
from .naming import QUOTE, TAG, named, numbered, shown
from .record import Record
from .terminals import terminal
from .words import DESIGN_GAPS, DEVICES, GAP_LAYER, KEY_ROWS, LAYER_NAMES, LED_ROWS, OVERVIEW, REV, SOLVED

NONE = "—"         # a cell the run fills in when it reaches it


def figure(x: float, d: int = 1) -> str:
    return f"{x:,.{d}f}"


def head(rec: Record, n: int) -> Markup:
    return render("full_record/parts.html#head", number=str(n) if n < 8 else "R", title=LAYER_NAMES[n], overview=OVERVIEW[n].format(**rec.counts),
                  chips=render(f"full_record/chips.html#l{n}"))


def gap_rows(rec: Record) -> list[tuple[str, str, str, str]]:
    """The recording's own gaps, less those every node's own agent closed, then the design's: (id, title, what you might
    expect, what happens)."""
    own = [(str(g.get("id") or ""), named(g.get("title") or "", TAG), named(g.get("expect") or "", TAG), named(g.get("actual") or "", TAG))
           for g in rec.gaps if isinstance(g, dict) and g.get("id") not in SOLVED]
    return own + DESIGN_GAPS


def layer_gaps(rec: Record, n: int) -> Markup | str:
    rows = [render("full_record/parts.html#gap", title=title, actual=actual) for gid, title, _, actual in gap_rows(rec) if GAP_LAYER.get(gid) == n]
    return render("full_record/parts.html#gaps", items=join(rows)) if rows else ""


def layer_revs(n: int) -> Markup:
    rows = [render("full_record/parts.html#rev", title=title, tag=tag, was=was, now=now) for tag, title, was, now, _, layer in REV if layer == n]
    return render("full_record/parts.html#revs", rows=join(rows))


def buyers(rec: Record, terms: dict[str, list[Markup]]) -> Markup:
    return render("full_record/layers.html#buyers", head=head(rec, 1), gaps=layer_gaps(rec, 1),
                  terminal=terminal("buy", "buyers", "utility, grid operator: orders, contracts, calls", terms["buy"]))


def ledger_value(h: dict[str, Any], key: str | None) -> str:
    """A half hour's figure; the buildings' part of what is asked of the nodes is worked out here."""
    if key is not None:
        return figure(h[key])
    return f'{h["asked_buildings_kw"] / h["asked_of_nodes_kw"] * 100:.1f}%'


def ledger_row(row: tuple[Any, ...], hs: list[dict[str, Any]], first_set: dict[str, int]) -> Markup:
    """One row of the clearing at a glance: a section's title, or a figure per half hour, lit from the first step that sets it."""
    if len(row) == 1:
        return render("full_record/layers.html#ledger_section", span=str(len(hs) + 1), title=row[0])
    letter, label, key, lights, how = row
    return render("full_record/layers.html#ledger_row", cls="fut keyrow" if letter in KEY_ROWS else "fut", step=str(first_set[lights]), letter=letter, label=label,
                  how=render("full_record/layers.html#ledger_how", how=how) if how else "",
                  cells=join(render("full_record/layers.html#ledger_cell", value=ledger_value(h, key)) for h in hs))


def coordinator(rec: Record, terms: dict[str, list[Markup]], first_set: dict[str, int]) -> Markup:
    hs = rec.half_hours[:6]
    return render("full_record/layers.html#coordinator", head=head(rec, 2), revs=layer_revs(2), gaps=layer_gaps(rec, 2),
                  terminal=terminal("coord", "coordinator", "market.py, rt_market.py: the working, line by line", terms["coord"], size="tall"),
                  columns=join(render("full_record/layers.html#ledger_column", start=named(h.get("start") or "", TAG)) for h in hs),
                  rows=join(ledger_row(r, hs, first_set) for r in LED_ROWS))


def town(rec: Record, terms: dict[str, list[Markup]]) -> Markup:
    return render("full_record/layers.html#town", head=head(rec, 3), messages=figure(rec.ledger["totals"]["messages"], 0), revs=layer_revs(3), gaps=layer_gaps(rec, 3),
                  terminal=terminal("town", "envelopes", "sender, receiver, id, signature cut to 16 characters. Bodies stay shut", terms["town"]))


def node_column(side: str, cast: dict[str, Any], label: str, extra: dict[str, Any] | None, lines: list[Markup]) -> Markup:
    """A followed node: its nine steps, the node that runs the same steps beside it, and its terminal."""
    node = cast.get("node") or "not in this trace"
    shelf = cast.get("shelf") or []
    also = render("full_record/layers.html#node_also", node=shown(extra["node"], TAG), side=side) if extra and extra.get("node") else ""
    block = "home" if side == "h" else "bld"
    return render("full_record/layers.html#node_column", col="homecol" if side == "h" else "bldcol", side=side, block=block, label=label, node=shown(node, TAG),
                  bits=f" · {len(shelf)} tools on its shelf" if shelf else "", also=also,
                  terminal=terminal(block, str(node), ("home_agent" if side == "h" else "building_agent") + ": every step as recorded", lines, cls=block))


def cell(rec: Record, n: dict[str, Any]) -> Markup:
    """One node of the community, with its figures on hover."""
    led = (rec.ledger.get("nodes") or {}).get(n["node"]) or {}
    bits = [numbered(n["number"]) if n["number"] else shown(n["node"], QUOTE), "its own agent, plans by code"]

    def kw0(k: str) -> Any:
        return (led.get(k) or [None])[0]
    if kw0("offered_kw") is not None:
        bits.append(f'offered {kw0("offered_kw"):,.1f} kW')
    if kw0("contract_kw") is not None:
        bits.append(f'contract {kw0("contract_kw"):,.1f} kW')
    if led.get("delivered_kwh") is not None:
        bits.append(f'delivered {led["delivered_kwh"]:,.1f} kWh')
    if led.get("paid_usd") is not None:
        bits.append(f'paid ${led["paid_usd"]:,.2f}')
    return render("full_record/layers.html#cell", kind=(" big" if n["big"] else "") + (" think" if n["think"] else ""), tip=", ".join(bits))


def nodes(rec: Record, terms: dict[str, list[Markup]]) -> Markup:
    f = rec.follow
    return render("full_record/layers.html#nodes", head=head(rec, 4), homes=str(rec.counts["homes"]), buildings=str(rec.counts["buildings"]), reader=rec.reader,
                  home=node_column("h", f.get("thinking_home") or {}, "Home", None, terms["home"]),
                  building=node_column("b", f.get("university") or {}, "Building", f.get("mall_or_office"), terms["bld"]),
                  answers=str(rec.meta.get("model_calls")), total=str(len(rec.nodes)), cells=join(cell(rec, n) for n in rec.nodes), revs=layer_revs(4), gaps=layer_gaps(rec, 4),
                  queue=terminal("queue", "the small model", "its prompts and answers, in full. think=false, so nothing is hidden", terms["queue"], cls="model", size="tall"))


def tools(rec: Record, terms: dict[str, list[Markup]]) -> Markup:
    return render("full_record/layers.html#tools", head=head(rec, 5), revs=layer_revs(5), gaps=layer_gaps(rec, 5),
                  terminal=terminal("tools", "tool server", "context.py, guard.py, drivers.py: every call and verdict", terms["tools"], size="tall"))


def devices(rec: Record, terms: dict[str, list[Markup]]) -> Markup:
    who, called = rec.device_rows(), rec.devices_called()
    rows = [render("full_record/layers.html#device_row", key=key, name=name, who=shown(who.get(key) or "", TAG) or "no write yet",
                   set=NONE if key in called else "no call on this day", was=NONE if key in called else "", now=NONE if key in called else "") for key, name in DEVICES]
    return render("full_record/layers.html#devices", head=head(rec, 6), rows=join(rows), revs=layer_revs(6), gaps=layer_gaps(rec, 6),
                  terminal=terminal("dev", "devices", "each write, with the device's own readings before and after", terms["dev"]))


def people(rec: Record, terms: dict[str, list[Markup]], chats: dict[str, list[Markup]]) -> Markup:
    return render("full_record/layers.html#people", head=head(rec, 7), owner=join(chats["owner"]), manager=join(chats["manager"]), revs=layer_revs(7), gaps=layer_gaps(rec, 7),
                  terminal=terminal("people", "people", "what is kept for them, and what they said", terms["people"]))


def return_path(rec: Record, terms: dict[str, list[Markup]]) -> Markup:
    rows = [render("full_record/layers.html#return_row", start=named(h.get("start") or "", TAG), sold=figure(h["sold_kw"]), k=str(k)) for k, h in enumerate(rec.half_hours[:6])]
    return render("full_record/layers.html#return_path", head=head(rec, 8), rows=join(rows), revs=layer_revs(8), gaps=layer_gaps(rec, 8),
                  terminal=terminal("ret", "return path", "readings, checks, settlement, payment", terms["ret"], size="tall"))


def sheet_layers(rec: Record, terms: dict[str, list[Markup]], chats: dict[str, list[Markup]], first_set: dict[str, int]) -> Markup:
    """The eight layers, one after another."""
    return join((buyers(rec, terms), coordinator(rec, terms, first_set), town(rec, terms), nodes(rec, terms), tools(rec, terms), devices(rec, terms),
                 people(rec, terms, chats), return_path(rec, terms)), "\n")
