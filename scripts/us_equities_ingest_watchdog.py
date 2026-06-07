#!/usr/bin/env python3
from __future__ import annotations
import json, os, re, subprocess, time
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT=Path('/srv/market-data/massive/us_equities')
MANIFEST=ROOT/'manifest'
SHARDS=MANIFEST/'shards'
WATCHDOG_STATE=MANIFEST/'watchdog_state.json'
CT=ZoneInfo('America/Chicago')
SOFT_BYTES=140*1024**3
HARD_BYTES=160*1024**3
STALE_MINUTES=int(os.environ.get('WATCHDOG_STALE_MINUTES','60'))
SLOW_SLEEP_CAP=float(os.environ.get('WATCHDOG_SLEEP_CAP','2.0'))

def now_utc(): return datetime.now(timezone.utc)
def iso(dt): return dt.isoformat()
def parse_dt(s):
    if not s: return None
    try: return datetime.fromisoformat(str(s).replace('Z','+00:00'))
    except Exception: return None

def age_minutes(dt):
    if not dt: return 10**9
    return max(0, (now_utc()-dt.astimezone(timezone.utc)).total_seconds()/60)

def human(n):
    if n is None: return 'n/a'
    n=float(n)
    for u in ['B','KB','MB','GB','TB']:
        if n<1024 or u=='TB': return f'{n:.1f} {u}'
        n/=1024

def sh(cmd, check=False, timeout=60):
    p=subprocess.run(cmd, text=True, capture_output=True, timeout=timeout)
    if check and p.returncode != 0:
        raise RuntimeError(f"{cmd} failed rc={p.returncode}: {p.stderr[-500:]}")
    return p.stdout.strip(), p.stderr.strip(), p.returncode

def unit(worker): return f'us-equities-ingest@{worker}.service'
def status_path(worker): return MANIFEST/f'status_{worker}.json'
def log_path(worker): return ROOT/'logs'/f'ingest_{worker}.log'
def env_path(worker): return SHARDS/f'{worker}.env'

def active(worker):
    out,_,_=sh(['systemctl','is-active',unit(worker)], timeout=15)
    return out

def load_json(path):
    try: return json.loads(path.read_text())
    except Exception: return {}

def dataset_bytes():
    out,_,rc=sh(['du','-sb',str(ROOT)], timeout=90)
    if rc == 0:
        return int(out.split()[0])
    return None

def configured_workers():
    workers=[]
    for p in sorted(SHARDS.glob('shard*.env')):
        workers.append(p.stem)
    if workers:
        return workers
    return [p.stem.replace('status_','') for p in sorted(MANIFEST.glob('status_shard*.json'))]

def get_sleep(worker):
    p=env_path(worker)
    if not p.exists(): return 0.75
    for line in p.read_text().splitlines():
        if line.startswith('SLEEP_BETWEEN_CALLS='):
            try: return float(line.split('=',1)[1].strip().strip('"'))
            except Exception: return 0.75
    return 0.75

def set_sleep(worker, value):
    p=env_path(worker)
    lines=p.read_text().splitlines() if p.exists() else []
    out=[]; done=False
    for line in lines:
        if line.startswith('SLEEP_BETWEEN_CALLS='):
            out.append(f'SLEEP_BETWEEN_CALLS={value:.2f}')
            done=True
        else:
            out.append(line)
    if not done: out.append(f'SLEEP_BETWEEN_CALLS={value:.2f}')
    p.write_text('\n'.join(out)+'\n')

def recent_rate_limit_hits(worker, minutes=60):
    p=log_path(worker)
    if not p.exists(): return 0
    cutoff=time.time()-minutes*60
    if p.stat().st_mtime < cutoff: return 0
    try:
        # Tail last 500 lines without dumping API URLs/secrets.
        out,_,_=sh(['tail','-500',str(p)], timeout=30)
    except Exception:
        return 0
    return len(re.findall(r'http_status"?:\s*429|Too Many Requests|rate limit', out, re.I))

def progress_summary():
    out,err,rc=sh(['/srv/market-data-venv/bin/python','/root/spy/scripts/us_equities_ingest_progress.py'], timeout=120)
    return out if out else err

def main():
    MANIFEST.mkdir(parents=True, exist_ok=True)
    actions=[]; warnings=[]
    workers=configured_workers()
    b=dataset_bytes()
    if b and b > HARD_BYTES:
        for w in workers:
            sh(['systemctl','stop',unit(w)], timeout=120)
        print(f"🚨 US equities ingest watchdog stopped all workers: dataset size {human(b)} exceeded hard cap {human(HARD_BYTES)}.")
        print(progress_summary())
        return
    elif b and b > SOFT_BYTES:
        warnings.append(f'dataset above soft cap: {human(b)}')

    prev=load_json(WATCHDOG_STATE)
    new_state={'checked_at_utc':iso(now_utc()),'workers':{}}

    total_429=0
    for w in workers:
        s=load_json(status_path(w))
        state=s.get('state','missing')
        upd=parse_dt(s.get('updated_at_utc'))
        stale=age_minutes(upd)
        svc=active(w)
        rc=int(s.get('range_completed_symbols') or 0)
        prev_w=(prev.get('workers') or {}).get(w, {})
        prev_rc=int(prev_w.get('range_completed_symbols') or -1)
        prev_checked=parse_dt(prev_w.get('checked_at_utc'))
        no_progress_minutes=age_minutes(prev_checked) if prev_rc == rc else 0
        hits=recent_rate_limit_hits(w)
        total_429 += hits

        if state == 'complete':
            pass
        elif svc != 'active':
            sh(['systemctl','restart',unit(w)], timeout=120)
            actions.append(f'restarted `{w}` because service was `{svc}` and state was `{state}`')
        elif stale > STALE_MINUTES and no_progress_minutes > STALE_MINUTES:
            sh(['systemctl','restart',unit(w)], timeout=120)
            actions.append(f'restarted `{w}` because status was stale {stale:.0f}m and range progress did not advance')
        elif stale > STALE_MINUTES:
            warnings.append(f'`{w}` status stale {stale:.0f}m but service active; watching')

        new_state['workers'][w]={
            'state':state,
            'service':svc,
            'range_completed_symbols':rc,
            'current_symbol':s.get('current_symbol'),
            'updated_at_utc':s.get('updated_at_utc'),
            'checked_at_utc':iso(now_utc()),
        }

    if total_429:
        old=max([get_sleep(w) for w in workers] or [0.75])
        new=min(SLOW_SLEEP_CAP, max(old+0.25, old*1.25))
        if new > old:
            for w in workers: set_sleep(w,new)
            # Do not kill healthy workers just for one 429 burst; new value applies on restart.
            actions.append(f'detected `{total_429}` recent rate-limit hits; increased future per-worker sleep from `{old:.2f}s` to `{new:.2f}s`')
        else:
            warnings.append(f'detected `{total_429}` recent rate-limit hits; sleep already at cap `{old:.2f}s`')

    WATCHDOG_STATE.write_text(json.dumps(new_state, indent=2))

    header='✅ US equities ingest watchdog: healthy'
    if actions: header='🛠️ US equities ingest watchdog: actions taken'
    elif warnings: header='⚠️ US equities ingest watchdog: warnings'
    print(header)
    print(f"Checked: {now_utc().astimezone(CT).strftime('%Y-%m-%d %I:%M %p %Z')}")
    if actions:
        print('Actions:')
        for a in actions: print(f'- {a}')
    if warnings:
        print('Warnings:')
        for w in warnings: print(f'- {w}')
    print()
    print(progress_summary())

if __name__ == '__main__':
    main()
