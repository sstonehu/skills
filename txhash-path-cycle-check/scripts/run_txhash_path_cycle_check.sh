#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <txHash> [output_dir]"
  exit 1
fi

TX_HASH="$1"
if ! [[ "$TX_HASH" =~ ^0x[0-9a-fA-F]{64}$ ]]; then
  echo "ERROR: invalid tx hash: $TX_HASH"
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SKILL_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# Auto-detect go-service: env var > walk-up from skill dir > $HOME/dt_workspace
if [[ -n "${GO_SERVICE_DIR:-}" ]] && [[ -d "$GO_SERVICE_DIR/cmd/replay" ]]; then
  :
elif [[ -d "$SKILL_DIR/../../../../go-service/cmd/replay" ]]; then
  GO_SERVICE_DIR="$(cd "$SKILL_DIR/../../../../go-service" && pwd)"
elif [[ -d "$HOME/dt_workspace/go-service/cmd/replay" ]]; then
  GO_SERVICE_DIR="$HOME/dt_workspace/go-service"
else
  echo "ERROR: cannot find go-service. Set GO_SERVICE_DIR env var." >&2
  exit 1
fi
WS_DIR="$(dirname "$GO_SERVICE_DIR")"

TS="$(date +%Y%m%d%H%M%S)"
TX_SHORT="${TX_HASH:2:8}"
DEFAULT_OUT="$GO_SERVICE_DIR/test_output/txhash_path_cycle_check_${TX_SHORT}_${TS}"
OUT_DIR="${2:-$DEFAULT_OUT}"
IDENTIFY_OUT="$OUT_DIR/identify"
REPORT_OUT="$OUT_DIR/path_cycle_report.txt"

mkdir -p "$OUT_DIR"

echo "txHash=$TX_HASH"
echo "workspace=$WS_DIR"
echo "goService=$GO_SERVICE_DIR"
echo "output=$OUT_DIR"

cd "$GO_SERVICE_DIR"

# Step 1: Identify target pool paths from tx logs
./cmd/replay/run_identify_target_path.sh -tx_hash="$TX_HASH" -output_dir="$IDENTIFY_OUT"

ANALYSIS_JSON="$IDENTIFY_OUT/target_path_analysis.json"
if [[ ! -f "$ANALYSIS_JSON" ]]; then
  echo "ERROR: missing $ANALYSIS_JSON"
  exit 1
fi

# Step 2: Resolve route/cycle/refer from bin data
go run ./cmd/replay/find_path_cycle -analysis_json="$ANALYSIS_JSON" | tee "$REPORT_OUT"

# Step 3: Phase-aware cycle reordering (largest closed cycle + cashPool)
CORRECTED_OUT="$OUT_DIR/path_cycle_corrected.json"
python3 "$SCRIPT_DIR/correct_cycle_order.py" "$OUT_DIR" > "$CORRECTED_OUT"
echo "Corrected cycle order: $CORRECTED_OUT"

echo ""
echo "Saved:"
echo "  $ANALYSIS_JSON"
echo "  $REPORT_OUT"
echo "  $CORRECTED_OUT"
