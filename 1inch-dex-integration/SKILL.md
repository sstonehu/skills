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
- 当前 quote 主线不是 Go 侧 `BuildExactInQueryCall`。即使某个 `QuoteModule` 需要注册，也不能假设要实现未被 pipeline 调用的 Go 侧 eth_call 构建；应先确认 `seed / mid25` 实际是否通过 `QuoterV8 + buildPathForTestRoute + buildTxnForTestRoute`。
- Go 侧 `model/dex/quote_${dex}_lib.go` 的首要职责是注册 `DexInfo`、ABI 和 module，让 `MustGetDexInfo(dex)` 能返回非空 `DexInfo`；不要把“已在 `dex_config.go` 配置”误认为 Go 侧注册完成。

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
- pool 配置只表达 canonical pool，不要为了支持双向交易复制成两条 pool。双向能力应由 route 层根据 `singleDirection` / `SingleDirection` 生成正反 route；只有合约或协议真实单向时才标单向。
- `fromToken/toToken`、`zeroForOne`、`token0In`、direct packed flag 等字段语义必须分层记录：pool/listener 的方向语义不能直接复用成 direct handler 的协议私有标志位，除非明确只在 direct step 构建阶段做局部转义。
- Solidity 接入前先判断是否允许进入主合约：如果新 dex 不能与既有逻辑高度复用，或者继续增加 `RouterProxyV8Simulate.sol` 体积风险过高，就必须改走 `RouterProxyExtend.sol`
- 走 `RouterProxyExtend.sol` 的 dex，编码必须放在 `0x50+` 区间，不能继续占用主合约家族编码
- `exactOutInternal` 只能做路由分发；协议具体 quote / swap / direct 实现必须放在对应家族 lib 中。不要把实现逻辑直接塞进顶层路由方法。
- Quote、simulate/dynamic、direct 是三套合约面：`QuoterV8`、`RouterProxyV8Simulate` / `RouterProxyExtend`、`RouterProxyV8Direct`。不能假设一个合约或一个入口改完会自动覆盖三阶段；详设必须逐阶段列出 dispatch 与实现 lib。
- 选择 `dexHeader / dexType` 时，先比对 path 字节格式，再比对执行语义。协议名或代码文件归属不能决定编码归属；如果 path 格式复用某家族但 quote/swap 是协议专属，应使用该 path bucket 的独立 `dexType` 并在 dispatch 中专门分流。
- 同一个 `dexType` 不能承载不同 path 格式。若复用同一个 `dexHeader` 下的新 subtype，必须同步确认 Go builder、JS caller/direct builder、Solidity `PathLib.getStepLength`、direct handler 的 step 长度和 flag 偏移完全一致。

## 范式使用规则

- 所有协议范式定义、DEX 到范式的映射总表，统一以 `docs/dex集成范式.md` 为准。
- Skill 不再重复维护整套范式正文；执行时只负责：
  - 先把目标 DEX 映射到范式文档中的某个范式
  - 再按方法论文档推进 `Pools / Events -> Quote / Swap -> Replay -> 经验沉淀`
  - 最后把本次结论回填到范式文档、方法论文档或详设文档
- 判断范式时，优先看执行模型，再看协议名称。
- 如果 path 看起来能复用，但 quote / swap 明显不能复用，应输出成“复用某范式的 path / 执行模型 + 协议专属 quote/swap”。
- 如果目标协议体现出新的稳定执行模型，应先更新 `docs/dex集成范式.md`，再继续实现。

## Curve01 复盘后新增硬性门禁

Curve01 的经验不作为协议特例处理，而作为所有新 DEX 的前置门禁：

