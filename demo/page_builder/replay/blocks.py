"""The map: its boxes, what each one is, the lines between them, and the stages of the phone's strip.

A box is (id, name on the map, hue, tag, a few words). The aggregator's four parts and the two buyers stand on top, the
community agent's six parts under them, NANDA Town, then a home's and a building's branch and the return path. An evening
with single sites adds a solar-and-battery plant and a data center beside the community; a year set's evenings have none.
"""
from __future__ import annotations

SITE_BLOCKS = ("site-pv", "site-dc")
BLOCKS = [
    ("agg-clean", "Reading cleaner", "c1", "ML", "Takes noise out of the grid's readings"),
    ("agg-share", "Sharing-out", "c1", "CODE", "Who is asked, and for how much"),
    ("mkt", "Request agent", "c1", "CODE", "Sends each its request, signed"),
    ("agg-ref", "Referee", "c1", "CODE · AI", "Checks reports. AI reads their words"),
    ("utl", "The utility", "c1", "", "Sets the most the community may send out"),
    ("buy-u", "Buyer: utility", "c1", "", "Orders the cut, and pays for it"),
    ("buy-g", "Buyer: grid operator", "c1", "", "Same evening, same pool"),
    ("co-fc", "Community forecast", "c2", "ML", "Its homes' demand"),
    ("co-cover", "Promise and cover", "c2", "", "Promises less than offered"),
    ("co-agent", "Members' batteries", "c2", "", "Their own, held for the peak"),
    ("co-market", "Day-ahead clearing", "c2", "", "Book and contracts"),
    ("co-desk", "Gap filling", "c2", "", "Covers a shortfall"),
    ("co-report", "Verify and report", "c2", "", "One row a quarter hour"),
    ("site-pv", "Solar-and-battery plant", "c2", "", "Holds for the peak"),
    ("site-dc", "Data center", "c2", "", "Less at the peak"),
    ("town", "NANDA Town", "c3", "", "Carries signed envelopes. Reads nothing inside"),
    ("h-agent", "Home agent", "c4h", "", "Code makes each plan, with a receipt"),
    ("h-model", "Small model", "mdl", "AI", "Reads the owner's note. Words the report"),
    ("h-tools", "Tool server", "c5", "", "Every device call starts here"),
    ("h-guard", "Guard", "c5", "", "Checks every call. Has the last word"),
    ("h-seal", "Seal", "c5", "", "One use, exactly what passed"),
    ("h-driver", "Driver", "c5", "", "Sends each checked call"),
    ("h-dev", "Devices", "c6", "HARDWARE", "Battery, car, cooling, hot water"),
    ("h-person", "Home owner", "c7", "", "Writes in. Told when it gives less"),
    ("b-agent", "Building agent", "c4b", "", "Code makes each plan, by zone"),
    ("b-model", "Small model", "mdl", "AI", "Reads the manager's note. Words the report"),
    ("b-tools", "Tool server", "c5", "", "Every device call starts here"),
    ("b-guard", "Guard", "c5", "", "Checks every call. Has the last word"),
    ("b-seal", "Seal", "c5", "", "One use, exactly what passed"),
    ("b-driver", "Driver", "c5", "", "Sends each checked call"),
    ("b-dev", "Devices", "c6", "HARDWARE", "Cooling, air, lights, plugs"),
    ("b-person", "Building manager", "c7", "", "Writes in. Told when it gives less"),
    ("r-read", "Readings", "cr", "", "Signed by each node"),
    ("r-check", "Checks", "cr", "", "At every door"),
    ("r-settle", "Settlement", "cr", "", "On what meters show"),
    ("r-pay", "Payment", "cr", "", "By delivery, on record"),
]
_NAMES = {b[0]: b[1] for b in BLOCKS}
FULL_NAME = {**_NAMES,
             "co-fc": "The community agent's forecast", "co-cover": "The community agent's promise and cover",
             "co-agent": "The members' batteries", "co-market": "The community agent's day-ahead clearing",
             "co-desk": "The community agent's gap filling", "co-report": "The community agent's report upward",
             "site-pv": "A solar-and-battery plant's own agent", "site-dc": "A data center's own agent",
             "h-model": "Small model, for a home", "h-tools": "Tool server, home", "h-guard": "Guard, home", "h-seal": "Seal, home",
             "h-driver": "Driver, home", "h-dev": "Home devices", "b-model": "Small model, for a building",
             "b-tools": "Tool server, building", "b-guard": "Guard, building", "b-seal": "Seal, building",
             "b-driver": "Driver, building", "b-dev": "Building devices"}
