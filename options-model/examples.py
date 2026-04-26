"""
Worked examples for the 0DTE SPX pricer.

Shows expected P&L for an ITM call vs an OTM call given +/- moves
in SPX at different times of day. Run: python3 examples.py
"""
from pricer import price_scenario

SPOT = 5800
VIX  = 16.0

# Two strikes: one ITM (~10 pts ITM = 0.17% ITM), one OTM (~25 pts OTM = 0.43% OTM)
STRIKES = [("ITM 5790C", 5790, "call"),
           ("OTM 5825C", 5825, "call")]

# Underlying scenarios as % moves
MOVES = [("-0.5%", -0.005), ("+0.5%", +0.005), ("+1.0%", +0.010)]


def run_block(label: str, mins_now: int, mins_scn: int):
    print(f"\n=== {label}  (T_now={mins_now}min, T_scn={mins_scn}min, "
          f"SPX={SPOT}, VIX={VIX}) ===")
    header = f"{'leg':<10} {'now$':>8} " + " ".join(
        f"{m:>22}" for m, _ in MOVES)
    print(header)
    for name, K, kind in STRIKES:
        # price-now is the same across move scenarios; compute once
        ref = price_scenario(SPOT, K, kind, mins_now, VIX,
                             SPOT, mins_scn)        # same spot, just for now$
        now_str = f"{ref.price_now:8.2f}"
        cells = []
        for _, pct in MOVES:
            spot_scn = SPOT * (1 + pct)
            r = price_scenario(SPOT, K, kind, mins_now, VIX,
                               spot_scn, mins_scn)
            cells.append(f"${r.price_scn:6.2f} {r.pnl_pct:+7.1f}%   ")
        print(f"{name:<10} {now_str} " + " ".join(c.rjust(22) for c in cells))

    # show greeks once for context (at "now")
    print("greeks @ now:")
    for name, K, kind in STRIKES:
        r = price_scenario(SPOT, K, kind, mins_now, VIX, SPOT, mins_scn)
        g = r.greeks_now
        print(f"  {name}: Δ={g['delta']:+.3f}  Γ={g['gamma']:.5f}  "
              f"vega=${g['vega']:.3f}/volpt  θ/min=${g['theta_min']:+.3f}  "
              f"IV={r.iv_now*100:.2f}%")


if __name__ == "__main__":
    print("0DTE SPX option scenario tables")
    print("Format per cell: scenario_price   pnl_pct%")

    # Example A: noon → 1pm  (240 → 180 min remaining)
    run_block("Example A — 12:00pm → 1:00pm", mins_now=240, mins_scn=180)

    # Example B: 3:00pm → 3:30pm  (60 → 30 min remaining)  — theta crunch
    run_block("Example B — 3:00pm → 3:30pm  (theta crunch)",
              mins_now=60, mins_scn=30)
