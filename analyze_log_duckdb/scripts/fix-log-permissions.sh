#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat >&2 <<'USAGE'
Usage:
  fix-log-permissions.sh [--dry-run] DIR...

Fix unreadable Go/go-service production log files before DuckDB import.

Defaults:
  owner: ecs-user:ecs-user
  mode:  0644
  files: combined_dt-mev-statefulset-pricer-0*.log*

Each DIR must be under /dt-logs/log/mainnet/.
USAGE
}

dry_run=0
owner="ecs-user:ecs-user"
mode="0644"
dirs=()
script_path="$(readlink -f "$0")"
installed_helper="/usr/local/sbin/dt-fix-log-permissions"

while (($#)); do
  case "$1" in
    --dry-run)
      dry_run=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    --)
      shift
      dirs+=("$@")
      break
      ;;
    -*)
      echo "unknown option: $1" >&2
      usage
      exit 2
      ;;
    *)
      dirs+=("$1")
      shift
      ;;
  esac
done

if ((${#dirs[@]} == 0)); then
  usage
  exit 2
fi

for dir in "${dirs[@]}"; do
  case "$dir" in
    /dt-logs/log/mainnet/*) ;;
    *)
      echo "refuse path outside /dt-logs/log/mainnet: $dir" >&2
      exit 2
      ;;
  esac
  if [[ ! -d "$dir" ]]; then
    echo "missing directory: $dir" >&2
    exit 2
  fi
done

if ((!dry_run)) && [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
  if [[ -x "$installed_helper" && "$script_path" != "$installed_helper" ]]; then
    exec sudo "$installed_helper" "${dirs[@]}"
  fi
  exec sudo "$script_path" "${dirs[@]}"
fi

for dir in "${dirs[@]}"; do
  echo "== $dir =="
  if ((dry_run)); then
    find "$dir" -maxdepth 1 -type f -name 'combined_dt-mev-statefulset-pricer-0*.log*' -printf '%M %u %g %p\n'
    continue
  fi

  find "$dir" -maxdepth 1 -type f -name 'combined_dt-mev-statefulset-pricer-0*.log*' -exec chown "$owner" {} +
  find "$dir" -maxdepth 1 -type f -name 'combined_dt-mev-statefulset-pricer-0*.log*' -exec chmod "$mode" {} +
  find "$dir" -maxdepth 1 -type f -name 'combined_dt-mev-statefulset-pricer-0*.log*' ! -readable -printf 'still unreadable: %p\n'
done
