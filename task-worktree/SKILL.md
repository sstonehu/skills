---
name: task-worktree
description: Create isolated multi-repo git worktree task workspaces for Dural Trade replay, operations, testing, snapshot-generating, and script-changing tasks. Use when a task touches both go-service and dural_trade, needs TASK_ID-scoped outputs, or must avoid dirtying the clean dt_workspace checkouts.
---

# Task Worktree

## Overview

Use this skill before cross-repo replay, operations, testing, or snapshot-generating work that can modify scripts or produce same-named files. It creates one task directory containing separate git worktrees for `go-service` and `dural_trade`, copies each repo's `.env` file when present (both into the worktree subdirectory and to the task root with a distinguishing name), plus task-local output directories.

Default repo bases:

- `go-service`: `feature/cycle-order`
- `dural_trade`: `direct-guard`

The user previously referred to `direct-gurad`; the local repo branch is `direct-guard`, so use `direct-guard` unless the user explicitly overrides it.

## Create A Task Workspace

Run the bundled script from the skill directory:

```bash
/home/ecs-user/dt_workspace/skills/task-worktree/scripts/create-task-workspace.sh <TASK_ID>
```

Example:

```bash
/home/ecs-user/dt_workspace/skills/task-worktree/scripts/create-task-workspace.sh replay-20260701-001
```

The script creates:

```text
/home/ecs-user/dt_workspace/task_worktrees/<TASK_ID>/
  go-service/
  dural_trade/
  go-service.env        # copy of go-service/.env at task root
  dural_trade.env       # copy of dural_trade/.env at task root
  outputs/
    snapshots/
    logs/
    tmp/
  env.sh
  TASK.md
```

The script copies `.env` files in two places:

- **Per-repo worktree subdirectory**: `go-service/.env` and `dural_trade/.env` inside each worktree, so tools that expect `.env` next to the repo root work normally.
- **Task root**: `go-service.env` and `dural_trade.env` at the task root, for easy sourcing or inspection without descending into each worktree.

Specifically:

- `/home/ecs-user/dt_workspace/go-service/.env` → `<TASK_ID>/go-service/.env` and `<TASK_ID>/go-service.env`
- `/home/ecs-user/dt_workspace/dural_trade/.env` → `<TASK_ID>/dural_trade/.env` and `<TASK_ID>/dural_trade.env`

All copies happen only when the source `.env` exists. It records the copy status of each in `TASK.md`. It refuses to overwrite any existing target file.

After creation, switch into the task workspace:

```bash
cd /home/ecs-user/dt_workspace/task_worktrees/<TASK_ID>
source ./env.sh
```

Then run all task commands from `$GO_SERVICE_DIR` and `$DURAL_TRADE_DIR`. Write snapshots, logs, and temporary artifacts under `$SNAPSHOT_DIR`, `$LOG_DIR`, or `$TMP_DIR`.

## Override Branches Or Paths

Use overrides only when the user explicitly asks for different bases or a non-default workspace root:

```bash
create-task-workspace.sh <TASK_ID> \
  --go-branch <ref> \
  --dural-branch <ref> \
  --workspace-root /home/ecs-user/dt_workspace
```

Refs may be local branches, tags, commit SHAs, or remote refs such as `origin/main`.

## Clean Up

When a task is finished and no process is using the worktrees, remove the task worktrees with:

```bash
/home/ecs-user/dt_workspace/skills/task-worktree/scripts/remove-task-workspace.sh <TASK_ID>
```

By default this removes the copied `.env` files from task worktrees, keeps `outputs/`, `env.sh`, and `TASK.md`, and does not delete task branches. To delete fully merged branches, pass `--delete-branches`. Do not use force deletion unless the user explicitly asks.

## Rules

- Do not modify `/home/ecs-user/dt_workspace/go-service` or `/home/ecs-user/dt_workspace/dural_trade` directly for cross-repo operations tasks after this skill triggers.
- Do not write task snapshots or logs to shared absolute paths unless the path includes `TASK_ID`.
- If a task workspace already exists, inspect it rather than recreating or overwriting it.
- If branch creation fails because a branch already exists or is checked out elsewhere, stop and report the exact branch and worktree path.

## Enable Snapshot Dump Switches

When debugging or replaying, you often need go-service to dump intermediate JSON snapshots to `test_output/`. The source files contain commented-out `util.WriteJSONFile` calls for this purpose. Use the bundled script to uncomment them all at once:

```bash
/home/ecs-user/dt_workspace/skills/task-worktree/scripts/enable-snapshot-dump.sh [GO_SERVICE_DIR]
```

If `GO_SERVICE_DIR` is omitted, it defaults to `./go-service` (task worktree layout).

The script is idempotent and handles missing imports automatically. It uncomments dump calls for:

| File | Snapshot files |
| --- | --- |
| `opportunity_handler.go` | `simulatorEvent.json` |
| `simulator_async.go` | `SeedOut.json`, `Mid25Revenue.json`, `Mid25Revenue.after.json`, `mid1_Revenue.json` (x2) |
| `pricer.go` | `pricer.requestBodies.%d.json`, `pricer.responses.%d.json` |
| `try_arbi_batch.go` | `reqs.json`, `debug_result.json` |
| `try_arbi_batch_direct.go` | `direct_reqs.json`, `direct_resp.json` |

It also:

- Creates `test_output/` in the go-service directory (`os.WriteFile` does not create directories).
- Uncomments or adds the `"log"` and `"go-service/pkg/util"` imports where needed.
- Leaves the `else` branch (`dynamic_resp.json`) in `try_arbi_batch_direct.go` commented, because Go requires `} else {` on one line and the user only requested `direct_*` files.

To revert all changes:

```bash
cd <GO_SERVICE_DIR>
git checkout -- core/builder/opportunity_handler.go core/simulator/simulator_async.go core/pricer/pricer.go core/simulator/try_arbi_batch.go core/simulator/try_arbi_batch_direct.go
```
