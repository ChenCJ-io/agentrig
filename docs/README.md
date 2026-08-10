# AgentRig 文档中心

这里维护 AgentRig 当前实现的权威边界、运行手册、架构决策与 GOAI 2026 参赛证据。早期讨论稿
统一归档在 `design-history/`，不会与当前实现混用。

## 按目标开始

| 你的目标 | 推荐入口 |
|---|---|
| 五分钟运行一个无模型、可重复的完整场景 | [快速开始与安全部署](./08-快速开始与安全部署.md) |
| Read the setup and security guide in English | [English quick start](./quickstart.en.md) |
| 理解 AgentRig 解决的问题与总体边界 | [总体架构](./00-总体架构.md) |
| 接入新的被测 Agent、Driver 或 Provider | [V1 实现与接入](./01-核心Agent价值复核与讨论交接.md) |
| 验证 V1 Core、数据库、wheel 和真实协议 | [V1 验收](./02-V1验收.md) |
| 部署 Manager、Curator、Judge 三角色 | [AgentTeams 开发设计](./03-V2-智能评测助手与AgentTeams-开发设计.md) |
| 复现真实 Matrix/AgentTeams 本机链路 | [本机演示与验收](./04-本机演示与验收.md) |
| 了解产品界面和交互设计 | [完整产品与界面开发设计](./05-V2-完整产品与界面开发设计.md) |
| 理解证据化决策、委派和恢复策略 | [自适应评测闭环](./06-V2.1-基于证据的自适应评测闭环-开发设计.md) |
| 查看下一阶段可复现交付方案 | [V2.2 质量门禁 RFC](./07-V2.2-可复现交付与质量门禁-RFC.md) |
| 核对比赛材料、评分映射和真实证据 | [GOAI 2026 交付中心](./competition/README.md) |

## 权威文档

| 文档 | 状态 | 负责回答 |
|---|---|---|
| [00-总体架构](./00-总体架构.md) | Implemented | 产品边界、控制方式、核心领域和安全不变量 |
| [01-V1 实现与接入](./01-核心Agent价值复核与讨论交接.md) | Implemented | 模块、配置、Driver、Provider、HTTP/MCP 接口和部署 |
| [02-V1 验收](./02-V1验收.md) | Verified | 自动化、数据库、wheel、Demo 与协议验收记录 |
| [03-V2 AgentTeams 开发设计](./03-V2-智能评测助手与AgentTeams-开发设计.md) | Implemented | 三角色身份、Matrix、会话、计划、权限和部署 |
| [04-本机演示与验收](./04-本机演示与验收.md) | Verified | 真实 lassist + AgentTeams + Matrix 操作与证据 |
| [05-产品与界面设计](./05-V2-完整产品与界面开发设计.md) | Implemented | 信息架构、页面、交互、视觉与验收基线 |
| [06-V2.1 自适应评测闭环](./06-V2.1-基于证据的自适应评测闭环-开发设计.md) | Implemented | 结构化决策、动态委派、故障恢复和质量指标 |
| [07-V2.2 质量门禁 RFC](./07-V2.2-可复现交付与质量门禁-RFC.md) | Proposed | 公开复现、Release Evidence、可观测性和后续路线 |
| [08-快速开始与安全部署](./08-快速开始与安全部署.md) | Current | 最短运行路径、鉴权、网络和部署安全 |

状态含义：

- **Implemented**：对应功能已经进入当前代码；
- **Verified**：除实现外还包含可重复的本机或 CI 验收记录；
- **Current**：当前推荐操作入口；
- **Proposed**：待评审方案，不改变现有实现承诺。

## 其他入口

| 资源 | 内容 |
|---|---|
| [Public Reference Target](../examples/reference_target/README.md) | 无模型、无私有依赖的成功/回归/恢复场景 |
| [AgentTeams 部署包](../deploy/agentteams/README.md) | 三角色资源、配置模板、构建与权限隔离 |
| [Skill 目录](../skills/README.md) | Core、Manager、Curator、Judge 的 11 项工作流合同 |
| [API/模块贡献指南](../CONTRIBUTING.md) | 开发环境、架构约束、验证矩阵和 PR 要求 |
| [安全策略](../SECURITY.md) | 支持版本、漏洞范围和私密报告渠道 |

## 文档治理

当前实现事实以 00—06 和 08 为准。07 在状态转为 Accepted 前只是后续 RFC；04 和比赛证据报告
记录特定参考环境的验收事实，不代表所有部署自动具备相同外部依赖。

形成 V1/V2 时的讨论记录和早期设计稿保存在
[`design-history/`](./design-history/README.md)，仅用于追溯决策，不作为当前 API、代码结构或
验收口径。若文档与测试、migration 或公开 Schema 冲突，以可执行契约为准，并应在同一改动中
修正文档。
