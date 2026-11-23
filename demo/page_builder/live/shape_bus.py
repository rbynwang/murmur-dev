"""The steps of one message the bus accepted: steps(sh, event, tq, wall).

An event is the bus record's {message_id, from, to, kind, body, at}. A message crossing NANDA Town is shown as its envelope: the
lines Town can read (who sent it to whom, its context, its signature, its size) and, last, what the receiver reads out of it. A
message to the grid operator is a buyer's step, since the map's receiver of an envelope is the utility alone. What only some
messages carry a step of its own for is said once a sale (the call for offers, the contracts, the frozen list): Shaping.once.

Not every message is a step. A message to or from a node the story does not follow is counted, and so is every report row but the
first from the community and from each site inside the window: Shaping.count, which the console shows as numbers.
"""
from __future__ import annotations

from dataclasses import replace
from typing import Any

from .. import names as N
from .fmt import J, T, cut, hm, n0, n1, n2, pl, table
from .shape import Shaping, Step
from .words_bus import ROWS

Event = dict[str, Any]
BUYERS = ("utility", "grid-operator")
SITE_KIND = {"site-pv": "solar-and-battery plant", "site-dc": "data center"}


def kind(e: Event) -> str:
    return str(e.get("kind") or "").removeprefix("beckn.")


def message(e: Event) -> dict[str, Any]:
    body = e.get("body") or {}
    return body.get("message") or {} if isinstance(body, dict) else {}


def label(sh: Shaping, who: Any, start: bool = False) -> str:
    """A participant as a sentence names it: "home 39", "the office", "the utility"."""
    return N.name_of(sh.name(who), start=start)


def buyer_box(who: Any) -> str:
    return "buy-g" if str(who or "").startswith("grid") else "buy-u"


def site_of(who: Any) -> tuple[str, str]:
    box = "site-pv" if "pv" in str(who) else "site-dc"
    return box, SITE_KIND[box]


def envelope(e: Event, opened: list[dict[str, str]]) -> list[dict[str, str]]:
    """What Town can read of a message, then what its receiver reads out of it."""
    b = e.get("body") if isinstance(e.get("body"), dict) else {}
    c = b.get("context") or {}
    return [T("out", f"envelope  message_id={e.get('message_id')}  from={e.get('from')}  to={e.get('to')}  kind={e.get('kind')}"),
            T("note", f"context   action={c.get('action')}  transactionId={c.get('transactionId')}  messageId={c.get('messageId')}  "
                      f"ttl={c.get('ttl')}  domain={c.get('domain')}"),
            T("sign", f"signer {cut(b.get('signer'))}  sig {cut(b.get('sig'))}  Ed25519 over the canonical JSON of the whole body"),
            T("note", f"body      {len(J(b)):,} bytes, carried unread")] + opened


def town(sh: Shaping, row: str, e: Event, tq: int, wall: float, opened: list[dict[str, str]] | None = None, **words: Any) -> Step:
    """A message as its envelope, in the Row named `row`. One to the grid operator is the grid operator's own step."""
    r = ROWS[row]
    if str(e.get("to") or "").startswith("grid") and r.layer == "town":
        r = replace(r, layer="buyer")
    node = words.pop("node", None)
    lines = envelope(e, opened if opened is not None else [T("in", J(message(e), 400))])
    return sh.step(r, tq, wall, frm=e.get("from"), to=e.get("to"), node=node, lines=lines, **words)


def parties(sh: Shaping, e: Event) -> dict[str, str]:
    """The words every Row may name: the buyer of the message and the node it is about, each as a sentence says it."""
    who = next((x for x in (e.get("to"), e.get("from")) if str(x) in BUYERS), "")
    node = next((x for x in (e.get("to"), e.get("from")) if N.is_home(sh.name(x)) or N.is_building(sh.name(x))), "")
    return {"buyer": label(sh, who), "Buyer": label(sh, who, True), "name": label(sh, node), "Name": label(sh, node, True),
            "buyer_box": buyer_box(who)} | ({"node": node} if node else {})


