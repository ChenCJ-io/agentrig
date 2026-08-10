<h1 align="center">AgentRig</h1>

<p align="center"><strong>让每一次 AI Agent 变更都经过可复现、可审计、可回归的验证。</strong></p>

<p align="center">
  MCP 原生的多 Agent 回归评测与受控发布门禁基础设施
</p>

<p align="center">
  <a href="https://github.com/ChenCJ-io/agentrig/actions/workflows/ci.yml"><img alt="CI" src="https://github.com/ChenCJ-io/agentrig/actions/workflows/ci.yml/badge.svg"></a>
  <img alt="Python 3.12+" src="https://img.shields.io/badge/Python-3.12%2B-3776AB?logo=python&logoColor=white">
  <img alt="MCP native" src="https://img.shields.io/badge/MCP-native-5B5BD6">
  <img alt="Status: competition preview" src="https://img.shields.io/badge/status-competition%20preview-2563EB">
  <a href="./LICENSE"><img alt="MIT License" src="https://img.shields.io/badge/license-MIT-16A34A"></a>
</p>

<p align="center">
  <a href="#五分钟复现">五分钟复现</a> ·
  <a href="#工作原理">工作原理</a> ·
  <a href="./docs/README.md">文档中心</a> ·
  <a href="./docs/competition/README.md">GOAI 2026 参赛材料</a> ·
  <a href="./README.en.md">English</a>
</p>

<p align="center">
  <img src="./docs/competition/assets/agentrig-assistant.png" width="100%" alt="AgentRig 智能评测助手展示 Manager、Simulation Curator、Evidence Judge 与可追溯运行证据">
</p>

<p align="center"><sub>真实本机验收界面：Manager 编排评测，Curator 提供受控工具结果，Judge 基于冻结证据裁决。</sub></p>

Agent 上线后的风险通常不来自“接口能否调用”，而来自模型、提示词、工具、上下文和依赖变化后，
行为是否仍然满足业务与安全约束。AgentRig 将自然语言评测目标转换为**可预览、必须确认、幂等
提交**的执行计划，并保存从工具调用到最终裁决的完整证据链。

它刻意分开两件事：**AgentTeams 负责谁与谁协作，AgentRig Core 负责什么事实已经发生。**
任何 Agent 都不能通过一段看似成功的文本改写运行事实，也不能绕过确认、权限或证据门禁。

> AgentRig 是 [GOAI 2026 Agent Infra 新智基座](./docs/competition/README.md)参赛项目。
> 仓库包含三 Agent Identity、11 项 Skill、真实运行证据、演示脚本与可重复构建的方案材料。

## 为什么是 AgentRig

| 常见问题 | AgentRig 的处理方式 |
|---|---|
| 回答看起来正确，但过程无法复核 | 保存不可变运行快照、RunEvent、工具结果、评判记录与引用 |
| 多 Agent 对话很多，却无法证明真正协作 | 保存 Matrix 请求/响应 event ID、角色 invocation、输入输出 Hash 和终态 |
| 工具调用难以稳定复现 | 按 Fixture → Sample → Simulation Curator → Real Tool 的受控 Provider 链执行 |
| “执行完成”被误当成“测试通过” | 分离运行状态、Rule、Evidence Judge 与外部控制方结论；`completed ≠ pass` |
| 模型或协作运行时故障后记录丢失 | 以数据库事实链为准，支持幂等重试、断线恢复和显式失败投影 |
| Agent 获得过多控制权限 | Manager、Curator、Judge 使用职责隔离的 MCP 工具面和独立凭据 |

## 工作原理

```mermaid
flowchart LR
    U[用户目标] --> M[AgentTeams Manager]
    M --> P[EvaluationPlan 预览]
    P -->|用户确认| G{AgentRig Core Gate}
    G --> T[被测 Agent]
    T -->|缺少可靠工具结果| C[Simulation Curator]
    T --> E[(不可变运行证据)]
    C --> E
    E --> R[Deterministic Rules]
    E --> J[Evidence Judge]
    R --> V[可追溯结论]
    J --> V
```

| 角色 | 负责 | 明确不负责 |
|---|---|---|
| **Manager** | 理解目标、查询资产、形成计划、解释结果 | 绕过用户确认、直接写入评判事实 |
| **Simulation Curator** | 在可靠样本缺失时生成并校验受控工具结果 | 调用真实业务工具、决定最终 pass/fail |
| **Evidence Judge** | 依据 rubric 和冻结证据独立裁决并引用事件 | 修改 RunEvent、补造不存在的证据 |
| **AgentRig Core** | 执行、权限、状态机、证据、Rule 与审计事实 | 依赖模型或聊天文本才能保持正确性 |

## 已验证的场景

| 场景 | 预期 | 可核验证据 |
|---|---|---|
| **成功回归** | 受控工具调用完成，Rule 3/3，Judge `pass` | 工具事件、Curator/Judge invocation、Matrix 双向 event ID |
| **策略回归** | Candidate 未先确认即执行，明确判 `fail` | A/B 差异、Rule 2/3、Judge 引用同一违规事件 |
| **显式恢复** | 第一次 503/超时保持失败；新 Run 恢复通过 | 两个不可变 Run、错误分类、未覆盖的历史证据 |

