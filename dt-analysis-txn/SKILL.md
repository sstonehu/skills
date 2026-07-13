---
name: dt-analysis-txn
description: Analyze why a competitor arbitrage transaction was or was not caught by production. Given a competitor txHash and target block, walk through 5 steps to locate mid1 logs, verify pool config, confirm cycle existence in cycleStore, replay builder, and diagnose refer selection gaps. Use when analyzing competitor MEV transactions, diagnosing missed arbitrage opportunities, or replaying production opportunity paths. Each step can be invoked independently.
---

# DT Analysis Txn

Analyze whether production caught a competitor arbitrage path, and if not, locate the root cause.

## Overview

Given a competitor txHash and the target block it backran, walk through up to 5 steps. Each step is a self-contained sub-skill that can be invoked independently.

## Inputs

- `txHash`: competitor transaction hash (0x...)
- `blockNumber`: the block the competitor backran (target block)
- `targetPoolId`: the pool address that triggered the opportunity (the target pool in the block)
- `targetPath`: list of (dex, poolAddress, fromToken -> toToken) legs describing the arbitrage cycle

## Task Workspace

Use the `task-worktree` skill to create an isolated workspace before starting:

```bash
/home/ecs-user/dt_workspace/skills/task-worktree/scripts/create-task-workspace.sh <TASK_ID>
cd /home/ecs-user/dt_workspace/task_worktrees/<TASK_ID>
source ./env.sh
```

Copy `.env` files from the clean checkouts:

```bash
cp /home/ecs-user/dt_workspace/go-service/.env go-service/.env
cp /home/ecs-user/dt_workspace/dural_trade/.env dural_trade/.env
```

## Steps

Execute steps in order. Stop early when a root cause is found. Each step references a detailed guide in `references/`.

### Step 1: Find Corresponding Logs

Check whether block-path mid1 logs for the target block contain the target cycle.

Read: [references/step1-find-logs.md](references/step1-find-logs.md)

Key: search pricer logs under `/dt-logs/log/mainnet/<YYYY>/<MM>/<DD>/<HH>/` for `simulator.mid1` entries with matching blockNumber and targetPoolId. Distinguish `liquidityType=block` (block path) from `liquidityType=pool` (mempool/servo2 path) by `timeRecord.blockHash`.

- Block path found target cycle: **success**, production caught it. Stop.
- Block path did NOT find: proceed to Step 2.

### Step 2: Verify PoolIds Exist in Config

Check all poolAddresses from the target path exist in `pools.json` (ETH-like) or `pools_bridge.json` (others).

Read: [references/step2-check-config.md](references/step2-check-config.md)

- All found: proceed to Step 3.
- Some missing: investigate pool discovery (`mgr.pools.${dex}.js`) or bridge construction (`quote_${dex}_lib.js`). Stop and report.

### Step 3: Verify Target Cycle Exists in CycleStore

Confirm the target cycle (specific route direction) exists in the current cycleStore and whether it appears in the targetRoute's refer topK.

Read: [references/step3-verify-cycle.md](references/step3-verify-cycle.md)

Key: match routes by poolAddress + fromToken + toToken (not by cycleId, which is unstable across config versions). Search cycleStore via refer lookup, refer intersection, and brute force.

- Cycle exists AND in refer: proceed to Step 4.
- Cycle exists but NOT in refer: proceed to Step 5.
- Cycle does NOT exist: investigate Phase A DFS construction. Stop and report.

### Step 4: Replay Builder and Simulator

Replay the opportunity through builder to generate simulatorEvent.json, verify target cycle appears in DuralPaths.

Read: [references/step4-replay.md](references/step4-replay.md)

Key: uncomment opportunity.json dump in `mev.listener.block.js`, run `test_mev.simulator_block.js` via hardhat, copy opportunity.json to go-service, uncomment simulatorEvent.json dump in `opportunity_handler.go`, **uncomment pipeline stage snapshot dumps in `simulator_async.go`** (SeedOut, Mid25Revenue, Mid25Revenue.after, priceMapAcc, mid1_Revenue), run `replay_builder`.

