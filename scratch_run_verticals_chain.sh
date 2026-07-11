#!/bin/bash
# Autonomous chain: wait for short-leg pull -> price verticals -> compose
# verdict -> Telegram ping. Everything logged under analyst/po_comp_options/theta.
set -x
cd /root/spy
T=/root/spy/analyst/po_comp_options/theta
export PYTHONWARNINGS=ignore

while kill -0 939358 2>/dev/null; do sleep 60; done
echo "short-leg pull finished: $(tail -3 $T/pull_short.log | head -2)"
while pgrep -f scratch_theta_zerobid_stress >/dev/null; do sleep 60; done

python3 scratch_theta_verticals.py > $T/verticals.log 2>&1 || {
  /root/.local/bin/hermes send --to telegram:7980528578 -q \
    "Bilbo verticals run FAILED - see verticals.log. Session has details."; exit 1; }

python3 - <<'PY' > $T/FINAL_DIRECTIONAL_STATUS.md 2>&1
from pathlib import Path
T = Path('/root/spy/analyst/po_comp_options/theta')
print("# Directional goal status (auto-generated)\n")
print("## Verticals (pre-registered spec, hold to end, defined risk)\n```")
print((T/'verticals.log').read_text().split('scored verticals')[-1])
print("```\n## Zero-bid stress (Codex finding #1)\n```")
zb = (T/'zerobid.log').read_text()
print(zb[zb.find('trades:'):] if 'trades:' in zb else zb[-800:])
print("```\n## Blind-selection singles (committed protocol)")
print("top-10 ex-ante picks OOS: +8.3% mean, positive 10/10 (blind_selection_grid.csv)")
PY

SUMMARY=$(python3 - <<'PY'
import re
from pathlib import Path
log = Path('/root/spy/analyst/po_comp_options/theta/verticals.log').read_text()
lines = [l for l in log.splitlines() if re.search(r'==|hold half|hold full|dist|monthly', l)]
print("BILBO DIRECTIONAL - verticals run complete.")
print("\n".join(lines[:18]))
print("Full: theta/FINAL_DIRECTIONAL_STATUS.md. Resume the 'Study continuation' session for interpretation.")
PY
)
/root/.local/bin/hermes send --to telegram:7980528578 -q "$SUMMARY"
echo "CHAIN COMPLETE"
