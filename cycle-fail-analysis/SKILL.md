---
name: cycle-fail-analysis
description: Analyze replay batches where mid1 fails and classify root causes by cycle reachability.
---

# cycle-fail-analysis

分析 replay 批次中 mid1 失败的根因，按 cycle 可达性逐层分类。标准输出使用 `idx` 对齐 `replay_result_*.csv` 数据行号 - 1（去掉表头后的 0-based 批次位置）。

## 输入

- replay 输出目录（含 `replay_result_*.csv`, `per_tx/`, `go_replay_snapshots/`）

## 输出

1. `mid1_target_cycle.json`：per-TX cycle/path 详情，包含 `idx`
2. `mid1_target_cycle.csv`：cycle/path CSV，第三列为 `idx`
3. `mid1_fail_detail_v3_classified.csv`：逐阶段失败明细，第二列为 `idx`

## 分类方法

```text
对每条 mid1 失败 tx：
  1. find_path_cycle_batch -> 取得 matchKind/cycleId/routeRefer
  2. correct_cycle_order.py -> phase-aware 闭环矫正
  3. 读取 step_c.log -> 确定 targetRoute
  4. 读取 simulatorEvent.json -> 统计 dp_evt
  5. 读取 Mid25Revenue.json -> mid25 count
  6. 读取 Mid25Revenue.after.json -> after count
  7. 读取 mid1_Revenue.json -> len(mid1)

分类：
  X_no_success: cycle 存在但 mid1=0
  X_no_cycle: cycle 不存在
  X_no_route: routeId 缺失
  X_no_block: 无 block 匹配
```

## 用法

```bash
# 全量分析
python3 skills/cycle-fail-analysis/scripts/analyze.py <replay_output_dir>

# 或通过 orchestrator
bash skills/analyze_direct_replay/scripts/batch_analyze.sh <replay_output_dir>
```

## 依赖

- `find_path_cycle_batch` Go binary
- `txhash-path-cycle-check/scripts/correct_cycle_order.py`
- `go_replay_snapshots/` 中的中间产物（simulatorEvent, Mid25Revenue, mid1_Revenue 等 JSON）