def per_half_hour(slots: list[dict[str, Any]], key: str) -> list[float]:
    return [float(s.get(key) or 0) for s in slots or []]


# ---------------------------------------------------------------- the day-ahead sale
def discover(sh: Shaping, e: Event, tq: int, wall: float) -> list[Step]:
    intent, w = message(e).get("intent") or {}, parties(sh, e)
    need = intent.get("need")
    if need is None:
        date = str(intent.get("date") or "")
        return [town(sh, "ask_q" if date == sh.ev.meta.get("day") else "tomorrow_q", e, tq, wall, date=date, **w)]
    out = []
    if sh.once(need.get("event_id"), "call"):
        slots, members = need.get("slots") or [], sh.ev.total
        kw = per_half_hour(slots, "kw_requested")
        out.append(sh.step(ROWS["call"], tq, wall, frm="community", to="all nodes", members=members, kw=n0(max(kw or [0])),
                           lines=[T("out", f"discover to {pl(members, 'member')}: event {need.get('event_id')}, window {hm(need.get('window_start'))} "
                                           f"to {hm(need.get('window_end'))}, {pl(len(slots), 'half hour')}, ${n2((slots or [{}])[0].get('price') or 0)}/kWh"),
                                  T("calc", f"the call's kW per half hour: {J(kw)}")]))
    if e.get("to") in sh.follow:
        row = ROWS["call_reach"] if N.is_home(sh.name(e.get("to"))) else replace(ROWS["call_reach"], beat="bld-offer")
        out.append(replace_row(sh, row, e, tq, wall, w))
    else:
        sh.count["call reached a node not followed"] += 1
    return out


def replace_row(sh: Shaping, row: Any, e: Event, tq: int, wall: float, w: dict[str, str]) -> Step:
    node = w.pop("node", None)
    return sh.step(row, tq, wall, frm=e.get("from"), to=e.get("to"), node=node, lines=envelope(e, [T("in", J(message(e), 400))]), **w)


def on_discover(sh: Shaping, e: Event, tq: int, wall: float) -> list[Step]:
    msg, w = message(e), parties(sh, e)
    if str(e.get("from")) in BUYERS:
        cats = msg.get("catalogs") or []
        if not cats:
            return [town(sh, "tomorrow_a", e, tq, wall, date="tomorrow", **w)]
        res = [r for c in cats for r in c.get("resources") or []]
        said = [f"order {r.get('id')}: {(r.get('descriptor') or {}).get('shortDesc') or ''}".rstrip(": ") for r in res]
        return [town(sh, "ask_a", e, tq, wall, opened=[T("in", x) for x in said] or None, **w)]
    if e.get("from") not in sh.follow:
        sh.count["offer from a node not followed"] += 1
        return []
    slots = (msg.get("offer") or {}).get("slots") or []
    kw = per_half_hour(slots, "kw_offered")
    row = ROWS["offer_sent"] if N.is_home(sh.name(e.get("from"))) else replace(ROWS["offer_sent"], beat="bld-offer")
    node = w.pop("node", None)
    return [sh.step(row, tq, wall, frm=e.get("from"), to=e.get("to"), node=node, kw=n2(max(kw or [0])), values={"offer_kw": kw},
                    lines=envelope(e, [T("in", f"offer, kW per half hour: {J(kw)}")]), **w)]


def buyer_side(row: str):
    def shape(sh: Shaping, e: Event, tq: int, wall: float) -> list[Step]:
        w = parties(sh, e)
        status = str((message(e).get("contract") or {}).get("status") or "").lower()
        return [town(sh, row, e, tq, wall, status=status or "signed", **w)]
    return shape


