"""What the parts of a node host share: the telemetry keys, the waits before a batch of readings goes again, and who an alarm holds."""
from __future__ import annotations

import logging
import resource
import sys
from typing import Any
from murmur.node.home import MemberNode


log = logging.getLogger("murmur-host")


TEXT_MAX = 400                 # the longest text an override may carry: what the community agent keeps of a node's own words


UNREAD = "the node's alarm file can't be read"


TEL_KEYS = ("pv_kw", "load_kw", "batt_kw", "ev_kw", "grid_kw", "grid_cf_kw", "soc_pct", "soc_cf_pct", "mode", "ev_held", "ev_plugged", "ev_need_kwh",
            "ev_deadline", "price_usd_mwh", "ts", "control", "owed_kw", "rt_extra_kw", "t_dev_c", "t_in_c", "cool_kw", "override")


def node_class(cfg: dict[str, Any]) -> type:
    """Which node class speaks for a member, by cfg buyers and report_rule: MemberNode, or report_rule.py's PoolNode or QuietNode."""
    if not cfg.get("buyers") and cfg.get("report_rule") != "exception":
        return MemberNode
    from murmur.node.report_rule import PoolNode, QuietNode
    return QuietNode if cfg.get("report_rule") == "exception" else PoolNode


def held(f: Any) -> dict[str, Any]:
    """The nodes an alarm holds, and what it said. Each node's own dict is copied once, so a word that ends one while this runs can't trip it."""
    out = {}
    for n, h in list(f.homes.items()):
        for _ in range(5):
            try:
                ov = dict(getattr(h.adapter, "overrides", None) or {})
                break
            except RuntimeError:                          # the dict changed while it was copied: once more
                ov = {}
        if "alarm_hold" in ov:
            out[n] = ov["alarm_hold"]
    return out


def memory_mb() -> dict[str, float]:
    """This process now and at its most, for /health: the numbers a start on a small machine watches."""
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1048576 if sys.platform == "darwin" else 1024)
    now = 0.0
    try:
        with open("/proc/self/statm") as f:
            now = int(f.read().split()[1]) * resource.getpagesize() / 1048576
    except OSError:
        try:
            import psutil
            now = psutil.Process().memory_info().rss / 1048576
        except ImportError:
            pass
    return {"now_mb": round(now, 1), "peak_mb": round(peak, 1)}
