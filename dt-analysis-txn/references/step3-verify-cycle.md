# Step 3: Verify Target Cycle Exists in CycleStore

## Objective

Confirm whether the target 4-pool cycle exists in the current cycleStore, and whether it appears in the targetRoute's refer.

## Prerequisites

- Worktree with go-service config matching the target block's production config (or closest available).
- `precomputed_meta.json` tokenlistTimeStamp must match `tokenlist_1.json` timeStamp. Fix if mismatched:
  ```python
  import json
  meta = json.load(open('conf/precomputed_meta.json'))
  tl_ts = json.load(open('conf/tokenlist_1.json'))['timeStamp']
  meta['tokenlistTimeStamp'] = tl_ts
  json.dump(meta, open('conf/precomputed_meta.json','w'), indent=2)
  ```

## Key concepts

- **Pool**: defined in pools.json/pools_bridge.json, one direction.
- **Route**: each Pool generates two Routes (forward + reverse). Route has `FromToken`, `ToToken`, `RouteId`, `Rev` (reverse route pointer).
- **Cycle**: DFS-constructed closed loop of routes. Stored in cycleStore as routeId sequences.
- **Refer (routeCycleIDs)**: for each routeId, a topK (20000) list of cycleIds sorted by PackedScore. This is what builder reads to generate DuralPaths.
- A cycle may exist in cycleStore but NOT be in a route's refer (if its score is too low to make topK).

## Procedure

### 3.1 Find routeIds for target pools

Search `cache.Routes` by `Pool.PoolAddress` (case-insensitive). Each pool will have multiple routes (forward + reverse, possibly multiple poolId variants).

```go
for _, route := range cache.Routes {
    poolAddr := strings.ToLower(route.Pool.PoolAddress)
    if targetPoolAddrs[poolAddr] {
        // Print routeId, poolId, fromToken, toToken
    }
}
```

### 3.2 Match target path to specific routeIds

The target path has a specific token flow direction. Match each leg by poolAddress + fromToken symbol + toToken symbol.

Example for path EETH->USDC->MIM->USDT->WETH:
```
[0] pool=0x836951EB from=EETH to=USDC  -> routeId=33564
[1] pool=0x5a6A4D54 from=USDC to=MIM   -> routeId=23701
[2] pool=0x579a9A9d from=MIM to=USDT   -> routeId=22950
[3] pool=0xc7bBeC68 from=USDT to=WETH  -> routeId=56027
```

### 3.3 Check if cycle exists in cycleStore

Three search methods, in order:

1. **Refer search**: check `store.CyclesByRoute(targetRouteId)` for a cycle containing all 4 routeIds.
2. **Refer intersection**: collect cycleIds from all 4 routeIds' refers, find cycles appearing in all 4 sets.
3. **Brute force**: scan all cycles in `store.CycleMeta` with matching hop count.

```go
for cid := uint32(0); cid < uint32(len(store.CycleMeta)); cid++ {
    cycleRoutes := store.CycleRoutesOf(cid)
    if len(cycleRoutes) != len(targetRouteIds) { continue }
    matchCount := 0
    for _, crid := range cycleRoutes {
        if targetRouteIdSet[crid] { matchCount++ }
    }
    if matchCount == len(targetRouteIds) {
        // Found
    }
}
```

### 3.4 Also check reverse direction

The same 4 pools traversed in reverse direction forms a different cycle with different routeIds. Check both directions as they are independent cycles in the store.

### 3.5 Interpret results

- **Cycle exists AND is in targetRoute's refer**: builder should find it. Proceed to Step 4 (replay).
- **Cycle exists but NOT in refer**: cycle score too low for topK. Proceed to Step 5 (score comparison).
- **Cycle does NOT exist**: preCompute DFS did not build this cycle. Investigate Phase A DFS construction.
