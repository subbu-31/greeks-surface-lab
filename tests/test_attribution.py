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


def test_cross_terms_reduce_the_residual():
    """A move in both spot and vol together is exactly where the pure
    first-order/gamma decomposition leaves the most on the table -- vanna
    (the dS*dsigma cross term) should recover most of it."""
    r = attribute_leg(S, S * 1.08, K, T, T, SIGMA, SIGMA * 1.3, "CE")
    first_order_only = r["delta_pnl"] + r["gamma_pnl"] + r["vega_pnl"] + r["theta_pnl"] + r["rho_pnl"]
    residual_without_cross_terms = r["actual_pnl"] - first_order_only
    assert abs(r["residual"]) < abs(residual_without_cross_terms)


def test_volga_reduces_residual_for_a_large_vol_only_move():
    # A 30% relative vol move -- large, but still inside the range where a
    # second-order Taylor term is expected to help. (At a much larger move,
    # e.g. sigma doubling, third-order curvature can dominate volga's
    # correction entirely -- that isn't a bug, it's Taylor expansions being
    # a local approximation, and is exactly why a residual is reported
    # rather than treated as fully closed by any finite Greek ladder.)
    r = attribute_leg(S, S, K, T, T, SIGMA, SIGMA * 1.3, "CE")
    first_order_only = r["delta_pnl"] + r["gamma_pnl"] + r["vega_pnl"] + r["theta_pnl"] + r["rho_pnl"]
    residual_without_volga = r["actual_pnl"] - first_order_only
    assert abs(r["residual"]) < abs(residual_without_volga)


def test_charm_reduces_residual_for_a_combined_spot_and_time_move():
    r = attribute_leg(S, S * 1.05, K, T, T - 20 / 365, SIGMA, SIGMA, "CE")
    first_order_only = r["delta_pnl"] + r["gamma_pnl"] + r["vega_pnl"] + r["theta_pnl"] + r["rho_pnl"]
    residual_without_charm = r["actual_pnl"] - first_order_only
    assert abs(r["residual"]) < abs(residual_without_charm)


def test_pure_vol_move_has_no_vanna_or_charm_contribution():
    """Only sigma changes -- dS=0 and dt_elapsed=0, so the two cross terms
    (which both require dS) must vanish exactly, leaving vega + volga."""
    r = attribute_leg(S, S, K, T, T, SIGMA, SIGMA * 1.4, "CE")
    assert r["vanna_pnl"] == 0.0 and r["charm_pnl"] == 0.0
    assert r["volga_pnl"] != 0.0  # the one second-order term that doesn't need dS


def test_pure_rate_move_is_all_rho():
    """Nothing else moves -- delta/gamma/vega/theta terms must be exactly
    zero and rho should account for (nearly) the whole repricing. Mirrors
    test_pure_time_decay_is_all_theta, and exists because rho had never
    once been exercised with a nonzero rate change anywhere in this
    project before this test: attribute_leg defaults r1 to r0, and nothing
    calling it ever passed a different value -- so rho_pnl was
    structurally 0.0 in every number this project had ever reported.
    The 25bp move here is the real, documented RBI MPC cut of 2025-02-07
    (6.50% -> 6.25%, the first in the cutting cycle that continued through
    2025), not an arbitrary number picked to make the test pass.
    """
    r = attribute_leg(S, S, K, T, T, SIGMA, SIGMA, "CE", r0=0.065, r1=0.0625)
    assert r["delta_pnl"] == 0.0 and r["gamma_pnl"] == 0.0
    assert r["vega_pnl"] == 0.0 and r["theta_pnl"] == 0.0
    assert r["rho_pnl"] != 0.0
    assert abs(r["residual"]) < abs(r["actual_pnl"]) * 0.05


def test_rho_pnl_has_the_right_sign_for_a_real_rate_cut():
    """A call's rho is positive (higher rates -> higher forward -> more
    valuable call), so a rate CUT must reduce a long call's price via a
    negative rho_pnl, and do the opposite for a put. Uses the real,
    documented 2025-06-06 RBI cut (6.00% -> 5.50%, 50bps) -- the same cut
    that exposed build_market_snapshot.py's stale RF=0.065 default for its
    2025-06-02 snapshot date (fixed to 0.060, the rate actually in effect
    on that date per RBI/PIB primary sources)."""
    call = attribute_leg(S, S, K, T, T, SIGMA, SIGMA, "CE", r0=0.060, r1=0.055)
    put = attribute_leg(S, S, K, T, T, SIGMA, SIGMA, "PE", r0=0.060, r1=0.055)
    assert call["rho_pnl"] < 0.0
    assert put["rho_pnl"] > 0.0


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
    for f in ("actual_pnl", "delta_pnl", "gamma_pnl", "vega_pnl", "volga_pnl", "vanna_pnl",
              "theta_pnl", "charm_pnl", "rho_pnl", "residual"):
        assert abs(out["total"][f] - sum(leg[f] for leg in out["legs"])) < 1e-9
    assert 0.0 <= out["total"]["pct_explained"] <= 1.2  # allow slack for the residual's sign


def test_netting_signed_residuals_across_independent_periods_is_misleading():
    """Regression test for a real bug found while building this: rolling up
    multiple days' attributions with net(residual)/net(actual) -- the same
    pattern attribute_portfolio correctly uses ACROSS LEGS -- lets one day's
    positive residual cancel another's negative one and can make a
    per-day fit that's actually consistent (each day similarly good or bad)
    look wildly better or worse than it is. The fix (used in
    scripts/attribute_pnl.py) is sum(|residual_i|) / sum(|actual_i|).
    This test constructs two days with identical, real per-day residual
    quality but opposite-signed residuals, and shows the naive net ratio
    swings enormously while the robust one stays put.
    """
    day1 = attribute_leg(S, S * 1.06, K, T, T, SIGMA, SIGMA * 1.25, "CE")
    day2 = attribute_leg(S, S * 0.94, K, T, T, SIGMA, SIGMA * 0.8, "CE")
    residuals = [day1["residual"], day2["residual"]]
    actuals = [day1["actual_pnl"], day2["actual_pnl"]]

    naive_net_ratio = abs(sum(residuals)) / abs(sum(actuals))
    robust_ratio = sum(abs(r) for r in residuals) / sum(abs(a) for a in actuals)

    # The robust, per-day metric is bounded by construction (each day's own
    # fit is reasonable); the naive net metric has no such guarantee and
    # can be pushed arbitrarily high by picking day2's move to make the two
    # residuals close to offsetting in sign while the two actual_pnls partly
    # cancel too -- exactly the failure mode this test exists to catch.
    assert robust_ratio < 0.5
    assert naive_net_ratio >= robust_ratio  # the whole point: net-of-signs is never more informative


def test_pct_explained_is_nan_for_zero_actual_pnl():
    out = attribute_portfolio([dict(S0=S, S1=S, K=K, T0=T, T1=T, sigma0=SIGMA, sigma1=SIGMA, cp="CE")])
    assert out["total"]["pct_explained"] != out["total"]["pct_explained"]  # nan != nan


if __name__ == "__main__":
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\n{len(tests)} tests passed")
