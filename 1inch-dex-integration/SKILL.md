---
name: "1inch-dex-integration"
description: "Evaluates a DEX for 1inch_dural_trade integration and maps it to existing router/quoter patterns. Invoke when adding a new DEX or comparing with paraswap-dex-lib."
---

# 1inch DEX Integration

用于在 `1inch_dural_trade` 中评估和固化新 DEX 接入流程，并结合 `paraswap-dex-lib` 判断某个 DEX 是否可以直接复用现有能力集成。

## 何时使用

- 用户希望把 DEX 集成流程标准化
- 用户希望评估某个 DEX 是否能直接接入 `1inch_dural_trade`
- 用户希望把 `paraswap-dex-lib` 中某个 DEX 映射到 1inch 现有实现
- 用户希望生成某个 DEX 的接入 checklist、改造点、风险点

## 必读上下文

优先阅读以下文件：

- `.trae/rules/project_rules.md`
- `docs/dex集成方法论.md`
- `docs/dex集成范式.md`
- `contracts/QuoterV8.sol`
- `contracts/lib/PathLib.sol`
- `contracts/RouterProxyV8Simulate.sol`
- `config/abi/`
- `config/*_pools_*.json`
- `config/topics.json`
- `config/newPoolTopics.json`
- `config/newTokenPoolEvents.json`

同时对照：

- `paraswap-dex-lib/src/dex/<dex>/`
- `paraswap-dex-lib/src/abi/<dex>/`
- `paraswap-dex-lib/dex_onchain_pricing.csv`

## 固定规范

- 文档职责分层固定如下：
  - Skill：执行时的固定规范、检查项、输出模板与调研动作
  - `.trae/rules/project_rules.md`：workspace 级架构约束与跨仓协作边界
  - `docs/dex集成方法论.md`：项目内正式流程规则文档
  - `docs/dex集成范式.md`：协议范式总表与各范式定义，是协议范式的唯一长期维护入口
  - `docs/paraSwap-p0-p1-integration-guide.md`：状态看板与阶段进展
  - `docs/paraSwap-dex-integration-task.md`：ParaSwap 对照研究母清单与候选池资料入口
  - `docs/dex-detail/*.md`：单项详设、边界与实现结论
  - `docs/*handoff*.md`：跨 workspace 交接，不重复维护规则正文
- 建议阅读顺序固定如下：
  1. `.trae/rules/project_rules.md`
  2. `docs/dex集成方法论.md`
  3. `docs/dex集成范式.md`
  4. `docs/paraSwap-p0-p1-integration-guide.md`
  5. `docs/paraSwap-dex-integration-task.md`
  6. `docs/dex-detail/*.md`
  7. `docs/*handoff*.md`

- 当前项目的 `mev` 主链路固定为：
  - `listener -> builder -> simulator -> sender`
- 工程职责固定为：
  - `dural_trade`：`listener`、`sender`
  - `go-service`：`builder`、`simulator`、`pricer`
  - `private_reth`：私有节点
  - `dt_eks_scripts`：部署与节点服务编排
- `simulator` 会调用 `pricer`，并向 `privateReth` 发起请求。
- 部署假设默认是 `dt-go`、`dt-mev-simu`、`reth` 同节点，优先按 IPC 路线理解联调。
- 评估 DEX 集成时，必须先把实现放回这条系统链路中理解，不要把 quote / swap 当成孤立模块。
- `quote` 阶段重点对应：
  - `seed / mid25`
  - `buildPathAndBaseAmountForTestRoute`
  - `buildPathForTestRoute`
  - `buildTxnForTestRoute`
- `swap` 阶段重点对应：
  - `mid1 / tryDirectDynamic`
  - `buildPathAndBaseAmount`
  - `buildBackrunCallDatasForPercents`
- 两个阶段都必须重点检查：
  - `updateFlagsForChain`
  - `getPathAndTypes`
- 如果 `quote` 与 `swap` 依赖同一组路径字段，就必须优先复用 `testRoute / simulate` 共享 path 主线。
- 不要为了单独打通 `quote`，在 Go 侧额外新增一套绕开现有主线的临时 runtime。

