#!/usr/bin/env bash
set -euo pipefail
ROOT=/srv/market-data/massive/us_equities
WORKER_ID="${WORKER_ID:-single}"
if [[ "$WORKER_ID" == "single" || -z "$WORKER_ID" ]]; then
  LOG="$ROOT/logs/full_ingest.log"
  LOCK="$ROOT/ingest.lock"
  STATUS="$ROOT/manifest/status.json"
else
  LOG="$ROOT/logs/ingest_${WORKER_ID}.log"
  LOCK="$ROOT/ingest_${WORKER_ID}.lock"
  STATUS="$ROOT/manifest/status_${WORKER_ID}.json"
fi
mkdir -p "$ROOT/logs" "$ROOT/manifest"

# If this worker has already completed its assigned range, do not restart work.
if [[ -f "$STATUS" ]]; then
  state="$(/usr/bin/python3 - <<PY
import json, pathlib
p=pathlib.Path('$STATUS')
try:
    print(json.loads(p.read_text()).get('state') or '')
except Exception:
    print('')
PY
)"
  if [[ "$state" == "complete" ]]; then
    echo "Worker $WORKER_ID already complete; exiting cleanly."
    exit 0
  fi
fi

# Remove only stale locks. Never remove a live ingest lock.
if [[ -f "$LOCK" ]]; then
  oldpid="$(cat "$LOCK" 2>/dev/null || true)"
  if [[ -n "$oldpid" && -d "/proc/$oldpid" ]]; then
    echo "Live ingest lock exists for worker $WORKER_ID PID $oldpid; refusing duplicate start" >&2
    exit 3
  fi
  rm -f "$LOCK"
fi

# Resume after the last processed symbol for this worker unless explicitly overridden.
if [[ -z "${RESUME_AFTER:-}" && -z "${START_AT_SYMBOL:-}" && -f "$STATUS" ]]; then
  RESUME_AFTER="$(/usr/bin/python3 - <<PY
import json, pathlib
p=pathlib.Path('$STATUS')
try:
    s=json.loads(p.read_text())
    print(s.get('last_processed_symbol') or s.get('last_completed_symbol') or '')
except Exception:
    print('')
PY
)"
fi
export RESUME_AFTER
export OMP_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1
export MKL_NUM_THREADS=1
export NUMEXPR_NUM_THREADS=1
export SLEEP_BETWEEN_CALLS="${SLEEP_BETWEEN_CALLS:-0.75}"

{
  echo
  echo "===== us_equities ingest launch $(date -Is) ====="
  echo "WORKER_ID=$WORKER_ID RANGE_START_INDEX=${RANGE_START_INDEX:-} RANGE_END_INDEX=${RANGE_END_INDEX:-} RESUME_AFTER=${RESUME_AFTER:-} START_AT_SYMBOL=${START_AT_SYMBOL:-} SLEEP_BETWEEN_CALLS=$SLEEP_BETWEEN_CALLS"
  echo "PID $$"
} >> "$LOG"

exec /srv/market-data-venv/bin/python /root/spy/scripts/ingest_us_equities_5m_parquet.py >> "$LOG" 2>&1
