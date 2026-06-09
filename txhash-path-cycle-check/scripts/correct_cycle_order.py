#!/usr/bin/env python3
"""
Phase-aware cycle reordering: corrects find_path_cycle output to form a
proper closed cycle starting from ETH-like or stable token, with cashPool
legs appended at the end.

Reads:
  - target_path_analysis.json (identify output — authoritative token direction)
  - path_cycle_report.txt    (find_path_cycle output — authoritative routeIds)
  - go-service/conf/StableTokens.json (authoritative stable token set)

Algorithm (aligns with Go orderLegsAsCycle, extended for cashPool):
  1. Merge: leg tokens from identify, routeIds from report, matched by pool key.
  2. legStartPriority: ETH-like=0, stable=1, other=2.
  3. DFS: find largest closed-cycle subset (size k <= n).
  4. Rotate cycle subset to begin at highest-priority leg.
  5. Append remaining legs (cashPool / unclosed outputs) after the cycle.
  6. If no closed cycle found, return original order.

Output: corrected cycle order (JSON on stdout, or --csv for CSV).
"""

import argparse, json, os, re, sys

# ETH-like addresses (matching Go modelbase.IsETHLike)
ETH_LIKE = {a.lower() for a in [
    '0x0000000000000000000000000000000000000000',
    '0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2',
    '0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE',
]}
WETH = '0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2'

# ── helpers ──────────────────────────────────────────────────────────

def load_stable_set(config_dir):
    """Load stable token addresses from conf/StableTokens.json."""
    path = os.path.join(config_dir, 'StableTokens.json')
    if not os.path.exists(path):
        return set()
    with open(path) as f:
        tokens = json.load(f)
    return {t['address'].lower() for t in tokens}

def canonical(addr):
    a = addr.lower()
    return WETH if a in ETH_LIKE else a

def token_eq(a, b):
    return canonical(a) == canonical(b)

def leg_priority(from_addr, stable_set):
    a = from_addr.lower()
    if a in ETH_LIKE:
        return 0
    if a in stable_set:
        return 1
    return 2

# ── parsing ──────────────────────────────────────────────────────────

def parse_report(report_path):
    """Extract routeIds from find_path_cycle report. Returns (route_ids, cycle_info_dict)."""
    with open(report_path) as f:
        content = f.read()
    route_ids = []
    cycle_info = {"cycleExists": False, "cycleId": -1, "minUsd": 0.0, "mismatchKind": "?"}
    for line in content.split('\n'):
        m = re.search(r',\s*(-?\d+),\s*([0-9.]+)$', line)
        if m:
            route_ids.append(int(m.group(1)))
        # Parse cycle existence line
        if line.startswith("exists="):
            for p in line.split(","):
                p = p.strip()
                if p.startswith("exists="):
                    cycle_info["cycleExists"] = (p.split("=")[1].lower() == "true")
                elif p.startswith("mismatchKind="):
                    cycle_info["mismatchKind"] = p.split("=")[1]
            m = re.search(r'internalCid=(\d+)', line)
            if m:
                cycle_info["cycleId"] = int(m.group(1))
            m = re.search(r'minUsd=([0-9.]+)', line)
            if m:
                cycle_info["minUsd"] = float(m.group(1))
    if cycle_info["cycleExists"] and cycle_info["mismatchKind"] == "?":
        cycle_info["mismatchKind"] = "found"
    return route_ids, cycle_info

def parse_target_paths(analysis_json_path):
    """Extract legs with correct token direction from identify output."""
    with open(analysis_json_path) as f:
        data = json.load(f)
    legs = []
    for tp in data.get('targetPoolPaths', []):
        t0 = tp.get('token0', {})
        t1 = tp.get('token1', {})
        ti = tp.get('token0In', True)
        fr, to = (t0, t1) if ti else (t1, t0)
        legs.append({
            'fromSymbol': fr.get('symbol', '?'),
            'toSymbol':   to.get('symbol', '?'),
            'fromAddr':   fr.get('address', ''),
            'toAddr':     to.get('address', ''),
            'poolAddress': tp.get('poolAddress', ''),
            'poolId':      tp.get('poolId', ''),
            'dex':         tp.get('dex', ''),
        })
    return legs

# ── reorder ──────────────────────────────────────────────────────────