def confirm(sh: Shaping, e: Event, tq: int, wall: float) -> list[Step]:
    if str(e.get("to")) in BUYERS:
        return buyer_side("confirm_b")(sh, e, tq, wall)
    c, w, out = message(e).get("contract") or {}, parties(sh, e), []
    if sh.once(c.get("event_id"), "contracts"):
        n = len(sh.snap.get("alloc") or {}) or sh.ev.total
        out.append(sh.step(ROWS["contracts"], tq, wall, frm="community", to="all nodes", n=n, values={"contracts": n},
                           lines=[T("out", f"confirm to {pl(n, 'node')}: kW per half hour, price, opt-out time, when the car may restart")]))
    if e.get("to") not in sh.follow:
        sh.count["contract to a node not followed"] += 1
        return out
    kw = [float(x.get("kw") or 0) for x in c.get("commitments") or []]
    price = next((s.get("price") for s in ((sh.snap.get("need") or {}).get("slots") or [])), None) or 0
    return out + [town(sh, "contract_reach", e, tq, wall, kw=n2(max(kw or [0])), price=n2(price), values={"contract_kw": kw}, **w)]


def on_confirm(sh: Shaping, e: Event, tq: int, wall: float) -> list[Step]:
    if str(e.get("from")) in BUYERS:
        return buyer_side("on_confirm_b")(sh, e, tq, wall)
    if str((message(e).get("contract") or {}).get("status") or "").upper() not in ("ACCEPTED", ""):
        sh.count["declined"] += 1
    if e.get("from") not in sh.follow:
        sh.count["answer from a node not followed"] += 1
        return []
    status = str((message(e).get("contract") or {}).get("status") or "answered")
    return [town(sh, "contract_answer", e, tq, wall, status=status, **parties(sh, e))]


def update(sh: Shaping, e: Event, tq: int, wall: float) -> list[Step]:
    m, w, out = message(e), parties(sh, e), []
    if "telemetry_done" in m:
        d = m["telemetry_done"] or {}
        return [town(sh, "readings_done", e, tq, wall, opened=[T("in", f"meters {d.get('meters')}, readings {d.get('readings')}, missing {d.get('missing')}")], **w)]
    c = m.get("contract") or {}
    meters = c.get("participatingMeters") or []
    if not meters:
        sh.count["update"] += 1
        return []
    if sh.once(c.get("community_event"), "frozen"):
        sold = [float(v) for _, v in sorted((c.get("capacityOffered") or {}).items(), key=lambda kv: int(kv[0]))]
        out.append(sh.step(ROWS["frozen"], tq, wall, frm="community", to="buyers", n=len(meters),
                           lines=[T("in", f"{len(meters)} accepted"), T("calc", f"capacity sold, final: {J(sold)} kW per half hour")],
                           values={"accepted": len(meters), "declined": sh.count["declined"], "sold_kw": [max(sold or [0])]}))
    return out + [town(sh, "final_list", e, tq, wall, **w)]


# ---------------------------------------------------------------- the aggregator's requests and the reports upward
def request(sh: Shaping, e: Event, tq: int, wall: float) -> list[Step]:
    if str(e.get("to")).startswith("site-"):
        box, what = site_of(e.get("to"))
        req = message(e).get("request") or {}
        rows = req.get("rows") or []
        most = max((abs(float(r.get("battery_kw") or 0)) for r in rows), default=0.0)
        return [town(sh, "site_ask", e, tq, wall, site_kind=what, site_box=box,
                     values={"site_asked": f"{n0(most)} kW", "site_cards": [[what.capitalize(), [["Quarter hours", str(len(rows))], ["Most asked", f"{n0(most)} kW"]]]],
                             "site_ask_cap": "asked of the site at most in a quarter hour. The same signed request a community gets"})]
    sh.held[e.get("message_id") or ""] = (e, tq, wall)     # shown with its answer, which says whether it was taken
    return []


