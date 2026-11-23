"""The steps of what the console reads beside the bus: its own posts, the sale's snapshots and the meter.

  posted(sh, post, tq, wall)               an order the console placed with a buyer, or a surprise it posted to a node's or a buyer's door
  snapshot(sh, trigger, event, tq, wall)   the sale as GET /v2/events/{id} gave it at a trigger: select (the offers and the book),
                                           telemetry_done (the readings), settlement and done (what was delivered, and the pay)
  delivery(sh, rows, now, tq, wall)        a half hour of the window, once its two quarter-hours are in the meter and the clock has left it

What a snapshot is made of is the sale's own record (the community agent's market): offers by node, the pooled offer, what was sold and
asked of each node, the readings, the actuals and the result. A snapshot is kept in sh.snap for the next items, which read it.
"""
from __future__ import annotations

from typing import Any

from .. import names as N
from .beats import SURPRISES
from .fmt import J, T, hm, n1, n2, pl, table, usd
from .shape import QUARTER, Row, Shaping, Step, when
from .words_bus import ROWS

LAYER = {"note": "person", "car_now": "person", "weather": "device", "building_closed": "person", "building_need": "person",
         "emergency": "buyer", "battery_fault": "agent", "battery_low": "agent"}


def slots(d: dict[str, Any] | None) -> list[float]:
    """A per-half-hour figure as the market keeps it ({"0": kW, "1": kW, ...}), as a list in slot order."""
    return [round(float(v), 3) for _, v in sorted((d or {}).items(), key=lambda kv: int(kv[0]))]


def surprise_kind(post: dict[str, Any]) -> str | None:
    """Which surprise a post is, by its door and body; None for an order."""
    if post.get("kind"):
        return str(post["kind"])
    path, body = str(post.get("path") or ""), post.get("body") or {}
    if path.endswith("/alert"):
        return "emergency"
    over = (body.get("override") or {}).get("kind")
    named = {"note": "note", "ev_now": "car_now"}.get(over) if over else None
    keys = {"weather": "weather", "closed": "building_closed", "zone_event": "building_need", "battery_fault": "battery_fault",
            "battery_soc": "battery_low"}
    return named or next((v for k, v in keys.items() if k in body), None)


def posted(sh: Shaping, post: dict[str, Any], tq: int, wall: float) -> list[Step]:
    body = post.get("body") or {}
    if str(post.get("path") or "").endswith("/needs"):
        return [order(sh, post, body, tq, wall)]
    kind = surprise_kind(post)
    if kind not in SURPRISES:
        sh.count["a post of no known kind"] += 1
        return []
    title, word, _, _ = SURPRISES[kind]
    who = post.get("who") or (body.get("override") or {}).get("home") or next(iter((body.get("battery_fault") or body.get("battery_soc") or {}).get("homes") or []), None)
    if who is None and "/b/" in str(post.get("path")):
        who = str(post["path"]).split("/b/")[1].split("/")[0]
    ok = 200 <= int(post.get("status") or 0) < 300
    row = Row(f"s-{kind}", "exception", LAYER[kind], title, "{word}: {said}", True, True, "")
    said = f"posted to {post.get('part')}, which answered {post.get('status')}" if ok else f"not taken: the {post.get('part')} answered {post.get('status')}"
    buyer = str(post.get("part")) if kind == "emergency" else None
    return [sh.step(row, tq, wall, frm=buyer or "person", to=post.get("part"), node=who if kind != "emergency" else None, word=word, said=said,
                    lines=[T("out", f"POST {post.get('path')}  {J(body, 400)}"), T("in", f"answer {post.get('status')}: {J(post.get('answer'), 400)}")])]


