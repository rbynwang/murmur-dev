"""The Full record's own words: the layers' names, what changed in each layer, the design's own gaps and the fixed rows of
the layers' tables. Everything a recording says comes from the recording; these are the words around it."""
from __future__ import annotations

from ..templating import Markup

LAYER_NAMES = {1: "The aggregator and the utility", 2: "Community agent", 3: "NANDA Town", 4: "Node agents",
               5: "Tool server, guard, seal, driver", 6: "Appliances", 7: "People", 8: "Return path"}
LAYER_HUES = {1: "1", 2: "2", 3: "3", 4: "4h", 5: "5", 6: "6", 7: "7", 8: "r"}

START = "Press Play to follow one recorded day, from a buyer's order to the last payment."

# What each change is called on a step's tag, by its change id
CHANGE_TAG = {"sale": "fixed", "desk": "fixed", "money": "fixed", "limits": "fixed", "ops": "new", "agents": "changed",
              "all_agents": "new", "plans": "changed", "reader": "changed", "levels": "new"}
CHANGE_NAME = "plans by code"          # every change a step of these recordings carries is the design's plans by code

# What changed since the last version: (tag, title, what was wrong, what changed, change id, layer)
REV = [
    ("fixed", "Sell to the order", "Offers were counted down by a 0.9 confidence and by reputation, on top of the safe figure. A live sale sold 2,969 kW of a 4,362 kW order, and the nodes then delivered more than that.",
     "Offers count at face value: firm first, then tentative as far as a deposit holds it. The margin sits on top and never lowers what is sold.", "sale", 2),
    ("new", "Second round", "The clearing ran once. A short sale went through with nothing going back to the nodes.",
     "If offers don't cover the order and the margin with room to spare, a node that held back hears what the pool lacks, and its agent may raise its offer, inside its safe limit.", "sale", 2),
    ("fixed", "Desk asks by size", "A buyer's call asked only nodes with room on file, and a cautious offer leaves about 1%. On 14 Jul a staged call got 29.2% with the university never asked.",
     "A call asks by size, in waves of 32, 64, then the rest. The same case now fills all 2,181 kWh.", "desk", 2),
    ("new", "State survives a restart", "All market state lived in memory: a restart of the coordinator or a buyer lost the sale and its money, and nobody was told.",
     "Each service keeps what a sale needs on disk and reloads it. /health now says whether Town answers and sends get through.", "ops", 2),
    ("new", "The clock waits for every agent", "Each service ran on the wall clock, so a busy agent skipped a step: on the 7 Nov live day two nodes skipped one each.",
     "At each 15-minute step every clock holds until every agent has answered and nothing the market waits on is still coming. The desk takes every answer before it moves power. "
     "A wait stuck for 3 minutes lets the clock go on, on the record.", "all_agents", 2),
    ("new", "The coordinator hears only the amount", "An offer carried its agent's reason, the person's words and any flags to the coordinator.",
     "An offer carries kW per half hour and nothing in words. The reason, the person's words and any flags stay in the node's own copy and its receipt.", "all_agents", 2),
    ("new", "Three levels", "One coordinator stood between every node and the buyers, with no utility above it.",
     "An aggregator asks each community for its part, the utility sets a limit, and each community has its own agent. The community agent adds the offers up, holds back a cover, runs what the "
     "community shares and reports upward. Home agents plan their own devices, and only an amount goes up. This evening ran with the community switch on, the utility's limit set, a stand-in "
     "for the aggregator's agent asking the community over NANDA Town, and two stand-in desks carrying the order to the homes.", "levels", 2),
    ("fixed", "One id per message", "A replayed day reused batch ids with new bodies. Town refused them and Murmur took that as sent, and a message it refused itself was recorded as processed.",
     "An id now says which message it is: a retry keeps its id and first body, and each play of a day has its own. A refused send is loud, and a refused message is recorded as rejected.", "town", 3),
    ("changed", "Plans by code", "On 8 Nov the big model made every plan: 1,091 answers over the eight days.",
     "Code makes every plan: the offer, the commitment, the sale's opening, each exception and the pre-cool. Every home and building keeps its own agent, and each receipt reads "
     "\"rule: plans are decided by code\". Over the seven different days sellers get $90,519, against $90,386 then, and the two are never more than $44.02 apart on a day.", "plans", 4),
    ("changed", "Exception: one whole plan", "The big model answered each exception with one whole plan, and the clock waited for it.",
     "Code answers each exception and the sale's opening with one whole plan, at once. The guard checks every call in it, and the receipt keeps the plan and the fact behind it.", "plans", 4),
    ("changed", "Less needs a reason", "A model that gave less than the rule's amount had to say why.",
     "When code's plan gives less than the rule's amount, its reason is on the receipt and the person is told. On the notes day the office gave 102 kW instead of 320, for its manager's note.", "plans", 4),
    ("new", "Every decision leaves a receipt", "Only a plan's record set the rule's plan beside the agent's choice.",
     "Each decision leaves a receipt in the node's chained log: what was asked, the rule's plan, what the agent chose, its reason and its facts.", "all_agents", 4),
    ("changed", "No plan waits on a model", "Each plan waited for the big model, and a failed answer fell back to the rule's plan.",
     "No plan waits on a model, so none can fail that way. If a note can't be read at all, everything is kept for the night and the person is told.", "plans", 4),
    ("changed", "Each node reads its own notes", "On 8 Nov the big model read each note, as one more of its decisions.",
     "A small model, Qwen 3.5 4B, reads each note and turns it into one of six needs. Code keeps the need from then on, the guard holds it, and the person hears what it costs. A need can only "
     "keep a device back for its owner. The small model reads a note in about 4 seconds on a 24 W board. It still misses about 5 needs in 151 notes, and a note written to fool it works 8 times in 26.",
     "reader", 4),
    ("changed", "Steps 1 to 4 are on the record", "They were labels stamped over work done inside the offer.",
     "Each step now enters the record in its real order, with its inputs and outputs: the facts and the rule's plan the agent reads.", "agents", 4),
    ("fixed", "One number per limit", "A person's 0.2 °C comfort limit became 1.5 to 2.4 °C on every agent node, and a lowered light limit missed the agent.",
     "Each limit is one number, read by the sellable figure, the menu, the prompt, the guard and the controller.", "limits", 5),
    ("new", "Check at the point of write", "The controller wrote to devices with no check of its own, and a missing guard input could read as a yes.",
     "A person's limit binds at the write. The guard refuses a tool off the turn's list, and a missing input is a no.", "limits", 5),
    ("fixed", "Alarm reaches a live node", "No alarm could reach a live node.", "It can now, and only a person's signed word ends it.", "limits", 6),
    ("new", "The person hears why", "Nothing was pushed to a person.",
     "When a node gives less than asked, its owner or manager is told why, in plain words. It waits on the node's own channel, and goes in the day's report.", "all_agents", 7),
    ("changed", "The report goes up", "Step 9's report stayed on the node, and nothing sent it.",
     "The facts, their labels, the summary and who wrote them go to the coordinator, signed, and stay on the sale. No model reads them there.", "agents", 7),
    ("fixed", "Readings checked at every door", "A node could set a buyer's bill to any size: one false reading billed $204,026.52.",
     "Each reading is held to the meter, stored energy and nameplate at the coordinator and both buyers. A liar is bounded, not stopped: about $216 on one home at worst.", "money", 8),
    ("fixed", "Settlement works out, then pays", "A settlement went out once, after the contract was marked done. One failed send on the first live day stranded $21,388.67 for 202 sellers.",
     "Everything is worked out first, so a sale is paid whole or not yet. A missing settlement is asked for again.", "money", 8),
    ("fixed", "Lost readings are chased", "A batch lost to one buyer went unseen, and that buyer settled short.",
     "Each buyer says what it lacks, the coordinator asks again, and what arrives late is paid as a top-up. Nothing is taken back.", "readings", 8),
]
BRANCH_ONLY = ("plans", "reader", "levels")          # changes on a branch, not merged
ON_AGENTIC = "all_agents"                            # the all-agent changes, on their own branch

