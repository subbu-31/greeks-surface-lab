#!/usr/bin/env python3
"""
attribute_pnl.py -- Run the Greek attribution engine on a real, consecutive
sequence of daily snapshots (same strike, same expiry, five real trading
days from web/data/snapshot_series.json -- see build_snapshot_series.py).
For each day-to-day transition, decompose the straddle's actual P&L into
delta/gamma/vega/theta/rho contributions plus a residual.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bs_solver import attribute_portfolio

SERIES = Path(__file__).resolve().parents[1] / "web" / "data" / "snapshot_series.json"

FIELDS = ("price0", "price1", "actual_pnl", "delta_pnl", "gamma_pnl", "vega_pnl", "theta_pnl", "rho_pnl", "residual")
HEADER = f"{'transition':<24}{'price0':>9}{'price1':>9}{'actual':>9}{'delta':>9}{'gamma':>9}{'vega':>9}{'theta':>9}{'rho':>9}{'resid':>9}"


def main():
    payload = json.loads(SERIES.read_text())
    samples = payload["samples"]
    r = payload["risk_free"]
    K = payload["atm_strike"]
    print(f"expiry {payload['expiry']}, strike {K}, {len(samples)} real daily snapshots "
          f"at {payload['entry_time']}\n")

    print(HEADER)
    print("-" * len(HEADER))
    running_actual, running_residual = 0.0, 0.0
    for a, b in zip(samples, samples[1:]):
        T0, T1 = a["dte_days"] / 365.0, b["dte_days"] / 365.0
        legs = [
            dict(S0=a["spot"], S1=b["spot"], K=K, T0=T0, T1=T1,
                 sigma0=a["ce"]["iv"], sigma1=b["ce"]["iv"], cp="CE", r0=r),
            dict(S0=a["spot"], S1=b["spot"], K=K, T0=T0, T1=T1,
                 sigma0=a["pe"]["iv"], sigma1=b["pe"]["iv"], cp="PE", r0=r),
        ]
        out = attribute_portfolio(legs)["total"]
        label = f"{a['date']} -> {b['date']}"
        print(f"{label:<24}" + "".join(f"{out[f]:>9.2f}" for f in FIELDS))
        running_actual += out["actual_pnl"]
        running_residual += out["residual"]

    print("-" * len(HEADER))
    print(f"Over the full {len(samples)}-day window: {running_actual:+.2f} actual P&L on the "
          f"straddle, {running_residual:+.2f} of it ({abs(running_residual/running_actual):.1%}) "
          "unexplained by the five Greek terms -- the rest is vanna/charm and other cross terms "
          "the linear/quadratic expansion doesn't reach.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
