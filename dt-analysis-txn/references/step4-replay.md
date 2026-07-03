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

### 4.2 Generate simulatorEvent.json (go-service side)

1. Open `opportunity_handler.go` simulatorEvent.json dump (uncomment `util.WriteJSONFile` in `publishToSimulatorInternal`).
2. Run replay_builder:

```bash
cd <go_service_worktree>
mkdir -p test_output
go run ./cmd/replay_builder -input opportunity.json -mockBlock true
```

3. Check `test_output/simulatorEvent.json` for target cycleId in `DuralPaths`.

### 4.3 Check if target cycle is in DuralPaths

```python
import json
with open('test_output/simulatorEvent.json') as f:
    data = json.load(f)
dural_paths = data['DuralPaths']
# DuralPaths only contain CycleId + OverlayPatch; need to cross-reference with cycleStore
cycle_ids = set(dp['CycleId'] for dp in dural_paths)
```

### 4.4 Interpret results

- **Target cycleId in DuralPaths**: builder found the path. Proceed to replay_simulator for detailed simulation.
- **Target cycleId NOT in DuralPaths**: builder did not select this cycle. Proceed to Step 5.

### 4.5 (Optional) Replay simulator for target path

If target cycle found in DuralPaths:
1. Note the `duralPathIdx`.
2. Open `simulator_async.go` stage dump files.
3. Run `cmd/replay_simulator` with the target duralPathIdx.
4. Track which simulation stage the replay reaches.

## Key files to modify

| File | Modification |
|---|---|
| `dural_trade/scripts/listener/mev.listener.block.js` | Uncomment `fs.writeFileSync('./opportunity.json', ...)` |
| `go-service/core/builder/opportunity_handler.go` | Uncomment `util.WriteJSONFile("test_output/simulatorEvent.json", ...)` in `publishToSimulatorInternal` |
