"""Checks explorer.js's hand-reimplemented BS object against
bs_solver/black_scholes.py -- the two are kept in sync by hand (a static
page can't call Python at runtime), so nothing else catches them drifting
apart. Requires node on PATH.
"""
import json
import random
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bs_solver.black_scholes import price, delta, gamma, vega, theta, rho

ROOT = Path(__file__).resolve().parents[1]
JS_RUNNER = ROOT / "tests" / "_js_parity_runner.js"

# erf is Abramowitz-Stegun in JS (~1.5e-7 max error) vs math.erf in Python
# (exact to machine precision) -- allow a little slack, tight enough to
# still catch a real transcription error between the two files.
TOL = 5e-4


def gen_cases(n=60, seed=7):
    rng = random.Random(seed)
    cases = []
    for _ in range(n):
        S = rng.uniform(50, 500)
        K = rng.uniform(50, 500)
        T = rng.uniform(0.02, 2.0)
        sigma = rng.uniform(0.05, 1.2)
        r = rng.uniform(0.0, 0.12)
        cp = rng.choice(["CE", "PE"])
        cases.append({"S": S, "K": K, "T": T, "sigma": sigma, "r": r, "cp": cp})
    return cases


def run_js(cases):
    JS_RUNNER.write_text(f"""
const BS = require({json.dumps(str(ROOT / "web" / "explorer.js"))});
const cases = {json.dumps(cases)};
const out = cases.map(function(c) {{
  return {{
    price: BS.price(c.S, c.K, c.T, c.sigma, c.cp, c.r),
    delta: BS.delta(c.S, c.K, c.T, c.sigma, c.cp, c.r),
    gamma: BS.gamma(c.S, c.K, c.T, c.sigma, c.r),
    vega: BS.vega(c.S, c.K, c.T, c.sigma, c.r),
    theta: BS.theta(c.S, c.K, c.T, c.sigma, c.cp, c.r),
    rho: BS.rho(c.S, c.K, c.T, c.sigma, c.cp, c.r),
  }};
}});
process.stdout.write(JSON.stringify(out));
""")
    try:
        result = subprocess.run(["node", str(JS_RUNNER)], capture_output=True, text=True, check=True, timeout=30)
    finally:
        JS_RUNNER.unlink(missing_ok=True)
    return json.loads(result.stdout)


def _worst_relative_errors():
    cases = gen_cases()
    js_out = run_js(cases)
    py_fns = {"price": lambda S, K, T, sigma, cp, r: price(S, K, T, sigma, cp, r=r),
              "delta": lambda S, K, T, sigma, cp, r: delta(S, K, T, sigma, cp, r=r),
              "gamma": lambda S, K, T, sigma, cp, r: gamma(S, K, T, sigma, r=r),
              "vega": lambda S, K, T, sigma, cp, r: vega(S, K, T, sigma, r=r),
              "theta": lambda S, K, T, sigma, cp, r: theta(S, K, T, sigma, cp, r=r),
              "rho": lambda S, K, T, sigma, cp, r: rho(S, K, T, sigma, cp, r=r)}
    worst = {}
    for c, js in zip(cases, js_out):
        for field, fn in py_fns.items():
            py_val = fn(c["S"], c["K"], c["T"], c["sigma"], c["cp"], c["r"])
            js_val = js[field]
            diff = abs(py_val - js_val)
            scale = max(1.0, abs(py_val))
            worst[field] = max(worst.get(field, 0.0), diff / scale)
    return worst


def test_js_matches_python_across_random_cases():
    worst = _worst_relative_errors()
    for field, rel_err in worst.items():
        assert rel_err < TOL, f"{field}: worst relative error {rel_err:.2e} exceeds {TOL:.0e}"


if __name__ == "__main__":
    worst = _worst_relative_errors()
    for field, rel_err in worst.items():
        print(f"  ok  {field:<8} worst relative error {rel_err:.2e}")
    print("\nJS/Python parity confirmed")
