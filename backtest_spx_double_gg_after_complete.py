"""
Follow-up to backtest_spx_double_gg_revert.py.

Among the SPX "double Golden Gate" days where, after the downside gate opened
and the upside gate reopened (both before noon CT), the UPSIDE gate then
*completes* (+61.8% ATR) -- what happens AFTER that completion?

  Continuation : pushes on to +78.6% / +100% (full ATR) and/or closes well above
  Mean revert  : gives the gate back -- pulls down to +38.2%, then PDC
  Sideways     : holds in the gate (+38.2..+78.6) and closes near +61.8%

Path is resolved on 1-minute RTH bars from the first +61.8% touch onward.
"""

from __future__ import annotations

import pandas as pd

from backtest_spx_double_gg_revert import load_spx, first_time, NOON_CT_AS_ET, pct


def main():
    print("Loading FirstRateData SPX 1-minute + daily ...", flush=True)
    df = load_spx()
    cutoff_t = pd.Timestamp(NOON_CT_AS_ET).time()

    recs = []
    for date, g in df.groupby("date", sort=True):
        first = g.iloc[0]
        pdc, atr = first["prev_close"], first["atr_14"]
        morning = g[g.index.time < cutoff_t]
        if len(morning) == 0:
            continue

        dn_open_t = first_time(morning, morning["low"] <= first["dn_0382"])
        if dn_open_t is None:
            continue
        after_dn = morning[morning.index > dn_open_t]
        up_open_t = first_time(after_dn, after_dn["high"] >= first["up_0382"])
        if up_open_t is None:
            continue

        # Upside gate must COMPLETE (+61.8%) after it opened.
        after_up = g[g.index > up_open_t]
        up_close_t = first_time(after_up, after_up["high"] >= first["up_0618"])
        if up_close_t is None:
            continue

        # Path from the completion touch onward.
        after_c = g[g.index > up_close_t]
        from_c = g[g.index >= up_close_t]
        if len(after_c) == 0:
            continue  # completed on the very last bar; no "after"

        hit_0786 = bool((from_c["high"] >= first["up_0786"]).any())
        hit_100 = bool((from_c["high"] >= first["up_100"]).any())
        back_0382 = bool((after_c["low"] <= first["up_0382"]).any())   # gate reopens / given back
        back_pdc = bool((after_c["low"] <= pdc).any())
        back_trig = bool((after_c["low"] <= first["up_trig"]).any())

        max_high_after = from_c["high"].max()
        min_low_after = after_c["low"].min()
        close_price = g.iloc[-1]["close"]
        max_ext_atr = (max_high_after - pdc) / atr        # furthest up reached, in ATR from PDC
        give_back_atr = (first["up_0618"] - min_low_after) / atr  # pullback below +61.8 in ATR
        close_atr = (close_price - pdc) / atr

        # Classification (priority: continuation > revert > sideways).
        if hit_0786 or close_price >= first["up_0786"]:
            label = "continuation"
        elif back_0382:
            label = "mean_reversion"
        else:
            label = "sideways"

        recs.append({
            "date": str(date),
            "up_close_hhmm": f"{up_close_t.hour:02d}:{0 if up_close_t.minute < 30 else 30:02d}",
            "hit_0786": hit_0786,
            "hit_100": hit_100,
            "back_to_0382": back_0382,
            "back_to_pdc": back_pdc,
            "back_to_trig": back_trig,
            "max_ext_atr": max_ext_atr,
            "give_back_atr": give_back_atr,
            "close_atr": close_atr,
            "close_ge_0618": close_price >= first["up_0618"],
            "label": label,
        })

    ev = pd.DataFrame(recs)
    n = len(ev)
    print(f"\n{'='*70}")
    print("AFTER THE UPSIDE GATE COMPLETES (+61.8%) -- what next?")
    print(f"{'='*70}")
    print(f"  Qualifying days (upside gate completed, with bars after): n = {n}")
    if n == 0:
        return

    print("\n--- Outcome classification (priority: continuation > revert > sideways) ---")
    for key, lbl in [("continuation", "Continuation (reaches +78.6% or closes there+)"),
                     ("mean_reversion", "Mean reversion (gives gate back to +38.2%)"),
                     ("sideways", "Sideways (holds gate, no +78.6%, no give-back)")]:
        c = int((ev["label"] == key).sum())
        print(f"  {lbl:<48s} {c:4d}/{n}  {pct(c, n)}")

    print("\n--- Continuation detail (from the +61.8% touch onward) ---")
    for col, lbl in [("hit_0786", "Reaches +78.6%"),
                     ("hit_100", "Reaches +100% (full ATR)"),
                     ("close_ge_0618", "Closes at/above +61.8%")]:
        c = int(ev[col].sum())
        print(f"  {lbl:<34s} {c:4d}/{n}  {pct(c, n)}")

    print("\n--- Pullback detail (after the +61.8% touch) ---")
    for col, lbl in [("back_to_0382", "Pulls back to +38.2% (gate reopens)"),
                     ("back_to_trig", "Pulls back to +23.6% trigger"),
                     ("back_to_pdc", "Pulls back to PDC")]:
        c = int(ev[col].sum())
        print(f"  {lbl:<34s} {c:4d}/{n}  {pct(c, n)}")

    print("\n--- Magnitudes (ATR units) ---")
    print(f"  Furthest extension reached:   median={ev['max_ext_atr'].median():+.3f} ATR   "
          f"mean={ev['max_ext_atr'].mean():+.3f} ATR")
    print(f"  Deepest give-back below +61.8: median={ev['give_back_atr'].median():+.3f} ATR   "
          f"mean={ev['give_back_atr'].mean():+.3f} ATR")
    print(f"  Close vs PDC:                 median={ev['close_atr'].median():+.3f} ATR   "
          f"mean={ev['close_atr'].mean():+.3f} ATR")

    OUT = "analyst/spx_double_gg_after_complete_events.csv"
    ev.to_csv(OUT, index=False)
    print(f"\nSaved to {OUT}")


if __name__ == "__main__":
    main()
