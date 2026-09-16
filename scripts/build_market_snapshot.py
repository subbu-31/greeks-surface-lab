#!/usr/bin/env python3
"""
build_market_snapshot.py -- Pull one real trading day's option chain across
several live expiries from the raw Zerodha weekly archives, price every
strike with bs_solver at each of seven hourly checkpoints through the
session, and dump a compact JSON payload for the web dashboard.

This is a one-off data-prep script (not part of the bs_solver package). It
reads DL_DIR the same way the source research pipeline did:
  <DL_DIR>/<expiry YYYYMMDD>.zip containing
    nifty_spot.csv                        1-min NIFTY 50 bars
    {strike}{CE|PE}_{expiry}.csv          1-min option bars

No bid/ask in this data -- only OHLCV + OI on the traded price -- so the
"liquidity" flag is a volume threshold on that single matched print, not a
real quoted spread, and the parity check uses the matched CE/PE close, not
a mid. Each checkpoint is matched to the most recent real print at or
before it, within a 3-minute staleness cap, rather than requiring an exact
same-minute trade -- most strikes don't print in every single minute, and
an exact-match requirement would starve every hour but the busiest one.
Every price used is still a real traded print; nothing here is interpolated
or synthesized.

Runs twice in this repo, on purpose: the default date (2024-12-27) is the
attribution engine's own first real day, so the two features describe the
same week. python3 build_market_snapshot.py --date 2026-03-11
--out web/data/market_snapshot_2026.json is a second, deliberately
different sample -- NIFTY's weekly expiry moved from Thursday to Tuesday
by 2026, and this is the breadth check that the pipeline (and the
date-aware rf_rate() it now uses instead of a hand-verified constant)
still works cleanly on that changed convention.
"""
import argparse
import json
import math
import os
import re
import sys
import zipfile
from pathlib import Path
from typing import Any, Optional

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bs_solver import implied_vol, delta, gamma, vega, theta, rf_rate

# Overridable via the DL_DIR env var (see README "Reproducing") -- the
# default only ever resolves to a path on the machine running it, never a
# literal committed to version control.
DL_DIR = Path(os.environ.get("DL_DIR", str(Path.home() / "Desktop" / "nifty options data")))
DEFAULT_OUT = Path(__file__).resolve().parents[1] / "web" / "data" / "market_snapshot.json"
LEG_RE = re.compile(r"^(\d+)(CE|PE)_(\d{8})\.csv$")

# NIFTY trades 09:15-15:30; hourly checkpoints from the open, one short of
# the close since a 15:15 mark is already 15 minutes from expiry-of-day.
# Same convention the (now-retired) build_intraday_series.py used.
CHECKPOINTS = ["09:15:00", "10:15:00", "11:15:00", "12:15:00",
               "13:15:00", "14:15:00", "15:15:00"]
MAX_STALENESS_MIN = 3

DEFAULT_SNAPSHOT_DATE = "2024-12-27"  # the same real day scripts/build_snapshot_series.py's
                                       # attribution demo starts from -- unified so the dashboard's
                                       # smile/skew/term-structure and the attribution engine's Greek
                                       # breakdown describe the same market, not two unrelated weeks
N_EXPIRIES = 4                        # nearest N weekly expiries live that day
LIQUID_MIN_VOLUME = 50                # contracts traded in the matched print
PARITY_TOL_PTS = 15.0                 # |residual| beyond this is flagged, not "arbitrage"


def load_ts(df: pd.DataFrame) -> pd.DataFrame:
    df["ts"] = pd.to_datetime(df["Timestamp"], format="%d-%m-%Y %H:%M:%S", errors="coerce")
    return df


def nearest_prior(df: pd.DataFrame, date: str, time_: str,
                   require_volume: bool) -> tuple[Optional[float], Optional[int]]:
    """Most recent real print at or before `time_`, within the staleness cap."""
    target = pd.Timestamp(f"{date} {time_}")
    lo = target - pd.Timedelta(minutes=MAX_STALENESS_MIN)
    window = df[(df["ts"] <= target) & (df["ts"] >= lo)]
    if require_volume:
        window = window[window["Volume"] > 0]
    if not len(window):
        return None, None
    row = window.loc[window["ts"].idxmax()]
    vol = int(row["Volume"]) if "Volume" in row else None
    return float(row["Close"]), vol


def years_to_expiry(date: str, time_: str, expiry_yyyymmdd: str) -> float:
    entry = pd.Timestamp(f"{date} {time_}")
    exp = pd.Timestamp(f"{expiry_yyyymmdd[:4]}-{expiry_yyyymmdd[4:6]}-{expiry_yyyymmdd[6:]} 15:30:00")
    return max((exp - entry).total_seconds(), 1e-6) / 86400.0 / 365.0


def nearest_by_delta(rows: list[dict[str, Any]], target_abs_delta: float, cp: str) -> Optional[dict[str, Any]]:
    cand = [r for r in rows if r["cp"] == cp and r["delta"] is not None]
    if not cand:
        return None
    return min(cand, key=lambda r: abs(abs(r["delta"]) - target_abs_delta))


