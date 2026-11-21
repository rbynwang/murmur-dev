"""How a recorded evening's steps group into moments, and which box of the map each step and each terminal line belongs to.

A moment is one idea a first-time viewer can follow. Its rule picks its steps by stage, layer, title, node and time, never by
position. Rules run in table order and the first match wins, except that a moment marked `first` looks before the others.
key picks the steps its terminal shows, say the step whose sentence explains it (and pick which sentence), big and cap the
number or decision that matters: a {name} in them takes a figure from the recording. path is the one message's way along the
map's lines; side_path runs along the branch of the node it is about (h- or b-).
"""
from __future__ import annotations

import re
from typing import Any, Callable

from .. import names as N

Step = dict[str, Any]
Rule = Callable[[Step, dict[str, Any]], bool]


def st(*names: str) -> Rule:
    return lambda s, c: s.get("stage") in names


def ly(*names: str) -> Rule:
    return lambda s, c: s.get("layer") in names


def ti(pat: str) -> Rule:
    r = re.compile(pat, re.I)
    return lambda s, c: bool(r.search(str(s.get("title") or "")))


def nd(*who: str) -> Rule:
    """home, code and second are the recording's followed nodes; building is any building."""
    def rule(s: Step, c: dict[str, Any]) -> bool:
        n = str(s.get("node") or "")
        return any(N.is_building(n) if w == "building" else n == c.get(w) for w in who)
    return rule


def at(lo: str | None = None, hi: str | None = None) -> Rule:
    """The step's clock on the evening's day. Anything the day before counts as before the day starts."""
    def rule(s: Step, c: dict[str, Any]) -> bool:
        t = str(s.get("sim_time") or "")
        hm = t[11:16] if t[:10] >= str(c.get("day") or "") else "00:00"
        return (lo is None or hm >= lo) and (hi is None or hm <= hi)
    return rule


def allof(*rs: Rule) -> Rule:
    return lambda s, c: all(r(s, c) for r in rs)


def anyof(*rs: Rule) -> Rule:
    return lambda s, c: any(r(s, c) for r in rs)


class Mo:
    """One moment of the story."""

    def __init__(self, id: str, title: str, rule: Rule, key: str, say: str = "", pick: int = 0, big: str = "", cap: str = "",
                 path: tuple[str, ...] = (), side_path: tuple[str, ...] = (), trade: tuple[str, ...] = (), also: tuple[str, ...] = (),
                 carry: str = "", note: str = "", block: str = "", gap: str = "", alt: tuple[str, str] | None = None,
                 first: bool = False, opt: bool = False):
        self.id, self.title, self.rule, self.key, self.say, self.pick = id, title, rule, key, say or key, pick
        self.big, self.cap, self.path, self.side_path, self.trade, self.also = big, cap, path, side_path, trade, also
        self.carry, self.note, self.block, self.gap, self.alt = carry, note, block, gap, alt
        self.first, self.opt = first, opt or first


CHAIN_ANY = "^Guard|^Seal and write|takes the write"
OPENING = "Step 7: code's opening"
CODE_NOTE = "Code makes this decision, and its receipt says so. No model is asked for a plan."
SIDE_PLAN = ("agent", "tools", "guard", "seal", "driver", "dev")
SIDE_PARTS = ("agent", "model", "tools", "guard", "seal", "driver", "dev", "person")
HOME_CHAIN = ("h-agent", "h-tools", "h-guard", "h-seal", "h-driver", "h-dev")
BLD_CHAIN = ("b-agent", "b-tools", "b-guard", "b-seal", "b-driver", "b-dev")
PAY_CAP_YEAR = "to sellers. The coordinator keeps {keep}"