def order(sh: Shaping, post: dict[str, Any], b: dict[str, Any], tq: int, wall: float) -> Step:
    buyer = str(b.get("to") or post.get("part") or "")
    kw, price, dep = float(b.get("kw") or 0), float(b.get("price_usd_per_kwh") or 0), float(b.get("deposit_usd") or 0)
    sh.ev.order(sh.name(buyer), kw, b.get("start"), b.get("end"), price, dep)
    hours = max(0.0, (when(f"2000-01-01 {b.get('end')}") - when(f"2000-01-01 {b.get('start')}")).total_seconds() / 3600)
    ans = post.get("answer") or {}
    key = "order_utility_kw" if buyer == "utility" else "order_grid_operator_kw"
    sh.held["asked"] = round(float(sh.held.get("asked") or 0) + kw, 3)
    return sh.step(ROWS["order"], tq, wall, frm=buyer, to="community", Buyer=N.name_of(sh.name(buyer), True), kw=n1(kw),
                   start=b.get("start"), end=b.get("end"), date=b.get("date"), price=n2(price), deposit=n2(dep),
                   values={key: kw, "price_usd_per_kwh": price, "deposit_usd": dep, "asked_kw": [sh.held["asked"]]},
                   lines=[T("in", f"place_order({J({k: b.get(k) for k in ('date', 'start', 'end', 'kw', 'price_usd_per_kwh', 'deposit_usd')})})"),
                          T("calc", f"worth if delivered in full: {n2(kw)} kW x {n1(hours)} h x ${n2(price)}/kWh = {usd(kw * hours * price)}"),
                          T("out", f"order {ans.get('event_id')}: placed at {hm(ans.get('placed_at'))}, status {post.get('status')}")])


# ---------------------------------------------------------------- the sale's snapshots
def snapshot(sh: Shaping, trigger: list[str] | str, ev: dict[str, Any], tq: int, wall: float) -> list[Step]:
    sh.snap = ev
    marks = [trigger] if isinstance(trigger, str) else list(trigger or [])
    out: list[Step] = []
    if "select" in marks:
        out += sh.shaped(BOOK_ROWS["offers"], ev, tq, wall, offers_in, sh, ev, tq, wall, kind="offers")
        out += sh.shaped(BOOK_ROWS["book"], ev, tq, wall, book, sh, ev, tq, wall, kind="book")
    if "telemetry_done" in marks:
        out += sh.shaped(BOOK_ROWS["readings"], ev, tq, wall, readings_in, sh, ev, tq, wall, kind="readings")
    if "settlement" in marks or "done" in marks:
        out += sh.shaped(BOOK_ROWS["pay"], ev, tq, wall, settled, sh, ev, tq, wall, kind="pay")
    return out


BOOK_ROWS = {
    "offers": Row("offers-in", "offers", "market", "All offers are in",
                  "{homes} and {buildings} offered. {firm} kW are firm and {tent} kW tentative in the fullest half hour.", True, True, "co-market"),
    "book": Row("book", "clearing", "coordinator", "The book: firm first, then what deposits hold",
                "In the fullest half hour {sold} of the {asked} kW ordered are sold.", True, True, "co-market"),
    "reserve": Row("book", "clearing", "coordinator", "The reserve: what the nodes are asked for",
                   "The nodes are asked for {nodes} kW in the fullest half hour: the {sold} kW sold plus a reserve of {reserve} kW.", False, False, "co-market"),
    "cover": Row("book", "clearing", "coordinator", "The community agent holds back a cover",
                 "The community promises {share} of what its members offered, by {by}, in case they deliver less.", False, False, "co-cover"),
    "limit": Row("book", "clearing", "coordinator", "The utility's limit at the connection is checked",
                 "Each half hour sold is checked against the most the community may send out at its connection: {cut}.", False, False, "co-market"),
    "readings": Row("readings", "readings", "coordinator", "Readings are in",
                    "{got} signed readings are in, of {due} due. Each is checked before anything is paid.", False, True, "r-check"),
    "pay": Row("pay", "settlement", "market", "The coordinator works out each node's pay",
               "Everything is worked out before anything is paid: nodes get {pool}. Of the rest of the bill, {fee} is kept.", True, True, "r-pay"),
}


def kw_at(offer: dict[str, Any], i: int) -> float:
    """What one node's offer holds for half hour i."""
    return float(next((s.get("kw_offered") for s in offer.get("slots") or [] if s.get("id") == i), 0) or 0)