# Which layer each gap belongs to, by its id: the recording's own gaps and the design's
GAP_LAYER = {"no_ceiling": 1, "no_split_choice": 2, "second_round_idle": 2, "reputation_idle": 2, "explain_skipped": 2, "town_not_live": 3, "few_think": 4,
             "all_agents_not_live": 4, "clock_waits_in_replay": 4, "code_nodes_no_guard": 5, "limit_passed_battery_trip": 5, "devices_simulated": 6, "no_one_told": 7,
             "opt_out_unseen": 7, "note_no_reply": 7, "alarm_never_cleared": 7, "reports_unread": 8, "blind_in_window": 8, "baseline_blind_to_heat": 8, "no_money_moves": 8}
SOLVED = {"town_not_live", "few_think", "code_nodes_no_guard"}       # gaps every node's own agent closed: they stay out of the lists
OUT_OF_TABLE = "no_data_centers"                                      # a gap the table of gaps leaves out

# The design's own gaps, after the recording's: (id, title, what you might expect, what happens)
DESIGN_GAPS = [
    ("all_agents_not_live", "Plans by code isn't live yet", "All 200 homes and 3 buildings run this code on the real machines.",
     "Live, the 200 homes run 68aacc4: 3 homes and the 3 buildings have a model, and the other 197 homes run on rules. Plans by code has run on the eight recorded days only, "
     "with 8 homes and 3 buildings on a local NANDA Town. It isn't deployed on the 200 homes yet."),
    ("market_stand_ins", "A stand-in asks in the aggregator's place", "An aggregator that shares one grid need among many communities and asks each for its part.",
     "The sharing-out is worked out offline on ENGIE's year. In this evening a stand-in for the aggregator's agent sends that result as a signed request and receives the community's answer "
     "and its report. It doesn't share out the need itself, has no meter of its own and reads no words. Two stand-in desks with fixed orders carry the order to the homes and buildings."),
    ("no_utility_limit", "The limit never bound on this evening", "The utility sets a limit at the community's connection, and a sale that would pass it gives way.",
     "The limit is set and every half hour sold is checked against it. On this winter evening the community draws from the grid, so the limit on what it may send out never binds and nothing was cut."),
    # this one sentence stands on the page with its apostrophes as written, so it is given as page text
    ("community_switch_off", "The battery and the meter are stand-ins",
     Markup("The members' batteries are their owners' devices. The community agent asks for them together, and the meter at the connection is its own."),
     "The community switch is on: its cover comes from its own record, it answers the aggregator's signed request for itself, and it sends its report upward one signed row a quarter hour. "
     "The battery itself is replayed from ENGIE's record, and the community's own meter and battery reading come from a stand-in on the same computer."),
    ("reader_misses", "The small model misreads some notes", "Every need a person writes is kept, and a note can't be used to give orders.",
     "On 151 labelled notes the small model still misses about 5 needs, and a note written to fool it works 8 times in 26. A need can only keep a device back for its owner, so a wrong reading "
     "costs the sale and never a person's limit. If a note can't be read at all, everything is kept for the night and the person is told."),
]

