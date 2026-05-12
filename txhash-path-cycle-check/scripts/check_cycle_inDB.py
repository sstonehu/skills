#!/usr/bin/env python3
"""check_cycle_inDB: 查 route 序列在 DuckDB cycle_summary 中是否存在.

用法:
  python3 check_cycle_inDB.py --routes 21306,27484,56032,65273
  python3 check_cycle_inDB.py --routes 21306,27484,56032,65273 --duckdb /path/to/cycle_duckdb.duckdb
  python3 check_cycle_inDB.py --tx-hash 0x5b3e... --report-dir /path/to/txhash_path_cycle_check_xxx

匹配策略:
  1. 全量匹配 (所有 N 条 route, 循环移位)
  2. 去 cashPool 匹配 (N-1 条, 尝试逐条剔除)
"""

import argparse
import sys

try:
    import duckdb
except ImportError:
    print("ERROR: pip install duckdb", file=sys.stderr)
    sys.exit(1)


DEFAULT_DUCKDB = "/mnt/evm_node/duckDB/cycle_duckdb.duckdb"


def parse_route_ids_from_report(report_dir: str) -> list[int]:
    import re
    report_path = f"{report_dir}/path_cycle_report.txt"
    route_ids = []
    with open(report_path) as f:
        for line in f:
            m = re.match(r'^\s*(\d+)\s+\S+', line)
            if m:
                route_ids.append(int(m.group(1)))
    if not route_ids:
        f.seek(0)
        for line in f:
            m = re.search(r'route[dD]s?\s*[=:]\s*\[([^\]]+)\]', line)
            if m:
                route_ids = [int(x.strip()) for x in m.group(1).split(",")]
                break
    return route_ids


def circular_shifts(routes: list[int]) -> list[list[int]]:
    n = len(routes)
    return [[routes[(i + j) % n] for j in range(n)] for i in range(n)]


def build_where(shift: list[int]) -> str:
    n = len(shift)
    conds = [f"route_len = {n}"]
    for i, rid in enumerate(shift):
        conds.append(f"route_{i} = {rid}")
    return " AND ".join(conds)


def query_shifts(con, routes: list[int]) -> list[dict]:
    """对 routes 所有循环移位查询 cycle_summary. 返回匹配列表."""
    results = []
    for i, shift in enumerate(circular_shifts(routes)):
        where = build_where(shift)
        sql = f"SELECT cycle_id, alive, meta, route_len FROM cycle_summary WHERE {where} LIMIT 10"
        try:
            rows = con.execute(sql).fetchall()
        except Exception as e:
            results.append({"shift": i, "start_route": shift[0], "error": str(e)})
            continue
        for row in rows:
            results.append({
                "shift": i, "start_route": shift[0],
                "cycle_id": row[0], "alive": row[1], "meta": row[2], "route_len": row[3],
            })
    return results


def check_duckdb(duckdb_path: str, routes: list[int], quiet: bool = False):
    """返回 (matches, match_mode). match_mode: exact, no_cashpool, not_found."""
    con = duckdb.connect(duckdb_path, read_only=True)
    n = len(routes)

    if not quiet:
        print(f"DuckDB: {duckdb_path}")
        print(f"Routes ({n}): {routes}")
        print()

    # --- Strategy 1: full routes ---
    matches = query_shifts(con, routes)
    if matches and not any("error" in m for m in matches):
        if not quiet:
            print("=" * 72)
            print("cycle_summary 匹配 (全量)")
            print("=" * 72)
            _print_matches(matches)
            print()
        con.close()
        return matches, "exact"

    # --- Strategy 2: drop cashPool (try each route as candidate) ---
    if n >= 3:
        for drop_idx in range(n):
            subset = [r for j, r in enumerate(routes) if j != drop_idx]
            m2 = query_shifts(con, subset)
            if m2 and not any("error" in x for x in m2):
                if not quiet:
                    print("=" * 72)
                    print(f"cycle_summary 匹配 (去 cashPool: drop route {routes[drop_idx]} at idx {drop_idx})")
                    print("=" * 72)
                    _print_matches(m2)
                    print()
                con.close()
                return m2, f"no_cashpool_drop_{drop_idx}"
            if m2 and all("error" in x for x in m2):
                continue

    if not quiet:
        print("=" * 72)
        print("cycle_summary 匹配")
        print("=" * 72)
        print("  NOT FOUND (full + no-cashpool both failed)")
        print()

    # --- route_winners ---
    if not quiet:
        print("=" * 72)
        print("route_winners (各 route 的 winner 排名)")
        print("=" * 72)
        for rid in routes:
            try:
                cnt = con.execute(
                    "SELECT COUNT(*) FROM route_winners WHERE route_id = ?", [rid]
                ).fetchone()[0]
            except Exception as e:
                print(f"  route {rid}: ERROR - {e}")
                continue
            if cnt > 0:
                top = con.execute(
                    "SELECT rank, cycle_id, score FROM route_winners WHERE route_id = ? ORDER BY rank LIMIT 3",
                    [rid],
                ).fetchall()
                print(f"  route {rid}: {cnt} entries, top ranks: {top}")
            else:
                print(f"  route {rid}: 0 entries (not in route_winners)")
        print()

    con.close()
    return [], "not_found"


def _print_matches(matches):
    for m in matches:
        if "error" in m:
            print(f"  shift {m['shift']} (start={m['start_route']}): ERROR {m['error']}")
        else:
            print(f"  shift {m['shift']} (start={m['start_route']}): "
                  f"cycle_id={m['cycle_id']} alive={m['alive']} meta={m['meta']} route_len={m['route_len']}")


def main():
    parser = argparse.ArgumentParser(description="check_cycle_inDB")
    parser.add_argument("--duckdb", default=DEFAULT_DUCKDB, help=f"DuckDB path")
    parser.add_argument("--routes", help="逗号分隔的 route IDs")
    parser.add_argument("--report-dir", help="txhash_path_cycle_check 输出目录")
    parser.add_argument("--tx-hash", help="txHash（备查）")
    args = parser.parse_args()

    if args.routes:
        route_ids = [int(x.strip()) for x in args.routes.split(",")]
    elif args.report_dir:
        route_ids = parse_route_ids_from_report(args.report_dir)
        if not route_ids:
            print(f"ERROR: cannot parse route IDs from {args.report_dir}/path_cycle_report.txt",
                  file=sys.stderr)
            sys.exit(1)
    else:
        print("ERROR: need --routes or --report-dir", file=sys.stderr)
        sys.exit(1)

    if len(route_ids) < 2:
        print("ERROR: need at least 2 routes, got:", route_ids, file=sys.stderr)
        sys.exit(1)

    check_duckdb(args.duckdb, route_ids)


if __name__ == "__main__":
    main()
