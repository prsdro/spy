#!/bin/bash
# Pipeline 3: 30m Bilbo box (confirm + ltf10po entries, orig8 + new12),
# then box30 analysis + position-sizing scores on hourly D trades.
set -x
cd /root/spy
export PYTHONWARNINGS=ignore

O8="PO_EVENTS=events_v2_eth.csv PO_TOPUP=underlying_5m_topup_v2.parquet"
N12="PO_EVENTS=events_new12.csv PO_TOPUP=underlying_5m_topup_new12.parquet"

for V in confirm ltf10po; do
  echo "=== box30 $V orig8 ==="
  env $O8 PO_OUT=box30_${V}_o8 VARIANT=$V python3 scratch_po_comp_box30.py || exit 1
  echo "=== box30 $V new12 ==="
  env $N12 PO_OUT=box30_${V}_n12 VARIANT=$V python3 scratch_po_comp_box30.py || exit 1
done

echo "=== analysis: box30 + sizing ==="
python3 scratch_po_comp_sizing.py || exit 1
echo "=== BOX30 PIPELINE COMPLETE ==="
