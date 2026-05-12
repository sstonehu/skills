---
name: "txhash-path-cycle-check"
description: "Given a txHash, run target-path identification and route/cycle/refer validation, then output path lines with routeId+usdTotal, cycle existence (cycleId/routeIds/minUsd), each route's refer position/len/last minUsd, and a phase-aware corrected cycle order."
---

# TxHash Path Cycle Check

给定 `txHash`，自动串联三个步骤：

1. `go-service/cmd/replay/run_identify_target_path.sh` — 从 tx logs 识别 target pool paths
2. `go-service/cmd/replay/find_path_cycle` — RouteId 映射 + CycleStore 查询 + Refer 分析
3. `scripts/correct_cycle_order.py` — Phase-aware 闭环矫正

## 输出

- 终端：三段标准输出（路径 / cycle 存在性 / refer）
- 文件：
  - `<output_dir>/identify/target_path_analysis.json` — identify 步骤原始输出
  - `<output_dir>/path_cycle_report.txt` — find_path_cycle 标准输出
  - `<output_dir>/path_cycle_corrected.json` — 矫正后的 cycle 顺序

## 三段标准输出

1. **路径**：`dex, poolId, fromTokenSymbol -> toTokenSymbol, routeId, usdTotal`
2. **cycle 是否存在**：`exists, routeIds, mismatchKind, legCount`
   - `no_route`：≥1 个 leg 的 routeId=-1（store 缺少该 route）
   - `no_cycle_match`：所有 route 存在但 cycle 在 CycleStore 中找不到
   - `found`：cycle 存在
3. **各 route 的 refer**：`routeId, inRefer, pos, len(refer), lastHop, lastMinUsd`

## Phase-aware 闭环矫正（Step 3）

`find_path_cycle` 中的 `orderLegsAsCycle` 要求**全部** leg 形成闭环，无法处理 cashPool 模式（部分 leg 不参与闭环）。

`correct_cycle_order.py` 扩展了这一逻辑：

### 数据源
| 数据 | 来源 | 权威性 |
|------|------|--------|
| Token 符号/方向 | `target_path_analysis.json`（来自 `_getPathFromLog`，基于 tx logs） | 链上真实数据 |
| RouteId | `find_path_cycle` 输出（route store 查询） | route store 权威 |
| Stable 分类 | `conf/StableTokens.json` | 配置权威 |
| ETH-like 判定 | `modelbase.IsETHLike()`（ETH/WETH/E 地址） | 代码权威 |

### 算法
1. `legStartPriority`: ETH-like=0, stable=1, other=2
2. DFS 找**最大闭环子集**（k ≤ n，不要求全部 leg 参与）
3. 闭环子集旋转到最高 priority 的 leg 起始
4. 剩余 leg（cashPool）追加到末尾
5. 若无法形成任何闭环，返回原始顺序

### 关键注意事项
- Hex regex 必须 `[a-fA-F0-9]` 以支持 EIP-55 checksum 大写地址
- UniswapV3 pool 的 `poolId=None`，pool key 匹配时 fallback 到 `poolAddress`
- route store 的 token symbol 可能与实际链上不同（pool 映射偏差），以 identify 为准
- 输出中不缩写 poolAddress、poolId、txHash

## 用法

```bash
bash skills/txhash-path-cycle-check/scripts/run_txhash_path_cycle_check.sh <txHash>
bash skills/txhash-path-cycle-check/scripts/run_txhash_path_cycle_check.sh <txHash> /custom/output/dir

# 单独运行矫正（已有 identify + report）
python3 skills/txhash-path-cycle-check/scripts/correct_cycle_order.py <output_dir>
python3 skills/txhash-path-cycle-check/scripts/correct_cycle_order.py <output_dir> --csv
```