def _start() -> list[Mo]:
    return [
        Mo("orders", "Two buyers order the same evening", allof(st("order"), ly("buyer")), key="places its order", say="utility places",
           big="{asked}", cap="asked for each half hour, {window}", trade=("util_kw", "grid_kw", "price", "deposits"), gap="no_ceiling"),
        Mo("ask", "Both orders join one sale", st("order"), key="answers with its order|joins the same sale", say="joins the same sale",
           big="One pool", cap="a meter can't be sold twice", path=("buy-u", "town", "co-market"), trade=("asked", "price", "window"),
           carry="signed order", gap="town_not_live"),
        Mo("call", "One call goes to every member", allof(st("offers"), ti("call for offers goes|own forecast")),
           key="call for offers goes|own forecast", say="call for offers goes", pick=1, big="{members}", cap="members called",
           path=("co-market", "town"), trade=("asked", "window"), also=("h-agent", "b-agent"), carry="call for offers"),
        Mo("home-safe", "A home's code works out what it can safely sell",
           allof(st("offers"), nd("home"), ti("call reaches|Steps 1 to 4|safe offer")), key="Steps 1 to 4|safe offer",
           say="Steps 1 to 4", pick=1, big="{home_safe}", cap="the planner's safe figure. The offer is made from it",
           path=("town", "h-agent"), trade=("home_firm", "home_tent"), carry="call for offers"),
        Mo("home-model", "Code makes the home's offer", allof(st("offers"), nd("home")), key="Step 5|sends its offer", say="Step 5",
           big="{home_offer}", cap="offered. The safe figure: {home_safe}", path=("h-agent", "town", "co-market"),
           trade=("home_safe", "home_offer"), carry="offer", note=CODE_NOTE),
        Mo("code-home", "A second home's code offers the same way", allof(st("offers"), nd("code", "second")),
           key="Step 5|sends its offer", say="Step 5", big="{second_offer}", cap="offered. Its safe figure: {second_safe}",
           path=("town", "h-agent", "town"), trade=("second_safe", "second_offer"), carry="call, then offer", opt=True),
        Mo("bld-offer", "Buildings offer the same way", allof(st("offers"), nd("building")), key="Step 5|checks the model|sends its offer",
           say="sends its offer", big="{uni_offer}", cap="offered by the university", path=("town", "b-agent", "town"),
           trade=("uni_offer", "other_offer"), carry="call, then offer", block="b-agent", opt=True),
        Mo("offers-in", "All offers are in", ti("All offers are in|working starts|Offers by kind|Second round"),
           key="All offers|Offers by kind|Second round", say="All offers", pick=1, big="{offered}", cap="offered, for {asked} asked",
           path=("town", "co-market"), trade=("offers", "firm", "tent", "off_h", "off_b"), carry="offers", gap="second_round_idle"),
        Mo("reserve", "One number is set: the reserve", ti("picks the reserve|reserve is set"), key="picks the reserve|reserve is set",
           say="reserve is set", big="{margin}", cap="asked of the nodes beyond what is sold", trade=("asked", "offered"),
           carry="short sheet"),
        Mo("book", "The book fills the order", ti("The book|The reserve: what|move the peak|deposits still hold"),
           key="The book|The reserve: what|deposits still hold", say="The book", big="{sold}", cap="sold, firm power first",
           trade=("reserve", "nodes", "dep_back", "dep_held")),
        Mo("cover", "The community agent holds back a cover", ti("holds back a cover"), key="holds back a cover", big="{sold}",
           cap="promised upward, less than its members offered", trade=("reserve",), block="co-cover", first=True),
        Mo("limit", "The utility's limit at the connection is checked", ti("limit at the connection is checked"),
           key="limit at the connection", big="Nothing cut", cap="every half hour sold is inside the limit", block="utl", first=True),
        Mo("split", "Homes against buildings", ti("Homes against buildings"), key="Homes against buildings", pick=1, big="Not a decision",
           cap="the split follows the offers", trade=("ask_h", "ask_b", "off_h", "off_b"), also=("h-agent", "b-agent"),
           gap="no_split_choice", opt=True),
        Mo("buyer-contract", "Each buyer signs",
           allof(st("contract"), ti("takes the order|drafts|names the meters|accepts the terms|coordinator confirms|contract is active")),
           key="names the meters|contract is active", say="contract is active", big="{sold}", cap="under contract, at {price}",
           path=("co-market", "town", "buy-u"), trade=("nodes", "reserve"), carry="contract"),
        Mo("node-contract", "Every node gets a contract. Its code answers",
           allof(st("contract"), ti("Each node gets|contract reaches|Step 6|says ACCEPTED|Nobody is told")),
           key="Each node gets|contract reaches|Step 6|says ACCEPTED", say="Each node gets", pick=1, big="{members}",
           cap="contracts, one per node", path=("co-market", "town", "h-agent"), trade=("c_home", "c_code", "c_uni", "c_other"),
           carry="contract", gap="opt_out_unseen"),
        Mo("frozen", "The deal is frozen", st("contract"), key="deal is frozen|final list|Baselines", say="Baselines", big="{accepted}",
           cap="accepted, {declined} declined. Baselines come first", path=("co-market", "town", "buy-u"), trade=("sold", "reserve"),
           carry="final list"),
        Mo("precool", "Morning: code sets the pre-cool", allof(st("prepare"), at(None, "13:59")), key="pre-cool|" + CHAIN_ANY,
           say="pre-cool", big="Guard says {guard}", cap="code's pre-cool call, as the guard answered it", side_path=SIDE_PLAN,
           trade=("nodes", "reserve"), carry="device call", alt=("No pre-cool", "code makes no call this morning"), opt=True),
        Mo("desk-day", "Afternoon: a shortfall reaches the desk",
           anyof(allof(st("exception"), at("12:00", "17:29")), allof(st("prepare"), ly("device"), at("12:00", "17:29"))),
           key="tells the desk|adds up|prepares itself", say="adds up", big="{short_now}", cap="reported short",
           side_path=("agent", "town", "co-desk"), trade=("reserve",), carry="shortfall"),
        Mo("ask-refused", "A request the batteries can't meet is refused", ti("can't meet"), key="can't meet",
           say="refuses the request", big="Refused", cap="in writing, and nothing changes: a request is not an order",
           carry="signed request", block="co-agent", first=True),
        Mo("agg-clean", "The aggregator cleans the grid's readings", ti("cleans the grid's readings"), key="cleans the grid's readings",
           big="{agg_watch}", cap="the transformer its plan watches. Noise and glitches are taken out first", block="agg-clean",
           first=True),
        Mo("agg-share", "The need is shared out among all the batteries", ti("need is shared out"), key="need is shared out",
           big="{agg_asked}", cap="asked of its members' batteries at 19:00, their part of the whole need",
           path=("agg-clean", "agg-share", "mkt"), carry="who is asked", block="agg-share", first=True),
        Mo("battery-ask", "The aggregator asks the members' batteries", ti("asks the members' batteries|request for the batteries"),
           key="asks the members' batteries|takes the request", say="takes the request", big="Taken",
           cap="a signed request, and the community agent answers for its members", carry="signed request", block="co-agent",
           first=True),
    ]


