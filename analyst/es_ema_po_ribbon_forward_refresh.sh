#!/bin/bash
# Standing forward test for the ribbon-riding candidate.
# Re-fetches SPY 1-min from Massive and re-scores the frozen spec on the
# accumulating post-2026-01-23 window. Run monthly (or whenever).
# Spec frozen in analyst/es_ema_po_ribbon_forward_prereg.md — do not edit it.
rm -f /root/spy/analyst/spy_1m_massive_fwd.csv
cd /root/spy && PYTHONWARNINGS=ignore python3 analyst/es_ema_po_ribbon_forward_spy.py
