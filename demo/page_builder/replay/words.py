"""The fixed words of a replay page that do not belong to one box of the map: the names of the figures, the design's own gaps,
what changed in each part, who decides what, and the short lists the whole picture shows beside a box.

Every recording the pages play is one evening of ENGIE's data, run with the community agent's switch on, the aggregator's
request as a signed message and the aggregator's own parts on the map. An evening with single sites names the part of the bill
that is not paid on "kept from the bill"; a year's evening names it what the community agent keeps.
"""
from __future__ import annotations

# A recording's gaps that describe something the design has since closed: they stay off the page
SOLVED = frozenset({"town_not_live", "few_think", "code_nodes_no_guard"})

# The design's own gaps, which no recording can know about: each one's title, and the sentence the whole picture shows
DESIGN_GAPS = [
    {"id": "all_agents_not_live", "title": "Plans by code isn't live yet",
     "actual": "Live, the 200 homes run 68aacc4: 3 homes and the 3 buildings have a model, and the other 197 homes run on rules."},
    {"id": "market_stand_ins", "title": "A stand-in asks in the aggregator's place",
     "actual": "The sharing-out is worked out offline on ENGIE's year."},
    {"id": "no_utility_limit", "title": "The limit never bound on this evening",
     "actual": "The limit is set and every half hour sold is checked against it."},
    {"id": "community_switch_off", "title": "The battery and the meter are stand-ins",
     "actual": "The community switch is on: its cover comes from its own record, it answers the aggregator's signed request for "
               "itself, and it sends its report upward one signed row a quarter hour."},
    {"id": "reader_misses", "title": "The small model misreads some notes",
     "actual": "On 151 labelled notes the small model still misses about 5 needs, and a note written to fool it works 8 times in 26."},
]

# Which boxes each gap belongs to on the whole picture
GAP_BLOCKS = {"no_ceiling": ("buy-u",), "second_round_idle": ("co-market",), "no_split_choice": ("co-market",),
              "reputation_idle": ("co-market",), "devices_simulated": ("h-driver", "b-driver"), "no_one_told": ("h-person", "b-person"),
              "opt_out_unseen": ("h-person",), "alarm_never_cleared": ("b-person",), "reports_unread": ("r-read",),
              "blind_in_window": ("r-read",), "no_money_moves": ("r-pay",), "all_agents_not_live": ("h-agent", "b-agent"),
              "market_stand_ins": ("mkt",), "no_utility_limit": ("utl",), "community_switch_off": ("co-agent",),
              "reader_misses": ("h-model", "b-model")}

