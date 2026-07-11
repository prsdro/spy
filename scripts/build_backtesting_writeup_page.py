#!/usr/bin/env python3
"""Render BACKTESTING_AND_STUDY_WRITEUP.md -> site/backtesting-writeup.html.
Unlinked page (Pedro 2026-07-08): not in nav.js or index.html on purpose."""
from pathlib import Path

import markdown

SRC = Path('/root/spy/analyst/po_comp_options/BACKTESTING_AND_STUDY_WRITEUP.md')
OUT = Path('/root/spy/site/backtesting-writeup.html')

body = markdown.markdown(SRC.read_text(), extensions=['tables'])

page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>Backtesting, Biases & the Bilbo Box Study | Milkman Trades</title>
<style>
 body{{margin:0;background:#0b0e14;color:#e5edf7;font-family:ui-sans-serif,system-ui,sans-serif;line-height:1.65;font-size:16px}}
 .wrap{{max-width:780px;margin:0 auto;padding:28px 18px 80px}}
 h1{{font-size:clamp(24px,5vw,34px);letter-spacing:-.02em;line-height:1.2;margin:.4em 0}}
 h2{{font-size:22px;margin:2em 0 .5em;color:#dbeafe;border-bottom:1px solid #1f2a44;padding-bottom:6px}}
 h3{{font-size:17.5px;margin:1.6em 0 .4em;color:#facc15}}
 p, li{{color:#cbd7e6}}
 strong{{color:#e5edf7}}
 em{{color:#93a4b8}}
 hr{{border:0;border-top:1px solid #1f2a44;margin:2.2em 0}}
 ul,ol{{padding-left:1.3em}} li{{margin:7px 0}}
 table{{border-collapse:collapse;font-size:13.5px;margin:16px 0;display:block;overflow-x:auto}}
 td,th{{padding:7px 10px;border:1px solid #1f2a44;text-align:left;vertical-align:top}}
 th{{background:#0f1524;color:#93a4b8}}
 blockquote{{border-left:3px solid #1f2a44;margin:1em 0;padding:.1em 1em;color:#93a4b8}}
 .foot{{color:#7b8ba1;font-size:13px;border-top:1px solid #1f2a44;margin-top:44px;padding-top:14px}}
 a{{color:#60a5fa}}
</style></head><body><div class="wrap">
{body}
<div class="foot">Milkman Trades · internal writeup · not linked from the homepage.
Related: <a href="/bilbo-box-options.html">the Bilbo Box options study</a> ·
<a href="/cheatsheet-bilbo-breakout.png">one-page cheat sheet</a></div>
</div></body></html>"""
OUT.write_text(page)
print('wrote', OUT, len(page), 'bytes')
