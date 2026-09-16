"""Date-aware risk-free rate, sourced to RBI/PIB press releases.

Ported from a sibling research pipeline where this exact schedule was built
after finding a flat `RF = 0.065` constant had been used, unchecked, in
every Sharpe/Sortino calculation across seven files spanning a multi-year
sample that actually saw five different rate regimes. `black_scholes.RF`
has the same flat-constant shape for backward-compatible callers that never
pass a date; this module exists so a *new* caller (e.g. a script building a
snapshot for a fresh date) doesn't have to re-derive or eyeball the correct
rate by hand, which is exactly how the original bug happened.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional, Union

DateLike = Union[str, date, datetime]

# RBI policy repo rate, verified against RBI/PIB press releases (not assumed):
#   to 2025-02-06   6.50%
#   2025-02-07      6.25%  (MPC, 25bp cut)
#   2025-04-09      6.00%  (MPC, 25bp cut, "with immediate effect")
#   2025-06-06      5.50%  (MPC, 50bp cut)
#   2025-12-05      5.25%  (MPC, 25bp cut)
# Confirmed unchanged at the 2026-02-06 and 2026-04-08 MPC meetings.
_RF_SCHEDULE: list[tuple[Optional[str], float]] = [
    ("2025-02-07", 0.065), ("2025-04-09", 0.0625),
    ("2025-06-06", 0.060), ("2025-12-05", 0.055), (None, 0.0525),
]


def _as_date(d: DateLike) -> date:
    if isinstance(d, str):
        return date.fromisoformat(d)
    if isinstance(d, datetime):
        return d.date()
    return d


def rf_rate(on: Optional[DateLike] = None) -> float:
    """Date-aware risk-free rate. `on` is a date, datetime, or ISO date
    string; None returns the most recent known rate (5.25%) -- a
    date-aware function that fell back to the *oldest* rate on a missing
    date would just be a slower way to reproduce the staleness bug it
    exists to fix. Every real caller in this repo passes an explicit date;
    this fallback only matters if a future one doesn't.

    Each schedule entry is the rate in force strictly before its cutoff
    date -- e.g. rf_rate("2025-02-06") is 0.065, rf_rate("2025-02-07") is
    already 0.0625.
    """
    if on is None:
        return _RF_SCHEDULE[-1][1]
    d = _as_date(on)
    for cutoff, rate in _RF_SCHEDULE:
        if cutoff is None or d < date.fromisoformat(cutoff):
            return rate
    return _RF_SCHEDULE[-1][1]