- **path bucket 与执行家族分离**：先证明新 DEX 的普通 path、direct packed step、extra orderData、salt/config、delegate address 等字节布局和目标 bucket 一致，再决定 `dexHeader / dexType`。不能因为实现函数临时放进某个 lib，就把 dexIdx 放进该家族编码。
- **子类型必须独立分流**：复用 Fluid legacy / Bancor / Curve 等 bucket 时，如果 1B flag 或尾部字段语义不同，必须使用独立 `dexType`。dispatch 走错 handler 时，flag 会被误读，例如 `isBuy` 被当成 `isETHIn`，revert 会表现成不相关的 WETH withdraw 或其它旧 handler 行为。
- **pool 单条、route 双向**：手写 pool 只保存一个 canonical 方向。若合约支持 buy/sell 或 exact-in 双向兑换，不要复制 pool；确认 Go route 层会因 `SingleDirection=false` 生成反向 route，并在详设写清 canonical pool 与 route 方向的关系。
- **quote module 注册不可省**：即使 quote 阶段不调用 Go 侧 `BuildExactInQueryCall`，也必须有 `quote_${dex}_lib.go` 注册 module。否则 `MustGetDexInfo(dex)` 会返回空 `DexInfo{}`，path 打印会出现 `-(pool)->`，并可能让旧 preencode path 带着 DexIdx=0 进入 pricer。
- **quote preencode 是运行输入**：改 `DexIndexes`、新增 module、改 path 格式后，必须重新生成 `quote_preencode.bin`，或在 replay 工具中明确清空 `QuotePreEncodeData` 让 runtime 重算。只改源码不处理 precompute 缓存，会导致 seed 阶段仍使用旧 DexIdx。
- **direct approve 不在 handler 内做**：direct handler 不查询 allowance、不 approve、不做“兜底”。是否插入 approve step 由链下模拟结果 `approveArr` 决定，链上 handler 只消费已经准备好的 token/allowance 状态并执行 swap。
- **三阶段合约分开验收**：quote 阶段、mid1/dynamic 阶段、direct 阶段的 handler 可能在不同合约或不同 lib 中。每阶段都要分别说明入口、dispatch、path 解码、部署地址与 trace 验证。
- **部署状态是验证对象**：Solidity dispatch 改完并编译通过不等于 replay 会走新代码。`mev_debug_traceCall` 模拟链上已部署合约，必须用 calls trace 证明新 dex 走到了新 handler。
- **特殊 policy 要显式文档化**：如果 sender / profit share / outer profit check / direct bound 对某个 pool 有协议特化规则，必须在详设和实现清单中写明触发条件（如 poolId 命中），不要让 sender 后处理成为隐含知识。

## `multiV4` 的执行提醒

- `multiV4` 的完整适用条件与集成方式见 `docs/dex集成范式.md`。
- 执行时只保留几个必须检查的点：
  - 它是不是执行范式问题，而不只是 path 编码问题
  - quote path 与非 direct swap path 是否共用主线路径语义
  - `testRouteOnce` 是否只做单档输入
  - `testRoute` 是否通过多次调用 `testRouteOnce` 收集多档结果
  - 若使用 `unlock + callback + revert/catch`，自定义 revert 是否能稳定传播并被外层 decode

## FluidDexLite / Curve01 复盘后新增的强制检查

每个新 DEX 在进入实现前，都要先回答下面 22 个问题：

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
   - 对应的 `QuoterV8` / `RouterProxyV8Simulate` 或 `RouterProxyExtend` / `RouterProxyV8Direct` 入口分别是什么？
14. 它是否错误绕开了：
   - `buildPathForTestRoute`
   - `buildPathAndBaseAmount`
   - `updateFlagsForChain`
   - `getPathAndTypes`
15. pool 配置是 canonical 单条，还是确实需要多条 pool？如果需要双向交易，是由 route 层生成反向，还是协议本身必须两条 pool？
16. `singleDirection` / `SingleDirection` 应该是什么？这个决定是否已经和合约真实 buy/sell 能力一致？
17. 选用的 `dexHeader / dexType` 是因为 path 字节布局一致，还是只是因为协议名或代码文件看起来相似？
18. 如果复用现有 path bucket，普通 path、direct packed step、flag 位置、extra orderData、salt/config、delegate address 是否逐字节一致？
19. Go builder、JS caller/direct builder、Solidity `PathLib.getStepLength` 是否都按同一 subtype 计算长度？
20. `DexTags` 是否真实反映 `supportExactOut` / recipient / borrow / selfRedeem？是否存在不可能进入的 `isExactOut` 分支？
21. direct handler 是否完全不做 allowance 查询和 approve？approve 是否只由链下 `approveArr` 生成独立 step？
22. 改完 dexIdx、module 或 path 后，`quote_preencode.bin` / 部署合约 / replay dump 是否有刷新或验证计划？

