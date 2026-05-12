# cycle-fail-analysis

分析 replay 批次中 mid1 失败的根因，按 cycle 可达性逐层分类。

## 输入

- replay 输出目录（含 `replay_result_*.csv`, `per_tx/`, `go_replay_snapshots/`）

## 输出

1. 分类汇总：Cat1/Cat2/Cat3 统计
2. 全量失败明细 CSV：`mid1_fail_detail.csv`
3. Cat1 内部细分：mid25/mid25.after 通过率

## 分类方法

```
对每条 mid1 失败 tx：
  1. run_identify_target_path → 取得路径 routeIds
  2. find_path_cycle → 检查 cycle 在 CycleStore 中是否存在
     - Section 2: exists=true/false
     - Section 3: 各 route inRefer=true/false + pos
  3. 读取 step_c.log → 确定 targetRouteId
  4. 读取 simulatorEvent.json → 用 DuralPathIdx 匹配目标 cycle
  5. 读取 Mid25Revenue.json → CycleId/DuralPathIdx 匹配
  6. 读取 Mid25Revenue.after.json → 同上
  7. 读取 mid1_Revenue.json → len(mid1)

分类：
  Cat1: cycle存在 AND targetRoute在simulateEvent中(pos<15000)
  Cat2: cycle存在 AND targetRoute不在simulateEvent中
  Cat3: cycle不存在
```

## Cat1 内部细分

| 阶段 | 检查方式 | 通过条件 |
|------|---------|---------|
| mid25 (quote) | Mid25Revenue.json 含目标 CycleId/DuralPathIdx | quote 计算通过 |
| mid25.after (截断) | Mid25Revenue.after.json 含目标 | top-N 截断保留 |
| mid1 (替换) | mid1_Revenue.json 非空 | 找到盈利替换 |

## 用法

```bash
# 全量分析
python3 skills/cycle-fail-analysis/scripts/analyze.py <replay_output_dir>

# 或手动步骤
bash skills/txhash-path-cycle-check/... <txHash>
```

## 依赖

- `txhash-path-cycle-check` skill（step 1 + find_path_cycle）
- `go_replay_snapshots/` 中的中间产物（simulatorEvent, Mid25Revenue, mid1_Revenue 等 JSON）