def offers_in(sh: Shaping, ev: dict[str, Any], tq: int, wall: float) -> list[Step]:
    offers, pooled = ev.get("offers") or {}, ev.get("pooled_offer") or {}
    homes = [n for n in offers if N.is_home(sh.name(n))]
    firm, tent = slots(pooled.get("firm_kw")), slots(pooled.get("tentative_kw"))
    total = [round(a + b, 3) for a, b in zip(firm, tent)]
    by_kind = [[round(sum(kw_at(o, i) for n, o in offers.items() if (n in homes) == side), 2) for i in range(len(total))]
               for side in (True, False)]
    top = max(range(len(total)), key=total.__getitem__) if total else 0
    rows = [[sh.ev.ledger["half_hours"][i]["start"] if i < len(sh.ev.ledger["half_hours"]) else str(i), n1(by_kind[0][i]), n1(by_kind[1][i]),
             n1(firm[i]), n1(tent[i])] for i in range(len(total))]
    return sh.step(BOOK_ROWS["offers"], tq, wall, frm="all nodes", to="community", homes=pl(len(homes), "home"),
                   buildings=pl(len(offers) - len(homes), "building"), firm=n1(firm[top] if firm else 0), tent=n1(tent[top] if tent else 0),
                   lines=[T("in", f"{pl(len(offers), 'offer')}: {pl(len(homes), 'home')}, {pl(len(offers) - len(homes), 'building')}.")] +
                   [T("calc", x) for x in table(["half hour", "homes kW", "buildings kW", "firm kW", "tentative kW"], rows)],
                   values={"offers_in": len(offers), **{k: [round(xs[top], 3)] if xs else [] for k, xs in (
                       ("offered_kw", total), ("offered_homes_kw", by_kind[0]), ("offered_buildings_kw", by_kind[1]), ("offered_firm_kw", firm),
                       ("offered_tentative_kw", tent))}})


def book(sh: Shaping, ev: dict[str, Any], tq: int, wall: float) -> list[Step]:
    cs = ev.get("clear_summary") or {}
    sold, asked = slots(cs.get("capacity_offered_kw")), slots(cs.get("requested_kw"))
    alloc = ev.get("alloc") or {}
    nodes = [round(sum(float(a.get(str(i)) or 0) for a in alloc.values()), 3) for i in range(len(sold))]
    reserve = [round(max(0.0, x - y), 3) for x, y in zip(nodes, sold)]
    top = max(range(len(sold)), key=sold.__getitem__) if sold else 0
    halves = [h["start"] for h in sh.ev.ledger.get("half_hours") or []]
    rows = [[halves[i] if i < len(halves) else str(i), n1(asked[i] if i < len(asked) else 0), n1(sold[i]), n1(nodes[i])] for i in range(len(sold))]
    cover, limit = ev.get("cover") or {}, ev.get("connection_limit") or {}
    cut = "nothing had to be cut" if not limit.get("cut") else f"cut in {pl(len(limit['cut']), 'half hour')}"
    one = lambda xs: xs[top] if xs else 0          # noqa: E731  the fullest half hour's figure
    return [sh.step(BOOK_ROWS["book"], tq, wall, frm="community", sold=n1(one(sold)), asked=n1(one(asked)),
                    lines=[T("note", "The book fills each order from firm power first, in proportion to the orders' size. The rest comes from "
                                     "tentative power, as far as each deposit holds it.")] +
                    [T("calc", x) for x in table(["half hour", "ordered", "sold", "asked of nodes"], rows)],
                    values={"sold_kw": [one(sold)], "asked_kw": [one(asked)]}),
            sh.step(BOOK_ROWS["reserve"], tq, wall, frm="community", nodes=n1(one(nodes)), sold=n1(one(sold)), reserve=n1(one(reserve)),
                    lines=[T("calc", f"asked of nodes, kW per half hour: {J(nodes)}"), T("calc", f"reserve, kW per half hour: {J(reserve)}")],
                    values={"asked_of_nodes_kw": [one(nodes)], "reserve_kw": [one(reserve)]}),
            sh.step(BOOK_ROWS["cover"], tq, wall, frm="community", share=f"{float(cover.get('share') or 0) * 100:.1f}%",
                    by=str(cover.get("by") or "its record"),
                    lines=[T("calc", f"finished evenings on its record when this sale is cleared: {cover.get('sales_on_record', 0)}"),
                           T("calc", f"share of the offers it promises: {float(cover.get('share') or 0) * 100:.1f}%, from {cover.get('by')}")]),
            sh.step(BOOK_ROWS["limit"], tq, wall, frm="community", cut=cut,
                    lines=[T("calc", f"the most it may send out: {n1(limit.get('limit_out_kw') or 0)} kW"),
                           T("calc", f"half hours checked: {limit.get('checked', 0)}; cut: {len(limit.get('cut') or {})}")])]


