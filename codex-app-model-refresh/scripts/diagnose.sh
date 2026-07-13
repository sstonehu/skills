#!/usr/bin/env bash

set -u

CODEX_HOME="${CODEX_HOME:-$HOME/.codex}"
CONFIG_PATH="$CODEX_HOME/config.toml"
STATE_DB="$CODEX_HOME/state_5.sqlite"
THREAD_ID=""
RECENT_THREADS=""
CATALOG_PATH=""
CLI_MODELS_FILE=""

usage() {
  cat <<'EOF'
Usage: diagnose.sh [--thread-id ID] [--recent-threads N]

Run read-only diagnostics for a stale Codex App /model menu.

Options:
  --thread-id ID       Show the persisted model for one Codex task.
  --recent-threads N   Show model assignments for the N most recent tasks.
  -h, --help           Show this help.
EOF
}

section() {
  printf '\n== %s ==\n' "$1"
}

print_json_models() {
  local path="$1"
  python3 - "$path" <<'PY'
import json
import sys

path = sys.argv[1]
try:
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
except Exception as exc:
    print(f"ERROR: cannot parse {path}: {exc}")
    raise SystemExit(1)

items = data.get("models", []) if isinstance(data, dict) else data
if not isinstance(items, list):
    print("ERROR: JSON does not contain a model list")
    raise SystemExit(1)

models = []
for item in items:
    if not isinstance(item, dict):
        continue
    name = (
        item.get("slug")
        or item.get("id")
        or item.get("model")
        or item.get("name")
        or item.get("display_name")
        or item.get("displayName")
    )
    if name:
        models.append(str(name))

print(f"model_count={len(models)}")
for model in models:
    print(f"  {model}")
PY
}