# What each layer is, under its name; {homes}, {buildings} and {nodes} are the community's own counts
OVERVIEW = {
    1: "The aggregator: shares one grid need among its 80 participants and asks each community for its part. A stand-in for its own agent asks the community over NANDA Town, signed, and "
       "hears its answer and its report. Two stand-in desks with fixed orders still carry the order to the homes and buildings. The utility: sets a limit at the community's connection, "
       "which can overrule a sale. The limit is set, and checked at the clearing. The two desks order the same evening: how many kW off the grid in each half hour, in which window, at what "
       "price, with what deposit. They don't think and they don't bargain.",
    2: "One seller for {homes} homes and {buildings} buildings. It collects offers, fills the orders from them and writes one contract per node. It works by code at every step: clearing, "
       "readings and payment. It hears only each node's amount. The members' batteries follow the aggregator's request, which arrives at 14:00 as a signed message. The community agent "
       "answers for them: it takes the request, or refuses it and says why. In this evening the battery is replayed from ENGIE's record: it is not a device here. Agents exchange signed, "
       "typed messages. They don't negotiate.",
    3: "A channel. Every message between agents is a signed envelope that Town accepts, holds until it is claimed, and logs. It reads no amounts, sets no price and picks no seller. Nothing "
       "on this page is decided here.",
    4: "Every home and building has its own agent, and code makes every one of its plans. Steps 1 to 4 are tools that give the planner its facts. Code then decides the offer, the "
       "commitment, the sale's opening, every exception and the morning pre-cool, and each receipt reads \"rule: plans are decided by code\". Code's planner works out the safe amount "
       "inside the person's limits, and offers it. A need read from a note lowers it, and the person is told. Code picks the devices and works out each one's exact kW. A small model "
       "reads what a person writes and words the report. In this recording code makes every plan for all {nodes} nodes, {homes} homes and {buildings} buildings, and a small model reads "
       "what people write and words the reports.",
    5: "The only way from an agent to a device. A call passes the step's menu, then policy, then six guard checks on safety and money limits, then takes a one-use seal to the driver. The "
       "guard checks and never decides: a blocked call comes back with its reason. Its lines below are its real run, branch by branch.",
    6: "What the calls do to the devices, and what the sale takes from them. Every load here is simulated, and no real device is connected.",
    7: "When a node gives less than asked, its agent tells the owner or manager why, in plain words, on the node's own channel and in the day's report. A person still has the last word: "
       "a signed limit beats everything above it. A note reaches the small model as words. It can state one of six needs, which code then keeps, and it can't raise a limit.",
    8: "The same layers, upward. After the window each node signs its half-hour readings, every door checks them, each buyer settles on what can count, and the coordinator splits the pay "
       "by delivery. The money rests on what sellers say about themselves, inside physical limits: no meter yet belongs to someone else. These are records and signed messages. No money moves.",
}