def price_expiry_at(expiry: str, spot_df: pd.DataFrame, legs: dict[tuple[int, str], pd.DataFrame],
                     snapshot_date: str, time_: str, rf: float) -> Optional[dict[str, Any]]:
    S, _ = nearest_prior(spot_df, snapshot_date, time_, require_volume=False)
    if S is None:
        return None
    T = years_to_expiry(snapshot_date, time_, expiry)
    dte_days = round(T * 365, 2)

    rows = []
    n_total = len(legs)
    for (strike, cp), df in legs.items():
        close, volume = nearest_prior(df, snapshot_date, time_, require_volume=True)
        if close is None or close <= 0.5:
            continue
        iv = implied_vol(close, S, strike, T, cp, r=rf)
        if iv is None or not (0.02 < iv < 3.0):
            continue
        d = delta(S, strike, T, iv, cp, r=rf)
        g = gamma(S, strike, T, iv, r=rf)
        v = vega(S, strike, T, iv, r=rf)
        th = theta(S, strike, T, iv, cp, r=rf)
        rows.append({
            "strike": strike, "cp": cp, "close": close, "volume": volume,
            "moneyness": round(strike / S, 4), "iv": round(iv, 4),
            "delta": round(d, 4), "gamma": round(g, 6), "vega": round(v, 3),
            "theta_per_day": round(th / 365.0, 3),
            "liquid": (volume or 0) >= LIQUID_MIN_VOLUME,
        })
    rows.sort(key=lambda r: (r["strike"], r["cp"]))

    # Put-call parity, discounted-strike form: C - P + K*e^-rT - S should
    # be ~0 for a genuine European pair. Flagging a large residual as
    # "likely stale/illiquid/asynchronous", never as an arbitrage signal --
    # these are two separate last-traded prints, not a simultaneous quote.
    by_strike: dict[int, dict[str, Any]] = {}
    for r in rows:
        by_strike.setdefault(r["strike"], {})[r["cp"]] = r
    parity = []
    for k, leg_pair in by_strike.items():
        if "CE" in leg_pair and "PE" in leg_pair:
            residual = (leg_pair["CE"]["close"] - leg_pair["PE"]["close"]
                        + k * math.exp(-rf * T) - S)
            parity.append({
                "strike": k, "residual": round(residual, 2),
                "ce_vol": leg_pair["CE"]["volume"], "pe_vol": leg_pair["PE"]["volume"],
                "valid": abs(residual) <= PARITY_TOL_PTS,
            })

    parity_by_strike = {p["strike"]: p["valid"] for p in parity}
    for r in rows:
        r["parity_valid"] = parity_by_strike.get(r["strike"])  # None = other leg didn't trade

    atm_ce = nearest_by_delta(rows, 0.5, "CE")
    atm_pe = nearest_by_delta(rows, 0.5, "PE")
    atm_iv = None
    if atm_ce and atm_pe:
        atm_iv = round((atm_ce["iv"] + atm_pe["iv"]) / 2, 4)
    d25c = nearest_by_delta(rows, 0.25, "CE")
    d25p = nearest_by_delta(rows, 0.25, "PE")

    return {
        "expiry": expiry, "dte_days": dte_days, "spot": S,
        "atm_iv": atm_iv,
        "skew_25d": round(d25p["iv"] - d25c["iv"], 4) if (d25p and d25c) else None,
        "contracts_total": n_total, "contracts_retained": len(rows),
        "rows": rows,
        "parity": sorted(parity, key=lambda r: r["strike"]),
    }


def build_snapshot(snapshot_date: str, n_expiries: int = N_EXPIRIES,
                    checkpoints: list[str] = CHECKPOINTS) -> dict[str, Any]:
    rf = rf_rate(snapshot_date)  # date-aware -- see bs_solver.rates, ported after this
                                 # project's own flat-RF assumption turned out to be wrong once
    zips = sorted(p for p in DL_DIR.iterdir() if re.match(r"^\d{8}\.zip$", p.name))
    all_expiries = [p.stem for p in zips]
    live = [e for e in all_expiries if e > snapshot_date.replace("-", "")][:n_expiries]
    print(f"snapshot {snapshot_date}  rf={rf}  expiries used: {live}")

    by_time: dict[str, dict[str, Any]] = {t: {"expiries": []} for t in checkpoints}
    for e in live:
        zp = DL_DIR / f"{e}.zip"
        with zipfile.ZipFile(zp) as zf:
            spot_df = load_ts(pd.read_csv(zf.open("nifty_spot.csv"), usecols=["Timestamp", "Close"]))
            legs: dict[tuple[int, str], pd.DataFrame] = {}
            for name in zf.namelist():
                m = LEG_RE.match(Path(name).name)
                if not m or m.group(3) != e:
                    continue
                strike, cp = int(m.group(1)), m.group(2)
                legs[(strike, cp)] = load_ts(pd.read_csv(zf.open(name), usecols=["Timestamp", "Close", "Volume"]))

        n_priced = 0
        for t in checkpoints:
            payload = price_expiry_at(e, spot_df, legs, snapshot_date, t, rf)
            if payload is None:
                print(f"  {e} {t}: no spot print, skipping"); continue
            by_time[t]["expiries"].append(payload)
            n_priced += 1
            print(f"  {e} {t}: dte={payload['dte_days']}d  spot={payload['spot']}  "
                  f"strikes_priced={payload['contracts_retained']}/{payload['contracts_total']}  "
                  f"atm_iv={payload['atm_iv']}")
        if not n_priced:
            print(f"  {e}: priced at no checkpoint, dropping")

    return {
        "snapshot_date": snapshot_date, "risk_free": rf,
        "checkpoints": checkpoints, "by_time": by_time,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--date", default=DEFAULT_SNAPSHOT_DATE, help="snapshot session date, YYYY-MM-DD")
    ap.add_argument("--out", default=str(DEFAULT_OUT), help="output JSON path")
    ap.add_argument("--n-expiries", type=int, default=N_EXPIRIES, help="nearest N live expiries to price")
    args = ap.parse_args()

    payload = build_snapshot(args.date, args.n_expiries)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload))
    print(f"\nwrote {out} ({out.stat().st_size/1024:.1f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
