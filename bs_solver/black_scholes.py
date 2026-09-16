"""Black-Scholes pricing, implied volatility, and the Greeks.

Extracted from a NIFTY options research pipeline (originally lib/bs.py in
that project, where IV and delta were computed from the entry-time option
price, entry-time spot, and entry-time time-to-expiry -- never a later
intraday snapshot). Standalone here: no pandas, no numpy, stdlib only.

cp is "CE" for a call, "PE" for a put -- kept from the source project's
convention (Zerodha's own naming for call/put option instruments).
"""
from __future__ import annotations

import math
from datetime import date, datetime
from typing import Literal, Optional, Union

CP = Literal["CE", "PE"]
DateLike = Union[str, date, datetime]

RF = 0.065   # default risk-free rate -- matches India's RBI repo rate Feb 2023 to Feb 2025,
             # NOT after: 6.25% from 2025-02-07, 6.00% from 2025-04-09, 5.50% from 2025-06-06
             # (confirmed against RBI/PIB press releases). Always pass r explicitly for a date
             # after 2025-02-07 -- this default is a fallback for the un-cut period, not "today".
YEAR = 365.0


def _nd(x: float) -> float:
    """Standard normal CDF."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _npdf(x: float) -> float:
    """Standard normal PDF."""
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def _d1_d2(S: float, K: float, T: float, sigma: float, r: float) -> tuple[float, float]:
    d1 = (math.log(S / K) + (r + 0.5 * sigma * sigma) * T) / (sigma * math.sqrt(T))
    return d1, d1 - sigma * math.sqrt(T)


def price(S: float, K: float, T: float, sigma: float, cp: CP, r: float = RF) -> float:
    """Option price. At T<=0 or sigma<=0, falls back to intrinsic value."""
    if T <= 0 or sigma <= 0:
        return max(0.0, S - K) if cp == "CE" else max(0.0, K - S)
    d1, d2 = _d1_d2(S, K, T, sigma, r)
    if cp == "CE":
        return S * _nd(d1) - K * math.exp(-r * T) * _nd(d2)
    return K * math.exp(-r * T) * _nd(-d2) - S * _nd(-d1)


def implied_vol(option_price: float, S: float, K: float, T: float, cp: CP, r: float = RF,
                 lo: float = 0.005, hi: float = 4.0, tol: float = 1e-5,
                 iters: int = 80) -> Optional[float]:
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


def delta(S: float, K: float, T: float, sigma: Optional[float], cp: CP, r: float = RF) -> float:
    if T <= 0 or sigma is None or sigma <= 0:
        return (1.0 if S > K else 0.0) if cp == "CE" else (-1.0 if S < K else 0.0)
    d1, _ = _d1_d2(S, K, T, sigma, r)
    return _nd(d1) if cp == "CE" else _nd(d1) - 1.0


def gamma(S: float, K: float, T: float, sigma: float, r: float = RF) -> float:
    """Same for calls and puts. Rate of change of delta per unit of spot."""
    if T <= 0 or sigma <= 0:
        return 0.0
    d1, _ = _d1_d2(S, K, T, sigma, r)
    return _npdf(d1) / (S * sigma * math.sqrt(T))


def vega(S: float, K: float, T: float, sigma: float, r: float = RF) -> float:
    """Same for calls and puts. Per 1.00 (100 vol points) change in sigma --
    divide by 100 for the conventional 'per 1 vol point' quote."""
    if T <= 0 or sigma <= 0:
        return 0.0
    d1, _ = _d1_d2(S, K, T, sigma, r)
    return S * _npdf(d1) * math.sqrt(T)


def theta(S: float, K: float, T: float, sigma: float, cp: CP, r: float = RF) -> float:
    """Per year -- divide by 365 for the conventional 'per day' quote."""
    if T <= 0 or sigma <= 0:
        return 0.0
    d1, d2 = _d1_d2(S, K, T, sigma, r)
    decay = -(S * _npdf(d1) * sigma) / (2 * math.sqrt(T))
    if cp == "CE":
        return decay - r * K * math.exp(-r * T) * _nd(d2)
    return decay + r * K * math.exp(-r * T) * _nd(-d2)


def rho(S: float, K: float, T: float, sigma: float, cp: CP, r: float = RF) -> float:
    """Per 1.00 (100 percentage points) change in the risk-free rate."""
    if T <= 0 or sigma <= 0:
        return 0.0
    _, d2 = _d1_d2(S, K, T, sigma, r)
    if cp == "CE":
        return K * T * math.exp(-r * T) * _nd(d2)
    return -K * T * math.exp(-r * T) * _nd(-d2)


def vanna(S: float, K: float, T: float, sigma: float, r: float = RF) -> float:
    """d(delta)/d(sigma), equivalently d(vega)/dS. Same for calls and puts
    (delta_put = delta_call - 1, a constant shift that vanishes on
    differentiation). Verified against a finite difference of delta() --
    see tests/test_greeks_finite_diff.py.
    """
    if T <= 0 or sigma <= 0:
        return 0.0
    d1, d2 = _d1_d2(S, K, T, sigma, r)
    return -_npdf(d1) * d2 / sigma


def charm(S: float, K: float, T: float, sigma: float, cp: CP, r: float = RF) -> float:
    """d(delta)/d(time elapsed) -- matches theta()'s sign convention (decay
    per unit of calendar time passing, not per unit of time-to-expiry).
    Same value for calls and puts, same reasoning as vanna(). cp is accepted
    for interface symmetry with the other Greeks but doesn't change the
    result.
    """
    if T <= 0 or sigma <= 0:
        return 0.0
    d1, d2 = _d1_d2(S, K, T, sigma, r)
    return -_npdf(d1) * (2 * r * T - d2 * sigma * math.sqrt(T)) / (2 * T * sigma * math.sqrt(T))


def volga(S: float, K: float, T: float, sigma: float, r: float = RF) -> float:
    """d(vega)/d(sigma), a.k.a. vomma. Same for calls and puts."""
    if T <= 0 or sigma <= 0:
        return 0.0
    d1, d2 = _d1_d2(S, K, T, sigma, r)
    return vega(S, K, T, sigma, r) * d1 * d2 / sigma


def years_to_expiry(entry_ts: Union[str, datetime], expiry_date: DateLike,
                     expiry_hour: int = 15, expiry_minute: int = 30) -> float:
    """Year-fraction from entry_ts to expiry_date at expiry_hour:expiry_minute.

    entry_ts: a datetime (needs a time-of-day; a bare date isn't accepted),
    or an ISO-format string parseable by datetime.fromisoformat().
    expiry_date: a date/datetime, or an ISO-format date string ("YYYY-MM-DD")
    -- only the year/month/day are used from it.
    """
    if isinstance(entry_ts, str):
        entry_ts = datetime.fromisoformat(entry_ts)
    if isinstance(expiry_date, str):
        expiry_date = datetime.fromisoformat(expiry_date)
    expiry_dt = datetime(expiry_date.year, expiry_date.month, expiry_date.day,
                          expiry_hour, expiry_minute)
    seconds = max((expiry_dt - entry_ts).total_seconds(), 1e-6)
    return (seconds / 86400.0) / YEAR