# The appliance table's rows: (key, name)
DEVICES = [("battery", "Home battery"), ("car", "Car"), ("cooling", "Home cooling"), ("water", "Hot water, machines"),
           ("campus", "Campus battery"), ("plant", "Building cooling and air"), ("lights", "Lights"), ("plugs", "Plugs")]

# The clearing at a glance: a section's title, or (letter, label, the ledger's key, the value that lights the row, how it is worked out)
LED_ROWS = [
    ("The order",),
    ("A", "Ordered by both buyers", "asked_kw", "asked_kw", ""),
    ("The offers",),
    ("B", "Offered, firm", "offered_firm_kw", "offered_firm_kw", "sold first"),
    ("C", "Offered, tentative", "offered_tentative_kw", "offered_tentative_kw", "sold only as far as a deposit holds it"),
    ("D", "Offered in all", "offered_kw", "offered_kw", "B + C"),
    ("The sale",),
    ("E", "Sold", "sold_kw", "sold_kw", "fills to A from B, then C. Confidence no longer shrinks it"),
    ("F", "Reserve", "reserve_kw", "reserve_kw", "E × margin, as far as the offers reach. It never lowers E"),
    ("G", "Asked of the nodes", "asked_of_nodes_kw", "asked_of_nodes_kw", "E + F"),
    ("Homes against buildings",),
    ("H", "Homes offered", "offered_homes_kw", "offered_homes_kw", ""),
    ("I", "Buildings offered", "offered_buildings_kw", "offered_buildings_kw", ""),
    ("J", "Homes asked", "asked_homes_kw", "asked_homes_kw", "each node gives its firm kW and the same share of its tentative kW"),
    ("K", "Buildings asked", "asked_buildings_kw", "asked_buildings_kw", "nobody picks homes or buildings: the split follows the offers"),
    ("L", "Buildings' part of G", None, "asked_buildings_kw", "K ÷ G, worked out here from J and K"),
]
KEY_ROWS = ("E", "G")