# What changed in each part: (tag, title, what was wrong, what changed, its boxes). The whole picture shows one sentence of each
REVS = [
    ("fixed", "Sell to the order", "Offers were counted down by a 0.9 confidence and by reputation, on top of the safe figure.",
     "Offers count at face value: firm first, then tentative as far as a deposit holds it.", ("co-market",)),
    ("new", "Second round", "The clearing ran once.",
     "If offers don't cover the order and the margin with room to spare, a node that held back hears what the pool lacks, and its "
     "agent may raise its offer, inside its safe limit.", ("co-market",)),
    ("fixed", "Desk asks by size", "A buyer's call asked only nodes with room on file, and a cautious offer leaves about 1%.",
     "A call asks by size, in waves of 32, 64, then the rest.", ("co-desk",)),
    ("new", "State survives a restart", "All market state lived in memory: a restart of the coordinator or a buyer lost the sale and "
     "its money, and nobody was told.", "Each service keeps what a sale needs on disk and reloads it.", ("co-market",)),
    ("new", "The clock waits for every agent", "Each service ran on the wall clock, so a busy agent skipped a step: on the 7 Nov live "
     "day two nodes skipped one each.", "At each 15-minute step every clock holds until every agent has answered and nothing the "
     "market waits on is still coming.", ("co-market",)),
    ("new", "The coordinator hears only the amount", "An offer carried its agent's reason, the person's words and any flags to the "
     "coordinator.", "An offer carries kW per half hour and nothing in words.", ("co-market",)),
    ("new", "Three levels", "One coordinator stood between every node and the buyers, with no utility above it.",
     "An aggregator asks each community for its part, the utility sets a limit, and each community has its own agent.",
     ("mkt", "utl", "co-agent")),
    ("fixed", "One id per message", "A replayed day reused batch ids with new bodies.",
     "An id now says which message it is: a retry keeps its id and first body, and each play of a day has its own.", ("town",)),
    ("changed", "Plans by code", "On 8 Nov the big model made every plan: 1,091 answers over the eight days.",
     "Code makes every plan: the offer, the commitment, the sale's opening, each exception and the pre-cool.", ("h-agent", "b-agent")),
    ("changed", "Exception: one whole plan", "The big model answered each exception with one whole plan, and the clock waited for it.",
     "Code answers each exception and the sale's opening with one whole plan, at once.", ("h-agent", "b-agent")),
    ("changed", "Less needs a reason", "A model that gave less than the rule's amount had to say why.",
     "When code's plan gives less than the rule's amount, its reason is on the receipt and the person is told.", ("h-model", "b-model")),
    ("new", "Every decision leaves a receipt", "Only a plan's record set the rule's plan beside the agent's choice.",
     "Each decision leaves a receipt in the node's chained log: what was asked, the rule's plan, what the agent chose, its reason and "
     "its facts.", ("h-agent", "b-agent")),
    ("changed", "No plan waits on a model", "Each plan waited for the big model, and a failed answer fell back to the rule's plan.",
     "No plan waits on a model, so none can fail that way.", ("h-model", "b-model")),
    ("changed", "Each node reads its own notes", "On 8 Nov the big model read each note, as one more of its decisions.",
     "A small model, Qwen 3.5 4B, reads each note and turns it into one of six needs.", ("h-model", "b-model")),
    ("changed", "Steps 1 to 4 are on the record", "They were labels stamped over work done inside the offer.",
     "Each step now enters the record in its real order, with its inputs and outputs: the facts and the rule's plan the agent reads.",
     ("h-agent", "b-agent")),
    ("fixed", "One number per limit", "A person's 0.2 °C comfort limit became 1.5 to 2.4 °C on every agent node, and a lowered light "
     "limit missed the agent.", "Each limit is one number, read by the sellable figure, the menu, the prompt, the guard and the "
     "controller.", ("h-guard", "b-guard")),
    ("new", "Check at the point of write", "The controller wrote to devices with no check of its own, and a missing guard input could "
     "read as a yes.", "A person's limit binds at the write.", ("h-guard", "b-guard")),
    ("fixed", "Alarm reaches a live node", "No alarm could reach a live node.", "It can now, and only a person's signed word ends it.",
     ("h-dev", "b-dev")),
    ("new", "The person hears why", "Nothing was pushed to a person.",
     "When a node gives less than asked, its owner or manager is told why, in plain words.", ("h-person", "b-person")),
    ("changed", "The report goes up", "Step 9's report stayed on the node, and nothing sent it.",
     "The facts, their labels, the summary and who wrote them go to the coordinator, signed, and stay on the sale.",
     ("h-person", "b-person")),
    ("fixed", "Readings checked at every door", "A node could set a buyer's bill to any size: one false reading billed $204,026.52.",
     "Each reading is held to the meter, stored energy and nameplate at the coordinator and both buyers.", ("r-check",)),
    ("fixed", "Settlement works out, then pays", "A settlement went out once, after the contract was marked done.",
     "Everything is worked out first, so a sale is paid whole or not yet.", ("r-settle",)),
    ("fixed", "Lost readings are chased", "A batch lost to one buyer went unseen, and that buyer settled short.",
     "Each buyer says what it lacks, the coordinator asks again, and what arrives late is paid as a top-up.", ("r-read",)),
]

# The names of the figures a moment can show, in the order of the whole picture's list
_TV = [("asked", "Asked"), ("util_kw", "Buyer: utility"), ("grid_kw", "Buyer: grid operator"), ("price", "Price"), ("window", "Window"),
       ("deposits", "Deposits placed"), ("members", "Members"), ("offers", "Offers in"), ("offered", "Offered"), ("firm", "Firm"),
       ("tent", "Tentative"), ("off_h", "Homes offered"), ("off_b", "Buildings offered"), ("margin", "Reserve share"), ("sold", "Sold"),
       ("reserve", "Reserve"), ("nodes", "Asked of nodes"), ("ask_h", "Homes asked"), ("ask_b", "Buildings asked"),
       ("dep_held", "Deposits held"), ("dep_back", "Deposits back"), ("accepted", "Contracts accepted"), ("declined", "Declined"),
       ("call_kw", "Buyer's call"), ("call_price", "Call price"), ("call_conf", "Desk confirmed"), ("twin", "Below the no-sale twin"),
       ("readings", "Readings in"), ("meters", "Meters"), ("refused", "Refused"), ("sold_kwh", "Sold, in kWh"),
       ("delivered", "On the meters"), ("pay_u", "Buyer: utility pays"), ("pay_g", "Buyer: grid operator pays"),
       ("buyers_pay", "Buyers pay"), ("sellers", "To sellers"), ("homes_usd", "Of which homes"), ("bld_usd", "Of which buildings")]