def answer(sh: Shaping, e: Event, tq: int, wall: float) -> list[Step]:
    a = message(e).get("answer") or {}
    if str(e.get("from")).startswith("site-"):
        box, what = site_of(e.get("from"))
        said = "it takes the request whole" if a.get("taken") else f"it gives less: {a.get('why') or 'no reason given'}"
        return [town(sh, "site_answer", e, tq, wall, site_kind=what, site_box=box, answer=said,
                     values={"site_cards": [[what.capitalize(), [["Its answer", "taken" if a.get("taken") else "less"], ["Why", str(a.get("why") or "")]]]],
                             "site_ans_cap": "signed, with the reason wherever it will give less. No coordinator in between"})]
    asked = next((v for k, v in sh.held.items() if str(a.get("request") or "") and str(a.get("request")) in k), None)
    out: list[Step] = []
    beat = "battery-ask" if a.get("taken") else "ask-refused"
    if asked:
        sh.held.pop(asked[0].get("message_id") or "", None)
        out.append(town(sh, "request", asked[0], asked[1], asked[2]) if a.get("taken") else
                   replace_row(sh, replace(ROWS["request"], beat=beat, key=False), asked[0], asked[1], asked[2], {}))
    row = "request_taken" if a.get("taken") else "request_refused"
    out.append(sh.step(ROWS[row], tq, wall, frm="community", lines=[
        T("calc", f"quarter hours asked: {a.get('rows')}  ·  too late, because they had ended: {a.get('too_late', 0)}"),
        T("out", f"answer: {'taken' if a.get('taken') else 'refused'}, {a.get('rows')} quarter hours from {hm(a.get('first'))} to {hm(a.get('last'))}")]))
    out.append(replace_row(sh, replace(ROWS["request_back"], beat=beat), e, tq, wall, {}))
    return out


def report(sh: Shaping, e: Event, tq: int, wall: float) -> list[Step]:
    r = message(e).get("report") or {}
    ts, (w0, w1) = str(r.get("timestamp") or ""), sh.window
    inside = w0 <= ts < w1
    who = str(e.get("from"))
    if not inside or not sh.once("report", who):
        sh.count["community.report"] += 1
        return []
    line = T("out", f"{hm(ts)}  net power {n0(r.get('reported_p_net_kw') or 0)} kW  charge {n0(r.get('reported_soc_percent') or 0)}%  "
                    f"price ${float(r.get('quote_price_usd_kwh') or 0):.3f} per kWh")
    if who.startswith("site-"):
        box, what = site_of(who)
        return [sh.step(ROWS["site_report"], tq, wall, frm=who, to="aggregator", site_kind=what, site_box=box, lines=[line, T("note", str(r.get("text") or ""))],
                        values={"site_rows": "1 row a quarter hour", "site_cards": [[what.capitalize(), [["Charge", f"{n0(r.get('reported_soc_percent') or 0)}%"]]]],
                                "site_rep_cap": "signed rows from the sites, one a quarter hour"})]
    end = f"{int(ts[11:13]) + (int(ts[14:16]) + 15) // 60:02d}:{(int(ts[14:16]) + 15) % 60:02d}" if len(ts) >= 16 else ""
    return [sh.step(ROWS["community_report"], tq, wall, frm="community", start=hm(ts), end=end, lines=[line, T("note", str(r.get("text") or ""))])]


# ---------------------------------------------------------------- the desk
def rt_call(sh: Shaping, e: Event, tq: int, wall: float) -> list[Step]:
    c = message(e).get("call") or {}
    sh.calls[str(c.get("id"))] = c
    return [town(sh, "call_in", e, tq, wall, kw=n0(c.get("kw") or 0), start=hm(c.get("start")), end=hm(c.get("end")), price=n2(c.get("price_usd_per_kwh") or 0),
                 why=str(c.get("why") or "a call"), values={"call_kw": c.get("kw")}, **parties(sh, e))]


def rt_capacity(sh: Shaping, e: Event, tq: int, wall: float) -> list[Step]:
    short = message(e).get("short") or {}
    w = parties(sh, e)
    if not short:
        return [town(sh, "short_none", e, tq, wall, **w)]
    most = max(float(v) for v in short.values())
    return [town(sh, "short", e, tq, wall, kw=n2(most), opened=[T("in", f"short: {J(short)}")], **w)]


