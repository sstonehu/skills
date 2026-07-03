#!/usr/bin/env python3
"""
cycle-fail-analysis: analyze mid1 failures in a replay batch.

Produces 3 output files in the batch directory:
  - mid1_target_cycle.json         — per-TX cycle/path structured data
  - mid1_target_cycle.csv          — 12-col CSV (txHash..poolIds)
  - mid1_fail_detail_v3_classified.csv — 17-col CSV (txHash..routeIds)

Usage:
  python3 analyze.py <replay_output_dir>
"""

import json, os, re, glob, csv, sys, subprocess, tempfile, shutil
from collections import defaultdict

# ── Path detection ────────────────────────────────────────────────────

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(SCRIPT_DIR)           # .../cycle-fail-analysis
SKILLS_DIR = os.path.dirname(SKILL_DIR)            # .../skills
DOT_CLAUDE = os.path.dirname(SKILLS_DIR)           # .../.claude

def detect_go_service():
    gsd = os.environ.get('GO_SERVICE_DIR', '')
    if gsd and os.path.isdir(os.path.join(gsd, 'cmd', 'replay')):
        return gsd
    # Walk up from .claude: .claude/../go-service = dt_workspace/go-service
    candidate = os.path.join(DOT_CLAUDE, '..', 'go-service')
    candidate = os.path.abspath(candidate)
    if os.path.isdir(os.path.join(candidate, 'cmd', 'replay')):
        return candidate
    candidate = os.path.expanduser('~/dt_workspace/go-service')
    if os.path.isdir(os.path.join(candidate, 'cmd', 'replay')):
        return candidate
    return None

GO_SERVICE = detect_go_service()
CORRECTOR = os.path.join(SKILLS_DIR, 'txhash-path-cycle-check', 'scripts', 'correct_cycle_order.py')
FIND_CYCLE_BATCH = os.path.join(GO_SERVICE, 'cmd', 'replay', 'find_path_cycle_batch') if GO_SERVICE else None
CONF_DIR = os.path.join(GO_SERVICE, 'conf') if GO_SERVICE else None

def detect_go_config_dir():
    gdir = os.environ.get('GO_CONFIG_DIR', '').strip()
    if gdir and os.path.isdir(gdir):
        return gdir
    if GO_SERVICE:
        env_path = os.path.join(GO_SERVICE, '.env')
        if os.path.exists(env_path):
            with open(env_path) as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#') or '=' not in line:
                        continue
                    key, val = line.split('=', 1)
                    if key.strip() != 'GO_CONFIG_DIR':
                        continue
                    val = val.strip().strip("'").strip('\"')
                    if val and os.path.isdir(val):
                        return val
    return CONF_DIR

PRECOMPUTED_DIR = detect_go_config_dir()

# ── Helpers ───────────────────────────────────────────────────────────

def read_json(path):
    if not path or not os.path.exists(path): return None
    with open(path) as f: return json.load(f)

def find_snapshot(snap_dir, short, suffix):
    if not os.path.isdir(snap_dir): return None
    for f in os.listdir(snap_dir):
        if short in f and f.endswith(suffix):
            return os.path.join(snap_dir, f)
    return None

def pool_key(p):
    """poolId if non-empty, else poolAddress."""
    pid = p.get('poolId', '') or p.get('pool_id', '')
    if pid.strip(): return pid
    return p.get('poolAddress', '') or p.get('pool_address', '')

def get_token_direction(p):
    """Extract from -> to with correct direction from a pool path dict."""
    ti = p.get('token0In', True)
    t0 = p.get('token0', {})
    t1 = p.get('token1', {})
    if ti:
        fr, to = t0.get('symbol', '?'), t1.get('symbol', '?')
    else:
        fr, to = t1.get('symbol', '?'), t0.get('symbol', '?')
    return fr, to

def batch_index_from_dir(per_tx_dir, fallback):
    if not per_tx_dir:
        return fallback
    m = re.match(r'^(\d+)_', os.path.basename(per_tx_dir))
    if not m:
        return fallback
    return int(m.group(1)) - 1

