"""The Data view: the two-view page's second layout. The map stays on the left as the split view draws it; each box carries
four squares in a fixed order (ENGIE, product survey, measured records, our estimates), filled where the part reads that kind
of source, and a click on a part opens a panel on how its data was built. This is the page's "fg-dv" data element; the figures
are read from the year's files, kept in facts/data_view.json."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

FACTS = Path(__file__).resolve().parent.parent / "facts" / "data_view.json"

KINDS = {"e": ("ENGIE", "ENGIE's own data", "Its 2025 records, used unchanged."),
         "s": ("Survey", "Product survey", "Current US products, read from their makers' datasheets."),
         "m": ("Measured", "Measured records", "Public records: utility load research, a federal survey, city reports, measured buildings."),
         "o": ("Ours", "Our estimates", "Set or computed by us where no record exists.")}

# each box of the map: the kinds it reads (in the order e s m o) and the panel a click opens
BOX = {"agg-clean": ("e", "clean"), "agg-share": ("eo", "share"), "mkt": ("", "req"), "agg-ref": ("eo", "ref"), "buy-u": ("eo", "buy"), "buy-g": ("eo", "buy"), "utl": ("e", "utl"),
       "co-fc": ("eo", "fc"), "co-cover": ("o", "cover"), "co-agent": ("e", "batt"), "co-market": ("o", "clear"), "co-desk": ("o", "clear"), "co-report": ("eo", "clear"),
       "town": ("", "town"),
       "h-agent": ("esmo", "homes"), "h-model": ("o", "hnotes"), "h-tools": ("s", "hguard"), "h-guard": ("so", "hguard"), "h-seal": ("", "hguard"), "h-driver": ("s", "hguard"),
       "h-dev": ("esmo", "hdev"), "h-person": ("o", "people"),
       "b-agent": ("esmo", "blds"), "b-model": ("o", "bnotes"), "b-tools": ("s", "bguard"), "b-guard": ("s", "bguard"), "b-seal": ("", "bguard"), "b-driver": ("s", "bguard"),
       "b-dev": ("so", "bdev"), "b-person": ("o", "occ"),
       "site-pv": ("e", "pv"), "site-dc": ("eo", "dc"),
       "r-read": ("o", "ret"), "r-check": ("", "ret"), "r-settle": ("o", "ret"), "r-pay": ("o", "ret"),
       # parts of the map that are not boxes: the community's own frame, and the lines inside a single site's frame
       "host": ("eo", "host"), "site-pv-1": ("e", "pv"), "site-pv-2": ("e", "pv"), "site-pv-3": ("o", "pv"), "site-dc-1": ("e", "dc"), "site-dc-2": ("eo", "dc"), "site-dc-3": ("", "dc")}


def payload() -> dict[str, Any]:
    """The Data view's data: the four kinds of source, each box's kinds and panel, and the panels in order."""
    F = json.loads(FACTS.read_text(encoding="utf-8"))
    n0 = lambda x: f"{x:,.0f}"          # noqa: E731
    H = F["weekday_kw"]; A = F["households"]
    P = {
        "clean": {"t": "Reading cleaner", "r": "ML", "f": "The aggregator", "d": "Cleans the grid's readings before any plan is made.",
                  "src": [["e", "The loading of every transformer, hour by hour, for 2025."], ["e", "ENGIE's 2023 release, where the true grid state is known. The cleaning is proven on it."]],
                  "viz": [{"y": "stats", "h": "Hours with a transformer at 80% or more, 2025", "rows": [[str(F["hours_at_80_as_read"]), "as the readings come", "e"], [str(F["hours_at_80_cleaned"]), "once cleaned, using past readings only", "e"]]}]},
        "share": {"t": "Sharing-out", "r": "CODE", "f": "The aggregator", "d": "Works out the need by hour and shares it among all 80 participants.",
                  "src": [["e", "Every participant's battery: power, energy, charge and connection limit."], ["e", "How far a transformer's loading falls for each MW given at a site, fitted on the 2023 grid state."],
                          ["o", "The line to stay under: 80% of a transformer's rating."]],
                  "viz": [{"y": "bars", "h": "Battery power in ENGIE's data, MW", "max": 200, "rows": [[f'{F["count"]["pv_bess"]} solar-and-battery plants', F["mw"]["pv_bess"], "e"], [f'{F["count"]["datacenter"]} data centers', F["mw"]["datacenter"], "e"], [f'{F["count"]["community"]} communities', F["mw"]["community"], "e"]]}]},
        "req": {"t": "Request agent", "r": "CODE", "f": "The aggregator", "d": "Sends each participant the sharing-out's figures as a signed request.", "src": [],
                "viz": [{"y": "note", "t": "It holds no data of its own. What it sends is worked out by the sharing-out."}]},
        "ref": {"t": "Referee", "r": "CODE · AI", "f": "The aggregator", "d": "Checks every report row. A small model reads only the words.",
                "src": [["e", "The report layout ENGIE's participants send."], ["e", "ENGIE's own 2025 reports, with the false ones they hold. The referee was built and measured on them."],
                        ["o", "Its settings: every report is held against the meter at 30 minutes and at 2 hours."], ["o", "The false reports planted in our own runs."]],
                "viz": [{"y": "fields", "h": "One report row, every 15 minutes", "rows": [["Net power", "e"], ["Battery charge", "e"], ["A quote", "e"], ["A note in words", "e"]]}]},
        "buy": {"t": "The buyers and their order", "r": "", "f": "The aggregator", "d": "A utility and a grid operator order the cut. In the runs they are stand-ins.",
                "src": [["e", "The window, 18:00 to 21:00: the three dearest hours in ENGIE's prices, in every month of 2025."],
                        ["o", "The price of a cut: $2.04 per kWh, our conversion of a Massachusetts programme's $275 per kW."],
                        ["o", "The size of the order, set so that all that is offered is taken."], ["o", "The pay split: 70% members, 10% the community's operator, 20% the aggregator."]],
                "viz": [{"y": "range", "h": "The price of a cut, $ per kWh", "max": 3.5, "band": [1.53, 3.06, "the range of our conversion"], "marks": [[2.04, "$2.04, used in the runs", "o"]]},
                        {"y": "split", "h": "Who is paid, of each dollar a buyer pays", "rows": [[70, "members", "o"], [10, "the community's operator", "o"], [20, "the aggregator", "o"]]}]},
        "utl": {"t": "The utility", "r": "", "f": "The aggregator", "d": "Sets the most the community may send out at its connection.",
                "src": [["e", f'The community\'s connection limit, {n0(F["host_limit"])} kW.']],
                "viz": [{"y": "stats", "rows": [[n0(F["host_limit"]) + " kW", "the limit at the community's connection", "e"]]}]},
        "host": {"t": "The community's own record", "r": "", "f": "Community", "d": "One of ENGIE's 20 communities is the host. Our homes and buildings sit inside it.",
                 "src": [["e", "Net power at its meter, every 15 minutes of 2025."], ["e", f'Its solar size, {n0(F["host_pv"])} kW, and its temperature, sunlight and prices.'],
                         ["o", "Its solar by day, estimated from ENGIE's 35 metered solar plants (R² 0.92)."],
                         ["o", "The split of its use: our 200 homes 23%, our office 3%, our shops 6%. The other 68% stays as ENGIE recorded it."]],
                 "viz": [{"y": "stack", "h": "An average weekday in the host community, kW by hour", "homes": H["homes"], "bld": [a + b for a, b in zip(H["office"], H["shops"])], "other": H["other"], "win": [18, 21]}]},
        "fc": {"t": "Community forecast", "r": "ML", "f": "Community agent", "d": "What its members will draw and can give tomorrow evening.",
               "src": [["e", "ENGIE's temperature and sunlight."], ["o", "Forecast models trained on our 200 homes."], ["o", "For a building, the last day of the same kind."]], "viz": []},
        "cover": {"t": "Promise and cover", "r": "CODE", "f": "Community agent", "d": "Promises less than its members offered, in case they deliver less.",
                  "src": [["o", "The cover is taken from the community's own record of earlier evenings. Until three are on record it is a fixed 10%."]],
                  "viz": [{"y": "stats", "rows": [["10%", "the fixed cover, until three evenings are on record", "o"]]}]},
        "batt": {"t": "Members' batteries", "r": "", "f": "Community agent", "d": "The homes' own batteries, held for the peak. The community has none of its own.",
                 "src": [["e", "ENGIE's one figure for the community's home batteries, with their reported charge."]],
                 "viz": [{"y": "stats", "rows": [[n0(F["host_kw"]) + " kW", "their power, added up", "e"], [n0(F["host_kwh"]) + " kWh", "their energy, added up", "e"]]}]},
        "clear": {"t": "Clearing, gap filling, report", "r": "CODE", "f": "Community agent", "d": "Clears the offers, fills gaps on the day, and reports upward.",
                  "src": [["e", "The report goes upward in ENGIE's own layout. No member is named in it."], ["o", "Each member's baseline: its ten most recent similar days, adjusted to the day itself."]], "viz": []},
        "town": {"t": "NANDA Town", "r": "", "f": "The network", "d": "MIT's NANDA Town, run locally. It carries signed envelopes and reads nothing inside.", "src": [],
                 "viz": [{"y": "note", "t": "It is software, and holds no data."}]},
        "homes": {"t": "The 200 households", "r": "", "f": "Home agents", "d": "Each home is a physics model with people in it, placed inside ENGIE's community.",
                  "src": [["e", "ENGIE's temperature and sunlight at its site."],
                          ["m", "National Grid load research: the average Massachusetts home, hour by hour. Shape of the day r = 0.92."], ["m", "A measured multi-story instrumented research house dataset, circuit-level heat pump, lighting, and plug loads: one measured house, its solar and its heat pump."],
                          ["m", "Which home owns what: the federal household survey (EIA RECS 2024)."],
                          ["s", f'{F["products"]["home"]} products of {F["brands"]["home"]} brands, each with its maker\'s ratings.'],
                          ["o", "Each house's physics, the household types, the owners' limits and the cars' use."]],
                  "viz": [{"y": "layers", "h": "What one simulated home is made of", "rows": [["e", "Weather", "ENGIE's temperature and sunlight"], ["o", "The house", "One thermal mass, heat loss 0.15 to 0.67 kW per °C"],
                                                                                      ["o", "People", "One of six household types"], ["m", "Appliances", "Owned at the federal survey's rates"],
                                                                                      ["o", "Car", "Sessions with an arrival, a departure and energy owed"], ["m", "Roof solar", "ENGIE's sunlight through one measured roof's conversion"],
                                                                                      ["s", "Battery", "Power, capacity and losses from its datasheet"]]}]},
        "hnotes": {"t": "What people write", "r": "AI", "f": "Home agents", "d": "The small model reads an owner's note and turns it into limits the code must keep.",
                   "src": [["o", "The notes it reads were written by us for the tests, each with its true meaning set down first."]],
                   "viz": [{"y": "stats", "rows": [["151", "labelled notes, 26 of them hostile", "o"]]}]},
        "hguard": {"t": "A home's tools, guard and driver", "r": "CODE", "f": "Home agents", "d": "One road to a device. The guard checks every command, and has the last word.",
                   "src": [["s", "What each device can do, and how a real one is reached: from its product's documents."], ["o", "Each owner's limits: how much warmer the house may get, a car timer, devices that are off limits."]],
                   "viz": [{"y": "stats", "h": "The owners' limits", "rows": [["0.8 to 3.0 °C", "how much warmer a house may get", "o"], ["118", "homes with a car timer", "o"], ["189", "owners with a device off limits", "o"]]}]},
        "hdev": {"t": "Home devices", "r": "HARDWARE", "f": "Home agents", "d": "Battery, car and charger, thermostat, water heater, dryer, dishwasher, pool pump.",
                 "src": [["s", f'{F["products"]["home"]} products of {F["brands"]["home"]} brands in {F["kinds"]["home"]} kinds. Seven battery products, and cars from 19 models.'],
                         ["m", "Which home owns what: the federal household survey (EIA RECS 2024), Massachusetts single-family homes."],
                         ["e", "Roof solar reads ENGIE's sunlight."], ["o", "A two-way car in every home at the full level: an ideal case. 34 of the 200 cars can power a home today."]],
                 "wide": True, "viz": [{"y": "units", "h": "One square is one product", "groups": F["units"]["home"], "cols": 3}]},
        "people": {"t": "The people", "r": "PERSON", "f": "Home agents", "d": "Who is home, what they allow, and when their cars come and go.",
                   "src": [["o", "Six household types, with the holidays and school breaks of 2025."], ["o", "Each owner's limits."], ["o", "When cars leave, return and charge. No public measured home-charging data exists."]],
                   "viz": [{"y": "bars", "h": "The 200 households, by type", "max": 50, "rows": [["Retired", A["retiree"], "o"], ["Commuter", A["commuter"], "o"], ["Hybrid worker", A["hybrid"], "o"], ["Works from home", A["wfh"], "o"],
                                                                                           ["Family", A["family"], "o"], ["Evening shift", A["evening_shift"], "o"]]}]},
        "blds": {"t": "The two buildings", "r": "", "f": "Building agents", "d": "A small office and a strip of shops, each our full building model at 4% of its size.",
                 "src": [["e", "ENGIE's temperature and sunlight, as for the homes."],
                         ["m", "Boston's building energy reports (BERDO 2025): our office matches 56 Boston offices, our shops 8 strip malls and stores."],
                         ["m", "National Grid's business classes: the hourly shape of each building type."], ["m", "Boston Public Library's meter, every 5 minutes: real day-to-day variation, from 380 usable days."],
                         ["s", f'{F["products"]["building"]} products of {F["brands"]["building"]} brands in {F["kinds"]["building"]} kinds.'], ["o", "Who is in each zone, and how the loads split among zones."]],
                 "viz": [{"y": "stats", "h": "The buildings they match", "rows": [["37,000 sq ft", "the middle size of the 56 Boston offices", "m"], ["50,000 sq ft", "the middle size of the 8 strip malls and stores", "m"]]}]},
        "bnotes": {"t": "What the manager writes", "r": "AI", "f": "Building agents", "d": "The small model reads a manager's note and turns it into limits the code must keep.",
                   "src": [["o", "The manager's notes it reads were written by us for the tests."]], "viz": []},
        "bguard": {"t": "A building's tools, guard and driver", "r": "CODE", "f": "Building agents", "d": "One road to a device. The guard keeps the limits of each lever.",
                   "src": [["s", "224 control rules, checked against makers' documents and the mechanical code."]],
                   "viz": [{"y": "rows", "h": "A lever, and the limit the guard keeps", "rows": [["Zone cooling", "At most 1.5 °C warmer while open, 3 °C while closed"], ["Air handler fans", "Never stopped. Free zones slow to half flow"],
                                                                                         ["Lights", "Dim at most 25% in the shops, 50% in the office"], ["Plug loads", "Empty rooms only. Never network or security"]], "k": "s"}]},
        "bdev": {"t": "Building equipment", "r": "HARDWARE", "f": "Building agents", "d": "Cooling, fans, lights and plugs, and the systems that run them.",
                 "src": [["s", f'{F["products"]["building"]} products of {F["brands"]["building"]} brands in {F["kinds"]["building"]} kinds.'],
                         ["o", "How cooling, fans, lights and plugs split among zones: assigned by floor area. No public source gives it."]],
                 "wide": True, "viz": [{"y": "units", "h": "One square is one product", "groups": F["units"]["building"], "cols": 3}]},
        "occ": {"t": "Who is in, and where", "r": "PERSON", "f": "Building agents", "d": "The building's people, zone by zone.",
                "src": [["o", "An occupancy plan by zone, made the day before, and the day as it truly went."]], "viz": []},
        "pv": {"t": "Solar-and-battery plants", "r": "", "f": "Single sites", "d": "Each plant answers the aggregator for itself. Its battery is under a peak contract.",
               "src": [["e", "Net power and battery charge every 15 minutes, with each battery's power and energy and the site's connection limit."],
                       ["o", "Three notes from people at plants, written by us for the test, each with its true meaning set down first."]],
               "viz": [{"y": "stats", "h": "In ENGIE's data", "rows": [[str(F["count"]["pv_bess"]), "solar-and-battery plants", "e"], [f'{F["mw"]["pv_bess"]} MW', "of battery power", "e"], [f'{F["mwh"]["pv_bess"]} MWh', "of battery energy", "e"], [f'{F["pv"]["pv_bess"]} MW', "of solar", "e"]]}]},
        "dc": {"t": "Data centers", "r": "", "f": "Single sites", "d": "Each data center answers for itself. It buys its power as before, and only shifts when it draws.",
               "src": [["e", "Net power and battery charge every 15 minutes, with each battery's power and energy and the site's connection limit."],
                       ["e", "ENGIE's 2023 release: 16.3% of the data centers' energy can wait, for 4.5 to 10.5 hours."], ["o", "Its carry-over to the same sites' 2025 load."]],
               "viz": [{"y": "stats", "h": "In ENGIE's data", "rows": [[str(F["count"]["datacenter"]), "data centers", "e"], [f'{F["mw"]["datacenter"]} MW', "of battery power", "e"], [f'{F["mwh"]["datacenter"]} MWh', "of battery energy", "e"], ["16.3%", "of their energy can wait", "e"]]}]},
        "ret": {"t": "Readings, settlement, payment", "r": "", "f": "Return path", "d": "Signed readings come back, buyers settle on the meters, and pay follows delivery.",
                "src": [["o", "The meters are the simulated devices' own. A twin of each home and building with no sale gives the truth."], ["o", "Pay follows delivery against the baseline, at the price of a cut."]],
                "viz": [{"y": "split", "h": "Who is paid, of each dollar a buyer pays", "rows": [[70, "members", "o"], [10, "the community's operator", "o"], [20, "the aggregator", "o"]]}]},
    }
    order = ["clean", "share", "req", "ref", "buy", "utl", "host", "fc", "cover", "batt", "clear", "town", "homes", "hnotes", "hguard", "hdev", "people", "blds", "bnotes", "bguard", "bdev", "occ", "pv", "dc", "ret"]
    for p in P.values():                                    # the kinds a panel shows are the kinds of its own sources
        p["k"] = "".join(k for k in "esmo" if any(s[0] == k for s in p["src"]))
    heads = {"e": f'Its 2025 records, unchanged: {sum(F["count"].values())} participants every 15 minutes, and a 200-bus grid read every hour.',
             "s": f'{F["products_all"]} current US products of {F["brands_all"]} brands, each with its maker\'s ratings.',
             "m": "Public records: National Grid load research, a measured multi-story instrumented research house dataset, circuit-level heat pump, lighting, and plug loads, the federal household survey, Boston's building reports, a measured library, measured weather.",
             "o": "Set by us where no record exists: household types, owners' limits, car use, the community's solar by day, the price of a cut."}
    return {"kinds": {k: {"tag": v[0], "name": v[1], "what": v[2], "head": heads[k]} for k, v in KINDS.items()},
            "box": {b: {"k": v[0], "p": v[1]} for b, v in BOX.items()}, "panels": P, "order": order}