- `poolId` 识别优先放在 `quote_${dex}_lib.js` 的 `parseLog`
- 如果原生 `Interface` 无法直接识别 `poolId`，就在 `quote_${dex}_lib.js` 中重载 `parseLog`
- `parseLogsToMeaningfulLogs` 只负责通过 topic 识别可能影响价格的流动性事件
- 只有通过 topic 无法识别的事件，才允许在 `parseLogsToMeaningfulLogs` 中按地址做特判
- 地址特判仅适用于 `topic = 0` 或原生日志结构无法仅靠 topic 区分的协议
- `_getPathFromLog` 只消费已识别的 meaningfulLogs，不承担事件识别职责
- 评估事件接入时，必须先判断：
  1. 是否已经能在 `topics.json` 中唯一登记
  2. 是否能在 `quote_${dex}_lib.js` 的 `parseLog` 中稳定产出 `poolId`
  3. 只有前两者都不满足时，才讨论 listener 地址特判
- 对包装资产、汇率型协议、rebase 型协议，若价格变化更适合通过定时刷新吸收，则应明确标注为“不接入 listener”，而不是补特判
- `pools.json` 中的 pool 可以保留嵌套结构，但 Go 运行时 `Pool.go` 使用的是扁平模型
- 只要 quote / swap / path / replay 会读取某个字段，就必须在 pool 加载阶段把嵌套字段映射到扁平字段
- pool 特殊字段映射必须按 `dex` 定向处理，不要做无边界通用兼容，避免错误适配其它协议
- Solidity 接入前先判断是否允许进入主合约：如果新 dex 不能与既有逻辑高度复用，或者继续增加 `RouterProxyV8Simulate.sol` 体积风险过高，就必须改走 `RouterProxyExtend.sol`
- 走 `RouterProxyExtend.sol` 的 dex，编码必须放在 `0x50+` 区间，不能继续占用主合约家族编码

## 范式使用规则

- 所有协议范式定义、DEX 到范式的映射总表，统一以 `docs/dex集成范式.md` 为准。
- Skill 不再重复维护整套范式正文；执行时只负责：
  - 先把目标 DEX 映射到范式文档中的某个范式
  - 再按方法论文档推进 `Pools / Events -> Quote / Swap -> Replay -> 经验沉淀`
  - 最后把本次结论回填到范式文档、方法论文档或详设文档
- 判断范式时，优先看执行模型，再看协议名称。
- 如果 path 看起来能复用，但 quote / swap 明显不能复用，应输出成“复用某范式的 path / 执行模型 + 协议专属 quote/swap”。
- 如果目标协议体现出新的稳定执行模型，应先更新 `docs/dex集成范式.md`，再继续实现。

## `multiV4` 的执行提醒

- `multiV4` 的完整适用条件与集成方式见 `docs/dex集成范式.md`。
- 执行时只保留几个必须检查的点：
  - 它是不是执行范式问题，而不只是 path 编码问题
  - quote path 与非 direct swap path 是否共用主线路径语义
  - `testRouteOnce` 是否只做单档输入
  - `testRoute` 是否通过多次调用 `testRouteOnce` 收集多档结果
  - 若使用 `unlock + callback + revert/catch`，自定义 revert 是否能稳定传播并被外层 decode

## FluidDexLite 复盘后新增的强制检查

每个新 DEX 在进入实现前，都要先回答下面 14 个问题：