_GUARD = ("Six checks on every device call: safety and money limits, and what a person asked to keep. It checks and never plans, "
          "and it has the last word. A blocked call comes back with its reason. Below is its real run, branch by branch.")
_TOOLS = "Shows only this step's tools, the rule's own plan among them. Policy says who may do what, and denies by default."
ABOUT = {
    "agg-clean": "The aggregator's first part. The grid's own transformer readings carry noise and glitches, so each hour's readings are rebuilt from the patterns the whole grid shares, before any plan is made. A fitted model.",
    "agg-share": "The aggregator's second part, by code. From the loading it expects, it works out how much must be given in each hour to keep every transformer under 80%, and shares that out among all its participants by what each has in store.",
    "mkt": "The aggregator's third part: its own AI agent on the network. It asks every participant for its part over NANDA Town, signed: a community through its community agent, a solar-and-battery plant and a data center each directly. It reads the answer and the report that come back. It asks. It does not order. The amounts it carries come from the sharing-out's code.",
    "agg-ref": "The aggregator's fourth part. Code checks every report row: the signature and the sender, the limits, values that are stuck, and the meter. An AI model reads only the new words in a report's note, and a note can only lower trust. A row that is not trusted is held back from settlement.",
    "utl": "The utility sets the most a community may send out at its connection. That limit can overrule a sale. It doesn't buy or sell.",
    "buy-u": "Carries the aggregator's order to the community for one buyer, the utility, and settles it on the meters afterwards.",
    "buy-g": "The same for a second buyer, the grid operator. Both orders fill from one pool, so a meter is never sold twice.",
    "co-fc": "The community agent's own forecast of its homes' evening demand. It is fitted again each day on the community's last weeks of meter readings and the weather forecast.",
    "co-cover": "The community agent promises upward less than its members offered: only the share its own record says they deliver. Its members are still asked for everything they offered, and the difference is the cover. After the evening, what was delivered goes onto its record, and the next cover is taken from it. All by code.",
    "co-agent": "The members' batteries follow the aggregator's signed request, and the community agent answers for them: a request above their rating is refused in writing.",
    "co-market": "The day-ahead clearing, by code. One seller for every member of the community: it calls for offers, fills the book with firm power first, keeps every half hour inside the utility's limit, and sends each member its contract. It hears only amounts.",
    "co-desk": "Gap filling, by code. On the day it hears each shortfall, asks the members that have room to spare, takes every answer, and moves the gap between them.",
    "co-report": "The community agent reports upward: one signed row for each quarter hour, with its own meter beside it. No member is named. Checking each member's readings and working out pay are on the return path, below.",
    "site-pv": "A solar-and-battery plant is one site with one owner and one meter, so its own agent answers the aggregator: no coordinator stands in between. It takes the request for its battery, answers what it will give with the reason wherever that is less, follows it inside its own limits, and sends a signed row every quarter hour. Code decides; a person's limit at the site is kept and named in the answer.",
    "site-dc": "A data center answers the aggregator the same way, through its own agent. Its battery follows the request above its backup reserve. It may also pause work that can wait and run it again within its own waiting time. Critical load is never touched.",
    "town": "A channel. It holds and logs signed envelopes. It reads no amounts and picks no seller.",
    "h-agent": "Every home has its own agent. Code makes its plans: its offer, its commitment, how it opens the sale, and its answer when something changes. What the owner wrote can only lower what it gives. Only an amount leaves the home.",
    "b-agent": "Every building has its own agent too, and code plans by zone: lights first, then air and cooling, inside the limits the manager set. Only an amount leaves the building.",
    "h-model": "A small AI model on the site. It reads what the owner writes and turns it into limits the plan must keep, and it words the report the owner reads. It never sets an amount.",
    "b-model": "The same small AI model for a building. It reads what the manager writes, such as a note about the chiller, and words the report. It never sets an amount.",
    "h-tools": _TOOLS, "b-tools": _TOOLS, "h-guard": _GUARD, "b-guard": _GUARD,
    "h-seal": "One use. The device takes only what the guard passed.", "b-seal": "One use. The device takes only what the guard passed.",
    "h-driver": "Sends each checked call to its device, in that device's own language.",
    "b-driver": "Sends each checked call to its device, in that device's own language.",
    "h-dev": "The home's own devices: the battery, the car charger, heating and cooling, hot water.",
    "b-dev": "The building's own devices: cooling, air handling, lights, plugs and car charging.",
    "h-person": "The owner writes to the home's agent in plain words, and is told in plain words when the home gives less than asked. A limit the owner set beats everything else.",
    "b-person": "The manager writes to the building's agent in plain words, and is told in plain words when the building gives less than asked. A limit the manager set beats everything else.",
    "r-read": "Each node signs its half-hour readings, 45 minutes after the last.",
    "r-check": "Each reading is held to the meter, stored energy and nameplate at every door.",
    "r-settle": "Each buyer settles on what can count. The money rests on what sellers say, inside physical limits.",
    "r-pay": "Pay goes by delivery, at each class's share. These are records. No money moves.",
}
_GUARD_BRIEF, _TOOLS_BRIEF = "Six checks on every device call. It never plans, and it has the last word.", "Shows only this step's tools. Policy denies by default."
BRIEF = {
    "agg-clean": "Rebuilds each hour's transformer readings from the patterns they share, before any plan is made.",
    "agg-share": "Works out the need by hour, and who is asked for how much.",
    "mkt": "An AI agent that asks every participant, signed, and reads its answer and its report. It asks, it doesn't order.",
    "agg-ref": "Checks every report row: signature, limits, stuck values, the meter. AI reads the notes, and a note can only lower trust.",
    "utl": "Sets a limit at the community's connection, which can overrule a sale.",
    "buy-u": "Carries the aggregator's order for the utility, and settles it on the meters.",
    "buy-g": "Carries the order for the grid operator. Both orders fill from one pool.",
    "co-fc": "Its homes' evening demand, fitted each day on its own last weeks of readings.",
    "co-cover": "Promises only the share its record says its members deliver. The rest is the cover.",
    "co-agent": "They follow the aggregator's signed request. The community agent answers for its members.",
    "co-market": "Calls for offers, fills the book, keeps the utility's limit, sends each contract. By code.",
    "co-desk": "Hears a shortfall, asks members with room to spare, and moves the gap. By code.",
    "co-report": "One signed row a quarter hour, with its own meter beside it. No member is named.",
    "site-pv": "One site, its own agent. Takes the request, answers for itself, reports each quarter hour.",
    "site-dc": "One site, its own agent. Its battery follows the request; work that can wait may be paused and run later.",
    "town": "A channel for signed envelopes. It reads no amounts and picks no seller.",
    "h-agent": "Code makes each of the home's plans, inside what its owner asked to keep. Only an amount leaves the home.",
    "b-agent": "Code plans the building by zone, inside the manager's limits. Only an amount leaves the building.",
    "h-model": "Reads what the owner writes, and words the report. It never sets an amount.",
    "b-model": "Reads what the manager writes, and words the report. It never sets an amount.",
    "h-tools": _TOOLS_BRIEF, "b-tools": _TOOLS_BRIEF, "h-guard": _GUARD_BRIEF, "b-guard": _GUARD_BRIEF,
    "h-driver": "Sends each checked call to its device.", "b-driver": "Sends each checked call to its device.",
    "h-dev": "The home's own devices.", "b-dev": "The building's own devices.",
    "h-person": "Writes in plain words. Told in plain words when the home gives less.",
    "b-person": "Writes in plain words. Told in plain words when the building gives less.",
    "r-settle": "Each buyer settles on what can count, inside physical limits.",
}
# with no single sites, the request agent asks the community alone
NO_SITES = {"mkt": ("The aggregator's third part: its own AI agent on the network. It asks each community for its part over NANDA Town, signed, and reads the answer and the report that come back. It asks. It does not order. The amounts it carries come from the sharing-out's code.",
                    "An AI agent that asks each community, signed, and reads its answer and its report. It asks, it doesn't order.")}
