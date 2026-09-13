"""Sanity checks for the Greek attribution engine."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bs_solver import price, attribute_leg, attribute_portfolio

S, K, T, SIGMA, R = 100.0, 100.0, 0.5, 0.20, 0.05


def test_zero_move_is_fully_explained():
    r = attribute_leg(S, S, K, T, T, SIGMA, SIGMA, "CE")
    assert abs(r["actual_pnl"]) < 1e-9
    for f in ("delta_pnl", "gamma_pnl", "vega_pnl", "theta_pnl", "rho_pnl", "residual"):
        assert abs(r[f]) < 1e-9


def test_actual_pnl_matches_direct_reprice():
    r = attribute_leg(S, 102.0, K, T, T, SIGMA, SIGMA, "CE")
    direct = price(102.0, K, T, SIGMA, "CE") - price(S, K, T, SIGMA, "CE")
    assert abs(r["actual_pnl"] - direct) < 1e-9


def test_residual_shrinks_as_move_shrinks():
    """The Taylor expansion is a local approximation -- a smaller spot move
    should leave a smaller (in absolute terms) unexplained residual."""
    big = attribute_leg(S, S * 1.10, K, T, T, SIGMA, SIGMA, "CE")
    small = attribute_leg(S, S * 1.01, K, T, T, SIGMA, SIGMA, "CE")
    assert abs(small["residual"]) < abs(big["residual"])


def test_pure_time_decay_is_all_theta():
    """Nothing else moves -- delta/gamma/vega/rho terms must be exactly
    zero and theta should account for (nearly) the whole repricing."""
    r = attribute_leg(S, S, K, T, T - 30 / 365, SIGMA, SIGMA, "CE")
    assert r["delta_pnl"] == 0.0 and r["gamma_pnl"] == 0.0
    assert r["vega_pnl"] == 0.0 and r["rho_pnl"] == 0.0
    assert abs(r["residual"]) < abs(r["actual_pnl"]) * 0.05


def test_short_leg_flips_the_sign():
    long_pnl = attribute_leg(S, 105.0, K, T, T, SIGMA, SIGMA, "CE", qty=1.0)
    short_pnl = attribute_leg(S, 105.0, K, T, T, SIGMA, SIGMA, "CE", qty=-1.0)
    assert abs(long_pnl["actual_pnl"] + short_pnl["actual_pnl"]) < 1e-9


def test_portfolio_sums_its_legs():
    legs = [
        dict(S0=S, S1=103.0, K=100.0, T0=T, T1=T, sigma0=SIGMA, sigma1=SIGMA, cp="CE", qty=2.0),
        dict(S0=S, S1=103.0, K=105.0, T0=T, T1=T, sigma0=SIGMA, sigma1=0.22, cp="PE", qty=-1.0),
    ]
    out = attribute_portfolio(legs)
    for f in ("actual_pnl", "delta_pnl", "gamma_pnl", "vega_pnl", "theta_pnl", "rho_pnl", "residual"):
        assert abs(out["total"][f] - sum(leg[f] for leg in out["legs"])) < 1e-9
    assert 0.0 <= out["total"]["pct_explained"] <= 1.2  # allow slack for the residual's sign


def test_pct_explained_is_nan_for_zero_actual_pnl():
    out = attribute_portfolio([dict(S0=S, S1=S, K=K, T0=T, T1=T, sigma0=SIGMA, sigma1=SIGMA, cp="CE")])
    assert out["total"]["pct_explained"] != out["total"]["pct_explained"]  # nan != nan


if __name__ == "__main__":
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\n{len(tests)} tests passed")
