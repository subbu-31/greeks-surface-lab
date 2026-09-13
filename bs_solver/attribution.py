"""Greek-based P&L attribution: given an option's parameters at two points
in time, explain the change in price as a sum of first-order Greek
contributions (delta, gamma, vega, theta, rho) plus whatever the Taylor
expansion doesn't capture -- cross terms like vanna and charm, and anything
higher order in a large move.

This is the standard desk technique for explaining an options book's daily
P&L: reprice isn't itself informative about *why* the number moved, but the
Greeks measured at the start of the period are, up to the size of the
residual.
"""
from .black_scholes import price, delta, gamma, vega, theta, rho, RF


def attribute_leg(S0, S1, K, T0, T1, sigma0, sigma1, cp, r0=RF, r1=None, qty=1.0):
    """Attribute one leg's P&L between two snapshots to its Greeks at t0.

    S0/S1: spot before/after. T0/T1: years-to-expiry before/after (T1 < T0
    for a forward move in time -- theta_pnl uses the elapsed time T0 - T1,
    matching black_scholes.theta's own per-calendar-time-elapsed sign
    convention). sigma0/sigma1: implied vol before/after. r0/r1: risk-free
    rate before/after (defaults to unchanged).
    qty: signed contracts -- negative for a short leg, scales every term.

    Returns price0/price1/actual_pnl at qty scale, each Greek's contribution
    (delta_pnl from dS, gamma_pnl from the second-order dS term, vega_pnl
    from dsigma, theta_pnl from the passage of time, rho_pnl from dr), and
    a residual: actual_pnl minus the sum of those five terms.
    """
    if r1 is None:
        r1 = r0

    p0 = price(S0, K, T0, sigma0, cp, r0)
    p1 = price(S1, K, T1, sigma1, cp, r1)

    d0 = delta(S0, K, T0, sigma0, cp, r0)
    g0 = gamma(S0, K, T0, sigma0, r0)
    v0 = vega(S0, K, T0, sigma0, r0)
    th0 = theta(S0, K, T0, sigma0, cp, r0)
    rh0 = rho(S0, K, T0, sigma0, cp, r0)

    dS = S1 - S0
    dsigma = sigma1 - sigma0
    dt_elapsed = T0 - T1  # positive as time passes; theta is quoted per unit of *this*
    dr = r1 - r0

    delta_pnl = d0 * dS
    gamma_pnl = 0.5 * g0 * dS * dS
    vega_pnl = v0 * dsigma
    theta_pnl = th0 * dt_elapsed
    rho_pnl = rh0 * dr

    actual_pnl = p1 - p0
    explained = delta_pnl + gamma_pnl + vega_pnl + theta_pnl + rho_pnl
    residual = actual_pnl - explained

    return {
        "price0": p0, "price1": p1, "actual_pnl": qty * actual_pnl,
        "delta_pnl": qty * delta_pnl, "gamma_pnl": qty * gamma_pnl,
        "vega_pnl": qty * vega_pnl, "theta_pnl": qty * theta_pnl,
        "rho_pnl": qty * rho_pnl, "residual": qty * residual,
        "greeks_t0": {"delta": d0, "gamma": g0, "vega": v0, "theta": th0, "rho": rh0},
    }


def attribute_portfolio(legs):
    """Sum attribute_leg(**leg) across a book. `legs` is a list of dicts,
    each with the keyword arguments attribute_leg takes (qty included).

    Returns the per-leg breakdowns plus a "total" row summing every field
    other than greeks_t0, and "pct_explained": how much of the actual move
    the five Greek terms account for (nan if actual_pnl is exactly zero).
    """
    rows = [attribute_leg(**leg) for leg in legs]
    fields = ["price0", "price1", "actual_pnl", "delta_pnl", "gamma_pnl",
              "vega_pnl", "theta_pnl", "rho_pnl", "residual"]
    total = {f: sum(r[f] for r in rows) for f in fields}
    explained = total["actual_pnl"] - total["residual"]
    total["pct_explained"] = (
        explained / total["actual_pnl"] if total["actual_pnl"] != 0 else float("nan")
    )
    return {"legs": rows, "total": total}
