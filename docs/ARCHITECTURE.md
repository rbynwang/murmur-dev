# Architecture

Murmur sells one thing: an evening cut, by the kW, delivered by a community's members, its homes and buildings, in an evening
window (18:00 to 21:00 in the example). No electricity is traded. Single sites (a solar-and-battery plant, a data center) take part
beside the community: they answer the aggregator's requests for battery power and report to it, and sell nothing. Every participant
has its own Ed25519 key and its own name on one message bus, and every message between participants is signed. The community agent,
the aggregator, each single site and each buyer is a process of its own; homes and buildings run inside a host process. Code decides
every amount, limit and payment; a small language model only reads what people write to their node and words the node's report.

This document covers the parts, the messages between them, the waiting clock, one evening from the day before to settlement, the
package layout, what the demo runner adds, and what each part keeps across a restart. The envelope, the ids and the safety chain
are specified in [PROTOCOL_AND_SAFETY.md](PROTOCOL_AND_SAFETY.md); the data and what it cannot show in
[DATA_AND_LIMITS.md](DATA_AND_LIMITS.md).

## 1. The parts

| Part | Process | Name on the bus | Role |
|---|---|---|---|
| Home node and its agent | inside the homes' host | `home-01`, `home-02`, ... | offers a cut, answers a commitment, delivers, signs its meter readings, reports |
| Building node and its agent | inside the buildings' host | `building-01`, `building-02` | the same protocol, with a building's zones, plant, lights and plug loads as levers |
| Homes' host | `python -m murmur.agents.host_doors run [--limit N]` | one session per home | runs every home it names in one process (`--limit`: the first N only) |
| Buildings' host | `python -m murmur.agents.host_doors run --buildings` | one session per building | the same for buildings |
| Community agent | `python -m murmur.agents.community.service run` | `community` | one community at one point of the grid: market, forecast, cover and promise, clearing, gap desk, report, split of the pay, waiting clock |
| Aggregator | `python -m murmur.agents.aggregator run` | `aggregator` | asks each participant for battery power by the quarter hour, checks and keeps every report row |
| Single site | `python -m murmur.agents.site_service run` | `site-pv-01`, `site-dc-01` | a solar-and-battery plant or a data center that answers the aggregator for itself |
| Buyers | `python -m demo.runner.buyers NAME --port PORT` | `utility`, `grid-operator` | order the cut, contract with the community agent, send baselines, settle on the members' signed readings, call on an alert |
| Message bus | any server of the bus contract; `python -m demo.runner bus [--host HOST] --port PORT --runs FILE` locally | none | carries every signed message: join, send, notify, claim, ack |
| Model server | any server of the chat endpoint at `llm_url`; `python -m demo.runner.model` stands in | none | reads notes and words reports for the nodes' agents |

The community agent, the aggregator and a site also take `pubkey` in place of `run`, which prints the part's public key.

### 1.1 Member nodes and their agents

Homes and buildings run the same protocol code (`node/home.py`, `MemberNode`). Which class speaks for a member is set by cfg
`buyers` and `report_rule` (`agents/host_common.py`): `MemberNode` with neither; `PoolNode` (`node/report_rule.py`: each offer split
into firm and tentative kW, and an alarm holds the node out of every sale) with `buyers`; and `QuietNode`, a `PoolNode` that reports
by exception, with `report_rule = "exception"`. A node:

- replays its profile from the dataset (`replay.Replay`) on simulated devices (`node/simulator.py`, `node/simulator_building.py`).
  No real device is driven: the simulated driver acts on the replay, and every real driver in `node/drivers.py` refuses every
  write.
- forecasts the window (`forecast = "temp_regression"`, a straight-line fit on temperature, or `"trained"`, the quantile models in
  `$MURMUR_MODELS_DIR`; a building forecasts its own record by the temperature line, or with `"same_kind_day"` by the last day of
  the same kind) and works out its safe offer per half hour: kW by part (battery, car pause, cooling, lights, appliances), the
  evening after the window at four delivery levels for the rebound guard, and the car's restart.
- checks a commitment against that offer and installs the plan for the window. With `control_mode = "rolling"` a home's controller
  re-plans every 5 dataset minutes over its battery, its car's charging and its cooling (`node/rolling.py`, `node/control.py`); with
  the default, `fixed`, it keeps the installed plan and answers every ask of the gap desk with 0 kW. A building always runs `rolling`.
- reports a shortfall it sees coming (`rt_capacity`), answers the gap desk's ask (`rt_answer` to an `rt_ask`) and takes on what the
  desk dispatches (`rt_dispatch`: more on top of its booking, or a release).
- signs one meter reading per half hour it owes, in two copies: one with the simulator's `truth` to the community agent, one
  without it to the first buyer (`utility_name`), which its host copies to every other buyer. A `QuietNode` holds its readings,
  per receiver, and sends each receiver one `batch` envelope 45 minutes after its last reading (225 minutes after its first at the
  latest). Only a `QuietNode` answers a chase for missing readings (`readings_wanted`).

