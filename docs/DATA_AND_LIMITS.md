# Data and limits

Every source the system and its experiments read: what it holds, what it is used for, its grain and its known limits. Then what is
synthetic, where data comes from at run time, how each of the four measured results is reproduced, and what the results do not show.
Every device, meter and payment is simulated or replayed from recorded data. No real home, device, meter or payment is involved.

Where a figure comes with a module, a test or a file, it is computed or held there. Where it comes with none, it is a reading of a source
the repository does not hold (ENGIE's releases, the measured weather and public sources, the homes' and buildings' datasets and their
build), and no code in the repository recomputes it.

## 1. The sources at a glance

| Source | Holds | Grain | Used for |
|---|---|---|---|
| ENGIE's 2025 release (section 2) | 80 participants' reports, ratings, meters, battery telemetry, grid readings, prices, sunlight, temperature | 15 min and 1 h | the aggregator's side, the host community's record, every run's weather and prices, the choice of evenings |
| ENGIE's 2023 release (section 3) | a simulated year of the same grid with its true state | 1 h and 15 min | the proof of the reading cleaner, the ruler, data centers' work that can wait |
| The homes' and buildings' dataset (section 4) | 200 simulated homes, a small office and shops, their devices, people and limits | 15 min | every home and building node |
| Measured weather (section 5) | Massachusetts 2025-26, with day-ahead forecasts as issued | 15 min in the homes' files | the forecast the agents read, the real-weather version of the year |
| Measured public sources (section 6) | the research house, load research, the federal household survey, makers' datasheets, building reports, one building's meter | per source | building and checking the homes and buildings |
| The price book (section 7) | each class of device's share of the order's price, the part of a bill that is kept and who keeps it, the same-day adjustment | per class of device | every bill and payment |
| Recorded runs (section 8) | recorded evenings and the year's offline runs | 15 min and half hours | the pages, `year_runs` |

## 2. ENGIE's 2025 release

**Holds.** Eleven Parquet files on one 200-bus grid with 80 participants at 80 buses: 20 communities, 10 data centers and 50
solar-and-battery plants. Battery power by kind: plants 183.2 MW, data centers 35.5 MW, communities 25.8 MW, 244.5 MW in all.

| File | Holds | Grain |
|---|---|---|
| `reports.parquet` | each report as delivered: interval, delivery time, sender and claimed identity, sequence number, signature check, net power, battery charge, an energy quote, a note | 15 min |
| `nodes.parquet`, `asset_ratings.parquet` | kind and bus; solar, battery power and energy, connection limit, peak rounded to 50 kW, cars, servers | static |
| `grid_topology_*.parquet` | buses, lines, transformers | static |
| `market_prices.parquet` | the real-time system price | 15 min |
| `obs_grid.parquet` | supervisory snapshots: voltages, line and transformer loading, feeder import | 1 h |
| `obs_ami.parquet` | the utility's meter, for 56 of the 80 participants | 15 min |
| `obs_device.parquet` | the battery's own telemetry (power, charge, current, temperature), for 40 of the 80 | 1 h |
| `obs_irradiance.parquet` | satellite sunlight and air temperature at each site | 1 h |

Timestamps are UTC; the participants' local clock is `America/Chicago`. Reports run from 2025-01-01 06:00 to 2026-01-01 05:45 UTC.
ENGIE scores 1 March to 31 December 2025; January and February are warm-up. The release holds no ground truth and no labels.

**Used for.**
- Transformer loading (`experiments/engie/grid.py`): the readings ENGIE marks good, 8,760 hours by 66 transformers.
- The batteries as reported (`experiments/engie/fleet.py`): only a report signed in the sender's own name with a valid signature counts,
  first delivery of each slot; gaps are interpolated; each battery's loss on the way out is measured from its full-power steps (the
  fleet's median for a battery with 50 or fewer); a one-step spike of charge that comes straight back is replaced by the mean of its
  neighbours.
- The referee: reports, ratings, meters, battery telemetry, and the sunlight that says which hours are dark at each site.
- The year's 48 evenings (`year_runs choose`): the mean price from 18:00 to 21:00, local clock.
- Every evening run on ENGIE's data. One of the 20 communities, the host, holds the simulated homes and buildings. Its record is kept as
  given: net power at its meter every 15 minutes, solar 3,416 kW, connection limit 3,214 kW, its homes' batteries as one total of
  1,624 kW and 4,400 kWh with their reported charge (`demo/page_builder/overview/data/facts.json`). Its temperature, sunlight and prices
  are those of the homes and buildings inside it. The single sites run on their own records and ratings.

**Limits.**
- *The grid readings are noisy snapshots with no truth beside them.* As read, 196 hours have a transformer at 80% or more and 10 at
  100% or more, the highest at 110.8%; 18,476 readings are missing and 705 are single-hour jumps. Cleaned with the whole year, 94 hours
  stay at 80% or more (none at 100%, highest 85.3%); cleaned with the past only, 96. Cleaned, they fall at 19:00 and 20:00 on transformers
  35 and 38 (`tests/experiments/test_meter_cleaning.py`, `engie_data`). Every 2025 count of strained hours, and every figure that follows
  from one, rests on cleaned readings, not on truth.
- *The temperature reads as generated.* The daily mean moves 0.27 °C from one day to the next at all 80 sites alike (0.25 to 0.29),
  where measured Massachusetts weather moves 2.6 °C. The year has no cold snap and no heat wave (daily means between about −3 and 25 °C).
  ENGIE's documentation calls the file satellite sunlight and air temperature; "generated" is a reading of the numbers. The sunlight does
  change from day to day. So the part of the homes' variation that all homes share, the weather, is lost, while one home's own
  variation, its people, is kept: the 200 homes together vary about 4 to 6% from evening to evening on ENGIE's weather, against 7 to 13%
  on real weather. A forecast error or a delivery figure from ENGIE's year is an easier case than reality.
- *The release has no weather forecast.* The forecast the agents read is ENGIE's temperature plus the error an issued forecast made on a
  matched measured day (about 1.9 °C on average). The forecast then misses by more than the weather moves: the reverse of real weather.
