#!/bin/bash
# Poll the Massive key every 10 min; when it's back on a paid tier
# (>5 rapid requests succeed), launch the new-12 options pipeline once.
KEY=$(grep POLYGON_API_KEY /root/spx-chart-app/.env | cut -d= -f2)
LOG=/root/spy/analyst/po_comp_options/relaunch_new12.log
echo "$(date -u -Is) watcher start" >> "$LOG"
while true; do
  ok=0
  for i in $(seq 1 8); do
    code=$(curl -s -o /dev/null -w "%{http_code}" "https://api.massive.com/v2/aggs/ticker/SPY/range/1/day/2026-07-01/2026-07-02?apiKey=$KEY")
    [ "$code" = "200" ] && ok=$((ok+1))
  done
  echo "$(date -u -Is) burst ok=$ok/8" >> "$LOG"
  if [ "$ok" -ge 7 ]; then
    echo "$(date -u -Is) PAID TIER DETECTED — launching new-12 pipeline" >> "$LOG"
    cd /root/spy
    export PO_TICKERS=PLTR,AVGO,NFLX,MU,COIN,SMCI,HOOD,INTC,UBER,BAC,JPM,DIS \
      PO_WINDOW_START=2024-07-14 PO_SESSION=ETH PO_EVENTS=events_new12.csv \
      PO_TODO=contracts_todo_new12.json PO_TOPUP=underlying_5m_topup_new12.parquet \
      PO_BUCKETS=W1,W2 PO_OFFSETS=0,0.5,-0.5
    python3 fetch_po_comp_options.py >> analyst/po_comp_options_nohup.out 2>&1 \
      && PO_OUT=v3_new12 python3 backtest_po_comp_v3.py >> "$LOG" 2>&1 \
      && echo "$(date -u -Is) NEW12 PIPELINE COMPLETE" >> "$LOG"
    exit 0
  fi
  sleep 600
done
