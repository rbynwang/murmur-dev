"""The reading cleaner: each hour rebuilt from the few patterns the transformer readings share.

The 66 readings of one hour are not independent: a few things the whole grid shares (the load, the plants' output) drive them. So an hour is
rebuilt from the k patterns the sensors share, and what one sensor says alone is treated as its noise. A reading further from its rebuilt value
than four times that sensor's usual error is a glitch: it is set aside and rebuilt from the others, and so is a missing reading.

Two forms:
  clean      learns the patterns from the whole table at once
  past_only  cleans each hour with patterns learned only from readings that came before it, as a cleaner running live must
"""
from __future__ import annotations

import numpy as np

FIRST, WARM, EVERY = 3, 28, 7      # past_only: older patterns for the first days, then learned again daily, then every seven days


def clean(X: np.ndarray, k: int, rounds: int = 3, sweeps: int = 8) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Rebuild each row of X (hours x sensors, NaN where missing) from the k patterns the sensors share.

    Returns the rebuilt table, the glitches found, and each sensor's usual error (a robust spread of what it says alone)."""
    X = X.copy()
    miss = np.isnan(X)
    bad = np.zeros_like(miss)
    mu = np.nanmean(X, axis=0)
    for _ in range(rounds):
        hole = miss | bad
        Z = np.where(hole, mu, X)
        for _ in range(sweeps):
            m = Z.mean(axis=0)
            U, S, Vt = np.linalg.svd(Z - m, full_matrices=False)
            Rb = (U[:, :k] * S[:k]) @ Vt[:k] + m
            Z = np.where(hole, Rb, X)
        res = np.where(hole, np.nan, X - Rb)
        sd = 1.4826 * np.nanmedian(np.abs(res - np.nanmedian(res, axis=0)), axis=0)
        bad = bad | (np.abs(np.nan_to_num(X - Rb)) > 4 * np.maximum(sd, .5)) & ~miss
    return Rb, bad, sd


def patterns(X: np.ndarray, k: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """What a stretch of readings shows: each sensor's usual level, the k shared patterns, each sensor's usual error."""
    Rb, bad, sd = clean(X, k)
    Z = np.where(np.isnan(X) | bad, Rb, X)
    m = Z.mean(axis=0)
    _, _, Vt = np.linalg.svd(Z - m, full_matrices=False)
    return m, Vt[:k], np.maximum(sd, .5)


def one_hour(x: np.ndarray, m: np.ndarray, V: np.ndarray, sd: np.ndarray, rounds: int = 3) -> tuple[np.ndarray, np.ndarray]:
    """One hour's readings fitted to known patterns; a reading further than four usual errors from its fit is set aside and the hour fitted again."""
    ok = np.isfinite(x)
    flagged = np.zeros(len(x), dtype=bool)
    for _ in range(rounds):
        if ok.sum() <= len(V):
            return m.copy(), flagged
        c = np.linalg.lstsq(V[:, ok].T, (x - m)[ok], rcond=None)[0]
        rb = m + c @ V
        new = np.isfinite(x) & (np.abs(np.nan_to_num(x - rb)) <= 4 * sd)
        flagged = np.isfinite(x) & ~new
        if (new == ok).all():
            break
        ok = new
    return rb, flagged


def past_only(X: np.ndarray, steps_per_day: int, k: int, older: tuple | None = None) -> tuple[np.ndarray, np.ndarray]:
    """Clean X (time x sensors) so that each step uses only what came before it.

    older: (level, patterns, error) from older readings of the same grid, used for the first FIRST days. From then on the patterns come from this
    series' own past: learned again every day for the first WARM days, while a few more days still change them, then every EVERY days."""
    out = np.empty_like(X)
    bad = np.zeros(X.shape, dtype=bool)
    n, a = len(X), 0
    while a < n:
        day = a // steps_per_day
        block = (FIRST if day < FIRST else 1 if day < WARM else EVERY) * steps_per_day
        if day < FIRST:
            P = older if older is not None else patterns(X[:FIRST * steps_per_day], k)
        else:
            P = patterns(X[:a], k)
        for t in range(a, min(a + block, n)):
            out[t], bad[t] = one_hour(X[t], *P)
        a += block
    return out, bad
