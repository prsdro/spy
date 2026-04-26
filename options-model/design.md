# 0DTE SPX Options — Simple Expected-Return Model

A scrappy framework for forecasting 0DTE SPX option P&L given a directional thesis,
without dragging in QuantLib, stochastic vol, or surface fitting. Black-Scholes +
a VIX→IV mapper + a tiny linear skew is enough to be useful intraday.

---

## 1. Conceptual model (plain English)

You have a directional view: "SPX moves from S₀ to S₁ by time t₁."
We want to answer: *what does my call/put do between now and then?*

Three forces drive the option's price change:

1. **Delta / gamma** — the option re-prices because spot moved.
2. **Theta** — time passes, extrinsic value bleeds. On 0DTE this dominates the last 1–2 hours.
3. **Vega / IV regime** — implied vol changes (or doesn't). For a quick scenario we usually
   *hold IV constant* and let the VIX regime set the level. If the user wants, they can pass
   a "scenario VIX" too.

We bolt these together with one tool: **Black-Scholes**, evaluated twice — once *now*,
once *at the scenario time/spot/IV* — and take the difference. That's it.

For 0DTE we don't need fancy time handling: T is just **minutes-to-close / minutes-per-year**
(390 min/day × 252 trading days ≈ 98,280 min/yr).

---

## 2. Minimal inputs

Per scenario:

| Input | Example | Notes |
|---|---|---|
| `spot_now` | 5800 | current SPX |
| `strike` | 5810 | option strike |
| `option_type` | "call" / "put" | |
| `minutes_to_expiry_now` | 240 | e.g. 240 = noon ET on a 4pm-close 0DTE |
| `vix_now` | 16.5 | current VIX print |
| `spot_scenario` | 5830 | thesis target |
| `minutes_to_expiry_scenario` | 180 | thesis time (1pm ET) |
| `vix_scenario` (optional) | 16.5 | default = vix_now (vol-flat scenario) |
| `r` | 0.045 | risk-free, set once |

Output: theoretical price now, theoretical price at scenario, $ P&L, % P&L, plus
the greeks at "now" so the trader has context.

---

## 3. Math

### Black-Scholes (European, no dividend for simplicity)

```
d1 = [ln(S/K) + (r + σ²/2)·T] / (σ·√T)
d2 = d1 − σ·√T
Call = S·N(d1) − K·e^(−rT)·N(d2)
Put  = K·e^(−rT)·N(−d2) − S·N(−d1)
```

T is in **years**. For 0DTE we use `T = minutes_left / (390 · 252)`. As T → 0,
`σ√T → 0`, so extrinsic collapses — this is the non-linear theta crunch the trader
feels in the last hour.

### Why not a "theta-per-minute" shortcut?
Because BSM's theta is itself non-linear near expiry. Re-pricing with the new T is
*both* simpler and more accurate than approximating dC/dt as constant. We expose
theta-per-minute as a derived diagnostic (`θ/390/252`) but don't use it for forecasting.

### Greeks (closed form, used for diagnostics)
- Δ_call = N(d1), Δ_put = N(d1) − 1
- Γ = φ(d1) / (S·σ·√T)
- Vega = S·φ(d1)·√T   (per 1.0 vol; divide by 100 for "per vol point")
- Θ_call = −S·φ(d1)·σ/(2√T) − r·K·e^(−rT)·N(d2)   (per year; /252 → per day; /(252·390) → per min)

---

## 4. VIX → per-strike IV

VIX itself is a 30-day SPX vol index. For 0DTE the realized IV traders see is usually
**lower than VIX** because the term structure is normally upward-sloping in calm regimes
and inverted in stressed ones. A simple, defensible mapping:

```
ATM_IV_0DTE ≈ VIX/100 · k(regime)
  k = 0.85   if VIX < 15     (calm: 0DTE IV << 30d IV)
  k = 0.95   if 15 ≤ VIX < 20
  k = 1.05   if 20 ≤ VIX < 30 (stress: front-end inverts)
  k = 1.20   if VIX ≥ 30
```

This is a **rough heuristic**, not a fit. Override with your own scalar if you have
better data.

### Skew (kept dumb-simple, linear in moneyness)

Define moneyness `m = (K − S)/S` (positive = OTM call side, negative = OTM put side).

```
IV(K) = ATM_IV + slope_put · max(0, −m) + slope_call · max(0, m)
slope_put  = +0.50   (puts richer; +0.5 vol pts per 1% OTM put)
slope_call = −0.30   (calls cheaper out; −0.3 vol pts per 1% OTM call)
```

Floor at 1% so we never get a negative IV. Again — rough. The point is to stop
pricing 5750 puts at the same vol as 5810 calls.

---

## 5. Script architecture

Single file `pricer.py`, stdlib + numpy + scipy only.

```
pricer.py
├── bs_price(S, K, T, r, sigma, kind)        # Black-Scholes
├── bs_greeks(S, K, T, r, sigma, kind)       # delta/gamma/vega/theta
├── vix_to_atm_iv(vix)                       # regime lookup
├── strike_iv(S, K, atm_iv,                  # linear skew
│           slope_put=0.50, slope_call=-0.30)
├── minutes_to_T(minutes)                    # → years
├── price_scenario(...)                      # the user-facing call:
│      returns dict {price_now, price_scn, pnl, pnl_pct, greeks_now}
└── __main__ demo
```

Data flow:

```
inputs ──► vix_to_atm_iv ──► strike_iv ──┐
                                          ├─► bs_price (now)      ┐
inputs (S₀, T₀)  ──────────────────────────┘                       ├─► P&L
inputs (S₁, T₁, vix₁) ──► strike_iv ──► bs_price (scenario) ──────┘
```

`examples.py` imports `price_scenario` and prints two tables.

---

## 6. Worked examples

Setup: SPX = 5800, VIX = 16, 0DTE expiring 4:00pm ET.

**Example A — ITM call (5790) vs OTM call (5825) at 12:00pm (240 min left).**
Scenarios: SPX → {5771 (-0.5%), 5829 (+0.5%), 5858 (+1.0%)} by 1:00pm (180 min left).

**Example B — same strikes, same scenarios, but starting at 3:00pm (60 min left)
with scenario time at 3:30pm (30 min left).** This shows the theta crunch: the OTM
call needs much more move just to break even.

`examples.py` prints:

```
Example A — start 12:00pm, target 1:00pm
strike  type  now$    -0.5%      +0.5%      +1.0%
5790    call  ...     ...        ...        ...
5825    call  ...     ...        ...        ...
```

Reading these tables gives a clean intuition: ITM = mostly delta, OTM = lottery
ticket (huge % gains on the +1% case, full donut on the −0.5%, theta-dominated
in the last hour).

---

## 7. Caveats / what's intentionally missing

- No dividend yield (SPX index, small effect intraday — fine).
- No vol surface fitting; skew is linear and hand-set.
- VIX→IV `k` factors are eyeballed; calibrate to your own broker's IV when you can.
- No early exercise (SPX is European — correct).
- No bid-ask, no slippage. Add a haircut to outputs if you trade on this.
- Vega is held flat in scenarios unless user passes `vix_scenario`.

Simple wins. Iterate only when a specific output disagrees with reality.
