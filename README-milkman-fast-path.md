# Milkman fast-path commands

Reusable artifact commands now live in `/root/spy/bin/`.

## Commands

```bash
/root/spy/bin/milkman-pnl-distribution --since 2026-04-21 --render
/root/spy/bin/milkman-render-png /tmp/report.html /tmp/report.png --width 1800 --height auto
/root/spy/bin/milkman-verify-live 'https://milkmantrades.com/spx-open-band-path.html?v=check' --local /root/spy/site/spx-open-band-path.html
```

## Notes

- `milkman-pnl-distribution` reads `/var/www/tradelab/index.html` and parses the embedded `<script id="trade-data">` payload.
- `milkman-render-png` uses Playwright full-page screenshots when available and falls back to `/snap/bin/chromium`.
- `milkman-verify-live` checks fetch status, SHA parity when `--local` is supplied, mobile overflow, console/page errors, and visible bad values such as `NaN` or `undefined`.
