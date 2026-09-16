# Greeks Surface Lab

[![CI](https://github.com/subbu-31/greeks-surface-lab/actions/workflows/ci.yml/badge.svg)](https://github.com/subbu-31/greeks-surface-lab/actions/workflows/ci.yml)

A standalone, dependency-free Black-Scholes solver, a Greek-based P&L
attribution engine built on top of it, and two 3D-first ways to look at
the solver itself: a closed-form Greeks explorer you drive with sliders,
and a real NIFTY option-chain snapshot with an IV smile, term structure,
skew, Greeks-by-strike, and put-call-parity view.

Every formula has been cross-checked against finite-difference derivatives
of the pricer itself -- not as a one-off, but as a permanent test
(`tests/test_greeks_finite_diff.py`) covering delta, gamma, vega, theta,
rho, and the three second-order Greeks (vanna, charm, volga) the
attribution engine uses, all agreeing to 10⁻⁴-10⁻¹¹ -- plus put-call
parity and an independent JS reimplementation used by the web page.

## Layout

- `bs_solver/black_scholes.py` -- price, implied vol (bisection), delta,
  gamma, vega, theta, rho, vanna, charm, volga. Stdlib only, no
  pandas/numpy, fully typed (`mypy --strict` clean). The first-order Greeks
  were originally extracted from a NIFTY options research pipeline's
  `lib/bs.py`; this repo has no dependency on that project.
- `bs_solver/attribution.py` -- the Greek attribution engine: given an
  option's (or a book's) parameters at two points in time, decomposes the
  actual price change into eight Greek contributions -- delta, gamma,
  vega, theta, rho, and the second-order cross terms volga (d(vega)/dsigma),
  vanna (dS*dsigma), and charm (dS*dt) -- plus a residual for whatever's
  still left (third-order and higher terms, and cross terms with rho,
  usually negligible for short-dated equity index options).
  `attribute_leg` does one option; `attribute_portfolio` sums a list of
  legs held over the *same* period and reports what fraction of the book's
  P&L the eight terms explain. Its docstring carries a specific warning,
  below, about a real bug this repo shipped and then caught.
- `bs_solver/rates.py` -- `rf_rate(on)`, a date-aware risk-free rate
  verified against RBI/PIB press releases, ported in from a sibling
  research pipeline after the exact same bug (a flat rate constant used,
  unchecked, across a sample that saw several real rate changes) turned up
  here too -- see "the assumption behind rho was wrong" below.
- `tests/test_black_scholes.py` -- put-call parity, boundary behaviour, an
  IV round-trip, and sign/bound checks on each Greek.
- `tests/test_greeks_finite_diff.py` -- every Greek (including vanna/charm/
  volga) checked against a finite difference of the function one order
  below it, across 25 random (S, K, T, sigma, r, cp) points.
- `tests/test_attribution.py` -- checks the attribution sums back to the
  actual reprice, that a pure time-decay move is explained entirely by
  theta, that each second-order term measurably reduces the residual for
  the move it corresponds to, that a short leg's P&L is the exact negative
  of the long leg's, that a portfolio's total is the sum of its legs, and
  a regression test for the netting bug described below.
- `tests/test_js_parity.py` -- shells out to `node` to run the same random
  grid of (S, K, T, sigma, r, cp) through `web/explorer.js`'s BS object and
  checks it against `black_scholes.py` to within the JS erf approximation's
  own error bound. Requires `node` on PATH.
- `tests/test_rates.py` -- checks `rf_rate()` against every RBI/PIB
  decision date it's sourced from, that it treats a `date`/`datetime`/ISO
  string identically, and that its no-date fallback is the *latest* known
  rate, not the oldest.
- `scripts/build_market_snapshot.py` -- one-off data-prep script, now a
  small CLI (`--date`, `--out`, `--n-expiries`) rather than hardcoded
  constants, so it can build more than one session without copy-pasting
  the script (see "two sessions" below). Pulls a real trading day's option
  chain across several live expiries out of the raw Zerodha weekly
  archives, at **seven hourly checkpoints** from 09:15 to 15:15 IST, prices
  every strike (including theta) with `bs_solver` at each checkpoint,
  computes the discounted-strike put-call parity residual and a
  liquidity/parity-validity flag per contract, and writes
  `web/data/market_snapshot.json` by default -- one file holding the whole
  day, keyed by checkpoint (`by_time["09:15:00"].expiries`, etc.), not one
  file per hour. Each checkpoint is matched to the most recent real print
  at or before it within a 3-minute staleness cap, not an exact-minute
  match -- most strikes don't print in every single minute, and an
  exact-match rule would starve every hour but the busiest one. Default
  date is 2024-12-27 -- the same real day `build_snapshot_series.py`
  starts from, so `20250109` shows up as one of its four live expiries
  (see "unified" below). `--date 2026-03-11 --out
  web/data/market_snapshot_2026.json` builds the second, deliberately
  different sample in `web/data/` (see "two sessions" below). Needs
  `DL_DIR` pointing at a local copy of the archives to re-run; not needed
  just to use the solver.
- `scripts/build_snapshot_series.py` -- pulls **six** real strikes (an ATM
  pair, an OTM call/put pair, and a further-OTM wing call/put pair) at a
  fixed intraday time across five consecutive real trading days (one
  option contract's own CSV spans about three weeks), and writes
  `web/data/snapshot_series.json`. This is what lets the attribution demo
  below build a straddle, a strangle, and an iron condor from genuine
  consecutive market data instead of a synthetic scenario. Also records
  each leg's traded volume and a liquidity flag (same 50-lot floor as
  `build_market_snapshot.py`) -- this attribution runs on last-traded
  prices with no bid/ask exactly like the market snapshot does, and was
  originally built without checking that, which is documented below.
- `scripts/attribute_pnl.py` -- runs the attribution engine over the same
  five real days three times, in increasing order of structure complexity:
  a straddle (the two ATM legs), a strangle (the OTM call + put), then an
  iron condor (sell the strangle, buy the wings) -- each printed and
  checked before the next is added, per the project's own development
  order. Every transition's table row also reports the thinnest volume
  behind it, and the summary reruns the fit with any transition that
  leans on a thin leg excluded, so a residual can't quietly be quote
  staleness dressed up as unexplained Greeks.
- `web/index.html` + `explorer.js` + `market.js` -- the two-tab page.
  `explorer.js` reimplements the same Black-Scholes formulas in JS (kept
  in sync with `black_scholes.py` by hand and checked by
  `tests/test_js_parity.py`, since a static page can't call Python at
  runtime). On the Solver Explorer tab, "time to expiry" -- whenever it's a
  fixed parameter rather than the surface's own axis (Spot × Strike, Spot ×
  Volatility) -- can be set two ways via a **Days / Calendar** toggle: a
  plain days slider, or the real dashboard's own **Session**, **Entry
  hour**, and **Expiry** choices (the same two sessions, seven hourly
  checkpoints, and each session's own live expiries), not a free-form
  date/minute picker -- this solver has no live or intra-checkpoint feed
  behind it, so offering arbitrary dates or minute-level entry times would
  imply a precision that doesn't exist. Expiry is marked at 15:30 local
  (matching `bs_solver.rates`' convention), and defaults to the same
  2024-12-27 09:15 -> 2025-01-09 session the Real NIFTY Snapshot tab's
  primary data comes from, so "13.26 days" means the same thing on both
  tabs. Switching Session resets Expiry to that session's own first live
  expiry, the same reconciliation `market.js` does. A combination outside
  the explorer's declared 1-180d range is clamped, not silently misused,
  and the clamp is shown, not hidden. `market.js` reads
  the prebuilt JSON and drives every chart on the Real NIFTY Snapshot tab
  off three linked controls -- **Session**, **Hour**, and **Expiry** -- so
  picking a different hour re-renders the IV smile, term structure/skew,
  IV surface, per-strike Greeks, put-call parity, and traded volume
  together, all against that hour's own real prints, not a separate
  fixed-contract side panel.

## Installing

```
pip install .                    # solver + attribution engine only, zero dependencies
pip install ".[snapshot-tools]"  # + pandas, needed only to rebuild web/data/*.json
pip install ".[dev]"             # + pytest, mypy -- what CI runs, see below
```

`bs_solver` ships a `py.typed` marker (PEP 561) and passes `mypy --strict`
with zero suppressions besides two narrow, commented ones where mypy can't
follow a runtime field-name list against a `TypedDict` -- a known limitation
of the type system, not an unchecked path.

## Running it

```
pytest                                    # full suite (33 tests) via standard tooling
mypy                                      # strict type check, zero dependencies beyond the stdlib types
python3 tests/test_black_scholes.py       # any test file also runs standalone, no pytest required
python3 tests/test_greeks_finite_diff.py  # every Greek against a finite difference of the one before it
python3 tests/test_attribution.py         # sanity-check the attribution engine
python3 tests/test_js_parity.py           # cross-check explorer.js against the Python solver
python3 scripts/attribute_pnl.py          # straddle, then strangle, then iron condor, on 5 real days
python3 -m http.server 8000 -d web        # serve the page (fetch() needs http://, not file://)
```
Then open `http://localhost:8000` and use the **Session** selector on the
Real NIFTY Snapshot tab to switch between the two prebuilt sessions (see
"two sessions" below), and the **Hour** selector next to it to step through
that session's own trading day -- every chart on the tab re-renders against
the selected hour's real prints. CI (`.github/workflows/ci.yml`) runs `mypy` and
`pytest` on every push, across Python 3.9-3.12.

To rebuild the market snapshot against a different date, `DL_DIR=... python3
scripts/build_market_snapshot.py --date YYYY-MM-DD --out web/data/whatever.json`
(add its path to the `sessionSelect` options in `web/index.html` to see it
in the dashboard). The attribution series' date/expiry/strike-offset
constants are still at the top of `scripts/build_snapshot_series.py`.

## A real bug found while building this

Adding vanna, charm, and volga (the three second-order Greeks) to
`attribute_leg` and then rolling the daily results up across the 5-day
window with `sum(residual) / sum(actual)` produced a nonsensical result:
the straddle's headline "% explained" swung from roughly 92% (before the
new terms) to roughly 64% (after), as if three more, individually
finite-difference-verified Greek terms had made the fit *worse*.

They hadn't. Per-day, each term reduced its corresponding residual exactly
as expected (see `tests/test_attribution.py`'s cross-term tests). The
"% explained" number was the bug: netting *signed* residuals across four
independent day-to-day transitions lets one day's positive residual cancel
another day's negative one, so the ratio reflects how the week's residuals
happened to line up in sign, not how well the Greeks fit any given day.
The original ~92% figure was itself partly a product of favourable
cancellation, not a clean measurement -- adding the new terms happened to
disturb that cancellation, which read as "worse" while the actual day-by-day
fit had modestly improved (~93.1% to ~93.3%, measured correctly).

The fix, now in `scripts/attribute_pnl.py`, is to aggregate with
`sum(|residual_i|) / sum(|actual_i|)` -- each day scored on its own,
immune to cross-day cancellation. `attribute_portfolio`'s own netting
(across legs held *simultaneously*, not across time) is legitimate and
unchanged; its docstring now says explicitly why that case differs from
this one, and `test_netting_signed_residuals_across_independent_periods_is_misleading`
locks the distinction in as a regression test.

## The sample window never reached a genuinely mid-life, high-vega regime -- and mostly can't

The first version of `build_snapshot_series.py` always landed on the same
kind of window no matter which real expiry it was pointed at: roughly
6-16 days to expiry, every time. That's not a coincidence to wave away --
near expiry, gamma and theta dominate a NIFTY weekly's P&L and vega (and
by extension vanna/volga, which scale off vega) matters comparatively
little, so the whole vanna/charm/volga build-out had only ever been
exercised where it has the least to explain.

Two real, evidenced causes, not one:

1. **The far-OTM wings (originally +-300/+-600 points) had essentially no
   trading volume until roughly the final nine days of life.** Checked
   directly against daily traded volume per strike, not assumed. Tightening
   to +-150/+-300 -- picked because the data showed real, thousands-of-
   contracts liquidity by ~three weeks out at that distance, not picked to
   hit a target DTE -- fixed this part.
2. **The ATM put specifically has zero trades in the literal 09:45:00
   1-minute bar on five consecutive early days**, despite trading a few
   thousand contracts that same day at other times. Requiring an exact
   timestamp match (the original implementation) silently discarded every
   one of those days. Replaced with "most recent print at or before 09:45,
   within a 3-minute staleness cap" -- the same convention the source
   research pipeline already uses for entry-time option marks, reused
   rather than invented.

Both fixes are real and both are now in the code. The combined result:
the reachable window moved from 13.24d-7.24d to **14.24d-8.24d** -- one
extra day, not the jump to 25-30 DTE a "mid-life" fix might imply. Chasing
it further (tried widening the staleness cap to 20 minutes) gained
nothing more, because the leg that blocks each earlier candidate day
keeps rotating -- the ATM put on some days, the OTM wings on others --
rather than being one fixable bottleneck. Checked directly: on
2024-12-20, the ATM put clears a 20-minute window fine, but the wings
still don't print at all until 09:56 and later. This is not a
code limitation to fix with a bigger timeout; it's the actual liquidity
shape of a NIFTY weekly contract, which ramps roughly exponentially into
its final week regardless of how the entry time or staleness tolerance is
tuned. A genuinely liquid 25-30 DTE window for a 6-leg structure like this
one may not exist in this instrument class at all -- reaching it would
more plausibly need a monthly-expiry contract (not in this dataset) or
accepting materially worse liquidity than anything else in this project
tolerates.

## rho was never once tested with a real rate change -- and the assumption behind it was actually wrong

`attribute_leg`'s `r1` defaults to `r0`, and until now nothing anywhere in
this project -- no script, no test -- ever called it with a different
value. `rho_pnl` was structurally `0.0` in every single number this
project had ever reported, dressed up as an "eight-Greek ladder."

Checked what the real risk-free rate actually did rather than just adding
a synthetic test to make the number move. RBI/PIB press releases confirm
the repo rate held flat at 6.50% through the entire Dec 2024-Jan 2025
window both data scripts now use (see "unified" below) -- so `rho_pnl == 0`
there is *correct*, not a gap. It hadn't always been this simple: the
market snapshot used to be dated 2025-06-02, two days *before* the RBI's
2025-06-06 cut to 5.50%, inside the window opened by the 2025-04-09 cut to
6.00% -- meaning the correct rate for that date was 6.00%, not the 6.50%
the whole project was using at the time. Fixing that (before the snapshot
date was later moved) wasn't cosmetic: one previously-rejected strike on
the 2025-06-12 expiry cleared the no-arbitrage IV bound (105/106 ->
106/106) purely from correcting the rate.

Also added `tests/test_pure_rate_move_is_all_rho` and
`test_rho_pnl_has_the_right_sign_for_a_real_rate_cut`, both using the
real, dated cut magnitudes above rather than an arbitrary number, so rho
is now an exercised, sign-checked term instead of a name in a list.

## The dashboard and the attribution engine used to describe two unrelated weeks

`build_market_snapshot.py`'s snapshot day and `build_snapshot_series.py`'s
expiry were chosen independently, in separate sessions, with no reference
back to each other -- 2025-06-02 for one, the week around the 2025-01-09
expiry for the other, five months apart. There was no technical reason
they needed to match (one script needs breadth across strikes/expiries on
one day, the other needs depth across days for one expiry), but there was
also no reason they were five months apart, and it meant the two features
told two disconnected stories about the market instead of one coherent
one. Unified by pointing `build_market_snapshot.py` at 2024-12-27 -- the
attribution engine's own first real day -- so `20250109` now shows up as
one of the dashboard's four live expiries too: the smile/skew/term-
structure view and the Greek attribution breakdown now describe the same
underlying week. Confirmed, not assumed: both scripts independently
compute the identical spot print (23,870.25) for that date from their own
separate reads of `nifty_spot.csv`.

## Two sessions, on purpose -- one paired sample and one breadth check

Unifying the two features onto one week (above) is good for coherence, but
it also means the whole repo now runs on a single real session. To check
the code generalises rather than being quietly tuned to one week's data,
`build_market_snapshot.py` also ships a second, deliberately different
session: `--date 2026-03-11`, more than a year later. NIFTY's weekly
expiry moved from Thursday to Tuesday by 2026 (confirmed directly against
the raw archive filenames, not assumed -- every 2024/2025 expiry in this
dataset is a Thursday, every 2026 one is a Tuesday), so this isn't just a
different date, it's a different exchange convention. The dashboard's
**Session** selector switches between the two prebuilt JSON files with no
other code path change; both went through the same `build_snapshot()`
function, the same `rf_rate()` lookup (0.065 for the first, 0.0525 for the
second -- picked up automatically, not hand-verified per session the way
the original 0.060/2025-06-02 rate was), and the same in-browser check
(no console errors, sensible smile/skew on both) before being trusted.

Adding a second session surfaced a real bug in the switching code itself:
`loadSession(path)`'s `fetch(...).then(...)` had no guard against two
loads racing -- if an earlier session's fetch happened to resolve *after*
a later one (plausible on the initial page-load fetch racing a fast
manual switch, or under ordinary network jitter), its `.then()` would run
last and silently overwrite the dropdown/charts with the wrong session's
data while the selector itself still showed the session the user had
actually chosen. Reproduced directly (firing the switch to 2026 then
immediately back to 2024 exposed exactly this: selector said 2024, charts
still showed 2026), then fixed with a monotonic sequence counter --
each `loadSession()` call captures its own sequence number, and a
response is applied only if no newer load has started since. Verified
both directions, including the deliberately-raced case.

## The hourly view started as a separate card, and that was the wrong shape

The first attempt at showing intraday movement added a fixed-strike,
fixed-expiry side panel (`scripts/build_intraday_series.py`) that revalued
one ATM contract every hour, independent of the Session/Expiry/Quotes
controls above it. That's a narrower question than the dashboard's other
views answer -- it shows one contract's clock, not how the *chain* looks
at a given hour -- and it meant "hourly" and "which strike/expiry" lived
in two disconnected parts of the page. Replaced it with a single **Hour**
selector wired into the same state the Session and Expiry selectors
already drive: `build_market_snapshot.py` now prices the full chain at
seven hourly checkpoints (09:15-15:15 IST) instead of one fixed 09:45
cross-section, and every chart on the tab -- IV smile, term structure and
skew, the IV surface, per-strike Greeks, put-call parity, traded volume --
re-renders off whichever hour is selected. The old script and its narrower
data file are gone; the checkpoint convention it introduced (hourly, real
prints matched within a 3-minute staleness cap) is what the chain-wide
version now uses too.

One side effect worth being explicit about: exact-minute matching (the
original `build_market_snapshot.py`) and nearest-prior-within-3-minutes
matching (needed for checkpoints other than the one lucky minute a whole
chain happened to trade in) aren't the same filter, so per-hour stats like
the parity residual and contracts-retained count move around across the
day -- e.g. the primary session's median |parity residual| ranges roughly
8-31 points depending on which of the seven hours is selected, not one
fixed number. That range itself is informative: it means the two
mid-morning/early-afternoon hours checked so far are not meaningfully
"more parity-valid" than the open or close, consistent with this dataset
never having a firm quote to check parity against in the first place.

## "Session and Expiry aren't reconciling" turned out to be file://, not the state machine

A report that Session and Expiry looked out of sync sent this back through
every combination the dashboard's state machine can reach: rapid session
switches in both orders, a session switch while a non-default Hour and
Expiry were active, cycling all seven hours under the "Parity-valid only"
filter (including hours with zero valid pairs), and a full rerun of
`build_market_snapshot.py` checked for determinism and for any checkpoint
missing an expiry the others have. All of it reconciled correctly and
`market.js`'s actual state -- `selectedHour`/`selectedExpiry` plus the
`by_time` lookup -- was never the problem. The real cause: opening
`index.html` directly (`file://...`) rather than through a local server.
Browsers block a page's own `fetch()` requests over `file://`, so `DATA`
never loads and the dropdowns never populate -- and because every control
still *looks* interactive, the failure reads as "Session and Expiry don't
agree" rather than "nothing loaded", which is what actually happened.
`market.js` now checks `location.protocol` before attempting any fetch and
disables Session/Hour/Expiry/Quotes with an explicit instruction ("serve
this over HTTP") instead of leaving them in that ambiguous state -- see
"Running it" above for the one-line server command.

## What's real and what isn't

- **Solver Explorer** tab: purely synthetic. You pick the axes and fixed
  parameters; every surface is the closed-form solver evaluated on a grid.
- **Real NIFTY Snapshot** tab: real 1-minute option prices from one
  session at the selected hour (see the snapshot strip at the top of the
  page, and the **Hour** selector next to Session), IV backed out per
  strike, Greeks computed from that IV. The dataset has OHLCV + open
  interest but **no bid/ask** -- every number is a last-traded print, not
  a live quote -- so:
  - a "Liquid only" filter (volume &ge; 50 lots at the matched print) and a
    "Parity-valid only" filter (put-call parity residual within &plusmn;15
    points) are both available from the Quotes selector, and the snapshot
    strip always shows contracts retained vs. total for the current filter;
  - the put-call parity check uses the discounted-strike form
    (`C - P + K*e^-rT - S`) against the matched CE/PE close, not a mid, so a
    large residual is flagged as a likely stale/asynchronous print, never
    as a live arbitrage -- and in this dataset, most strike pairs exceed
    the tolerance at every hour (median residual roughly 8-31 points across
    the seven checkpoints in the primary session, not one fixed number --
    see "the hourly view started as a separate card" above), which is the
    expected result of checking parity with no bid/ask, not a broken
    filter;
  - the traded-volume panel is the matched print's own interval volume,
    not a cumulative session total, and puts are mirrored below zero
    purely as a comparison device, labelled as such;
  - only 4 expiries were live that day, so the IV surface is a heatmap
    (moneyness x expiry) rather than a continuous 3D surface, and cells
    outside the moneyness range that expiry actually traded are left as
    missing (rendered as the plot background) rather than extrapolated and
    shown as if they were observed.
- The primary market snapshot and the attribution series describe the same
  week (see "unified" above) and both correctly use 0.065 -- that week
  sits inside the unbroken pre-cut RBI regime. The second, 2026 snapshot
  (see "two sessions" above) correctly uses 0.0525 instead, picked up
  automatically by `rf_rate()` rather than hand-verified per date --
  there's no longer a *silent* cross-dataset rate mismatch, but the rate
  does genuinely differ between the two dashboard sessions, as it should.
  Neither dataset accounts for dividends/carry, and both treat
  Black-Scholes as an implied-vol quoting convention rather than a
  literal pricing claim -- standard practice for short-dated index
  options, where jumps and discrete hedging dominate anyway.
- **`scripts/attribute_pnl.py`**: every number in it is real -- real spot,
  real traded option prices, real implied vols, across five genuine
  consecutive trading days, for six real strikes combined into a straddle,
  a strangle, and an iron condor. The scope to keep in mind: it's six
  contracts' path through one particular expiry week, not a claim about
  attribution accuracy in general -- that's deliberate, per the decision to
  build and debug the attribution engine itself (one week, three
  structures, in increasing order of complexity) before scaling it out to
  more days or expiries.
  `build_snapshot_series.py` now records each leg's traded volume and flags
  anything within 3x the 50-lot liquidity floor used elsewhere in this
  project, and the demo prints a liquid-only recheck alongside the
  headline number. For this week, three of the straddle's four transitions
  turn out to lean on the ATM put trading only 75 lots (against thousands
  everywhere else) -- thin enough that "explained by the Greeks" and
  "priced off a stale minute" aren't distinguishable from this data alone.
  Excluding those transitions moves the straddle's fit from 93.3% to 92.7%
  -- reassuringly close, but that comparison now rests on a single
  remaining transition, so read it as "not obviously inflated by
  illiquidity" rather than "proven clean." The strangle and condor legs
  (further OTM, apparently more actively traded this week) show no thin
  transitions at all under the same check.