- Target cycle in DuralPaths: optionally replay_simulator for detailed simulation. Stop.
- Target cycle NOT in DuralPaths: proceed to Step 5.

### Step 5: Analyze Why Target Cycle Is Missing from Refer

Compare target cycle's MinUsdScore against the boundary MinUsdScore in the same hop bucket of the targetRoute's refer.

Read: [references/step5-analyze-missing.md](references/step5-analyze-missing.md)

Key: Phase B splits refer into 2/3-hop bucket (quota topK/2) and 4+hop bucket (quota topK/2). Within each bucket, cycles are ranked by PackedScore DESC. If target cycle's MinUsdScore is below the bucket boundary, it cannot enter refer.

Report: target MinUsdScore, boundary MinUsdScore, hop bucket, verdict.

## Architecture Background

Read [references/architecture.md](references/architecture.md) for the full pipeline:

1. **Pools**: `mgr.pools.${dex}.js` fetches rawPools; `quote_${dex}_lib.js` builds config entries. ETH-like pools -> `pools.json`; others -> `pools_bridge.json`. Multi-pool contracts (curveV2) generate multiple entries with `_u0_N` poolId suffixes.

2. **Routes**: each Pool generates two Routes (forward + reverse) with swapped From/To. RouteId is a global uint32 index, unstable across config versions. `route.Rev` points to the opposite direction route.

3. **Cycles (Phase A)**: DFS enumerates closed route loops. Two phases: Phase 1 (WETHWETH, ETH-like anchored) and Phase 2 (StableCash, stable-anchored with ETH cash pool). Max 12 routes per cycle. `MinUsdScore` = minimum usdTotal across all pools in the cycle. cycleId is arrival-order based, not stable across runs.

4. **Refer (Phase B)**: per route, select topK=20000 cycles via dual hop-bucket (2/3-hop quota=10000, 4+hop quota=10000). Within bucket: `PackedScore DESC, cycle_id ASC`. PackedScore bit 63 = hop group (1=2/3-hop, 0=4+hop). Stable-cycle candidates filtered out for non-cash-like routes. Gap fill between buckets.

5. **Builder**: reads `store.CyclesByRoute(targetRouteId)` to get refer cycles, constructs DuralPaths. If target cycle not in refer topK, builder never considers it.

6. **Block vs Pool path**: same pool, opposite route direction. Independent refer lists. A cycle may be in one direction's refer but not the other's.

## Critical Rules

- **Never use cycleId from production logs to look up cycles in a different config version's cycleStore.** cycleId is not stable across precompute runs. Always match by poolAddress + token direction to find routeIds, then search cycleStore by routeId sets.
- **Fix precomputed_meta.json timestamp mismatch** before loading cycleStore: set `tokenlistTimeStamp` to match `tokenlist_1.json`'s `timeStamp`.
- **Routes are bidirectional**: each pool generates two routes (forward + reverse). The same 4 pools traversed in opposite directions are two independent cycles with different routeIds.
- **Block path vs pool path**: same pool, opposite route direction. Block path uses `targetRouteId` for USDT->WETH; pool path uses the reverse routeId for WETH->USDT. A cycle may appear in one's refer but not the other's.

## Reference: Cycle Precompute Architecture

- Phase A: DFS enumerates all合法 cycles, writes to DuckDB `cycle_summary`.
- Phase B: per route, select topK (20000) cycles as `route_winners` (refer). Uses dual hop-bucket (2/3-hop + 4+hop) with base quota + gap fill.
- Phase C: export survivors to 7 split-bin files (cycleOffsets, cycleRoutes, cycleMeta, routeOffsets, routeCycleIDs, execMeta, execOrder).
- Phase D: quote pre-encode + meta finalize.

Detailed design: `go-service/docs/design-cycles-index.md` and `go-service/docs/design-cycle-precompute-duckdb.md`.