- *Prices and peaks have one shape all year.* The three dearest hours are 18:00 to 21:00 in every month, and the host's draw peaks at
  19:00 in every month. An evening costs about $75 per MWh in summer and $135 in January; the 45 dearest evenings all fall in December to
  February. The window is 18:00 to 21:00 all year. There is no summer afternoon peak, so the buildings' main lever, cooling, meets no
  dear hour.
- *There is no home, building, device or person.* A community is one total at its meter. What the host uses beyond the simulated homes
  and buildings is one block of other use that nobody controls, 68% of its year. From 18:00 to 21:00 the simulated parts stay inside the
  host's record in every month (0 of 4,380 quarter hours over, at least 584 kW to spare). Over all hours they exceed it in 2,058 of
  35,040 quarter hours (5.9%): late at night, when cars charge and air conditioners run, and around midday, where the host's solar is an
  estimate. There other use is held at zero, so the total is the simulation's, not ENGIE's record. The total equals ENGIE's record from
  18:00 to 21:00 only.
- *A community's solar is not metered.* ENGIE meters a community only at its connection. The host's solar by day is estimated from
  ENGIE's 35 metered solar plants, one slope for each month and hour (R² 0.92; the plants differ from 0.946 to 1.061 of the middle).
  After dark the host's use is exact; by day it is uncertain by that spread, and the buildings exceed the estimate in 4 to 12% of daytime
  quarter hours. Sunlight never reads zero at night: the referee counts a site as lit above 75 W/m², since night readings carry noise up
  to about 66 W/m².
- *A community's battery is its homes' batteries added up*, not one battery. The 2025 release does not say what it is; the 2023 release
  describes a community as the homes and businesses of a real county, with rooftop solar and home batteries on a share of its homes. The
  simulated homes carry batteries, solar and cars of their own on top of the host's record (2,160 kW and 3,603 kWh of batteries,
  1,636 kW of solar, 200 cars). Results at the aggregator's level use ENGIE's batteries only. A figure that adds ENGIE's community battery
  to the homes' batteries counts storage twice.
- *As recorded, the host's batteries give their energy before the evening*: full (90%) by about 11:15 every day, at their floor at 19:00
  on 96 to 97% of days.
- *The reports hold false and faulty reports by design*: reports in another participant's name, replays, notes aimed at the checker,
  and stuck values. A replay that takes each participant's power from the reports carries them, so a count of honest rows wrongly
  distrusted on such a replay has to set ENGIE's own false reports aside first.
- *Most slots have no meter reading in time.* 56 participants have a utility meter; 77% of their readings arrive within two hours and
  none within 30 minutes. A slot is checked against a meter only when its report has also arrived by the deadline: 52% of slots at two
  hours (`checked_against_a_meter`, `experiments/engie/referee/calls.py`). Nothing the 24 participants without a meter say about power
  can be checked. In the system's own runs only the community's report rows carry its meter (`meter_p_net_kw`, where the evening's feed
  gives one); a single site's rows carry none, and the aggregator's agent checks rows by their form and three row rules, against no meter.
- *There is no payment for a peak cut and no penalty for a missed promise*, only energy prices ($0.153 per kWh at 19:00 in winter).

## 3. ENGIE's 2023 release

**Holds.** A simulated year of the same grid with the same 80 participants at the same buses, and the state the 2025 release keeps back:
every transformer's true loading every hour (`grid_powerflow_results_2023.parquet`), each participant's net power and true battery power
every 15 minutes (`agents_timeseries_2023_15min.parquet`), the system's load and prices every 15 minutes
(`system_prices_and_load_2023_15min.parquet`), each participant's description and bus (`agents_metadata.parquet`), and each data
center's work that could be postponed, with how long it may wait.

**Used for.**
- The proof of the reading cleaner (`experiments/engie/meter_cleaning/proof.py`): the true 2023 loading is given the faults the 2025
  readings show (2.6 points of noise, single-hour jumps of 12 to 40 points, missing readings), cleaned by the same code and compared with
  the truth it came from. The cleaner keeps the number of shared patterns (2) that comes closest to the truth at loaded hours (true
  loading 70% or more).
- The ruler (`meter_cleaning/ruler.py`): each transformer's relief per MW given, separately for the three kinds of participant, fitted on
  the hours in the top 30% of load and checked on weeks the fit never saw, on the top 10% of load and on hour-to-hour changes.
- The data centers' work that can wait, in the recorded evenings.

**Limits.**
- The truth is 2023's. On 2023, with two patterns kept, 51 hours are truly at 80% or more; the faulty readings show about 185, the
  cleaned ones about 52, of which about 43 are true (means of three trials; `test_engie_published_cleaning_figures`). That says how far
  the 2025 count can be trusted; it is not the 2025 truth.
- The ruler is 2023's response carried to 2025. With every battery giving in proportion to its power, transformer 35 falls 3.14 points
  per 100 MW and transformer 38 1.16; all 80 batteries at full power relieve them by at most 7.7 and 2.8 points. On weeks the fit never
  saw it explains 96% and 99% of their loading (`test_engie_published_ruler`).
- Several sites change size between the releases (one data center from 8.7 to 46.1 MW peak). The data centers' postponable share
  (16.3% of their energy over 2023, 11 to 21% by site, waiting 4.5 to 10.5 hours) laid on 2025's load is a carry-over, not a 2025 fact.

## 4. The homes' and buildings' dataset

Read from the folder `MURMUR_DATA_DIR` names. The dataset for ENGIE's community is not in the repository; `tests/fixtures/data` is a
synthetic stand-in in the same file forms (section 9).