1. 它是“一池一地址”还是“单合约多池”？
2. `poolAddress` 是否足够唯一？如果不够，唯一键到底是 `poolId` / `dexId` / `salt` / `config` / 其它什么？
3. 是否存在官方 resolver / quoter？如果有，第一版是否应优先走官方链上询价，而不是本地数学？
4. quote path 和非 direct 主线 swap path 是否共用同一套结构？
5. 该 DEX 需要改的是顶层入口，还是只需在现有家族分支内做子类型特化？
6. JS / Go / Solidity 三侧是否都完成了注册？
7. Go 侧 ABI 是否放在 `go_service/conf/abi/`，而不是隐式依赖其它服务目录？
8. 原始 pool JSON 是否有嵌套字段，需要在 cache loader 映射到扁平 `Pool.go`？
9. 这些特殊字段映射是否已经明确限定在对应 `dex` 分支内？
10. 哪些设计是“有意如此”而不是“缺口”？
11. 这个 dex 应该进主合约，还是必须走 `RouterProxyExtend.sol`？
12. 如果走 extend，`dexIdx` 是否已经规划到 `0x50+` 区间？
13. 它在当前项目架构里落在哪条主线：
   - `seed / mid25`
   - `mid1`
   - `tryDirectDynamic`
   - `replay`
14. 它是否错误绕开了：
   - `buildPathForTestRoute`
   - `buildPathAndBaseAmount`
   - `updateFlagsForChain`
   - `getPathAndTypes`

如果上面任何一项没有明确答案，不要直接开始写合约。

## 注册矩阵

评估和落地一个新 DEX 时，至少检查这三类注册点：

- JS 侧：
  - `scripts/lib/quote_${dex}_lib.js`
  - `scripts/lib/DexConfig.js`
  - `scripts/lib/common_lib.js`
  - `config/topics.json`
- Go 侧：
  - `go_service/model/base/dex_config.go`
  - `go_service/model/dex/quote_${dex}_lib.go`
  - `go_service/conf/abi/*.json`
- Solidity 侧：
  - `contracts/lib/PathLib.sol`
  - 对应家族 quoter / router
  - 只有在必要时才修改顶层入口，如 `QuoterV8.sol`、`RouterProxyExtend.sol`

## 开工前 30 秒 Checklist

开始实现前，先快速确认下面 14 项：

- [ ] 已确认协议范式，知道应该优先复用哪一类 Quoter / Router
- [ ] 已确认唯一池键，不会误把 `poolAddress` 当唯一标识
- [ ] 已确认 quote 是官方 quoter / resolver、链上 pool 调用，还是本地数学
- [ ] 已确认 swap 是 router / pool / vault 哪一种
- [ ] 已确认 quote path 与非 direct 主线 swap path 是否同构
- [ ] 已确认 `direct` 本阶段做还是不做
- [ ] 已确认 JS / Go / Solidity 三侧需要改哪些注册点
- [ ] 已确认 Go ABI 存放位置是 `go_service/conf/abi/`
- [ ] 已确认 listener 是否真的需要接入，而不是应该用定时刷新吸收
- [ ] 已确认原始 pool JSON 是否存在嵌套字段，需要映射到扁平 `Pool.go`
- [ ] 已确认这些 pool 特殊字段映射会按 `dex` 定向处理，而不是做全局误适配
- [ ] 已确认哪些参数是架构上“有意固定”，后续必须写入文档
- [ ] 已确认该 dex 是否允许进入 `RouterProxyV8Simulate.sol`，还是必须走 `RouterProxyExtend.sol`
- [ ] 如果走 extend，已确认 `dexIdx` 落在 `0x50+` 区间

如果这 14 项里有任何一项答不上来，先停下来补文档。

## 实现阶段 Checklist

进入编码后，建议按这个顺序推进：

- [ ] 先补 `mgr.pools.${dex}.js`
- [ ] 再补 `quote_${dex}_lib.js`
- [ ] 再补 Go 侧 `quote_${dex}_lib.go`
- [ ] 同步补齐 JS / Go 两侧 ABI
- [ ] 确认 `parseLog` 能稳定产出 `poolId`
- [ ] 检查 raw pool 是否有嵌套字段需要映射到 `Pool.go`
- [ ] 把特殊字段映射收口到对应 `dex` 的 cache loader 分支
- [ ] 再补 `topics.json` 与 listener 逻辑
- [ ] 先改 path 编码
- [ ] 先确认 path 是否进入 `testRoute / simulate` 共享主线
- [ ] 再改 `PathLib.sol` 解码
- [ ] 再接 quoter
- [ ] 最后接 router / swap 主线