def _sites_ask() -> list[Mo]:
    return [
        Mo("site-ask", "The aggregator asks single sites too", ti("aggregator asks a"), key="aggregator asks a", big="{site_asked}",
           cap="{site_ask_cap}", carry="signed request", block="site-pv", first=True),
        Mo("site-words", "A site answers in words", ti("answers in words"), key="answers in words", big="{site_notes}",
           cap="{site_notes_cap}", carry="a person's note", block="site-pv", first=True),
        Mo("site-answer", "Each site answers for itself", ti("answers for itself"), key="answers for itself", big="Taken",
           cap="{site_ans_cap}", carry="signed answer", block="site-dc", first=True),
    ]


def _evening() -> list[Mo]:
    return [
        Mo("watch-bld", "Code opens the building's devices", allof(st("prepare"), nd("building")), key=OPENING + "|" + CHAIN_ANY,
           say=OPENING, big="{calls_uni}", cap="device calls at the university, {calls_other} at {other_place}", path=BLD_CHAIN,
           trade=("owed_uni", "calls_uni", "calls_other"), carry="device call", opt=True),
        Mo("watch-home", "The same in a home", st("prepare"), key=OPENING + "|" + CHAIN_ANY, say=OPENING, big="{calls_home}",
           cap="device calls at this home", path=HOME_CHAIN, trade=("owed_home", "calls_home"), carry="device call", block="h-agent",
           gap="devices_simulated"),
        Mo("told", "The person is told in plain words", ti(r"(?:manager|owner) is told"), key="is told", big="In plain words",
           cap="the person hears why the node gave less", side_path=("agent", "person"), carry="plain words", gap="opt_out_unseen",
           first=True),
        Mo("window", "The sale runs", st("delivery"), key=r"What reaches a person|Nothing reaches a person|Delivery, \d\d:\d\d",
           say=r"Delivery, \d\d:\d\d", big="{hh0}", cap="below the no-sale twin in the first half hour",
           trade=("hh0", "hh1", "hh2", "hh3", "hh4", "hh5"), also=("h-person", "b-person"), gap="blind_in_window"),
        Mo("community-report", "The community reports upward", ti("community's report upward"), key="community's report upward",
           big="No member named", cap="one signed row for each quarter hour, in the layout ENGIE's participants send",
           carry="signed report row", block="co-report", first=True),
        Mo("exc-model", "Something changed. Code answers",
           allof(st("exception"), ti("Step 8: code's answer|carries out its own plan|^Tool:")),
           key="Step 8: code's answer|carries out its own plan", say="Step 8: code's answer", big="Code answers",
           cap="no model is asked: the receipt says so", carry="what changed", note=CODE_NOTE),
        Mo("exc-code", "The plan goes through the guard", st("exception"), key=CHAIN_ANY + "|tells the desk|desk's evening",
           say="^Guard:", big="Guard says {guard}", cap="each call is checked before it runs", side_path=SIDE_PLAN,
           trade=("reports", "rounds", "warnings"), carry="device call", block="{side}-guard"),
        Mo("report", "The small model words the report", st("report"), key=r"Step 9: the model|sends its report|The report for",
           say="Step 9: the model", big="No one reads it", cap="it stays beside the sale",
           side_path=("agent", "model", "agent", "town", "co-market"), carry="labelled report", gap="reports_unread"),
        Mo("agg-ref", "The referee checks every report row", ti("referee checks"), key="referee checks", big="{agg_trusted}",
           cap="report rows trusted. Nothing is held back from settlement", path=("mkt", "agg-ref"), carry="report rows",
           block="agg-ref", first=True),
    ]


