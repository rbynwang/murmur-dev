"""A synthetic community's dataset, in the file forms an evening reads: homes, one small office building, their devices, the
price book, the buyers' catalog, and two single sites (a solar-and-battery plant and a data center).

Three homes (two with a car, all with a battery) and one office over any run of days at 15-minute steps. Every number comes from
a generator seeded with SEED and the gzip files carry no timestamp, so the same days give the same bytes on every machine. The
test fixtures (tests/fixtures/make_fixtures.py) are its two-day form; the demo's example evening (example.py) a longer one.
"""
from __future__ import annotations

import csv
import gzip
import io
import json
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

SEED = 20250127
HOMES = {"home-01": ("HH001", True, 13.5, 5.0), "home-02": ("HH002", False, 10.0, 5.0), "home-03": ("HH003", True, 9.8, 7.08)}      # record ids the package's tool shelves know
BUILDING = "building-01"
OFFICE_ZONES = ("Floors 1-3", "Floors 4-6", "Floors 7-8", "Vacant floors")
PLACE = {"name": "Test community", "lat": 42.36, "lon": -71.06}
SITES = (("site-pv-01", "pv_bess", 900.0), ("site-dc-01", "datacenter", 400.0))
COUNT = {2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven", 8: "eight", 9: "nine", 10: "ten"}


_PAYLOADS = (("CAPACITY_REQUESTED", "KW", 400.0), ("PRICE", "USD_PER_KWH", 2.04), ("SHORTFALL_PENALTY", "USD_PER_KWH", 0.0))
BUYER = "utility-or-engie-mock"                     # the stand-in buyers' name in their contracts (demo/runner/buyers/utility.py PARTICIPANT)
FORM_NEED = {"id": "flex-need-form-only", "descriptor": {"name": "Form only", "shortDesc": "the form of an order; never played"},
             "quantity": {"unitCode": "kW", "unitQuantity": 400.0, "@type": "Quantity"},
             "resourceAttributes": {"@context": "https://schema.nfh.global/DemandFlexNeed/v2.0/context.jsonld", "@type": "DemandFlexNeed",
                                    "location": {"geo": {"type": "Point", "coordinates": [PLACE["lon"], PLACE["lat"]]}},
                                    "intervalPeriod": {"start": "2024-12-26T00:00:00Z", "duration": "PT30M"},
                                    "payloadDescriptors": [{"objectType": "EVENT_PAYLOAD_DESCRIPTOR", "payloadType": t, "units": u, "insertedBy": "buyer"}
                                                           for t, u, _ in _PAYLOADS],
                                    "intervals": [{"id": k, "payloads": [{"type": t, "values": [v]} for t, _, v in _PAYLOADS]} for k in range(6)]}}
FORM_OFFER = {"id": "offer-form-only", "descriptor": {"name": "Form only", "shortDesc": "the form of an order; never played"},
              "resourceIds": [FORM_NEED["id"]], "validity": {"endDate": "2024-12-31T22:00:00Z"},
              "offerAttributes": {"@context": "https://schema.nfh.global/DemandFlexBuyOffer/v2.0/context.jsonld", "@type": "DemandFlexBuyOffer",
                                  "contractAttributes": {"@context": "https://schema.nfh.global/DEGContract/v2.0/context.jsonld", "@type": "DEGContract",
                                                         "roles": [{"role": "buyer", "participantId": BUYER}, {"role": "seller", "participantId": None}],
                                                         "policy": {"url": "https://raw.githubusercontent.com/beckn/DEG/refs/heads/main/specification/policies/demand-flex-contractpolicy.rego",
                                                                    "queryPath": "data.deg.contracts.demand_flex"}},
                                  "inputs": [{"role": "buyer", "participantId": BUYER, "inputs": {"currency": "USD", "baselineMethodology": {"bestOf": 3, "outOf": 14}}},
                                             {"role": "seller", "participantId": None}]}}


def days_from(first: str, n: int) -> tuple[str, ...]:
    d0 = datetime.strptime(first, "%Y-%m-%d")
    return tuple((d0 + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(n))


def hour_of(ts: str) -> float:
    return int(ts[11:13]) + int(ts[14:16]) / 60


def write_gz_csv(path: Path, header: list[str], rows: list[list]) -> None:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(header)
    w.writerows(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f, gzip.GzipFile(fileobj=f, mode="wb", mtime=0, filename="") as g:
        g.write(buf.getvalue().encode())


def write_csv(path: Path, header: list[str], rows: list[list]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(header)
        w.writerows(rows)


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=1, sort_keys=True) + "\n")


class Community:
    """The synthetic community over `days` (the evening is on `event`, the last day but one by default)."""

    def __init__(self, days: tuple[str, ...], event: str | None = None):
        self.days, self.event = days, event or days[-1]
        self.steps = [f"{d} {h:02d}:{m:02d}" for d in days for h in range(24) for m in (0, 15, 30, 45)]
        self.rng = np.random.default_rng(SEED)

    def weather(self) -> list[dict[str, float]]:
        out = []
        for ts in self.steps:
            h = hour_of(ts)
            sun = max(0.0, np.sin(np.pi * (h - 7.5) / 9.0)) if 7.5 <= h <= 16.5 else 0.0
            temp = -4.0 + 4.0 * np.sin(np.pi * (h - 9.0) / 12.0) + self.rng.normal(0, 0.3)
            price = 42.0 + (110.0 if 17 <= h < 21 else 0.0) + self.rng.normal(0, 3.0)
            out.append({"sun": sun, "temp": round(temp, 2), "fc_temp": round(temp + self.rng.normal(0, 0.8), 2), "ghi": round(520 * sun, 1),
                        "price": round(price, 2), "price_da": round(price * 0.9 + 5, 2)})
        return out

    def home_rows(self, w: list[dict[str, float]], pv_scale: float, evening_kw: float) -> list[list]:
        rows = []
        for ts, x in zip(self.steps, w):
            h = hour_of(ts)
            base = 0.35 + (evening_kw if 17 <= h < 22 else 0.0) + (0.6 if 6.5 <= h < 8.5 else 0.0) + abs(self.rng.normal(0, 0.08))
            rows.append([ts, round(pv_scale * x["sun"], 3), round(base, 3), x["price"], x["price_da"], x["ghi"], x["temp"], x["fc_temp"], 20.0,
                         round(0.9 * x["ghi"], 1), 0.0])
        return rows

    def building_rows(self, w: list[dict[str, float]]) -> tuple[list[list], list[list]]:
        load, hvac = [], []
        for ts, x in zip(self.steps, w):
            h = hour_of(ts)
            open_ = 7 <= h < 19
            base = (42.0 if open_ else 18.0) + abs(self.rng.normal(0, 1.0))
            load.append([ts, 0.0, round(base, 2), x["price"], x["price_da"], x["ghi"], x["temp"], x["fc_temp"], 20.0, round(0.9 * x["ghi"], 1), -1.8])
            hvac.append([ts, 0.0, 1.9, 22.8 if open_ else 21.0, int(open_), -1, 8.4 if open_ else 5.3])
        return load, hvac

    def sessions(self) -> list[list]:
        """A car's charging sessions: overnight after each evening but the last, and a short one on the last evening."""
        d = self.days
        nights = [[f"{a} 18:30", f"{b} 07:00", 14.0, 7.2, f"{a} 17:45"] for a, b in zip(d, d[1:])]
        return nights + [[f"{d[-1]} 18:15", f"{d[-1]} 23:45", 9.5, 7.2, f"{d[-1]} 17:30"]]

    def write(self, data: Path, sites_file: Path) -> int:
        """Writes the dataset into `data` and the single sites into `sites_file`; the number of files in `data`."""
        days, steps, rng = self.days, self.steps, self.rng
        w = self.weather()
        fleet, owners, hvac_params, rows = [], {}, {}, {"home": {}, "building": {BUILDING: 0}}
        for i, (name, (rec, has_ev, kwh, kw)) in enumerate(HOMES.items()):
            write_gz_csv(data / f"homes/{rec}.csv.gz", ["ts_local", "pv_kw", "base_kw", "price_usd_mwh", "price_da_usd_mwh", "ghi_wm2", "temp_c", "fc_temp_c",
                                                        "fc_cloud_pct", "fc_sw_wm2", "dkw_dT"], self.home_rows(w, 3.0 + i, 1.2 + 0.4 * i))
            write_csv(data / f"homes/{rec}_ev.csv", ["arrival_local", "deadline_local", "kwh", "max_kw", "plug_in_local"], self.sessions() if has_ev else [])
            write_gz_csv(data / f"homes/{rec}_hvac.csv.gz", ["ts_local", "cool_kw", "cop", "t_in_c", "occ", "mode"],
                         [[ts, 0.0, 2.1, 21.5, int(not (i == 1 and 9 <= hour_of(ts) < 17)), -1] for ts in steps])
            fleet.append({"name": name, "host": "offline", "county_id": "C01", "county": "Test county", "profile": f"homes/{rec}", "has_ev": has_ev,
                          "battery": {"kwh": kwh, "kw": kw, "eta": 0.95, "reserve_pct": 20.0, "soc_max_pct": 100.0, "soc0_pct": 60.0, "source": "synthetic"},
                          "export_limit_kw": kw, "kind": "replay", "synthetic_home": f"T-{rec}", "heating_type": "gas_furnace", "pv_kw_dc": 3.0 + i,
                          "pv_scale_kw": 3.0 + i, "n_ev": int(has_ev), "lat": PLACE["lat"], "lon": PLACE["lon"], "forecast_place": "test", "tier": 1})
            owners[name] = {"max_rise_c": 1.5, "max_rise_away_c": 2.5, "precool_c": 0.5, "respond": 1.0, "online": 1.0, "charge_kw": 7.2, "v2h_kwh": 10.0}
            hvac_params[name] = {"synthetic_home": f"T-{rec}", "ua_kw_per_c": 0.45, "cap_kwh_per_c": 8.0, "tau_h": 17.8, "cool_cap_kw": 8.0,
                                 "cooling_type": "window_ac", "heat_pump": False, "window_fraction": 0.5, "setpoint_summer_c": 24.0, "comfort_band_c": 1.5}
            rows["home"][name] = i
        write_json(data / "fleet_v2.json", {"version": "fixture", "n_homes": len(fleet), "homes_per_county": len(fleet),
                                            "counties": [{"county_id": "C01", "county": "Test county", "households": len(fleet), "lat": PLACE["lat"],
                                                          "lon": PLACE["lon"], "bus": 1}], "homes": fleet})
        write_json(data / "owners.json", {"tier": 1, "homes": owners})
        write_json(data / "hvac_params.json", {"source": "synthetic", "homes": hvac_params})
        self.write_building(data, w, rows)
        write_json(data / "grid_events.json", {"context": {"networkId": "murmur.local/demo-deg", "version": "2.0.0", "action": "catalog/publish",
                                                           "bppId": "utility.murmur.local", "transactionId": "fixture", "messageId": "fixture",
                                                           "timestamp": "2025-01-01T00:00:00Z"},
                                               "message": {"catalogs": [{"id": "catalog-fixture", "descriptor": {"name": "Test buyer stand-in"},
                                                                         "provider": {"id": "utility", "descriptor": {"name": "Utility (stand-in)"}},
                                                                         "resources": [FORM_NEED], "offers": [FORM_OFFER]}]}})
        write_json(data / "dataset.json", {"name": "fixture", "label": f"Synthetic test community: three homes and one office over {COUNT.get(len(days), len(days))} days",
                                           "tz_offset_h": -5, "tz_label": "local", "range": [days[0], days[-1]], "baseline_from": days[0],
                                           "replay_start": f"{days[0]} 00:00", "events_file": "grid_events.json", "default_event": self.event, "holidays": [],
                                           "agent_defaults": {"clock_profile": "homes/HH001", "profile": "homes/HH001"}, "profile_alias": {},
                                           "community": PLACE, "models": "models/forecast", "models_2026": "models/forecast"})
        write_json(sites_file, {"date": self.event, "sites": self.sites(w)})
        return len(list(data.rglob("*")))

    def write_building(self, data: Path, w: list[dict[str, float]], rows: dict) -> None:
        days, steps = self.days, self.steps
        load, hvac = self.building_rows(w)
        write_gz_csv(data / "buildings/office.csv.gz", ["ts_local", "pv_kw", "base_kw", "price_usd_mwh", "price_da_usd_mwh", "ghi_wm2", "temp_c", "fc_temp_c",
                                                        "fc_cloud_pct", "fc_sw_wm2", "dkw_dT"], load)
        write_gz_csv(data / "buildings/office_hvac.csv.gz", ["ts_local", "cool_kw", "cop", "t_in_c", "occ", "mode", "light_kw"], hvac)
        write_csv(data / "buildings/office_ev.csv", ["arrival_local", "deadline_local", "kwh", "max_kw"], [])
        battery0 = {"kwh": 0.0, "kw": 0.0, "eta": 0.95, "reserve_pct": 0.0, "soc_max_pct": 100.0, "soc0_pct": 0.0, "source": "none"}
        office = {"name": BUILDING, "kind": "building", "label": "Small office (synthetic)", "short": "Small office", "profile": "buildings/office", "place": PLACE,
                  "floor_area_sqft": 30400, "cooled_share": 1,
                  "thermal": {"ua_kw_per_c": 3.3, "cap_kwh_per_c": 31.3, "tau_h": 9.5, "cool_cap_kw": 117.7, "cool_kw_per_c": 0.75, "cooling_type": "plant",
                              "keeps_cold": True, "how": "synthetic"},
                  "lighting": {"open_kw": 8.4, "closed_kw": 5.3, "dim_max_share": 0.5}, "schedule": {"t_in_open_c": 22.8, "t_in_closed_c": 25.0},
                  "battery": battery0, "sell": {"fans": 0.5, "plugs": 0.2}, "free": 0.85,
                  "limits": {"max_rise_c": 1.5, "max_rise_away_c": 2.775, "precool_c": 1.0, "light_dim_max": 0.5}}
        write_json(data / "buildings/office.json", office)
        write_json(data / "buildings.json", {"buildings": [{**{k: office[k] for k in ("name", "kind", "label", "short", "profile", "place", "floor_area_sqft", "battery")},
                                                            "has_ev": False, "export_limit_kw": 0.0, "host": "offline", "params": "buildings/office.json"}]})
        plan = np.zeros((len(OFFICE_ZONES), len(days), 24), dtype=np.float32)
        for z in range(len(OFFICE_ZONES)):
            plan[z, :, 7:19] = 0.0 if OFFICE_ZONES[z] == "Vacant floors" else 0.8
        (data / "buildings").mkdir(parents=True, exist_ok=True)
        with open(data / "buildings/schedules.npz", "wb") as f:
            np.savez(f, keys=np.array([f"office/{z}" for z in OFFICE_ZONES]), days=np.array(days), plan=plan, true=plan)
        devices = {"home": {"hpwh": {"label": "Heat pump water heater", "kind": "shift", "kw": 1.7, "share": 1.0, "order": 1, "path": "the maker's app"},
                            "dryer": {"label": "Clothes dryer", "kind": "shift", "kw": 5.6, "share": 1.0, "order": 3, "path": "the maker's cloud"},
                            "v2h": {"label": "Car, two-way charger", "kind": "source", "kw": 9.6, "share": 1.0, "event_kwh": 10.0, "eff": 0.9, "path": "the maker's cloud"}},
                   "building": {"fans": {"label": "Fans", "kind": "shed", "kw": 0.0, "share": 1.0, "path": "the building system"},
                                "plugs": {"label": "Plug loads", "kind": "shed", "kw": 0.0, "share": 1.0, "path": "plug relays"}}}
        write_json(data / "devices/catalog.json", {"devices": devices, "rows": rows, "stagger_max_min": 120, "catch_up_after_min": 90})
        evening = np.array([1.0 if 18 <= hour_of(ts) < 21 else 0.0 for ts in steps], dtype=np.float32)
        for dev, kw in (("hpwh", 1.7), ("dryer", 5.6), ("v2h", 9.6)):
            np.save(data / f"devices/home_{dev}.npy", np.vstack([evening * kw * (1.0 if (i + len(dev)) % 2 == 0 or dev == "hpwh" else 0.0) for i in range(len(HOMES))]))
        for dev, kw in (("fans", 6.0), ("plugs", 3.0)):
            np.save(data / f"devices/building_{dev}.npy", np.vstack([np.array([kw if 7 <= hour_of(ts) < 19 else 0.0 for ts in steps], dtype=np.float32)]))
        write_json(data / "devices/price_book.json", {"as_of": "2025-01-01", "note": "synthetic price book for tests", "coordinator_keeps": 0.3,
                                                      "same_day_adjustment": True, "x": {"home_battery": 0.7, "building": 0.5075, "home_other": 0.18375},
                                                      "kept_split": {"community_operator": 0.1, "aggregator": 0.2}})

    def sites(self, w: list[dict[str, float]]) -> dict:
        out = {}
        for name, kind, rating in SITES:
            feed = {ts: {"base_kw": round(-300.0 + 600 * x["sun"] if kind == "pv_bess" else -800.0, 3), "recorded_kw": 0.0, "own_kwh": 0.0, "share": 0.0,
                         "price_usd_kwh": round(x["price"] / 1000, 5), "store_before_kwh": round(0.5 * rating * 2, 3)} for ts, x in zip(self.steps, w)}
            req = {"id": f"req-{name}-{self.event}", "to": name, "made_at": f"{self.event} 14:00",
                   "rows": [{"ts": ts, "battery_kw": round(0.6 * rating, 1) if "18:00" <= ts[11:] < "21:00" else 0.0, "price_usd_kwh": round(x["price"] / 1000, 5)}
                            for ts, x in zip(self.steps, w) if ts[:10] == self.event and ts[11:] >= "14:00"]}
            out[name] = {"site": {"id": name.upper().replace("-", "_"), "kind": kind, "rating_kw": rating, "energy_kwh": rating * 2, "out_factor": 0.9,
                                  "limit_out_kw": rating * 1.5, "wait_h": 0.0}, "feed": feed, "requests": [req]}
        return out