# ── Parse find_path_cycle_batch output ─────────────────────────────────

def run_find_path_cycle_batch(per_tx_dirs):
    """Run find_path_cycle_batch Go binary once for all dirs.
    Returns dict: short -> {matchKind, cycleId, minUsd, routeRefer: [{routeId,dex,poolKey,from,to,pos,referLen,lastHop,lastMinUsd},...]}"""
    if not FIND_CYCLE_BATCH or not GO_SERVICE:
        print("ERROR: cannot find go-service", file=sys.stderr)
        return {}
    dirs_arg = ','.join(per_tx_dirs)
    result = subprocess.run(
        ['go', 'run', './cmd/replay/find_path_cycle_batch', '-dirs', dirs_arg,
         '-confDir', PRECOMPUTED_DIR],
        cwd=GO_SERVICE, capture_output=True, text=True, timeout=300
    )
    out = result.stdout + result.stderr

    # Parse tabular output with regex (fixed-width unreliable due to variable padding).
    # Format: short(8hex) whitespace n_pools(int) whitespace matchKind whitespace [cycleId] [route_refer_path]
    # Example: f4a4eb88     3       found              733697240(57$) 84304 uniswapV4 ... | ...
    results = {}
    for line in out.split('\n'):
        line = line.rstrip()
        if not line.strip():
            continue
        m = re.match(
            r'^([0-9a-f]{8})\s+(\d+)\s+(\S+)\s*'  # short, n_pools, matchKind
            r'(?:(\d+)\((\d+)\$\))?\s*'              # optional cycleId(minUsd$)
            r'(.*)$',                                 # route_refer_path (rest)
            line
        )
        if not m:
            continue
        short = m.group(1)
        n_pools = int(m.group(2))
        match_kind = m.group(3).rstrip()
        cycle_id_str = m.group(4)
        min_usd_str = m.group(5)
        route_refer_str = m.group(6).strip()

        cycle_id = int(cycle_id_str) if cycle_id_str else 0
        min_usd = float(min_usd_str) if min_usd_str else 0.0
        cycle_route_ids = []
        cm = re.search(r'\bcycleRoutes=([0-9,]+)', route_refer_str)
        if cm:
            cycle_route_ids = [int(x) for x in cm.group(1).split(',') if x]
            route_refer_str = re.sub(r'\s*\|?\s*cycleRoutes=[0-9,]+\s*\|?\s*', ' | ', route_refer_str).strip(' |')

        route_refers = []
        for segment in route_refer_str.split('|'):
            seg = segment.strip()
            if not seg:
                continue
            tokens = seg.split()
            if len(tokens) < 5:
                continue
            try:
                rid = int(tokens[0])
            except ValueError:
                continue
            dex = tokens[1]
            pool_key_val = tokens[2]
            pair = tokens[3]
            ref_str = tokens[4] if len(tokens) > 4 else '-1_0_0_0.00'
            fr_to = pair.split('->')
            fr = fr_to[0] if len(fr_to) > 0 else '?'
            to = fr_to[1] if len(fr_to) > 1 else '?'
            ref_parts = ref_str.split('_')
            try:
                pos = int(ref_parts[0]) if len(ref_parts) > 0 else -1
                ref_len = int(ref_parts[1]) if len(ref_parts) > 1 else 0
                last_hop = int(ref_parts[2]) if len(ref_parts) > 2 else 0
                last_min = float(ref_parts[3]) if len(ref_parts) > 3 else 0.0
            except (ValueError, IndexError):
                pos, ref_len, last_hop, last_min = -1, 0, 0, 0.0
            route_refers.append({
                'routeId': rid, 'dex': dex, 'poolKey': pool_key_val,
                'from': fr, 'to': to,
                'pos': pos, 'referLen': ref_len, 'lastHop': last_hop, 'lastMinUsd': last_min,
            })

        results[short] = {
            'nPools': n_pools, 'matchKind': match_kind,
            'cycleId': cycle_id, 'minUsd': min_usd,
            'cycleRouteIds': cycle_route_ids,
            'routeRefer': route_refers,
        }
    return results

