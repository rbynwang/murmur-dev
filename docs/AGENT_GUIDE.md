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
| An emergency call during the evening | `POST /alert` at your buyer (section 5) | how much was confirmed, how much is short |
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
dataset time written `YYYY-MM-DD HH:MM`; the wall clock does not matter.

## 3. Start a network and drive its clock

Your order is the evening file's `order_kw`, in kW for every half hour of the window, one number for each buyer:

```json
"order_kw": {"grid-operator": 5.4, "utility": 9.0}
```

Edit `out/example/evening.json` before you start. The price is `price_usd_per_kwh` in the same file (2.04 when absent). The runner
places both orders itself when the evening starts, each with a deposit of a tenth of what it could cost.

```bash
python -m demo.console --config demo/runner/config.example.json --port 0 --speed max
```

Leave it running (it stops every part it started on Ctrl-C or SIGTERM). It prints `console on http://127.0.0.1:PORT/`. Beside the
run folders it writes its key, `out/runs/console.key`. The run's own folder is `out/runs/<time>/`; its `run.json` holds the address
of every part under `urls`, your buyer's among them.

| Console route | What |
|---|---|
| `GET /console/state` | `play` (`idle`, `starting`, `running`, `held`, `settled`, `failed`), `clock` (the dataset time), `phase`, `error`, `warn`, `roster` |
| `POST /console/do` | one command as JSON; 202 when taken, 400 `{"error": words}` when refused |

Both want the key in the header `X-Murmur-Console`. The commands:

| Command | Effect |
|---|---|
| `{"do": "start"}` or `{"do": "start", "run_to": "2025-01-28 17:30"}` | starts the evening at 09:45 the day before; with `run_to`, plays to that quarter hour and holds |
| `{"do": "hold"}`, `{"do": "go"}` | holds the clock once its step is done; lets it go on |
| `{"do": "step"}` | only while held: plays to the next quarter hour that is played |
| `{"do": "run_to", "ts": "2025-01-28 19:00"}` | plays to a later quarter hour of this evening and holds |

A command is taken at once and done a moment later: ask `/console/state` until `play` and `clock` say what you wait for. The clock
leaps over quarter hours in which nothing is scheduled. The evening ends with `play` `settled` (the sale's money is final) or
`failed`; after that the console takes `start` only.

## 4. Read your buyer

Your buyer's address is `urls.utility` or `urls["grid-operator"]` in `run.json`. Reads need no key.

| Route | Answer |
|---|---|
| `GET /health` | `now` (the buyer's dataset time), `contracts` (how many) |
| `GET /contracts` | for each contract: `event_id`, `status`, `meters`, `offered` (the kW promised to you in each half hour of the window, keyed `"0"` for the first), and `settlement` once there is one |
| `GET /evidence/{event_id}` | the whole record of one order: the signed `order`, `offered`, each meter's `baselines` and `meter_readings`, `rejected_readings`, `settlement` |
| `GET /calls` | your emergency calls: `kw`, `start`, `end`, `price_usd_per_kwh`, `confirmed_kw`, `short_kw`, `status`, and once settled `delivered_kwh` and `paid_usd` |
| `GET /events?n=50` | the buyer's last events, oldest first |

The `event_id` of an order is `flex-need-<date>` at `utility` and `grid-operator-need-<date>` at `grid-operator`.

The contract appears once the community has answered the order, at 10:00 the day before the evening; `offered` may be less than
you ordered, and is 0 in a half hour the community promises nothing. `settlement` is `null` until the readings are in, shortly
after the window ends:

| Settlement field | Meaning |
|---|---|
| `components` | one row for each half hour: `offered` (kW promised), `delivered` (kW the meters show, against each meter's baseline; below 0 when the members drew more than their baseline), `pay` (USD) |
| `total` | your bill for the order, USD: every delivered kWh at its class's rate, with no cap at the promise and no penalty |
| `full_price_usd` | the same kWh at the order's price: the most the bill could be |
| `deposit` | `held_usd`, `credited_usd`, `refund_usd` and `still_due_usd`: what you still owe after the deposit |

## 5. Raise an emergency call

```bash
curl -s -X POST "$BUYER/alert" -H 'Content-Type: application/json' -d '{"kw": 2, "minutes": 60, "why": "feeder overload"}'
```

| Field | Rule |
|---|---|
| `kw` | the extra kW you want, more than 0 and at most 2000; or `pct`, a percentage of your order |
| `minutes` | 15 to 240 (60 when absent) |
| `why` | free text, at most 120 characters |
| `at` | optional: a later dataset time at which the call goes out |

The answer is `{"at", "end", "kw", "why", "called"}`. The call starts at the next quarter hour, at twice the order's price, and the
community agent confirms what its members can add: read `confirmed_kw` and `short_kw` in `GET /calls` a step later. Anything else
is `400` with the reason in `detail`.

## 6. A small example

With the console running and `K` its key, `C` its address and `BUYER` the utility's address:

```bash
curl -s -X POST "$C/console/do" -H "X-Murmur-Console: $K" -H 'Content-Type: application/json' \
     -d '{"do": "start", "run_to": "2025-01-28 17:30"}'
curl -s "$C/console/state" -H "X-Murmur-Console: $K"        # until "play": "held"
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
- **Calls settle late.** A call that overlaps the window is settled 120 minutes after the window ends. The example evening is
  `settled` and its clock held as soon as the sale's money is final, about 21:45, so a call's `status` stays `OPEN` and its
  `paid_usd` and `delivered_kwh` stay `null`: this run cannot tell you what an emergency call cost.
- **Simulated.** The homes, the buildings, their devices and meters are simulated from synthetic data, the buyers are stand-ins, and
  no money moves. A reading is signed by its member's key and checked by the buyer before it counts.
- **Stop what you started.** The console ends its own parts when it is stopped. Other programs may run on the same computer: call
  only the addresses your own run printed, and never stop a process by its name.

## 8. Where the rest is

[README](../README.md) for every command, [ARCHITECTURE](ARCHITECTURE.md) for the parts and an evening's course,
[PROTOCOL_AND_SAFETY](PROTOCOL_AND_SAFETY.md) for the signed messages and the checks a reading must pass,
[DATA_AND_LIMITS](DATA_AND_LIMITS.md) for what is synthetic and what is measured.