| File | Holds |
|---|---|
| `dataset.json` | `name`, `range`, `replay_start`, the clock (`tz_offset_h`, `tz_name`, `tz_label`), `holidays`, `baseline_from` (the first day a baseline may use), the community's place (`community`), `default_event`, the buyers' catalog file (`events_file`), the model folders (`models`, `models_2026`), every node's defaults (`agent_defaults`), `profile_alias`, `community_forecast_spread` |
| `fleet_v2.json` | the homes: profile, battery, solar, car, heating type, place, export limit, device tier (`tier`, 1 when unset) |
| `homes/<profile>.csv.gz` | every 15 minutes: solar kW, household kW, real-time and day-ahead price, sunlight, temperature, the forecast as issued (temperature, cloud, sunlight), kW per °C |
| `homes/<profile>_ev.csv` | the car's charging sessions: arrival, deadline, kWh, most kW, plug-in time |
| `homes/<profile>_hvac.csv.gz`, `hvac_params.json` | each house's cooling as it ran (kW, efficiency, indoor temperature, occupancy, mode) and its constants (heat loss, heat storage, time constant, cooling capacity, type) |
| `owners.json` | each owner's limits: how much warmer the house may get at home and away, pre-cooling, response, car charging kW, two-way car kWh |
| `devices/catalog.json`, `devices/<type>_<device>.npy` | by node type (`home`, `building`): each device's kind (shift, shed or source), rating and order; its draw by node (one row per node, as the catalog's `rows` maps them) and replay step, already inside the meter's load |
| `devices/price_book.json` | the price book (section 7) |
| `buildings.json`, `buildings/` | each building's load and cooling records, thermal and lighting constants, limits, and zone plans for the dataset's own days (`schedules.npz`) |
| `grid_events.json` | the catalog the stand-in buyer publishes |

### 4.1 Homes

200 Massachusetts house types placed in the host. Each is a simulated house: one thermal mass (heat loss 0.15 to 0.67 kW per °C, heat
storage 5.5 to 22.7 kWh per °C) whose furnace, heat pump or air conditioner holds the thermostat against the outdoor temperature and the
sun. One of six household types sets who is home, with the holidays and school breaks of 2025. Appliances are owned at the federal
household survey's rates and draw their products' ratings; roof solar is the host's sunlight through the research house's measured
conversion; batteries and chargers follow their datasheets; each car has charging sessions with an arrival, a departure and the energy
owed. On ENGIE's days heating and cooling are worked out again on ENGIE's weather.

A home's tier picks its agent's tool shelf (`src/murmur/node/shelves.json`), and the agent sees only the devices whose tool is on it
(`src/murmur/node/see.py`). Tier 3 holds car charging only (`limit_ev_charging`). Tier 2 adds the battery (`set_battery`), the thermostat
(`set_thermostat`, 116 homes) or the room air conditioners (`set_room_ac`, 84) and the water heater (`set_water_heater`). Tier 1 adds the
two-way car (`discharge_car`, all 200), the dishwasher and dryer (`delay_appliance`, 193) and the pool pump (`set_pool_pump`, 21). The
water heater, the two-way car, the dishwasher, the dryer and the pool pump also need their row in the device catalog and their name in
`MURMUR_DEVICES` (section 10). At tier 3, on ENGIE's weather with the community agent, the recorded runs promise 47.9 kW and pay a home
$0.23 an evening on average (`demo/page_builder/year_results/data/two_versions.json`, `pay.json`). Eight homes (`home-01` to `home-08`)
run as nodes on the message network in the recorded evenings; all 200 take part in the year's offline runs.

Checks, made on the Massachusetts build of the same simulator on measured weather: against load research's average home, shape of the
day r = 0.92 and daily energy r = 0.81, the homes using 1.36 times that home; against the research house, heat pump r = 0.95 to 0.97 and
solar 954 to 975 kWh per kW a year, against 985 measured; appliance ownership as the survey gives it (section 6).

**Limits.**
- No home is a real household: load, devices and people are simulated, calibrated against measured sources but not measured.
- No public measured home-charging data exists: when cars leave, return and charge is assumed. Tier 1 gives every home's car the
  two-way tool, an ideal case: only 34 of the 200 cars can power a home.
- The household types and each owner's limits are assumptions: how much warmer the house may get (0.8 to 3.0 °C), a car timer
  (118 homes), devices that are off limits (189 owners). The notes the small models read are written for the tests, each with its true
  meaning set down first.
- The homes are Massachusetts house types inside a Midwest community, and their storage, solar and cars come on top of the host's own
  (section 2).

### 4.2 Buildings

The shops (`building-01`) and the small office (`building-02`) are a full shopping-center and office model at 4% of their size, on
ENGIE's weather: the office averages 39 kW with a peak of 58 kW, the shops 81 kW with a peak of 156 kW. The city's building energy reports
check their size and the utility's business classes give their hourly shape (section 6). Zone plans give each zone's occupancy as planned
the day before and as the day went; the maps packaged in `src/murmur/node/buildings/` cover 1 October 2025 to 30 September 2026, and a
dataset on other days brings its own `buildings/schedules.npz` in the same layout. Equipment and its rules come from makers' documents:
145 products of 90 brands in 41 kinds, and 224 control rules checked against them and the mechanical code, which the guard keeps. A
building's own devices (the catalog's building rows: fans, plug loads, car ports) always take part; `MURMUR_DEVICES` does not switch them
(`src/murmur/node/simulator_building.py`).

**Limits.**
- On ENGIE's smooth weather every weekday comes out almost the same, so in the ENGIE-weather version the day-to-day variation of the
  Boston Public Library's meter is laid over both buildings, held to 0.6 to 1.25 of their own. The library is neither an office nor a
  mall: the size of the variation is a real building's, its cause another building's, and in summer it carries the library's answer to
  Boston's weather. The real-weather version leaves it out: the buildings then answer the weather themselves, and both together would
  count the weather twice.
- No measured office or mall of this size is in the data. How cooling, fans, lights and plugs split among zones is assigned by floor
  area: no public source gives it. Occupancy on ENGIE's 2025 days is borrowed from the maps' year. The managers' notes are written for
  the tests.

### 4.3 Forecast models

Read from `MURMUR_MODELS_DIR`, in the folders `dataset.json` names (`models`; `models_2026` for `fleet_errors.json`). A home reads them
only with `forecast = "trained"`. The community agent reads them when a sale opens, with `community_forecast` (on by default in a
pooled market), whatever `forecast` says (`src/murmur/agents/community/market_above.py`, `forecast.py`): its outlook loads
`home_base_load` and `solar_per_kw`, then `community_load`, and fits its own hours only when `fleet_errors.json` is there and at least
21 whole days precede the forecast; with fewer, `community_load` answers. A missing model file makes the outlook fail, and the sale
goes on without it. The demo example writes all four (section 9), and its outlook fits its own hours on 22 days.