def reorder_cycle(legs, stable_set):
    """
    Phase-aware DFS: find largest closed-cycle subset starting from
    highest-priority leg.  Append remaining (cashPool) legs.
    Returns (ordered_legs, is_reordered).
    """
    n = len(legs)
    original_route_ids = [leg.get('routeId', -1) for leg in legs]

    if n < 2:
        for leg in legs:
            leg['in_cycle'] = False
        return legs, False

    for cycle_size in range(n, 1, -1):
        best_result, best_priority = None, 99
        for start in range(n):
            path = [start]
            used = {start}

            def dfs(cur):
                if len(path) == cycle_size:
                    return token_eq(legs[cur]['toAddr'], legs[path[0]]['fromAddr'])
                nxt = legs[cur]['toAddr']
                for i in range(n):
                    if i in used:
                        continue
                    if token_eq(legs[i]['fromAddr'], nxt):
                        used.add(i)
                        path.append(i)
                        if dfs(i):
                            return True
                        path.pop()
                        used.remove(i)
                return False

            if dfs(start):
                ordered = [legs[i] for i in path]
                remaining = [legs[i] for i in range(n) if i not in used]
                # Rotate to highest-priority leg
                priorities = [leg_priority(l['fromAddr'], stable_set) for l in ordered]
                min_p = min(priorities)
                rot = next(i for i, p in enumerate(priorities) if p == min_p)
                ordered = ordered[rot:] + ordered[:rot]
                res = ordered + remaining
                rp = leg_priority(res[0]['fromAddr'], stable_set)
                if rp < best_priority:
                    best_priority = rp
                    best_result = res
        if best_result is not None:
            # Mark in_cycle for the closed-cycle subset (first cycle_size legs)
            cycle_count = cycle_size
            for i, leg in enumerate(best_result):
                leg['in_cycle'] = (i < cycle_count)
            reordered = ([l['routeId'] for l in best_result] != original_route_ids)
            return best_result, reordered

    # No closed cycle found — all legs marked not in cycle
    for leg in legs:
        leg['in_cycle'] = False
    return legs, False

# ── main ─────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(description='Phase-aware cycle reordering')
    p.add_argument('output_dir', help='Directory containing identify/ and path_cycle_report.txt')
    p.add_argument('--config-dir', default=None,
                   help='go-service/conf directory (default: auto-detect from workspace or GO_SERVICE_DIR env var)')
    p.add_argument('--csv', action='store_true', help='Output CSV instead of JSON')
    p.add_argument('--rich', action='store_true', help='Output rich CSV with txHash, cycleId, isReordered, inCycle')
    p.add_argument('--tx-hash', default='', help='txHash for --rich CSV context')
    args = p.parse_args()

    out_dir = args.output_dir
    analysis_json = os.path.join(out_dir, 'identify', 'target_path_analysis.json')
    report_txt    = os.path.join(out_dir, 'path_cycle_report.txt')

    if not os.path.exists(analysis_json):
        print(f'ERROR: missing {analysis_json}', file=sys.stderr)
        sys.exit(1)
    if not os.path.exists(report_txt):
        print(f'ERROR: missing {report_txt}', file=sys.stderr)
        sys.exit(1)

    # Auto-detect config dir
    config_dir = args.config_dir
    if not config_dir:
        # Priority: GO_SERVICE_DIR env var -> walk-up from output -> file location fallback
        gsd = os.environ.get('GO_SERVICE_DIR', '')
        if gsd and os.path.isdir(os.path.join(gsd, 'conf')):
            config_dir = os.path.join(gsd, 'conf')
        else:
            d = os.path.abspath(out_dir)
            while d != '/':
                candidate = os.path.join(d, 'go-service', 'conf')
                if os.path.isdir(candidate):
                    config_dir = candidate
                    break
                d = os.path.dirname(d)
            if not config_dir:
                config_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..', 'go-service', 'conf')
                config_dir = os.path.normpath(config_dir)

    stable_set = load_stable_set(config_dir)

    # Parse inputs
    route_ids, cycle_info = parse_report(report_txt)
    legs = parse_target_paths(analysis_json)

    # Map routeIds by pool position (match by order in report == order in targetPoolPaths)
    for i, leg in enumerate(legs):
        leg['routeId'] = route_ids[i] if i < len(route_ids) else -1

    # Reorder
    ordered, is_reordered = reorder_cycle(legs, stable_set)

    if args.rich:
        # Rich CSV with txHash, cycleId, isReordered, per-leg detail
        import csv as _csv, io as _io
        buf = _io.StringIO()
        w = _csv.writer(buf)
        w.writerow(['txHash', 'cycleId', 'isReordered', 'legIdx', 'routeId', 'dex',
                     'poolId', 'from', 'to', 'inCycle'])
        for i, leg in enumerate(ordered):
            pid = leg.get('poolId', '') or leg.get('poolAddress', '')
            w.writerow([args.tx_hash, cycle_info['cycleId'], str(is_reordered).lower(),
                        i, leg['routeId'], leg['dex'], pid,
                        leg['fromSymbol'], leg['toSymbol'],
                        str(leg.get('in_cycle', False)).lower()])
        sys.stdout.write(buf.getvalue())
    elif args.csv:
        # Legacy CSV output (now with in_cycle filled)
        import csv as _csv, io as _io
        buf = _io.StringIO()
        w = _csv.writer(buf)
        w.writerow(['idx', 'from', 'to', 'routeId', 'poolAddress', 'poolId', 'dex',
                     'start_priority', 'in_cycle'])
        for i, leg in enumerate(ordered):
            w.writerow([i, leg['fromSymbol'], leg['toSymbol'], leg['routeId'],
                        leg['poolAddress'], leg['poolId'], leg['dex'],
                        leg_priority(leg['fromAddr'], stable_set),
                        str(leg.get('in_cycle', False)).lower()])
        sys.stdout.write(buf.getvalue())
    else:
        json.dump(ordered, sys.stdout, indent=2, default=str)

if __name__ == '__main__':
    main()
