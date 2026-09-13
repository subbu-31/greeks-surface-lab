#!/usr/bin/env python3
"""
build_snapshot_series.py -- Unlike build_market_snapshot.py (one chain, one
timestamp), this pulls the SAME strike's real price at the same intraday
time across several consecutive real trading days, so the attribution
engine has genuine before/after snapshots to run on instead of a
synthetic scenario.

Reads DL_DIR the same way the source research pipeline did:
  <DL_DIR>/<expiry YYYYMMDD>.zip containing
    nifty_spot.csv                        1-min NIFTY 50 bars
    {strike}{CE|PE}_{expiry}.csv          1-min option bars

Each option CSV spans roughly the three weeks up to its own expiry, so one
archive is enough to sample several real days for one contract.
"""
import json
import re
import sys
import zipfile
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bs_solver import implied_vol

DL_DIR = Path("/Users/ramasamysadacharam/Desktop/nifty options data")
OUT = Path(__file__).resolve().parents[1] / "web" / "data" / "snapshot_series.json"
LEG_RE = re.compile(r"^(\d+)(CE|PE)_(\d{8})\.csv$")
ENTRY_TIME = "09:45:00"
RF = 0.065

SNAPSHOT_EXPIRY = "20250109"   # a representative mid-sample weekly expiry
N_SAMPLE_DAYS = 5              # last N trading days before this expiry


def read_close_at(df, ts_col, date, time_, value_col="Close"):
    hit = df[(df[ts_col].dt.strftime("%Y-%m-%d") == date) & (df[ts_col].dt.strftime("%H:%M:%S") == time_)]
    return float(hit[value_col].iloc[0]) if len(hit) else None


def years_to_expiry(date, time_, expiry_yyyymmdd):
    entry = pd.Timestamp(f"{date} {time_}")
    exp = pd.Timestamp(f"{expiry_yyyymmdd[:4]}-{expiry_yyyymmdd[4:6]}-{expiry_yyyymmdd[6:]} 15:30:00")
    return max((exp - entry).total_seconds(), 1e-6) / 86400.0 / 365.0


def main():
    zp = DL_DIR / f"{SNAPSHOT_EXPIRY}.zip"
    expiry_date = f"{SNAPSHOT_EXPIRY[:4]}-{SNAPSHOT_EXPIRY[4:6]}-{SNAPSHOT_EXPIRY[6:]}"
    with zipfile.ZipFile(zp) as zf:
        spot = pd.read_csv(zf.open("nifty_spot.csv"), usecols=["Timestamp", "Close"])
        spot["ts"] = pd.to_datetime(spot["Timestamp"], format="%d-%m-%Y %H:%M:%S", errors="coerce")

        # Candidate trading dates: the real calendar, taken from the spot
        # series (which has full daily coverage), restricted to the run-up
        # to this expiry. A single option leg's own CSV is not a reliable
        # source of "which days had a session" -- a far-OTM strike can have
        # almost no trading history even in a week the market was open.
        spot_dates = sorted(spot[spot["ts"].dt.strftime("%Y-%m-%d") <= expiry_date]["ts"].dt.strftime("%Y-%m-%d").unique())
        candidates = spot_dates[-(N_SAMPLE_DAYS * 3):]

        s_guess = read_close_at(spot, "ts", candidates[0], ENTRY_TIME)
        strikes = sorted({int(m.group(1)) for n in zf.namelist() if (m := LEG_RE.match(Path(n).name))})
        atm_strike = min(strikes, key=lambda k: abs(k - s_guess))
        print(f"expiry {SNAPSHOT_EXPIRY}, atm strike {atm_strike} (spot {s_guess} on {candidates[0]})")

        ce_df = pd.read_csv(zf.open(f"{atm_strike}CE_{SNAPSHOT_EXPIRY}.csv"), usecols=["Timestamp", "Close", "Volume"])
        ce_df["ts"] = pd.to_datetime(ce_df["Timestamp"], format="%d-%m-%Y %H:%M:%S", errors="coerce")
        pe_df = pd.read_csv(zf.open(f"{atm_strike}PE_{SNAPSHOT_EXPIRY}.csv"), usecols=["Timestamp", "Close", "Volume"])
        pe_df["ts"] = pd.to_datetime(pe_df["Timestamp"], format="%d-%m-%Y %H:%M:%S", errors="coerce")

        samples = []
        for d in candidates:
            if len(samples) >= N_SAMPLE_DAYS:
                break
            S = read_close_at(spot, "ts", d, ENTRY_TIME)
            ce_close = read_close_at(ce_df, "ts", d, ENTRY_TIME)
            pe_close = read_close_at(pe_df, "ts", d, ENTRY_TIME)
            if S is None or ce_close is None or pe_close is None:
                print(f"  {d}: missing a real print at {ENTRY_TIME}, skipping"); continue
            T = years_to_expiry(d, ENTRY_TIME, SNAPSHOT_EXPIRY)
            ce_iv = implied_vol(ce_close, S, atm_strike, T, "CE", RF)
            pe_iv = implied_vol(pe_close, S, atm_strike, T, "PE", RF)
            if ce_iv is None or pe_iv is None:
                print(f"  {d}: IV solve failed, skipping"); continue
            samples.append({
                "date": d, "time": ENTRY_TIME, "spot": S, "dte_days": round(T * 365, 3),
                "ce": {"close": ce_close, "iv": round(ce_iv, 4)},
                "pe": {"close": pe_close, "iv": round(pe_iv, 4)},
            })
            print(f"  {d}: spot={S}  dte={round(T*365,2)}d  ce_iv={round(ce_iv,4)}  pe_iv={round(pe_iv,4)}")

    payload = {"expiry": SNAPSHOT_EXPIRY, "atm_strike": atm_strike, "risk_free": RF,
               "entry_time": ENTRY_TIME, "samples": samples}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=1))
    print(f"\nwrote {OUT} ({len(samples)} real daily snapshots)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
