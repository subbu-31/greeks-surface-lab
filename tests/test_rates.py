"""Checks rf_rate() against the RBI/PIB press-release dates it's sourced
from, rather than trusting the schedule by inspection -- the exact same
regression test as the sibling repo this schedule was ported from, since
a schedule that silently drifts from its cited sources is the same
staleness bug wearing a disguise.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bs_solver import rf_rate

CASES = [
    ("2024-06-01", 0.065, "pre-cut, RBI held 6.50% from Feb 2023"),
    ("2025-02-06", 0.065, "day before the first 2025 cut"),
    ("2025-02-07", 0.0625, "RBI MPC, 25bp cut to 6.25%"),
    ("2025-04-08", 0.0625, "day before the April cut"),
    ("2025-04-09", 0.060, "RBI/PIB: 25bp cut to 6.00%, 'with immediate effect'"),
    ("2025-06-05", 0.060, "day before the June cut"),
    ("2025-06-06", 0.055, "RBI MPC (June 4-6 meeting), 50bp cut to 5.50%"),
    ("2025-12-04", 0.055, "day before the December cut"),
    ("2025-12-05", 0.0525, "RBI MPC (Dec 3-5 meeting), 25bp cut to 5.25%"),
    ("2026-02-06", 0.0525, "RBI MPC held steady -- confirms no cut in between"),
    ("2026-04-08", 0.0525, "RBI MPC held steady -- confirms no cut through the sample's end"),
]


def test_rf_rate_matches_every_documented_rbi_decision():
    for d, expected, source in CASES:
        got = rf_rate(d)
        assert abs(got - expected) < 1e-9, f"{d} ({source}): expected {expected}, got {got}"


def test_rf_rate_accepts_date_datetime_and_iso_string_equally():
    from datetime import date, datetime
    assert rf_rate("2025-06-06") == rf_rate(date(2025, 6, 6)) == rf_rate(datetime(2025, 6, 6, 9, 45))


def test_rf_rate_default_is_the_latest_known_rate_not_the_oldest():
    """A date-aware function defaulting to the oldest, most stale rate on a
    missing date would just reproduce the bug it was built to fix."""
    assert rf_rate() == 0.0525
    assert rf_rate(None) == 0.0525


if __name__ == "__main__":
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\n{len(tests)} tests passed")