| Model | What it forecasts | Trained on |
|---|---|---|
| `home_base_load` | a home's base load, 10, 50 and 90% quantiles (gradient-boosted trees) | 100 synthetic homes |
| `solar_per_kw` | solar per kW of panel, corrected for each hour of the day by the array's last 14 days | the research house's solar |
| `ev_window` | the energy a car takes from 15:00 to 20:00; read only when its file exists | synthetic homes with cars |
| `community_load` | a community's demand by hour while fewer than 21 whole days of its homes' summed load precede the forecast; from then on each hour is fitted on its last 42 such days against the issued forecast's cooling degrees above 20 °C, heating degrees below 10 °C and a day-off flag, and the model stands aside | load research's average Massachusetts home, May 2025 to June 2026 |
| `fleet_errors.json` | not a model: the days kept out of every fit (`kept_out`) | |

Inputs are the home's own record, the calendar and the weather forecast as issued about 48 hours ahead (ECMWF). The default forecast,
`temp_regression`, is a straight-line fit on temperature from the home's own record and needs no models; the demo runner sets it for
every part.

**Limits.**
- The models are trained on the measured Massachusetts year and used on the same households on ENGIE's days.
- On ENGIE's weather a forecast that reads the weather shows no clear advantage over a plain rule. Over the year the buildings' plain rule (the
  last day of the same kind) misses by 1.68% (office) and 1.81% (shops), a trained model on the weather forecast by 2.56% and 3.14%. Over
  37 evenings the homes' trained models miss by 41.9% a home and 8.2% together, the rule of the previous three days by 44.5% and 7.8%.
  That says ENGIE's weather has little to forecast; it does not say trained models are no better on real weather.

## 5. Weather

ENGIE's weather is section 2's: hourly air temperature and sunlight at each site, with its limits.

**Measured weather.** Massachusetts, 2025-26, with day-ahead forecasts as issued about 48 hours ahead (ECMWF), per 15-minute step in the
homes' files. Used for:
1. the forecast the agents read on ENGIE's days: ENGIE's temperature plus the issued forecast's error on a matched measured day;
2. the real-weather version of the year: ENGIE's temperature plus the measured year's day-to-day movement, matched by month and day, with
   the forecast missing by what the issued forecast missed that day. Its daily mean moves 2.65 °C from one day to the next (measured:
   2.62 °C), its monthly means stay within 0.9 °C of ENGIE's, and its coldest day is −11.6 °C and its warmest 33.3 °C. The homes and
   buildings are rebuilt on it by the same build;
3. the homes' checks on the Massachusetts build (section 4.1).

**Limits.**
- In the real-weather version only the temperature moves. Sunlight, prices, the host's record, the batteries and the request stay
  ENGIE's, so a hot day can fall on a day ENGIE's sky was cloudy, and ENGIE's community and prices do not answer a cold snap.
- Real weather hardly changes the sale and does change its measurement. At tier 1 with the community agent the homes and buildings offer
  1,769 kW on ENGIE's weather and 1,770 kW on real weather and promise 1,481 and 1,501 kW: what is sold is device capacity (batteries, car
  charging, water heaters), which does not follow the weather. The buyers' baseline is off by 9.2% and 11.7%
  (`demo/page_builder/year_results/data/two_versions.json`). ENGIE's smooth weather flatters the measurement, not the sale.
- The measured weather is Massachusetts', not that of ENGIE's community.

## 6. Measured public sources

| Source | Grain | Used for | Limit |
|---|---|---|---|
| A measured multi-story instrumented research house dataset, circuit-level heat pump, lighting, and plug loads | one house's circuits | every home's roof solar (sunlight through its measured conversion), `solar_per_kw`, how a heat pump answers the cold | one house: its roof and its heat pump stand for all 200 |
| Load research: a Massachusetts utility's residential average home and its business classes | hourly class averages | the homes' load checks, `community_load`, the buildings' hourly shape | an average smooths every single home's variation |
| The federal household survey (EIA RECS 2024), Massachusetts single-family homes | ownership rates | which home owns which appliance: dishwasher 88%, electric dryer 76%, second fridge 43%, freezer 31%, pool 10%, hot tub 6% | ownership only: when an appliance runs comes from the household type, what it draws from its product |
| Makers' datasheets: current US products, 172 for homes (108 brands, 22 kinds) and 145 for buildings (90 brands, 41 kinds) | one record per product | every device's rating and limits | of 191 home product records checked against their sources, 93 are right, 61 corrected and 37 still open |
| The city's building energy reports (BERDO 2025) | a year's use per building | the buildings' size: the office uses about what 56 Boston offices report (middle size 37,000 sq ft), the shops match 8 strip malls and stores (50,000 sq ft) | a year's total only: no hour-by-hour record of such a building |
| The Boston Public Library's meter | kW every 5 minutes, 380 usable days | the buildings' day-to-day variation on ENGIE's weather | not an office and not a mall |

## 7. The price book and the order's price

`devices/price_book.json` in the dataset is read by `src/murmur/settlement/rules.py` and `src/murmur/agents/community/gaps_settle.py`.
It holds `x` (each class's share of the order's price), `coordinator_keeps`, `kept_split`, `same_day_adjustment`, `as_of` and `note`, and
no price.

- A buyer orders a cut at a price per kWh. The demo runner posts each buyer's order at `PRICE_USD_KWH`, $2.04 (`demo/runner/evening.py`),
  which the evening file's `price_usd_per_kwh` overrides, with a deposit of 10% of what the order could cost. The stand-in catalog's
  form-only need carries the same $2.04 (`demo/runner/synthetic.py`).
- Each measured kWh is billed at the order's price times its class's rate, `x` / (1 − `coordinator_keeps`): 1 for a home battery or a
  two-way car, 0.725 for a building, 0.2625 for any other home device ($2.04, $1.479 and $0.5355 at $2.04). Of each bill 0.3 is kept,
  0.1 by the community's operator and 0.2 by the aggregator; the members get 0.7, so a node earns the order's price times 0.7, 0.5075 or
  0.18375 (`x`) for each kWh it delivered.
