"""
0DTE SPX option pricer — simple Black-Scholes + VIX→IV mapper + scenario runner.

Design goal: scrappy and readable, not a production engine.
Run `python3 examples.py` to see worked examples.
"""
from __future__ import annotations
from dataclasses import dataclass
import math
import numpy as np
from scipy.stats import norm

# --- constants ---------------------------------------------------------------
MIN_PER_TRADING_DAY = 390      # 9:30am - 4:00pm ET
TRADING_DAYS = 252
MIN_PER_YEAR = MIN_PER_TRADING_DAY * TRADING_DAYS   # ≈ 98,280
DEFAULT_R = 0.045

# --- core math ---------------------------------------------------------------
def minutes_to_T(minutes: float) -> float:
    """Convert minutes-to-expiry to years (BSM time unit)."""
    return max(minutes, 1e-6) / MIN_PER_YEAR

def bs_price(S: float, K: float, T: float, r: float, sigma: float, kind: str) -> float:
    """Black-Scholes European option price. kind in {'call','put'}."""
    if T <= 0 or sigma <= 0:
        intrinsic = max(S - K, 0.0) if kind == "call" else max(K - S, 0.0)
        return intrinsic
    sqrtT = math.sqrt(T)
    d1 = (math.log(S / K) + (r + 0.5 * sigma * sigma) * T) / (sigma * sqrtT)
    d2 = d1 - sigma * sqrtT
    if kind == "call":
        return S * norm.cdf(d1) - K * math.exp(-r * T) * norm.cdf(d2)
    else:
        return K * math.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)

def bs_greeks(S: float, K: float, T: float, r: float, sigma: float, kind: str) -> dict:
    """Returns delta, gamma, vega (per 1 vol pt), theta (per day), theta_per_min."""
    if T <= 0 or sigma <= 0:
        return dict(delta=0.0, gamma=0.0, vega=0.0, theta_day=0.0, theta_min=0.0)
    sqrtT = math.sqrt(T)
    d1 = (math.log(S / K) + (r + 0.5 * sigma * sigma) * T) / (sigma * sqrtT)
    d2 = d1 - sigma * sqrtT
    pdf_d1 = norm.pdf(d1)
    if kind == "call":
        delta = norm.cdf(d1)
        theta_yr = (-S * pdf_d1 * sigma / (2 * sqrtT)
                    - r * K * math.exp(-r * T) * norm.cdf(d2))
    else:
        delta = norm.cdf(d1) - 1.0
        theta_yr = (-S * pdf_d1 * sigma / (2 * sqrtT)
                    + r * K * math.exp(-r * T) * norm.cdf(-d2))
    gamma = pdf_d1 / (S * sigma * sqrtT)
    vega = S * pdf_d1 * sqrtT / 100.0           # per 1 vol POINT (i.e. 1%)
    theta_day = theta_yr / TRADING_DAYS
    theta_min = theta_yr / MIN_PER_YEAR
    return dict(delta=delta, gamma=gamma, vega=vega,
                theta_day=theta_day, theta_min=theta_min)

# --- VIX → IV mapping --------------------------------------------------------
def vix_to_atm_iv(vix: float) -> float:
    """Rough VIX → 0DTE ATM IV mapping. VIX is 30d; 0DTE usually trades different."""
    v = vix / 100.0
    if vix < 15:    k = 0.85
    elif vix < 20:  k = 0.95
    elif vix < 30:  k = 1.05
    else:           k = 1.20
    return v * k

def strike_iv(S: float, K: float, atm_iv: float,
              slope_put: float = 0.50, slope_call: float = -0.30) -> float:
    """Simple linear skew. Slopes are vol POINTS per 1% moneyness.
    Positive moneyness = OTM call side; negative = OTM put side."""
    m_pct = (K - S) / S * 100.0           # moneyness in percent
    if m_pct >= 0:                         # call side
        iv_pts = atm_iv * 100.0 + slope_call * m_pct
    else:                                  # put side
        iv_pts = atm_iv * 100.0 + slope_put * (-m_pct)
    return max(iv_pts, 1.0) / 100.0       # floor at 1% IV

# --- scenario runner ---------------------------------------------------------
@dataclass
class ScenarioResult:
    price_now: float
    price_scn: float
    pnl: float
    pnl_pct: float
    iv_now: float
    iv_scn: float
    greeks_now: dict

    def fmt(self) -> str:
        g = self.greeks_now
        return (f"  now=${self.price_now:7.2f}  scn=${self.price_scn:7.2f}  "
                f"P&L=${self.pnl:+7.2f} ({self.pnl_pct:+7.1f}%)  "
                f"IV {self.iv_now*100:4.1f}→{self.iv_scn*100:4.1f}  "
                f"Δ={g['delta']:+.2f} Γ={g['gamma']:.4f} "
                f"θ/min=${g['theta_min']:+.3f}")

def price_scenario(spot_now: float, strike: float, option_type: str,
                   minutes_to_expiry_now: float, vix_now: float,
                   spot_scenario: float, minutes_to_expiry_scenario: float,
                   vix_scenario: float | None = None,
                   r: float = DEFAULT_R,
                   slope_put: float = 0.50,
                   slope_call: float = -0.30) -> ScenarioResult:
    if vix_scenario is None:
        vix_scenario = vix_now

    iv_now = strike_iv(spot_now, strike, vix_to_atm_iv(vix_now),
                       slope_put, slope_call)
    iv_scn = strike_iv(spot_scenario, strike, vix_to_atm_iv(vix_scenario),
                       slope_put, slope_call)

    T_now = minutes_to_T(minutes_to_expiry_now)
    T_scn = minutes_to_T(minutes_to_expiry_scenario)

    p_now = bs_price(spot_now, strike, T_now, r, iv_now, option_type)
    p_scn = bs_price(spot_scenario, strike, T_scn, r, iv_scn, option_type)
    greeks = bs_greeks(spot_now, strike, T_now, r, iv_now, option_type)

    pnl = p_scn - p_now
    pnl_pct = (pnl / p_now * 100.0) if p_now > 1e-6 else float("nan")
    return ScenarioResult(p_now, p_scn, pnl, pnl_pct, iv_now, iv_scn, greeks)


if __name__ == "__main__":
    # smoke test
    r = price_scenario(spot_now=5800, strike=5810, option_type="call",
                       minutes_to_expiry_now=240, vix_now=16,
                       spot_scenario=5830, minutes_to_expiry_scenario=180)
    print("smoke test 5810C, SPX 5800→5830, noon→1pm, VIX 16:")
    print(r.fmt())