def _sites_report() -> list[Mo]:
    return [
        Mo("site-pause", "A data center pauses work that can wait", ti("pauses work that can wait"), key="pauses work that can wait",
           big="{site_paused}", cap="{site_pause_cap}", carry="work to pause", block="site-dc", first=True),
        Mo("site-report", "The sites report upward", ti("reports upward, for itself"), key="reports upward, for itself",
           big="{site_rows}", cap="{site_rep_cap}", carry="signed report row", block="site-pv", first=True),
    ]


def _end(sites: bool) -> list[Mo]:
    return [
        Mo("readings", "Signed readings come in", st("readings"), key="sends its readings|Readings are in", say="Readings are in",
           pick=1, big="{readings}", cap="readings in, {refused} refused", path=("h-dev", "r-read", "r-check"),
           trade=("meters", "readings", "refused"), also=("town",), carry="signed readings"),
        Mo("settle", "Buyers settle on the meters", allof(st("settlement"), anyof(ly("buyer"), ti("settlement goes"))),
           key="counts each meter|settles", say="counts each meter", big="{buyers_pay}", cap="buyers pay for {delivered} on the meters",
           path=("r-check", "r-settle"), trade=("sold_kwh", "delivered", "pay_u", "pay_g"), carry="settlement"),
        Mo("pay", "Pay is worked out", st("settlement"), key="works out each node|told its pay|No payment", say="works out each node",
           big="{sellers}", cap="{pay_cap}" if sites else PAY_CAP_YEAR, path=("r-settle", "r-pay"),
           trade=("buyers_pay", "homes_usd", "bld_usd", "keep", "dep_held"), carry="pay notice", gap="no_money_moves"),
        Mo("community-record", "The evening goes onto the community's record", ti("writes the evening on its record"),
           key="writes the evening on its record", big="Its next cover", cap="is taken from what it delivered tonight", block="co-cover",
           first=True),
    ]


def table(sites: bool) -> list[Mo]:
    """The moments of an evening, in the story's order: with single sites, their own moments stand among the community's."""
    return _start() + (_sites_ask() if sites else []) + _evening() + (_sites_report() if sites else []) + _end(sites)


def side(s: Step) -> str:
    return "b" if N.is_building(s.get("node")) else "h"


def block_of(s: Step) -> list[str]:
    """The boxes a step belongs to, before line_blocks() splits a step whose lines cross more than one."""
    lay, stage, title, node, frm = (s.get("layer"), s.get("stage"), str(s.get("title") or ""), str(s.get("node") or ""),
                                    str(s.get("from") or ""))
    if lay == "buyer":
        if frm == "aggregator":
            for pat, b in (("cleans the grid's readings", "agg-clean"), ("need is shared out", "agg-share"), ("referee checks", "agg-ref")):
                if re.search(pat, title):
                    return [b]
            return ["mkt"]
        if stage == "settlement":
            return ["r-settle"]
        return ["buy-g" if frm.startswith("grid") or str(s.get("to") or "").startswith("grid") else "buy-u"]
    if lay in ("market", "coordinator"):
        return [_community_block(stage, title)]
    if lay == "model":
        return [f"{side(s)}-model"]
    if lay in ("home_agent", "building_agent"):
        return ["h-agent" if lay == "home_agent" else "b-agent"]
    if lay in ("guard", "driver"):
        return [f"{side(s)}-{lay}"]
    if lay == "device":
        return [f"{side(s)}-dev"] if node else ["h-dev", "b-dev"]
    return [f"{side(s)}-person"] if node else ["h-person", "b-person"]