如果上面任何一项没有明确答案，不要直接开始写合约。

## 注册矩阵

评估和落地一个新 DEX 时，至少检查这三类注册点：

- JS 侧：
  - `scripts/lib/quote_${dex}_lib.js`
  - `scripts/lib/DexConfig.js`
  - `scripts/lib/common_lib.js`
  - `scripts/lib/callerMethodLib.js`（direct packed step / step length）
  - `config/topics.json`
  - `config/topics.listener.swap.json`
  - `config/newPoolTopics.json`
  - `config/newTokenPoolEvents.json`
- Go 侧：
  - `go_service/model/base/dex_config.go`（`DexIndexes` + `DexTags`）
  - `go_service/model/dex/quote_${dex}_lib.go`（必须创建，`init()` 注册 module，否则 `MustGetDexInfo` 返回空）
  - `go_service/conf/abi/*.json`
  - `go_service/core/simulator/build_path_lib.go` / `build_path.go`
  - `go_service/core/simulator/direct_orders.go`
  - `go_service/core/simulator/direct_calldata.go`
  - precompute 输出：`quote_preencode.bin` / route bundle
- Solidity 侧：
  - `contracts/lib/PathLib.sol`
  - 对应家族 quoter / router
  - 对应 direct router lib
  - 只有在必要时才修改顶层入口，如 `QuoterV8.sol`、`RouterProxyExtend.sol`

## 开工前 30 秒 Checklist

开始实现前，先快速确认下面 22 项：

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
- [ ] 已确认 canonical pool 与 route 双向生成边界，不会复制 pool 来表达双向 route
- [ ] 已确认 `singleDirection` / `SingleDirection` 的值与协议真实能力一致
- [ ] 已确认 `dexHeader / dexType` 是按 path 字节格式选择，不是按协议名称或临时代码位置选择
- [ ] 已确认复用 path bucket 时不会和旧 subtype 共用不同格式
- [ ] 已确认 Go / JS / Solidity 三侧 step length、flag offset、extra data 规则一致
- [ ] 已确认 `DexTags.supportExactOut` 与 quote/swap 实际能力一致，不会写不可达分支
- [ ] 已确认 direct handler 不做 allowance / approve，approve 只由 `approveArr` 编排
- [ ] 已确认 precompute 缓存和链上部署状态如何刷新或验证

如果这 22 项里有任何一项答不上来，先停下来补文档。

## 实现阶段 Checklist

进入编码后，建议按这个顺序推进：

- [ ] 先补 `mgr.pools.${dex}.js`
- [ ] 再补 `quote_${dex}_lib.js`
- [ ] 再补 Go 侧 `quote_${dex}_lib.go`
- [ ] 为 Go quote module 补最小测试：`MustGetDexInfo(dex)` 非空、DexIdx 正确、ABI 能加载关键方法
- [ ] 同步补齐 JS / Go 两侧 ABI
- [ ] 确认 `parseLog` 能稳定产出 `poolId`
- [ ] 明确 pool 是 canonical 单条还是确实多条；不要为了双向 route 复制 pool
- [ ] 检查 raw pool 是否有嵌套字段需要映射到 `Pool.go`
- [ ] 把特殊字段映射收口到对应 `dex` 的 cache loader 分支
- [ ] 再补 `topics.json` 与 listener 逻辑
- [ ] 先改 path 编码
- [ ] 先确认 path 是否进入 `testRoute / simulate` 共享主线
- [ ] 如果复用已有 `dexHeader`，先写清新 `dexType` 与旧 subtype 的 path 差异
- [ ] 同步更新 Go / JS / Solidity 三侧 step length 与 flag offset
- [ ] 再改 `PathLib.sol` 解码
- [ ] 再接 quoter
- [ ] 最后接 router / swap 主线
- [ ] direct 阶段只接 packed step 与 handler dispatch；不要在 handler 中加 allowance / approve 兜底
- [ ] 如果 sender / share / profit policy 有 poolId 特化，单独列为 sender 阶段改动并写进详设

