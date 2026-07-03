---
name: "analyze_direct_replay"
description: "Analyze RouterProxyV8Direct direct replay results end-to-end: decode calldata steps, locate revert root cause from trace, classify custom errors, and generate direct_fail_report.md."
---

# Analyze Direct Replay

用于分析 `RouterProxyV8Direct` 的 `direct` 回放结果，定位“revert 发生在哪个 step / 哪个后置检查”，并输出批次级统计与 `direct_fail_report.md`。

> 本 skill 是 `direct-trace-step-analyzer` 与 `analyze_direct_replay` 的合并版，统一使用本名称。

## 何时使用

- 用户要分析 `go_replay_snapshots/*_direct_resps.json` 的 direct revert 原因。
- 用户要知道 revert 发生在 direct calldata 的哪一步，或是发生在 Router 的 post-check。
- 用户要做批次统计：`txn 条数 / mid1 条数 / mid1 item 数 / direct success 数 / dynamic success 数`。
- 用户要产出可读的 `calldata` 拆解（selector + name + step list）。

## 输入与前提

- 必需输入文件：
  - `go_replay_snapshots/*_direct_resps.json`
- 建议同时读取：
  - replay 批次目录下 `replay_result_*.csv`（批次统计口径）
  - 对应 `*_direct_reqs.json` 与 `*_mid1_Revenue.json`（按 id 对齐）
- 推荐辅助代码（语义校验）：
  - `go-service/core/simulator/direct_calldata.go`
  - `dural_trade/contracts/RouterProxyV8Direct.sol`
  - `dural_trade/contracts/lib/BaseRouterDirect.sol`
  - `dural_trade/contracts/lib/MultiV4RouterDirect.sol`
  - `dural_trade/contracts/lib/UniswapV3RouterDirect.sol`

## 默认脚本入口

- 固定逻辑已脚本化到：
  - `skills/analyze_direct_replay/analyze_direct_replay.js`
- 典型用法：
  - 分析整个批次目录：
    - `node skills/analyze_direct_replay/analyze_direct_replay.js go-service/test_output/<batch>`
  - 从某个 `*_direct_resps.json` 反推所在批次并生成 report：
    - `node skills/analyze_direct_replay/analyze_direct_replay.js go-service/test_output/<batch>/go_replay_snapshots/<file>_direct_resps.json`
  - 只分析单个 snapshot：
    - `node skills/analyze_direct_replay/analyze_direct_replay.js --single go-service/test_output/<batch>/go_replay_snapshots/<file>_direct_resps.json`
  - 只输出到 stdout、不落盘：
    - `node skills/analyze_direct_replay/analyze_direct_replay.js --stdout-only go-service/test_output/<batch>`

## 已脚本固定的逻辑

- 自动发现同批次的：
  - `*_direct_resps.json`
  - `*_direct_reqs.json`
  - `*_mid1_Revenue.json`
  - `replay_result_*.csv`（若存在）
- 自动完成：
  - ABI 外层解析（selector / offset / bytes length）
  - path step 拆解
  - `share + gas` trailer 识别
  - direct 请求 / 响应 / revert 计数
  - `mid1` / `direct` / `dynamic` 批次统计
  - nested trace 最深 error 节点提取
  - root-only custom error 解码
  - `direct_fail_report.md` 生成

## 仍建议人工复核的部分

- 新增 dex header / 新 step 编码后，需同步补脚本长度表。
- 极少数 trace 若 selector 与地址特征都很弱，`step` 定位仍是启发式，不应冒充形式化证明。
- 若脚本出现 `decode_mismatch`，应回到：
  - `go-service/core/simulator/direct_calldata.go`
  - `dural_trade/contracts/RouterProxyV8Direct.sol`
  做编码/分发对照。

## 固定分析方法

0. 默认先运行固定脚本生成初版 `direct_fail_report.md`，再人工复核脚本标出的 mismatch / unknown / heuristic 样本。
1. 仅使用 `direct_resps` 的 `result.input` 作为 calldata 源，不回溯 `mid1_Revenue.DirectCallData`。
2. 先做 ABI 外层解析：
   - selector（前 4B）
   - offset（32B）
   - bytes length（32B）
   - payload/path bytes
3. 按 direct path 协议逐步解码：
   - `ff0200/ff0300/ff0100/ff0600/ff0700/ff0800`
   - `0x03/0x04`（v3 类）
   - `0x05`（curveV2）
   - `0x07/0x08/0x09/0x0A`（multi family）
     - `type==0x02` 是 settle，步长 43
     - swap 步长分别按 `64 + poolLen * perPool + 20`
4. 用 trace 树定位失败层级：
   - 先看 `result.error`
   - 再 DFS `result.calls` 找最深 error 节点
   - 将 error 路径映射到 payload 中最近的 step（通常是该回调后紧邻的 guard/check step）
5. 做 root-only 特判：
   - 若 `trace_error_path = root_only`，优先读取 `result.output` 前 4B selector。
   - 若 selector 可映射到 Router custom error，则归类为 `post_check_<ErrorName>`，不要保留 `root_unknown`。
6. 输出口径：
   - `revert_total`
   - 每个 `step_idx` 次数
   - 每个 `step_tag` 次数
   - custom error / root cause 维度聚合
   - 批次级成功率与计数

