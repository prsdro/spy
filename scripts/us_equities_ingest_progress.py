#!/usr/bin/env python3
from __future__ import annotations
import csv, json, math, os, subprocess
from datetime import datetime, timezone, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT=Path('/srv/market-data/massive/us_equities')
MANIFEST=ROOT/'manifest'
STATUS=MANIFEST/'status.json'
CT=ZoneInfo('America/Chicago')

def human(n):
    if n is None: return 'n/a'
    n=float(n)
    for u in ['B','KB','MB','GB','TB']:
        if n<1024 or u=='TB': return f'{n:.1f} {u}'
        n/=1024

def parse_dt(s):
    if not s: return None
    try:
        return datetime.fromisoformat(str(s).replace('Z','+00:00'))
    except Exception:
        return None

def age_text(dt):
    if not dt: return 'n/a'
    seconds=max(0, int((datetime.now(timezone.utc)-dt.astimezone(timezone.utc)).total_seconds()))
    if seconds < 90: return f'{seconds}s ago'
    minutes=seconds//60
    if minutes < 90: return f'{minutes}m ago'
    hours=minutes//60
    if hours < 48: return f'{hours}h {minutes%60}m ago'
    days=hours//24
    return f'{days}d {hours%24}h ago'

def short_age(dt):
    txt=age_text(dt)
    if txt.endswith(' ago'):
        txt=txt[:-4]
    return txt.replace(' ', '')

def compact_stage(stage, year=None):
    stage=str(stage or '')
    replacements={
        'bars_5m_adjusted':'5m',
        'daily_and_corporate_actions':'daily+corp',
        'symbol_complete':'done',
    }
    stage=replacements.get(stage, stage)
    if year not in (None,'') and stage:
        return f'{stage} {year}'
    return stage or 'n/a'

def trim(value, width):
    value=str(value or '')
    if len(value) <= width:
        return value
    if width <= 1:
        return value[:width]
    return value[:width-1] + '…'

def markdown_table(rows):
    if not rows:
        return ''
    widths=[max(len(str(row[i])) for row in rows) for i in range(len(rows[0]))]
    return '\n'.join('  '.join(str(row[i]).ljust(widths[i]) for i in range(len(row))).rstrip() for row in rows)

def dur(seconds):
    if seconds is None or not math.isfinite(seconds): return 'n/a'
    seconds=max(0,int(seconds)); d,rem=divmod(seconds,86400); h,rem=divmod(rem,3600); m,_=divmod(rem,60)
    if d: return f'{d}d {h}h {m}m'
    if h: return f'{h}h {m}m'
    return f'{m}m'

def dataset_bytes():
    try:
        out=subprocess.check_output(['du','-sb',str(ROOT)], text=True, timeout=60).split()[0]
        return int(out)
    except Exception:
        vals=[]
        for p in MANIFEST.glob('status*.json'):
            try: vals.append(int(json.loads(p.read_text()).get('dataset_bytes') or 0))
            except Exception: pass
        return max(vals) if vals else None

def unit_active(worker):
    try:
        svc=f'us-equities-ingest@{worker}.service'
        out=subprocess.run(['systemctl','is-active',svc], text=True, capture_output=True, timeout=10)
        return out.stdout.strip()
    except Exception:
        return 'unknown'

def load_shard_statuses():
    rows=[]
    for p in sorted(MANIFEST.glob('status_shard*.json')):
        try:
            s=json.loads(p.read_text())
            s['_path']=str(p)
            rows.append(s)
        except Exception:
            pass
    return rows