完整结果见[真实 AgentTeams 运行证据](./docs/competition/07-真实运行证据报告.md)；无需模型和私有
依赖的公开复现路径见 [Public Reference Target](./examples/reference_target/README.md)。

## 五分钟复现

### 路径 A：公开确定性 Demo（推荐）

只需 Python 3.12+、[uv](https://docs.astral.sh/uv/) 和 Node.js 20+；场景运行不需要模型 Key、
Docker 或私有项目。

```bash
git clone https://github.com/ChenCJ-io/agentrig.git
cd agentrig
scripts/reference_demo.sh all --profile reference-ci
```

脚本会从干净环境完成依赖安装、Web 构建、数据库迁移、服务启动、三个场景执行、证据导出及
离线完整性校验。完成后访问 `http://127.0.0.1:8020`，产物位于
`.agentrig/reference-demo/evidence/`。

```bash
scripts/reference_demo.sh validate-evidence --require-clean-source
scripts/reference_demo.sh down
```

### 路径 B：最小本地服务

```bash
uv sync --extra dev
cd web && npm ci && npm run build && cd ..
uv run agentrig db upgrade
uv run agentrig serve
```

默认入口：Web `http://127.0.0.1:8000/`、HTTP API `/api/`、Streamable HTTP MCP `/mcp/`。
配置、鉴权和网络边界见[快速开始与安全部署](./docs/08-快速开始与安全部署.md)。

### 路径 C：完整三 Agent 验收

真实 AgentTeams v1.1.2、Matrix、lassist/Pixcake 与模型的本机联调需要 Docker 和部署侧凭据。
按[本机演示与验收](./docs/04-本机演示与验收.md)执行；Secret 只写入被 Git 忽略的本机环境文件。

## 核心能力

| 领域 | 能力 |
|---|---|
| **评测编排** | 单用例、批量、多版本、重复运行、双 Target A/B、计划预览与确认 |
| **Agent 接入** | ACP、HTTP/SSE、Pixcake、OpenAI-compatible、allowlisted Python/JSONL Driver |
| **工具控制** | controlled、CaseRun 级 MCP proxy、observe-only；Fixture/Sample/Curator/Real Tool 链 |
| **评判体系** | Deterministic Rule、Evidence Judge、External Controller 分层存档 |
| **多 Agent 协作** | Manager/Curator/Judge 三角色、Matrix Bridge、隔离 MCP 权限面、11 项 Skill |
| **证据与恢复** | 不可变快照、append-only RunEvent、结果引用、幂等状态机、断线恢复 |
| **工程与安全** | SQLite/PostgreSQL、Alembic、Secret 引用、出站策略、脱敏、SBOM 与校验和 |
| **交付界面** | React 管理界面、HTTP API、MCP、CLI、JSON/Markdown/HTML 报告 |

## 文档导航

| 想做什么 | 从这里开始 |
|---|---|
| 运行第一个可复现场景 | [快速开始与安全部署](./docs/08-快速开始与安全部署.md) |
| 理解系统边界和数据流 | [总体架构](./docs/00-总体架构.md) |
| 接入新的被测 Agent | [V1 实现与接入](./docs/01-核心Agent价值复核与讨论交接.md) |
| 部署三 Agent 协作环境 | [AgentTeams 部署包](./deploy/agentteams/README.md) |
| 编排 MCP 工作流 | [Skill 目录](./skills/README.md) |
| 复核比赛证据与材料 | [GOAI 2026 交付中心](./docs/competition/README.md) |
| 查看全部权威文档 | [文档中心](./docs/README.md) |

## 质量门禁

主分支 CI 覆盖 Python 3.12/3.13、PostgreSQL migration、公开参考场景、wheel 隔离安装、前端
单元测试、浏览器与可访问性测试、依赖审计和生产构建。

```bash
uv run ruff check src tests scripts examples
uv run mypy src/agentrig
uv run pytest
cd web && npm run typecheck && npm run test:coverage && npm run e2e && npm run build
```

## 版本与成熟度

当前版本为 `0.2.0a0`，定位为 **GOAI 2026 参赛预览版 / Alpha**。V2 三角色协作闭环、公开
Reference CI、证据导出与安全边界均已实现并完成本机验收；当前适合评测复现、比赛演示和受控
试点，尚不是无人值守生产环境的通用 GA 版本。生产试点应保留计划确认、人工审批、最小权限和
审计门禁。

## 参与项目

提交问题或改进前请阅读[支持指南](./SUPPORT.md)、[贡献指南](./CONTRIBUTING.md)和
[安全策略](./SECURITY.md)。安全漏洞请使用 GitHub Private Vulnerability Reporting，不要创建
公开 Issue。

AgentRig 使用 [MIT License](./LICENSE)。