## 收尾验证 Checklist

在宣布“已接入”前，至少确认：

- [ ] quote path 打包测试已补
- [ ] simulate / swap 主线路径测试已补
- [ ] direct packed step 测试已补，至少断言 dexIdx、step 长度、pool、recipient、协议私有 flag、bound
- [ ] `buildPathForTestRoute` 与 `buildPathAndBaseAmount` 已验证共用路径语义
- [ ] Go ABI loader 能从 `go_service/conf/abi/` 读到新 ABI
- [ ] quote / swap / replay 状态已回填到文档
- [ ] “有意如此”的设计已写入详设，不留隐含知识
- [ ] 已明确当前未做项，例如 `direct` / 多跳 / `exactOut`
- [ ] Go 侧 `quote_${dex}_lib.go` 已创建且 `init()` 已注册 module（不只是改了 `dex_config.go`）
- [ ] `quote_preencode.bin` 已重新生成，或已确认 `QuotePreEncodeData` 不含过期 DexIdx
- [ ] direct handler 内部不做 allowance 查询 / approve，approve 完全由 `approveArr` 驱动
- [ ] 链上合约已重新部署，新 dispatch 分支已生效（`mev_debug_traceCall` 能走到新 handler）
- [ ] `replay_simulator` 打印的 path 中 dex 名称不为空
- [ ] `pricer.responses.*.json` 中新 dex 的询价不 revert
- [ ] `direct_resp.json` 的 calls trace 中新 dex 走的是正确 handler
- [ ] `seedout.json` 中新 dex 对应 leg 的 `amountOut` 非零且方向正确
- [ ] `mid1_revenue.json` 中若 `GasUsedDirect = 0`，已查看 `direct_reqs.json` / `direct_resp.json` 并解释 direct 失败原因
- [ ] 已用最新部署合约地址或 trace 证明 Quoter / Simulate / Direct 三个阶段不是混用旧合约
- [ ] 已检查 `grep` 中不存在旧 dexIdx、旧 subtype、旧 step length、旧不可达分支

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
6. path bucket / dexType / direct packed step 的选择理由
7. canonical pool、route 方向、`singleDirection` 决策
8. 风险点与验证顺序
9. 是否需要 listener 特判，以及不需要时的理由
10. precompute 缓存刷新与链上部署验证计划

## 范式映射要求

- 先在 `docs/dex集成范式.md` 中定位目标 DEX 对应的范式。
- 输出时必须明确写出：
  - 当前复用的是哪一个范式
  - 复用的是整个范式，还是只复用 path / 执行模型
  - quote 与 swap 是否都落在同一范式下
  - 是否需要写成“执行范式 + 协议专属 quote/swap”
- 如果当前仓库已有相同范式实现，再回到代码里列出应优先检查的 quoter / router / path 文件。
- 如果范式文档里没有合适归类，就先提出“需要新增范式”，而不是直接把实现硬塞进最像的旧家族。
- 如果只复用 path bucket，而不复用 quote/swap 执行语义，必须选择独立 `dexType` 并写清普通 path 与 direct packed step 是否完全同构。

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
- path bucket / dexType 为什么这样选
- canonical pool 是否需要 route 层生成反向
- outer profit check 是否承担最终风控
- direct approve 是否完全依赖 `approveArr`
- `direct` 是否本阶段明确不做
- precompute 文件和链上合约是否需要刷新 / 重新部署

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
- 可复用的 path bucket / dexType：
- 普通 path 格式：
- direct packed step 格式：
- 需要修改的配置：
- 需要新增 ABI：
- Go 侧需要新增的注册：
- precompute / runtime 缓存处理：
- 链上部署与 trace 验证：
- 需要补充的 topics：
- `parseLog` 方案：
- listener 特判方案：
- path 唯一键扩展：
- canonical pool 与 route 方向：

### 结论

- 分类：可直接集成 / 可半直接集成 / 需要新增范式
- 原因：
- 最小实现路径：
- 风险点：
- 必跑验证：