## 关键判定规则

- 若 `error` 发生在 `v3/v4 callback` 内，且后续存在 `ff0700/ff0800`，优先判定为对应 guard step 失败。
- 若 trace 仅有 root revert 且无子调用 error：
  - 先按 selector 做 custom error 解码。
  - 仅在 selector 不可解码时，才保留 `root_unknown`。
- 若 payload 解码出现越界，标记为 `decode_mismatch`，并输出偏移位置。

## Custom Error 解码（优先）

- 以 `RouterProxyV8Direct.sol` 为准，至少包含：
  - `NoProfit()` -> `0xe39aafee`
  - `TradeFailed(uint256)` -> `0x7005668f`
  - `InvalidDexType(uint8)` -> `0xdd85b49d`
  - `InvalidExactOutputDex(uint8)` -> `0x0453a8bb`
  - `InvalidFlashLoanSender(address)` -> `0x28393780`

## 输出模板（必须包含）

- 样本范围：
- txn 条数：
- 有 mid1 条数：
- mid1 成功率（txn 维度）：
- mid1 item 数：
- 有 direct success 数（txn 维度）：
- direct success 数（item 维度）：
- dynamic success 数（item 维度）：
- direct 请求总数：
- direct 响应总数：
- direct revert 总数：
- revert step 分布（step_idx）：
- revert step 分布（step_tag + 语义 + 计数）：
- 代表性样本（3 条）：
  - `resp_index`
  - `step_idx`
  - `step_tag`
  - `trace_error_path`

## 自动产出 Report（默认执行）

- 每次使用本 skill 分析 `*_direct_resps.json` 时，默认同时产出 `direct_fail_report.md`。
- 输出位置：当前 replay 批次目录下，例如 `test_output/<batch>/direct_fail_report.md`。
- 文件路径字段必须使用“相对 `test_output` 的地址”，不要写绝对路径。
- report 必须包含两部分：
  - 汇总分布：
    - `revert_total`
    - `revert step 分布（step_tag + 语义 + 计数）`
    - root-only 解码结果（若存在）
  - 逐条明细：
    - `txHash`
    - `revert所在step`（不是 revert 文本）
    - `reqs文件`
    - `resps文件`
    - `id`
    - `mid1文件`
    - `DuralPathIdx`
    - `calldata拆解`
- 如果 `reqs/resps/mid1` 可一一映射，优先按 `id` 对齐，并在明细中保留 `id`。
- 若 `output` 为空，仍需给出 step 定位，不得回退为“仅文本原因”。

## 批次完整输出 (4 文件)

通过 `scripts/batch_analyze.sh <batch_dir>` 一键生成。单独运行：

```bash
# Phase 1: direct replay 分析
node skills/analyze_direct_replay/analyze_direct_replay.js <batch_dir>

# Phase 2: mid1 cycle/fail 分析
python3 skills/cycle-fail-analysis/scripts/analyze.py <batch_dir>
```

| 文件 | 来源 | 说明 |
|------|------|------|
| `direct_fail_report.md` | `analyze_direct_replay.{js,py}` | direct revert 统计 + 逐条 calldata 拆解 |
| `mid1_target_cycle.json` | `cycle-fail-analysis/analyze.py` | JSON 数组: per-TX cycle/path 详情，`idx` 为 replay_result 数据行号 - 1 |
| `mid1_target_cycle.csv` | `cycle-fail-analysis/analyze.py` | 12 列: txHash..poolIds, corrected route order，`idx` 为 replay_result 数据行号 - 1 |
| `mid1_fail_detail_v3_classified.csv` | `cycle-fail-analysis/analyze.py` | 17 列: txHash..routeIds, 逐阶段失败明细 |

### mid1_target_cycle.csv 列说明

```
txHash, blockNumber, idx, logCount, poolPathCount, legs, reordered,
cycleExists, mismatchKind, cycleRouteIds, pathDetail, poolIds
```

- `legs`: logicHopCount (cycle 存在时) 否则 legCount
- `reordered`: correct_cycle_order 是否改变了 route 排序
- `cycleRouteIds`: corrected order 下的逗号分隔 routeId
- `pathDetail`: pipe-separated `dex:from->to`
- `poolIds`: pipe-separated, poolId 为空时 fallback 到 poolAddress (UniswapV3)

### mid1_fail_detail_v3_classified.csv 列说明

```
txHash, idx, short, hop, cycleId, targetRoute, dp_evt, mid25, after,
mid1, best, minUsd, orig_cls, matchKind, new_cls, cycle_path, routeIds
```

- `new_cls`: X_no_success / X_no_cycle / X_no_route / X_no_block
- `cycle_path`: pipe-separated `routeId dex poolId from->to pos_referLen_lastHop_lastMinUsd` (corrected order)
- `orig_cls`: X1 (正常运行) / ? (无 step_d 日志)

## 注意事项

- 不要把“revert 文本为空”误认为“无法定位 step”；优先通过 step 协议解码 + trace error path 定位。
- 统计时区分：
  - `direct 未执行`（无 req/无 resp）
  - `direct 执行成功`
  - `direct 执行并 reverted`
- 输出必须给出绝对数量和占比。
- 若能识别 custom error，就不要输出 `root_unknown`。
