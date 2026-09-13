# Greeks Surface Lab

A standalone, dependency-free Black-Scholes solver, a Greek-based P&L
attribution engine built on top of it, and two 3D-first ways to look at
the solver itself: a closed-form Greeks explorer you drive with sliders,
and a real NIFTY option-chain snapshot with an IV smile, term structure,
skew, Greeks-by-strike, and put-call-parity view.

Every formula has been cross-checked against finite-difference derivatives
of the pricer itself (delta/gamma/vega/theta/rho all agree to 10⁻⁶-10⁻¹¹),
against put-call parity, and against an independent JS reimplementation
used by the web page -- see `tests/`.

## Layout

- `bs_solver/black_scholes.py` -- price, implied vol (bisection), delta,
  gamma, vega, theta, rho. Stdlib only, no pandas/numpy. Originally
  extracted from a NIFTY options research pipeline's `lib/bs.py`; this
  repo now has no dependency on that project.
- `bs_solver/attribution.py` -- the Greek attribution engine: given an
  option's (or a book's) parameters at two points in time, decomposes the
  actual price change into delta/gamma/vega/theta/rho contributions plus
  a residual for whatever the Taylor expansion doesn't capture (vanna,
  charm, and other higher-order/cross terms). `attribute_leg` does one
  option; `attribute_portfolio` sums a list of legs and reports what
  fraction of the book's P&L the five Greek terms explain.
- `tests/test_black_scholes.py` -- put-call parity, boundary behaviour, an
  IV round-trip, and sign/bound checks on each Greek.
- `tests/test_attribution.py` -- checks the attribution sums back to the
  actual reprice, that a pure time-decay move is explained entirely by
  theta, that a short leg's P&L is the exact negative of the long leg's,
  and that a portfolio's total is the sum of its legs.
- `tests/test_js_parity.py` -- shells out to `node` to run the same random
  grid of (S, K, T, sigma, r, cp) through `web/explorer.js`'s BS object and
  checks it against `black_scholes.py` to within the JS erf approximation's
  own error bound. Requires `node` on PATH.
- `scripts/build_market_snapshot.py` -- one-off data-prep script. Pulls a
  real trading day's option chain across several live expiries out of the
  raw Zerodha weekly archives, prices every strike with `bs_solver`, and
  writes `web/data/market_snapshot.json`. Needs `DL_DIR` pointing at a
  local copy of the archives to re-run; not needed just to use the solver.
- `scripts/build_snapshot_series.py` -- pulls the *same* strike's real
  price at a fixed intraday time across several consecutive real trading
  days (one option contract's own CSV spans about three weeks), and writes
  `web/data/snapshot_series.json`. This is what makes the attribution demo
  below run on genuine consecutive market data instead of a synthetic
  scenario.
- `scripts/attribute_pnl.py` -- runs the attribution engine across every
  consecutive pair of real daily snapshots in `snapshot_series.json` and
  prints a day-by-day Greek breakdown of the straddle's actual P&L, plus a
  running total.
- `web/index.html` + `explorer.js` + `market.js` -- the two-tab page.
  `explorer.js` reimplements the same Black-Scholes formulas in JS (kept
  in sync with `black_scholes.py` by hand and checked by
  `tests/test_js_parity.py`, since a static page can't call Python at
  runtime); `market.js` reads the prebuilt JSON.

## Installing

```
pip install .                    # solver + attribution engine only, zero dependencies
pip install ".[snapshot-tools]"  # + pandas, needed only to rebuild web/data/*.json
```

## Running it

```
python3 tests/test_black_scholes.py      # sanity-check the solver
python3 tests/test_attribution.py        # sanity-check the attribution engine
python3 tests/test_js_parity.py          # cross-check explorer.js against the Python solver
python3 scripts/attribute_pnl.py         # Greek P&L attribution over 5 real consecutive trading days
python3 -m http.server 8000 -d web       # serve the page (fetch() needs http://, not file://)
```
Then open `http://localhost:8000`.

To rebuild the market snapshot or the attribution series against a
different date/expiry, edit the constants at the top of
`scripts/build_market_snapshot.py` / `scripts/build_snapshot_series.py`
and re-run with `DL_DIR` set to your local copy of the archives.

## What's real and what isn't

- **Solver Explorer** tab: purely synthetic. You pick the axes and fixed
  parameters; every surface is the closed-form solver evaluated on a grid.
- **Real NIFTY Snapshot** tab: real 1-minute option prices from one
  session (see the date in the page header), IV backed out per strike,
  Greeks computed from that IV. The dataset has OHLCV + open interest but
  **no bid/ask**, so:
  - the "liquidity" panel uses traded volume as a proxy, not a real quoted spread;
  - the parity residual uses the traded CE/PE close, not a mid-price, so
    some of its drift is discretization noise, not real mispricing.
  - only 4 expiries were live that day, so the IV-by-expiry view is a
    heatmap (moneyness x expiry) rather than a continuous 3D surface --
    a fine mesh across 4 discrete expiries would just be interpolation
    dressed up as resolution the data doesn't have.
- Both tabs use `RF = 0.065` as the risk-free rate; the market snapshot
  doesn't account for dividends/carry, and treats Black-Scholes as an
  implied-vol quoting convention rather than a literal pricing claim --
  standard practice for short-dated index options, where jumps and
  discrete hedging dominate anyway.
- **`scripts/attribute_pnl.py`**: every number in it is real -- real spot,
  real traded option prices, real implied vols, across five genuine
  consecutive trading days for one fixed strike. The only thing to note is
  scope: it's one contract's path through one particular week, not a
  claim about attribution accuracy in general.