query_threads() {
  local mode="$1"
  local value="$2"
  python3 - "$STATE_DB" "$mode" "$value" "$CATALOG_PATH" <<'PY'
import datetime
import json
import os
import sqlite3
import sys

path, mode, value, catalog_path = sys.argv[1:5]
try:
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
except Exception as exc:
    print(f"ERROR: cannot open SQLite database read-only: {exc}")
    raise SystemExit(1)

columns = {row[1] for row in connection.execute("pragma table_info(threads)")}
required = {"id", "model"}
if not required.issubset(columns):
    print("ERROR: threads table does not contain id and model columns")
    raise SystemExit(1)

selected = ["id", "model"]
for column in ("updated_at", "cwd", "archived"):
    if column in columns:
        selected.append(column)

if mode == "thread":
    rows = connection.execute(
        f"select {','.join(selected)} from threads where id = ?",
        (value,),
    ).fetchall()
else:
    limit = int(value)
    order = "updated_at desc" if "updated_at" in columns else "rowid desc"
    rows = connection.execute(
        f"select {','.join(selected)} from threads order by {order} limit ?",
        (limit,),
    ).fetchall()

if not rows:
    print("No matching task rows.")
    raise SystemExit(0)

catalog_models = None
if catalog_path and os.path.isfile(catalog_path):
    try:
        with open(catalog_path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        items = data.get("models", []) if isinstance(data, dict) else data
        catalog_models = {
            str(
                item.get("slug")
                or item.get("id")
                or item.get("model")
                or item.get("name")
                or item.get("display_name")
                or item.get("displayName")
            )
            for item in items
            if isinstance(item, dict)
        }
    except Exception:
        catalog_models = None

for row in rows:
    record = dict(zip(selected, row))
    if catalog_models is not None:
        record["model_in_catalog"] = record.get("model") in catalog_models
    updated = record.get("updated_at")
    if isinstance(updated, int):
        try:
            record["updated_at_utc"] = datetime.datetime.fromtimestamp(
                updated, datetime.timezone.utc
            ).isoformat()
        except (OverflowError, OSError, ValueError):
            pass
    print(" ".join(f"{key}={record.get(key)!r}" for key in record))
PY
}

while (($#)); do
  case "$1" in
    --thread-id)
      [[ $# -ge 2 ]] || { printf 'ERROR: --thread-id requires a value\n' >&2; exit 2; }
      THREAD_ID="$2"
      shift 2
      ;;
    --recent-threads)
      [[ $# -ge 2 ]] || { printf 'ERROR: --recent-threads requires a value\n' >&2; exit 2; }
      [[ "$2" =~ ^[1-9][0-9]*$ ]] || {
        printf 'ERROR: --recent-threads must be a positive integer\n' >&2
        exit 2
      }
      RECENT_THREADS="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      printf 'ERROR: unknown option: %s\n' "$1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

CLI_MODELS_FILE="$(mktemp)"
trap 'rm -f "$CLI_MODELS_FILE"' EXIT

section "Configured model catalog"
if [[ -f "$CONFIG_PATH" ]]; then
  printf 'config=%s\n' "$CONFIG_PATH"
  CATALOG_PATH="$(
    sed -nE 's/^[[:space:]]*model_catalog_json[[:space:]]*=[[:space:]]*"([^"]+)".*/\1/p' \
      "$CONFIG_PATH" | tail -n 1
  )"
else
  printf 'WARNING: config not found: %s\n' "$CONFIG_PATH"
fi

if [[ -n "$CATALOG_PATH" && "$CATALOG_PATH" != /* ]]; then
  CATALOG_PATH="$CODEX_HOME/$CATALOG_PATH"
fi

if [[ -n "$CATALOG_PATH" && -f "$CATALOG_PATH" ]]; then
  stat -c 'catalog=%n modified=%y epoch=%Y size=%s' "$CATALOG_PATH"
  print_json_models "$CATALOG_PATH" || true
elif [[ -n "$CATALOG_PATH" ]]; then
  printf 'WARNING: configured catalog does not exist: %s\n' "$CATALOG_PATH"
else
  printf 'model_catalog_json is not configured; Codex may use its bundled catalog.\n'
fi

section "Fresh CLI model parsing"
if command -v codex >/dev/null 2>&1; then
  printf 'codex_binary=%s\n' "$(command -v codex)"
  if codex debug models >"$CLI_MODELS_FILE" 2>&1; then
    print_json_models "$CLI_MODELS_FILE" || true
    if [[ -n "$CATALOG_PATH" && -f "$CATALOG_PATH" ]]; then
      python3 - "$CATALOG_PATH" "$CLI_MODELS_FILE" <<'PY'
import json
import sys

def names(path):
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    items = data.get("models", []) if isinstance(data, dict) else data
    return {
        str(
            item.get("slug")
            or item.get("id")
            or item.get("model")
            or item.get("name")
            or item.get("display_name")
            or item.get("displayName")
        )
        for item in items
        if isinstance(item, dict)
    }

try:
    catalog = names(sys.argv[1])
    cli = names(sys.argv[2])
except Exception as exc:
    print(f"comparison=ERROR detail={exc}")
    raise SystemExit(0)

print("catalog_vs_cli=MATCH" if catalog == cli else "catalog_vs_cli=MISMATCH")
if catalog != cli:
    print("  only_in_catalog=" + ",".join(sorted(catalog - cli)))
    print("  only_in_cli=" + ",".join(sorted(cli - catalog)))
PY
    fi
  else
    printf 'ERROR: codex debug models failed:\n'
    sed -n '1,40p' "$CLI_MODELS_FILE"
  fi
else
  printf 'ERROR: codex is not on PATH\n'
fi

section "App-server daemon version"
DAEMON_OUTPUT=""
if command -v codex >/dev/null 2>&1; then
  DAEMON_OUTPUT="$(codex app-server daemon version 2>&1 || true)"
  printf '%s\n' "$DAEMON_OUTPUT"
  python3 - "$DAEMON_OUTPUT" <<'PY'
import json
import os
import sys

raw = sys.argv[1]
try:
    data = json.loads(raw)
except Exception:
    raise SystemExit(0)

managed_path = data.get("managedCodexPath")
managed_version = data.get("managedCodexVersion")
if managed_path and not os.path.exists(managed_path):
    print(f"NOTICE: managed Codex path is missing: {managed_path}")
if data.get("status") == "running" and not managed_version:
    print("NOTICE: running app-server may not be daemon-managed; stop/restart can fail.")
if (
    data.get("cliVersion")
    and data.get("appServerVersion")
    and data["cliVersion"] != data["appServerVersion"]
):
    print("WARNING: CLI and app-server versions differ.")
PY
fi

section "App-server processes"
PROCESS_ROWS="$(
  ps -eo pid=,ppid=,etimes=,lstart=,args= 2>/dev/null \
    | awk '/[c]odex .*app-server --listen unix:\/\// || /[c]odex app-server proxy/'
)"
if [[ -n "$PROCESS_ROWS" ]]; then
  printf '%s\n' "$PROCESS_ROWS"
else
  printf 'No Codex app-server process found.\n'
fi

if [[ -n "$CATALOG_PATH" && -f "$CATALOG_PATH" && -n "$PROCESS_ROWS" ]]; then
  CATALOG_EPOCH="$(stat -c %Y "$CATALOG_PATH")"
  NOW_EPOCH="$(date +%s)"
  while read -r pid ppid elapsed rest; do
    [[ "$pid" =~ ^[0-9]+$ && "$elapsed" =~ ^[0-9]+$ ]] || continue
    if [[ "$rest" == *"app-server --listen unix://"* ]]; then
      START_EPOCH=$((NOW_EPOCH - elapsed))
      if ((START_EPOCH < CATALOG_EPOCH)); then
        printf 'WARNING: PID %s started before the catalog changed; stale memory is plausible.\n' "$pid"
      fi
    fi
  done <<<"$PROCESS_ROWS"
fi

section "Sockets and lock files"
FOUND_STATE=0
for path in \
  "$CODEX_HOME"/app-server-control/*.sock \
  "$CODEX_HOME"/app-server-control/*.lock \
  "$CODEX_HOME"/app-server-daemon/*.lock; do
  [[ -e "$path" || -S "$path" ]] || continue
  FOUND_STATE=1
  stat -c 'path=%n type=%F modified=%y epoch=%Y' "$path"
  if [[ "$path" == *.lock ]] && command -v lsof >/dev/null 2>&1; then
    HOLDERS="$(lsof -t "$path" 2>/dev/null | paste -sd, -)"
    if [[ -n "$HOLDERS" ]]; then
      printf '  held_by_pids=%s\n' "$HOLDERS"
    else
      printf '  held_by_pids=none\n'
    fi
  fi
done
((FOUND_STATE)) || printf 'No app-server sockets or lock files found.\n'

if [[ -n "$THREAD_ID" || -n "$RECENT_THREADS" ]]; then
  section "Persisted task model state"
  if [[ ! -f "$STATE_DB" ]]; then
    printf 'WARNING: state database not found: %s\n' "$STATE_DB"
  elif ! command -v python3 >/dev/null 2>&1; then
    printf 'ERROR: python3 is required for read-only SQLite fallback.\n'
  else
    [[ -z "$THREAD_ID" ]] || query_threads thread "$THREAD_ID"
    [[ -z "$RECENT_THREADS" ]] || query_threads recent "$RECENT_THREADS"
  fi
fi

section "Interpretation"
cat <<'EOF'
- Catalog and CLI match, but App is stale: investigate app-server/frontend/task state.
- App-server predates catalog: reconnect or restart the correct server, then verify a new PID.
- Old lock timestamps with no holders: do not delete locks as the first fix.
- Fresh App server but /model still stale: the Codex App frontend caches the model list independently. A full restart of the Codex App (not just reconnect) is required to clear the frontend cache.
- Fresh App server but one task is stale: inspect that exact threads.model row.
- Success requires the Codex App /model menu or affected task to show the expected model.
EOF
