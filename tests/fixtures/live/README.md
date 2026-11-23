# Live fixtures: two evenings as a console reads them

Two evenings of the demo's example configuration (`demo/runner/config.example.json`, the stand-in model), each run once on one
computer and read the way a presenter's console reads a running evening: a pass every 0.25 s that reads the conductor's view
first, then the bus record's new events, the sale, each node's new record rows and the meter's new rows. The clock leaped (leap
on, pace 0, at most 192 quarter-hours a leap) and played the stops a console sets: the day-ahead sale, 10:00, the aggregator's
requests, each event, an hour before the window, every quarter-hour from 17:30 to 21:00, and 21:15, 21:30, 21:45.

Read them through `tests/page_builder/live_fixture.py`, the one loader. Nothing here is made up or reworded: every item is what
its source gave.

## Files

`facts.json` is plain. The other twelve are packed (below): `<capture>_<source>.json`.

| Source | An item, as the loader gives it | `evening` | `surprises` |
|---|---|---|---|
| `conductor` | `{t, part, view}`: `GET /demo/conductor` of the community agent, whole, one a pass | 239 | 158 |
| `bus` | `{t, event}`: an `accepted` event of the bus record, `{event, message_id, from, to, kind, body, at}` | 90 | 57 |
| | `{t, now, count}`: the `community.report` rows of a pass that were not kept, by sender | 35 | 13 |
| `sale` | `{t, summary}`: `GET /v2/summary`, kept when it differed from the pass before | 34 | 14 |
| | `{t, trigger, id, event}`: `GET /v2/events/{id}`, read in a pass that held a trigger | 3 | 1 |
| `rows` | `{t, node, row}`: a row of a node's record, as the hosts' record door serves it | 176 | 128 |
| `meter` | `{t, ts, homes_kw, buildings_kw}`: a quarter-hour the runner's meter fed | 164 | 14 |
| `posts` | `{t, part, path, body, status, answer, what}`: an order, or a surprise with `kind, who, at, from` | 3 | 8 |

`t` is the wall time of the pass that read the item, in seconds from the capture's start, taken as the pass began. `part` is the
stretch of the capture a pass lies in. `facts.json` holds what a live evening is made from (`day, homes, buildings, sites, follow,
half_hours, model`), the window, the buyers' orders, the configuration's events, the aggregator's requests, and under `captures`
what each capture was: gates, stops, leaps, the sale's totals, the surprises, the bus messages by kind.

## The packed form

Whole, in plain JSON, the items of `evening` are 1.37 MB (the conductor's view of every pass alone 938 kB), and these fixtures
are held to 200 kB for the first capture and 320 kB for both. So each file is written packed, and nothing is lost: the loader
gives every item back exactly as it was read, key order included.

```
{"about": "...", "shapes": [[key, ...], ...], "shared": [value, ...], "items": [value, ...]}
```

A value is a number, a text, true, false, null, or a list whose first element says what it is: `[0, a, b]` is the list `[a, b]`;
`[k, a, b]` with k above 0 is a dict whose keys are `shapes[k - 1]` and whose values are `a, b`; `[-k]` is `shared[k - 1]`, a
dict, list or text that comes more than once in the file. One item a line. To see an item plain:

```
python -c "import json; from tests.page_builder import live_fixture as F; print(json.dumps(F.load('evening')['bus'][0], indent=1))"
```

## How they were cut

- **Kept.** `evening`: every pass, from the start's own pass (the clock still idle) to eight quiet passes after the hold of
  `settled`. `surprises`: the passes in which the clock stood at 18:00 to 21:00, which is from the quarter-hour it stood in before
  each surprise to that surprise's last stop (part 0), and the eight passes at 23:00 in which the emergency's call was settled
  (part 1), read after the driver let the hold of `settled` go, as a presenter's Continue does.
- **Thinned.** Only `community.report` rows: the first from the community agent and from each of the two sites read while the
  clock was inside the window are whole; the others are counted, by pass, by the quarter-hour the clock then held and by sender.
  Every other message read in a kept pass is whole.
- **Scrubbed.** An address of the run is replaced by its part's role name (the conductor says "homes: a message just left"
  where its door names the part by address); a wall-clock stamp in seconds since 1970 (`at`, `sentWall`, the sale's `*_wall`)
  is counted from the capture's start, like `t`; a run of 48 or more hex characters (`sig`, `signer`, `hash`, `prev`, `key`,
  `asked`) is cut to its first 16. No address, port, folder path, token or key is in a file.
