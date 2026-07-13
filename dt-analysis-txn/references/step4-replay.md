# Step 4: Replay Builder and Simulator

## Objective

Replay the opportunity through builder and simulator to verify whether the target path is found and whether simulation succeeds.

## Prerequisites

- Worktree with go-service and dural_trade, both with `.env` copied from production.
- `precomputed_meta.json` timestamp fixed to match `tokenlist_1.json`.
- `GO_CONFIG_DIR` env var pointing to valid precomputed binaries (routes.bin, split bins).

## Procedure

### 4.1 Generate opportunity.json (dural_trade side)

1. Open `mev.listener.block.js` opportunity.json dump (uncomment `fs.writeFileSync('./opportunity.json', ...)`).
2. Run `test_mev.simulator_block.js` via hardhat:

```bash
cd <dural_trade_worktree>
TARGET_POOL=<poolAddr> BLOCK_NUMBER=<blockNum> MAX_MATCHES=1 \
  npx hardhat run test/test_mev.simulator_block.js --network mainnet
```

3. Copy `opportunity.json` to go-service worktree.

### 4.2 Enable pipeline stage snapshots (go-service side)

Before running replay_builder, uncomment the dump points in `simulator_async.go`
so every pipeline stage writes its intermediate result to `test_output/`.

**4.2.1 Uncomment the `util` import**

In `go-service/core/simulator/simulator_async.go`, find the commented import and
uncomment it:

```go
// before
	// "go-service/pkg/util"
// after
	"go-service/pkg/util"
```

**4.2.2 Uncomment the six WriteJSONFile dump blocks**

Each block is a 3-line `if / log.Printf / }` group commented with `//`. Search
by the filename string and remove the `// ` prefix from every line in the block.

| Output file | Variable | Stage |
|---|---|---|
| `test_output/SeedOut.json` | `res.Out` | seed — initial quote/pricing for all DuralPaths |
| `test_output/Mid25Revenue.json` | `ctx.Mid25Revenue` | mid25 revenue before topN trimming |
| `test_output/Mid25Revenue.after.json` | `ctx.Mid25Revenue` | mid25 revenue after topN trimming |
| `test_output/priceMapAcc.json` | `ctx.PriceMapAcc` | accumulated step price map |
| `test_output/mid1_Revenue.json` | `ctx.Mid1Revenue` | mid1 result at S4 stage (100 best TryArbiResult) |
| `test_output/mid1_Revenue.json` | `t.Mid1Revenue` | mid1 result at dispatcher stage (overwrites S4) |

Example — each block looks like this before uncommenting:

```go
// if err := util.WriteJSONFile("test_output/SeedOut.json", res.Out); err != nil {
// 	log.Printf("⚠️ dump SeedOut: write failed: %v", err)
// }
```

After uncommenting:

```go
if err := util.WriteJSONFile("test_output/SeedOut.json", res.Out); err != nil {
	log.Printf("⚠️ dump SeedOut: write failed: %v", err)
}
```

A one-liner to uncomment all six blocks at once:

```bash
cd <go_service_worktree>
python3 -c "
import re
p = 'core/simulator/simulator_async.go'
lines = open(p, encoding='utf-8').readlines()
# Uncomment util import
for i, l in enumerate(lines):
    if '\"go-service/pkg/util\"' in l and l.strip().startswith('//'):
        lines[i] = l.replace('// ', '', 1)
# Uncomment WriteJSONFile blocks (3-line if/log/} groups)
for i, l in enumerate(lines):
    if 'util.WriteJSONFile(\"test_output/' in l and l.strip().startswith('//'):
        for j in range(i, min(i+3, len(lines))):
            idx = lines[j].find('// ')
            if idx >= 0:
                lines[j] = lines[j][:idx] + lines[j][idx+3:]
open(p, 'w', encoding='utf-8').writelines(lines)
print('done')
"
```

**4.2.3 (Optional) Enable mid1LogsProfits.json in agg_debug.go**

For the final `BestProfitLog` entries (100 profit logs with CycleId, Revenue,
Profit, poolIds), uncomment the dump in `go-service/core/simulator/agg_debug.go`
inside the `debugDynamic` function, right after `tr.SimulateDynamicEnd`:

```go
if err := util.WriteJSONFile("test_output/mid1LogsProfits.json", mid1LogsProfits); err != nil {
	log.Printf("⚠️ dump mid1LogsProfits: write failed: %v", err)
}
```

**4.2.4 Enable simulatorEvent.json in opportunity_handler.go**

Uncomment `util.WriteJSONFile("test_output/simulatorEvent.json", ...)` in
`publishToSimulatorInternal` inside `go-service/core/builder/opportunity_handler.go`.

### 4.3 Run replay_builder

```bash
cd <go_service_worktree>
mkdir -p test_output
go run ./cmd/replay_builder -input opportunity.json -mockBlock true
```

The replay sleeps 120 s after processing to let the simulator finish. After it
completes, check `test_output/` for the generated snapshot files.

### 4.4 Pipeline stage snapshot files

| File | Stage | Content |
|---|---|---|
| `simulatorEvent.json` | builder | 15000 DuralPaths (CycleId + OverlayPatch) |
| `SeedOut.json` | seed | `res.Out` — initial quote/pricing for all DuralPaths |
| `Mid25Revenue.json` | mid25 (pre-trim) | `ctx.Mid25Revenue` — all mid25 results |
| `Mid25Revenue.after.json` | mid25 (post-trim) | `ctx.Mid25Revenue` — topN survivors |
| `priceMapAcc.json` | mid25 | `ctx.PriceMapAcc` — accumulated step price map |
| `mid1_Revenue.json` | mid1 | `ctx.Mid1Revenue` / `t.Mid1Revenue` — 100 best TryArbiResult |
| `mid1LogsProfits.json` | dynamic | 100 BestProfitLog (CycleId, Revenue, Profit, poolIds) |

Pipeline flow:

```
Builder → simulatorEvent.json (15000 DuralPaths)
  → seed   → SeedOut.json
  → mid25  → Mid25Revenue.json → Mid25Revenue.after.json (topN)
  → mid1   → mid1_Revenue.json (100 best)
  → dynamic → mid1LogsProfits.json (100 BestProfitLog)
```

### 4.5 Check if target cycle is in DuralPaths

```python
import json
with open('test_output/simulatorEvent.json') as f:
    data = json.load(f)
dural_paths = data['DuralPaths']
# DuralPaths only contain CycleId + OverlayPatch; need to cross-reference with cycleStore
cycle_ids = set(dp['CycleId'] for dp in dural_paths)
```

### 4.6 Check mid1 results

```python
import json
with open('test_output/mid1LogsProfits.json') as f:
    logs = json.load(f)
# Each entry has: CycleId, profit, revenue, afterBalance, gasfee, descAndPercent.poolIds
# Sort by profit descending to see the most profitable paths
```

- **Target cycleId in mid1LogsProfits**: production found and simulated the
  target path. Check profit amount and gas cost.
- **Target cycleId NOT in mid1LogsProfits**: production did not select this
  cycle in the top 100. Proceed to Step 5 to check if the cycle exists in
  cycleStore refer at all.

### 4.7 Interpret results

- **Target cycleId in DuralPaths**: builder found the path. Proceed to replay_simulator for detailed simulation.
- **Target cycleId NOT in DuralPaths**: builder did not select this cycle. Proceed to Step 5.

### 4.8 (Optional) Replay simulator for target path

If target cycle found in DuralPaths:
1. Note the `duralPathIdx`.
2. Use the pipeline stage snapshots to trace which stage the path survived.
3. Run `cmd/replay_simulator` with the target duralPathIdx.
4. Track which simulation stage the replay reaches.

## Key files to modify

| File | Modification |
|---|---|
| `dural_trade/scripts/listener/mev.listener.block.js` | Uncomment `fs.writeFileSync('./opportunity.json', ...)` |
| `go-service/core/builder/opportunity_handler.go` | Uncomment `util.WriteJSONFile("test_output/simulatorEvent.json", ...)` in `publishToSimulatorInternal` |
| `go-service/core/simulator/simulator_async.go` | Uncomment `util` import + 6 `WriteJSONFile` dump blocks (SeedOut, Mid25Revenue, Mid25Revenue.after, priceMapAcc, mid1_Revenue ×2) |
| `go-service/core/simulator/agg_debug.go` | (Optional) Uncomment `WriteJSONFile("test_output/mid1LogsProfits.json", ...)` in `debugDynamic` |
