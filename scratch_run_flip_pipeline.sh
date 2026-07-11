#!/bin/bash
# Study continuation pipeline: new12 walks + orig8 chain walk + management grid.
# All output under analyst/po_comp_options/ and this log. Safe to run detached.
set -x
cd /root/spy
LOG_DIR=/root/spy/analyst/po_comp_options
export PYTHONWARNINGS=ignore

N12_EV=events_new12.csv
N12_TP=underlying_5m_topup_new12.parquet
O8_EV=events_v2_eth.csv
O8_TP=underlying_5m_topup_v2.parquet

echo "=== walk 1/4: new12 F (full box, first poke) ==="
PO_EVENTS=$N12_EV PO_TOPUP=$N12_TP PO_OUT=flip12_fullbox NO_FLAG=1 WAIT_FULL_BOX=1 \
  python3 scratch_po_comp_flip_rerun.py || exit 1
echo "=== walk 2/4: new12 D (close-confirmed) ==="
PO_EVENTS=$N12_EV PO_TOPUP=$N12_TP PO_OUT=flip12_confirm CONFIRM_CLOSE=1 \
  python3 scratch_po_comp_flip_rerun.py || exit 1
echo "=== walk 3/4: new12 F + multi-entry chains ==="
PO_EVENTS=$N12_EV PO_TOPUP=$N12_TP PO_OUT=flip12_fbmulti NO_FLAG=1 WAIT_FULL_BOX=1 MULTI_ENTRY=1 \
  python3 scratch_po_comp_flip_rerun.py || exit 1
echo "=== walk 4/4: orig8 F + multi-entry chains ==="
PO_EVENTS=$O8_EV PO_TOPUP=$O8_TP PO_OUT=flip8_fbmulti NO_FLAG=1 WAIT_FULL_BOX=1 MULTI_ENTRY=1 \
  python3 scratch_po_comp_flip_rerun.py || exit 1
echo "=== management grid ==="
python3 scratch_po_comp_mgmt_grid.py || exit 1
echo "=== PIPELINE COMPLETE ==="
