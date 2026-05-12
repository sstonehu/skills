---
name: doc-orchestrator
description: Use when generating Chinese architecture or detailed-design documents for an existing project or a new requirement, especially when the document should be outlined first, refined through interaction, and then saved under the target project's docs/ directory.
---

# Doc Orchestrator

用于统一生成中文 `architecture` 与 `detailed-design` 文档。

- 用户显式指定文档类型
- skill 自动判断是“现有项目分析流”还是“需求访谈流”
- 先给提纲，确认后再生成全文
- 全文默认保存到目标项目的 `docs/` 目录

## 何时使用

- 用户要为现有项目补架构文档或详细设计文档
- 用户给出需求、方案或功能目标，希望先访谈再形成正式文档
- 用户要求先出提纲，再确认后生成完整文档
- 用户要求文档默认使用中文

## 不适用场景

- 用户只需要简短解释，不需要正式文档
- 用户只需要单独的 ADR、API 设计或数据模型文档
- 用户没有指定 `architecture` 或 `detailed-design`

## 必需输入

请求中必须显式包含以下其一：

- `architecture`
- `detailed-design`

如果用户没有指定类型，只问这一句：

`请先指定文档类型：architecture 或 detailed-design。`

## 需要读取的资源

根据文档类型按需读取：

### `architecture`

- `templates/architecture-outline.md`
- `templates/architecture-full.md`
- `checklists/architecture-checklist.md`

### `detailed-design`

- `templates/detailed-design-outline.md`
- `templates/detailed-design-full.md`
- `checklists/detailed-design-checklist.md`

## 输出约定

- 文档语言：中文
- 提纲先在会话中展示
- 未获提纲确认前，不生成全文
- 未获用户明确要求前，不保存提纲文件
- 全文默认保存到目标项目的 `docs/` 目录
- 同名文件默认不覆盖，先询问用户

## 执行流程

1. 校验文档类型。
2. 识别目标项目根目录：
   - 优先使用用户在请求里显式给出的项目路径或项目名
   - 否则，如果当前工作目录明显是项目根目录，就直接使用
   - 仍不确定时，只问一个简短问题确认项目目录
3. 识别目标项目中的 `docs/` 命名风格：
   - 若已有明显约定，优先沿用
   - 若没有明显约定，使用默认文件名：
     - `architecture-<topic>.md`
     - `detailed-design-<topic>.md`
4. 自动判断来源模式：
   - 若输入更像“基于现有仓库/代码/文档梳理”，走“现有项目分析流”
   - 若输入更像“基于需求或方案设计”，走“需求访谈流”
   - 若两者混合，优先分析现有项目，再补最少量澄清问题
5. 先生成提纲，不生成全文。
6. 在会话中展示提纲，等待用户确认或修改。
7. 提纲确认后，基于对应全文模板生成完整文档。
8. 用对应 checklist 自检。
9. 保存全文到目标项目的 `docs/` 下。
10. 汇报保存路径、主要假设与未决项。

## 现有项目分析流

按最小充分原则收集证据：

- `README*`
- 现有 `docs/`
- 主配置文件、构建文件、入口文件
- 核心目录结构
- 与当前主题直接相关的接口、模型、流程代码

规则：

- 先事实，后推断
- 关键结论如果无法从代码或现有文档中支撑，就标为“待确认”
- 只在事实不足以支撑提纲时提问
- `architecture` 文档中的关键模块、边界、数据流结论，尽量附文件路径依据
- `detailed-design` 文档中的关键接口、流程扩展点、依赖点，尽量附代码路径依据

## 需求访谈流

一次只问一个问题，优先顺序固定：

1. 目标
2. 范围
3. 非目标
4. 约束
5. 成功标准
6. 依赖、兼容性、上线限制

规则：

- 信息足够支撑提纲后立即停止追问
- 不把多个不相关问题塞进一条消息
- 对未确认事项使用“待确认项”，不要伪装成已定方案

## 提纲门禁

- 提纲必须先在会话里展示
- 没有提纲确认，不得生成全文
- 默认不把提纲写入 `docs/`

## `architecture` 文档规则

- 重点写清：背景、目标、范围、非目标、系统边界、模块职责、关键流程、关键决策、风险
- 明确区分：
  - 当前现状
  - 目标形态
  - 约束与假设
  - 关键决策与理由
- 不要把架构文档写成逐步实现说明，除非实现细节直接影响架构边界或关键决策

## `detailed-design` 文档规则

- 重点写清：接口、数据结构、主流程、分支流程、异常处理、配置、验证方式、实施注意事项
- 文档必须足够具体，能够支持后续实现或评审
- 避免使用 `适当处理`、`按需支持`、`视情况而定` 这类模糊表述

## 路径与保存规则

- 全文默认保存到目标项目的 `docs/`
- 若目标项目下没有 `docs/`，则创建该目录
- 若目标项目根目录不明确，先询问，不自行猜测
- 若目标文件已存在，先询问用户选择覆盖还是生成带后缀的新文件

## 质量门禁

保存前必须检查：

- 没有 `TODO`、`TBD`
- 没有空章节
- 各章节之间没有明显冲突
- 不确定内容没有被写成确定事实
- `architecture` 文档没有滑向实现细节堆砌
- `detailed-design` 文档足够具体，可直接指导实现
- 分析流下，关键结论有可追溯依据
- 访谈流下，关键设计与已确认范围、约束一致

## 完成时的简短汇报

- 保存路径
- 文档类型
- 实际采用的来源模式
- 主要假设
- 未决项或剩余风险