# ── Run correct_cycle_order for one TX ─────────────────────────────────

def run_correct_cycle_order(short, tx_hash, tmp_dir):
    """Create temp identify dir and run correct_cycle_order --rich.
    Returns list of corrected leg dicts, or None on failure."""
    identify_dir = os.path.join(tmp_dir, 'identify')
    report_path = os.path.join(tmp_dir, 'path_cycle_report.txt')
    if not os.path.exists(report_path):
        return None
    os.makedirs(identify_dir, exist_ok=True)

    result = subprocess.run(
        ['python3', CORRECTOR, tmp_dir, '--config-dir', CONF_DIR,
         '--rich', '--tx-hash', tx_hash],
        capture_output=True, text=True, timeout=30
    )
    if result.returncode != 0:
        return None

    # Parse rich CSV output
    lines = result.stdout.strip().split('\n')
    if len(lines) < 2:
        return None

    legs = []
    reader = csv.DictReader(lines)
    for row in reader:
        legs.append({
            'routeId': int(row.get('routeId', -1)),
            'dex': row.get('dex', '?'),
            'poolId': row.get('poolId', ''),
            'from': row.get('from', '?'),
            'to': row.get('to', '?'),
            'inCycle': row.get('inCycle', 'false') == 'true',
            'isReordered': row.get('isReordered', 'false') == 'true',
            'cycleId': int(row.get('cycleId', -1)),
        })

    is_reordered = legs[0]['isReordered'] if legs else False
    cycle_id = legs[0]['cycleId'] if legs else -1
    return {'legs': legs, 'isReordered': is_reordered, 'cycleId': cycle_id}

# ── Build identify + report temp files for correct_cycle_order ─────────