What leaves a node is checked against one list (`node/amount.py`): amounts, and the figures the market needs to check and place
them (the evening's rebound curves, the car's restart, the sizes of battery, cooling and lighting, a what-if day's weather, the
agent's decision tag). No note, reason or device list goes on the wire: a commitment's answer carries its status and no reason,
and a shortfall report carries no cause but `drift` (the forecast changed) and `abnormal` (a closed building).

A node has an agent when `llm_enabled` is on and `thinking_homes` names it (a list of names, or a count that takes every 10th home
first) or `thinking_buildings` does (every building unless a list narrows it). The agent runs the nine steps of `node/agent.py`
(`node/building_agent.py` for a building):

| Steps | Who decides | What happens |
|---|---|---|
| 1 to 4 | code | schedule, forecast, devices, what can be sold |
| 5, 6 | code (`node/offer_rule.py`) | the offer as a share of the safe offer and the answer to a commitment, under the owner's wishes (a home) or the manager's policy (a building) |
| 7 | code | 30 dataset minutes before the window (`MURMUR_LEAD_MIN`): the plan of device calls for the sale |
| 8 | code | an exception (a limit fell, a note, the car plugged in, a battery trip, a call, a shortfall): the plan again |
| 9 | code and model | at the window's end code writes the facts, the model words them for the person, and only the numbers (`owed_kw`, `sold_kwh`, `delivered_kwh`, `short_kwh`) go to the community agent |

Every device call goes through the node's context server (`node/context.py`): the step's menu, the policy (`node/policy.py`, deny by
default), the guard (`node/guard.py`, `node/guard_building.py`: life safety, the person's limits, the device's card, the wishes,
what the sale may take), the seal (`drivers.Gate`: only a sealed ticket's command reaches a driver) and the driver. A person's note
is read by the model into wishes from a fixed list (`node/note_reader.py`); code keeps them and the guard holds them. Every decision
leaves a receipt in the node's decision record (section 7.1).

### 1.2 The hosts

A host (`agents/host.py`, `NodeHost`; `agents/building.py`, `BuildingHost`) runs every node it names in one process: cfg `homes`,
else every replayed home of `fleet_v2.json`; cfg `buildings`, else every building of `buildings.json`. Each node has its own replay,
simulated devices, key, bus session and lock; a node with an agent has its own thread (`Thinker`: its mail first, then the newest
step), and the agents share one door to the model (`node/llm_client.py`, `SharedModel`: `llm_slots` requests at a time, an exception
before a sale step before a report).

- A tick loop passes over every node once a second.
- Poll workers (`host_poll_workers`) check the nodes' inboxes with short checks, never a held long poll: every `host_poll_seconds`
  for a minute after mail, every `host_poll_idle_seconds` otherwise, and a claim pass every `host_sweep_seconds` anyway.
- Sends go through a pool; a send that fails is tried again under the same id after 5, 15, 45, 120 and 300 s. A single reading
  that fails is sent again by its node at its next tick instead. A reading or batch addressed to the first buyer goes, the same
  signed body, to every other buyer in cfg `buyers` under `<id>:<buyer>`, and a batch goes to its own receiver under `<id>:<receiver>`.
- A message is acted on once: a copy still being worked on is left alone, and one already finished is only acknowledged, with the
  status the first came to.
- `POST /person/{node}` takes a person's signed word: the one way an alarm ends and a limit goes up.

Doors: `GET /health`, `/telemetry` (each node's latest row; with `since`, up to 192 rows after that dataset time, which the runner's
meter feed reads), `/homes/{name}`, `/agents`, `/agents/{name}/receipts`, `/demo/clock`; `POST /person/{name}`, `/demo/reset`,
`/demo/clock` and `/demo/scenario`, which takes `weather` (`pv`, `load`, `dT`, `from`, `hours`), an `override` of one node (homes:
`ev_now`, `comfort`, `stop`, `depart_at`, `clear`, `note`, `alarm`; buildings: `comfort`, `lights`, `stop`, `clear`, `alarm`),
`battery_fault`, `closed` and `zone_event` (buildings only) and `reset`. The buildings' host serves each building also under
`/b/{name}/`: `health`, `telemetry`, `v2/status`, `demo/reset`, `demo/clock`, `demo/scenario`.

### 1.3 The community agent

One process stands for one community (`agents/community/service.py`, `CommunityAgent`). It holds the community's key and the keys
it pinned at first contact, takes every message from its inbox (`Market.handle` for the market's kinds, `Market.from_above` for the
aggregator's; one past its time to live is acknowledged `rejected` unread), ticks the market once a second and runs the waiting
clock (section 4). Its members, the roster, are cfg `roster` (else every home of `fleet_v2.json`) plus the buildings cfg
`buildings` names. With cfg `buyers` the market is pooled: every buyer's order on a window fills from one pool.

| Component | Modules (`agents/community/`) | What it does |
|---|---|---|
| Market | `market.py` with `market_above.py`, `market_orders.py`, `market_clearing.py`, `market_delivery.py`, `market_settle.py`, `market_rules.py` | one sale per window: each buyer's order at the door (one buyer's bad numbers cost that order only), the pool all orders on a window share, the call for offers, the contract with each buyer and with each member, the readings the sale is owed, the settlement |
| Forecast | `forecast.py` | with `community_forecast` (on by default in a pooled market), when the call for offers goes out: the base demand of the member homes in `fleet_v2.json` by hour for the sale's day, cars excluded and buildings not in it, with its 10/50/90 % range, kept on the sale's record (`outlook`); with fewer than 21 days of history the dataset's community model stands in; a missing model or missing data never stops a sale |
| Cover and promise | `community.py` | with a community definition (cfg `community`), no half hour is promised upward beyond the cover's share of what the members offered: 1/(1 + `clear_margin`) until 3 sales are on record, then the lower of that and the lowest share delivered over the last 10 sales whose result was in by the clearing. Each half hour sold is then checked against the connection's limits (`limit_out_kw`, `limit_in_kw`) on the meter's expected reading and the members' batteries' planned output, and cut to fit |
| Clearing | `market_clearing.py` | the book per half hour (firm power to the orders in proportion to their size; tentative power as far as each buyer's deposit holds it), a second round to members that held back when the pool is short, the rebound guard (the evening after the window may not peak above the evening without the sale; each paused car restarts in the valley that keeps the total lowest), and each member's share with the margin on top |
| Gap desk | `gaps.py`, `gaps_calls.py`, `gaps_settle.py`, `gaps_rules.py` | a buyer's call (`rt_call`) or the members' reported shortfalls beyond the margin, filled from the biggest answers and dispatched (`rt_dispatch`); a call is confirmed to its buyer (`rt_confirm`). A call asks every member, and under the exception rule goes out in waves of 32 members, biggest first, doubling while it is short. A gap asks only helpers, never a member that reported a shortfall: inside a booked sale its accepted members, elsewhere the roster; under the exception rule only those with room on file. A gap still open goes up the price ladder (x1.0, x1.25, x1.5); then the buyers are warned. The desk logs each gap it takes up as `rt_gap`, which is no message. A buyer may end its call early (`rt_end`), which releases what was dispatched from then on. A call's settlement pays the members the desk dispatched, and what is left of the bill is the call's `fee_usd` |
| Report | `community_feed.py`, `market_above.py` | with a community definition: one row per quarter hour in the participants' layout (`entity_id`, `timestamp`, `reported_p_net_kw`, `reported_soc_percent`, `quote_side`, `quote_price_usd_kwh`, `text`, `meter_p_net_kw`), naming no member, sent once to its aggregator, signed |
| Requests from above | `community_asked.py` | the aggregator's signed request for the members' batteries (kW and price by quarter hour), taken or refused with the reason; a request asks and never orders |
| Members | `members.py`, `community_rules.py` | the member record from the definition: each member's connection point, devices by kind and size, the kinds of sale it agreed to (`evening_sale`, `grid_call`) and a pay share. An offer from a member off the record, or for a kind of sale it has not agreed to, is refused; an opt-out in the record's file is honoured, and no code adds one. What members' messages may say is checked at the market's door (`offer_problem` in `market_rules.py`, `settlement/market_checks.py`) |
| Settlement | `market_settle.py`, `settlement/` | each buyer's bill checked against the market's own sums from the meters, split by measured delivery at the price book's class shares, paid once; readings that come late are paid as top-ups |

A sale's phase (`/v2/summary`) runs `offers`, `clearing`, `cleared`, `utility` (the contract with the buyers), `homes` (the
members' commitments), `settling` and `done`. It ends `failed` when the buyers' contract is not ACTIVE by the order's `commit_by`
(16:00 the day before) or after `utility_retries` rounds, and `no_offer` when the clearing leaves nothing to sell.

Doors: `GET /health`, `/v2/summary`, `/v2/events/{id}` (with `signed=true` the whole record: every signed reading as it came, and the
pinned keys), `GET` and `POST /demo/conductor`, `POST /demo/start`; with a community definition also `GET /v2/community`,
`/v2/community/report?n=` and `POST /v2/community/feed`.

The definition (cfg `community`) is `id`, `point`, `limit_out_kw` and, where there are any, `limit_in_kw`, `battery` (`rating_kw`,
`energy_kwh`, `out_factor`, `in_factor`, `run_by_agent`), `solar_kw`, `meter` (kW by time), `members` (`member`, `connects_at`,
`devices`, `sales`, `pay_share`, `at`), `report_when_ended` and `aggregator` (`id`, `public_key`). Its meter comes in through
`POST /v2/community/feed`: rows by quarter hour, each a `ts` and at least one number of `meter_kw`, `expect_kw` (the meter without
the batteries or the sale, on which the limits are checked), `battery_kw`, `soc_pct` and `price_usd_kwh`. A row with any other field,
or a number out of range, is refused, and the whole feed with it. With an aggregator on record, what the members' batteries are to
give (`battery_kw`) comes only from the aggregator's signed request; without one it comes in through the feed. A community has its
members' batteries, not a battery of its own: with `battery.run_by_agent` the agent steps them itself each quarter hour with a single
site's arithmetic (`agents/site.py`) and is fed `idle_kw`, `own_kwh`, `recorded_kw` and `store_kwh`; otherwise their power and
charge come with the feed.

### 1.4 The aggregator

`agents/aggregator.py`. Its requests (`aggregator_requests`: each `{id, to, made_at, rows}`, a row a `ts` with `battery_kw` and, for
a community, `price_usd_kwh` or, for a data center, `pause_kw`) and its participants (`aggregator_communities`: each one's id,
connection limit and public key) come from its settings; the community agent and the single sites are participants alike. With
`aggregator_waits_for_start` (on by default) it sends nothing until its clock is set. At each request's `made_at` it sends
`community.request`; it notes each `community.answer`; it checks each `community.report` row against the participant's key and
keeps it, and flags a charge outside 10 to 90 %, more sent out than the connection allows, or the same power four quarter hours
running where it did not ask for one flat amount. A second, different row for a kept quarter hour is refused; the first stands. It
keeps 14 days of rows per participant. Doors: `/health`, `/aggregator`, `/aggregator/rows`, `/demo/reset`, `/demo/clock`.

### 1.5 Single sites

`agents/site.py` (the site's arithmetic) and `agents/site_service.py` (its process). Its settings: `site` (`id`, `kind` `pv_bess`
or `datacenter`, `rating_kw`, `energy_kwh`, `out_factor`, `limit_out_kw`, `wait_h`), `site_feed` (by quarter hour: `base_kw`,
`recorded_kw`, `own_kwh`, `share`, `price_usd_kwh`, and `store_before_kwh` for the first), `site_limits` (`give_max_kw`, `hold`,
`pause_max_kw`, and `why`, the line its answer gives) and `site_aggregator` (`name`, `public_key`). A site takes a request only from
its aggregator, under that key, and answers what its limits allow, with the reason wherever that is less. A request with a row it
can't read (a time not written `YYYY-MM-DD HH:MM`, a kW that is not a number of 0 or more) gets a signed refusal with the reason. An
answer the bus did not take goes again, under the same id, when the request comes again or at a later tick. It steps each quarter
hour of its feed in order, none skipped, and reports one row per quarter hour. Its battery stays between 10 and 90 % of its charge,
only charges from 12:00 and follows the request from 14:00; a data center may also pause work that can wait and runs it back evenly
before it is due. Doors: `/health`, `/site`, `/demo/reset`, `/demo/clock`.

### 1.6 The buyers

The buyers are stand-ins (`demo/runner/buyers/`): `utility` and `grid-operator`, one class under two names. A buyer:

- turns an order (`POST /needs`, before 10:00 the day before) into that day's signed need: a demand-flex need and its buy offer, kW
  and price per half hour, a deadline of 16:00 the day before, and a deposit where the order carries one;
- answers the community agent's `discover`, contracts with it (`select`, `init`, `confirm`) and enrols the participating meters;
- sends each meter's baseline: the mean of the last 10 days of the same kind, with the same-day adjustment where the price book
  sets it;
- checks each signed reading against the key it pinned for that meter at its first reading, and settles;
- turns an alert (`POST /alert`) into an `emergency` call (`rt_call`) at twice the program's price, settled on what the meters show
  beyond the booking. The price rule that would make a `short_notice` call is off in the stand-in.

Only the community agents a buyer has enrolled (`utility_aggregators`, by default `community`) may discover and contract with it.
Doors: `GET /health`, `/contracts`, `/evidence/{event_id}`, `/events`, `/traffic`, `/calls`, `/demo/clock`; `POST /needs`, `/alert`
(`kw`, or `pct` of the program's kW; `minutes`, 15 to 240; `why`; `at`), `/demo/reset` (with `clear_orders` every order goes) and
`/demo/clock`.

### 1.7 The message bus

The bus is any server of a small HTTP contract (version 0.2.0). Its address is the setting `town_url`, and the run is `town_run_id`.

| Call | What it does |
|---|---|
| `POST /runs/{run}/join` | a session for a name, with the run's grant and a proof of the session key, or with a join token; a join ends the name's earlier session |
| `POST /runs/{run}/messages` | one message id, one message; the same message again (sender, receiver, kind and body) is a replay, anything else under a taken id is refused (409) and goes nowhere |
| `GET /runs/{run}/inbox/notify` | a wake-up hint, never a held long poll |
| `POST /runs/{run}/inbox/claim` | the oldest message, leased with a fence; a lease that runs out hands it out again |
| `POST /runs/{run}/inbox/ack` | done (`processed` or `rejected`), with the fence; a stale fence is refused |

Every call but the join carries its session in the `X-Town-Session` header; the bodies, answers and status codes are in
PROTOCOL_AND_SAFETY.md section 6. A handled message is acknowledged `processed` and a refused one `rejected` (a batch partly
refused stays `processed`, with a count).

The client (`protocol/transport.py`, `TownSession`) tries a call once more on a dropped connection or a 502, 503 or 504, joins again
on a 401, and pauses 60 s when its name is taken three times in two minutes: one process per name. `protocol/inbox.py` watches an
inbox with short checks and brings in several claimers when mail comes. Every body is a signed Beckn v2 demand-flex envelope
(`protocol/envelope.py`, `protocol/signing.py`) with a time to live: 900 s for a message that matters only while the market decides,
a day for a statement of fact (a reading, a report row, a settlement, a payment). Ids are stable (`protocol/ids.py`): a retry names a
message again, an answer takes its id from the message it answers, and a message nobody asked for takes its id from its sender's
key, its play tag and what it says. The community agent, the buyers, the aggregator and each site append one line per signed message
they send or receive to a wire log (`protocol/wire.py`).

## 2. Who talks to whom

```
      utility ──┐                                    ┌── aggregator ──── site-pv-01, site-dc-01
grid-operator ──┤ discovery, contract, baselines,    │   request, answer, report rows
                │ settlement, calls                  │
                ▼                                    ▼
          ┌──────────────────────── community agent ────────────────────────┐
          │ market · forecast · cover · clearing · gap desk · report ·      │
          │ settlement split · waiting clock                                 │
          └────────────┬─────────────────────────────────────┬──────────────┘
                       │ call for offers, commitments,       │
                       │ notices, chases, pay, gap desk      │
                       ▼                                     ▼
                 homes' host                           buildings' host
                 home-01, home-02, ...                 building-01, building-02
                       └── each member's signed readings also go to every buyer ──┘
```

Every line in the diagram is a signed message on the one bus. The clock and the demo's doors are plain HTTP (section 4).

| Kind on the bus | From | To | Carries |
|---|---|---|---|
| `beckn.discover` | community | each buyer | `intent.date`: tomorrow's needs, asked from 10:00 until the buyer answers |
| `beckn.on_discover` | buyer | community | catalogs: each need with its offer |
| `beckn.discover` | community | each member | `intent.need`: the call for offers, the whole pool the orders ask; with `more`, the second round |
| `beckn.on_discover` | member | community | `offer`: kW per half hour (firm, tentative, by part), confidence, energy, what it held back, the evening's rebound, the car's restart |
| `beckn.select`, `init`, `confirm` | community | each buyer | the contract steps; `init` names the participating meters, the capacity and the buyer's share of the pool |
| `beckn.on_select`, `on_init`, `on_confirm` | buyer | community | the contract, DRAFT, then ACTIVE |
| `beckn.confirm` | community | member | the commitment: kW per half hour, price, opt-out time, the car's restart, the pre-charge, the settlement rule |
| `beckn.on_confirm` | member | community | ACCEPTED or DECLINED; the reason stays on the node |
| `beckn.cancel` | community | member | a yes that came after the contract with the buyers was final: stand down |
| `beckn.update` | community | each buyer | the final contract (meters, capacity, each meter's half hours); later `telemetry_done`: the readings are in |
| `beckn.update` | community | member | the event notice two hours before the window (not under the exception rule) |
| `beckn.on_status` | buyer | community | `performance.kind = "baselines"`; `readings_lacking`; the settlement with the actuals; a call's settlement |
| `beckn.on_status` | member | community and each buyer | its signed readings: the community's copy with `truth`, the first buyer's without, which the host copies to every other buyer; under the exception rule one `batch` envelope per receiver |
| `beckn.on_status` | member | community | `node_report`: owed, sold, delivered and short, as numbers |
| `beckn.on_status` | community | member | the payment, the delivered and committed kWh, its reputation |
| `beckn.status` | community | member | `readings_wanted`: the half hours to send again |
| `beckn.rt_call` | buyer | community | a short-notice or emergency call (the stand-in buyer calls on an alert) |
| `beckn.rt_end` | buyer | community | a call's early end, which releases what the desk dispatched after it; the stand-in buyers never send one |
| `beckn.rt_ask`, `rt_answer` | community, member | member, community | how much more a member can add |
| `beckn.rt_dispatch` | community | member | what it owes on top of its booking, or a release |
| `beckn.rt_confirm` | community | buyer | what is confirmed of a call, who owes what, an early warning of a shortfall |
| `beckn.rt_capacity` | member | community | `short`: the kW it sees itself short by quarter hour, with the flags `drift` (the forecast changed) and `abnormal` (a closed building) |
| `community.request` | aggregator | community or site | battery kW (and a data center's pause kW) by quarter hour, and the price where given |
| `community.answer` | community or site | aggregator | taken or refused, the rows taken, why |
| `community.report` | community or site | aggregator | one report row per quarter hour |

Trust is by key. A member takes messages only from the name `community` signed by a key in `community_pubkeys`. The community agent
pins each member's and each buyer's key at its first signed message, and holds each member's claim to its enrolled nameplate. The
community agent and the aggregator check each other against the keys their settings enrol (`community.aggregator.public_key`,
`aggregator_communities`). Where none is enrolled, the community agent pins the key of the aggregator's first message, and the
aggregator pins a participant's key only once that participant's first message verifies under it. A site checks the aggregator
against `site_aggregator.public_key`. A buyer takes contract steps only from the community agents it enrolled, and readings only
from meters enrolled in its contract for that sale. Every `POST` door of the community agent, the hosts, the buyers, the aggregator
and the sites asks for the control token in `X-Murmur-Token` once `secrets/control_token` exists; `GET` doors are open. A token file
that is empty or can't be read shuts every `POST` door. The community agent sends its own token with its clock posts, so every part
whose clock it keeps needs the same token. The runner writes none: every door of a demo run is open.

## 3. An evening, from the day before to settlement

D is the evening's day and W its window. Times are dataset times, read off the community agent's clock; the figures are the code's
defaults and the stand-in buyers'.

| When | What happens | Messages |
|---|---|---|
| D-1 09:45 | `/demo/start` sets every participant's clock to this step, held, before the runner's gate at 10:00; the runner places each buyer's order (`POST /needs`) and opens the gate | HTTP doors |
| D-1 10:00 | the community agent asks each buyer for tomorrow's needs; the clock waits for the first buyer's answer, until 16:00 at most | `discover`, `on_discover` |
| every buyer asked has answered (a silent buyer holds it 30 s at most) | the call for offers goes to every member; with `community_forecast`, the community forecast is made | `discover` with the need |
| offers come in | each offer is checked at the door (member record, nameplate, numbers); members with no offer in hear the call again every 30 minutes | `on_discover` |
| all offers in, or 90 minutes before the clearing's deadline | a second round to members that held back, if the pool is short | `discover` with `more` |
| all offers in, at the latest 16:00 - 180 minutes (13:00) | the clearing, the cover, the connection's limit; the sale goes on the sales record | none |
| then | the contract with each buyer, tried again with a growing wait; the sale fails if it is not ACTIVE by 16:00 or after 5 rounds | `select`, `on_select`, `init`, `on_init`, `confirm`, `on_confirm` |
| every buyer ACTIVE | each allocated member's commitment; a decline is topped up from spare offers, a member that hasn't answered hears it again after 30 minutes | `confirm`, `on_confirm`, `cancel` |
| every commitment answered, or 16:00 | the final contract to each buyer, sent until the bus takes it; each buyer answers with the baselines | `update`, `on_status` |
| D 14:00 (the example's request) | the aggregator's request for the members' batteries and the sites' batteries | `community.request`, `community.answer` |
| W - 2 h | the event notice, except under the exception rule, where the commitment carries the pre-charge | `update` |
| W - 30 minutes | each agent plans the sale (step 7) | none |
| each quarter hour | one report row from the community agent (once the quarter hour has ended, with `report_when_ended`) and one from each site | `community.report` |
| W | delivery; members report shortfalls they see coming; the gap desk fills them; a buyer's alert becomes an emergency call | `rt_capacity`, `rt_ask`, `rt_answer`, `rt_dispatch`, `rt_confirm`, `rt_call` |
| end of W | each agent's report (step 9) | `on_status` with `node_report` |
| end of W + 45 minutes | each member's held readings: one envelope to the community agent and one to the first buyer, which the host copies to every other buyer | `on_status` with `batch` |
| from end of W + 15 minutes | once no reading is missing, the community agent tells each buyer the readings are in. From end of W + 60 minutes, once no reading has come for `readings_quiet_s`, it asks members for missing readings every 30 minutes (the gap doubling after 3 rounds). After `readings_wait_minutes` (120), 3 rounds and a quiet inbox, or at 120 + 240 minutes regardless, the buyers are told anyway, with what is missing on the record | `update` with `telemetry_done`, `status` with `readings_wanted` |
| a buyer has every reading, or 30 minutes after it said what it lacks | the buyer's settlement, with the actuals | `on_status` with `readings_lacking`, then the settlement |
| every buyer settled | the split: each member paid by measured delivery, reputations moved (0.7 of the old mark and 0.3 of the share delivered, at most 1.2; a member with no counted reading keeps 0.7 of its mark); the sale's record is written | `on_status` with the payment |
| later readings, for a day | top-up settlements and top-up payments; a buyer that has not settled is asked again every hour | `on_status`, `update` |

The demo runner follows the sale. Once the sale is `done` with no reading missing it tells the clock to hold, and it ends `settled`
when the clock says the step in hand is finished. It ends at once on `failed` or `no_offer`; where the clock stands before the
evening's last step, 03:00 the morning after, or on the last step of the data (`settled, with an alarm standing` when the sale is
done, else `not settled`); or `timed out` when neither the clock nor the sale has said anything new for a step's pace and 900 s
more.

## 4. The waiting clock, its gates and its leaps

Every participant keeps the dataset's clock (`replay.Replay`): wall time mapped onto 15-minute dataset steps, on an absolute line that
the community agent sets for all of them, so they agree on the step at the same wall moment. A held clock stays on its step until it
is set again. The loop that works by a clock (a host's tick, a site's, the aggregator's, a buyer's, the market's) starts its next pass
as soon as the clock is set, and the part's `GET /demo/clock` answers `ticked`: the dataset time of that loop's last whole pass since
then. A clock set several quarter hours on loses none of them: a home steps each in order (192 at most) and its host gives back as
many meter rows, a site steps and reports each, and the community agent writes a report row for each.

With `clock_waits`, the community agent moves every clock (`agents/community/conductor.py`). `POST /demo/start` (`event`;
`step_seconds` from 2 to 120, the participants' own clock setting; `pace_s` from 0 to 120, when not given `step_seconds`; `leap`;
`lead_s`) posts `/demo/reset` and then `/demo/clock` to every participant it knows (the first buyer at `utility_url`, the homes' host
at `host_url`, each building at `building_urls`, the rest at `clock_extra_targets`), sets them to 09:45 the day before the event,
held, all starting `lead_s` later, and starts the clock loop. It refuses with 503 while the agent's inbox is still clearing old
messages, unless `force` is set.

The loop looks at the step every clock holds: at once after a move, every `clock_poll_s` (0.05 s) while that step waits on the
participants, at the end of a played step's pace, and every 0.5 s while nothing can move; a word at its door or a meter reading fed
wakes it at once. A step that is played is finished when all of these hold:

1. It has lasted its pace: `pace_s` as the start or the door set it (0: no time of its own), else `step_seconds`; never less than
   `clock_min_step_s`.
2. Every node service (`clock_wait_urls`, by default the homes' host and the buildings' host) says through `GET /agents` that all
   its nodes ticked at this step, no agent is deciding, no message is leaving, and none left in the last `clock_wait_quiet_s`.
3. Every other participant that says how far its loop is has caught up with this step (`ticked`: the buyers, the aggregator, the
   sites; one that does not say, or does not answer, is not waited for), and so has the market's own loop. With `clock_wait_meter`,
   the community's meter holds a reading for every quarter hour since the step the clocks moved from.
4. No signed message other than a meter reading went through the community agent's wire log or the first buyer's in the last
   `clock_wait_quiet_s`. A clock that runs fast (it leaps, or its pace is under `step_seconds`) also waits that long from the moment
   every participant had caught up, the time an inbox takes to be looked at; one that leaps does not wait after a report row the
   community sent upward, which nothing answers.
5. The market waits on nothing only an answer can bring: offers to come, the buyers' contract, commitments to answer, the buyers'
   settlement, a call's answers, readings due, reports the gap desk has not read, and from 10:00 to 16:00 the day before, the first
   buyer's answer for tomorrow.

Then the agent posts the step the clocks move to, held, to every participant in parallel and moves its own clock. Once every node
service has finished a step, the gap desk reads that step's shortfall reports together.

- **Leaping.** With `clock_leap`, or `leap` at the start or at the door, the clock plays only the steps something is scheduled at
  and moves over the empty quarter hours between them in one move: to the next stop, or `clock_leap_max_steps` on (12 by default,
  192 at most) when no stop comes first. A stop is a gate (and, once it is opened, its step and the one after), a step the driver
  named (`stops`, `run_to`), the last step of the data, and every quarter hour the market has something at
  (`market_schedule.py`): the day's question from 10:00 to 16:00 while a buyer has not answered it, a sale's contract while it is
  open, its notice, its evening from `clock_lead_minutes` (30) before the window through its readings to its settlement, and a call
  of the gap desk. An empty step the clock lands on lasts no pace and no inbox's time: it is finished once every participant has
  caught up and nothing else of the list is still to come. Each leap is on the record with the wall time it took (`leaps`, and a
  `clock_leap` event).
- **Going on.** When the list of waits stays the same for `clock_wait_idle_s` (180 s by default; the runner sets 600 s), the clock
  goes on without them, and each such step is on the record (`went_on`, and a `clock_went_on` event).
- **Lines sent again.** A participant a post does not reach is named once (`clock_not_reached`). Every 20 s the agent reads each
  participant's clock and sends its own line again to any part on another line (`clock_sent_again`).
- **Gates.** `POST /demo/conductor {"gates": [step, ...]}` names steps the clock stops before. At a gate the clock holds on the step
  before it with everything else done, and `GET /demo/conductor` shows `at_gate`. A runner posts what happens at that step and opens
  it with `{"open": step}`, so a scripted event lands before any node sees its step. Gates and stops stay through `/demo/start`.
- **A driver's word.** The same door takes, alone or together: `{"stops": [step, ...]}`, steps of the data a leap must land on (a
  new list takes the old one's place); `{"leap": true}` or `false`; `{"pace_s": 0 to 120}`; `{"hold": true}`, which stops the clock
  once the step in hand is finished, and `false`, which lets it go on; `{"step": n}`, which plays n steps, a leap counting as one,
  and holds again; `{"run_to": step}`, which goes on to that step and holds there. A word that cannot be read is refused whole (400).
- `GET /demo/conductor` says whether the clock waits, the step it holds, the steps moved, the seconds held beyond the pace, what it
  waits on now, every step it went on without something, its gates, its stops and the next step it must play (`next_stop`), its
  pace, whether it leaps and how far, whether the driver holds it, its last 50 leaps (`from`, `to`, `steps`, `wall_ms`) and its last
  50 played steps (`sim`, `wall_ms`, `waited_on`), and its `mode`: `idle`, `playing`, `waiting`, `leaping`, `at_gate`, `held` or
  `ended`.

## 5. The package

The package (`pyproject.toml`) needs Python 3.11 or later with numpy, scipy, httpx, fastapi, uvicorn and cryptography; its extras
are `dev` (pytest) and `experiments` (pandas, pyarrow).

```
src/murmur/
  config.py      settings: DEFAULTS, then the dataset's agent_defaults, then the part's agent.json; the MURMUR_* folders
  files.py       files written whole or not at all, set aside when unreadable; the code stamp /health reports
  replay.py      the dataset's replay clock, and the what-if weather
  protocol/      the wire
  node/          a member node and its agent
  agents/        the processes: the hosts, the aggregator, a single site
  agents/community/   the community agent
  settlement/    what a reading may say, the baselines, the pay rules
```

| Package | Modules | What they hold |
|---|---|---|
| `protocol/` | `envelope.py`, `signing.py`, `ids.py`, `transport.py`, `inbox.py`, `doors.py`, `wire.py` | the signed Beckn v2 envelope and its time to live; Ed25519 over canonical JSON and the key files; stable message ids; the bus client and its journal of sent bodies; the inbox poller; the control-token door; the wire log |
| `node/`: protocol | `home.py`, `home_forecast.py`, `home_offer.py`, `home_delivery.py`, `home_days.py`, `report_rule.py`, `amount.py`, `grounds.py`, `telemetry.py` | the member's side of the market: forecasts, the safe offer, the commitment, readings, the exception rule, what may leave the node |
| `node/`: simulation | `simulator.py`, `simulator_rolling.py`, `simulator_rules.py`, `simulator_building.py`, `context_sim.py`, `rolling.py`, `control.py`, `hvac.py`, `devices.py`, `surprises.py`, `buildings/` | the simulated home and building on the replay, the 5-minute controller, cooling, the extra devices (a home's by `MURMUR_DEVICES`, a building's own always), a building's closure or zone event, the zone maps (`office.json`, `shopping_center.json`, and `schedules.npz`, each zone's planned and true occupancy) |
| `node/`: forecasts | `forecast.py`, `treemodel.py` | the trained quantile forecasts, evaluated with numpy |
| `node/`: the agent | `agent.py`, `agent_levers.py`, `agent_notes.py`, `agent_plan.py`, `building_agent.py`, `building_levers.py`, `building_plan.py`, `see.py`, `see_building.py`, `offer_rule.py`, `offer_shape.py`, `report.py`, `note_reader.py`, `note_words.py`, `modes.py`, `llm_client.py` | the nine steps, code's plans, the offer rule under the person's standing limits, the note reader, the report, the model client |
| `node/`: the road to a device | `context.py`, `calls.py` with `home_plans_past.npz`, `policy.py`, `guard.py`, `guard_building.py`, `guard_building_rules.py`, `guard_building_tools.py`, `drivers.py`, `tools.py` with `tools.json`, `shelves.json`, `home_setup.json` | the context server, the call checks and the homes' day-before plans, who may change what, the guards, the seal and the drivers, the tool cards and each node's shelf |
| `node/`: records | `record.py`, `person.py` | the decision record; a person's word, the alarm and the signed limits on disk; the deploy's commands for the token and a person's key |
| `agents/` | `host.py`, `host_common.py`, `host_people.py`, `host_doors.py`, `home.py`, `building.py`, `aggregator.py`, `site.py`, `site_service.py` | the hosts and their doors, the aggregator, a single site |
| `agents/community/` | `service.py`, `doors.py`, `conductor*.py`, `community.py`, `community_asked.py`, `community_feed.py`, `community_rules.py`, `members.py`, `forecast.py`, `market*.py`, `gaps*.py` | the community agent (section 1.3) and its waiting clock (`conductor.py`, with what a step waits on, which steps must be played, and its door) |
| `settlement/` | `rules.py`, `meter_check.py`, `market_checks.py` | the baseline rule, the class shares and keeps of the price book, the split; what a reading, an order, a call and a settlement may say before money moves |

The rest of the repository: `demo/runner/` (section 6), `demo/page_builder/` (the demo pages, from the recorded evenings in
`demo/recordings/`: `python -m demo.page_builder.build --out DIR`), `experiments/engie/` (offline pipelines on the aggregator's data:
meter cleaning, peak allocation, the referee, the year runs), `tests/` and `scripts/verify_clean_repo.py` (the trace scanner:
`python scripts/verify_clean_repo.py .`).

The suite runs with `pytest` from the repository root (`testpaths` in `pyproject.toml`). `tests/conftest.py` points
`MURMUR_DATA_DIR` and `MURMUR_MODELS_DIR` at the synthetic fixtures in `tests/fixtures/`, sets `MURMUR_DEVICES` to the fixtures'
devices, gives the session a fresh configuration and log folder, and removes every other `MURMUR_*` variable but
`MURMUR_ENGIE_DATA_DIR` and `MURMUR_PUBLISHED_DIR`; a test marked `engie_data` skips without the first, and the comparison with the
published pages in `tests/page_builder/test_pages.py` without the second. `python tests/fixtures/make_fixtures.py` writes the
two-day fixtures.

### Settings and addresses

Every address a part listens on or calls is a setting. Each service listens at `bind_host` on the port its settings name
(`community_port`, `host_port`, `buildings_port`, `aggregator_port`, `site_port`; a buyer's `--port`); the local bus, the stand-in
model and the state feed take `--host` and `--port`.

| Setting | What it names |
|---|---|
| `bind_host` | the address every service listens on: `127.0.0.1`, the loopback address, unless a deployment sets another |
| `town_url`, `town_run_id` | the message bus and the run |
| `llm_url`, `llm_model` | the model server, read only with `llm_enabled` (off by default) |
| `utility_url`, `host_url`, `building_urls`, `clock_extra_targets`, `clock_wait_urls` | where the community agent's clock reaches the first buyer, the homes' host, each building and the other parts, and which node services it waits for |

| Variable | What it names |
|---|---|
| `MURMUR_CONFIG_DIR` | the part's folder: `agent.json`, `secrets/`, `state/` (unset: a folder in the user's home directory) |
| `MURMUR_DATA_DIR` | the dataset the part replays: `dataset.json`, `fleet_v2.json`, `homes/`, `buildings/`, `buildings.json`, `devices/`, `owners.json`, `hvac_params.json`, the buyers' catalog (unset: `src/data`) |
| `MURMUR_MODELS_DIR` | the trained forecast models, read with `forecast = "trained"` and by the community forecast (unset: `src/models`) |
| `MURMUR_LOG_DIR` | the part's logs (unset: `logs/` in its folder) |
| `MURMUR_DEVICES` | the homes' devices besides batteries and cars that take part: `all` or a comma list; unset, none. A building's own fans, plugs and car ports always take part |
| `MURMUR_DRIVERS` | the drivers behind the context server: `simulated` by default |
| `MURMUR_LEAD_MIN` | how long before the window an agent plans the sale (30) |
| `MURMUR_BATTERY_MODE` | `backup`: a battery is held for sales, gives nothing to its own house and refills from the grid overnight at 2 kW; a building's battery needs it |
| `MURMUR_CHARGE_KW` | a cap in kW on a home battery's charging, unless the owner's limits set one |
| `MURMUR_CAREFUL_NOTES` | the careful note step, in place of `careful_notes` in `agent.json` |
| `MURMUR_ENGIE_DATA_DIR` | the aggregator's dataset, for `experiments/engie/` and its marked tests |
| `MURMUR_NOTES_MODEL_URL`, `MURMUR_NOTES_MODEL` | a model server the referee asks about the notes, in place of the recorded answers |
| `MURMUR_PUBLISHED_DIR` | the published pages `tests/page_builder/test_pages.py` compares the year results page with; unset, that test skips |

The settings that set behaviour, with their defaults (`config.py` and each reader):

| Part | Settings |
|---|---|
| every part | `replay_start` (the dataset's), `replay_step_seconds` (60), `replay_loop_days` (1); `max_message_age_s` (900) for the community agent, the nodes and the buyers; `town_poll_seconds` (1) and `town_poll_idle_seconds` (3) for all but the hosts |
| community: the sale | `roster`, `buildings` (none), `buyers` (none: one buyer, `utility_name`, default `utility`), `community` (no definition), `report_rule`, `clear_margin` (0.10), `clear_lead_minutes` (180), `fill_to_ask` and `second_round` (on in a pooled market), `community_forecast` (on in a pooled market), `rebound_tolerance` (0), `coordinator_fee_share` (0) |
| community: waits | in dataset minutes `discover_retry_minutes`, `utility_retry_minutes` (doubling), `offers_retry_minutes` and `confirm_retry_minutes` (30 each), `confirm_retries` (3), `utility_retries` (5), `readings_wait_minutes` (120); in wall seconds `discover_retry_wall_seconds` (30), `utility_retry_wall_seconds` (60, doubling), `offers_retry_wall_seconds`, `confirm_retry_wall_seconds` and `readings_chase_wall_seconds` (120 each), `readings_quiet_s` (30), `report_up_retry_s` (30), `rt_answer_wait_s` (25, plus the bus's lag up to `rt_answer_wait_max_extra_s`, 90) |
| community: workers and clock | `send_workers` (8), `inbox_workers` (4), `catchup_workers` (16); `clock_waits` (off), `clock_wait_idle_s` (180), `clock_wait_quiet_s` (4), `clock_wait_meter` (off), `clock_leap` (off), `clock_leap_max_steps` (12), `clock_lead_minutes` (30), `clock_poll_s` (0.05), `clock_min_step_s` (0); `sync_broadcast` (off: sends in line and no wall-time floors, for the tests) |
| hosts | `homes` and `buildings` (every one), `control_mode` (`fixed`), `forecast` (`temp_regression`), `buyers`, `report_rule`, `utility_name`, `community_pubkeys`, `person_keys`, `opt_out_days`, `owner_limits`, `rt_min_price` (0), `send_workers` (8), `host_poll_workers` (8), `host_poll_seconds` (5), `host_poll_idle_seconds` (15), `host_sweep_seconds` (60) |
| agents | `llm_enabled` (off), `llm_slots` (1), `llm_temperature`, `llm_seed`, `thinking_homes` (none), `thinking_buildings` (every building), `careful_notes` (off) |
| buyers | `utility_aggregators` (`community`), `utility_settle_wait_minutes` (30), `utility_settle_quiet_s` (30), `utility_inbox_workers` (12), `grid_watch` (on), `call_settle_after_min` (60) |
| aggregator, sites | `aggregator_requests`, `aggregator_communities`, `aggregator_waits_for_start` (on); `site`, `site_feed`, `site_limits`, `site_aggregator` |

## 6. What the demo runner adds

`demo/runner/` plays one evening on one machine, every part its own process at the configuration's `host` (`127.0.0.1` in
`config.example.json`, and when none is given): it is every part's `bind_host` and the host of every address the runner hands out.
From the repository root: `python -m demo.runner example`, then
`python -m demo.runner evening --config demo/runner/config.example.json`. Paths in a configuration are read from the
configuration's own folder. `evening` exits 0 when the run ends `settled` (or `settled, with an alarm standing`), else 1.
`python -m demo.runner compare RUN_A RUN_B` exits 0 when two finished runs were the same evening, 1 when they differ and 2 when a
run folder cannot be read.

| Module | What it adds |
|---|---|
| `__main__.py` | the commands: `example [--out FOLDER]`, `evening --config FILE [--feed-port N]`, `compare RUN_A RUN_B`, `feed --run FOLDER [--host H] [--port N]`, `bus [--host H] --port PORT --runs FILE` |
| `settings.py` | one JSON configuration (`config.example.json`): the run's id, the host every part listens on and is called at, a fresh run folder, the ports (`"free"` or a block from 51000), the data and model folders, the evening, the sites, the participants' clock setting (`step_seconds`, 2 to 120), the pace of a played step (`pace_s`, 0 to 120; a file that names none plays at `step_seconds`), whether the clock leaps (`leap`, off unless named; on in the example) and how far at most (`leap_max_steps`, 1 to 192, 96 unless named), the quiet seconds, the devices (`all` by default), the model (`{"stand_in": true}` or a server's address on the host and its name), the scripted events, the feed's port. It is checked before anything starts |
| `bus.py` | the local message bus: the contract of section 1.7 in memory, leases of 30 s, `GET /health`, and `GET /runs/{run}/record?after=N`, every accepted message and every ack from the Nth on |
| `grants.py` | one controller key per name in the run folder; for the run, a grant naming a fresh session key (`join`, `send`, `claim`, `ack`), valid for one hour, signed by the controller; the bus pins each name's controller key and checks the grant and the session's proof at the join |
| `stack.py` | writes each part's folder (its `agent.json`, its keys, its grants and tokens, the public keys it must trust) and starts each part as its own process with only the environment it needs: the bus, the stand-in model, the community agent, the buyers, the homes' host, the buildings' host, the aggregator, each site. It waits for the bus's `/health`, then for each other part's but the stand-in model's, and stops only the processes it started |
| `evening.py` | resets the buyers; tells the clock its gates (10:00 the day before, where the buyers are asked for their orders; each scripted event's step; the evening's last step, 03:00 the morning after or where its feed ends) and its stops (the step each request of the aggregator goes at, and the quarter hour after it); posts `/demo/start` with `pace_s`; places each buyer's order (a deposit of a tenth of what it could pay) and opens the first gate; feeds the community's meter each quarter hour once every member has reported it (the feed's base load plus each member's `grid_kw - grid_cf_kw` from its host's `/telemetry`, read every eighth of the pace, between 0.05 and 0.25 s, and after a leap for every quarter hour since the last one fed); posts each scripted event at its gate (`note`, `car_now`, `building_closed`, `zone_event`, `cloud`, `emergency`); follows the sale, holds the clock once the money is final (section 3), and writes `summary.json` (with `clock`: the steps moved, every leap and played step, the seconds held beyond the pace, the run's wall seconds) and `record.json.gz`, the bus record whole |
| `compare.py` | says whether two finished runs were the same evening, from their `summary.json` and `record.json.gz`: the outcome (how each ended, the sale as the community holds it, the aggregator's view), every message that is no report row (between each sender and receiver the same messages of each kind, as often and in the same order) and the report rows as a set. Wall times, message ids, signatures, keys and the tag a run ends an id with are left out, and so is what only follows from which of two messages between different pairs came first: `result.components`, the aggregator's last 200 flags, and which buyer's order a pooled sale goes by (a note says when the two runs differ in that). It prints what differs, 20 lines of each kind |
| `feed.py` | the read-only state feed, `GET /live/state.json` (schema `murmur.live.v1`, CORS open): each part's `/health`, the community's `/v2/summary` and the buyers' `/contracts`, read every 5 s. It sends nothing to any part |
| `model.py` | the stand-in model server (`--host`, `--port`, `--ms`, `--log`): it answers a `POST` to any path after `--ms` (50 ms). Given tools, a note becomes `set_owner_wish` by its words (battery, then chiller or cooling, then car) or `no_wish`, a report is two plain sentences with no numbers, and any other question gets `no_action` where it is offered, else the first tool; without tools it answers one plain sentence |
| `buyers/` | the stand-in buyers (section 1.6): `utility.py`, `utility_orders.py`, `utility_settle.py`, `utility_doors.py`, `utility_meters.py`, `grid_watch.py`, `stand_in.py` |
| `synthetic.py`, `example.py` | the synthetic community, seeded, byte for byte the same on every machine: three homes, one office, two single sites, their devices, the price book and the buyers' catalog. `example` writes `data/` (25 days, 2025-01-05 to 2025-01-29), `models/forecast/` (three plain one-leaf tree models and `fleet_errors.json`, which keeps no day out: `community_load` gives the community's load as the mean of its own last 14 days, within 10 % either way; `home_base_load` and `solar_per_kw` are the homes' two models the community's forecaster is built on, which replaces the load one and has no array of its own), `sites.json` and `evening.json` (the evening of 2025-01-28 from 18:00 to 21:00, two orders, the community's definition, the evening's feed and the aggregator's battery request). With 22 whole days before the call for offers, the community's outlook fits its own hours there; with fewer than 21 it falls back to `community_load`. The test fixtures are its two-day form |

The runner's settings for every part: `bind_host`, the bus, the replay from 00:00 of the evening's day with no loop at
`step_seconds` a step, the rolling controller, the temperature forecast, both buyers and the exception rule, with short polls and
retry waits scaled to `step_seconds`. Every home and building gets an agent (`llm_enabled`, the model's address and name, every home
in `thinking_homes`, one model slot, temperature 0, seed 7) and the community's key in `community_pubkeys`; no other part gets a
model's address. The community agent gets `clock_waits`, `clock_wait_meter`, `clock_leap` and `clock_leap_max_steps` from the
configuration, the roster, the clock's targets (`utility_url`, `host_url`, `building_urls`, `clock_extra_targets`) and its
definition with the aggregator's id and key. The aggregator gets the evening's battery request and each site's requests, and the
community and the sites with their keys.

```
<run folder>/
  bus.json                    the run's id, each name's join token and controller public key
  run.json                    each part's address, the homes and the buildings (the feed reads it)
  controllers/                <name>.controller.key, one per name
  logs/                       one log per process; model_answers.jsonl
  summary.json                what the evening came to
  record.json.gz              every message the bus accepted and every ack
  community/                  agent.json, secrets/, state/, logs/ (the buyers run in this folder)
  homes/, buildings/          agent.json, secrets/ (town_grants.json, host_tokens.json), fleet/keys/, state/
  aggregator/, site-pv-01/, site-dc-01/    agent.json, secrets/, logs/
```

The runner restarts nothing: when one of its processes stops, the run ends with an error and the runner stops every process it
started.

## 7. Restart

Each part keeps its few files in its own folder and builds everything else again from its settings and its dataset. There is no
separate keeper process: nothing outside a part copies, watches or restores its state.

### 7.1 What each part keeps on disk

Paths are inside the part's folder (`$MURMUR_CONFIG_DIR`); logs are in `$MURMUR_LOG_DIR`.

| Part | File | Written | Read back |
|---|---|---|---|
| every part | its key: `secrets/signing.key` (community), `secrets/aggregator.key`, `secrets/site.key`, `secrets/<buyer>.key`, `fleet/keys/<node>.key` (one per node in a host) | at the first start: whole, mode 600, one key however many processes reach the name at once | at every start: the part keeps its identity |
| community | `state/home_pins.json` | each key pinned at a first signed message (members, buyers, and the aggregator where its key isn't enrolled), written whole | at start; a file that can't be read is set aside (`.old`) and each sender is pinned again at its next message |
| community | `state/community_members.json` | the member record and each enrolment, with its time | at start; a member on record is not enrolled again from the definition, and an opt-out written into the file between runs is honoured. A file that can't be parsed stops the start |
| community | `state/community_sales.json` | each sale at its clearing (offered, promised), its delivery at the settlement, and its gap to the promise for the community and each member | at start: the cover reads the last 10 sales. A file that can't be parsed stops the start |
| community | `state/community_requests.json` | each request taken from the aggregator (its answer and a digest of its rows) and the rows taken, for two days | at start, when it was written for this community and this aggregator: the members' batteries' kW and the prices by quarter hour come back, and a request delivered again gets the same answer |
| community | `state/events/<sale>.json` | each sale's whole record, once it is paid | never: it is for people |
| hosts | `state/person/<node>.json`, beside it `<node>.floor` and `<node>.bad` | the alarm holding the node, the limits a person signed, the last number each signer used; written whole before the door answers. `.floor` marks when the file was lost | at start, before any tick |
| hosts | `state/decisions/<node>.jsonl`: the node record | one chained line per step, device call, receipt, alarm, person's word and model answer, flushed and synced; a torn last line goes to `.torn` | at start, when the node's agent is made |
| hosts | `state/<node>_wishes.json`, `state/<node>_policy.json` | by a person or a deploy | when the agent is made: the owner's standing wishes, the manager's policy |
| community, buyers, aggregator, sites | `logs/town_wire*.jsonl` | one line per signed message sent or received | the community agent's clock reads the tail of its own and the first buyer's to see whether a message is on its way |
| every part | `agent.json`, `secrets/town_grants.json`, `secrets/town_token` (a buyer's `secrets/<buyer>_town_token`), `secrets/host_tokens.json`, `secrets/control_token`, `secrets/person_<role>.key` | by the deploy or the runner; `python -m murmur.node.person token`, `key ROLE` and `trust ROLE KEY` make the control token and a person's key and write `person_keys`, and `word NODE VERB --url URL` sends a person's signed word to a host | at start; the control token on every `POST` |

The transport's journal of sent bodies (`transport.Sent`) holds, by message id, the first body each session sent (the last 512),
so that a retry under that id sends that body and the bus answers it as a replay. It is held in memory for as long as the process
runs.

Everything else lives in memory: the market's sales, the gap desk, the reputations, the report rows still to go up, the nodes'
offers, contracts, payments, meter rows and held readings, the buyers' orders and contracts, the aggregator's rows, the sites'
requests, every replay clock and each part's play tag (made at each start and at each `/demo/start` or `/demo/reset`). The local bus
keeps its runs, sessions, inboxes and record in memory too.

### 7.2 What a restart does

A restarted part reads its settings, its dataset and the files above, joins the bus again, and reads its inbox from the oldest
message not yet acknowledged; a message whose handler did not finish was never acknowledged, so the bus hands it out again after its
lease. A part with a grant on file joins only with that grant and never falls back to its join token; a grant expires an hour after
the runner wrote it, and a join with it is then refused (403). The community agent, the nodes and the buyers drop what has waited
past its time to live. The community agent reports `ready` once its inbox has been empty once, and a host once its first pass over
the nodes is done.

Its clock starts from `replay_start`, not held, until the community agent's clock loop, which reads every participant's clock every
20 s, sends it the current line. Meanwhile a host whose nodes are on another step keeps the step from ending, and the aggregator and a
site start their work only once their clock is set.

Ids after a restart:

- An answer keeps its id, because the id comes from the message it answers.
- A message a part sends unasked carries its play tag, which is new, so it goes under a new id.
- The aggregator's requests and the sites' answers and rows have fixed ids (sender, receiver, kind, request id or quarter hour).
  Made again, such a message carries a new time and signature, so the bus refuses it (409) where it holds the first, and the
  first stands.

### 7.3 A restart in the middle of an evening

| Part restarted | What comes back | What is lost, and what follows |
|---|---|---|
| Community agent | its key, the pinned keys, the member record, the sales record behind the cover, the requests taken from the aggregator | the sale in progress (offers, commitments, readings, settlement), the gap desk, the reputations, the clock loop and its gates. Messages about the lost sale are refused. The other parts stay held on their step, and the evening starts again with `/demo/start` from 09:45 the day before |
| Homes' or buildings' host | each node's key; its alarm and its person's limits, set again before any tick (an alarm in the node record holds the node too, and a person's file that can't be read holds it until a person clears it); from the node record, what people said through the signed channel, an alarm's stop, the notes already read and the device calls already made (a call started and not recorded finished is not sent again) | the offers, contracts, payments, meter rows and held readings. The restarted node does not hold the contract it accepted, so it sends no readings for it and answers the community agent's request for them with the half hours gone. After the rounds, the buyers settle on the readings they hold, the sale carries what is missing, and a node with no counted reading is paid nothing |
| Aggregator | its key, its requests and participants | the rows, answers and flags it kept. It sends each request whose time has come again under its fixed id, which the bus refuses if it holds the first, and it keeps the rows that arrive from then on |
| Single site | its key, the site, its feed and its limits | the request in force and the rows it sent. It steps every quarter hour of its feed again from the first; rows the bus holds are refused and the first stand. The request was acknowledged before the restart, so its battery runs its own schedule until its aggregator asks again |
| Buyer (stand-in) | its key | its orders, contracts, readings and baselines. It refuses the messages of a sale it does not hold, the community agent asks it for the settlement every hour for a day, and that sale does not settle with it |
| Local bus | the run from `bus.json`: the tokens and the controllers' keys | every message, session and the record. Each part joins again at its next call, with its grant where it holds one; once that grant's hour is up the join is refused (403), and the part stays off the bus |
