#!/usr/bin/env python3
"""
build_snapshot_series.py -- Unlike build_market_snapshot.py (one chain, one
timestamp), this pulls several real strikes' real prices at the same
intraday time across several consecutive real trading days, so the
attribution engine has genuine before/after snapshots to run structures
(straddle, strangle, iron condor) against instead of a synthetic scenario.

Reads DL_DIR the same way the source research pipeline did:
  <DL_DIR>/<expiry YYYYMMDD>.zip containing
    nifty_spot.csv                        1-min NIFTY 50 bars
    {strike}{CE|PE}_{expiry}.csv          1-min option bars

Each option CSV spans roughly the three weeks up to its own expiry, so one
archive is enough to sample several real days for one set of strikes.
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
LIQUID_MIN_VOLUME = 50         # contracts traded in the print actually used -- same bar as build_market_snapshot.py
MAX_STALENESS_MIN = 3          # same cap the source research pipeline uses for entry-time option marks.
                                # Tried widening to 20min while chasing an earlier window: it gained
                                # nothing further, because the leg that blocks each earlier day keeps
                                # rotating (the ATM put on some days, the OTM wings on others) rather
                                # than being one fixable bottleneck -- see the README note on this.

# Strike offsets (index points) from day-0 spot, snapped to the nearest
# strike actually listed. short_* are the strangle/condor's sold legs;
# long_* are the condor's further-OTM wings.
#
# Originally 300/600. Checked (not assumed) against daily traded volume for
# every candidate strike across its full life: at 300/600 the wings had no
# real liquidity -- often literally zero volume -- until ~9 days before
# expiry, which silently forced the "earliest 5 valid days" walk-forward
# below to land in the terminal week no matter how far back the candidate
# date window reached. At 150/300 every leg clears real daily volume
# (thousands to tens of thousands of contracts) by roughly three weeks out,
# which is what actually lets the sample reach a higher-DTE, higher-vega
# window instead of always the terminal one.
OFFSETS = {"atm": 0, "short_call": 150, "short_put": -150, "long_call": 300, "long_put": -300}
SIDE_FOR = {"atm": None, "short_call": "CE", "short_put": "PE", "long_call": "CE", "long_put": "PE"}


def nearest_prior_print(df, ts_col, date, time_, max_staleness_min, require_volume):
    """The most recent bar at or before `time_` on `date`, within
    max_staleness_min -- not an exact-timestamp match. A round-numbered
    entry time (09:45:00) landing exactly on a printed 1-minute bar is a
    coincidence, not something to require: on this dataset, the ATM put
    used for the straddle had zero trades in the literal 09:45:00 bar on
    five consecutive early days despite trading a few thousand contracts
    that same day, which silently blocked every one of those days from
    ever being sampled. Real point-in-time systems use "most recent tick
    within a staleness bound," which is also the exact convention the
    source research pipeline (donchian-option-overlay) already uses for
    entry-time option marks -- reused here rather than invented fresh.
    """
    target = pd.Timestamp(f"{date} {time_}")
    lo = target - pd.Timedelta(minutes=max_staleness_min)
    window = df[(df[ts_col] <= target) & (df[ts_col] >= lo)]
    if require_volume:
        window = window[window["Volume"] > 0]
    if not len(window):
        return None, None
    row = window.loc[window[ts_col].idxmax()]
    volume = int(row["Volume"]) if "Volume" in row else None
    return float(row["Close"]), volume


def years_to_expiry(date, time_, expiry_yyyymmdd):
    entry = pd.Timestamp(f"{date} {time_}")
    exp = pd.Timestamp(f"{expiry_yyyymmdd[:4]}-{expiry_yyyymmdd[4:6]}-{expiry_yyyymmdd[6:]} 15:30:00")
    return max((exp - entry).total_seconds(), 1e-6) / 86400.0 / 365.0


def load_leg_csv(zf, strike, cp):
    df = pd.read_csv(zf.open(f"{strike}{cp}_{SNAPSHOT_EXPIRY}.csv"), usecols=["Timestamp", "Close", "Volume"])
    df["ts"] = pd.to_datetime(df["Timestamp"], format="%d-%m-%Y %H:%M:%S", errors="coerce")
    return df


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

        s_guess, _ = nearest_prior_print(spot, "ts", candidates[0], ENTRY_TIME, MAX_STALENESS_MIN, require_volume=False)
        available = sorted({int(m.group(1)) for n in zf.namelist() if (m := LEG_RE.match(Path(n).name))})

        strikes = {}
        for name, offset in OFFSETS.items():
            strikes[name] = min(available, key=lambda k: abs(k - (s_guess + offset)))
        print(f"expiry {SNAPSHOT_EXPIRY}, spot {s_guess} on {candidates[0]}, strikes: {strikes}")

        legs_df = {}
        for name, strike in strikes.items():
            if name == "atm":
                legs_df["atm_ce"] = load_leg_csv(zf, strike, "CE")
                legs_df["atm_pe"] = load_leg_csv(zf, strike, "PE")
            else:
                legs_df[name] = load_leg_csv(zf, strike, SIDE_FOR[name])

        leg_strike = {"atm_ce": strikes["atm"], "atm_pe": strikes["atm"],
                      "short_call": strikes["short_call"], "short_put": strikes["short_put"],
                      "long_call": strikes["long_call"], "long_put": strikes["long_put"]}
        leg_cp = {"atm_ce": "CE", "atm_pe": "PE", "short_call": "CE", "short_put": "PE",
                  "long_call": "CE", "long_put": "PE"}

        samples = []
        for d in candidates:
            if len(samples) >= N_SAMPLE_DAYS:
                break
            S, _ = nearest_prior_print(spot, "ts", d, ENTRY_TIME, MAX_STALENESS_MIN, require_volume=False)
            if S is None:
                print(f"  {d}: no spot print within {MAX_STALENESS_MIN}min of {ENTRY_TIME}, skipping"); continue
            T = years_to_expiry(d, ENTRY_TIME, SNAPSHOT_EXPIRY)

            legs_out, ok = {}, True
            for name, df in legs_df.items():
                close, volume = nearest_prior_print(df, "ts", d, ENTRY_TIME, MAX_STALENESS_MIN, require_volume=True)
                if close is None:
                    ok = False; break
                iv = implied_vol(close, S, leg_strike[name], T, leg_cp[name], RF)
                if iv is None:
                    ok = False; break
                legs_out[name] = {"close": close, "iv": round(iv, 4), "volume": volume,
                                   "liquid": volume >= LIQUID_MIN_VOLUME}
            if not ok:
                print(f"  {d}: missing a real print or IV solve failed on one leg, skipping"); continue

            samples.append({"date": d, "time": ENTRY_TIME, "spot": S, "dte_days": round(T * 365, 3),
                             "legs": legs_out})
            illiquid = [k for k, v in legs_out.items() if not v["liquid"]]
            flag = f"  ILLIQUID: {illiquid}" if illiquid else ""
            print(f"  {d}: spot={S}  dte={round(T*365,2)}d  " +
                  "  ".join(f"{k}_iv={v['iv']}(vol={v['volume']})" for k, v in legs_out.items()) + flag)

    payload = {"expiry": SNAPSHOT_EXPIRY, "strikes": strikes, "risk_free": RF,
               "entry_time": ENTRY_TIME, "liquid_min_volume": LIQUID_MIN_VOLUME, "samples": samples}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=1))
    print(f"\nwrote {OUT} ({len(samples)} real daily snapshots)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
