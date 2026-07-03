#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  create-task-workspace.sh <TASK_ID> [options]

Options:
  --workspace-root <path>  Workspace root. Default: /home/ecs-user/dt_workspace
  --task-root <path>       Exact task root to create. Default: <workspace-root>/task_worktrees/<TASK_ID>
  --go-branch <ref>        Base ref for go-service. Default: feature/cycle-order
  --dural-branch <ref>     Base ref for dural_trade. Default: direct-guard
  -h, --help               Show this help.

Creates an isolated task workspace with separate git worktrees for go-service
and dural_trade, copies each repo's .env file when present (both into the
worktree subdirectory and to the task root with a distinguishing name), and
creates TASK_ID-scoped output directories plus env.sh.
USAGE
}

die() {
  echo "error: $*" >&2
  exit 1
}

quote_sh() {
  local value=$1
  printf "'%s'" "${value//\'/\'\\\'\'}"
}

copy_env_file() {
  local source_repo=$1
  local target_tree=$2
  local label=$3
  local source_env=$source_repo/.env
  local target_env=$target_tree/.env

  if [[ ! -f "$source_env" ]]; then
    echo "missing"
    return 0
  fi

  if [[ -e "$target_env" ]]; then
    die "$label target .env already exists; refusing to overwrite: $target_env"
  fi

  cp -p "$source_env" "$target_env"
  echo "copied"
}

# Copy a repo .env to the task root with a distinguishing name for easy sourcing.
copy_env_to_root() {
  local source_repo=$1
  local task_root_dir=$2
  local root_name=$3
  local label=$4
  local source_env=$source_repo/.env
  local target_env=$task_root_dir/$root_name

  if [[ ! -f "$source_env" ]]; then
    echo "missing"
    return 0
  fi

  if [[ -e "$target_env" ]]; then
    die "$label target root env already exists; refusing to overwrite: $target_env"
  fi

  cp -p "$source_env" "$target_env"
  echo "copied"
}

workspace_root=${DT_WORKSPACE_ROOT:-/home/ecs-user/dt_workspace}
task_root=
go_ref=feature/cycle-order
dural_ref=direct-guard
task_id=