- **Rows** were read from the run folder's `state/decisions/<node>.jsonl` as the files grew and put in the record door's form
  (`host_reads.served`): a `model` row's `tools` as names, long hex cut, every kind kept, `n` the row's place in the log.
- A snapshot's triggers: the first `select`; an `update` with `telemetry_done`; a buyer's `on_status` with `settlement`; the
  sale's phase `done`.

## `evening`: the whole example evening

239 passes, 60.2 s of wall time; the configuration's own note to home-02 at 17:00 (gates at the day-ahead sale and at 17:00).
Three leaps: D-1 10:15 to D 10:00 (95 quarter-hours, 241 ms), 10:00 to 14:00 (244 ms), 14:00 to 16:45 (241 ms); 25 played
steps. The sale is `flex-need-2025-01-28` here; which buyer's order comes first names it, so nothing may read it by name.

**Totals: the seller is paid $20.7893, the pool is $14.5730, and the meters show 26.067 kWh delivered.**

| When | What the passes hold |
|---|---|
| start | the two orders; 4,305 report rows as the sites catch up to the start |
| D-1 10:00 | the day-ahead sale, 34 messages: `discover`, `on_discover`, `select` to `on_confirm`, `update`, `on_status`; rows of steps 1 to 6; snapshot `select` |
| D 10:00 | the question for tomorrow: two `discover`, two `on_discover` with empty `catalogs` |
| 14:00 | the aggregator's three `community.request` and their `community.answer` |
| 17:00 | the note: rows `model, model, decision, told, receipt` of home-02 |
| 18:00 to 20:00 | step 7 of home-01 and home-03 at 18:00, of home-02 at 20:00; the gap desk at 18:15, 18:30 and 19:15; step 8 at 18:30, 19:00, 19:30 |
| 21:00 | step 9 and three `on_status` with `node_report` |
| 21:45 | nine reading batches, `telemetry_done`, the settlement, three pay notices; snapshots `telemetry_done` and `settlement, done` |
| D+1 10:00 | the clock leaps on before the hold: two `discover`, two empty `on_discover` |

Messages by kind, in the bus record and whole in the files: `discover` 10, `on_discover` 10, `select` 2, `on_select` 2, `init` 2,
`on_init` 2, `confirm` 5, `on_confirm` 5, `update` 4, `on_status` 21, `rt_capacity` 4, `rt_ask` 4, `rt_answer` 4, `rt_dispatch`
4, `rt_confirm` 2, `community.request` 3, `community.answer` 3: 87 of 87. `community.report`: 4,856 in the record, 3 whole,
4,853 counted.

## `surprises`: seven surprises inside the window

A second evening, driven the same way. Each surprise was posted while the clock stood at a gate, one quarter-hour before its
`at`, through its kind's door, then its stops were set and the gate opened. 158 passes are kept: 150 with the clock at 18:00 to
21:00 (part 0), 8 at 23:00 (part 1). Its sale is `grid-operator-need-2025-01-28` (the other buyer's order came first this time);
it settled at $12.8818 for the seller, $9.0407 for the pool, 18.252 kWh.

| Posted at | `at` | Kind | To |
|---|---|---|---|
| 18:00 | 18:15 | `emergency`, 20 kW for 60 min | the grid operator's `/alert` |
| 18:15 | 18:30 | `battery_fault`, home-01 | homes `/demo/scenario` |
| 18:45 | 19:00 | `battery_low`, home-02, 10 % | homes `/demo/scenario` |
| 19:00 | 19:15 | `weather` | both hosts' `/demo/scenario` |
| 19:30 | 19:45 | `car_now`, home-03 | homes `/demo/scenario` |
| 19:45 | 20:00 | `building_need`, building-01 | buildings `/b/building-01/demo/scenario` |
| 20:00 | 20:15 | `building_closed`, building-01 | the same |

What followed, in the whole messages: `rt_call` 1, `rt_capacity` 5, `rt_ask` 10, `rt_answer` 10, `rt_dispatch` 9,
`rt_confirm` 8, `on_status` 11, `community.report` 3 (39 more counted). Rows: home-01 47, home-02 13, home-03 68. The office sold
nothing, so the two building surprises draw no message; the weather draws none that names it.

The configuration's note at 17:00 was posted in this evening too; its quarter-hour is not kept. No snapshot lies in part 0; part
1 holds one, read when the grid operator's `on_status` with the call's `settlement` came.

## Not here

The words the driver gave the conductor and the start (they are in `facts.json`: `gates`, `stops`, `start`), the state feed's
own block, any process log, and the acks of the bus record.
