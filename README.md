# Murmur

Agents that cut a community's evening peak. Homes and buildings offer to draw less power in an evening window; a community agent
gathers their offers into one promise to the buyers above it (a utility, a grid operator, an aggregator), clears what the buyers
take, fills the gaps when a member falls short, checks every signed meter reading and pays each member for what its meter shows.
Single sites (a solar-and-battery plant, a data center) answer the aggregator beside the community, in the same signed messages.

Code decides every amount. A small language model only reads what people write to their agent ("keep the battery full tonight")
and words the reports; a note can only become a limit, and a guard checks every device call against the owner's limits before a
sealed command reaches a driver.

## Architecture in one screen

```
 buyers (utility, grid operator)        aggregator ─────────── single sites (plant, data center)
          │  orders, contracts, baselines,   │  requests, reports       each its own process
          │  settlement                      │
          ▼                                  ▼
 ┌──────────────────────── community agent ─────────────────────────┐
 │ forecast · cover and promise · clearing · gap desk · report up   │
 └───────────────┬──────────────────────────────────────┬───────────┘
                 │ discover, offers, confirm, readings  │
        homes' host (home nodes)              buildings' host (building nodes)
        each node: offer rule (code) → agent (notes, reports) → guard → seal → driver
                 └────── every message signed (Ed25519), over one message bus ──────┘
```

Every participant is a process with its own key and its own name on the message bus. The bus speaks a small HTTP contract
(join, send, notify, claim, ack, with leases, fences and run grants); `src/murmur/protocol/transport.py` is its client and
`demo/runner/bus.py` a local implementation. The clock is the dataset's: a replay of measured days at 15-minute steps, held at
each step until the network has finished it; asked to, it leaps over the quarter hours nothing is scheduled at.
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) has the whole picture.

## Directory map

| Path | What |
|---|---|
| `src/murmur/protocol/` | envelope, canonical JSON and Ed25519 signing, message ids, the bus client, the inbox poller, the token door |
| `src/murmur/node/` | a home or building node: replay and simulator, forecast, offer rule, agent, note reader, model client, guard, seal and drivers, report |
| `src/murmur/agents/` | the processes: the hosts of home and building nodes, the aggregator, a single site; `community/` is the community agent (market, clearing, gap desk, report) |
| `src/murmur/settlement/` | meter checks, baselines and the pay rules |
| `src/murmur/config.py` | settings from `agent.json` and `MURMUR_*` variables |
| `demo/runner/` | a whole evening on one machine: the local bus, run grants, the stand-in buyers and model, the state feed, synthetic example data, the comparison of two runs |
| `demo/page_builder/` | the demo pages from recorded evenings: templates, style sheets, scripts and the Python that fills them; `live/` shapes a running network's messages and rows into the same moments; `checks/` for browser checks |
| `demo/console/` | the presenter's console: it plays an evening on the runner's parts, keeps the live log and serves the page, the state and the presenter's commands |
| `demo/recordings/` | the recorded evenings the pages replay |
| `demo/pages/` | the built pages |
| `experiments/engie/` | offline pipelines on ENGIE's 2025 data: meter cleaning, peak allocation, the referee, the year runs |
| `tests/` | the test suite, on synthetic fixtures in `tests/fixtures/` |
| `scripts/verify_clean_repo.py` | the trace scanner every file must pass |
| `docs/` | [ARCHITECTURE](docs/ARCHITECTURE.md), [PROTOCOL_AND_SAFETY](docs/PROTOCOL_AND_SAFETY.md), [DATA_AND_LIMITS](docs/DATA_AND_LIMITS.md) |

## Quickstart

```bash
git clone <this repository> murmur && cd murmur
python3 -m venv .venv && . .venv/bin/activate && pip install -e ".[dev]"
pytest -q
```

The suite runs in seconds on the committed synthetic fixtures: no dataset, no network beyond 127.0.0.1, no fixed port. Tests
that need ENGIE's data carry `@pytest.mark.engie_data` and are skipped unless `MURMUR_ENGIE_DATA_DIR` is set.

## Configuration