# (a, b, how it is drawn). A message may run either way along an edge; the utility's limit carries no message
EDGES = [("agg-clean", "agg-share", "h"), ("agg-share", "mkt", "h"), ("mkt", "agg-ref", "h"), ("mkt", "buy-u", "v"), ("mkt", "buy-g", "v"),
         ("utl", "co-market", "absent"), ("buy-u", "town", "railL"), ("buy-g", "town", "railR"), ("co-fc", "co-cover", "h"),
         ("co-cover", "co-agent", "h"), ("co-agent", "co-market", "h"), ("co-market", "co-desk", "h"), ("co-market", "town", "v"),
         ("co-desk", "town", "v"), ("co-desk", "co-report", "h"), ("co-report", "town", "v"), ("town", "h-agent", "v"), ("town", "b-agent", "v"),
         ("h-agent", "h-model", "v"), ("h-tools", "h-guard", "v"), ("h-guard", "h-seal", "v"), ("h-seal", "h-driver", "v"),
         ("h-driver", "h-dev", "v"), ("b-agent", "b-model", "v"), ("b-tools", "b-guard", "v"), ("b-guard", "b-seal", "v"),
         ("b-seal", "b-driver", "v"), ("b-driver", "b-dev", "v"), ("h-agent", "h-tools", "skip"), ("b-agent", "b-tools", "skip"),
         ("h-dev", "h-agent", "sensor"), ("b-dev", "b-agent", "sensor"), ("h-person", "h-agent", "person"), ("b-person", "b-agent", "person"),
         ("h-dev", "h-person", "quiet"), ("b-dev", "b-person", "quiet"), ("h-dev", "r-read", "ret"), ("b-dev", "r-read", "ret"),
         ("r-read", "r-check", "h"), ("r-check", "r-settle", "h"), ("r-settle", "r-pay", "h"), ("site-pv", "town", "v"), ("site-dc", "town", "v")]
