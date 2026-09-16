"""Greek-based P&L attribution: given an option's parameters at two points
in time, explain the change in price as a sum of Greek contributions --
first-order (delta, vega, theta, rho) and the second-order/cross terms that
matter most in practice (gamma, vanna, volga, charm) -- plus whatever the
Taylor expansion still doesn't reach: third-order terms, and cross terms
with rho, both usually negligible for short-dated equity index options.

This is the standard desk technique for explaining an options book's P&L:
reprice isn't itself informative about *why* the number moved, but the
Greeks measured at the start of the period are, up to the size of the
residual. Decomposing the cross terms explicitly (rather than leaving them
in one undifferentiated residual) is what turns "the Greeks mostly explain
it" into an actual account of *which* Greek did what.
"""
from __future__ import annotations

from typing import Any, Iterable, List, Optional, TypedDict

from .black_scholes import CP, charm, delta, gamma, price, rho, theta, vanna, vega, volga


class Greeks(TypedDict):
    delta: float
    gamma: float
    vega: float
    theta: float
    rho: float
    vanna: float
    charm: float
    volga: float


class LegAttribution(TypedDict):
    price0: float
    price1: float
    actual_pnl: float
    delta_pnl: float
    gamma_pnl: float
    vega_pnl: float
    volga_pnl: float
    vanna_pnl: float
    theta_pnl: float
    charm_pnl: float
    rho_pnl: float
    residual: float
    greeks_t0: Greeks


class TotalRow(TypedDict):
    price0: float
    price1: float
    actual_pnl: float
    delta_pnl: float
    gamma_pnl: float
    vega_pnl: float
    volga_pnl: float
    vanna_pnl: float
    theta_pnl: float
    charm_pnl: float
    rho_pnl: float
    residual: float
    pct_explained: float


class PortfolioAttribution(TypedDict):
    legs: List[LegAttribution]
    total: TotalRow


def attribute_leg(S0: float, S1: float, K: float, T0: float, T1: float,
                   sigma0: float, sigma1: float, cp: CP, *,
                   r0: float, r1: Optional[float] = None,
                   qty: float = 1.0) -> LegAttribution:
    """Attribute one leg's P&L between two snapshots to its Greeks at t0.

    S0/S1: spot before/after. T0/T1: years-to-expiry before/after (T1 < T0
    for a forward move in time -- theta_pnl and charm_pnl use the elapsed
    time T0 - T1, matching black_scholes.theta's own per-calendar-time-
    elapsed sign convention). sigma0/sigma1: implied vol before/after.
    r0/r1: risk-free rate before/after (r1 defaults to r0 -- "unchanged" is
    a real modeling default, unlike r0 itself, which every caller must name;
    see bs_solver.rates.rf_rate() for the source of a real r0/r1 pair).
    qty: signed contracts -- negative for a short leg, scales every term.

    Returns price0/price1/actual_pnl at qty scale, each Greek's contribution
    -- delta_pnl (dS), gamma_pnl (0.5*dS^2), vega_pnl (dsigma), volga_pnl
    (0.5*dsigma^2), vanna_pnl (dS*dsigma cross term), theta_pnl (elapsed
    time), charm_pnl (dS*dt cross term), rho_pnl (dr) -- and a residual:
    actual_pnl minus the sum of all eight.
    """
    if r1 is None:
        r1 = r0

    p0 = price(S0, K, T0, sigma0, cp, r=r0)
    p1 = price(S1, K, T1, sigma1, cp, r=r1)

    d0 = delta(S0, K, T0, sigma0, cp, r=r0)
    g0 = gamma(S0, K, T0, sigma0, r=r0)
    v0 = vega(S0, K, T0, sigma0, r=r0)
    th0 = theta(S0, K, T0, sigma0, cp, r=r0)
    rh0 = rho(S0, K, T0, sigma0, cp, r=r0)
    va0 = vanna(S0, K, T0, sigma0, r=r0)
    ch0 = charm(S0, K, T0, sigma0, cp, r=r0)
    vo0 = volga(S0, K, T0, sigma0, r=r0)

    dS = S1 - S0
    dsigma = sigma1 - sigma0
    dt_elapsed = T0 - T1  # positive as time passes; theta/charm are quoted per unit of *this*
    dr = r1 - r0

    delta_pnl = d0 * dS
    gamma_pnl = 0.5 * g0 * dS * dS
    vega_pnl = v0 * dsigma
    volga_pnl = 0.5 * vo0 * dsigma * dsigma
    vanna_pnl = va0 * dS * dsigma
    theta_pnl = th0 * dt_elapsed
    charm_pnl = ch0 * dS * dt_elapsed
    rho_pnl = rh0 * dr

    actual_pnl = p1 - p0
    explained = (delta_pnl + gamma_pnl + vega_pnl + volga_pnl + vanna_pnl
                 + theta_pnl + charm_pnl + rho_pnl)
    residual = actual_pnl - explained

    return {
        "price0": p0, "price1": p1, "actual_pnl": qty * actual_pnl,
        "delta_pnl": qty * delta_pnl, "gamma_pnl": qty * gamma_pnl,
        "vega_pnl": qty * vega_pnl, "volga_pnl": qty * volga_pnl, "vanna_pnl": qty * vanna_pnl,
        "theta_pnl": qty * theta_pnl, "charm_pnl": qty * charm_pnl,
        "rho_pnl": qty * rho_pnl, "residual": qty * residual,
        "greeks_t0": {"delta": d0, "gamma": g0, "vega": v0, "theta": th0, "rho": rh0,
                      "vanna": va0, "charm": ch0, "volga": vo0},
    }