def _community_block(stage: Any, title: str) -> str:
    """The box of a community agent's step, or of a single site's own step (which the record keeps on the same layers)."""
    if "solar-and-battery plant" in title:
        return "site-pv"
    if "data center" in title:
        return "site-dc"
    if re.search(r"holds back a cover|writes the evening on its record", title):
        return "co-cover"
    if "report upward" in title:
        return "co-report"
    if stage == "readings":
        return "r-check"
    if stage == "settlement":
        return "r-pay"
    if re.search(r"desk|dispatch|evening", title, re.I):
        return "co-desk"
    if "forecast" in title:
        return "co-fc"
    if re.search(r"\brequest\b", title):
        return "co-agent"
    return "co-market"


def receiver(s: Step) -> str:
    """Which box reads what comes out of an envelope. Town itself reads nothing."""
    to, title, stage = str(s.get("to") or ""), str(s.get("title") or ""), s.get("stage")
    if stage == "readings":
        return "r-read"
    if stage == "settlement":
        return "r-settle" if "settlement" in title else "r-pay"
    if to == "aggregator":
        return "mkt"
    if to == "coordinator" and str(s.get("from") or "") == "aggregator":
        return "co-agent"
    if to == "coordinator":
        return "co-desk" if re.search(r"desk|call travels", title) else "co-market"
    if to == "utility":
        return "buy-u"
    return "b-agent" if N.is_building(to) else "h-agent"


def line_blocks(s: Step, kind: str, text: str) -> list[str]:
    """The box a terminal line belongs to. Town shows an envelope's outside and the receiver shows what came out of it; a guard
    step's first lines are the tool server's; a driver step's signature is the seal's; a delivery step's rows go to each side."""
    lay, title = s.get("layer"), str(s.get("title") or "")
    if "limit at the connection" in title and text.startswith("the most it may send out"):
        return ["utl"]
    if lay == "town":
        if kind in ("out", "note") and "report upward" in title:
            return ["co-report"]
        return [receiver(s)] if kind == "in" else ["town"]
    if lay == "guard" and (kind == "tool" or text.startswith(("run_call", "policy"))):
        return [f"{side(s)}-tools"]
    if lay == "driver" and kind == "sign":
        return [f"{side(s)}-seal"]
    if lay == "device" and not s.get("node"):
        if N.is_home(text):
            return ["h-dev"]
        if N.is_building(text):
            return ["b-dev"]
    return block_of(s)


def on_side(parts: tuple[str, ...], sd: str) -> tuple[str, ...]:
    return tuple(f"{sd}-{x}" if x in SIDE_PARTS else x for x in parts)


def path_of(mo: Mo, s: Step) -> tuple[str, ...]:
    """The moment's path: side_path takes the side of the node step s belongs to."""
    return on_side(mo.side_path, side(s)) if mo.side_path else mo.path


def place(steps: list[Step], table: list[Mo], ctx: dict[str, Any], drawn: set[tuple[str, str]]) -> tuple[list[Mo], list[list[int]]]:
    """The moments that have steps in this recording, and each one's steps. A step no moment takes, a moment that must have
    steps and has none, or a path off the map's drawn lines stops the build: the page would tell a story that is not there."""
    groups: list[list[int]] = [[] for _ in table]
    order = [k for k, m in enumerate(table) if m.first] + [k for k, m in enumerate(table) if not m.first]
    for i, s in enumerate(steps):
        hit = next((k for k in order if table[k].rule(s, ctx)), None)
        if hit is None:
            raise ValueError(f"no moment takes step {i}: {s.get('title')!r}")
        groups[hit].append(i)
    empty = [m.id for m, g in zip(table, groups) if not g and not m.opt]
    if empty:
        raise ValueError(f"moments with no steps: {empty}")
    off = [m.id for m in table for p in (m.path, on_side(m.side_path, "h"), on_side(m.side_path, "b"))
           for a, b in zip(p, p[1:]) if (a, b) not in drawn]
    if off:
        raise ValueError(f"moments whose path leaves the map's lines: {off}")
    keep = [(m, g) for m, g in zip(table, groups) if g]
    return [m for m, _ in keep], [g for _, g in keep]
