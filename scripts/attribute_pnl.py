#!/usr/bin/env python3
"""
attribute_pnl.py -- Run the Greek attribution engine on a real, consecutive
sequence of daily snapshots (six real strikes, one expiry, five real
trading days from web/data/snapshot_series.json -- see
build_snapshot_series.py), three structures in increasing order of
complexity: a straddle, then a strangle, then an iron condor built from
the same six legs.

Each structure prints its own day-by-day table and running total so a
regression in the next structure's plumbing is visible immediately against
the previous, already-verified one, rather than discovered only at the end.
Every row also reports the thinnest volume among that transition's legs --
this attribution is built on last-traded prices with no bid/ask, exactly
like the market snapshot, and a residual on a thinly-traded print is at
least as likely to be quote staleness as a missing Greek. See the ATM put
on 2024-12-30/12-31 below: it clears the 50-lot floor but at 75 contracts
against thousands elsewhere, "explained by the Greeks" and "priced off a
stale minute" are not distinguishable from this data alone.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bs_solver import attribute_portfolio

SERIES = Path(__file__).resolve().parents[1] / "web" / "data" / "snapshot_series.json"

FIELDS = ("actual_pnl", "delta_pnl", "gamma_pnl", "vega_pnl", "volga_pnl", "vanna_pnl",
          "theta_pnl", "charm_pnl", "rho_pnl", "residual")
HEADER = (f"{'transition':<24}" +
          "".join(f"{f.replace('_pnl',''):>9}" for f in FIELDS) + f"{'min_vol':>9}")


def leg_spec(name, a, b, K, T0, T1, r, cp, qty):
    return dict(S0=a["spot"], S1=b["spot"], K=K, T0=T0, T1=T1,
                sigma0=a["legs"][name]["iv"], sigma1=b["legs"][name]["iv"],
                cp=cp, r0=r, qty=qty)


def min_volume(a, b, leg_names):
    """The thinnest single print behind this transition -- across both legs
    and both days -- since one illiquid corner is enough to make the whole
    transition's residual suspect."""
    return min(min(a["legs"][n]["volume"], b["legs"][n]["volume"]) for n in leg_names)


def run_structure(title, leg_names, samples, strikes, r, leg_builder, liquid_min_volume):
    print(f"\n=== {title} ===")
    print(HEADER)
    print("-" * len(HEADER))
    running = {f: 0.0 for f in FIELDS}
    sum_abs_actual, sum_abs_residual = 0.0, 0.0
    sum_abs_actual_liquid, sum_abs_residual_liquid = 0.0, 0.0
    thin_transitions = []
    for a, b in zip(samples, samples[1:]):
        T0, T1 = a["dte_days"] / 365.0, b["dte_days"] / 365.0
        legs = leg_builder(a, b, strikes, T0, T1, r)
        out = attribute_portfolio(legs)["total"]
        mv = min_volume(a, b, leg_names)
        label = f"{a['date']} -> {b['date']}"
        print(f"{label:<24}" + "".join(f"{out[f]:>9.2f}" for f in FIELDS) + f"{mv:>9d}")
        for f in FIELDS:
            running[f] += out[f]
        sum_abs_actual += abs(out["actual_pnl"])
        sum_abs_residual += abs(out["residual"])
        if mv < liquid_min_volume * 3:  # flag anything within 3x the liquidity floor, not just below it
            thin_transitions.append((label, mv))
        else:
            sum_abs_actual_liquid += abs(out["actual_pnl"])
            sum_abs_residual_liquid += abs(out["residual"])
    print("-" * len(HEADER))
    print(f"{'total':<24}" + "".join(f"{running[f]:>9.2f}" for f in FIELDS))
    # Deliberately NOT |sum(residual)| / |sum(actual)| -- summing signed
    # residuals across independent day-to-day transitions lets a bad day's
    # error cancel against a good day's, so that ratio can look artificially
    # great (or artificially awful) depending on which way residuals happen
    # to point that week. sum(|residual_i|) / sum(|actual_i|) scores each
    # day's fit on its own and can't benefit from cross-day cancellation.
    frac_unexplained = sum_abs_residual / sum_abs_actual if sum_abs_actual else float("nan")
    print(f"Per-day fit, all transitions: {1 - frac_unexplained:.1%} explained "
          f"({sum_abs_residual:.2f} of {sum_abs_actual:.2f} points unexplained).")
    if thin_transitions:
        names = ", ".join(f"{label} (min vol {mv})" for label, mv in thin_transitions)
        if sum_abs_actual_liquid:
            frac_liquid = sum_abs_residual_liquid / sum_abs_actual_liquid
            print(f"  {len(thin_transitions)} transition(s) involve a leg within 3x the "
                  f"{liquid_min_volume}-lot liquidity floor and are excluded from a re-check: "
                  f"{names}.")
            print(f"  Per-day fit, thin transitions excluded: {1 - frac_liquid:.1%} explained "
                  f"({sum_abs_residual_liquid:.2f} of {sum_abs_actual_liquid:.2f} points).")
        else:
            print(f"  All {len(thin_transitions)} transition(s) involve a thin leg "
                  f"(within 3x the {liquid_min_volume}-lot floor): {names} -- no liquid-only "
                  "comparison possible for this structure.")
    else:
        print("  No transition involves a leg within 3x the liquidity floor.")
    return running


