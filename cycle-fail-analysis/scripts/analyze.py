#!/usr/bin/env python3
"""cycle-fail-analysis: analyze mid1 failures in a replay batch."""

import json, os, re, glob, csv, sys, subprocess
from collections import defaultdict

GO_SERVICE = os.environ.get('GO_SERVICE_DIR', os.path.expanduser('~/dt_workspace/go-service'))

def run_find_path_cycle(analysis_json):
    """Run find_path_cycle and parse output."""
    result = subprocess.run(
        ['go', 'run', './cmd/replay/find_path_cycle', '-analysis_json', analysis_json],
        cwd=GO_SERVICE, capture_output=True, text=True, timeout=180
    )
    out = result.stdout + result.stderr
    entry = {'exists': False, 'cid': 0, 'hop': 0, 'minUsd': 0, 'targetPos': -1, 'inEvent': False, 'routes': []}
    for line in out.split('\n'):
        if 'exists=true' in line:
            m = re.search(r'internalCid=(\d+).*logicHopCount=(\d+).*minUsd=([\d.]+)', line)
            if m: entry['exists']=True; entry['cid']=int(m.group(1)); entry['hop']=int(m.group(2)); entry['minUsd']=float(m.group(3))
        elif 'exists=false' in line:
            m = re.search(r'routeIds=([\d,]+)', line)
            if m: entry['routeIds'] = m.group(1)
        elif 'inRefer=' in line:
            parts = line.split(',')
            rid = int(parts[0].strip())
            inRefer = 'inRefer=true' in line
            pos_m = re.search(r'pos=(-?\d+)', line)
            pos = int(pos_m.group(1)) if pos_m else -1
            entry['routes'].append({'rid': rid, 'inRefer': inRefer, 'pos': pos})
            if entry['targetPos'] == -1:
                entry['targetPos'] = pos
                entry['firstInRefer'] = inRefer
    entry['inEvent'] = entry.get('firstInRefer', False) and entry.get('targetPos', -1) >= 0 and entry.get('targetPos', -1) < 15000
    return entry

def get_target_route(per_tx_dir):
    """Extract target route from step_c.log + source_analysis.json."""
    try:
        with open(f'{per_tx_dir}/step_c.log') as f: sc = json.load(f)
        pa = sc.get('poolAddress', '')
        with open(f'{per_tx_dir}/source_analysis.json') as f: sa = json.load(f)
        for p in sa.get('targetPoolPaths', []):
            if p.get('poolAddress', '').lower() == pa.lower():
                t0 = p.get('token0', {}).get('symbol', '?')
                t1 = p.get('token1', {}).get('symbol', '?')
                return f"{p.get('dex', '?')}:{t0}->{t1}"
    except: pass
    return ''

def check_snapshot(snap_dir, short, suffix, target_cid, target_pos):
    """Check if target cycle is in a snapshot JSON file."""
    for fname in os.listdir(snap_dir):
        if short not in fname or not fname.endswith(suffix): continue
        try:
            data = json.load(open(f'{snap_dir}/{fname}'))
            if isinstance(data, list):
                for entry in data:
                    if entry.get('CycleId') == target_cid or entry.get('DuralPathIdx') == target_pos:
                        return 'YES'
                return 'NO'
        except: pass
    return '?'

def get_mid1_len(snap_dir, short):
    for fname in os.listdir(snap_dir):
        if short not in fname or not fname.endswith('_mid1_Revenue.json'): continue
        try:
            data = json.load(open(f'{snap_dir}/{fname}'))
            if isinstance(data, list): return len(data)
            if isinstance(data, dict):
                for k in ['logs_profits', 'revenue', 'data']:
                    if k in data and isinstance(data[k], list): return len(data[k])
        except: pass
    return 0

def analyze(replay_dir):
    csv_file = glob.glob(f'{replay_dir}/replay_result_*.csv')[0]
    snap_dir = f'{replay_dir}/go_replay_snapshots'
    per_tx_dir = f'{replay_dir}/per_tx'

    # Read failed txHashes
    failed = []
    with open(csv_file) as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get('eventProduced') == 'Y' and row.get('mid1Produced') == 'N':
                failed.append(row['txHash'])

    print(f"Failed mid1: {len(failed)}")

    # Analyze each
    rows = []
    for i, tx in enumerate(failed):
        short = tx[2:10]
        print(f"[{i+1}/{len(failed)}] {tx[:18]}...")

        # Find per_tx dir and source_analysis
        dirs = glob.glob(f'{per_tx_dir}/*{short}*')
        analysis_json = f'{dirs[0]}/source_analysis.json' if dirs else None

        if analysis_json and os.path.exists(analysis_json):
            e = run_find_path_cycle(analysis_json)
        else:
            e = {'exists': False, 'cid': 0, 'hop': 0, 'minUsd': 0, 'targetPos': -1, 'inEvent': False, 'routes': []}

        target_route = get_target_route(dirs[0]) if dirs else ''
        mid25 = check_snapshot(snap_dir, short, '_Mid25Revenue.json', e['cid'], e['targetPos'])
        mid25after = check_snapshot(snap_dir, short, '_Mid25Revenue.after.json', e['cid'], e['targetPos'])
        mid1_len = get_mid1_len(snap_dir, short)

        if not e['exists']: cls = 'cat3'
        elif e['inEvent']: cls = 'cat1'
        else: cls = 'cat2'

        rows.append({
            'txHash': tx, 'targetRouteId': target_route,
            'cycleExists': e['exists'], 'simulateEventHasCycle': e['inEvent'],
            'mid25HasCycle': mid25, 'mid25afterHasCycle': mid25after,
            'len_mid1': mid1_len, 'cycleHop': e['hop'], 'cycleMinUsd': e['minUsd'],
            'classification': cls
        })

    # Write CSV
    out_csv = f'{replay_dir}/mid1_fail_analysis/mid1_fail_detail.csv'
    os.makedirs(os.path.dirname(out_csv), exist_ok=True)
    with open(out_csv, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=rows[0].keys())
        w.writeheader()
        w.writerows(rows)

    # Stats
    cats = defaultdict(list)
    for r in rows: cats[r['classification']].append(r)
    print(f"\n--- Summary ---")
    print(f"Cat1 (cycle in simulateEvent): {len(cats['cat1'])}")
    print(f"Cat2 (cycle not in simulateEvent): {len(cats['cat2'])}")
    print(f"Cat3 (cycle not exist): {len(cats['cat3'])}")

    cat1_mid25 = sum(1 for r in cats['cat1'] if r['mid25HasCycle'] == 'YES')
    cat1_mid25after = sum(1 for r in cats['cat1'] if r['mid25afterHasCycle'] == 'YES')
    print(f"Cat1 mid25 YES: {cat1_mid25}, mid25.after YES: {cat1_mid25after}")
    print(f"\nDetail: {out_csv}")

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <replay_output_dir>")
        sys.exit(1)
    analyze(sys.argv[1])