PNL_FIELDS = ["price0", "price1", "actual_pnl", "delta_pnl", "gamma_pnl", "vega_pnl",
              "volga_pnl", "vanna_pnl", "theta_pnl", "charm_pnl", "rho_pnl", "residual"]


def attribute_portfolio(legs: Iterable[dict[str, Any]]) -> PortfolioAttribution:
    """Sum attribute_leg(**leg) across a book. `legs` is a list of dicts,
    each with the keyword arguments attribute_leg takes (qty included).

    Returns the per-leg breakdowns plus a "total" row summing every field
    other than greeks_t0, and "pct_explained": how much of the actual move
    the eight Greek terms account for (nan if actual_pnl is exactly zero).

    Netting signed residuals across legs is valid here because every leg in
    `legs` is held over the *same* time period -- a hedge leg's residual
    genuinely offsetting another leg's is a real fact about the combined
    position. Do NOT reuse this same net-and-divide pattern to roll a
    "pct_explained" up across multiple, independent calls to this function
    (e.g. one call per day in a multi-day series) -- day-to-day residuals
    are unrelated draws, and summing them signed lets one day's error
    cancel another's, producing a ratio that reflects sign-cancellation
    luck rather than fit quality. Aggregate across periods with
    sum(|residual_i|) / sum(|actual_i|) instead -- see
    scripts/attribute_pnl.py's run_structure() for the mistake this
    guards against and the fix.
    """
    rows = [attribute_leg(**leg) for leg in legs]
    # PNL_FIELDS is a runtime list, not a set of literals, so mypy can't
    # verify each `f` is a valid LegAttribution key here -- it is, by
    # construction (PNL_FIELDS is exactly attribute_leg's numeric fields).
    total: dict[str, float] = {f: sum(r[f] for r in rows) for f in PNL_FIELDS}  # type: ignore[literal-required]
    explained = total["actual_pnl"] - total["residual"]
    total["pct_explained"] = (
        explained / total["actual_pnl"] if total["actual_pnl"] != 0 else float("nan")
    )
    return {"legs": rows, "total": total}  # type: ignore[typeddict-item]