STRUCTURES = [
    ("straddle", ["atm_ce", "atm_pe"]),
    ("strangle", ["short_call", "short_put"]),
    ("condor", ["short_call", "short_put", "long_call", "long_put"]),
]


def straddle_legs(a, b, strikes, T0, T1, r):
    K = strikes["atm"]
    return [
        leg_spec("atm_ce", a, b, K, T0, T1, r, "CE", qty=1.0),
        leg_spec("atm_pe", a, b, K, T0, T1, r, "PE", qty=1.0),
    ]


def strangle_legs(a, b, strikes, T0, T1, r):
    # Long strangle: OTM call + OTM put, no short legs -- the natural next
    # step up from a straddle (same "buy both sides" shape, wider strikes).
    return [
        leg_spec("short_call", a, b, strikes["short_call"], T0, T1, r, "CE", qty=1.0),
        leg_spec("short_put", a, b, strikes["short_put"], T0, T1, r, "PE", qty=1.0),
    ]


def condor_legs(a, b, strikes, T0, T1, r):
    # Iron condor: sell the near-the-money strangle, buy the further-out
    # wings for defined risk -- the four legs already priced above,
    # combined with the sign convention (short = negative qty) that was
    # never exercised by the straddle or strangle runs on their own.
    return [
        leg_spec("short_call", a, b, strikes["short_call"], T0, T1, r, "CE", qty=-1.0),
        leg_spec("short_put", a, b, strikes["short_put"], T0, T1, r, "PE", qty=-1.0),
        leg_spec("long_call", a, b, strikes["long_call"], T0, T1, r, "CE", qty=1.0),
        leg_spec("long_put", a, b, strikes["long_put"], T0, T1, r, "PE", qty=1.0),
    ]


def main():
    payload = json.loads(SERIES.read_text())
    samples = payload["samples"]
    strikes = payload["strikes"]
    r = payload["risk_free"]
    liquid_min_volume = payload.get("liquid_min_volume", 50)
    print(f"expiry {payload['expiry']}, {len(samples)} real daily snapshots at {payload['entry_time']}")
    print(f"strikes: {strikes}")

    run_structure(f"Straddle  (ATM {strikes['atm']} CE + PE)", STRUCTURES[0][1],
                  samples, strikes, r, straddle_legs, liquid_min_volume)
    run_structure(f"Strangle  (long {strikes['short_call']} CE + {strikes['short_put']} PE)",
                  STRUCTURES[1][1], samples, strikes, r, strangle_legs, liquid_min_volume)
    run_structure(f"Iron condor  (sell {strikes['short_put']}/{strikes['short_call']}, "
                  f"buy {strikes['long_put']}/{strikes['long_call']})",
                  STRUCTURES[2][1], samples, strikes, r, condor_legs, liquid_min_volume)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