_TV_END = [("call_usd", "The call pays"), ("call_keep", "Coordinator keeps of it")]
TV_SIDE = [("home_safe", "Ceiling"), ("home_firm", "Of it firm"), ("home_tent", "Of it tentative"), ("home_offer", "Offered"),
           ("second_safe", "Its ceiling"), ("second_offer", "It offered"), ("uni_offer", "University offers"), ("c_home", "A home"),
           ("c_code", "A rules-only home"), ("c_uni", "University"), ("owed_uni", "University owes"), ("calls_uni", "University calls"),
           ("owed_home", "Home owes"), ("calls_home", "Home calls"), ("reports", "Reports"), ("rounds", "Rounds moved"),
           ("warnings", "Warnings")]


def place_labels(place: str) -> list[tuple[str, str]]:
    """The names of the figures of the second followed building, called by what it is: "Office offers"."""
    return [("other_offer", f"{place} offers"), ("c_other", place), ("calls_other", f"{place} calls")]


def keep_label(sites: bool) -> str:
    """What the part of the bill not paid on to the sellers is called."""
    return "Kept from the bill" if sites else "Coordinator keeps"


def tv_labels(sites: bool) -> list[tuple[str, str]]:
    """The figures' names, as the page's data lists them."""
    return _TV + [("keep", keep_label(sites))] + _TV_END


# Who decides what, as the whole picture's first block says it
WHO_TITLE = "Who decides what"
WHO_SCOPE = ("In the record of 11 Nov 2026: one of ENGIE's evenings in January 2025, with eight homes, a small office and shops of its "
             "community 19 and a stand-in for the aggregator's own agent on a local NANDA Town. This code isn't on the 200-home live "
             "system yet.")
WHO_ROWS = [
    ("The 8 nodes", "Each home has its own agent, and code makes every one of its plans: the offer, the commitment, the sale's opening "
     "and each exception. Each receipt reads \"rule: plans are decided by code\"."),
    ("The offer", "Code's planner works out the safe amount inside the person's limits, and offers it. A need read from a note lowers "
     "it, and the person is told."),
    ("Sizing", "Code picks the devices and works out each one's exact kW."),
    ("The guard", "Code. It checks every device call against the safety and money limits and what a person asked to keep, and it has "
     "the last word."),
    ("The small model", "A stand-in answered in its place in this evening: it worded each home's report and made no plan. On the "
     "eight scenario days the reader was Qwen 3.5 4B."),
    ("The aggregator", "Shares one grid need among 80 participants and asks each community for its part. Here a stand-in for its own "
     "agent sends its request for the members' batteries as a signed message, and receives the community's signed answer and its "
     "report. It sends a list it is given: it does not share out the need itself. Two stand-in desks with fixed orders still carry "
     "the order to the homes and buildings."),
    ("The utility", "Sets a limit at the community's connection, which can overrule a sale. The limit is set in this evening and "
     "checked at the clearing."),
    ("Community agent", "By code, with its community switch on. It adds the offers up, promises only what its own record of finished "
     "evenings says its members deliver, clears the sale, keeps to the utility's limit, answers the aggregator's signed request for "
     "the members' batteries (it takes it, or refuses it and says why), sends its report upward one signed row a quarter hour, checks "
     "the readings and pays, keeping a fixed 20%. No AI decides anything here. The record below calls it the coordinator."),
    ("The same evening before", "The same evening ran this morning with the request given on the same computer and the report not "
     "sent. Every amount here equals that run's."),
]

# Where it stands, the whole picture's three columns: what is built, live and recorded, then what is still to build
BUILT = ["Plans by code and the small model for notes: on a branch, run on the eight scenario days, not merged or deployed",
         "The community agent's part: switched on in this evening, on branch engie-buildings, not deployed",
         "The aggregator's request, the community's answer and its report as signed messages, with a stand-in for the aggregator's agent",
         "The market, signing, nine steps, guard, receipts and records"]
LIVE = ["200 homes and 3 buildings on 68aacc4, since 18:01 on 7 Nov",
        "There, 3 homes and the 3 buildings have a model, and the other 197 homes run on rules"]
