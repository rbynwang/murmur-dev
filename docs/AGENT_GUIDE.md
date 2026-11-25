# Agent guide: using Murmur as a grid buyer's agent

For an agent (or the person setting one up) that wants to use Murmur without reading its code. It covers one role end to end,
the **grid buyer**: order an evening's peak cut from a community, see what the community promised, raise an emergency call during
the evening, and read what the meters delivered and what you owe.

## 1. What you get

A Murmur network is a community agent, its member homes and buildings, two buyers (`utility` and `grid-operator`), an aggregator
and single sites, each its own process on one machine, exchanging signed messages. There is no hosted network to call: you start
one on your own computer from this repository, on synthetic data, and it is yours for the run. A model is not needed (a stand-in
answers in its place).

As the buyer's agent you have three things:

| What | How | You learn |
|---|---|---|
| An order for one evening | `order_kw` in the evening file, before the network starts (section 3) | what the community promised you, half hour by half hour |
| An emergency call during the evening | `POST /alert` at your buyer (section 5) | how much was confirmed, how much is short, and after the evening what it delivered and cost |
| The record | `GET /contracts`, `/evidence/{event_id}`, `/calls`, `/events` at your buyer (section 4) | every signed reading, the settlement and your bill |

The presenter's console starts the network and gives you its clock: start, hold, run to a time, go on (section 3).

## 2. Set up

Python 3.11 or later. From the repository's root:

```bash
python3 -m venv .venv && . .venv/bin/activate && pip install -e ".[dev]"
python -m demo.runner example
```

`example` writes the synthetic community to `out/example/`: three homes, an office, a solar-and-battery plant and a data center,
25 days of data (5 to 29 January 2025), and one evening to play, **28 January 2025, 18:00 to 21:00**. Every time in Murmur is a
dataset time written `YYYY-MM-DD HH:MM`; the wall clock does not matter. The install takes seconds, and a whole evening about two
minutes.

## 3. Start a network and drive its clock

**Your order is a file, not a request.** It is the evening file's `order_kw`: kW for every half hour of the window, one number for
each buyer (`{"grid-operator": 5.4, "utility": 9.0}` as written). The file is large and printed over many lines, so change it
with a few lines of code, before you start the network:

```bash
python - <<'EOF'
import json, pathlib
f = pathlib.Path("out/example/evening.json"); e = json.loads(f.read_text())
e["order_kw"]["utility"] = 12.0
f.write_text(json.dumps(e, indent=1))
EOF
```

The price is `price_usd_per_kwh` in the same file (2.04 when absent). The runner places both orders itself when the evening
starts, each with a deposit of a tenth of what it could cost. An order cannot be placed or changed on a running network.

```bash
python -m demo.console --config demo/runner/config.example.json --port 0 --speed max
```

Leave it running (it stops every part it started on Ctrl-C or SIGTERM). It prints `console on http://127.0.0.1:PORT/`. Its key is
the file `out/runs/console.key`. The run's own folder is the newest one under `out/runs/`, named by its start time; its `run.json`
holds the address of every part under `urls`, your buyer's among them.

| Console route | What |
|---|---|
| `GET /console/state` | `play` (`idle`, `starting`, `running`, `held`, `settled`, `failed`), `clock` (the dataset time), `target` (where a `run_to` goes), `phase`, `error`, `warn`, `roster` |
| `POST /console/do` | one command as JSON; 202 when taken, 400 `{"error": words}` when refused |

Both want the key in the header `X-Murmur-Console`. The commands:

| Command | Effect |
|---|---|
| `{"do": "start"}` or `{"do": "start", "run_to": "2025-01-28 17:30"}` | starts the evening at 09:45 the day before; with `run_to`, plays to that quarter hour and holds |
| `{"do": "hold"}`, `{"do": "go"}` | holds the clock once its step is done; lets it go on |
| `{"do": "step"}` | only while held: plays to the next quarter hour that is played |
| `{"do": "run_to", "ts": "2025-01-28 19:00"}` | plays to a later quarter hour of this evening and holds |

How the clock behaves:

- A command is taken at once and done a moment later. **Wait on `clock`, not on `play`:** after a `run_to` from a held clock,
  `play` can keep reading `held` while the clock moves. You have arrived when `clock` is your time.