def build_temp_identify_data(tmp_dir, short, sa, batch_result):
    """Write identify/target_path_analysis.json and path_cycle_report.txt
    into tmp_dir for correct_cycle_order consumption.

    IMPORTANT: find_path_cycle_batch may reorder paths internally.
    We must align route_refers to targetPoolPaths by pool key so
    correct_cycle_order maps routeIds correctly."""
    identify_dir = os.path.join(tmp_dir, 'identify')
    os.makedirs(identify_dir, exist_ok=True)

    # target_path_analysis.json — from source_analysis.json (authoritative order)
    identify_paths = sa.get('targetPoolPaths', [])
    analysis = {
        'txHash': sa.get('txHash', ''),
        'targetBlockNumber': sa.get('targetBlockNumber', ''),
        'targetTxIndex': sa.get('targetTxIndex', ''),
        'targetLogCount': sa.get('targetLogCount', len(identify_paths)),
        'poolPathCount': len(identify_paths),
        'targetPoolPaths': identify_paths,
    }
    with open(os.path.join(identify_dir, 'target_path_analysis.json'), 'w') as f:
        json.dump(analysis, f, indent=2)

    br = batch_result or {}
    route_refers = br.get('routeRefer', [])
    match_kind = br.get('matchKind', '?')
    cycle_id = br.get('cycleId', 0)
    min_usd = br.get('minUsd', 0.0)
    n_pools = br.get('nPools', len(route_refers))

    # Map batch matchKind to report format
    if match_kind == 'found':
        report_mk = 'found'; report_exists = 'true'
    elif match_kind == 'not_in_store':
        report_mk = 'no_cycle_match'; report_exists = 'false'
    elif match_kind.startswith('open_path'):
        report_mk = 'no_cycle_match'; report_exists = 'false'
    elif match_kind.startswith('no_route'):
        report_mk = 'no_route'; report_exists = 'false'
    else:
        report_mk = match_kind; report_exists = 'false'

    # Build a pool-key → routeRefer lookup
    rr_by_pool = {}
    for rr in route_refers:
        key = rr['poolKey'].lower()
        rr_by_pool[key] = rr

    # Align route_refers to identify_paths order by pool key
    aligned = []
    for p in identify_paths:
        key = (p.get('poolId', '') or p.get('poolAddress', '')).lower()
        fr, to = get_token_direction(p)
        if key in rr_by_pool:
            rr = rr_by_pool[key]
            aligned.append({
                'dex': p.get('dex', rr.get('dex', '?')),
                'poolKey': key,
                'from': fr, 'to': to,
                'routeId': rr['routeId'],
                'pos': rr['pos'], 'referLen': rr['referLen'],
                'lastHop': rr['lastHop'], 'lastMinUsd': rr['lastMinUsd'],
            })
        else:
            # Leg not found in batch routeRefer — use -1
            aligned.append({
                'dex': p.get('dex', '?'), 'poolKey': key,
                'from': fr, 'to': to,
                'routeId': -1, 'pos': -1, 'referLen': 0,
                'lastHop': 0, 'lastMinUsd': 0.0,
            })

    # Use aligned list for report if it has data, else fallback to batch order
    use_route_refers = aligned if aligned else route_refers

    lines = []
    lines.append("1. 路径：")
    for rr in use_route_refers:
        lines.append(f"{rr['dex']}, {rr['poolKey']}, {rr['from']} -> {rr['to']}, {rr['routeId']}, 0.00")

    lines.append("")
    lines.append("2. cycle 在 CycleStore 中是否存在")
    if report_exists == 'true':
        lines.append(f"exists=true, internalCid={cycle_id}, logicHopCount={n_pools}, phase=1, minUsd={min_usd}")
    else:
        rids_str = ','.join(str(rr['routeId']) for rr in use_route_refers)
        lines.append(f"exists=false, routeIds={rids_str}, mismatchKind={report_mk}, legCount={len(use_route_refers)}")

    lines.append("")
    lines.append("3. 各 route 的 refer 中是否包含此 cycle")
    for rr in use_route_refers:
        in_ref = rr['pos'] >= 0
        lines.append(f"{rr['routeId']}, inRefer={'true' if in_ref else 'false'}, pos={rr['pos']}, len(refer)={rr['referLen']}, lastHop={rr['lastHop']}, lastMinUsd={rr['lastMinUsd']:.2f}")

    with open(os.path.join(tmp_dir, 'path_cycle_report.txt'), 'w') as f:
        f.write('\n'.join(lines))

    # Return aligned route_refers for downstream use (avoids re-parsing)
    return use_route_refers

# ── Main analyze ───────────────────────────────────────────────────────