## 执行时的注意事项

- 不要只看 DEX 名称，要看协议家族
- 不要默认 ParaSwap 已支持，就一定能在 1inch 直接接
- 不要默认事件名只有 `Swap/AddLiquidity/Withdraw`
- 必须确认 quote 是链上方法还是本地数学
- 必须确认 swap 是 router 调用还是 pool/vault 调用
- 必须确认 Go 侧 ABI 和注册是否同步补齐
- 不要因为 Go 侧有 `QuoteModule` 接口就默认要实现未被主线调用的 `BuildExactInQueryCall`；先追真实 quote pipeline
- 必须确认 1inch 现有 PathLib 是否能表达该路径结构
- 对单合约多池协议，必须先确认 path 是否要携带 `salt` / `config` / 其它唯一键
- 如果现有顶层 dexHeader 已能覆盖该协议家族，优先在家族库内部做子类型分支
- 如果新 DEX 的 path 格式与某家族不同，不能把它放进同一个 `dexType`；如需复用同一 `dexHeader`，必须使用新 subtype 并处理 subtype-specific step length
- 顶层 `exactOutInternal` 只做 dispatch；具体实现写入对应 lib，避免路由方法膨胀成协议实现
- 不要把 `poolId` 识别写进 `parseLogsToMeaningfulLogs`
- 不要为普通 `Transfer` 或常见 topic 事件增加地址特判
- 如果某个参数值是架构上有意固定的，例如由外层利润检查兜底，必须写进文档，不要留成隐含知识
- 如果 `DexTags.supportExactOut=false`，不要在实现里保留依赖 `isExactOut` 的可达路径；这类分支应明确为不可能分支或直接移除
- 改了 `DexIndexes` 后，grep 所有测试里硬编码的旧值，避免 stale 断言挡住包级测试
- 复用 Fluid legacy packed step 时，1B flag 语义可能不同（`isETHIn` vs `isBuy`），dispatch 必须按 `dexType` 正确分流
- direct handler 只做 swap，不做 allowance 判断；approve 由 `approveArr` 编码成独立 step
- `quote_preencode.bin` 在 dex 配置变更后必须重新生成，否则缓存的 path 会使用旧 DexIdx
- 链上合约修改 dispatch 后必须重新部署，`mev_debug_traceCall` 只模拟链上已部署的代码

## 集成后联调排查指南

新 DEX 代码写完、编译通过后，pipeline 仍可能在 `seed` / `mid1` / `direct` 阶段失败。以下是从 Curve01 集成中总结的排查流程和常见坑，按 pipeline 阶段排列。

### 排查流程（按阶段）

#### 1. path 打印阶段（`replay_simulator`）

用 `go run ./cmd/replay_simulator/` 打印 cycle path。如果 dex 名称缺失（如 `USDS-(-0x6C1A...)->01`），说明 `route.DexInfo.Dex` 为空。

- 根因：Go 侧 `model/dex/quote_${dex}_lib.go` 未创建，`MustGetDexInfo(dex)` 在 registry 中查不到 module，返回空 `DexInfo{}`
- 修复：创建 `quote_${dex}_lib.go`，在 `init()` 中 `RegisterQuoteModule(dex, ...)`，`GetDexIdxAndTag` 返回 `base.NewDexInfo(dex, dex)`
- 验证：`go test ./model/dex -run ${Dex} -v`

#### 2. seed / 询价阶段（pricer revert）

查看 `test_output/pricer.responses.*.json`。如果对应请求返回 `execution reverted`，先检查 `pricer.requestBodies.*.json` 里 path 的 dexIdx。

- 症状 A：dexIdx 只有 flag bits，base 为 0（如 `0x000020` 而非 `0x650220`）
  - 根因：`quote_preencode.bin` 是在 dex module 注册前生成的，缓存了 DexIdx=0 的 path
  - runtime 加载时 `attachQuotePreEncodeToRoutes` 无条件挂载旧缓存，`build_path.go` 发现 `QuotePreEncodeData != ""` 就跳过重算
  - 临时修复：在 `replay_simulator/main.go` 的 patch 函数中清掉所有 `QuotePreEncodeData`，强制重算
  - 根本修复：重新生成 precompute 文件（`routes.bin` / `quote_preencode.bin`）
