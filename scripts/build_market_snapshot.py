#!/usr/bin/env python3
"""
build_market_snapshot.py -- Pull one real trading day's option chain across
several live expiries from the raw Zerodha weekly archives, price every
strike with bs_solver, and dump a compact JSON payload for the web dashboard.

This is a one-off data-prep script (not part of the bs_solver package). It
reads DL_DIR the same way the source research pipeline did:
  <DL_DIR>/<expiry YYYYMMDD>.zip containing
    nifty_spot.csv                        1-min NIFTY 50 bars
    {strike}{CE|PE}_{expiry}.csv          1-min option bars

No bid/ask in this data -- only OHLCV + OI on the traded price -- so the
"liquidity" flag is a volume threshold on that single traded minute, not a
real quoted spread, and the parity check uses the traded CE/PE close, not
a mid.

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
import re
import sys
import zipfile
from pathlib import Path
from typing import Any, Optional

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bs_solver import implied_vol, delta, gamma, vega, theta, rf_rate

DL_DIR = Path("/Users/ramasamysadacharam/Desktop/nifty options data")
DEFAULT_OUT = Path(__file__).resolve().parents[1] / "web" / "data" / "market_snapshot.json"
LEG_RE = re.compile(r"^(\d+)(CE|PE)_(\d{8})\.csv$")
ENTRY_TIME = "09:45:00"

DEFAULT_SNAPSHOT_DATE = "2024-12-27"  # the same real day scripts/build_snapshot_series.py's
                                       # attribution demo starts from -- unified so the dashboard's
                                       # smile/skew/term-structure and the attribution engine's Greek
                                       # breakdown describe the same market, not two unrelated weeks
N_EXPIRIES = 4                        # nearest N weekly expiries live that day
LIQUID_MIN_VOLUME = 50                # contracts traded in that single 1-min bar
PARITY_TOL_PTS = 15.0                 # |residual| beyond this is flagged, not "arbitrage"


def read_spot_close_at(zf: zipfile.ZipFile, date: str, time_: str) -> Optional[float]:
    df = pd.read_csv(zf.open("nifty_spot.csv"), usecols=["Timestamp", "Close"])
    df["ts"] = pd.to_datetime(df["Timestamp"], format="%d-%m-%Y %H:%M:%S", errors="coerce")
    hit = df[(df["ts"].dt.strftime("%Y-%m-%d") == date) & (df["ts"].dt.strftime("%H:%M:%S") == time_)]
    return float(hit["Close"].iloc[0]) if len(hit) else None


def read_chain_at(zf: zipfile.ZipFile, expiry: str, date: str, time_: str) -> dict[tuple[int, str], dict[str, Any]]:
    """{(strike, cp): close} for every leg that traded at exactly this minute."""
    out: dict[tuple[int, str], dict[str, Any]] = {}
    for name in zf.namelist():
        m = LEG_RE.match(Path(name).name)
        if not m or m.group(3) != expiry:
            continue
        strike, cp = int(m.group(1)), m.group(2)
        df = pd.read_csv(zf.open(name), usecols=["Timestamp", "Close", "Volume"])
        df["ts"] = pd.to_datetime(df["Timestamp"], format="%d-%m-%Y %H:%M:%S", errors="coerce")
        hit = df[(df["ts"].dt.strftime("%Y-%m-%d") == date) & (df["ts"].dt.strftime("%H:%M:%S") == time_)]
        if len(hit) and hit["Volume"].iloc[0] > 0 and hit["Close"].iloc[0] > 0.5:
            out[(strike, cp)] = {"close": float(hit["Close"].iloc[0]), "volume": int(hit["Volume"].iloc[0])}
    return out


def years_to_expiry(date: str, time_: str, expiry_yyyymmdd: str) -> float:
    entry = pd.Timestamp(f"{date} {time_}")
    exp = pd.Timestamp(f"{expiry_yyyymmdd[:4]}-{expiry_yyyymmdd[4:6]}-{expiry_yyyymmdd[6:]} 15:30:00")
    return max((exp - entry).total_seconds(), 1e-6) / 86400.0 / 365.0


def nearest_by_delta(rows: list[dict[str, Any]], target_abs_delta: float, cp: str) -> Optional[dict[str, Any]]:
    cand = [r for r in rows if r["cp"] == cp and r["delta"] is not None]
    if not cand:
        return None
    return min(cand, key=lambda r: abs(abs(r["delta"]) - target_abs_delta))


def build_snapshot(snapshot_date: str, n_expiries: int = N_EXPIRIES) -> dict[str, Any]:
    rf = rf_rate(snapshot_date)  # date-aware -- see bs_solver.rates, ported after this
                                 # project's own flat-RF assumption turned out to be wrong once
    zips = sorted(p for p in DL_DIR.iterdir() if re.match(r"^\d{8}\.zip$", p.name))
    all_expiries = [p.stem for p in zips]
    live = [e for e in all_expiries if e > snapshot_date.replace("-", "")][:n_expiries]
    print(f"snapshot {snapshot_date}  rf={rf}  expiries used: {live}")

    expiries_payload = []
    for e in live:
        zp = DL_DIR / f"{e}.zip"
        with zipfile.ZipFile(zp) as zf:
            S = read_spot_close_at(zf, snapshot_date, ENTRY_TIME)
            if S is None:
                print(f"  {e}: no spot at {ENTRY_TIME}, skipping"); continue
            chain = read_chain_at(zf, e, snapshot_date, ENTRY_TIME)
            if not chain:
                print(f"  {e}: no legs traded at {ENTRY_TIME}, skipping"); continue
        T = years_to_expiry(snapshot_date, ENTRY_TIME, e)
        dte_days = round(T * 365, 2)

        rows = []
        for (strike, cp), q in chain.items():
            iv = implied_vol(q["close"], S, strike, T, cp, rf)
            if iv is None or not (0.02 < iv < 3.0):
                continue
            d = delta(S, strike, T, iv, cp, rf)
            g = gamma(S, strike, T, iv, rf)
            v = vega(S, strike, T, iv, rf)
            th = theta(S, strike, T, iv, cp, rf)
            rows.append({
                "strike": strike, "cp": cp, "close": q["close"], "volume": q["volume"],
                "moneyness": round(strike / S, 4), "iv": round(iv, 4),
                "delta": round(d, 4), "gamma": round(g, 6), "vega": round(v, 3),
                "theta_per_day": round(th / 365.0, 3),
                "liquid": q["volume"] >= LIQUID_MIN_VOLUME,
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
        for k, legs in by_strike.items():
            if "CE" in legs and "PE" in legs:
                residual = (legs["CE"]["close"] - legs["PE"]["close"]
                            + k * math.exp(-rf * T) - S)
                parity.append({
                    "strike": k, "residual": round(residual, 2),
                    "ce_vol": legs["CE"]["volume"], "pe_vol": legs["PE"]["volume"],
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

        expiries_payload.append({
            "expiry": e, "dte_days": dte_days, "spot": S,
            "atm_iv": atm_iv,
            "skew_25d": round(d25p["iv"] - d25c["iv"], 4) if (d25p and d25c) else None,
            "contracts_total": len(chain), "contracts_retained": len(rows),
            "rows": rows,
            "parity": sorted(parity, key=lambda r: r["strike"]),
        })
        print(f"  {e}: dte={dte_days}d  spot={S}  strikes_priced={len(rows)}/{len(chain)}  atm_iv={atm_iv}")

    return {
        "snapshot_date": snapshot_date, "entry_time": ENTRY_TIME, "risk_free": rf,
        "expiries": expiries_payload,
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
