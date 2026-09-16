"""Every closed-form Greek checked against a finite difference of price()
(or, for the second-order cross Greeks, of the first-order Greek they come
from) across a grid of random (S, K, T, sigma, r, cp) points. This is a
permanent version of the ad-hoc checks used to verify the BSM formulas and
derive vanna/charm/volga in the first place -- run once by hand, then
thrown away; this keeps the same check as a regression test instead.
"""
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bs_solver.black_scholes import price, delta, gamma, vega, theta, rho, vanna, charm, volga

TOL = 1e-4  # relative to the finite-difference step's own truncation error


def cases(n=25, seed=11):
    rng = random.Random(seed)
    out = []
    for _ in range(n):
        S = rng.uniform(50, 500)
        K = rng.uniform(50, 500)
        T = rng.uniform(0.02, 2.0)
        sigma = rng.uniform(0.05, 1.2)
        r = rng.uniform(0.0, 0.12)
        cp = rng.choice(["CE", "PE"])
        out.append((S, K, T, sigma, r, cp))
    return out


def rel_err(a, b):
    return abs(a - b) / max(1.0, abs(a))


def test_delta_matches_finite_diff_of_price():
    h = 1e-4
    for S, K, T, sigma, r, cp in cases():
        fd = (price(S + h, K, T, sigma, cp, r=r) - price(S - h, K, T, sigma, cp, r=r)) / (2 * h)
        assert rel_err(delta(S, K, T, sigma, cp, r=r), fd) < TOL


def test_gamma_matches_finite_diff_of_price():
    h = 1e-3
    for S, K, T, sigma, r, cp in cases():
        fd = (price(S + h, K, T, sigma, cp, r=r) - 2 * price(S, K, T, sigma, cp, r=r)
              + price(S - h, K, T, sigma, cp, r=r)) / (h * h)
        assert rel_err(gamma(S, K, T, sigma, r=r), fd) < 1e-2  # 2nd-order FD is noisier


def test_vega_matches_finite_diff_of_price():
    h = 1e-5
    for S, K, T, sigma, r, cp in cases():
        fd = (price(S, K, T, sigma + h, cp, r=r) - price(S, K, T, sigma - h, cp, r=r)) / (2 * h)
        assert rel_err(vega(S, K, T, sigma, r=r), fd) < TOL


def test_theta_matches_finite_diff_of_price():
    """theta is decay per unit of calendar time elapsed = -d(price)/dT."""
    h = 1e-6
    for S, K, T, sigma, r, cp in cases():
        fd = -(price(S, K, T + h, sigma, cp, r=r) - price(S, K, T - h, sigma, cp, r=r)) / (2 * h)
        assert rel_err(theta(S, K, T, sigma, cp, r=r), fd) < TOL


def test_rho_matches_finite_diff_of_price():
    h = 1e-5
    for S, K, T, sigma, r, cp in cases():
        fd = (price(S, K, T, sigma, cp, r=r + h) - price(S, K, T, sigma, cp, r=r - h)) / (2 * h)
        assert rel_err(rho(S, K, T, sigma, cp, r=r), fd) < TOL


def test_vanna_matches_finite_diff_of_delta():
    h = 1e-5
    for S, K, T, sigma, r, cp in cases():
        fd = (delta(S, K, T, sigma + h, cp, r=r) - delta(S, K, T, sigma - h, cp, r=r)) / (2 * h)
        assert rel_err(vanna(S, K, T, sigma, r=r), fd) < TOL


def test_charm_matches_finite_diff_of_delta():
    h = 1e-6
    for S, K, T, sigma, r, cp in cases():
        fd = -(delta(S, K, T + h, sigma, cp, r=r) - delta(S, K, T - h, sigma, cp, r=r)) / (2 * h)
        assert rel_err(charm(S, K, T, sigma, cp, r=r), fd) < TOL


def test_volga_matches_finite_diff_of_vega():
    h = 1e-5
    for S, K, T, sigma, r, cp in cases():
        fd = (vega(S, K, T, sigma + h, r=r) - vega(S, K, T, sigma - h, r=r)) / (2 * h)
        assert rel_err(volga(S, K, T, sigma, r=r), fd) < TOL


def test_vanna_and_charm_are_cp_independent():
    """delta_put = delta_call - 1 (a constant shift), so every derivative
    of delta -- vanna, charm -- must be identical for calls and puts."""
    for S, K, T, sigma, r, _ in cases():
        assert abs(vanna(S, K, T, sigma, r=r) - vanna(S, K, T, sigma, r=r)) < 1e-12
        assert abs(charm(S, K, T, sigma, "CE", r=r) - charm(S, K, T, sigma, "PE", r=r)) < 1e-12


if __name__ == "__main__":
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\n{len(tests)} tests passed")
