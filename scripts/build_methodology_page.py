#!/usr/bin/env python3
"""Render STANDALONE_TRADING_KNOWLEDGE_MANUAL.md -> site/trading-manual.html.
The public trading manual (linked from the homepage Resources section; the
same document is published at github.com/prsdro/satyland-trading-notes —
edit there, copy here, rerun). trading-methodology.html redirects here."""
from pathlib import Path

import markdown

SRC = Path('/root/spy/STANDALONE_TRADING_KNOWLEDGE_MANUAL.md')
OUT = Path('/root/spy/site/trading-manual.html')

md = markdown.Markdown(extensions=['tables', 'toc'])
body = md.convert(SRC.read_text())
toc = md.toc

page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>The Trading Manual | Milkman Trades</title>
<meta name="description" content="The full SPY/SPX trading methodology used on this site — Saty Mahajan's indicator system (ATR Levels, Pivot Ribbon, Phase Oscillator), setups, probabilities, and operating rules.">
<script src="/nav.js" defer></script>
<style>
 body{{margin:0;background:#0b0e14;color:#e5edf7;font-family:ui-sans-serif,system-ui,sans-serif;line-height:1.65;font-size:16px}}
 .wrap{{max-width:820px;margin:0 auto;padding:28px 18px 80px}}
 h1{{font-size:clamp(24px,5vw,34px);letter-spacing:-.02em;line-height:1.2;margin:.4em 0}}
 h2{{font-size:22px;margin:2.2em 0 .5em;color:#dbeafe;border-bottom:1px solid #1f2a44;padding-bottom:6px}}
 h3{{font-size:17.5px;margin:1.6em 0 .4em;color:#facc15}}
 h4{{font-size:15.5px;margin:1.4em 0 .3em;color:#93c5fd}}
 p, li{{color:#cbd7e6}}
 strong{{color:#e5edf7}} em{{color:#93a4b8}}
 hr{{border:0;border-top:1px solid #1f2a44;margin:2.2em 0}}
 ul,ol{{padding-left:1.3em}} li{{margin:6px 0}}
 table{{border-collapse:collapse;font-size:13.5px;margin:16px 0;display:block;overflow-x:auto}}
 td,th{{padding:7px 10px;border:1px solid #1f2a44;text-align:left;vertical-align:top}}
 th{{background:#0f1524;color:#93a4b8}}
 code{{background:#0f1524;border:1px solid #1f2a44;border-radius:4px;padding:1px 5px;font-size:13px}}
 a{{color:#60a5fa}}
 .lede{{color:#b6c5d8;font-size:16.5px;max-width:70ch}}
 .toc{{background:#0f1524;border:1px solid #1f2a44;border-radius:12px;padding:14px 18px;margin:22px 0;font-size:14px}}
 .toc ul{{margin:4px 0;padding-left:1.1em}} .toc>ul{{padding-left:.2em;list-style:none}}
 .toc a{{color:#93a4b8;text-decoration:none}} .toc a:hover{{color:#60a5fa}}
 .foot{{color:#7b8ba1;font-size:13px;border-top:1px solid #1f2a44;margin-top:44px;padding-top:14px}}
</style></head><body><div class="wrap">
<h1>The Trading Manual</h1>
<p class="lede">This is the complete written system behind everything on this site: Saty Mahajan's
indicator suite (ATR Levels, Pivot Ribbon, Phase Oscillator) and the level-to-level SPY/SPX framework
built on it — vocabulary, setups, historical probabilities from our own backtests, and the operating
rules used live. It is research support and trade-planning education, not financial advice.</p>
<div class="toc"><strong style="color:#dbeafe">Contents</strong>{toc}</div>
{body}
<div class="foot">Milkman Trades · methodology reference · statistics are historical SPY backtests, not certainties.
See also: <a href="/backtesting-writeup.html">backtesting, biases &amp; the Bilbo Box study story</a> ·
<a href="/bilbo-box-options.html">the Bilbo Box options study</a></div>
</div></body></html>"""
OUT.write_text(page)
print('wrote', OUT, len(page), 'bytes')