- Delivery is measured against a baseline: the mean of the last 10 days of the same kind (weekday or weekend, no holiday or event day,
  none before `baseline_from`), plus, with `same_day_adjustment`, the meter's load in the hour starting 2 hours before the event above its
  baseline. With fewer than 10 such days the baseline falls back, flagged: the clean days of the same kind in the last 45, then the clean
  days of any kind, then the sale days of the same kind with the recorded delivery added back, then none.
- The $2.04 is $275 per kW a year, a Massachusetts programme's payment for home batteries' average performance from June to September,
  divided by 135 event hours (45 events of 3 hours). The division is an assumption. The programme calls 30 to 60 events of at most
  3 hours, so the same payment is $3.06 to $1.53 per kWh.
- Every dollar figure rests on it: at tier 1 on ENGIE's weather buyers pay $8,022 an evening and a home earns $27.75
  (`demo/page_builder/year_results/data/pay.json`), about $1,249 over 45 evenings. At the $0.75 per kWh an Illinois utility's peak-time
  rebate pays, nearer ENGIE's communities, the same home would earn about $459 a year (`demo/page_builder/replay/trial.py`); the replay
  page puts it at about $330 to $360 at the Midwest capacity price.
- No amount is decided by a price: the battery plan reads only the grid's loading. Request and report rows carry price columns
  (`price_usd_kwh`, `quote_price_usd_kwh`) because the report follows the layout ENGIE's participants send.

## 8. Recorded runs in the repository

| Path | Holds |
|---|---|
| `demo/recordings/evening_2025-01-28/` | the evening of 28 January 2025 on ENGIE's data, recorded over a message network: eight homes, the shops and the office, their community agent, the aggregator's agent, two solar-and-battery plants (`site-pv-01`, `site-pv-02`) and a data center (`site-dc-01`); every step and envelope, with neutral ids |
| `demo/recordings/whole_evening_2025-01-28/` | the same evening with twelve single sites |
| `demo/recordings/year_engie_weather/`, `year_real_weather/` | twelve evenings of 2025, one a month, on each version of the weather, with `results_engie.json.gz` |
| `experiments/engie/year_runs/evening_runs.json.gz` | the 48 evenings as chosen before any run, and the 576 offline runs made on them (48 evenings × 3 tiers × 2 weather versions × with and without the community agent): each run's promise and its members' delivery by half hour, by the truth and by the buyers' meter, and its money |
| `experiments/engie/referee/model_readings.json` | the small model's recorded answers on the notes: its answer on each of the 530 new texts, and the 9 everyday sentences it answered wrongly, each keyed by the first 16 hex digits of the text's SHA-256; the fresh-set texts it answered wrongly, which are not ENGIE's, as plain text. No text of ENGIE's release |
| `demo/page_builder/*/data/`, `demo/page_builder/facts/` | the figures the pages quote, cut down from run results and ENGIE's ratings. The six files of `year_results/data/` say what they hold in `what`; `overview/data/` says where its figures come from in `about` and `from`; `explainer/data/` and `facts/` say neither |

**Limits.**
- In every recording the devices and meters are simulated (the signatures are real), the members' batteries are replayed from ENGIE's
  record as one total, and stand-ins take the place of the buyers and of the aggregator's own agent.
- The recorded evening states a need of 342 MW at 19:00 and 22 MW at 20:00, from the readings cleaned with the whole year; the past-only
  cleaning that `peak_allocation` reads states 346 and 14 MW. The request to the host's batteries is the same on both: 1,624 kW at 19:00
  and about 1,530 kW at 20:00. `peak_allocation` writes the year's counts, not the per-participant request rows a recording carries.
- `year_runs compare` recounts the recorded runs. Running the 576 runs again needs the homes' dataset, which is not in the repository.
- `demo/page_builder/year_results/data/with_and_without.json` differs from the recount in two figures: 1,769.2 kW promised without the
  agent (ENGIE's weather, tier 1) and a mean miss of −41.0% (tier 3, without), where `year_runs compare` writes 1,769.3 and −41.1.

## 9. What is synthetic

- `tests/fixtures/data/` and `tests/fixtures/sites.json`, written by `python tests/fixtures/make_fixtures.py` from
  `demo/runner/synthetic.py`: one community over two days of 15-minute steps (27 and 28 January 2025) with three homes (`home-01` to
  `home-03`, all with a battery, two with a car), a small office (`building-01`, 30,400 sq ft, no battery), their devices (water heater,
  dryer, two-way car; fans, plug loads), a price book marked synthetic with the shares of section 7, a catalog for the stand-in buyer
  with one form-only need (400 kW at $2.04) and one form-only offer, both marked "the form of an order; never played", and two single
  sites (`site-pv-01`, 900 kW; `site-dc-01`, 400 kW) with a feed and a request each. The weather is a daily curve around −4 °C with noise,
  its forecast the same curve with more noise, the price $42 per MWh plus $110 from 17:00 to 21:00. Every number comes from one seeded
  generator and the gzip files carry no timestamp, so the files are the same bytes on every machine; `tests/test_runner.py` holds the
  committed files to that.
- `tests/experiments/releases_for_peak.py`: a pair of ENGIE-like releases, five weeks of each year, with ENGIE's file names, columns and
  clocks and made-up numbers. The 2023 release holds a true grid state with a known response to the batteries, so the ruler has a right
  answer. The 2025 release holds noisy readings of the same ten transformers (jumps, gaps, rows of bad quality or of another source) and
  nine participants' battery reports (slots never sent, late copies, reports in another's name, bad signatures, one spike of charge),
  beside one participant without a battery. The meter cleaning and the peak allocation run on it whenever pandas and pyarrow are
  installed.
- The demo's example evening (`demo/runner/example.py`, written by `python -m demo.runner example --out out/example`): the same synthetic
  community over 25 days from 5 January 2025 (to 29 January), and the evening of 28 January from 18:00 to 21:00. The three homes and the
  office answer two buyers (the utility 9.0 kW, the grid operator 5.4 kW) through the community agent; `site-pv-01` and `site-dc-01`
  answer the aggregator. It adds the community's definition (a connection limit of 120 kW, 75 kW of solar, a battery of 40 kW and
  110 kWh, its meter from 20 January 10:00 to 27 January 10:00, its members' devices), the evening's feed by quarter hour from 27 January
  10:00 to 29 January 02:45, the aggregator's request to the battery (32 kW from 19:00 to 21:00), and `models/forecast/` with three
  plain one-leaf tree models and a `fleet_errors.json` that keeps no day out. `community_load` gives the community's load as the mean
  of its own last 14 days, within 10 % either way; `home_base_load` and `solar_per_kw` are the homes' two models the community's
  forecaster is built on, which replaces the load one and has no array of its own. With 22 whole days before the call for offers the
  community's outlook fits its own hours; `community_load` is what it falls back to with fewer than 21. `demo/runner/config.example.json`
  reads the example (`data_dir`, `"models_dir": "../../out/example/models"`, `evening`, `sites`), sets `"host": "127.0.0.1"` and adds
  one owner's note at 17:00.