def desk_rows(sh: Shaping, e: Event, one: str, many: str) -> tuple[str, str]:
    i = str(((message(e).get("ask") or message(e).get("dispatch") or message(e).get("answer") or {}).get("id")) or "")
    return (many, one) if i not in sh.calls else (many.replace("desk_", "call_"), one.replace("desk_", "call_"))


def rt_ask(sh: Shaping, e: Event, tq: int, wall: float) -> list[Step]:
    a, w = message(e).get("ask") or {}, parties(sh, e)
    many, one = desk_rows(sh, e, "desk_ask_one", "desk_ask")
    sh.asked[(str(a.get("id")), tq)] += 1
    out = []
    if sh.once(str(a.get("id")), "ask", tq):
        out.append(sh.step(ROWS[many], tq, wall, frm="community", to="members", n="its", start=hm(a.get("start")), end=hm(a.get("end")),
                           lines=[T("calc", J(a)), T("out", f"rt_ask to the members who can add, at ${n2(a.get('price_usd_per_kwh') or 0)} per kWh")]))
    if e.get("to") in sh.follow:
        out.append(town(sh, one, e, tq, wall, start=hm(a.get("start")), end=hm(a.get("end")), price=n2(a.get("price_usd_per_kwh") or 0), **w))
    return out


def rt_answer(sh: Shaping, e: Event, tq: int, wall: float) -> list[Step]:
    a = message(e).get("answer") or {}
    row = "call_answer" if str(a.get("id")) in sh.calls else "desk_answer"
    if e.get("from") not in sh.follow:
        sh.count["answer from a node not followed"] += 1
        return []
    return [town(sh, row, e, tq, wall, kw=n2(a.get("kw") or 0), **parties(sh, e))]


def rt_dispatch(sh: Shaping, e: Event, tq: int, wall: float) -> list[Step]:
    d, w = message(e).get("dispatch") or {}, parties(sh, e)
    row = "call_dispatch" if str(d.get("id")) in sh.calls else "desk_dispatch"
    steps = d.get("steps") or {}
    kw = max((float(v) for v in steps.values()), default=0.0)
    asked = sh.asked[(str(d.get("id")), tq)]
    lines = [T("calc", J(d, 400)), T("out", f"confirmed {kw:.3f} kW to {sh.name(e.get('to'))}, rt_ask to {pl(asked, 'member')} now")]
    return [town(sh, row, e, tq, wall, kw=n2(kw), start=hm(d.get("start")), end=hm(d.get("end")), price=n2(d.get("price_usd_per_kwh") or 0),
                 opened=lines, values={"call_confirmed_kw": kw} if row == "call_dispatch" else {}, **w)]


def rt_confirm(sh: Shaping, e: Event, tq: int, wall: float) -> list[Step]:
    m, w = message(e), parties(sh, e)
    if "warning" in m:
        x = m["warning"]
        if not sh.once("warning", str(x.get("id")), tq):
            return []
        return [town(sh, "desk_warns", e, tq, wall, kw=n2(x.get("short_kw") or 0), start=hm(x.get("start")), end=hm(x.get("end")),
                     why=str(x.get("why") or "a shortfall"), **w)]
    x = m.get("confirm")
    if x is None or str(x.get("id")) not in sh.calls:
        sh.count["rt_confirm"] += 1
        return []
    kw = float(x.get("kw") or x.get("confirmed_kw") or 0)
    return [town(sh, "call_confirm", e, tq, wall, kw=n2(kw), values={"call_confirmed_kw": kw}, opened=[T("in", f"confirmed {kw:.3f} kW, {J(x, 300)}")], **w)]


