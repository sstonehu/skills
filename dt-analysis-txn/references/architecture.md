# Architecture: Pools, Routes, Cycles, Refer

Background knowledge for analyzing competitor transactions. Read this when you need to understand how the pipeline constructs and selects cycles.

## 1. Pools Construction

### Source

`dural_trade/scripts/mgr/mgr.autoTask.refreshMevConfigs_agg.js` orchestrates pool refresh:

1. **Step 3.1 refresh local pools**: calls `mgr.pools.${dex}.js` per DEX to fetch rawPools from on-chain data or subgraph.
2. **Step 4 refresh bridge pools**: calls `quote_${dex}_lib.js` to construct `pools_bridge.json` entries from rawPools, applying DEX-specific filtering and token-pair expansion.

### Assignment rule

- Pools whose tokens include ETH-like tokens (WETH `0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2`, ETH `0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE`, EETH) go to `pools.json`.
- All other pools go to `pools_bridge.json`.
- A single poolAddress appears in exactly one file.

### Multi-entry pools

Some DEX contracts host multiple logical pools at one address (e.g., curveV2). These generate multiple entries per poolAddress, distinguished by `poolId` suffix:
- `_0_1`: non-underlying exchange, coins i=0 j=1
- `_u0_1`: underlying exchange, coins i=0 j=1
- `_u0_2`: underlying exchange, coins i=0 j=2

Each entry has a specific `fromToken` -> `toToken` pair. The `fromToken`/`toToken` in config defines only one direction; the reverse direction is generated at route construction time.

### Config entry structure

```json
{
  "dex": "curveV2",
  "poolAddress": "0x579a...",
  "poolId": "0x579a..._u0_2",
  "fromToken": {"address": "0x99D8...", "symbol": "MIM", "decimals": 18},
  "toToken": {"address": "0xdAC1...", "symbol": "USDT", "decimals": 6},
  "rawIds": ["0x579a..."],
  "zeroForOne": true,
  "reserve0": "...", "reserve1": "...",
  "usdTotal": 162245.17
}
```

## 2. Routes Construction

### From pool to routes

Each Pool generates **two Routes**: forward (fromToken -> toToken) and reverse (toToken -> fromToken). Both share the same `PoolId` and `PoolAddress` but have swapped `FromAddress`/`ToAddress`.

### Route struct (go-service/model/base/route.go)

Key fields:
- `RouteId`: global unique uint32 index, used for cycleStore and refer lookups.
- `PoolId`: inherited from pool config (e.g., `0x579a..._u0_2`).
- `FromAddress` / `ToAddress`: token addresses (swapped for reverse).
- `FromToken` / `ToToken`: token metadata pointers.
- `Pool`: back-pointer to pool config (poolAddress, dex, reserves, usdTotal, rawIds).
- `Rev`: pointer to the reverse Route. `route.Rev.RouteId` gives the opposite direction's routeId.
- `DirectionFwd`: true for forward, false for reverse.
- `Token0In`: whether token0 is the input token.

### routes.bin

Routes are serialized to `routes.bin` via `model/builder/serializer.go::SerializeRoutesAndSave`. The file stores a flat array of Route structs. At runtime, `cache.Routes` is indexed by RouteId (0..N-1).

### RouteId stability

RouteIds are **not stable** across config versions. Adding or removing pools shifts all subsequent RouteIds. Always match routes by poolAddress + token direction, never by RouteId from a different config version.

## 3. Cycles Construction (Phase A)

### DFS enumeration

Phase A uses DFS to enumerate all合法 closed cycles from the route graph. See `go-service/docs/design-cycle-precompute-duckdb.md` for full design.

### Two phases of DFS

- **Phase 1 (WETHWETH)**: `CyclePhaseWETHWETH = 1`. Cycles anchored on ETH-like tokens (WETH/ETH/EETH). DFS starts from ETH-like routes and closes back to ETH-like. These are the primary arbitrage cycles.
- **Phase 2 (StableCash)**: `CyclePhaseStableCash = 2`. Cycles anchored on stable tokens with a cash pool to ETH-like. Main path: `stable -> targetToken -> ... -> stable`, with `stable -> ETH-like` as cash pool metadata (`CashPoolRouteID`). ETH-like tokens are NOT allowed inside the stable-cash main DFS path.

### Cycle constraints

- Max 12 routes per cycle (route_0..route_11 in DuckDB schema).
- Cycle must form a closed loop: last route's toToken == first route's fromToken.
- `HopCount`: total route count in the cycle.
- `LogicHopCount`: logical hop count (may differ from HopCount for multi-step routes like uniswapV4).

### Stable-cycle marking

At cycle closure, Phase A checks if the cycle contains consecutive stable token segments:
- `CycleMetaFlagStableCash` (bit 0): stable-cash cycle.
- `CycleMetaFlagStableCycle` (bit 1): cycle has at least one `stable -> stable` route.

