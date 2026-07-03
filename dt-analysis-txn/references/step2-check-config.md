# Step 2: Verify PoolIds Exist in Config

## Objective

Check whether all poolIds from the target path exist in `pools.json` and/or `pools_bridge.json`.

## Config file locations

```
dural_trade/config/pools.json          # ETH-like token pools (WETH/ETH/EETH)
dural_trade/config/pools_bridge.json   # All other pools
```

Worktree copies:
```
task_worktrees/<TASK_ID>/dural_trade/config/pools.json
task_worktrees/<TASK_ID>/dural_trade/config/pools_bridge.json
```

## Pool assignment rule

- Pools whose tokens include ETH-like tokens (WETH, ETH, EETH) go to `pools.json`.
- All other pools go to `pools_bridge.json`.
- Each pool exists in exactly one file.

## Procedure

### 2.1 Search for each poolId

```python
import json

pools = json.load(open('pools.json'))
pools_bridge = json.load(open('pools_bridge.json'))

target_addr = "0x..."  # lowercase

for label, data in [('pools.json', pools), ('pools_bridge.json', pools_bridge)]:
    for item in data:
        if target_addr in json.dumps(item).lower():
            # Found
            from_sym = item['fromToken']['symbol']
            to_sym = item['toToken']['symbol']
            pool_id = item.get('poolId', '')
            print(f"{label}: from={from_sym} to={to_sym} poolId={pool_id}")
```

### 2.2 Interpret results

- **All poolIds found**: proceed to Step 3.
- **Some poolIds missing**: investigate why:
  1. Check if the pool exists in rawPools output from `mgr.pools.${dex}.js`
  2. If missing from rawPools: pool discovery issue (check `mgr.pools.${dex}.js` and event topics)
  3. If in rawPools but missing from config: `quote_${dex}_lib.js` filtered it out during `pools_bridge` construction
  4. Check `mgr.autoTask.refreshMevConfigs_agg.js` step 3.1 (refresh local pools) and step 4 (refresh bridge pools)

## Key notes

- `pools.json` entries have `poolAddress` and may have `poolId` (for multi-pool contracts like curveV2).
- `pools_bridge.json` entries for curveV2 have multiple entries per poolAddress (one per coin pair), with `poolId` suffix `_u0_1`, `_u0_2` etc.
- A single poolAddress can generate multiple pool entries with different token pairs.