def readings_in(sh: Shaping, ev: dict[str, Any], tq: int, wall: float) -> Step:
    got = sum(len(v) for v in (ev.get("readings") or {}).values())
    due = sum(len(v) for v in (ev.get("alloc") or {}).values())
    done = ev.get("telemetry_done") or {}
    due = int(done.get("readings", 0)) + len(done.get("missing") or ()) if done else due
    return sh.step(BOOK_ROWS["readings"], tq, wall, frm="community", got=got, due=due,
                   lines=[T("in", f"{pl(got, 'signed reading')} from {pl(len(ev.get('readings') or {}), 'node')}")],
                   values={"readings_in": got, "readings_expected": due})


def settled(sh: Shaping, ev: dict[str, Any], tq: int, wall: float) -> list[Step]:
    r = ev.get("result") or {}
    split = r.get("split") or {}
    if not split:
        return []
    per = split.get("per_home") or {}
    homes = round(sum(float(v) for k, v in per.items() if N.is_home(sh.name(k))), 4)
    builds = round(sum(float(v) for k, v in per.items() if N.is_building(sh.name(k))), 4)
    buyers = r.get("by_buyer") or {}
    sh.ev.totals({b: {"placed_usd": (x.get("deposit") or {}).get("held_usd")} for b, x in buyers.items()},
                 sum(float(x.get("sold_kwh") or 0) for x in buyers.values()), r.get("delivered_kwh_measured"))
    return sh.step(BOOK_ROWS["pay"], tq, wall, frm="community", to="all nodes", pool=usd(split.get("pool") or 0), fee=usd(split.get("fee") or 0),
                   lines=[T("calc", f"all buyers pay {usd(sum(float(x.get('paid_usd') or 0) for x in buyers.values()))}. {split.get('rule', '')}"[:600])] +
                   [T("calc", f"{k}: paid {usd(v)}") for k, v in per.items()] +
                   [T("out", f"the meters show {n2(r.get('delivered_kwh_measured') or 0)} kWh delivered; the seller is paid {usd(r.get('seller_usd') or 0)}")],
                   values={"paid_usd": split.get("pool"), "paid_homes_usd": homes, "paid_buildings_usd": builds, "coordinator_keep_usd": split.get("fee"),
                           "buyer_utility_usd": (buyers.get("utility") or {}).get("paid_usd"),
                           "buyer_grid_operator_usd": (buyers.get("grid-operator") or {}).get("paid_usd")})


# ---------------------------------------------------------------- the window, half hour by half hour
DELIVERY = Row("window", "delivery", "device", "Delivery, {start} to {end}",
               "From {start} the community runs {all} kW below what it would have used: {homes} kW from homes and {buildings} kW from buildings.",
               True, True, "h-dev")


def delivery(sh: Shaping, rows: list[dict[str, Any]], now: str, tq: int, wall: float) -> list[Step]:
    """The window's half hours that the meter holds whole and the clock has left, each once."""
    for r in rows:
        sh.meter[str(r.get("ts"))[:16]] = r
    out: list[Step] = []
    w0, w1 = sh.window
    if not w0:
        return out
    at = when(w0)
    while at < when(w1):
        a, b, end = at.strftime("%Y-%m-%d %H:%M"), (at + QUARTER).strftime("%Y-%m-%d %H:%M"), at + 2 * QUARTER
        if a in sh.meter and b in sh.meter and str(now)[:16] >= end.strftime("%Y-%m-%d %H:%M") and sh.once("delivery", a):
            out += sh.shaped(DELIVERY, sh.meter[a], tq, wall, half_hour, sh, a, b, end.strftime("%H:%M"), tq, wall, kind="delivery")
        at = end
    return out


def half_hour(sh: Shaping, a: str, b: str, end: str, tq: int, wall: float) -> Step:
    h = round((float(sh.meter[a]["homes_kw"]) + float(sh.meter[b]["homes_kw"])) / 2, 1)
    g = round((float(sh.meter[a]["buildings_kw"]) + float(sh.meter[b]["buildings_kw"])) / 2, 1)
    return sh.step(DELIVERY, tq, wall, frm="all nodes", sim_time=a, start=a[11:16], end=end, all=n1(h + g), homes=n1(h), buildings=n1(g),
                   lines=[T("calc", f"kW below the no-sale twin, mean of the two 15-minute steps: homes {n1(h)}, buildings {n1(g)}, all {n1(h + g)}"),
                          T("note", "The twin is the same node with no sale, which only the simulator knows. The meter counts what each member "
                                    "draws against it.")],
                   values={"live_kw": round(h + g, 1), "live_homes_kw": h, "live_buildings_kw": g})
