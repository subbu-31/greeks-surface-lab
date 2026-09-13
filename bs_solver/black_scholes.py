"""Black-Scholes pricing, implied volatility, and the Greeks.

Extracted from a NIFTY options research pipeline (originally lib/bs.py in
that project, where IV and delta were computed from the entry-time option
price, entry-time spot, and entry-time time-to-expiry -- never a later
intraday snapshot). Standalone here: no pandas, no numpy, stdlib only.

cp is "CE" for a call, "PE" for a put -- kept from the source project's
convention (Zerodha's own naming for call/put option instruments).
"""
import math
from datetime import datetime, timedelta

RF = 0.065   # default risk-free rate
YEAR = 365.0


def _nd(x):
    """Standard normal CDF."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _npdf(x):
    """Standard normal PDF."""
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def _d1_d2(S, K, T, sigma, r):
    d1 = (math.log(S / K) + (r + 0.5 * sigma * sigma) * T) / (sigma * math.sqrt(T))
    return d1, d1 - sigma * math.sqrt(T)


def price(S, K, T, sigma, cp, r=RF):
    """Option price. At T<=0 or sigma<=0, falls back to intrinsic value."""
    if T <= 0 or sigma <= 0:
        return max(0.0, S - K) if cp == "CE" else max(0.0, K - S)
    d1, d2 = _d1_d2(S, K, T, sigma, r)
    if cp == "CE":
        return S * _nd(d1) - K * math.exp(-r * T) * _nd(d2)
    return K * math.exp(-r * T) * _nd(-d2) - S * _nd(-d1)


def implied_vol(option_price, S, K, T, cp, r=RF, lo=0.005, hi=4.0, tol=1e-5, iters=80):
    """Bisection solve for sigma. Returns None outside the no-arbitrage band.

    Numerically unreliable deep ITM/OTM or very close to expiry: vega -> 0
    there (see vega()), so a wide range of sigma reprices to nearly the same
    option_price and the bisection has little to converge against, even
    though the returned sigma still reprices back to option_price almost
    exactly. Fine for the near-the-money, several-days-to-expiry contracts
    this module is meant for; not a general-purpose IV surface solver.
    """
    if T <= 0 or option_price <= 0:
        return None
    intrinsic = max(0.0, S - K) if cp == "CE" else max(0.0, K - S)
    if option_price < intrinsic - 1e-6:
        return None
    if price(S, K, T, hi, cp, r) < option_price:
        return None
    if price(S, K, T, lo, cp, r) > option_price:
        return None
    for _ in range(iters):
        mid = 0.5 * (lo + hi)
        if price(S, K, T, mid, cp, r) > option_price:
            hi = mid
        else:
            lo = mid
        if hi - lo < tol:
            break
    return 0.5 * (lo + hi)


def delta(S, K, T, sigma, cp, r=RF):
    if T <= 0 or sigma is None or sigma <= 0:
        return (1.0 if S > K else 0.0) if cp == "CE" else (-1.0 if S < K else 0.0)
    d1, _ = _d1_d2(S, K, T, sigma, r)
    return _nd(d1) if cp == "CE" else _nd(d1) - 1.0


def gamma(S, K, T, sigma, r=RF):
    """Same for calls and puts. Rate of change of delta per unit of spot."""
    if T <= 0 or sigma <= 0:
        return 0.0
    d1, _ = _d1_d2(S, K, T, sigma, r)
    return _npdf(d1) / (S * sigma * math.sqrt(T))


def vega(S, K, T, sigma, r=RF):
    """Same for calls and puts. Per 1.00 (100 vol points) change in sigma --
    divide by 100 for the conventional 'per 1 vol point' quote."""
    if T <= 0 or sigma <= 0:
        return 0.0
    d1, _ = _d1_d2(S, K, T, sigma, r)
    return S * _npdf(d1) * math.sqrt(T)


def theta(S, K, T, sigma, cp, r=RF):
    """Per year -- divide by 365 for the conventional 'per day' quote."""
    if T <= 0 or sigma <= 0:
        return 0.0
    d1, d2 = _d1_d2(S, K, T, sigma, r)
    decay = -(S * _npdf(d1) * sigma) / (2 * math.sqrt(T))
    if cp == "CE":
        return decay - r * K * math.exp(-r * T) * _nd(d2)
    return decay + r * K * math.exp(-r * T) * _nd(-d2)


def rho(S, K, T, sigma, cp, r=RF):
    """Per 1.00 (100 percentage points) change in the risk-free rate."""
    if T <= 0 or sigma <= 0:
        return 0.0
    _, d2 = _d1_d2(S, K, T, sigma, r)
    if cp == "CE":
        return K * T * math.exp(-r * T) * _nd(d2)
    return -K * T * math.exp(-r * T) * _nd(-d2)


def years_to_expiry(entry_ts, expiry_date, expiry_hour=15, expiry_minute=30):
    """Year-fraction from entry_ts to expiry_date at expiry_hour:expiry_minute.

    entry_ts: a datetime, or anything datetime.fromisoformat() accepts.
    expiry_date: a date/datetime, or an ISO-format date string ("YYYY-MM-DD").
    """
    if isinstance(entry_ts, str):
        entry_ts = datetime.fromisoformat(entry_ts)
    if isinstance(expiry_date, str):
        expiry_date = datetime.fromisoformat(expiry_date)
    expiry_dt = datetime(expiry_date.year, expiry_date.month, expiry_date.day,
                          expiry_hour, expiry_minute)
    seconds = max((expiry_dt - entry_ts).total_seconds(), 1e-6)
    return (seconds / 86400.0) / YEAR
