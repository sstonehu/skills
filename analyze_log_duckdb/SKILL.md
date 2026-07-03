---
name: analyze_log_duckdb
description: Use when analyzing Dural Trade / go-service / dural_trade production JSONL logs with DuckDB, including requests mentioning analyze_log_duckdb, /dt-logs, builder.getPaths, builder.buildResult, mevListener tags, simulator stages, source/liquidityType distributions, or cycleIds duplication.
---

# Analyze Logs With DuckDB

Use this skill for production log analysis in `/home/ecs-user/dt_workspace`.

## Defaults

- Logs live under `/dt-logs/log/mainnet/YYYY/MM/DD/HH/`.
- Include both `*.log` and `*.log.gz`.
- DuckDB working directory is `/dt-logs/duckDB/`.
- Logs are JSON Lines. Common root fields:
  - `timestamp`
  - `podName`
  - `tag`
  - `message`
  - `timeRecord`
  - Go logs may also include `caller`.
- JS/dural_trade logs use `logger.info`.
- Go/go-service logs use `logger.GlobalLogger.Info`.

## Important Operational Notes

- For recent windows, derive the absolute hour directories from local time, not memory.
- For cross-hour investigations, load adjacent hours together. Pricer logs can be split oddly by rotation and may require including the previous hour.
- Go pricer logs may be `root:root 0600` because `lumberjack` creates files with mode `0600`; DuckDB will fail on unreadable files. Before importing Go-side logs, run the bundled permission fixer on the target hour directories when unreadable pricer files exist.
- Do not silently skip unreadable pricer logs when the target tag is Go-side (`builder.*`, `simulator.*`, `SIM.MID1_DONE`) unless the user explicitly asks for readable-only analysis.
- Pricer uses size rotation; old segments may be deleted by `MaxBackups` retention, so absence of old `.gz` files can be retention loss, not lack of events.

## Workflow

1. Identify the exact hour directories.
2. Check file count and unreadable files.
3. If unreadable Go pricer files exist, run `scripts/fix-log-permissions.sh` for those hour directories, then re-check unreadable files.
4. Create a task-specific DuckDB under `/dt-logs/duckDB/`.
5. Import raw logs with `read_json_objects(..., format='newline_delimited', filename=true)`.
6. Create a parsed view with core fields:
   - `log_hour`
   - `ts`
   - `pod_name`
   - `tag`
   - `source = $.timeRecord.source`
   - `liquidity_type = $.timeRecord.liquidityType`
   - block keys such as `$.timeRecord.blockHash`, `$.timeRecord.blockNumber`, `$.message.blockNumber`, `$.message.block`
7. Query from the parsed view or create narrow temporary tables for heavy JSON arrays such as `message.cycleIds`.
8. Report counts, hour coverage, DB path, and any permission/retention caveats.

## Permission Fixer

Use `scripts/fix-log-permissions.sh` before DuckDB import when target Go pricer logs are unreadable.

The script:

- Accepts one or more hour directories under `/dt-logs/log/mainnet/`.
- Only touches `combined_dt-mev-statefulset-pricer-0*.log*`.
- Includes both `*.log` and `*.log.gz`.
- Defaults to `chown ecs-user:ecs-user` and `chmod 0644`.
- Refuses paths outside `/dt-logs/log/mainnet/`.
- Re-execs via `sudo` for non-dry-run fixes when not already root.

Examples:

```bash
skills/analyze_log_duckdb/scripts/fix-log-permissions.sh --dry-run /dt-logs/log/mainnet/2026/06/11/15
skills/analyze_log_duckdb/scripts/fix-log-permissions.sh /dt-logs/log/mainnet/2026/06/11/11 /dt-logs/log/mainnet/2026/06/11/12
```

If sudo password prompts block Codex, configure sudoers for the fixed script path rather than allowing arbitrary `chmod`:

```bash
sudo install -o root -g root -m 0755 \
  /home/ecs-user/dt_workspace/skills/analyze_log_duckdb/scripts/fix-log-permissions.sh \
  /usr/local/sbin/dt-fix-log-permissions

echo 'ecs-user ALL=(root) NOPASSWD: /usr/local/sbin/dt-fix-log-permissions' | \
  sudo tee /etc/sudoers.d/dt-fix-log-permissions

sudo chmod 0440 /etc/sudoers.d/dt-fix-log-permissions
sudo visudo -cf /etc/sudoers.d/dt-fix-log-permissions
```

The workspace script automatically prefers `/usr/local/sbin/dt-fix-log-permissions`
when that helper exists, so normal skill usage can keep calling the script path.

## Query Templates

Use [references/query-templates.md](references/query-templates.md) for copy-ready snippets:

- recent N-hour import
- tag counts by hour
- `source × liquidityType` distribution
- block target lookup
- `builder.buildResult` `cycleIds` expansion and duplication analysis
- unreadable file diagnostics
