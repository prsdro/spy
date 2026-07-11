#!/bin/bash
cd /root/spy
env PYTHONWARNINGS=ignore python3 scratch_theta_grid_pull.py >> analyst/po_comp_options/theta/grid_pull2.log 2>&1
if grep -q "GRID PULL COMPLETE" analyst/po_comp_options/theta/grid_pull2.log; then
  /root/.local/bin/hermes send --to telegram:7980528578 -q "Bilbo surface GRID PULL COMPLETE (12 cells x 3,833 trades, Pro tier). Resume the Claude Code session on the server to run the surface analysis: cd /root/spy && claude --resume (pick 'Study continuation'). Or reply here if Hermes can exec: claude -p --resume <session> 'run the surface analysis'"
else
  /root/.local/bin/hermes send --to telegram:7980528578 -q "Bilbo grid pull STOPPED EARLY - check analyst/po_comp_options/theta/grid_pull2.log on the server. It is restartable: bash /root/spy/scratch_run_gridpull.sh"
fi