- The clock leaps over quarter hours in which nothing is scheduled.
- **The evening ends by itself**, with `play` `settled`, as soon as its money is final: the order is settled (about 21:45 in the
  example) and so is every emergency call (a call that overlaps the window is settled 120 minutes after the window ends, so with
  a call the example ends at 23:00). A `run_to` to a later time is taken and the clock stops at the end all the same.
- After `settled` or `failed` the console takes `start` only: `go`, `step` and `run_to` are refused (`step` with the words "only
  while the clock is held", although the state then says `hold: true`). Read your buyer after `settled`; its answers stay.

## 4. Read your buyer

Your buyer's address is `urls.utility` or `urls["grid-operator"]` in `run.json`. Reads need no key.

| Route | Answer |
|---|---|
| `GET /health` | `now` (the buyer's dataset time), `contracts` (how many) |
| `GET /contracts` | for each contract: `event_id`, `status`, `meters`, `offered` (the kW promised to you in each half hour of the window, keyed `"0"` for the first), and `settlement` once there is one. It does not repeat what you ordered: that is `order.order.kw` in `/evidence` |
| `GET /evidence/{event_id}` | the whole record of one order: the signed `order`, `offered`, each meter's `baselines` and `meter_readings`, `rejected_readings`, `settlement` |
| `GET /calls` | `calls`, your emergency calls: `id`, `issued_at`, `start`, `end`, `kw`, `price_usd_per_kwh`, `confirmed_kw`, `short_kw`, `status` (`OPEN`, then `COMPLETE` or `REFUSED`), and once settled `delivered_kwh` and `paid_usd`; and `alerts`, what you posted |
| `GET /events?n=50` | the buyer's last events; each has `kind`, `sim` (the dataset time) and `at` (the wall clock, in seconds) |

The `event_id` of an order is `flex-need-<date>` at `utility` and `grid-operator-need-<date>` at `grid-operator`.

The contract appears once the community has answered the order, at 10:00 the day before the evening. `offered` may be less than
you ordered, and is 0 in a half hour the community promises nothing; the interface does not say why. An event of kind
`rt_warning` (`short_kw`, `start`, `end`, `why`) says the community now expects to fall short of its promise in that stretch;
`offered` does not change. `settlement` is `null` until the readings are in, shortly after the window ends:

| Settlement field | Meaning |
|---|---|
| `components` | one row for each half hour: `offered` (kW promised), `delivered` (your share of the kW the meters show against each meter's baseline, averaged over the half hour), `pay` (USD) |
| `total` | your bill for the order, USD |
| `full_price_usd` | the same delivered kWh at the order's price: the most the bill could be |
| `capped_kw` | only with an emergency call: the half hours the call covers, and the promise the order's part stops at there. What the meters gave beyond it is the call's, in `/calls` |
| `deposit` | `held_usd`: what of your deposit the community held (the signed order shows all you put up; what the community's power could not use went back at once). `credited_usd`: what of it went to the bill. `refund_usd`: what comes back. `still_due_usd`: the bill less what was credited |
| `policy` | the pay rule in words, with its rates |

Reading it:

- **`pay` is not `delivered` times the price.** Every delivered kWh is paid at its class's rate (a home battery's at the order's
  price, a building's and any other home device's at less; the rates are in `policy`), so `total` is at most `full_price_usd`.
  The answer does not say which class each kWh was, so you cannot rebuild `pay` from it.
- **No cap and no penalty** outside a call: delivery above the promise is paid, and delivery below it costs the community
  nothing. In a half hour a call covers, the order's part stops at the promise (`capped_kw`).
- **`delivered` and `pay` can be below 0** in a half hour in which the members drew more than their baselines. It is netted
  against the other half hours.
- **A meter sends a reading only for the half hours it committed to**, so a home can have fewer readings than the window has
  half hours with `rejected_readings` still 0. A battery's output is counted apart from the meter, and `share` is your part of
  each half hour when two buyers' orders fill from one pool, so `delivered` is not simply baseline less reading.
- The other fields (`eligible`, `penalty`, `net`, `revenue_flows`, `net_zero_ok`, `pins`, `pre_baselines`, `buyer_review`) are
  the settlement's own bookkeeping; a buyer can leave them.

## 5. Raise an emergency call

```bash
curl -s -X POST "$BUYER/alert" -H 'Content-Type: application/json' -d '{"kw": 2, "minutes": 60, "why": "feeder overload"}'
```

| Field | Rule |
|---|---|
| `kw` | the extra kW you want, more than 0 and at most 2000, one size for the whole call; or `pct`, a percentage of your order |
| `minutes` | 15 to 240 (60 when absent) |
| `why` | free text, at most 120 characters |
| `at` | leave it out. It belongs to the runner's scripted events: a call posted with a later time in `at` does not go out, and the clock then stands where it is |

- **When it starts.** A call goes out when you post it and starts at the next quarter hour. To start a call at 18:00, hold the
  clock at 17:45 (`run_to`) and post it then. A call cannot be scheduled ahead.
- **The answer** is `{"at", "end", "kw", "why", "called"}`: `at` is when the call went out, not its start. Its `start` and `id`
  are in `GET /calls`.
- **What is confirmed.** The community agent answers within a few seconds of real time, with the clock held or not: ask
  `GET /calls` until `confirmed_kw` is no longer `null`. `short_kw` is what it could not find. Nothing tells you beforehand how
  much a call could get, and a call cannot be changed or withdrawn.
- **What it costs.** The price is twice the order's. The call is settled 120 minutes after the window ends (section 3): then
  `status` is `COMPLETE`, `delivered_kwh` is what the meters added beyond the promise, and `paid_usd` is your bill for the call.
- Anything else is `400` with the reason in `detail`.

## 6. A small example

With the console running and `K` its key, `C` its address and `BUYER` the utility's address:

```bash
curl -s -X POST "$C/console/do" -H "X-Murmur-Console: $K" -H 'Content-Type: application/json' \
     -d '{"do": "start", "run_to": "2025-01-28 17:30"}'
curl -s "$C/console/state" -H "X-Murmur-Console: $K"        # until "clock": "2025-01-28 17:30"
curl -s "$BUYER/contracts"
```

```json
{"order-flex-need-2025-01-28-cf6dcb8bd1": {"status": "ACTIVE", "meters": ["home-01", "home-02", "home-03"],
  "offered": {"0": 0.0, "1": 2.43, "2": 3.81, "3": 3.84, "4": 4.39, "5": 2.06}, "event_id": "flex-need-2025-01-28"}}
```

The utility ordered 9.0 kW; the community promised 0 kW from 18:00, 2.43 kW from 18:30 and at most 4.39 kW (from 20:00).

## 7. Permissions and limits

- **One machine.** Every part listens on 127.0.0.1 only, on free ports chosen at the start. The console answers only requests whose
  `Host` is `127.0.0.1:PORT` or `localhost:PORT`.
- **Keys.** The console's two routes need its key. A buyer's reads need none; its `POST` routes need the control token in
  `X-Murmur-Token` only where a file `secrets/control_token` exists, and a demo run has none.
- **Orders.** One order a buyer and day, placed by the runner from `order_kw`. An order of your own through `POST /needs` for the
  same day is refused (`409`). An order must name a day of the data, a window on the half hour of at most 4 hours, at most 20,000 kW
  and at most 5 USD/kWh, and is taken only before 10:00 the day before.
- **What a buyer cannot ask.** Why a half hour is promised less than ordered, how much a call could get, which class a delivered
  kWh was, or what a single meter showed in a half hour a call covers: the interface has no answer to these.
- **Simulated.** The homes, the buildings, their devices and meters are simulated from synthetic data, the buyers are stand-ins, and
  no money moves. A reading is signed by its member's key and checked by the buyer before it counts.
- **Stop what you started.** The console ends its own parts when it is stopped. Other programs may run on the same computer: call
  only the addresses your own run printed, and never stop a process by its name.

## 8. Where the rest is

[README](../README.md) for every command, [ARCHITECTURE](ARCHITECTURE.md) for the parts and an evening's course,
[PROTOCOL_AND_SAFETY](PROTOCOL_AND_SAFETY.md) for the signed messages and the checks a reading must pass,
[DATA_AND_LIMITS](DATA_AND_LIMITS.md) for what is synthetic and what is measured.