def analyze(replay_dir):
    batch_dir = os.path.abspath(replay_dir)

    # Find replay result CSV
    csv_files = glob.glob(os.path.join(batch_dir, 'replay_result_*.csv'))
    if not csv_files:
        print(f"ERROR: no replay_result_*.csv in {batch_dir}", file=sys.stderr)
        sys.exit(1)
    csv_file = csv_files[0]

    snap_dir = os.path.join(batch_dir, 'go_replay_snapshots')
    per_tx_base = os.path.join(batch_dir, 'per_tx')

    # Read failed TXs. Include rows where event was not produced, because these
    # still represent mid1 failures in the batch-level replay result.
    failed = []
    failed_batch_index = {}
    with open(csv_file) as f:
        for batch_idx, row in enumerate(csv.DictReader(f)):
            if row.get('mid1Produced') != 'Y':
                tx = row['txHash']
                failed.append(tx)
                failed_batch_index[tx] = batch_idx

    print(f"Failed mid1: {len(failed)}")
    if not failed:
        # Produce empty output files
        for fname in ['mid1_target_cycle.json', 'mid1_target_cycle.csv', 'mid1_fail_detail_v3_classified.csv']:
            path = os.path.join(batch_dir, fname)
            with open(path, 'w') as f:
                if fname.endswith('.json'): f.write('[]')
                elif fname.endswith('.csv'): f.write('txHash\n')
        print("No failed TXs. Empty outputs written.")
        return

    # Map short hash -> full hash, per_tx_dir
    tx_map = {}  # short -> {full, per_tx_dir}
    per_tx_dirs = []
    for tx in failed:
        short = tx[2:10]
        dirs = glob.glob(os.path.join(per_tx_base, f'*{short}*'))
        per_tx_dir = dirs[0] if dirs else None
        tx_map[short] = {'full': tx, 'per_tx_dir': per_tx_dir}
        if per_tx_dir:
            per_tx_dirs.append(per_tx_dir)

    # ── Step A: Run find_path_cycle_batch once ──
    batch_results = {}
    if per_tx_dirs and GO_SERVICE:
        print("Running find_path_cycle_batch...")
        batch_results = run_find_path_cycle_batch(per_tx_dirs)
        print(f"  Got results for {len(batch_results)} TXs")

    # ── Step B: Process each TX ──
    rows = []
    for i, tx in enumerate(failed):
        short = tx[2:10]
        print(f"[{i+1}/{len(failed)}] {tx[:18]}...")

        per_tx_dir = tx_map[short]['per_tx_dir']
        sa_path = os.path.join(per_tx_dir, 'source_analysis.json') if per_tx_dir else None
        sa = read_json(sa_path) if sa_path else None

        br = batch_results.get(short, {})
        match_kind = br.get('matchKind', '?')
        # Normalize for classification
        if match_kind == 'found' or match_kind == 'not_in_store':
            cycle_exists = (match_kind == 'found')
        elif match_kind.startswith('open_path'):
            cycle_exists = False
        elif match_kind.startswith('no_route'):
            cycle_exists = False
        elif match_kind == 'empty':
            cycle_exists = False
        else:
            cycle_exists = False
        cycle_id_val = br.get('cycleId', 0) if cycle_exists else -1
        route_refers = br.get('routeRefer', [])

        # Extract legCount / poolPathCount
        identify_paths = sa.get('targetPoolPaths', []) if sa else []
        pool_path_count = len(identify_paths)
        log_count = sa.get('targetLogCount', pool_path_count) if sa else 0
        leg_count = len(route_refers)
        logic_hop_count = br.get('nPools', leg_count)

        # blockNumber / txIndex
        block_number = sa.get('targetBlockNumber', '') if sa else ''
        tx_index = failed_batch_index.get(tx, batch_index_from_dir(per_tx_dir, i))

        # Run correct_cycle_order to get corrected order
        corrected_data = None
        is_reordered = False
        # Align batch route_refers to identify_paths order, then run correct_cycle_order
        aligned_route_refers = route_refers  # default: use batch order
        if identify_paths and per_tx_dir and route_refers:
            with tempfile.TemporaryDirectory() as tmp_dir:
                aligned = build_temp_identify_data(tmp_dir, short, sa, br)
                if aligned:
                    aligned_route_refers = aligned
                corrected_data = run_correct_cycle_order(short, tx, tmp_dir)
                if corrected_data:
                    is_reordered = corrected_data.get('isReordered', False)
                    # Update cycleId from correct_cycle_order (authoritative)
                    if corrected_data.get('cycleId', -1) > 0:
                        cycle_id_val = corrected_data['cycleId']

        # Determine which legs to use for output (corrected if available, else aligned route_refers, else identify_paths)
        output_legs = []
        if corrected_data and corrected_data.get('legs'):
            corrected_legs = corrected_data['legs']
            rr_map = {rr['routeId']: rr for rr in aligned_route_refers}
            for cl in corrected_legs:
                rid = cl['routeId']
                rr = rr_map.get(rid, {})
                output_legs.append({
                    'routeId': rid,
                    'dex': cl.get('dex', '?'),
                    'poolId': cl.get('poolId', ''),
                    'from': cl.get('from', '?'),
                    'to': cl.get('to', '?'),
                    'inCycle': cl.get('inCycle', False),
                    'pos': rr.get('pos', -1),
                    'referLen': rr.get('referLen', 0),
                    'lastHop': rr.get('lastHop', 0),
                    'lastMinUsd': rr.get('lastMinUsd', 0.0),
                })
        elif aligned_route_refers:
            output_legs = [{
                'routeId': rr['routeId'], 'dex': rr.get('dex', rr.get('Dex', '?')),
                'poolId': rr.get('poolId', rr.get('poolKey', '')),
                'from': rr.get('from', rr.get('FromSymbol', '?')),
                'to': rr.get('to', rr.get('ToSymbol', '?')),
                'inCycle': False, 'pos': rr.get('pos', -1),
                'referLen': rr.get('referLen', rr.get('Len', 0)),
                'lastHop': rr.get('lastHop', 0),
                'lastMinUsd': rr.get('lastMinUsd', 0.0),
            } for rr in aligned_route_refers]
        else:
            # Fallback: use identify_paths directly (routeId=-1 for unknown)
            for p in identify_paths:
                fr, to = get_token_direction(p)
                output_legs.append({
                    'routeId': -1,
                    'dex': p.get('dex', '?'),
                    'poolId': pool_key(p),
                    'from': fr, 'to': to,
                    'inCycle': False,
                    'pos': -1, 'referLen': 0, 'lastHop': 0, 'lastMinUsd': 0.0,
                })

        # targetRoute
        target_route = ''
        sc_path = os.path.join(per_tx_dir, 'step_c.log') if per_tx_dir else None
        sc = read_json(sc_path)
        if sc and identify_paths:
            tid = sc.get('poolId', '') or sc.get('poolAddress', '')
            for p in identify_paths:
                pid = p.get('poolId', '') or p.get('poolAddress', '')
                if pid and tid and pid.lower() == tid.lower():
                    fr, to = get_token_direction(p)
                    target_route = f"{p.get('dex', '?')}:{fr}->{to}"
                    break

        # dp_evt (volume)
        dp_evt = ''
        se_path = find_snapshot(snap_dir, short, '_simulatorEvent.json')
        se = read_json(se_path)
        if se and isinstance(se, list):
            # Find matching DuralPathIdx
            for entry in se:
                # Just get the first one's volume if available
                vol = entry.get('Volume', entry.get('volume', '')) or entry.get('UsdVolume', entry.get('usdVolume', ''))
                if vol:
                    dp_evt = str(vol)
                    break
        if not dp_evt:
            # Fallback: targetUsdVolume from step_d log
            sd_path = os.path.join(per_tx_dir, 'step_d_replay.log') if per_tx_dir else None
            if sd_path and os.path.exists(sd_path):
                with open(sd_path) as f:
                    for line in f:
                        m = re.search(r'volume=([0-9.]+)', line)
                        if m:
                            dp_evt = m.group(1)
                            break
        if not dp_evt and sa:
            for bm in sa.get('blockMatches', []):
                bp = bm.get('blockPath', {})
                amt = bp.get('amountIn', '0')
                t0 = bp.get('token0', {})
                dec = t0.get('decimals', 18)
                try:
                    dp_evt = str(float(amt) / (10 ** dec))
                except:
                    dp_evt = amt
                break

        # mid25 / mid25.after / mid1 counts + best
        m25_cnt = '0'
        m25a_cnt = '0'
        m1_cnt = '0'
        best_val = '0'

        m25_path = find_snapshot(snap_dir, short, '_Mid25Revenue.json')
        m25_data = read_json(m25_path)
        if m25_data:
            if isinstance(m25_data, list): m25_cnt = str(len(m25_data))
            elif isinstance(m25_data, dict): m25_cnt = str(len(m25_data))

        m25a_path = find_snapshot(snap_dir, short, 'Mid25Revenue.after.json')
        m25a_data = read_json(m25a_path)
        if m25a_data:
            if isinstance(m25a_data, list): m25a_cnt = str(len(m25a_data))
            elif isinstance(m25a_data, dict): m25a_cnt = str(len(m25a_data))

        m1_path = find_snapshot(snap_dir, short, '_mid1_Revenue.json')
        m1_data = read_json(m1_path)
        if m1_data:
            if isinstance(m1_data, list): m1_cnt = str(len(m1_data))
            elif isinstance(m1_data, dict): m1_cnt = str(len(m1_data))

        # Check step_d log for best= and early failures
        sd_path = os.path.join(per_tx_dir, 'step_d_replay.log') if per_tx_dir else None
        sd_text = ''
        if sd_path and os.path.exists(sd_path):
            with open(sd_path) as f:
                sd_text = f.read()
            for line in sd_text.split('\n'):
                m = re.search(r'best=(\d+)', line)
                if m:
                    best_val = m.group(1)
                    break

        # Handle missing replay log
        if not sd_text.strip():
            m25_cnt = '?'; m25a_cnt = '?'
        elif 'SeedOut' not in sd_text:
            m25_cnt = '0'; m25a_cnt = '0'; m1_cnt = '0'

        if 'mid1_Revenue' not in sd_text and sd_text.strip():
            m1_cnt = '0'

        # Classification
        if cycle_exists:
            new_cls = 'X_no_success'
        elif match_kind.startswith('no_route'):
            new_cls = 'X_no_route'
        elif not sd_text.strip() and not identify_paths:
            new_cls = 'X_no_block'
        else:
            new_cls = 'X_no_cycle'

        orig_cls = 'X1'
        if not sd_text.strip():
            orig_cls = '?'

        # Determine hop: logicHopCount if cycle exists else legCount, fallback to nPools/identify count
        if cycle_exists:
            hop = logic_hop_count if logic_hop_count > 0 else len(aligned_route_refers or identify_paths)
        elif aligned_route_refers:
            hop = len(aligned_route_refers)
        else:
            hop = br.get('nPools', len(identify_paths))
        legs_field = hop

        rows.append({
            'txHash': tx, 'short': short, 'blockNumber': block_number,
            'idx': tx_index, 'logCount': log_count, 'poolPathCount': pool_path_count,
            'legs': legs_field, 'legCount': leg_count, 'logicHopCount': logic_hop_count,
            'isReordered': is_reordered,
            'cycleExists': cycle_exists, 'mismatchKind': match_kind,
            'cycleId': cycle_id_val, 'minUsd': br.get('minUsd', 0.0),
            'cycleRouteIds': br.get('cycleRouteIds', []),
            'targetRoute': target_route, 'dp_evt': dp_evt,
            'm25_cnt': m25_cnt, 'm25a_cnt': m25a_cnt, 'm1_cnt': m1_cnt,
            'best_val': best_val, 'orig_cls': orig_cls,
            'new_cls': new_cls, 'outputLegs': output_legs,
        })

    # ── Step C: Write mid1_target_cycle.json ──
    json_out = os.path.join(batch_dir, 'mid1_target_cycle.json')
    json_data = []
    for r in rows:
        entry = {
            'txHash': r['txHash'], 'blockNumber': r['blockNumber'],
            'idx': r['idx'], 'logCount': r['logCount'],
            'poolPathCount': r['poolPathCount'], 'legCount': r['legCount'],
            'logicHopCount': r['logicHopCount'], 'isReordered': r['isReordered'],
            'cycleExists': r['cycleExists'], 'mismatchKind': r['mismatchKind'],
            'cycleId': r['cycleId'], 'minUsd': r['minUsd'],
            'cycleRouteIds': [l['routeId'] for l in r['outputLegs'] if l.get('inCycle')],
            'targetRoute': r['targetRoute'], 'dp_evt': r['dp_evt'],
            'mid25Count': r['m25_cnt'], 'mid25afterCount': r['m25a_cnt'],
            'mid1Count': r['m1_cnt'], 'best': r['best_val'],
            'new_cls': r['new_cls'],
            'paths': [{
                'routeId': l['routeId'], 'dex': l['dex'],
                'poolId': l['poolId'], 'from': l['from'], 'to': l['to'],
                'inCycle': l['inCycle'],
                'pos': l['pos'], 'referLen': l['referLen'],
                'lastHop': l['lastHop'], 'lastMinUsd': l['lastMinUsd'],
            } for l in r['outputLegs']],
        }
        json_data.append(entry)
    with open(json_out, 'w') as f:
        json.dump(json_data, f, indent=2)
    print(f"\nGenerated: {json_out}")

    # ── Step D: Write mid1_target_cycle.csv ──
    csv_cycle = os.path.join(batch_dir, 'mid1_target_cycle.csv')
    with open(csv_cycle, 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['txHash', 'blockNumber', 'idx', 'logCount', 'poolPathCount',
                     'legs', 'reordered', 'cycleExists', 'mismatchKind', 'cycleRouteIds',
                     'pathDetail', 'poolIds'])
        for r in rows:
            path_parts = []
            pool_ids = []
            for l in r['outputLegs']:
                path_parts.append(f"{l['dex']}:{l['from']}->{l['to']}")
                pool_ids.append(l['poolId'])
            cycle_legs = [l for l in r['outputLegs'] if l.get('inCycle')]
            route_ids = [l['routeId'] for l in cycle_legs]
            rids_str = ','.join(str(rid) for rid in route_ids) + (',' if route_ids else '')
            w.writerow([r['txHash'], r['blockNumber'], r['idx'], r['logCount'],
                         r['poolPathCount'], r['legs'],
                         str(r['isReordered']).lower(),
                         str(r['cycleExists']).lower(),
                         r['mismatchKind'], rids_str,
                         ' | '.join(path_parts), ' | '.join(pool_ids)])
    print(f"Generated: {csv_cycle}")

    # ── Step E: Write mid1_fail_detail_v3_classified.csv ──
    csv_v3 = os.path.join(batch_dir, 'mid1_fail_detail_v3_classified.csv')
    with open(csv_v3, 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['txHash', 'idx', 'short', 'hop', 'cycleId', 'targetRoute',
                     'dp_evt', 'mid25', 'after', 'mid1', 'best', 'minUsd',
                     'orig_cls', 'matchKind', 'new_cls', 'cycle_path', 'routeIds'])
        for r in rows:
            cycle_path_parts = []
            for l in r['outputLegs']:
                ref_info = f"{l['pos']}_{l['referLen']}_{l['lastHop']}_{l['lastMinUsd']:.2f}"
                cycle_path_parts.append(f"{l['routeId']} {l['dex']} {l['poolId']} {l['from']}->{l['to']} {ref_info}")
            cycle_path = ' | '.join(cycle_path_parts)
            cycle_legs = [l for l in r['outputLegs'] if l.get('inCycle')]
            route_ids = [l['routeId'] for l in cycle_legs]
            rids_str = ','.join(str(rid) for rid in route_ids) + (',' if route_ids else '')
            w.writerow([r['txHash'], r['idx'], r['short'],
                         r['legs'], r['cycleId'], r['targetRoute'],
                         r['dp_evt'], r['m25_cnt'], r['m25a_cnt'], r['m1_cnt'],
                         r['best_val'], f"{r['minUsd']:.2f}",
                         r['orig_cls'], r['mismatchKind'], r['new_cls'],
                         cycle_path, rids_str])
    print(f"Generated: {csv_v3}")

    # ── Summary ──
    cls_counts = defaultdict(int)
    for r in rows: cls_counts[r['new_cls']] += 1
    print("\n--- Summary ---")
    for cls in ['X_no_route', 'X_no_cycle', 'X_no_success', 'X_no_block']:
        if cls in cls_counts:
            print(f"  {cls}: {cls_counts[cls]}")
    for cls, cnt in cls_counts.items():
        if cls not in ['X_no_route', 'X_no_cycle', 'X_no_success', 'X_no_block']:
            print(f"  {cls}: {cnt}")

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <replay_output_dir>")
        sys.exit(1)
    analyze(sys.argv[1])
