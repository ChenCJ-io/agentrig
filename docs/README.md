# AgentRig 文档中心

这里维护 AgentRig 当前实现的权威边界、运行手册与架构决策。早期讨论稿与已裁撤方案不在本仓库，
以免过程文档与当前实现混用。

## 按目标开始

| 你的目标 | 推荐入口 |
|---|---|
| 五分钟运行一个无模型、可重复的完整场景 | [快速开始与安全部署](./08-快速开始与安全部署.md) |
| Read the setup and security guide in English | [English quick start](./quickstart.en.md) |
| 一次性理解系统全貌：入口、模块、执行模型、数据与安全 | [总体架构](./00-总体架构.md) |
| 查包结构、Driver/Profile 字段、MCP 工具面与接口清单 | [实现与接入](./01-核心Agent价值复核与讨论交接.md) |
| 五分钟把线上 LLM 调用接进平台 | [生产 Trace 接入指南](./04-Trace接入指南.md) |
| 不改代码测试现有的 Agno / LangGraph / Python Agent | [Python Agent 接入指南](./05-Python-Agent接入指南.md) |
| 了解 Web 评测助手与计划状态机 | [智能评测助手架构](./03-智能评测助手架构.md) |
| 运行 AgentScope 验证与生产证据闭环 | [V2.3 实施与验收包](./09-V2.3-Agent运行时验证与生产证据闭环/README.md) |
| 一键验收本地或 Live 范围 | [V2.3 验收运行手册](./09-V2.3-Agent运行时验证与生产证据闭环/11-验收运行手册.md) |
| 评审被测 Agent 选择器与页面联动规则 | [被测 Agent 上下文联动 RFC](./10-被测Agent上下文选择与联动-RFC.md) |
| 评审 Trace 接入与生产回归闭环方案 | [一站式 Trace 接入 RFC](./11-一站式Trace接入与生产回归闭环-RFC.md) |
| 评审用例进仓库与 `agentrig test` 方案 | [用例文件与 agentrig test RFC](./12-用例文件与agentrig-test-RFC.md) |

## 权威文档

| 文档 | 状态 | 负责回答 |
|---|---|---|
| [00-总体架构](./00-总体架构.md) | Implemented | 产品边界、对外入口、模块分层、Run/Cell/Attempt 执行模型、数据与安全不变量 |
| [01-实现与接入](./01-核心Agent价值复核与讨论交接.md) | Implemented | 包结构、配置、Driver、Provider、MCP/HTTP 接口、生产接入与耐久执行 |
| [02-V1 验收记录](./02-V1验收.md) | Historical | `0.1.0a1` 时点的自动化、数据库、wheel、Demo 与协议验收记录 |
| [03-智能评测助手架构](./03-智能评测助手架构.md) | Current | 会话、回合、EvaluationPlan 状态机与确认边界 |
| [04-Trace 接入指南](./04-Trace接入指南.md) | Current | 接入源、双车道上报配置、语义方言与隐私三档策略 |
| [05-Python Agent 接入指南](./05-Python-Agent接入指南.md) | Current（Alpha） | 三步接入、一次测试的执行过程、框架层工具接管、用对话生成用例、安全边界与已知限制 |
| [08-快速开始与安全部署](./08-快速开始与安全部署.md) | Current | 最短运行路径、鉴权、网络和部署安全 |
| [09-V2.3 实施与验收包](./09-V2.3-Agent运行时验证与生产证据闭环/README.md) | Implemented / Live Pending | 质量报告、Driver Event v2、Capability、生产证据与耐久执行 |
| [10-被测 Agent 上下文联动 RFC](./10-被测Agent上下文选择与联动-RFC.md) | Accepted / Partially implemented | 被测 Agent 选择、路由上下文、助手会话绑定与历史快照边界 |
| [11-一站式 Trace 接入 RFC](./11-一站式Trace接入与生产回归闭环-RFC.md) | Accepted / Partially implemented（M1—M3 已落地） | 采集车道、接入体验、全文存储策略与 Trace 转用例自动化 |
| [12-用例文件与 agentrig test RFC](./12-用例文件与agentrig-test-RFC.md) | Accepted / Partially implemented（B1 已落地） | 用例写成仓库文件、`agentrig test` 的行为与退出码、CI 中的 Curator 策略 |

状态含义：

- **Implemented**：对应功能已经进入当前代码；
- **Verified**：除实现外还包含可重复的本机或 CI 验收记录；
- **Current**：当前推荐操作入口；
- **Live Pending**：本地实现和确定性验收已完成，但指定外部 Runtime 或数据库的实机证据尚未生成；
- **Accepted / Partially implemented**：方案已接受并部分落地，逐条状态见该文档的实施状态段；
- **Proposed**：待评审方案，不改变现有实现承诺；
- **Historical**：特定版本时点的记录，不代表当前事实。

## 其他入口

| 资源 | 内容 |
|---|---|
| [Public Reference Target](../examples/reference_target/README.md) | 无模型、无私有依赖的成功/回归/恢复场景 |
| [Skill 目录](../skills/README.md) | 面向外部编码 Agent 的 3 项 MCP 工作流 |
| [API/模块贡献指南](../CONTRIBUTING.md) | 开发环境、架构约束、验证矩阵和 PR 要求 |
| [安全策略](../SECURITY.md) | 支持版本、漏洞范围和私密报告渠道 |
| [变更记录](../CHANGELOG.md) | 版本历史与未发布改动 |

## 文档治理

当前实现事实以 00、01、03、04、05、08、09、代码和自动化测试为准。10 与 11 已被接受但只部分落地、12 已接受且 B1 已落地，
读这两份文档时必须先看其实施状态段；02 是历史时点记录。若文档与测试、migration 或公开 Schema
冲突，以可执行契约为准，并应在同一改动中修正文档。

形成 V1/V2 时的讨论记录与已裁撤方案只在维护者本地留存，不随仓库发布：它们记录的是当时的私有
被测环境与内部取舍，既不构成当前 API、代码结构或验收口径，也不应成为公开仓库的一部分。
