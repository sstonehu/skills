---
name: codex-app-model-refresh
description: Diagnose and resolve stale model lists or stale selected models in Codex App when the configured model catalog or `codex debug models` is already current. Use for `/model` menu mismatches, suspected Codex app-server process caches, stale app-server sockets or lock files, daemon-managed versus unmanaged server confusion, and per-thread model state in `~/.codex/state_5.sqlite`.
---

# Codex App Model Refresh

## Start With Read-Only Evidence

Run:

```bash
/home/ecs-user/dt_workspace/skills/codex-app-model-refresh/scripts/diagnose.sh
```

Inspect a known task or recent task model assignments only when needed:

```bash
/home/ecs-user/dt_workspace/skills/codex-app-model-refresh/scripts/diagnose.sh \
  --thread-id <THREAD_ID>
/home/ecs-user/dt_workspace/skills/codex-app-model-refresh/scripts/diagnose.sh \
  --recent-threads 10
```

The script checks the configured catalog, `codex debug models`, app-server processes and start times, daemon version state, sockets, locks, and optional SQLite thread state. It does not restart processes, delete locks, or mutate SQLite.

## Follow The Decision Tree

1. Compare the configured catalog with `codex debug models`.
   - If both are stale, fix the catalog source or `model_catalog_json` path first.
   - If the catalog is current but `codex debug models` is stale, investigate catalog parsing, config selection, or the active `codex` binary.
   - If both are current but Codex App `/model` is stale, stop investigating the catalog. Continue at the App layer.

2. Compare app-server start time with catalog modification time.
   - Treat an app-server that predates the catalog as a likely in-memory stale state.
   - Distinguish the desktop host process containing `features.code_mode_host=true` from `app-server proxy`.
   - Use `codex app-server daemon version` to compare CLI and running app-server versions.

3. Treat lock files as evidence, not the cause.
   - Check `~/.codex/app-server-control/` and `~/.codex/app-server-daemon/`.
   - Use `lsof <lock>` before concluding a lock is held.
   - Do not delete `.lock` files merely because their timestamps are old. In the resolved incident, no process held the locks; the stale long-running app-server process was the important state.

4. Determine whether the server is daemon-managed.
   - `codex app-server daemon stop` can report that a running server is not managed by the daemon.
   - `managedCodexVersion: null` or a missing `~/.codex/packages/standalone/current/codex` means daemon restart commands may not be usable.
   - A desktop SSH reconnect can relaunch `codex -c features.code_mode_host=true app-server --listen unix://` without the standalone daemon install.

5. Inspect per-task state without confusing history with an active defect.
   - `~/.codex/state_5.sqlite`, table `threads`, column `model` persists the selected model for each task.
   - A stale task model does not prove the model catalog is stale.
   - Read-only inspection is safe at any point, but treat it only as persisted-state evidence.
   - Enter the task-state remediation branch only when a fresh App server still opens the exact task with an obsolete selected model.
   - Verify the exact task ID before changing anything.

6. Check whether the Codex App frontend itself needs a restart.
   - The app-server restart refreshes server-side in-memory state, but the Codex App frontend (TUI process or Electron desktop client) caches the model list independently in its own memory.
   - After an app-server restart, reconnecting or resuming is not enough: the frontend may still display the old model list cached from before the catalog changed.
   - If the catalog, `codex debug models`, and a freshly restarted app-server all agree but the `/model` menu still shows stale models, a full restart of the Codex App is required.
   - In an XRDP/remote-desktop setup the Codex App may run as a local process on the server; in a desktop SSH setup the Electron client runs on the user's local machine. Either way, the frontend process must be restarted, not just reconnected.

## Apply Remediation Carefully

Prefer this order:

1. Capture the read-only diagnostic output.
2. Refresh the desktop connection or restart a genuinely daemon-managed app-server.
3. Verify that the app-server PID/start time changed.
4. Re-run `codex debug models` and check Codex App `/model`; CLI output alone is not proof that the App is fixed.
5. If the app-server is fresh but `/model` is still stale, restart the Codex App frontend itself (close and reopen the TUI/Electron client). Reconnecting or resuming without a full restart will not clear the frontend's in-memory model cache.
6. Change task SQLite state only when a fresh App server plus a restarted frontend still opens the exact task with an obsolete selected model.

Killing the `features.code_mode_host=true` app-server disconnects the current Codex App task. Warn the user and require an explicit restart request before doing it from an active task.

Before any SQLite mutation:

```bash
cp --preserve=all ~/.codex/state_5.sqlite \
  ~/.codex/state_5.sqlite.bak-modelmenu-$(date +%Y%m%dT%H%M%S)
```

Then update only the verified task ID and verify the resulting row. Never bulk-rewrite task models.

## Preserve These Lessons

- Use `codex debug models` as the fresh CLI/catalog parsing check.
- Treat Codex App model menus, app-server memory, frontend connection state, and task SQLite state as separate diagnostic surfaces.
- Avoid broad searches through `~/.codex/sessions`, `history.jsonl`, or `logs_2.sqlite`; they are noisy and rarely identify this mismatch.
- Prefer targeted `ps`, `stat`, `/proc/<pid>`, `lsof`, `codex app-server daemon version`, and read-only SQLite queries.
- Do not declare success until the App `/model` menu or the affected task itself reflects the expected model.
- The Codex App frontend (TUI/Electron) has its own in-memory model cache separate from the app-server. An app-server restart alone does not clear it; a full frontend restart is required.
- Remediating a stale model list is a two-layer fix: restart the app-server for server-side cache, then restart the Codex App for frontend cache. Both layers must be refreshed.
