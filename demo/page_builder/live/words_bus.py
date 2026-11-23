"""The fixed words of the steps made from what crosses the bus, from the sale's snapshots, from the meter and from the console's own posts.

Each title and sentence is the recorded evenings' own wording where a recording had the step, because the builder's boxes and cards read
them (replay/moments.py, replay/panels.py): "desk" or "dispatch" in a title lands on the desk, "request" on the community agent,
"report upward" on its report. A {name} takes the field of that name given to Shaping.step; {Name} is the same name at the head of a
sentence.
"""
from __future__ import annotations

from .shape import Row


def R(beat: str, stage: str, layer: str, title: str, plain: str, key: bool = False, say: bool = False, box: str = "town") -> Row:
    return Row(beat, stage, layer, title, plain, key, say, box)


ROWS = {
    # the buyers' orders, posted by the console itself, and the day-ahead question
    "order": R("orders", "order", "buyer", "{Buyer} places its order",
               "{Buyer} orders {kw} kW from {start} to {end} on {date} at ${price} per kWh, and puts down a ${deposit} deposit.",
               key=True, say=True, box="{buyer_box}"),
    "ask_q": R("ask", "order", "town", "The coordinator asks what's wanted tomorrow",
               "At 10:00 the day before, the coordinator asks {buyer} what it needs for {date}."),
    "ask_a": R("ask", "order", "town", "{Buyer} answers with its order", "{Buyer}'s answer carries its order as a signed Beckn catalog.",
               key=True, say=True, box="co-market"),
    "tomorrow_q": R("tomorrow", "order", "town", "The coordinator asks about tomorrow",
                    "The day's question goes to {buyer}: what does it need for {date}?", key=True, say=True),
    "tomorrow_a": R("tomorrow", "order", "town", "{Buyer} has nothing to order", "{Buyer} answers with no order for {date}."),
    # the call for offers, and a followed node's part in it
    "call": R("call", "offers", "coordinator", "The call for offers goes to every member",
              "One call goes to all {members} members. It carries {kw} kW per half hour, so a node doesn't read one buyer's line.",
              key=True, say=True, box="co-market"),
    "call_reach": R("home-safe", "offers", "town", "The call reaches {name}", "The signed call for offers passes through Town to {name}."),
    "offer_sent": R("home-model", "offers", "town", "{Name} sends its offer",
                    "The offer goes back signed by {name}: {kw} kW at most per half hour. Town passes it on unread.", box="co-market"),
    # the contracts
    "select": R("buyer-contract", "contract", "town", "The coordinator takes the order", "The coordinator tells {buyer} it will fill this order."),
    "on_select": R("buyer-contract", "contract", "town", "The buyer drafts the contract", "{Buyer} answers with a draft contract.", box="co-market"),
    "init": R("buyer-contract", "contract", "town", "The coordinator names the meters and the kW",
              "The coordinator names the meters and {buyer}'s share of the capacity sold.", key=True),
    "on_init": R("buyer-contract", "contract", "town", "The buyer agrees to the meters", "{Buyer} agrees to the meters and the kW.", box="co-market"),
    "confirm_b": R("buyer-contract", "contract", "town", "The coordinator confirms the contract", "The coordinator confirms the contract with {buyer}."),
    "on_confirm_b": R("buyer-contract", "contract", "town", "The contract is active", "{Buyer} signs: the contract is {status}.", key=True, say=True,
                      box="co-market"),
    "contracts": R("node-contract", "contract", "coordinator", "Each node gets its contract",
                   "Both buyers are signed, so {n} nodes each get one contract. A node doesn't know who buys.", key=True, say=True, box="co-market"),
    "contract_reach": R("node-contract", "contract", "town", "The contract reaches {name}", "{Name} is asked for {kw} kW at most, at ${price} per kWh."),
    "contract_answer": R("node-contract", "contract", "town", "{Name} says {status}", "{Name} answers the contract: {status}.", box="co-market"),
    "frozen": R("frozen", "contract", "coordinator", "The deal is frozen",
                "{n} nodes take part. The meters and the capacity go to both buyers, who now work out each meter's baseline.", key=True,
                box="co-market"),
    "final_list": R("frozen", "contract", "town", "The final list goes to the buyer", "{Buyer} hears who takes part and how much was sold."),
    "baselines": R("frozen", "contract", "buyer", "Baselines are fixed before anyone delivers",
                   "{Buyer} works out what each of {n} meters would use on a normal day. Payment later is measured against this.", say=True,
                   box="{buyer_box}"),
    # the aggregator's requests
    "request": R("battery-ask", "prepare", "town", "The aggregator asks the members' batteries",
                 "The aggregator's agent asks this community's members' batteries for their part of the evening's need, signed with its own key.",
                 key=True, box="co-agent"),
    "request_taken": R("battery-ask", "prepare", "coordinator", "The community agent takes the request for the batteries",
                       "The request is from the aggregator on the community's record and its signature holds, so the community agent takes it. "
                       "It answers for its members: a request is not an order.", key=True, say=True, box="co-agent"),
    "request_refused": R("ask-refused", "prepare", "coordinator", "The community agent refuses the request it can't meet",
                         "The community agent refuses the request whole, and nothing changes. It answers for its members: a request is not an order.",
                         key=True, say=True, box="co-agent"),
    "request_back": R("battery-ask", "prepare", "town", "The answer to the request goes back, signed",
                      "The community's answer travels back over NANDA Town, signed with the community agent's own key."),
    "site_ask": R("site-ask", "prepare", "coordinator", "The aggregator asks a {site_kind}",
                  "The aggregator's agent asks this {site_kind} for its part of the evening's need, the same way it asks a community.",
                  key=True, say=True, box="{site_box}"),
    "site_answer": R("site-answer", "prepare", "coordinator", "The {site_kind} answers for itself",
                     "The {site_kind}'s own agent checks the request against its limits and answers, signed with its own key: {answer}.",
                     key=True, say=True, box="{site_box}"),
    # the reports upward
    "community_report": R("community-report", "delivery", "coordinator", "The community's report upward, {start} to {end}",
                          "One row for each quarter hour, written once it has ended: the meter at the connection, the batteries' charge and the "
                          "step's price.", key=True, say=True, box="co-report"),
    "site_report": R("site-report", "prepare", "coordinator", "The {site_kind} reports upward, for itself",
                     "Every quarter hour the {site_kind}'s agent sends one signed row over NANDA Town; the aggregator's agent keeps a row only "
                     "if the signature and the sender hold.", key=True, say=True, box="{site_box}"),
    # the desk
    "call_in": R("call-in", "exception", "town", "A call travels to the desk: {kw} kW, {start} to {end}",
                 "{Buyer} calls for {kw} kW more from {start} to {end}, at ${price} per kWh: {why}.", key=True, say=True, box="co-desk"),
    "short": R("desk", "exception", "town", "{Name} tells the desk",
               "{Name} tells the coordinator it will be short by up to {kw} kW. The report carries the amounts, and no reason in words.",
               key=True, say=True, box="co-desk"),
    "short_none": R("desk", "exception", "town", "{Name} tells the desk it is back on its plan",
                    "{Name} tells the coordinator it is no longer short.", box="co-desk"),
    "desk_ask": R("desk", "exception", "coordinator", "The desk asks who can add",
                  "The desk asks {n} members how much they can add from {start} to {end}.", key=True, box="co-desk"),
    "desk_ask_one": R("desk", "exception", "town", "The desk asks {name} what it can add",
                      "The desk asks {name} how much it can add from {start} to {end}, at ${price} per kWh."),
    "desk_answer": R("desk", "exception", "town", "{Name} answers the desk", "{Name} answers what it can add: {kw} kW.", box="co-desk"),
    "desk_dispatch": R("desk", "exception", "town", "The desk dispatches to {name}",
                       "{Name} is told what it owes on top: {kw} kW from {start} to {end}, at ${price} per kWh.", key=True),
    "desk_warns": R("desk", "exception", "town", "The desk warns the buyer",
                    "The desk tells {buyer} the community may fall short by {kw} kW from {start} to {end}: {why}."),
    "call_ask": R("call-desk", "exception", "coordinator", "The desk asks members for the call",
                  "The desk asks {n} members how much they can add for the call, from {start} to {end}.", key=True, box="co-desk"),
    "call_ask_one": R("call-desk", "exception", "town", "The desk asks {name} for the call",
                      "The desk asks {name} how much it can add for the call, at ${price} per kWh."),
    "call_answer": R("call-desk", "exception", "town", "{Name} answers the desk for the call", "{Name} answers what it can add: {kw} kW.",
                     box="co-desk"),
    "call_dispatch": R("call-desk", "exception", "town", "The desk dispatches the call to {name}",
                       "{Name} is told what it owes on top for the call: {kw} kW from {start} to {end}.", key=True),
    "call_confirm": R("call-desk", "exception", "town", "The desk confirms the call to {buyer}",
                      "The desk confirms {kw} kW of the call to {buyer}.", say=True),
    # after the window
    "node_report": R("report", "report", "town", "{Name} sends its report up", "The labelled report goes to the coordinator, signed.", box="co-market"),
    "readings": R("readings", "readings", "town", "{Name} sends its readings",
                  "After the window {name} sends all its signed readings in one envelope, to the coordinator and to each buyer.", key=True,
                  box="r-read"),
    "readings_done": R("readings", "readings", "town", "The coordinator tells {buyer} the readings are complete",
                       "Every reading the sale needs is in, and {buyer} can count each meter.", box="r-read"),
    "buyer_settles": R("settle", "settlement", "buyer", "{Buyer} settles", "{Buyer} owes ${usd} for its share of what the meters show.",
                       key=True, say=True, box="r-settle"),
    "pay_told": R("pay", "settlement", "town", "{Name} is told its pay",
                  "{Name} delivered {kwh} kWh of the {committed} kWh it committed, and is paid ${usd}. Its reputation is now {rep}.", key=True,
                  box="r-pay"),
}