## 收尾验证 Checklist

在宣布“已接入”前，至少确认：

- [ ] quote path 打包测试已补
- [ ] simulate / swap 主线路径测试已补
- [ ] `buildPathForTestRoute` 与 `buildPathAndBaseAmount` 已验证共用路径语义
- [ ] Go ABI loader 能从 `go_service/conf/abi/` 读到新 ABI
- [ ] quote / swap / replay 状态已回填到文档
- [ ] “有意如此”的设计已写入详设，不留隐含知识
- [ ] 已明确当前未做项，例如 `direct` / 多跳 / `exactOut`

## 标准输出目标

每次执行此 Skill，都应输出以下内容：

1. 该 DEX 在 `paraswap-dex-lib` 中的实现类型
2. 该 DEX 在 `docs/dex集成范式.md` 中对应的协议范式
3. 结论分类：
   - 可直接集成
   - 可半直接集成
   - 需要新增范式
4. 需要修改的文件清单
5. 事件来源、pools 来源、quote 方法、swap 方法
6. 风险点与验证顺序
7. 是否需要 listener 特判，以及不需要时的理由

## 范式映射要求

- 先在 `docs/dex集成范式.md` 中定位目标 DEX 对应的范式。
- 输出时必须明确写出：
  - 当前复用的是哪一个范式
  - 复用的是整个范式，还是只复用 path / 执行模型
  - quote 与 swap 是否都落在同一范式下
  - 是否需要写成“执行范式 + 协议专属 quote/swap”
- 如果当前仓库已有相同范式实现，再回到代码里列出应优先检查的 quoter / router / path 文件。
- 如果范式文档里没有合适归类，就先提出“需要新增范式”，而不是直接把实现硬塞进最像的旧家族。

## 与 paraswap-dex-lib 的映射方法

拿到目标 DEX 后，按下面顺序分析：

### 第一步：定位 ParaSwap 适配器

检查：

- `paraswap-dex-lib/src/dex/<dex>/`
- `paraswap-dex-lib/src/abi/<dex>/`

重点看：

- `initializePricing`
- `getPoolIdentifiers`
- `getPricesVolume`
- `getDexParam`
- `getTopPoolsForToken`
- 事件池类是否继承 `StatefulEventSubscriber`

### 第二步：识别 4 个核心能力

必须提取：

1. pools 来源
   - subgraph
   - factory/vault
   - API
   - 静态配置
2. 价格影响事件
   - swap
   - mint / addLiquidity
   - burn / removeLiquidity
   - fee/update/reprice
   - pool created
3. 链上 quote 方法
   - 例如 `quoteExactInputSingle`
   - `queryBatchSwap`
   - `get_dy`
   - `getAmountOut`
   - 或“无链上 quote，仅本地数学”
4. 链上 swap 方法
   - router 方法
   - pool 方法
   - vault 方法

### 第三步：映射到 1inch 的接入步骤

严格对照 `docs/dex集成方法论.md`：

1. pools 与 ABI
2. 路径与测试
3. topic 与 opportunity

进入代码前，先补一个“实现边界说明”：

- quote 是否走官方 quoter / resolver
- swap 是否走 router / pool / vault
- path 唯一键是否需要扩展字段
- outer profit check 是否承担最终风控
- `direct` 是否本阶段明确不做

并明确落到以下文件类型：

- `mgr.pools.${dex}.js`
- `quote_${dex}_lib.js`
- `quote_${dex}_lib.go`
- `dexConfig.js`
- `dex_config.go`
- `QuoterV8.sol`
- `PathLib.sol`
- `RouterProxyV8Simulate.sol` 或 `RouterProxyExtend.sol`
- `topics.json`
- `parseLogsToMeaningfulLogs`
- `_getPathFromLog`

事件接入时额外要求：