- The referee's fresh set (`experiments/engie/referee/fresh_notes.json`): 30 notes written to push a checker and 30 harmless look-alikes,
  none from ENGIE's data, written alongside the reader, so not an independent test. The owners' and managers' notes in the tests are
  written likewise.
- The lies the referee plants in ENGIE's own reports (`referee/plant.py`): ten kinds, up to 150 runs of 8 slots (2 hours) per kind, each
  at least 16 slots from any other, of kinds and sizes chosen here, not by ENGIE.
- The demo's stand-ins: the model (`demo/runner/model.py`) answers the chat route by rule, and nothing it says decides an amount; the
  buyers (`demo/runner/buyers`) take the orders the runner posts, contract with the community agent, send baselines, settle on the
  members' signed readings and call on short notice at an `emergency` event.
- What-if weather (`src/murmur/replay.py`): off by default. A node host's `POST /demo/scenario` with `{"weather": {pv, load, dT, from,
  hours}}` (the runner's `cloud` event sends one) scales the homes' solar (0 to 1.5) and household load (0.5 to 2) or moves their
  temperature (up to 15 °C either way) from a given moment; forecasts made earlier do not know it.

## 10. Where data comes from at run time

Every data folder is a setting. Every address a part listens on or calls is a setting: in a part's `agent.json`, in the runner's
configuration, or in the `--host` and `--port` the runner gives the bus and the stand-in model (a buyer takes `--port` and listens at
its `bind_host`). The loopback address, 127.0.0.1, is only the default of `bind_host` and of the runner's `host` (below).

| Setting | Read by | What it names |
|---|---|---|
| `MURMUR_DATA_DIR` | every node, the community agent, the buyers, settlement (`src/murmur/config.py`) | the dataset a node replays (section 4). Unset: the `data` folder beside the package, `src/data` in a checkout |
| `MURMUR_MODELS_DIR` | the community agent when a sale opens, with `community_forecast`; a home with `forecast = "trained"` | the trained models (section 4.3). Unset: `src/models` |
| `MURMUR_DEVICES` | `src/murmur/node/devices.py`, for a home's simulator and the settlement's meter check (`settlement/meter_check.py`) | the home devices that take part besides batteries and cars: `all`, a comma list, or unset for none. A building's own devices always take part (section 4.2) |
| `MURMUR_CONFIG_DIR` | every service (`src/murmur/config.py`) | a part's configuration folder: `agent.json`, `secrets/` (keys, join tokens, bus grants; never in the repository) and `state/`. Unset: `.config/murmur` in the home folder |
| `MURMUR_LOG_DIR` | every service | where it writes its logs. Unset: `logs/` in the configuration folder |
| `--data-dir`, else `MURMUR_ENGIE_DATA_DIR` | `experiments/engie` | the folder that holds ENGIE's releases (sections 2 and 3) |
| `MURMUR_NOTES_MODEL_URL`, `MURMUR_NOTES_MODEL` | `experiments/engie/referee` | a model server asked for the notes in place of the recorded answers |

**Addresses** sit in a part's `agent.json`, which the runner writes for a demo run (`demo/runner/stack.py`): `bind_host` (the address
every service listens on; `src/murmur/config.py` gives 127.0.0.1); `town_url` and `town_run_id` (the message bus); `llm_enabled` (off by
default), `llm_url` and `llm_model` (a node's model server); `community_port`, `host_port`, `buildings_port`, `aggregator_port` and
`site_port` (the services' ports); `utility_url`, `host_url`, `building_urls` and `clock_extra_targets` (where the community agent
reaches the first buyer, the homes' host, each building and the other clocked parts). The runner's `host` (`demo/runner/settings.py`;
127.0.0.1 when the configuration names none) is every part's `bind_host` and the host of every address the runner hands out, its
bus's, its stand-in model's and its state feed's included; a model server of one's own must be on it. Only the homes' and the
buildings' hosts get a model's address: the other parts get no `llm_url`. Every model server is asked at `POST {url}/api/chat`.

**Behaviour switches.** `MURMUR_BATTERY_MODE=backup` keeps batteries from covering their own site's load, so they wait for sales (a
building with a battery refuses to start without it). `MURMUR_LEAD_MIN` is how many minutes before a sale opens the agent plans it
(default 30). `MURMUR_DRIVERS` is `simulated` (the default) or `real`, whose drivers refuse every write. `MURMUR_CAREFUL_NOTES` sets the
careful note step on or off (unset: the configuration's `careful_notes`, off by default). `MURMUR_CHARGE_KW` caps a battery's charging
(unset: no cap).

**The demo runner's configuration** is one JSON file (`demo/runner/settings.py`; relative paths from its own folder): `run` (the run's id
on the bus), `host` (the address every part listens on and is called at; 127.0.0.1 when none is given), `folder` (must not exist yet;
`{time}` stands for the start time), `ports` (`"free"`, or a first port of 51000 or above), `data_dir` (must hold `dataset.json`),
`models_dir` (may be empty), `evening`, `sites`, `step_seconds` (2 to 120), `quiet_s`, `devices` (default `all`), `model`
(`{"stand_in": true}`, or a `url` on `host` with a `name`), `events` (`note`, `car_now`, `building_closed`, `zone_event`, `cloud` or
`emergency`, each `at` a `YYYY-MM-DD HH:MM`) and `feed_port`. The evening file needs `date`, `window`, `homes`, `order_kw`,
`community_definition` and `feed`, and may carry `buildings`, `battery_request` and `price_usd_per_kwh`; the sites file is
`{"sites": {name: {"site", "feed", "requests"}}}`. Every part it starts gets `MURMUR_DATA_DIR` and `MURMUR_DEVICES`, each service a
`MURMUR_CONFIG_DIR` in the run folder (the buyers share the community agent's), and all of them `MURMUR_MODELS_DIR` only when
`models_dir` is set (`demo/runner/stack.py`).

**ENGIE's data.** `--data-dir` names one release's own folder or a folder that holds the releases as subfolders under any names. A release
is known by a marker file, `reports.parquet` for 2025 and `grid_powerflow_results_2023.parquet` for 2023; among subfolders, exactly one
must hold each marker. A missing folder or release stops a pipeline with exit code 2 and a line that names what is missing. A pipeline
writes only into its `--out` folder, except that `peak_allocation` runs the meter cleaning into its `--cleaning` folder (section 11.1),
which may lie outside it. None contacts a network service, except the referee when it is given a model server.

**Tests.** Default `pytest` (`tests/conftest.py`) sets `MURMUR_DATA_DIR` to `tests/fixtures/data`, `MURMUR_MODELS_DIR` to
`tests/fixtures/models` (no such folder: a test that needs trained trees writes tiny ones to a temporary folder), `MURMUR_DEVICES` to
`hpwh,dryer,v2h,fans,plugs` (`fans` and `plugs` change nothing: they are a building's own), the configuration folder to a fresh temporary
one and `MURMUR_LOG_DIR` to `logs/` in it, and removes every other `MURMUR_*` variable except `MURMUR_ENGIE_DATA_DIR` and
`MURMUR_PUBLISHED_DIR`. A test marked `engie_data` skips with the reason "needs ENGIE's dataset: set MURMUR_ENGIE_DATA_DIR to run it"
when that variable is unset, and the comparison with the published pages (`tests/page_builder/test_pages.py`) skips without
`MURMUR_PUBLISHED_DIR`. When the folder lacks a release, the meter-cleaning and peak-allocation tests skip and name it (`engie_root`,
`tests/experiments/releases_for_peak.py`); the referee's and `year_runs`'s fail.

Not in the repository: ENGIE's two releases (from ENGIE); the homes' and buildings' datasets and trained models, for ENGIE's community
and for the measured Massachusetts year, and the code that builds them; the measured sources behind them (section 6); run folders, since
every run makes its own keys.

## 11. The four measured results and how each is reproduced

Commands run from the repository root. `meter_cleaning`, `peak_allocation`, the referee and `year_runs choose` need the `experiments`
extra (pandas, pyarrow) and ENGIE's data; `year_runs compare` and `year_runs evening` need neither. Without the extra,
`tests/experiments/test_meter_cleaning.py`, `test_peak_allocation.py` and `test_referee.py` skip at import.

| # | Result | Reproduced by | Reads | Held by |
|---|---|---|---|---|
| 1 | Holding the 80 participants' batteries for the peak takes the hours with a transformer at 80% or more from 96 to 19. The plan reads only the grid's loading, no price. Without the plants' batteries 84 remain | `python -m experiments.engie.peak_allocation --data-dir DIR --out OUT` | both releases | `tests/experiments/test_peak_allocation.py::test_engie_headline_result_one` (`engie_data`) |
| 2 | A community, a solar-and-battery plant and a data center answer the same aggregator in the same three signed messages, on a real message network | `python -m experiments.engie.year_runs evening --out OUT` | the recorded evening of 28 January 2025 | the command's exit code; `tests/experiments/test_year_runs.py::test_the_recorded_evening_answers_in_three_signed_messages` |
| 3 | The community agent leaves delivery and pay unchanged and makes the promise honest: over 48 evenings the true shortfall is 2.7% with it and 16.9% without it | `python -m experiments.engie.year_runs compare --out OUT` | `experiments/engie/year_runs/evening_runs.json.gz`; `demo/recordings/year_*/results_engie.json.gz` | `tests/experiments/test_year_runs.py::test_with_and_without_the_community_agent` and `::test_the_recording_holds_the_48_evenings_and_576_runs` (default suite, no pandas) |
| 4 | A language model reads what people write less reliably than code handles numbers, so code decides every amount and a note can only become a limit | `python -m experiments.engie.referee --data-dir DIR --out OUT` | the 2025 release and the recorded model answers | `tests/experiments/test_referee.py::test_the_recorded_answers_and_the_fresh_set` (with pandas and pyarrow) and `::test_the_published_table_from_engies_data` (`engie_data`); `tests/test_note_reader.py` for the rule |

**1. Peak allocation.** It stands on three things, each proven before use: the 2025 readings cleaned with the past only and the ruler by
kind of participant, both from `meter_cleaning`, and each battery's recorded behaviour (`experiments/engie/fleet.py`). On its own,
`python -m experiments.engie.meter_cleaning --data-dir DIR --out OUT` writes `cleaning.json`, `cleaning_past_only.json`, `ruler.json`,
`loading_2025_clean.npy`, `loading_2025_clean_past_only.npy`, `ruler_by_kind.npy` and `transformers.json`. `peak_allocation` reads the
cleaning from `--cleaning DIR`, by default `OUT/meter_cleaning`; when that folder lacks `loading_2025_clean_past_only.npy`,
`ruler_by_kind.npy` or `transformers.json` it runs the meter cleaning into it first, and it refuses results made for other transformers.
The past-only cleaner uses the other year's patterns for the first 3 days, learns them again daily up to day 28, then every 7 days
(`meter_cleaning/cleaner.py`). At 14:00 the plan expects tonight's loading from yesterday evening's, moved by how this morning (08:00 to
12:00) differs from yesterday morning; on the first day, with no yesterday, each asked battery gives a third of its usable energy in each
hour from 18:00 to 21:00. It takes true overloads first, as many hours as the batteries can bring under 100%, then as many hours as they
can bring under 80%, those that need least first; it splits each hour's amount by the energy each battery still has, and sends what is
left to strained hours it cannot clear, then to the evening's highest-loaded hours. The whole year is replayed every 15 minutes inside
every battery's charge band (10 to 90%), power and connection limit (`peak_allocation/replay.py`): from 14:00 an asked battery gives what
the plan says, from 12:00 to 14:00 it only charges as recorded, before noon it runs as recorded, and a battery nobody asks runs as
recorded all day. The loading after it is the cleaned reading less what the batteries' change moves each transformer, by the ruler.
`OUT/peak_allocation.json` holds 96 hours as recorded, 19 with every battery asked (all at 19:00), 84 with the plants' batteries left out
and 81 with the communities' alone, with no limit broken and no hour at 100% in any case. `test_engie_readings_as_they_come`,
`test_engie_published_cleaning_figures` and `test_engie_published_ruler` (`tests/experiments/test_meter_cleaning.py`, `engie_data`) hold
the meter cleaning's own figures (sections 2 and 3). With pandas and pyarrow installed, both pipelines also run in the default suite on
the synthetic pair of releases, where the right answers are known.

**2. Three signed messages.** `year_runs evening` reads every envelope of a recorded evening (by default
`demo/recordings/evening_2025-01-28/trace_engie_2025-01-28.json.gz`; another with `--recording`) and writes `OUT/evening_messages.json`.
On that evening four participants answer the aggregator: the community, `site-pv-01`, `site-pv-02` and `site-dc-01`. Each receives a
`community.request` signed with the aggregator's one key, answers with a `community.answer` signed with its own key, and sends signed
report rows (`community.report`) in ENGIE's participants' layout (`entity_id`, `timestamp`, `reported_p_net_kw`, `reported_soc_percent`,
`quote_side`, `quote_price_usd_kwh`, `text`, and `meter_p_net_kw` for the community's meter) that the aggregator's agent keeps: 155, 156,
156 and 156 rows, none flagged. The command exits 0 when every request has the same signer, the answers that came have distinct signers
that signed no request, and every report was sent and kept with none flagged; it does not require every participant to answer. It reads
the recording; it does not run the network again. In process, `tests/test_sites_aggregator.py`, `test_site_answers.py` and
`test_aggregator_keys.py` exercise one solar-and-battery plant (`site-pv-01`) and the aggregator's side of its exchange; no test runs
the community's or a data center's exchange with the aggregator in process. The whole exchange runs live on the local bus with
`python -m demo.runner evening --config demo/runner/config.example.json` after `python -m demo.runner example`.

**3. The community agent.** `year_runs compare` counts every one of the 576 recorded runs the same way and writes
`OUT/with_and_without.json`. At tier 1 on ENGIE's weather over the 48 evenings: promised 1,480.5 kW with the agent and 1,769.3 kW without
it (it then promises everything offered); delivered by the truth 1,468.4 and 1,469.6 kW; true shortfall 2.7% and 16.9% of the promise;
evenings truly kept 22 and 0; members paid $5,617 and $5,622 an evening. The other tiers and the real-weather version are in the same
file. It also counts how many evenings of each recorded year set (`demo/recordings/year_*/results_engie.json.gz`) are their month's
dearest of the 48: 12 of 12 for both (`test_the_year_sets_are_each_months_dearest_evening`). `year_runs choose --data-dir DIR --out OUT`
derives the 48 evenings again from ENGIE's 2025 prices by the rule (four a month: the two dearest from 18:00 to 21:00 and the two nearest
the month's middle, at least three days apart, a weekend evening among them, no holiday, no clock-change day, not the year's first week),
writes `OUT/evenings_48.json` and exits 1 when they differ from the recording's. The runs themselves are recorded, not run again
(section 8).

**4. Notes.** The referee calls every report slot of the 2025 release at ENGIE's two deadlines, 30 minutes and 2 hours, from what had
arrived by each, and writes `referee.json`, ENGIE's `decisions.parquet` and `agents.parquet`, `notes.json` and `plant.json`
(`experiments/engie/referee/README.md` gives under a minute and about 11 GB of memory on the full release). In `notes.json` code learns
107 everyday sentences from the warm-up months. From March on, 1,351 of 2,342,321 notes carry words outside them (530 distinct texts),
and only those words reach the model. The model flags 1,336 of the 1,351 (a word pattern, 399). It would wrongly flag 9 of the 107
everyday sentences, which never reach it because code knows them. On the fresh set it catches 29 of the 30 notes written to push a
checker (the pattern, 5) and wrongly flags 3 of the 30 harmless look-alikes (the pattern, 6). The model's answers are replayed from
`model_readings.json`, or from another file with `--readings FILE` (a named file that is missing stops the run with exit code 2); with
no readings file at all the word pattern `NOTE_PAT` stands in. Everything else is derived from the data. With `MURMUR_NOTES_MODEL_URL`
and `MURMUR_NOTES_MODEL` set, a run asks that model server instead and writes the answers it got to `OUT/model_readings.json`. On the
nodes, `tests/test_note_reader.py` holds the rule that follows: a malformed reply, an unknown tool, a value out of range, an end already
past, a server that errors or answers too late each leave code's own result.

The referee's limits: no score (ENGIE keeps the labels, and the planted kinds and sizes are chosen here); not a valid entry (several
thresholds and the model's instructions are set with the whole year in view); blind spots by design of the data (lies under 5% of a
participant's size, the 24 participants with no meter, the first 30 minutes, charge lies where the battery has no reading of its own);
"compromised" (40 of 80) is a judgement.

## 12. What is not shown

- **A price for a peak kilowatt.** ENGIE's data has energy prices only. Every dollar figure uses the order's price of $2.04 per kWh and
  the price book's shares (section 7).
- **Anything on real devices.** Every battery, car, thermostat and water heater is the simulator's model. The real drivers (Home Assistant,
  Matter, BACnet, OCPP, Modbus) refuse every write (`src/murmur/node/drivers.py`). Meters are the simulator's; the buyers and the
  aggregator's own agent are stand-ins.
- **That AI beats plain rules.** Code decides every amount and the model only reads words. Where the model is measured, on the referee's
  notes, it reads only the words code does not know, and it still errs where code does not (9 of the 107 everyday sentences, 3 of the 30
  look-alikes). On ENGIE's weather trained forecasts do no better than plain rules (section 4.3).
- Nor the 2025 grid's truth (every 2025 count of strained hours rests on cleaned readings), a score against ENGIE's labels, a measured
  office or mall of the buildings' size, or measured home charging.