while (($#)); do
  case "$1" in
    -h|--help)
      usage
      exit 0
      ;;
    --workspace-root)
      (($# >= 2)) || die "--workspace-root requires a path"
      workspace_root=$2
      shift 2
      ;;
    --task-root)
      (($# >= 2)) || die "--task-root requires a path"
      task_root=$2
      shift 2
      ;;
    --go-branch)
      (($# >= 2)) || die "--go-branch requires a ref"
      go_ref=$2
      shift 2
      ;;
    --dural-branch)
      (($# >= 2)) || die "--dural-branch requires a ref"
      dural_ref=$2
      shift 2
      ;;
    --*)
      die "unknown option: $1"
      ;;
    *)
      if [[ -n "$task_id" ]]; then
        die "unexpected argument: $1"
      fi
      task_id=$1
      shift
      ;;
  esac
done

[[ -n "$task_id" ]] || { usage >&2; exit 2; }
[[ "$task_id" =~ ^[A-Za-z0-9._-]+$ ]] || die "TASK_ID may only contain letters, digits, dot, underscore, and hyphen: $task_id"

workspace_root=${workspace_root%/}
task_root=${task_root:-$workspace_root/task_worktrees/$task_id}

go_repo=$workspace_root/go-service
dural_repo=$workspace_root/dural_trade
go_tree=$task_root/go-service
dural_tree=$task_root/dural_trade
output_dir=$task_root/outputs
go_branch=task/${task_id}-go
dural_branch=task/${task_id}-dural

[[ -d "$workspace_root" ]] || die "workspace root does not exist: $workspace_root"
[[ -d "$go_repo/.git" || -f "$go_repo/.git" ]] || die "not a git repo: $go_repo"
[[ -d "$dural_repo/.git" || -f "$dural_repo/.git" ]] || die "not a git repo: $dural_repo"
[[ ! -e "$task_root" ]] || die "task root already exists: $task_root"

git -C "$go_repo" rev-parse --verify --quiet "${go_ref}^{commit}" >/dev/null || die "go-service base ref not found: $go_ref"
git -C "$dural_repo" rev-parse --verify --quiet "${dural_ref}^{commit}" >/dev/null || die "dural_trade base ref not found: $dural_ref"

if git -C "$go_repo" show-ref --verify --quiet "refs/heads/$go_branch"; then
  die "go-service task branch already exists: $go_branch"
fi
if git -C "$dural_repo" show-ref --verify --quiet "refs/heads/$dural_branch"; then
  die "dural_trade task branch already exists: $dural_branch"
fi

mkdir -p "$output_dir/snapshots" "$output_dir/logs" "$output_dir/tmp"

cleanup_on_error() {
  set +e
  if [[ -d "$go_tree" ]]; then
    git -C "$go_repo" worktree remove --force "$go_tree" >/dev/null 2>&1
  fi
  if [[ -d "$dural_tree" ]]; then
    git -C "$dural_repo" worktree remove --force "$dural_tree" >/dev/null 2>&1
  fi
  git -C "$go_repo" branch -D "$go_branch" >/dev/null 2>&1
  git -C "$dural_repo" branch -D "$dural_branch" >/dev/null 2>&1
}
trap cleanup_on_error ERR

git -C "$go_repo" worktree add -b "$go_branch" "$go_tree" "$go_ref"
git -C "$dural_repo" worktree add -b "$dural_branch" "$dural_tree" "$dural_ref"

go_env_status=$(copy_env_file "$go_repo" "$go_tree" "go-service")
dural_env_status=$(copy_env_file "$dural_repo" "$dural_tree" "dural_trade")

go_root_env_status=$(copy_env_to_root "$go_repo" "$task_root" "go-service.env" "go-service")
dural_root_env_status=$(copy_env_to_root "$dural_repo" "$task_root" "dural_trade.env" "dural_trade")

trap - ERR

go_commit=$(git -C "$go_tree" rev-parse HEAD)
dural_commit=$(git -C "$dural_tree" rev-parse HEAD)
created_at=$(date -Iseconds)

cat > "$task_root/env.sh" <<ENV
export TASK_ID=$(quote_sh "$task_id")
export TASK_ROOT=$(quote_sh "$task_root")
export OUTPUT_DIR=\$TASK_ROOT/outputs
export SNAPSHOT_DIR=\$OUTPUT_DIR/snapshots
export LOG_DIR=\$OUTPUT_DIR/logs
export TMP_DIR=\$OUTPUT_DIR/tmp
export GO_SERVICE_DIR=\$TASK_ROOT/go-service
export DURAL_TRADE_DIR=\$TASK_ROOT/dural_trade
ENV

cat > "$task_root/TASK.md" <<TASK
# Task Workspace: $task_id

- Created: $created_at
- Workspace root: \`$workspace_root\`
- Task root: \`$task_root\`

## Repositories

| Repo | Source | Base ref | Task branch | Start commit | Worktree |
| --- | --- | --- | --- | --- | --- |
| go-service | \`$go_repo\` | \`$go_ref\` | \`$go_branch\` | \`$go_commit\` | \`$go_tree\` |
| dural_trade | \`$dural_repo\` | \`$dural_ref\` | \`$dural_branch\` | \`$dural_commit\` | \`$dural_tree\` |

## Local Environment Files

### Per-repo worktree copies

| Repo | Source \`.env\` | Task \`.env\` | Status |
| --- | --- | --- | --- |
| go-service | \`$go_repo/.env\` | \`$go_tree/.env\` | \`$go_env_status\` |
| dural_trade | \`$dural_repo/.env\` | \`$dural_tree/.env\` | \`$dural_env_status\` |

### Task root copies

| Repo | Source \`.env\` | Root copy | Status |
| --- | --- | --- | --- |
| go-service | \`$go_repo/.env\` | \`$task_root/go-service.env\` | \`$go_root_env_status\` |
| dural_trade | \`$dural_repo/.env\` | \`$task_root/dural_trade.env\` | \`$dural_root_env_status\` |

## Environment

\`\`\`bash
cd "$task_root"
source ./env.sh
\`\`\`

Write task artifacts under:

- \`$output_dir/snapshots\`
- \`$output_dir/logs\`
- \`$output_dir/tmp\`
TASK

cat <<DONE
Created task workspace:
  $task_root

Repos:
  go-service   $go_branch from $go_ref @ $go_commit
  dural_trade  $dural_branch from $dural_ref @ $dural_commit

.env (worktree subdirs):
  go-service   $go_env_status
  dural_trade  $dural_env_status

.env (task root):
  go-service   $go_root_env_status  -> $task_root/go-service.env
  dural_trade  $dural_root_env_status  -> $task_root/dural_trade.env

Next:
  cd "$task_root"
  source ./env.sh
DONE
