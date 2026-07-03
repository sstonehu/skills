#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  remove-task-workspace.sh <TASK_ID> [options]

Options:
  --workspace-root <path>  Workspace root. Default: /home/ecs-user/dt_workspace
  --task-root <path>       Exact task root. Default: <workspace-root>/task_worktrees/<TASK_ID>
  --delete-branches        Delete task branches with git branch -d after removing worktrees.
  -h, --help               Show this help.

Removes go-service and dural_trade worktrees for a task. Removes copied .env
files from the task worktrees and task root first, then keeps outputs, env.sh,
and TASK.md by default.
USAGE
}

die() {
  echo "error: $*" >&2
  exit 1
}

remove_copied_env() {
  local tree=$1
  local label=$2
  local env_file=$tree/.env

  if [[ -f "$env_file" ]]; then
    rm -f "$env_file"
    echo "removed copied $label .env: $env_file"
  fi
}

remove_root_env() {
  local task_root_dir=$1
  local root_name=$2
  local label=$3
  local env_file=$task_root_dir/$root_name

  if [[ -f "$env_file" ]]; then
    rm -f "$env_file"
    echo "removed copied $label root env: $env_file"
  fi
}

workspace_root=${DT_WORKSPACE_ROOT:-/home/ecs-user/dt_workspace}
task_root=
delete_branches=0
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
    --delete-branches)
      delete_branches=1
      shift
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
go_branch=task/${task_id}-go
dural_branch=task/${task_id}-dural

[[ -d "$go_repo/.git" || -f "$go_repo/.git" ]] || die "not a git repo: $go_repo"
[[ -d "$dural_repo/.git" || -f "$dural_repo/.git" ]] || die "not a git repo: $dural_repo"
[[ -d "$task_root" ]] || die "task root does not exist: $task_root"

if [[ -d "$go_tree" ]]; then
  remove_copied_env "$go_tree" "go-service"
  git -C "$go_repo" worktree remove "$go_tree"
else
  echo "skip: go-service worktree not found: $go_tree"
fi

if [[ -d "$dural_tree" ]]; then
  remove_copied_env "$dural_tree" "dural_trade"
  git -C "$dural_repo" worktree remove "$dural_tree"
else
  echo "skip: dural_trade worktree not found: $dural_tree"
fi

remove_root_env "$task_root" "go-service.env" "go-service"
remove_root_env "$task_root" "dural_trade.env" "dural_trade"

if [[ "$delete_branches" -eq 1 ]]; then
  git -C "$go_repo" branch -d "$go_branch"
  git -C "$dural_repo" branch -d "$dural_branch"
else
  cat <<DONE
Kept task branches:
  $go_branch
  $dural_branch

To delete fully merged branches later:
  git -C "$go_repo" branch -d "$go_branch"
  git -C "$dural_repo" branch -d "$dural_branch"
DONE
fi

cat <<DONE
Removed task worktrees for:
  $task_root

Kept task metadata and outputs unless you delete them manually:
  $task_root/outputs
  $task_root/env.sh
  $task_root/TASK.md
DONE