NO_MESSAGE = {("mkt", "buy-u"), ("mkt", "buy-g"), ("utl", "co-market")}
AGG_ROW = ("agg-clean", "agg-share", "mkt", "agg-ref", "utl", "buy-u", "buy-g")
CO_SIX = ("co-fc", "co-cover", "co-agent", "co-market", "co-desk", "co-report")
STRIP = [("Aggregator and utility", AGG_ROW), ("Community agent", CO_SIX), ("Single sites", SITE_BLOCKS), ("Town", ("town",)),
         ("Agent", ("h-agent", "b-agent")), ("Model", ("h-model", "b-model")), ("Tools", ("h-tools", "b-tools")), ("Guard", ("h-guard", "b-guard")),
         ("Seal", ("h-seal", "b-seal")), ("Driver", ("h-driver", "b-driver")), ("Devices", ("h-dev", "b-dev")), ("People", ("h-person", "b-person")),
         ("Return", ("r-read", "r-check", "r-settle", "r-pay"))]
LAYERS = {1: "The aggregator and the utility", 2: "Participants", 3: "NANDA Town", 4: "Node agents", 5: "Tool server, guard, seal, driver",
          6: "Appliances", 7: "People", 8: "Return path"}


class Map:
    """The map of one page: with the single sites beside the community, or without them."""

    def __init__(self, sites: bool):
        self.sites = sites
        self.blocks = [b for b in BLOCKS if sites or b[0] not in SITE_BLOCKS]
        self.ids = [b[0] for b in self.blocks]
        self.index = {b: i for i, b in enumerate(self.ids + ["input"])}       # a box's number in the page's data; "input" is last
        self.by = {b[0]: b for b in self.blocks}
        self.about, self.brief = dict(ABOUT), dict(BRIEF)
        if not sites:
            for b, (para, line) in NO_SITES.items():
                self.about[b], self.brief[b] = para, line
        self.edges = [e for e in EDGES if sites or e[0] not in SITE_BLOCKS]
        self.strip = [(n, bs) for n, bs in STRIP if sites or bs != SITE_BLOCKS]
        self.layers = {**LAYERS, 2: "Participants" if sites else "Community agent"}
        drawn = [(a, b) for a, b, _ in self.edges if (a, b) not in NO_MESSAGE]
        self.edge_set = set(drawn) | {(b, a) for a, b in drawn}       # the lines a moment's path may run along

    def full(self, b: str) -> str:
        return FULL_NAME.get(b, self.by[b][1] if b in self.by else b)

    def page_blocks(self) -> list[dict]:
        """The boxes as the page's data has them: name, hue, full name, paragraph and one line."""
        out = []
        for b, n, hue, _, sub in self.blocks:
            row = {"id": b, "n": n, "c": hue, "fn": self.full(b), "ab": self.about.get(b, ""), "a1": self.brief.get(b, self.about.get(b, ""))}
            if b in ("mkt", "utl"):
                row.update({"s": sub, "lv": 1})
            out.append(row)
        return out + [{"id": "input", "n": "Input", "c": "c3", "fn": "Input"}]

    def page_edges(self) -> list[list[str]]:
        return [[a, b, "lim" if "utl" in (a, b) else k] for a, b, k in self.edges]
