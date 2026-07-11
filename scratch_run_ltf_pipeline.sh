#!/bin/bash
# Pipeline 2: LTF-confirmation entries (10m/30m x plain/PO-gated x orig8/new12),
# flag-gated multi walk for new12 (re-arm OOS), then analysis.
set -x
cd /root/spy
export PYTHONWARNINGS=ignore

O8="PO_EVENTS=events_v2_eth.csv PO_TOPUP=underlying_5m_topup_v2.parquet"
N12="PO_EVENTS=events_new12.csv PO_TOPUP=underlying_5m_topup_new12.parquet"

echo "=== flag-gated multi walk, new12 (re-arm OOS) ==="
env $N12 PO_OUT=flip12_multi MULTI_ENTRY=1 python3 scratch_po_comp_flip_rerun.py || exit 1

for LTF in 10 30; do
  for PO in 0 1; do
    SUF=$([ "$PO" = "1" ] && echo "po" || echo "")
    echo "=== ltf${LTF}${SUF} orig8 ==="
    env $O8 PO_OUT=ltf${LTF}${SUF}_o8 LTF=$LTF LTF_PO=$PO python3 scratch_po_comp_ltf_entry.py || exit 1
    echo "=== ltf${LTF}${SUF} new12 ==="
    env $N12 PO_OUT=ltf${LTF}${SUF}_n12 LTF=$LTF LTF_PO=$PO python3 scratch_po_comp_ltf_entry.py || exit 1
  done
done

echo "=== analysis ==="
python3 scratch_po_comp_ltf_analysis.py || exit 1
echo "=== LTF PIPELINE COMPLETE ==="