def single_progress():
    if not STATUS.exists():
        print('## Market data ingest progress\n\n⚠️ No status file found yet. Ingest may not have started.')
        return
    s=json.loads(STATUS.read_text())
    pid=s.get('pid')
    alive=bool(pid and Path(f'/proc/{pid}').exists())
    state=s.get('state','unknown')
    total=int(s.get('total_symbols') or 0)
    done=int(s.get('completed_symbols') or 0)
    pct=(done/total*100) if total else 0
    updated=parse_dt(s.get('updated_at_utc'))
    updated_ct=updated.astimezone(CT).strftime('%Y-%m-%d %I:%M:%S %p %Z') if updated else 'n/a'
    current=s.get('current_symbol','')
    stage=s.get('current_stage','')
    year=s.get('current_year','')
    last=s.get('last_completed_symbol','') or s.get('last_processed_symbol','')
    msg=['## Market data ingest progress', '', '**Summary**']
    if state not in ('running',) or not alive:
        msg.append('- Status: ⚠️ not running')
        msg.append(f"- State: `{state}`; PID `{pid}`; alive `{alive}`")
        msg.append(f"- Last completed: `{last}`; current `{current}`")
    else:
        detail=compact_stage(stage, year)
        msg.append('- Status: 🟢 running')
        msg.append(f"- State: `{state}`; PID `{pid}`; current `{current}`")
        msg.append(f"- Stage: `{detail}`")
        msg.append(f"- Last completed: `{last}`")
    msg.append(f"- Symbols: `{done}/{total}` (`{pct:.1f}%`)")
    msg.append(f"- Failures: `{s.get('failures',0)}`")
    msg.append(f"- Dataset: `{human(s.get('dataset_bytes'))}`; caps `140 GB` soft / `160 GB` hard")
    msg.append(f"- Updated: `{updated_ct}` (`{age_text(updated)}`)")
    if s.get('last_error'):
        msg.append(f"- Last error: `{str(s.get('last_error'))[:180]}`")
    print('\n'.join(msg))

def shard_progress():
    statuses=load_shard_statuses()
    if not statuses:
        return False
    total=max(int(s.get('total_symbols') or 0) for s in statuses)
    min_start=min(int(s.get('range_start_index') or 0) for s in statuses)
    processed=0; failures=0; active=0; complete=0
    starts=[]; updates=[]
    rows=[('Status','Shard','Done','State','Cur','Stage','Last','Updated')]
    for s in statuses:
        worker=s.get('worker_id','?')
        rs=int(s.get('range_start_index') or 0); re=int(s.get('range_end_index') or rs); rt=max(0,re-rs)
        rc=int(s.get('range_completed_symbols') if s.get('range_completed_symbols') is not None else max(0,int(s.get('completed_symbols') or rs)-rs))
        rc=max(0,min(rt,rc)); processed += rc
        failures += int(s.get('failures') or 0)
        state=s.get('state','unknown')
        pid=s.get('pid'); alive=bool(pid and Path(f'/proc/{pid}').exists())
        if state == 'complete': complete += 1
        if state == 'running' and alive: active += 1
        updated=parse_dt(s.get('updated_at_utc'))
        started=parse_dt(s.get('started_at_utc'))
        if started: starts.append(started)
        if updated: updates.append(updated)
        stage=s.get('current_stage') or ''
        year=s.get('current_year')
        detail=compact_stage(stage, year)
        cur=s.get('current_symbol') or ''
        last=s.get('last_processed_symbol') or s.get('last_completed_symbol') or ''
        status_icon='OK' if state=='complete' else ('RUN' if state=='running' and alive else 'WARN')
        rows.append((status_icon, worker, f'{rc}/{rt}', trim(state, 8), trim(cur, 8), trim(detail, 14), trim(last, 8), short_age(updated)))
    done=min_start+processed
    remaining=max(0,total-done)
    pct=(done/total*100) if total else 0
    now=datetime.now(timezone.utc)
    eta_txt='n/a'; done_at='n/a'; rate_txt='n/a'
    if starts:
        elapsed=(now-min(starts)).total_seconds()
        if elapsed > 60 and processed > 0:
            rate=processed/elapsed
            rate_txt=f'{rate*3600:.0f} symbols/hour'
            eta=remaining/rate if rate else None
            eta_txt=dur(eta)
            done_at=(now+timedelta(seconds=eta)).astimezone(CT).strftime('%Y-%m-%d %I:%M %p %Z') if eta else 'n/a'
    latest=max(updates) if updates else None
    msg=[]
    msg.append('## US equities ingest watchdog/progress')
    msg.append('')
    msg.append('**Summary**')
    msg.append(f"- Workers: `{active}` running / `{complete}` complete / `{len(statuses)}` total")
    msg.append(f"- Symbols: `{done}/{total}` (`{pct:.1f}%`), remaining `{remaining}`")
    msg.append(f"- Rate: `{rate_txt}`, ETA `{eta_txt}`, done `{done_at}`")
    msg.append(f"- Failures: `{failures}`, data `{human(dataset_bytes())}`, latest update `{age_text(latest)}`")
    msg.append('')
    msg.append('**Shards**')
    msg.append('```')
    msg.append(markdown_table(rows))
    msg.append('```')
    print('\n'.join(msg))
    return True

def main():
    if not shard_progress():
        single_progress()
if __name__=='__main__': main()
