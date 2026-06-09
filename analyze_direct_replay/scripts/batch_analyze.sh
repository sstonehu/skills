#!/usr/bin/env bash
# batch_analyze.sh — 一键分析 replay 批次产出 4 个标准化文件
#
# 用法:
#   bash batch_analyze.sh <replay_batch_dir>
#
# 产出 (写入 batch_dir 根目录):
#   direct_fail_report.md              — direct replay revert 分析
#   mid1_target_cycle.json             — 失败 TX 的 cycle/path 详情 (JSON)
#   mid1_target_cycle.csv              — 同上 (CSV, 12 列)
#   mid1_fail_detail_v3_classified.csv — 逐阶段失败明细 (CSV, 17 列)
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <replay_batch_dir>"
  exit 1
fi

BATCH_DIR="$(cd "$1" && pwd)"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SKILL_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
SKILLS_DIR="$(cd "$SKILL_DIR/.." && pwd)"

# ── Auto-detect go-service ──
if [[ -n "${GO_SERVICE_DIR:-}" ]] && [[ -d "$GO_SERVICE_DIR/cmd/replay" ]]; then
  :
elif [[ -d "$SKILLS_DIR/../../go-service/cmd/replay" ]]; then
  GO_SERVICE_DIR="$(cd "$SKILLS_DIR/../../go-service" && pwd)"
elif [[ -d "$HOME/dt_workspace/go-service/cmd/replay" ]]; then
  GO_SERVICE_DIR="$HOME/dt_workspace/go-service"
else
  echo "ERROR: cannot find go-service. Set GO_SERVICE_DIR env var." >&2
  exit 1
fi
export GO_SERVICE_DIR

echo "=== Batch Analyze ==="
echo "Batch:    $BATCH_DIR"
echo "GoSvc:    $GO_SERVICE_DIR"
echo "Skills:   $SKILLS_DIR"
echo ""

# ── Phase 1: direct_fail_report.md ──
echo "--- Phase 1: direct replay analysis ---"
DIRECT_JS="$SKILL_DIR/analyze_direct_replay.js"
DIRECT_PY="$SKILL_DIR/analyze_direct_replay.py"

js_ok=1
if [[ -f "$DIRECT_JS" ]]; then
  if command -v node >/dev/null 2>&1; then
    node "$DIRECT_JS" "$BATCH_DIR" 2>/dev/null || js_ok=0
  else
    js_ok=0
  fi
fi

# Try Python when JS is unavailable/failed, or when no report exists yet.
if [[ ( "$js_ok" -eq 0 || ! -f "$BATCH_DIR/direct_fail_report.md" ) && -f "$DIRECT_PY" ]]; then
  [[ "$js_ok" -eq 0 ]] && echo "  WARN: JS analyzer unavailable or failed, trying Python..."
  python3 "$DIRECT_PY" "$BATCH_DIR" 2>/dev/null || echo "  WARN: Python analyzer also failed"
fi

if [[ -f "$BATCH_DIR/direct_fail_report.md" ]]; then
  echo "  OK: direct_fail_report.md"
else
  echo "  MISSING: direct_fail_report.md"
fi

# ── Phase 2: mid1 cycle/fail analysis ──
echo ""
echo "--- Phase 2: mid1 cycle & fail analysis ---"
CYCLE_PY="$SKILLS_DIR/cycle-fail-analysis/scripts/analyze.py"

if [[ -f "$CYCLE_PY" ]]; then
  python3 "$CYCLE_PY" "$BATCH_DIR"
else
  echo "  ERROR: missing $CYCLE_PY"
fi

# ── Phase 3: Verify ──
echo ""
echo "=== Output files ==="
for f in direct_fail_report.md mid1_target_cycle.json mid1_target_cycle.csv mid1_fail_detail_v3_classified.csv; do
  if [[ -f "$BATCH_DIR/$f" ]]; then
    sz=$(wc -c < "$BATCH_DIR/$f")
    echo "  [OK] $f ($sz bytes)"
  else
    echo "  [MISSING] $f"
  fi
done

echo ""
echo "Done: $BATCH_DIR"
