#!/bin/bash
# Rerun all ATR-bug-affected backtests in sequence (not parallel — avoid OOM).
# Output goes to audit-reruns/postfix-outputs/

cd /root/spy
mkdir -p audit-reruns/postfix-outputs

BACKTESTS=(
    backtest_atr_probabilities
    backtest_multiday_gg
    backtest_swing_gg
    backtest_call_trigger_confirmation
    backtest_gg_entries
    backtest_gg_invalidation
    backtest_gg_chop_zone
    backtest_gg_with_po
    backtest_premarket_ath
    backtest_trigger_box
    backtest_trigger_box_spreads
    backtest_gap_fill_cumulative
    backtest_gap_up_dump
    backtest_gap_up_pre_noon
    backtest_po_sustained_morning
    backtest_po_sustained_reversal
    backtest_po_sustained_cloud_mtf
    backtest_ema21_reversion
    backtest_4h_po_opex_extended
)

for bt in "${BACKTESTS[@]}"; do
    echo "[$(date +%H:%M:%S)] Running $bt..."
    python3 ${bt}.py > audit-reruns/postfix-outputs/${bt}.log 2>&1
    status=$?
    if [ $status -ne 0 ]; then
        echo "  FAILED: exit $status"
    else
        echo "  OK ($(wc -l < audit-reruns/postfix-outputs/${bt}.log) lines)"
    fi
done

echo "[$(date +%H:%M:%S)] All backtests complete."