Each process reads its settings from one folder, `$MURMUR_CONFIG_DIR`: `agent.json` and `secrets/` (its keys, bus tokens and run
grants, never in the repository). The order is the code's defaults (`config.DEFAULTS`), then the dataset's `agent_defaults`, then
`agent.json`.

| Variable | Meaning |
|---|---|
| `MURMUR_CONFIG_DIR` | the process's configuration folder |
| `MURMUR_DATA_DIR` | the dataset it replays (`dataset.json`, `fleet_v2.json`, `homes/`, `buildings/`, `devices/`) |
| `MURMUR_MODELS_DIR` | forecast models: a node's when its `forecast` is `trained`, and the community agent's outlook |
| `MURMUR_LOG_DIR` | where it writes logs (default `logs/` in the configuration folder) |
| `MURMUR_DEVICES` | the homes' devices that take part besides batteries and cars: `all` or a comma list (unset: none); a building's own fans, plug loads and car ports always take part |
| `MURMUR_ENGIE_DATA_DIR` | ENGIE's dataset, for the experiments and their tests |

Every address a part listens on or calls is a setting. A service listens at `bind_host` (default `127.0.0.1`, the loopback
address) on the port its settings name: `community_port`, `host_port`, `buildings_port`, `aggregator_port`, `site_port`, or a
buyer's `--port`. It calls the bus at `town_url` in the run `town_run_id` and the model server at `llm_url` with `llm_model`
(only with `llm_enabled`, off by default); the community agent's clock reaches `utility_url`, `host_url`, `building_urls` and
`clock_extra_targets`.

## Demo: one evening on this machine

```bash
python -m demo.runner example
python -m demo.runner evening --config demo/runner/config.example.json
python -m demo.runner compare out/runs/RUN_A out/runs/RUN_B
```

`example` writes a synthetic community (three homes, an office, a solar-and-battery plant, a data center; 25 days of data, 5 to
29 January 2025), plain forecast models and its evening to `out/example/`. `evening` starts every part at the configuration's
`host` (`127.0.0.1` in `config.example.json`, and when none is given): the bus, the stand-in model, the community agent, two
stand-in buyers, the two hosts, the aggregator and the sites, each with its own folder, keys and run grant under `out/runs/`. It
plays the evening from the day before to its settlement, with an owner's note at 17:00, and writes `summary.json` and the bus
record, `record.json.gz`. It prints the address of its read-only state feed (`/live/state.json`), which the two-view page's Live
view reads (`index.html?live=<address>`). `demo/runner/config.example.json` sets every setting; a model server of your own, on
that `host`, is `"model": {"url": "http://HOST:PORT", "name": "MODEL"}`.

With `"leap": true`, as in the example, the clock moves over the quarter hours nothing is scheduled at in one move and plays only
the others, each for at least `pace_s` seconds (`0`: as fast as the network finishes a step); with `"leap": false` it plays every
quarter hour. `compare` says whether two finished runs were the same evening (the same outcome, the same messages, the same report
rows) whatever their pace, or prints what differs.

## Live: the presenter's console

```bash
python -m demo.console --config demo/runner/config.example.json --port 0 --speed 2
```

The console starts the same parts as `evening` and serves, on `127.0.0.1`, the two-view page, the live state and the presenter's
door. Its link, with the presenter's key after `#k=` (a browser never sends that part), is written beside the key file
(`--key-file`, made when absent, mode 600) as `KEYFILE.link`. Opened, the page's Live tab is the split view playing the running
network: the map's wires and boxes, each moment's headline, cards and real terminal lines, a bar with the clock, its state
(Leaping to next event, Live event, Held, Settled), Start, Hold or Continue, Step, five speeds and eight surprises, and a
timeline of the evening with its pins. The clock leaps over quiet quarter-hours and plays the others as fast as the network
finishes them; the page's speed sets how long each moment stays on screen (8 seconds at 1, as the recorded replay at its 1x; 2 seconds at
4, the console's usual speed), and the console holds the clock while the screen is
behind. Anyone else who opens the page without the key only watches. The routes:

| Route | What |
|---|---|
| `GET /` | the page; opened with no `?live=`, it finds the console at its own address and opens Live (`?replay=1` keeps the recording) |
| `OPTIONS /live/surprise` | 204, only with `--audience`: any origin's page may post a tap (every other `OPTIONS` is 403) |
| `GET /how` | the architecture page beside the page file |
| `GET /live/state.json[?since=N]` | the live state; with a cursor, the moments after it (`murmur.live.v2`) |
| `POST /live/surprise` | a viewer's tap, without a key: exactly `{"kind": "<preset>"}` in at most 256 bytes (only with `--audience`) |
| `GET /console/state` | the console's own state, with the key (`X-Murmur-Console`) |
| `POST /console/do` | one command, with the key: `start`, `hold`, `go`, `step`, `run_to`, `pace`, `surprise` |

Two more options make it a console for an audience, with nobody at it:

- `--loop-days [FILE ...]` plays evening after evening: the first starts at once, a settled evening's summary stands 12 seconds
  ("Next day starting in 12s…"), then the next starts at the same speed. With no file it is the same evening again; each file is one more
  day's configuration, played in turn on a fresh stack in a run folder of its own (so their `folder` needs `{time}`). A
  configuration's `label` names its day in the page's bar: "Day 1 of 3 · Jan 28 Winter peak".
- `--audience` gives every viewer without the key a strip of six preset events in place of the presenter's controls: battery at
  10%, car needed now, solar down to a fifth, a building's need, a 20 kW grid emergency, a battery fault. A tap sends its preset's
  one word and nothing else. The first tap fires and starts a cooldown of 10 seconds; taps during it are votes, one a viewer in a
  round, and the most voted fires when it ends; an evening takes twenty. The live state carries the counts (`v2.crowd`) and the
  day (`v2.loop`).

The bar's Phone button (or `#qr`) opens "Try it on your phone": a QR code of the page's own address, drawn in the page with no
request and no address written in it, three links and two lines of what is live now.

A copy of the pages published elsewhere (a static site, under any folder) joins the same evening when a file `live.json` stands
beside the page: `{"live": "https://<the address the console is reached at>"}`. The page reads it, asks that address for the live
state, and opens Live with the audience's strip; its taps go to that address, its card and QR code show the copy's own address,
and no viewer's screen names the address behind it. With no such file, or when nothing answers there, the page is the recorded
replay and says nothing. The file belongs to the published copy only: this repository holds none.

`python -m demo.page_builder.checks.live demo/pages` checks Live against made-up feeds;
`python -m demo.page_builder.checks.live_run --config demo/runner/config.example.json` plays a real evening through a console in a
browser, and `python -m demo.page_builder.checks.live_public --config demo/runner/config.example.json` a looping one as its
audience sees it, on a phone's screen.

## Demo pages

```bash
python -m demo.page_builder.build --out demo/pages
```

The pages replay recorded evenings (`demo/recordings/`): the two-view page (split view, Data view, Live view), the three-view
page, a whole evening, two year sets, the year results, a method note and an architecture page. The builder uses the standard
library only. The browser checks in `demo/page_builder/checks/` (no word cut at many window sizes, every moment walked, links and
script errors) need Playwright: `python -m demo.page_builder.checks.fit demo/pages`.

## ENGIE experiments

```bash
pip install -e ".[experiments]"
python -m experiments.engie.meter_cleaning --data-dir DIR --out OUT
python -m experiments.engie.peak_allocation --data-dir DIR --out OUT
python -m experiments.engie.referee --data-dir DIR --out OUT
python -m experiments.engie.year_runs --data-dir DIR --out OUT
MURMUR_ENGIE_DATA_DIR=DIR pytest -q tests/experiments
```

`DIR` is ENGIE's 2025 student dataset. What each pipeline measures, and what the data cannot show, is in
[docs/DATA_AND_LIMITS.md](docs/DATA_AND_LIMITS.md).

## Checks before a commit

```bash
pytest -q
python scripts/verify_clean_repo.py .
```

The scanner fails on any private trace: machine names, private addresses, home-folder paths, remote-access words, earlier project
names.
