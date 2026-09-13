"""Sanity checks for bs_solver -- not a full options-pricing test suite,
just enough to catch a transcription error in the extraction."""
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bs_solver import price, implied_vol, delta, gamma, vega, theta, years_to_expiry

S, K, T, SIGMA, R = 100.0, 100.0, 0.5, 0.20, 0.05


def test_put_call_parity():
    c = price(S, K, T, SIGMA, "CE", R)
    p = price(S, K, T, SIGMA, "PE", R)
    lhs = c - p
    rhs = S - K * math.exp(-R * T)
    assert abs(lhs - rhs) < 1e-9


def test_price_at_expiry_is_intrinsic():
    assert price(110, 100, 0, 0.2, "CE") == 10.0
    assert price(90, 100, 0, 0.2, "CE") == 0.0
    assert price(90, 100, 0, 0.2, "PE") == 10.0


def test_implied_vol_round_trip():
    px = price(S, K, T, SIGMA, "CE", R)
    iv = implied_vol(px, S, K, T, "CE", R)
    assert abs(iv - SIGMA) < 1e-4


def test_implied_vol_none_outside_no_arbitrage_band():
    assert implied_vol(-1, S, K, T, "CE") is None
    assert implied_vol(price(S, K, T, 0.005, "CE") - 1, S, K, T, "CE") is None


def test_delta_bounds():
    dc = delta(S, K, T, SIGMA, "CE", R)
    dp = delta(S, K, T, SIGMA, "PE", R)
    assert 0.0 <= dc <= 1.0
    assert -1.0 <= dp <= 0.0
    assert abs((dc - dp) - 1.0) < 1e-9  # call delta - put delta == 1


def test_gamma_positive_and_symmetric_for_calls_and_puts():
    assert gamma(S, K, T, SIGMA, R) > 0


def test_vega_positive():
    assert vega(S, K, T, SIGMA, R) > 0


def test_theta_negative_for_atm_long_option():
    # a long ATM option decays -- theta should be negative for both cp
    assert theta(S, K, T, SIGMA, "CE", R) < 0
    assert theta(S, K, T, SIGMA, "PE", R) < 0


def test_years_to_expiry_positive_and_shrinks():
    t1 = years_to_expiry("2025-01-01T09:15:00", "2025-01-10")
    t2 = years_to_expiry("2025-01-05T09:15:00", "2025-01-10")
    assert t1 > t2 > 0


if __name__ == "__main__":
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\n{len(tests)} tests passed")
