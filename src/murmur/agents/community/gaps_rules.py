"""The real-time desk's small rules: what a real number is, and how many steps lie between two times."""
from __future__ import annotations

import math
from typing import Any
from murmur.protocol import envelope as beckn


MARGIN = 0.10                # asks the homes for this much more than it confirms (as the day-ahead clearing does)


PRICE_LADDER = (1.0, 1.25, 1.5)   # a gap the first round cannot fill is offered again at these multiples


ASK_COVER = 1.5              # the quiet path asks members whose known room covers a gap this many times


ASK_WAVE = 32                # a call asks this many members first, and twice as many each time it's still short. An ask and its answer are 1.3 kB and Town takes
                             # about 5 kB/s: this wave is 9 s of it, all 203 members a minute, and the three buildings at the top of the list hold nine tenths of what the answers offer


WARN_AGAIN_SHARE = 0.25      # the quiet path warns a buyer again only when the shortfall changes by this share


MIN_GAP_SHARE = 0.005        # the quiet path moves no gap under this share of what's sold: it costs more messages than it's worth


QUIET_CUSHION = 0.5          # the quiet path counts on this part of the margin, because small shortfalls go unreported and spend the rest


def real(v: Any) -> float | None:
    """A real number, or None. NaN and infinity count as no number."""
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def steps_between(start: str, end: str) -> list[str]:
    out, t = [], start
    while t < end:
        out.append(t)
        t = beckn.add_minutes(t, 15)
    return out
