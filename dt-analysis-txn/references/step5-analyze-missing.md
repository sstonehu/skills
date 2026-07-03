# Step 5: Analyze Why Target Cycle Is Missing from Refer

## Objective

Determine why a cycle that exists in cycleStore is not selected into a targetRoute's refer topK.

## Background: Phase B route winners selection

Phase B selects topK (20000) cycles per route as `route_winners`. The selection uses:

1. **Hop bucket split**: 2/3-hop bucket (base quota = topK/2) and 4+hop bucket (base quota = topK - topK/2).
2. **Bucket-internal sort**: `score DESC, cycle_id ASC` within each bucket.
3. **Gap fill**: if one bucket has fewer than base quota, the other bucket fills the gap.
4. **No cross-bucket re-sort**: final rank = 2/3-hop prefix + 4+hop prefix.

`PackedScore` encodes `MinUsdScore` and hop group. Higher MinUsdScore = higher score = higher rank within bucket.

## Procedure

### 5.1 Get target cycle metadata

```go
targetMeta := store.CycleMeta[targetCycleId]
// MinUsdScore, HopCount, LogicHopCount, Phase, Flags
```

### 5.2 Get targetRoute's refer cycles

```go
referCycles := store.CyclesByRoute(targetRouteId)
// Returns topK cycleIds sorted by rank
```

### 5.3 Determine hop bucket of target cycle

- `LogicHopCount <= 3`: 2/3-hop bucket
- `LogicHopCount >= 4`: 4+hop bucket

### 5.4 Find boundary MinUsdScore in the target's bucket

Separate refer cycles by hop bucket, find the lowest MinUsdScore in the target's bucket:

```go
var bucketMinUsd uint32 = 0xFFFFFFFF
for _, cid := range referCycles {
    meta := store.CycleMeta[cid]
    if isSameBucket(meta.LogicHopCount, targetMeta.LogicHopCount) {
        if meta.MinUsdScore < bucketMinUsd {
            bucketMinUsd = meta.MinUsdScore
        }
    }
}
```

### 5.5 Compare

- **Target MinUsdScore < boundary MinUsdScore**: cycle's score is too low to enter topK. This is the root cause.
- **Target MinUsdScore >= boundary MinUsdScore but still not in refer**: possible stable-cycle filtering (check `Flags & CycleMetaFlagStableCycle`) or other Phase B filter.

### 5.6 Report

Output:
- Target cycle: cycleId, MinUsdScore, LogicHopCount
- Refer: total cycles, hop bucket distribution (2/3-hop count, 4+hop count)
- Boundary MinUsdScore in target's bucket
- Verdict: "MinUsdScore X below refer boundary Y in 4+hop bucket"

## Common root causes

| Cause | How to identify |
|---|---|
| MinUsdScore too low | Compare target MinUsdScore with boundary in same hop bucket |
| Stable-cycle filter | Check `Flags & CycleMetaFlagStableCycle`; if set, non-cash-like routes filter it out |
| Phase A did not build cycle | Cycle not found in cycleStore at all (Step 3 brute force returns nothing) |
| Config version mismatch | routeIds differ between production logs and worktree; always match by poolAddress+direction, not cycleId |