RECORD_HEAD = "The record of 11 Nov"
RECORD_FIRST = "8 homes of ENGIE's community 19 and the aggregator's agent on a local NANDA Town"
RECORD_CHECK = "{when}, checked against the same evening's run with homes only"
RECORD_LAST = "Code makes every plan, and each decision leaves a receipt with its reason"
NOT_BUILT = ["This code on the 200-home system", "An aggregator's agent that shares out the need itself and writes in words",
             "The members' batteries as devices, and a meter of the community's own",
             "Real device drivers and a meter the seller doesn't control", "Overnight planning"]
IN_SHORT = "This evening, in short"

# What a person can write to a node, and what they hear back; the guard's six checks; a node's nine steps (number, name,
# who: step 2 forecasts with a regression on temperature, as the recordings' own step 2 says)
SAYS = [("a note", "read by the small model as words, never as an order"), ("need_now", "takes a device back at once"),
        ("set_limit", "signed, moves a limit"), ("close_group, open_group", "signed, shuts or opens a group"),
        ("clear_alarm", "only a person ends an alarm")]
HEARS = [("told", "why, in plain words, when the node gives less than asked")]
CHECKS = [(1, "Safety state", "any alarm stops every write"), (2, "Allowed", "on this turn's list, not a protected point"),
          (3, "Range", "inside the product's range and the limit in force"), (4, "Timing", "start timers, ramps, one stop a day"),
          (5, "Service", "comfort, owner's wishes, outdoor air, reserve"), (6, "One writer", "one call per point at a time")]
NINE = [(1, "Read schedule", "tool"), (2, "Forecast", "regression"), (3, "Check devices", "tool"), (4, "Sellable kW", "tool"),
        (5, "Decide offer", "code"), (6, "Commit", "code"), (7, "Opening", "code"), (8, "Exception", "code"), (9, "Report", "model")]

# The opening card: who does what, in the design. A two-view page opens on the premise the project stands on
CARD_TITLE = "Who does what"
PREMISE = ("The premise: AI agents will enter every household and every part of our lives, and make them more efficient. Here they "
           "do one job for a utility company: shaving the grid's evening peak.")
CARD_SITES = ("An aggregator asks for a lower evening peak, and every participant answers for itself. Code makes every amount, and AI "
              "reads the words.", [
                  ("The aggregator", "Cleans the grid's readings, shares one need among its participants, sends each its request, and "
                   "checks every report. It buys the evening cut, never anyone's electricity."),
                  ("Who pays", "Whoever bears the cost of the peak: a grid operator or a local utility."),
                  ("Participants", "A community answers through its community agent. A data center answers for itself. A "
                   "solar-and-battery plant holds its battery for the peak under a contract."),
                  ("Homes and buildings", "Their agents know the people and the devices and control the hardware. They sell their cut "
                   "through the community agent. Only an amount leaves a site."),
                  ("AI and code", "AI reads words in two places: people's notes at a home or a building, and reports at the referee. "
                   "Code makes every amount, limit and payment."),
                  ("This replay", "One recorded evening on ENGIE's data, 28 January 2025. Devices are simulated; stand-ins take the "
                   "place of the buyers. Dollars use our assumed price for a cut.")])
REPLAY_WITH_NOTES = ("One recorded evening on ENGIE's data, {date}. Devices are simulated, and stand-ins take the place of the buyers "
                     "and send the aggregator's messages. The reading of each note is a real small model's. Dollars use our assumed price.")
CARD_YEAR = ("Three levels of agents, each answering for its own owner. Code makes every amount, and AI reads and writes the words.", [
    ("The aggregator", "Cleans the grid's readings, shares one need among its participants, asks each community through its request "
     "agent, checks every report, and pays by the meter."),
    ("Community agent", "Adds its members' offers into one promise with a cover, holds its members' batteries for the peak, fills gaps "
     "on the day, and reports upward. All by code."),
    ("Home and building agents", "Know the people and the devices, plan the site and control the hardware. Only an amount ever leaves "
     "a site."),
    ("AI", "Reads what people write, and writes the requests and the reports. It never sets an amount."),
    ("Code and the guard", "Code makes every amount, limit and payment. The guard checks every device call and has the last word."),
    ("This replay", "One recorded evening on ENGIE's data, 28 January 2025. Devices are simulated, and stand-ins take the place of the "
     "buyers and the aggregator's request agent. Its reading cleaner, sharing-out and referee worked on the same day's records.")])
