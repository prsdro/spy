"""ES grid over the paper's published robustness knobs: VM x lookback.

Costs: 1 tick/side slippage + $4.30 RT commission per ES contract.
Reported by period, with emphasis on 2022+ and post-publication (2024-05+).
"""
import numpy as np
import pandas as pd
import json
from engine import run, summarize

DATA = "/srv/ftp/ossicones/futures-data/ES_full_1min_continuous_ratio_adjusted.txt"
COST_RT_PTS = 0.5 + 4.30 / 50.0  # 0.586 pts / RT

print("loading ES...")
df = pd.read_csv(DATA, header=None, names=["ts", "o", "h", "l", "c", "v"], parse_dates=["ts"])

rows = []
best_paths = None
for vm in [1.0, 1.5, 2.0]:
    for lb in [14, 90]:
        res, paths = run(df, vm=vm, cost_rt_price_units=COST_RT_PTS, lookback=lb)
        res["net_usd"] = res["net"] * 50.0
        for lo, hi, lab in [("2008-01-01", "2026-12-31", "full"),
                            ("2016-01-01", "2021-12-31", "2016-21"),
                            ("2022-01-01", "2026-12-31", "2022+"),
                            ("2024-05-01", "2026-12-31", "post-pub")]:
            sub = res[(res["date"] >= lo) & (res["date"] <= hi)]
            s = summarize(sub, lab)
            s.update({"vm": vm, "lb": lb,
                      "avg_usd": round(sub["net_usd"].mean(), 1),
                      "sd_usd": round(sub["net_usd"].std(), 1),
                      "gross_bps": round(sub["gross_ret_frac"].mean() * 1e4, 2)})
            rows.append(s)
        res.to_csv(f"es_vm{vm}_lb{lb}_daily.csv", index=False)
        if vm == 1.5 and lb == 90:
            np.savez_compressed(
                "es_vm1.5_lb90_paths.npz",
                **{f"{k}_hm": v[0] for k, v in paths.items()},
                **{f"{k}_pnl": v[1] for k, v in paths.items()})

out = pd.DataFrame(rows)
cols = ["vm", "lb", "label", "days", "avg_bps", "gross_bps", "avg_usd", "sd_usd",
        "t_stat", "sharpe", "hit_traded", "pct_days_traded", "avg_rts"]
out = out[cols]
out.to_csv("es_grid_results.csv", index=False)
print(out.to_string(index=False))
