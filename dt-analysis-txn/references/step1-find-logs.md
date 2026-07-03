# Step 1: Find Corresponding Logs

## Objective

Locate production mid1 logs for the target block and targetPoolId, check whether the target arbitrage path was found.

## Procedure

### 1.1 Locate log directory

Production logs are under `/dt-logs/log/mainnet/<YYYY>/<MM>/<DD>/<HH>/`.

Files are gzipped: `combined_dt-mev-statefulset-pricer-0-<timestamp>.log.gz`.

### 1.2 Find files containing the block number

```bash
cd /dt-logs/log/mainnet/<YYYY>/<MM>/<DD>/<HH>
zgrep -l "<blockNumber>" *.gz
```

### 1.3 Search mid1 logs for targetPoolId

mid1 logs have tag `simulator.mid1` in pricer files. Each entry has `timeRecord` with:
- `blockNumber`: target block
- `blockHash`: equals blockNumber string for block-path entries; empty string for mempool/servo2 pool-path entries
- `liquidityType`: `"block"` for block path; `"pool"` for mempool/servo2 path
- `targetPoolId` / `targetPool`: the target pool address
- `targetRouteId`: route ID for this opportunity

```bash
zcat <files> | grep '"simulator.mid1"' | grep '<blockNumber>' | grep -i '<targetPoolAddr>'
```

### 1.4 Distinguish block path vs pool path

Filter by `timeRecord.blockHash` and `timeRecord.liquidityType`:
- Block path: `blockHash == "<blockNumber>"`, `liquidityType == "block"`
- Pool/mempool path: `blockHash == ""`, `liquidityType == "pool"`

Both paths use the same cycleStore but different targetRouteId (opposite directions of the same pool).

### 1.5 Check if target cycle exists in mid1 output

mid1 entries contain `cyclePoolIds` array. Each element has `cycleId` and `poolIds`.

Match target poolIds (strip `_u0_N` suffix to compare poolAddress). A full match means all 4 target pools appear in one cycle's poolIds.

```python
# Match logic: strip _u0_N suffix from poolId for pool address comparison
pid_set = set(p.lower().split('_')[0] for p in cycle_pool_ids)
target_pools_set.issubset(pid_set)  # full match
```

### 1.6 Interpret results

- **Block path mid1 found target cycle**: success, production found the path. Stop.
- **Block path mid1 did NOT find target cycle**: proceed to Step 2.
- Note: pool path may find the cycle even if block path does not — this is expected since they use different targetRouteId (opposite directions).

## Key fields

| Field | Location | Meaning |
|---|---|---|
| `tag` | top-level | `simulator.mid1` for mid1 stage |
| `message.block` | message | block number string |
| `message.cyclePoolIds` | message | array of {cycleId, poolIds[]} |
| `timeRecord.blockHash` | timeRecord | block path: equals blockNumber; pool path: empty |
| `timeRecord.liquidityType` | timeRecord | `block` or `pool` |
| `timeRecord.targetPoolId` | timeRecord | target pool address |
| `timeRecord.targetRouteId` | timeRecord | route ID for this opportunity |