- 先补 `topics.json`
- 再确认 `quote_${dex}_lib.js` 的 `parseLog` 能否产出 `poolId`
- 最后才评估 `parseLogsToMeaningfulLogs` 是否需要地址特判
- 如果事件最终不接入 listener，需要在输出中明确写明原因和替代机制

### 第四步：给出结论分类

#### 可直接集成

满足：

- 1inch 已存在同范式 quoter/router
- 只需补 ABI、配置、topics、pool 源
- 不需要新增核心 Solidity 路由范式
- 不需要明显推高 `RouterProxyV8Simulate.sol` 体积

#### 可半直接集成

满足：

- 主要范式已存在
- 但需要补一层协议特化适配
- 例如不同的 quoter ABI、factory 逻辑、事件字段、path 编码
- 如果协议特化会继续推高主合约体积，优先改走 `RouterProxyExtend.sol`

#### 需要新增范式

满足：

- 现有 QuoterV8 / PathLib / RouterProxyV8Simulate 无法表达
- 需要新增 Solidity router/quoter 或全新路径编码
- 或者虽然逻辑上可表达，但不适合继续塞进主合约，必须改走 `RouterProxyExtend.sol` 与 `0x50+` 扩展编码

## 当前建议的“可直接/半直接”优先级

### 第一优先级：大概率可直接集成

- UniswapV2 类 fork
- UniswapV3 类 fork
- PancakeV2 / PancakeV3
- SushiV2 / SushiV3
- BalancerV2
- BancorV2 / BancorV3
- FluidDex
- WrapToken 类
- 已在 1inch 配置目录出现过的 DEX 家族

### 第二优先级：可半直接集成

- Algebra
- AlgebraIntegral
- Velodrome Slipstream
- SolidlyV3
- RamsesV2
- PharaohV3
- MaverickV2
- BalancerV3
- UniswapV4 各类 hook 变体

### 第三优先级：通常不能直接复用

- RFQ / offchain orderbook 类
- 需要签名撮合的协议
- Aave / Spark / lending 派生资产协议
- PSM / converter / transmuter / migrator
- Starknet / 非 EVM 体系

典型例子：

- Bebop
- Hashflow
- Dexalot
- Cables
- ParaSwapLimitOrders
- AngleTransmuter
- LitePSM
- SkyConverter
- Ekubo

## 输出模板

分析某个 DEX 时，必须按以下模板输出：

### DEX 概览

- 名称：
- ParaSwap 目录：
- 链：
- 协议范式：

### 四项能力

- pools 数据来源：
- 价格影响事件：
- quote 方法：
- swap 方法：

### 1inch 映射

- 可复用的 Quoter：
- 可复用的 Router：
- 可复用的家族总入口：
- 需要修改的配置：
- 需要新增 ABI：
- Go 侧需要新增的注册：
- 需要补充的 topics：
- `parseLog` 方案：
- listener 特判方案：
- path 唯一键扩展：

### 结论

- 分类：可直接集成 / 可半直接集成 / 需要新增范式
- 原因：
- 最小实现路径：
- 风险点：

## 执行时的注意事项

- 不要只看 DEX 名称，要看协议家族
- 不要默认 ParaSwap 已支持，就一定能在 1inch 直接接
- 不要默认事件名只有 `Swap/AddLiquidity/Withdraw`
- 必须确认 quote 是链上方法还是本地数学
- 必须确认 swap 是 router 调用还是 pool/vault 调用
- 必须确认 Go 侧 ABI 和注册是否同步补齐
- 必须确认 1inch 现有 PathLib 是否能表达该路径结构
- 对单合约多池协议，必须先确认 path 是否要携带 `salt` / `config` / 其它唯一键
- 如果现有顶层 dexHeader 已能覆盖该协议家族，优先在家族库内部做子类型分支
- 不要把 `poolId` 识别写进 `parseLogsToMeaningfulLogs`
- 不要为普通 `Transfer` 或常见 topic 事件增加地址特判
- 如果某个参数值是架构上有意固定的，例如由外层利润检查兜底，必须写进文档，不要留成隐含知识
