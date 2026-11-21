"""The year's evenings with the community agent and without it, counted the same way from each run's own rows.

Without the community agent the market promises everything the members offer. With it, the community promises what its own record says it
can keep. For each weather, tier and case, over the 48 evenings:

  promised_kw, delivered_by_the_truth_kw, delivered_by_the_meter_kw   evening means (kW over 18:00 to 21:00), averaged over the evenings
  evenings_kept_by_the_truth, evenings_kept_by_the_meter              evenings on which the delivery is at least the promise
  half_hours_short_by_the_truth (of half_hours)                       half hours in which the truth falls below the promise
  mean_miss_by_the_truth_pct                                          the true shortfall: an evening's shortfall as a share of its promise
                                                                      (none where the truth meets it), averaged over the evenings
  worst_evening_by_the_truth_pct                                      the largest of those shortfalls
  buyers_pay_usd, members_get_usd                                     an evening's money, averaged
"""
from __future__ import annotations

import gzip
import json
from pathlib import Path

import numpy as np

RECORDING = Path(__file__).resolve().parent / "evening_runs.json.gz"


def load(path: Path = RECORDING) -> dict:
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        return json.load(fh)


def counts(runs: list[dict]) -> dict:
    """The measures of one weather, tier and case over its evenings."""
    P = [np.asarray(r["promised_kw"], float) for r in runs]
    T = [np.asarray(r["true_kw"], float) for r in runs]
    pk, tk, mk = np.array([p.mean() for p in P]), np.array([t.mean() for t in T]), np.array([np.mean(r["metered_kw"]) for r in runs])
    miss = np.minimum((tk - pk) / pk, 0) * 100
    return {"evenings": len(runs), "promised_kw": round(pk.mean(), 1), "delivered_by_the_meter_kw": round(mk.mean(), 1),
            "delivered_by_the_truth_kw": round(tk.mean(), 1), "evenings_kept_by_the_meter": int((mk >= pk).sum()),
            "evenings_kept_by_the_truth": int((tk >= pk).sum()), "half_hours_short_by_the_truth": int(sum((t < p).sum() for p, t in zip(P, T))),
            "half_hours": int(sum(len(t) for t in T)), "mean_miss_by_the_truth_pct": round(miss.mean(), 1),
            "worst_evening_by_the_truth_pct": round(miss.min(), 1), "buyers_pay_usd": round(np.mean([r["buyers_pay_usd"] for r in runs])),
            "members_get_usd": round(np.mean([r["members_paid_usd"] for r in runs]))}


def table(rec: dict) -> dict[str, dict]:
    """Every weather, tier and case: '<weather>_t<tier>_with' and '_without'."""
    groups: dict[tuple, list[dict]] = {}
    for r in rec["runs"]:
        groups.setdefault((r["weather"], r["tier"], r["community_agent"]), []).append(r)
    return {f"{w}_t{t}_{'with' if on else 'without'}": {k: (float(v) if isinstance(v, np.floating) else int(v) if isinstance(v, np.integer) else v)
                                                         for k, v in counts(sorted(rs, key=lambda r: r["evening"])).items()}
            for (w, t, on), rs in sorted(groups.items(), key=lambda kv: (kv[0][0], kv[0][1], not kv[0][2]))}


def headline(tab: dict[str, dict], weather: str = "engie", tier: int = 1) -> str:
    a, b = tab[f"{weather}_t{tier}_with"], tab[f"{weather}_t{tier}_without"]
    return (f"over {a['evenings']} evenings (tier {tier}, {weather} weather) the true shortfall is {-a['mean_miss_by_the_truth_pct']:.1f}% with the "
            f"community agent and {-b['mean_miss_by_the_truth_pct']:.1f}% without it; truly kept {a['evenings_kept_by_the_truth']} and "
            f"{b['evenings_kept_by_the_truth']} evenings; delivered by the truth {a['delivered_by_the_truth_kw']:,.1f} and {b['delivered_by_the_truth_kw']:,.1f} kW; "
            f"members paid ${a['members_get_usd']:,} and ${b['members_get_usd']:,} an evening")
