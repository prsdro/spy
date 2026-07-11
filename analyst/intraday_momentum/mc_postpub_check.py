"""Spot-check the recommended eval cells on the post-publication window only
(2024-05 -> 2026-01): harsher drift assumption, no 2022 vol regime."""
import pandas as pd
from mc_sizing import load_paths, simulate, fixed, cushion_scaled

specs = [
    ("base", "es_intraday_momentum_paths.npz", "es_intraday_momentum_daily.csv"),
    ("vm15lb90", "es_vm1.5_lb90_paths.npz", "es_vm1.5_lb90_daily.csv"),
]
rows = []
for name, npz, csv in specs:
    days = load_paths(npz, csv, "2024-05-01", "2026-01-23")
    print(name, len(days), "days")
    for mode in ["intraday", "eod"]:
        for dd in [2500, 3000, 4000, 5000]:
            for pol_name, pol in [("fixed12", fixed(12)), ("fixed15", fixed(15)),
                                  ("fixed20", fixed(20)), ("cushion/250", cushion_scaled(250, 25))]:
                r = simulate(days, 20000, pol, dd, mode, 4500.0, 5, seed=7)
                r.update({"spec": name, "mode": mode, "dd": dd, "policy": pol_name})
                rows.append(r)
out = pd.DataFrame(rows)
out.to_csv("mc_postpub_check.csv", index=False)
for name in ["base", "vm15lb90"]:
    for mode in ["intraday", "eod"]:
        s = out[(out.spec == name) & (out["mode"] == mode)].pivot_table(
            index="policy", columns="dd", values=["p_pass", "p_blow"])
        print(f"== {name} {mode} =="); print(s.round(3).to_string())
