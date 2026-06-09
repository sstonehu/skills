# cycle-fail-analysis

分析 replay 批次中 mid1 失败的根因，按 cycle 可达性逐层分类。使用 `find_path_cycle_batch` (一次 config 加载处理所有 TX) + `correct_cycle_order.py` (phase-aware 闭环矫正) 产出标准化 v3 格式。

## 输入

- replay 输出目录（含 `replay_result_*.csv`, `per_tx/`, `go_replay_snapshots/`）

## 输出 (3 文件)

执行后在 batch 目录根下产出：

| 文件 | 列/格式 |
|------|---------|
| `mid1_target_cycle.json` | JSON 数组: txHash, blockNumber, idx, logCount, poolPathCount, cycleExists, mismatchKind, cycleId, minUsd, isReordered, paths[] (routeId, dex, poolId, from, to, inCycle, pos, referLen, lastHop, lastMinUsd) |
| `mid1_target_cycle.csv` | 12 列: txHash, blockNumber, idx, logCount, poolPathCount, legs, reordered, cycleExists, mismatchKind, cycleRouteIds, pathDetail, poolIds |
| `mid1_fail_detail_v3_classified.csv` | 17 列: txHash, idx, short, hop, cycleId, targetRoute, dp_evt, mid25, after, mid1, best, minUsd, orig_cls, matchKind, new_cls, cycle_path, routeIds |

### 列说明

- `legs` / `hop`: logicHopCount (cycle 存在时) 否则 legCount
- `idx`: `replay_result_*.csv` 中的数据行号 - 1（去掉表头后的 0-based 批次位置）
- `reordered`: correct_cycle_order.py 是否改变了 route 顺序
- `poolIds` / `poolId`: poolId 为空时 fallback 到 poolAddress (UniswapV3)
- `cycle_path`: pipe-separated `routeId dex poolId from->to pos_referLen_lastHop_lastMinUsd` (corrected order)
- `new_cls` 分类:
  - `X_no_success`: cycle 存在于 CycleStore 但 mid1=0
  - `X_no_cycle`: cycle 不存在于 CycleStore (open_path / not_in_store / no_cycle_match)
  - `X_no_route`: >=1 个 leg 无 routeId
  - `X_no_block`: 无 block 匹配
- `orig_cls`: X1 (正常运行) / ? (无 step_d 日志)

## 分类方法

```
对每条 mid1 失败 tx：
  1. find_path_cycle_batch -dirs=<all per_tx dirs> → matchKind, cycleId, routeRefer
  2. correct_cycle_order.py --rich → corrected leg order + isReordered + inCycle
  3. 读取 step_c.log → targetRoute
  4. 读取 simulatorEvent.json → dp_evt
  5. 读取 Mid25Revenue.json → mid25 count
  6. 读取 Mid25Revenue.after.json → after count
  7. 读取 mid1_Revenue.json → len(mid1)
  8. 读取 step_d_replay.log → best=, 阶段完成情况

matchKind 映射 (find_path_cycle_batch → v3):
  found         → X_no_success
  not_in_store  → X_no_cycle
  open_path(*)  → X_no_cycle
  no_route_leg* → X_no_route
  empty         → X_no_cycle
```

## 用法

```bash
# 单独运行
python3 skills/cycle-fail-analysis/scripts/analyze.py <replay_output_dir>

# 或通过 orchestrator (推荐)
bash skills/analyze_direct_replay/scripts/batch_analyze.sh <replay_output_dir>
```

## 依赖

- `find_path_cycle_batch` Go binary (`go-service/cmd/replay/find_path_cycle_batch`)
- `correct_cycle_order.py` (`txhash-path-cycle-check/scripts/correct_cycle_order.py`)
- `go_replay_snapshots/` 中的中间产物（simulatorEvent, Mid25Revenue, mid1_Revenue 等 JSON）
