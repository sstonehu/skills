#!/usr/bin/env bash
set -euo pipefail

# enable-snapshot-dump.sh
#
# Uncomment snapshot file dump switches in go-service source files.
# Idempotent: safe to run multiple times.
#
# Target snapshot files:
#   opportunity_handler.go     : simulatorEvent.json
#   simulator_async.go         : SeedOut.json, Mid25Revenue.json,
#                                Mid25Revenue.after.json, mid1_Revenue.json (x2)
#   pricer.go                  : pricer.requestBodies.%d.json,
#                                pricer.responses.%d.json
#   try_arbi_batch.go          : reqs.json, debug_result.json
#   try_arbi_batch_direct.go   : direct_reqs.json, direct_resp.json
#
# Usage:
#   enable-snapshot-dump.sh [GO_SERVICE_DIR]
#
# If GO_SERVICE_DIR is omitted, defaults to ./go-service (task worktree layout).
#
# To revert: git checkout the affected files in the go-service worktree.

GO_SERVICE_DIR="${1:-}"

if [[ -z "$GO_SERVICE_DIR" ]]; then
    if [[ -d "$PWD/go-service" ]]; then
        GO_SERVICE_DIR="$PWD/go-service"
    else
        echo "Usage: $0 <GO_SERVICE_DIR>"
        echo "  Or run from a task worktree root (containing go-service/)"
        exit 1
    fi
fi

if [[ ! -d "$GO_SERVICE_DIR" ]]; then
    echo "Error: go-service directory not found: $GO_SERVICE_DIR"
    exit 1
fi

# os.WriteFile does not create directories
mkdir -p "$GO_SERVICE_DIR/test_output"

# ---------------------------------------------------------------------------
# Helper: uncomment a commented Go code block.
#
# Range starts at the line matching <start> and ends at the next line that is
# exactly "// }" (with optional leading whitespace).  The "// " prefix is
# stripped from every line in the range, preserving indentation.
#
# Uses '#' as the sed address delimiter so '/' inside patterns needs no
# escaping.
# ---------------------------------------------------------------------------
uncomment_range() {
    local file="$1" start="$2"
    if grep -qE "^[[:space:]]*//.*${start}" "$file" 2>/dev/null; then
        sed -i -E '\#'"${start}"'#,\#^[[:space:]]*//[[:space:]]*\}$#{s|^([[:space:]]*)// ?|\1|;}' "$file"
        echo "  [OK]   $(basename "$file"): $start"
    else
        echo "  [SKIP] $(basename "$file"): $start (already active or not found)"
    fi
}

# ---------------------------------------------------------------------------
# Helper: uncomment a fixed number of lines starting from a pattern match.
# Used when the block does not end with a standalone "// }" line.
# ---------------------------------------------------------------------------
uncomment_lines() {
    local file="$1" pattern="$2" count="$3"
    local plus=$((count - 1))
    if grep -qE "^[[:space:]]*//.*${pattern}" "$file" 2>/dev/null; then
        sed -i -E "/${pattern}/,+${plus}{s|^([[:space:]]*)// ?|\1|;}" "$file"
        echo "  [OK]   $(basename "$file"): $pattern"
    else
        echo "  [SKIP] $(basename "$file"): $pattern (already active or not found)"
    fi
}

# ---------------------------------------------------------------------------
# Helper: uncomment a single commented-out import line.
# Matches:  // "import/path"
# Produces: "import/path"
# ---------------------------------------------------------------------------
uncomment_import() {
    local file="$1" import_path="$2"
    local escaped
    # Escape forward slashes for the sed regex
    escaped="${import_path//\//\\/}"
    if grep -qE "^[[:space:]]*//[[:space:]]*\"${escaped}\"" "$file" 2>/dev/null; then
        sed -i -E "s|^([[:space:]]*)//[[:space:]]*(\"${escaped}\")|\\1\\2|" "$file"
        echo "  [OK]   $(basename "$file"): uncommented import \"${import_path}\""
    else
        echo "  [SKIP] $(basename "$file"): import \"${import_path}\" already active or not found"
    fi
}

# ---------------------------------------------------------------------------
# Helper: add a missing import line after an existing import in the same group.
# Only adds if the import is not already present (commented or uncommented).
# ---------------------------------------------------------------------------
add_import_after() {
    local file="$1" anchor="$2" new_import="$3"
    local anchor_escaped new_escaped
    anchor_escaped="${anchor//\//\\/}"
    new_escaped="${new_import//\//\\/}"
    if ! grep -qE "^[[:space:]]*(//)?[[:space:]]*\"${new_escaped}\"" "$file" 2>/dev/null; then
        sed -i -E "/^[[:space:]]*\"${anchor_escaped}\"[[:space:]]*$/{p; s/\"${anchor_escaped}\"/\"${new_escaped}\"/;}" "$file"
        echo "  [OK]   $(basename "$file"): added import \"${new_import}\""
    else
        echo "  [SKIP] $(basename "$file"): import \"${new_import}\" already present"
    fi
}

echo "Enabling snapshot dump switches in: $GO_SERVICE_DIR"
echo ""

# === 1. opportunity_handler.go: simulatorEvent.json ===
uncomment_range \
    "$GO_SERVICE_DIR/core/builder/opportunity_handler.go" \
    'WriteJSONFile.*simulatorEvent\.json'

# === 2. simulator_async.go ===
ASYNC="$GO_SERVICE_DIR/core/simulator/simulator_async.go"

# "go-service/pkg/util" import is commented out
uncomment_import "$ASYNC" "go-service/pkg/util"

uncomment_range "$ASYNC" 'WriteJSONFile.*SeedOut\.json'
# Process .after first so the .json pattern does not shadow it
uncomment_range "$ASYNC" 'WriteJSONFile.*Mid25Revenue\.after\.json'
uncomment_range "$ASYNC" 'WriteJSONFile.*Mid25Revenue\.json'
# Appears twice (mid1 worker + S4 handler); sed handles all occurrences.
# Prefix with WriteJSONFile to avoid matching doc comments that mention the filename.
uncomment_range "$ASYNC" 'WriteJSONFile.*mid1_Revenue\.json'

# === 3. pricer.go ===
PRICER="$GO_SERVICE_DIR/core/pricer/pricer.go"

# requestBodies block: steps := ... through closing }
uncomment_range "$PRICER" 'steps := callDatas'
# responses block: responseFile := ... through closing }
uncomment_range "$PRICER" 'responseFile := fmt\.Sprintf'

# === 4. try_arbi_batch.go ===
BATCH="$GO_SERVICE_DIR/core/simulator/try_arbi_batch.go"

# "log" import is missing entirely (all log.Printf calls were commented)
add_import_after "$BATCH" "fmt" "log"

uncomment_range "$BATCH" 'WriteJSONFile.*reqs\.json'
uncomment_range "$BATCH" 'WriteJSONFile.*debug_result\.json'

# === 5. try_arbi_batch_direct.go ===
DIRECT="$GO_SERVICE_DIR/core/simulator/try_arbi_batch_direct.go"

# "log" import is commented out: // "log"
uncomment_import "$DIRECT" "log"

# Uncomment the "if kind == \"direct\"" branch (8 lines).
# The "else" branch (dynamic_resp.json) is left commented because Go requires
# "} else {" on one line, and the user only requested direct_* files.
uncomment_lines "$DIRECT" 'if kind == "direct"' 8

echo ""
echo "Done. Snapshot files will be written to: test_output/"
echo "Ensure the go binary's working directory contains a writable test_output/."