- 症状 B：dexIdx 正确但仍 revert
  - 检查 `QuoterV8.sol` 的 dispatch 是否覆盖了新的 `dexHeader / dexType` 组合
  - 检查 `PathLib.sol` 的 `getStepLength` 是否处理了新 dex 的 step 长度

#### 3. direct 阶段（direct call revert）

查看 `test_output/direct_resp.json` 的 `calls` 数组。按 step 格式拆解 `DirectCallData`（`mid1_Revenue.json`），确认每步的 dexIdx、pool、amount 是否正确。

- 症状 A：direct call revert，calls trace 显示走了旧 handler（如 `fluidSwap` 而非 `curve01Swap`）
  - 根因：链上部署的合约是旧版本，缺少新加的 dispatch 分支
  - 确认方式：calls trace 里是否调用了新 handler 对应的函数。如果没有，说明合约需要重新部署
  - 注意：`mev_debug_traceCall` 是对链上状态模拟，合约没重新部署就不会有新代码
- 症状 B：direct step 编码正确，但 handler 内部 revert
  - 检查 direct handler 是否做了不该做的事（如 handler 内部查 allowance 并 approve）
  - direct 范式：approve 移出 swap，由链下模拟的 `approveArr` 决定是否插入 approve step
  - handler 内部只做 swap，不做 allowance 判断

### 常见坑清单

#### 坑 1：Go 侧 quote module 注册遗漏

`DexIndexes` + `DexTags` 只是静态配置。`MustGetDexInfo(dex)` 实际走 `quoteModules` registry 查 module，没有 `quote_${dex}_lib.go` 的 `init()` 注册就返回空 `DexInfo{}`。

检查方式：`GetQuoteModule(dex)` 返回 false 就是没注册。

#### 坑 2：`quote_preencode.bin` 缓存过期

`QuotePreEncodeData` 有两个来源：precompute 时算好存 bin（主路径），runtime 发现为空时现算（兜底）。一旦 dex 配置变化（新注册 module、改 DexIdx），bin 文件里的缓存就过期了。

症状：route 的 `DexInfo.Dex` 和 `DexIdx` 看起来是对的（因为加载时从 `MustGetDexInfo` 重新派生），但 pricer 发出的 path 里 dexIdx 还是旧值（因为用了缓存的 `QuotePreEncodeData`）。

#### 坑 3：direct handler 内部做 allowance 兜底

direct handler 内部查 `allowance` 并 `approve` 会：
- 掩盖 approve step 缺失
- 让 direct 路径语义和模拟编排不一致
- 增加不必要的链上 gas 消耗

正确做法：approve 由 `BuildDirectCallData` 从 `result.ApproveArr` 编码成独立 step（`0xFF0200`）。

#### 坑 4：链上合约未重新部署

Solidity 代码改了 dispatch 分支，但 `mev_debug_traceCall` 模拟的是链上已部署的合约。如果合约没重新部署，新分支不会生效，dispatch 会走旧 handler。

排查方式：看 calls trace 里是否走到了新 handler。如果走了旧 handler（且旧 handler 的 step 格式与新 handler 相似），`isBuy` / `isETHIn` 等标志位会被互相误读，导致 revert 原因看起来不直观。

#### 坑 5：改 DexIndexes 后旧测试硬编码值

改了 `DexIndexes` 里的值后，grep 所有测试里硬编码的旧值（如 `0x0A0000` → `0x0A0100`），否则无关的 stale 断言会挡住包级测试。

#### 坑 6：path 格式复用但标志位语义不同

复用 Fluid legacy 的 packed step 格式时，1B flag 字段的语义可能不同（Fluid 用 `isETHIn`，curve01 用 `isBuy`）。如果 dispatch 走错了 handler，这个字节会被误读，导致不直观的 revert（如 WETH withdraw）。

确保 `exactOutInternal` 的 dispatch 按 `dexType` 正确分流，且部署的合约包含最新代码。