These flags affect Phase B refer filtering.

### CycleMeta fields

```go
type CycleMeta struct {
    HopCount        uint8   // total routes
    LogicHopCount   uint8   // logical hops (affects bucket assignment)
    Phase           uint8   // 1=WETHWETH, 2=StableCash
    Flags           uint16  // stable-cycle flags
    AnchorTokenID   uint32  // anchor token
    CashPoolRouteID uint32  // cash pool route (Phase 2 only)
    MinUsdScore     uint32  // minimum USD liquidity score across all routes in cycle
}
```

`MinUsdScore` is the key ranking signal: the minimum `usdTotal` across all pools in the cycle. Higher = more liquid = higher PackedScore.

### cycleId instability

cycleId is assigned during Phase A shard merge, based on arrival order. It is **not stable** across precompute runs. Different config versions produce different cycleIds for the same logical cycle.

### Output

Phase A writes to DuckDB `cycle_summary` table (~360M+ rows). Each row has cycle_id, score (PackedScore), meta (packed flags), route_len, and route_0..route_11.

## 4. Refer Selection (Phase B)

### Objective

For each routeId, select topK (20000) cycles as `route_winners`. These are the cycles the builder will consider when that route is the targetRoute.

### PackedScore

`PackedScore` is a uint64 that encodes:
- **Bit 63**: hop group. `1` = 2/3-hop (high priority), `0` = 4+hop (lower priority).
- **Lower bits**: MinUsdScore and other quality signals.

This means in raw `score DESC` ordering, all 2/3-hop cycles rank above all 4+hop cycles.

### Dual hop-bucket allocation

To prevent 2/3-hop cycles from monopolizing refer slots, Phase B splits topK into two buckets:

| Bucket | LogicHopCount | Base quota |
|---|---|---|
| Short (2/3-hop) | <= 3 | topK / 2 = 10000 |
| Long (4+hop) | >= 4 | topK - topK/2 = 10000 |

Rules:
1. Each bucket sorts internally by `score DESC, cycle_id ASC`.
2. If both buckets have enough candidates: each keeps base quota.
3. If one bucket is short: the other bucket fills the gap from its sorted surplus.
4. Final rank: short bucket prefix (rank 0..N-1), then long bucket prefix (rank N..M-1).
5. No cross-bucket re-sort after merge.

### Stable-cycle filtering

Before bucket sorting, candidates are filtered:

```
keep_candidate = NOT cycle_has_stable_cycle_flag OR route_is_stable_route
```

Where `is_stable_route` = both fromToken and toToken are cash-like (stable OR ETH-like OR bridge token).

Effect: non-cash-like routes (e.g., `WBTC -> WETH`) cannot refer stable-cycles. This prevents stable-token noise from flooding regular route refers.

### Phase B output

`route_winners` table: (route_id, rank, cycle_id, score). Each route has at most topK entries.

### Phase C export

Phase C exports `route_winners` to `routeOffsets.bin` + `routeCycleIds.bin` (CSR format). At runtime, `store.CyclesByRoute(routeId)` returns the topK cycleIds for that route.

## 5. Builder Refer Lookup

When builder receives an opportunity with `targetRouteId`:

1. Call `store.CyclesByRoute(targetRouteId)` to get up to 20000 cycleIds.
2. For each cycleId, reconstruct DuralPath from cycle routes.
3. Return DuralPaths to simulator for pricing.

If the target cycle is not in the refer topK, builder will never consider it, regardless of whether it exists in cycleStore.

## 6. Block Path vs Pool Path

The same pool address has two route directions:
- Forward: e.g., WETH -> USDT (routeId A)
- Reverse: e.g., USDT -> WETH (routeId B = A.Rev)

Block path and pool path may use different directions as targetRoute:
- Block path: targetRouteId = route for `USDT -> WETH` (the direction matching the block swap)
- Pool path: targetRouteId = route for `WETH -> USDT` (the direction matching the mempool swap)

A cycle may appear in one routeId's refer but not the other's, because:
- The two routeIds have independent refer lists.
- The cycle's PackedScore is the same, but the competing cycles in each refer list differ.
- One direction may have higher-USD pools competing, pushing the target cycle below topK.

## 7. Key documents

- `go-service/docs/design-cycles-index.md`: document index
- `go-service/docs/design-cycle-precompute-duckdb.md`: Phase A/B/C/D main design
- `go-service/docs/design-cycle-precompute-duckdb-phaseB-sort.md`: Phase B dual-bucket detail
- `go-service/model/base/route.go`: Route struct
- `go-service/model/base/cycle_store.go`: CycleStore struct and CSR lookup methods
- `go-service/core/precomputed/cycle_bundle_file.go`: split-bin load/save