# ---------------------------------------------------------------- after the window
def on_status(sh: Shaping, e: Event, tq: int, wall: float) -> list[Step]:
    m, w, frm = message(e), parties(sh, e), str(e.get("from"))
    if "performance" in m and (m["performance"] or {}).get("kind") == "baselines":
        meters = (m["performance"] or {}).get("meters") or {}
        lines = [T("note", f"method: {m['performance'].get('methodology')}")] + [
            T("calc", f"{k}: baseline {J([round(float((v.get(s) or {}).get('BASELINE') or 0), 3) for s in sorted(v, key=int)])} kW per half hour")
            for k, v in list(meters.items())[:8]]
        node = w.pop("node", None)
        return [sh.step(ROWS["baselines"], tq, wall, frm=frm, to=e.get("to"), node=node, n=len(meters), lines=lines, **w)]
    if "node_report" in m:
        return [town(sh, "node_report", e, tq, wall, **w)] if frm in sh.follow else []
    if "batch" in m:
        if frm not in sh.follow or str(e.get("to")) in BUYERS:
            sh.count["readings"] += 1
            return []
        return [town(sh, "readings", e, tq, wall, opened=[T("in", f"{pl(len(m['batch']), 'signed reading')}")], **w)]
    s = m.get("settlement") or {}
    if s.get("components") is not None and frm in BUYERS:
        parts = s.get("components") or []
        usd = round(sum(float(x.get("net") or 0) for x in parts), 4)
        key = "buyer_utility_usd" if frm == "utility" else "buyer_grid_operator_usd"
        node = w.pop("node", None)
        rows = [[x.get("id"), n1(x.get("offered") or 0), n1(x.get("delivered") or 0), n2(x.get("price") or 0), f"${n2(x.get('net') or 0)}"] for x in parts]
        return [sh.step(ROWS["buyer_settles"], tq, wall, frm=frm, to=e.get("to"), node=node, usd=n2(usd), values={key: usd},
                        lines=[T("calc", x) for x in table(["half hour", "sold to it", "delivered", "price", "pay"], rows)], **w)]
    if s and e.get("to") in sh.follow:
        return [town(sh, "pay_told", e, tq, wall, kwh=n2(s.get("delivered_kwh") or 0), committed=n2(s.get("committed_kwh") or 0),
                     usd=n2(s.get("payment") or 0), rep=f"{float(s.get('reputation') or 0):.3f}",
                     values={"paid_node_usd": s.get("payment"), "reputation": s.get("reputation")}, **w)]
    sh.count["on_status"] += 1
    return []


SHAPERS = {"discover": discover, "on_discover": on_discover, "select": buyer_side("select"), "on_select": buyer_side("on_select"),
           "init": buyer_side("init"), "on_init": buyer_side("on_init"), "confirm": confirm, "on_confirm": on_confirm, "update": update,
           "community.request": request, "community.answer": answer, "community.report": report, "rt_call": rt_call,
           "rt_capacity": rt_capacity, "rt_ask": rt_ask, "rt_answer": rt_answer, "rt_dispatch": rt_dispatch, "rt_confirm": rt_confirm,
           "on_status": on_status}
FAULT_ROW = {"discover": "call", "on_discover": "ask_a", "confirm": "contracts", "on_confirm": "contract_answer", "update": "frozen",
             "community.request": "request", "community.answer": "request_taken", "community.report": "community_report", "rt_call": "call_in",
             "rt_capacity": "short", "rt_ask": "desk_ask", "rt_answer": "desk_answer", "rt_dispatch": "desk_dispatch", "rt_confirm": "desk_warns",
             "on_status": "node_report"}


def steps(sh: Shaping, e: Event, tq: int, wall: float) -> list[Step]:
    """The steps of one accepted message, never an exception: a message of a kind no shaper knows is counted, not shown."""
    k = kind(e)
    shape = SHAPERS.get(k)
    if shape is None:
        sh.count[k or "a message of no kind"] += 1
        return []
    return sh.shaped(ROWS[FAULT_ROW.get(k, k if k in ROWS else "init")], e, tq, wall, shape, sh, e, tq, wall, kind=k)
