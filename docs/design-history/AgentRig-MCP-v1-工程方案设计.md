# AgentRig MCP v1 工程实现附录

> 状态：历史评审稿，已被 `AgentRig-V1-MCP-架构与代码设计.md` 取代
> 版本：0.2-draft
> 日期：2026-07-28
> 文档归属：AgentRig
> 归档说明：保留用于追溯早期工程拆分，不作为当前 V1 实现合同
> 上位架构：[AgentRig 总体架构：双控制模式与可扩展多 Agent 协作](./AgentRig-总体架构-双控制模式与多Agent协作-v0.4.md)
> 主评审文档：[AgentRig MCP v1 方案设计（评审版）](./AgentRig-MCP-v1-方案设计-评审版.md)

---

## 0. 这份方案应该解决什么

这是一份面向产品负责人、架构评审者和实现者的工程设计，不要求读者先熟悉代码里的英文
类型。正文先解释业务问题和设计理由，再给出代码名、接口和目录结构。

它需要让实现者明确回答：

1. MCP v1 做什么，不做什么。
2. 当前有哪些 Agent，谁拥有控制权。
3. Claude Code/Codex 如何完成选案、构建、执行和诊断闭环。
4. AgentRig 内部怎样划分 Domain、Application、Adapter 和 Entrypoint。
5. RunSpec、EvaluationJob、Snapshot、Evidence 等核心对象如何建模。
6. MCP 暴露哪些高层工具，输入输出和幂等语义是什么。
7. 两条现有 Runner 如何迁移成一个 Execution Engine。
8. Simulation Curator 和 Evidence Judge 第一版如何落地，而不提前建设 AgentTeams。
9. SQLite、Artifact、Event 和审计如何保存。
10. 每个阶段如何验收，失败时如何回滚。

本方案通过后，应继续输出：

- 领域模型与事件协议 ADR。
- MCP Tool JSON Schema。
- SQLite migration。
- Execution Engine RFC。
- SimulationSnapshot RFC。
- Evidence/Judge/Gate RFC。
- PR 拆分清单和验收用例。

### 0.1 建议阅读顺序

- 想先判断产品方向是否正确：阅读第 1、2、25、26 节。
- 想判断模块拆分是否合理：阅读第 4、5、6、14 节。
- 准备实现 MCP：阅读第 7—17 节和第 24 节。
- 准备做后续 Web 助手：阅读第 26 节。

### 0.2 命名原则

正文第一次出现重要概念时，采用“中文业务名（`代码名`）”的写法。代码名用于 Python
类型、数据库表、JSON Schema 和 MCP 参数稳定，不代表又增加了一层产品概念。

一个英文名保留下来必须有明确理由：

1. 它对应一个需要独立保存或传输的对象。
2. 它与前后对象具有不同生命周期。
3. 合并后会丢失审计、重试或权限边界。
4. 团队可以用一句中文解释它。

---

## 1. 执行摘要

### 1.1 MCP v1 中，谁决定测什么

MCP v1 只有一个评测范围负责人：Claude Code 或 Codex。这里的“范围负责人”是说它负责
决定测哪些用例、是否创建新用例以及何时重跑；代码和协议中的字段名为 `control_owner`。

```text
用户
  │
  ▼
Claude Code / Codex
  │ 通过 AgentRig Skill 理解流程，通过 MCP 执行动作
  ▼
AgentRig 应用服务
  │
  ▼
确定性执行内核
```

Claude Code/Codex 负责：

- 阅读业务 Agent 仓库和 Git diff。
- 判断改动影响。
- 查询 Catalog/Coverage/History。
- 选择已有用例或 Suite。
- 构建/修改 TestCase 草稿。
- 请求用户确认。
- 提交不可变 RunSpec。
- 跟踪 EvaluationJob。
- 读取 Evidence 和报告。
- 回到业务代码完成修复。

这样设计的原因是：CC/Codex 已经读取了仓库、Git diff 和用户修改意图。如果首版再让
AgentRig 内置 Manager 重新理解一次改动并选择用例，会出现两个范围负责人，结论冲突时也
无法判断应该听谁的。

因此，MCP v1 不实现回归评测管理员（Regression Manager），也不实现 AgentRig Web
评测助手。

### 1.2 MCP v1 中实际存在的智能角色

| 中文角色 | 代码/文档名 | 首版形态 | 是否决定测什么 | 为什么需要 |
|---|---|---|---|---|
| 外部编程助手 | Claude Code/Codex | 外部主 Agent | 是 | 它掌握代码改动上下文 |
| 模拟环境管理员 | `SimulationCurator` | 内部受约束智能工作流 | 否 | 工具环境缺失时生成并校验候选返回 |
| 证据评审员 | `EvidenceJudge` | 内部受约束智能工作流 | 否 | 规则无法表达时判断任务语义是否完成 |
| 被测 Agent | `AgentTarget` | 被测试的对象 | 不适用 | 它是质量评测对象，不属于评测团队 |

“受约束智能工作流”是指它们可以调用 LLM，但没有自主扩大任务、自由调用工具或创建其他
Agent 的权力。首版调用链固定为：

```text
Application Service
  → 固定输入 Schema
  → 专用 Skill/Prompt
  → LLM Provider
  → 固定输出 Schema
  → 确定性校验
  → 持久化 Artifact
```

后续 Managed 版本把它们接入 AgentTeams 时，复用同一输入输出契约。

### 1.3 用户看到的完整闭环

```text
Codex 根据代码改动选择用例
  → 形成已确认执行清单（RunSpec）
  → AgentRig 创建评测任务（EvaluationJob）
  → 准备冻结的工具环境（SimulationSnapshot）
  → 执行被测 Agent
  → 保存证据包（EvidenceBundle）
  → 生成评测报告（EvaluationReport）
  → 给出是否应阻止发布的建议（GateRecommendation）
```

这条链上的对象不会一次性合并成一个“大结果”，因为它们分别承担范围确认、任务恢复、
环境复现、事实审计、解释和发布治理等不同责任。

### 1.4 MCP v1 的架构边界

```text
CC/Codex（决定测什么）
   │
   ▼
MCP 接口层（协议转换）
   │
   ▼
应用服务层（组织业务流程）
   │
   ├── 领域规则和状态机
   ├── 统一执行引擎
   ├── 模拟环境管理员接口
   ├── 证据评审员接口
   └── 数据库与不可变文件存储
```

MCP Tool 不直接：

- 操作数据库。
- 调用具体 Transport。
- 持有 `_runs` 全局变量。
- 计算 Verdict。
- 拼装完整业务流程。

### 1.5 核心名词为什么需要单独存在

| 中文含义 | 代码名 | 为什么单独定义，不能与相邻概念合并 |
|---|---|---|
| 本次评测由谁决定范围 | `control_owner` | 明确责任主体，防止 Codex 与未来平台 Manager 同时扩大范围 |
| 本次启用的可选智能能力 | `enabled_capabilities` | Curator、Judge 可以独立开关，不能压成含义模糊的单一运行档位 |
| 服务部署方式 | `deployment_profile` | 本地或生产只影响基础设施，不应该改变谁选案或是否启用 LLM |
| 被测项目中的一个逻辑 Agent | `AgentTarget` | 同一个 Agent 会有多个版本，身份不能和某次构建绑定 |
| 被测 Agent 的不可变版本 | `TargetRevision` | baseline/candidate 比较必须精确到代码、Prompt、模型和工具 Schema 指纹 |
| 一个版本化测试意图 | `TestCaseVersion` | 用例修改后，历史任务仍需引用运行时的旧版本 |
| 已确认执行清单 | `RunSpec` | 它回答“准备测什么”；确认后不可修改，防止运行过程中范围漂移 |
| 一次完整评测任务 | `EvaluationJob` | 它回答“执行到哪了”；需要取消、恢复和查询状态，生命周期比 RunSpec 长 |
| 某个被测版本的一轮执行 | `Run` | baseline 和 candidate 使用同一 RunSpec，但必须保存为两个 Run 才能比较 |
| 一个用例在一次 Run 中的执行 | `CaseRun` | 批量任务中每个用例需要独立结果和状态 |
| 一次具体尝试 | `Attempt` | 重试不能覆盖第一次失败，否则无法审计不稳定性 |
| 工具环境缺口请求 | `SimulationRequest` | 先明确缺什么，再允许 Curator 生成候选，避免模拟逻辑隐藏在执行器里 |
| 已校验并冻结的工具环境 | `SimulationSnapshot` | baseline/candidate 必须复用相同环境；动态候选不能直接成为门禁依据 |
| 原始执行事实集合 | `EvidenceBundle` | Judge 和报告只能引用事实，不能各自重新拼装或修改 Trace |
| 最终评测报告 | `EvaluationReport` | 把规则结果、语义判断、差异和局限组织成可阅读结论，但不替人发布 |
| 发布门禁建议 | `GateRecommendation` | 系统可以建议阻止或复核，但不能冒充最终发布授权 |
| 最终发布决定 | `ReleaseDecision` | 由人或受信 CI Policy 记录，责任主体与评测系统不同 |
| 被测 Agent 的对话接入接口 | `ConversationDriver` | 解决“如何发消息和接收事件”，不负责工具返回 |
| 工具调用边界 | `ToolBoundary` | 解决“工具调用由模拟、回放还是真实工具响应”，需要独立安全策略 |
| 被测 Agent 接入绑定 | `ExecutionBinding` | 记录使用哪个 ConversationDriver 和 ToolBoundary，通常随 AgentTarget 配置 |
| 单次运行限制 | `ExecutionPolicy` | 记录超时、轮数、重试和并发，随 RunSpec 固定，不能混入长期接入配置 |
| 外部能力抽象接口 | `Port` | 应用逻辑只依赖它，才能替换数据库、LLM、AgentTeams 或传输协议 |
| 接口的具体实现 | `Adapter` | SQLite、MCP Proxy、LLM Provider 都是可替换实现，不进入领域规则 |

---

## 2. 范围

### 2.1 v1 必须实现

1. Project、AgentTarget、TargetRevision。
2. 版本化 TestCase/TestSuite。
3. Catalog 搜索与 Coverage 查询。
4. TestCase 草稿校验、创建、更新和批准边界。
5. 不可变 RunSpec。
6. 持久化 EvaluationJob、Run、CaseRun、Attempt。
7. 统一 Execution Engine。
8. ConversationDriver 和 ToolBoundary 两个端口。
9. Fixture、Replay、SimulationRequest、SimulationSnapshot。
10. 真实 Sample 的 draft/approved/rejected 生命周期。
11. Event、Trace、Artifact 和 EvidenceBundle。
12. Rule Evaluator。
13. 可选 Evidence Judge。
14. EvaluationReport。
15. GateRecommendation；不自动发布。
16. MCP 工具和 CC/Codex Skills。
17. SQLite + 本地 Artifact Store。
18. CLI 启动、自检和 Demo。
19. 并发隔离、取消、超时、重试和基础审计。

### 2.2 v1 明确不实现

- AgentRig Web Evaluation Assistant。
- Regression Manager。
- Agent Capability Registry。
- Assignment Scheduler。
- AgentTeams Manager/Worker 部署。
- Worker 自主调用其他 Worker。
- 生产级 PostgreSQL/对象存储。
- 自动代码修复。
- 自动批准 TestCase。
- 自动发布。
- 通用 RCA/Report/Drift/Safety 独立 Agent。
- 组织级多租户和复杂 RBAC。

### 2.3 v1 可选能力

- Simulation Curator LLM Provider。
- Evidence Judge LLM Provider。
- baseline/candidate A/B。
- FROZEN_SYNTHETIC 人工批准。
- REST 只读查询接口。

关闭所有可选 LLM 能力后，Core 仍必须可运行。

---

## 3. 当前实现基线

截至 2026-07-28，AgentRig 已有：

- FastAPI + FastMCP `/mcp`。
- MCP Proxy `/proxy`。
- TestCase + SQLite Repository。
- `CaseRunner` transport 执行链。
- `ProxyScenarioRunner` proxy 执行链。
- Scripted/Replay/Synth 模拟能力。
- SampleLibrary。
- Rule Judge 和 AI Judge。
- Batch/A-B/RCA/Flywheel/Report/Release 的早期模块。
- 三份 Coding Agent Skill。
- 150 个通过的测试。

当前主要结构问题：

1. `models.py` 只有 TestCase/RoundData 等早期对象。
2. `CaseRunner` 和 `ProxyScenarioRunner` 是两条执行架构。
3. `runtime.py`、Repository 和 REST `_runs` 使用进程级状态。
4. Synth 结果可以直接进入执行，没有 Calibration/Freeze/Gating。
5. Run 结果没有统一持久化。
6. MCP Tool 自己串联业务逻辑。
7. Verdict 主要是二元 passed/reasons。
8. ReleaseVerdict 没有 Recommendation/Decision 分层。
9. Source 注释仍引用已归档旧文档。
10. 接口 DTO、Domain Model 和存储模型没有明确分层。

v1 重构应复用行为正确的资产，但不能把当前模块边界视为目标架构。

---

## 4. 设计原则

### 4.1 一个 Core，不为 MCP 单独写业务逻辑

MCP、REST、CLI 都调用同一 Application Service。

### 4.2 MCP 是控制协议，不是状态机

MCP Tool 接收 Command/Query，Application Service 执行状态变化。

### 4.3 命令与查询分离

- Command 改变状态，必须带 `idempotency_key`。
- Query 只读，可重复调用。

### 4.4 长任务异步化

`evaluations.submit` 立即返回 EvaluationJob ID。CC/Codex 使用 `get`/`wait` 查询，不让一次
MCP 请求阻塞整个 Run。

### 4.5 事实不可变

- RunSpec 提交后不可变。
- Retry 新增 Attempt。
- Snapshot 冻结后不可变。
- Evidence 不覆盖。
- Judge 重跑产生新版本。

### 4.6 动态模拟不能隐藏

模拟 Miss 必须显式生成 SimulationRequest。SYNTHETIC 只能进入 Calibration。

### 4.7 Agent 不可信，输出必须二次校验

Simulation Curator/Judge 的输出必须经过 Pydantic/Domain Policy 校验后才能持久化。

### 4.8 先保持模块清晰，再考虑微服务

v1 是模块化单体。模块边界通过 Python package 和 Port 保证，不提前拆分网络服务。

---

## 5. 目标代码模块结构

先不看文件名，代码只分成五类责任：

| 代码区域 | 中文解释 | 可以依赖什么 | 为什么这样分 |
|---|---|---|---|
| `domain` | 不依赖框架的业务规则 | 标准库和领域内代码 | 保证状态机、门禁规则和不可变约束可单测、不会被 MCP 或数据库绑死 |
| `application` | 把多个规则组织成一个用户动作 | `domain` 和抽象接口 | “提交评测”“冻结快照”等完整流程需要事务、权限和步骤编排 |
| `ports` | 应用层对外部能力提出的接口 | 只依赖稳定数据类型 | 让执行器不关心背后接 SQLite、LLM、MCP Proxy 还是 AgentTeams |
| `adapters` | 外部协议和基础设施的具体实现 | `application`、`ports` | FastMCP、SQLite、文件存储等技术变化不会进入核心规则 |
| `bootstrap` | 读取配置并把具体实现组装起来 | 可以看到所有实现 | 依赖选择集中在启动处，避免业务模块到处创建全局单例 |

这里的 `Port` 可以理解为插座标准，`Adapter` 是插到插座上的具体设备。它们不是为了套用
架构术语，而是为了保证未来把本地 SQLite 换成 PostgreSQL、把固定 Judge 换成 LLM Judge
时，不需要修改评测规则和状态机。

对应的推荐目录如下：

```text
src/agentrig/
├── __init__.py
├── bootstrap/
│   ├── app.py
│   ├── container.py
│   ├── lifespan.py
│   └── settings.py
│
├── domain/
│   ├── common/
│   │   ├── ids.py
│   │   ├── errors.py
│   │   ├── result.py
│   │   └── time.py
│   ├── catalog/
│   │   ├── models.py
│   │   ├── policies.py
│   │   └── ports.py
│   ├── planning/
│   │   ├── models.py
│   │   └── policies.py
│   ├── execution/
│   │   ├── models.py
│   │   ├── events.py
│   │   ├── state_machine.py
│   │   ├── policies.py
│   │   └── ports.py
│   ├── simulation/
│   │   ├── models.py
│   │   ├── state_machine.py
│   │   ├── policies.py
│   │   └── ports.py
│   ├── evidence/
│   │   ├── models.py
│   │   └── ports.py
│   ├── evaluation/
│   │   ├── models.py
│   │   ├── rules.py
│   │   ├── policies.py
│   │   └── ports.py
│   └── governance/
│       ├── models.py
│       ├── gate.py
│       └── ports.py
│
├── application/
│   ├── dto/
│   │   ├── commands.py
│   │   ├── queries.py
│   │   └── responses.py
│   ├── catalog/
│   │   ├── service.py
│   │   └── authoring.py
│   ├── planning/
│   │   └── run_spec_service.py
│   ├── execution/
│   │   ├── evaluation_job_service.py
│   │   ├── execution_engine.py
│   │   ├── tool_loop.py
│   │   ├── preflight.py
│   │   └── comparison.py
│   ├── simulation/
│   │   ├── service.py
│   │   ├── calibration.py
│   │   └── snapshot_service.py
│   ├── evidence/
│   │   ├── service.py
│   │   └── builder.py
│   ├── evaluation/
│   │   ├── service.py
│   │   └── report_builder.py
│   └── governance/
│       ├── gate_service.py
│       └── approval_service.py
│
├── ports/
│   ├── conversation_driver.py
│   ├── tool_boundary.py
│   ├── simulation_curator.py
│   ├── evidence_judge.py
│   ├── repositories.py
│   ├── artifact_store.py
│   ├── event_store.py
│   ├── task_runner.py
│   ├── id_generator.py
│   └── clock.py
│
├── adapters/
│   ├── inbound/
│   │   ├── mcp/
│   │   │   ├── server.py
│   │   │   ├── envelope.py
│   │   │   └── tools/
│   │   │       ├── system.py
│   │   │       ├── catalog.py
│   │   │       ├── cases.py
│   │   │       ├── samples.py
│   │   │       ├── simulations.py
│   │   │       ├── evaluations.py
│   │   │       ├── evidence.py
│   │   │       └── governance.py
│   │   ├── rest/
│   │   │   ├── router.py
│   │   │   └── schemas.py
│   │   └── cli/
│   │       ├── main.py
│   │       ├── doctor.py
│   │       └── demo.py
│   └── outbound/
│       ├── persistence/
│       │   ├── sqlite/
│       │   │   ├── connection.py
│       │   │   ├── migrations/
│       │   │   └── repositories/
│       │   └── memory/
│       ├── artifacts/
│       │   └── local.py
│       ├── conversation/
│       │   ├── streaming_chat.py
│       │   ├── subprocess.py
│       │   ├── echo.py
│       │   └── imported_trace.py
│       ├── tool_boundary/
│       │   ├── mcp_proxy.py
│       │   ├── external_loop.py
│       │   └── observe_only.py
│       ├── intelligence/
│       │   ├── simulation_curator.py
│       │   ├── evidence_judge.py
│       │   └── prompts/
│       ├── llm/
│       │   └── openai_compat.py
│       └── observability/
│           ├── logging.py
│           └── otel.py
│
└── compatibility/
    ├── legacy_case.py
    └── legacy_mcp_tools.py

skills/
├── discover-regression-cases/
├── author-regression-case/
├── harvest-tool-samples/
├── run-agent-regression/
└── inspect-regression-result/

tests/
├── unit/domain/
├── unit/application/
├── contract/mcp/
├── contract/ports/
├── integration/sqlite/
├── integration/execution/
├── e2e/mcp_codex_loop/
└── fixtures/
```

### 5.1 为什么不继续堆在 `src/agentrig/` 根目录

当前 `case_runner.py`、`scenario_runner.py`、`batch_runner.py`、`release.py`、`rca.py` 等并列，
很难看出依赖方向，也容易让 MCP Tool 直接导入实现。

目标结构让依赖保持：

```text
Inbound Adapter
      ↓
Application
      ↓
Domain ← Ports
              ↑
       Outbound Adapter
```

### 5.2 为什么保留独立 `ports/`

Port 是 Application 和外部世界的稳定边界。后续接 AgentTeams、PostgreSQL 或其他被测
Agent 协议时，Domain/Application 不需要移动。

### 5.3 为什么 v1 仍是模块化单体

- 当前团队和规模不需要分布式事务。
- SQLite + 本地 Artifact 更适合开源体验。
- 清晰 Port 足以为未来服务化准备。
- 先验证 RunSpec/Execution/Snapshot/Evidence 契约更重要。

---

## 6. 当前模块迁移映射

| 当前模块 | 目标位置 | 处理方式 |
|---|---|---|
| `models.py` | `domain/catalog`、`domain/execution` | 拆分模型 |
| `case_runner.py` | `application/execution/execution_engine.py` | 吸收 tool loop |
| `scenario_runner.py` | `execution_engine.py` + Driver/Boundary | 合并，不保留第二 Runner |
| `transports/*` | `adapters/outbound/conversation/*` | 实现 ConversationDriver |
| `proxy/*` | `adapters/outbound/tool_boundary/mcp_proxy.py` | 实现 ToolBoundary |
| `mock/*` | `domain/simulation` + compatibility | 复用匹配算法 |
| `simulator/*` | `application/simulation` + intelligence adapter | 增加 Snapshot 生命周期 |
| `judges/rule_judge.py` | `domain/evaluation/rules.py` | 保持纯函数 |
| `judges/ai_judge.py` | `adapters/outbound/intelligence/evidence_judge.py` | 使用固定契约 |
| `storage/*` | `ports/repositories.py` + sqlite adapters | 扩展多 Repository |
| `runtime.py` | `bootstrap/container.py` | 删除可变业务单例 |
| `mcp_tools/*` | `adapters/inbound/mcp/tools/*` | 只调用 Application |
| `api.py::_runs` | EvaluationJob/Run Repository | 删除 |
| `batch_runner.py` | `application/execution/comparison.py` | 按 RunSpec 批量 |
| `ab.py` | `comparison.py` | 绑定相同 Snapshot |
| `release.py` | `domain/governance` + service | Recommendation/Decision 分层 |
| `flywheel.py` | v1 非核心，后续 Regression Curator | 暂保 compatibility |
| `rca.py` | 初步分类并入 EvaluationReport | 不升级 Agent |
| `report.py` | `evaluation/report_builder.py` | 确定性 Renderer |
| `telemetry.py` | observability adapter | 统一 trace IDs |

迁移期间允许 compatibility 层短期存在，但新模块禁止反向导入 compatibility。

---

## 7. 核心领域对象

### 7.1 Project

```python
class Project:
    id: ProjectId
    name: str
    created_at: datetime
    default_policies: PolicyRefs
```

### 7.2 AgentTarget

```python
class AgentTarget:
    id: AgentTargetId
    project_id: ProjectId
    name: str
    driver_ref: str
    tool_boundary_ref: str
    default_execution_binding_ref: str
    credential_ref: str | None
```

### 7.3 TargetRevision

```python
class TargetRevision:
    id: TargetRevisionId
    target_id: AgentTargetId
    code_commit: str | None
    prompt_versions: dict[str, str]
    skill_versions: dict[str, str]
    model: ModelFingerprint
    tool_schema_hash: str
    config_hash: str
    created_at: datetime
```

TargetRevision 一旦创建不可变。

### 7.4 TestCaseVersion

```python
class TestCaseVersion:
    case_id: TestCaseId
    version: int
    project_id: ProjectId
    name: str
    stimulus: Stimulus
    fixture_requirement: FixtureRequirement
    expectations: list[Expectation]
    rubric: str | None
    evaluator_policy: EvaluatorPolicy
    coverage: CoverageDescription
    provenance: Provenance
    status: Literal["draft", "approved", "deprecated"]
```

第一版 Expectation：

- expected_tools
- forbidden_tools
- tool_order
- argument_constraint
- text_contains
- structured_output
- no_execution_error

不允许任意 Python 表达式进入 TestCase。

### 7.5 TestSuiteVersion

```python
class TestSuiteVersion:
    suite_id: TestSuiteId
    version: int
    case_refs: list[TestCaseVersionRef]
    status: Literal["draft", "approved", "deprecated"]
```

### 7.6 RunSpec

```python
class RunSpec:
    id: RunSpecId
    schema_version: str
    project_id: ProjectId
    control_owner: ControlOwnerRef
    enabled_capabilities: frozenset[Capability]
    target_id: AgentTargetId
    mode: Literal["single", "baseline_candidate"]
    baseline_revision_id: TargetRevisionId | None
    candidate_revision_id: TargetRevisionId
    scope: RunScope
    execution_policy: ExecutionPolicy
    simulation_policy: SimulationPolicy
    evaluation_policy: EvaluationPolicy
    gate_policy_ref: str | None
    selection_reason: str
    created_at: datetime
```

`RunScope` 必须引用明确版本：

```python
class RunScope:
    case_refs: list[TestCaseVersionRef]
    suite_refs: list[TestSuiteVersionRef]
```

禁止提交“当前最新全部用例”这类运行时可漂移范围；提交时必须解析成固定版本集合。

### 7.7 EvaluationJob

```python
class EvaluationJob:
    id: EvaluationJobId
    run_spec_id: RunSpecId
    state: EvaluationJobState
    run_refs: list[RunId]
    report_ref: ArtifactRef | None
    recommendation_id: GateRecommendationId | None
    created_at: datetime
    updated_at: datetime
```

### 7.8 Run/CaseRun/Attempt

```python
class Run:
    id: RunId
    job_id: EvaluationJobId
    revision_id: TargetRevisionId
    state: RunState

class CaseRun:
    id: CaseRunId
    run_id: RunId
    case_ref: TestCaseVersionRef
    state: CaseRunState

class Attempt:
    id: AttemptId
    case_run_id: CaseRunId
    attempt_number: int
    snapshot_ref: SimulationSnapshotRef | None
    state: AttemptState
    started_at: datetime | None
    completed_at: datetime | None
    error: ClassifiedError | None
```

### 7.9 SimulationRequest/Candidate/Snapshot

```python
class SimulationRequest:
    id: SimulationRequestId
    case_ref: TestCaseVersionRef
    tool_call: ToolCall
    contract_ref: ArtifactRef
    scenario_context_ref: ArtifactRef
    state_ref: ArtifactRef | None
    constraints: list[SimulationConstraint]

class SimulationCandidate:
    id: SimulationCandidateId
    request_id: SimulationRequestId
    result: JsonValue
    state_patch: JsonPatch | None
    provenance: SimulationProvenance
    validation: ValidationResult

class SimulationSnapshot:
    id: SimulationSnapshotId
    content_hash: str
    entries: list[SimulationEntry]
    provenance: SimulationProvenance
    approval: SnapshotApproval
    gating_eligible: bool
```

### 7.10 EvidenceBundle

```python
class EvidenceBundle:
    id: EvidenceBundleId
    attempt_id: AttemptId
    transcript_ref: ArtifactRef
    tool_trace_ref: ArtifactRef
    event_log_ref: ArtifactRef
    metrics_ref: ArtifactRef | None
    snapshot_ref: SimulationSnapshotRef | None
    target_revision_id: TargetRevisionId
    hashes: dict[str, str]
```

### 7.11 Evaluation

```python
class RuleEvaluationResult:
    id: RuleResultId
    attempt_id: AttemptId
    checks: list[RuleCheck]
    status: Literal["pass", "fail", "error"]

class SemanticEvaluation:
    id: SemanticEvaluationId
    evidence_bundle_id: EvidenceBundleId
    status: Literal["pass", "fail", "inconclusive", "error"]
    reason_codes: list[str]
    rationale: str
    evidence_refs: list[EvidenceRef]
    judge_fingerprint: str

class EvaluationReport:
    id: EvaluationReportId
    job_id: EvaluationJobId
    case_results: list[CaseEvaluation]
    comparison: BaselineCandidateComparison | None
    limitations: list[str]
```

### 7.12 Gate

```python
class GateRecommendation:
    id: GateRecommendationId
    job_id: EvaluationJobId
    status: Literal["pass", "block", "needs_review"]
    policy_version: str
    reasons: list[str]
    evidence_refs: list[EvidenceRef]

class ReleaseDecision:
    id: ReleaseDecisionId
    recommendation_id: GateRecommendationId
    decision: Literal["approved", "rejected", "overridden"]
    actor: ActorRef
    reason: str
```

MCP v1 可以生成 Recommendation，但不自动生成 ReleaseDecision。

---

## 8. 状态机

### 8.1 EvaluationJobState

```text
SUBMITTED
  │
  ▼
PREFLIGHT
  ├── invalid ───────────────► REJECTED
  ├── simulation gap ────────► WAITING_FOR_SIMULATION
  │                                  │
  │                                  ▼
  │                            SNAPSHOT_READY
  └──────────────────────────────────┘
  │
  ▼
CALIBRATING（按需，NON_GATING）
  ├── needs sample ──────────► NEEDS_REVIEW
  └── frozen snapshot
  │
  ▼
RUNNING
  ├── retryable ─────────────► RETRY_SCHEDULED ─► RUNNING
  ├── fatal ─────────────────► FAILED
  └── evidence ready
  │
  ▼
AWAITING_JUDGMENT
  ├── judge error ───────────► NEEDS_REVIEW / FAILED
  └── report ready
  │
  ▼
GATE_EVALUATING
  │
  ▼
COMPLETED / BLOCKED / NEEDS_REVIEW
```

### 8.2 AttemptState

```text
CREATED
  → PREPARING
  → RUNNING
  → COLLECTING_EVIDENCE
  → COMPLETED

任何阶段可进入：
  CANCELLED
  TIMED_OUT
  INFRA_ERROR
  SIMULATION_BLOCKED
```

### 8.3 状态机执行规则

- State Machine 是 Domain 纯函数。
- Application Service 校验 expected version 后持久化状态。
- Agent/Adapter 只能提交 Command。
- 每次状态变化追加 Event。
- 乐观锁防止重复完成。
- Retry 新建 Attempt，旧 Attempt 不回退状态。

---

## 9. Execution Engine

### 9.1 统一端口

#### ConversationDriver

```python
class ConversationDriver(Protocol):
    async def start(
        self,
        target: AgentTarget,
        revision: TargetRevision,
        stimulus: Stimulus,
        context: RunContext,
    ) -> AsyncIterator[AgentEvent]: ...

    async def continue_with_tool_results(
        self,
        session: DriverSession,
        results: list[ToolResult],
        context: RunContext,
    ) -> AsyncIterator[AgentEvent]: ...

    async def cancel(self, session: DriverSession) -> None: ...
```

#### ToolBoundary

```python
class ToolBoundary(Protocol):
    async def resolve(
        self,
        call: ToolCall,
        context: ToolResolutionContext,
    ) -> ToolResolution: ...
```

`ToolResolution`：

- resolved_fixture
- resolved_replay
- resolved_real
- simulation_gap
- denied
- error

### 9.2 接入绑定与运行限制

```python
class ExecutionBinding:
    conversation_driver: str
    tool_boundary: str
    environment_policy: EnvironmentPolicy

class ExecutionPolicy:
    timeout_seconds: int
    max_tool_rounds: int
    max_retries: int
    concurrency: int
```

`ExecutionBinding` 回答“如何连接这个被测 Agent”，通常随 AgentTarget 保存；`ExecutionPolicy`
回答“本次允许怎么跑”，随 RunSpec 固定。二者分开后，调整某次回归的超时不会修改
AgentTarget 配置，更换传输方式也不会偷偷改变重试规则。

### 9.3 执行算法

```text
load immutable RunSpec
  → create Run/CaseRun/Attempt
  → load exact Snapshot
  → build isolated RunContext
  → ConversationDriver.start
  → consume normalized AgentEvent
      ├── text/event → append Evidence Event
      ├── tool_call → ToolBoundary.resolve
      │     ├── result → continue driver
      │     └── gap → stop Attempt / create SimulationRequest
      ├── done → collect Evidence
      └── error → classify
  → build EvidenceBundle
  → rule evaluation
  → optional Evidence Judge
```

### 9.4 为什么 Simulation Miss 默认终止 Attempt

v1 不在工具调用热路径等待 LLM Curator：

- 避免目标 Agent 长时间挂起。
- 避免 MCP/HTTP session 超时。
- 保持证据边界清晰。
- Snapshot 准备好后创建新 Attempt。

未来受管 Driver 支持挂起时，可以增加有限等待策略。

### 9.5 baseline/candidate

`baseline_candidate` 模式必须：

1. 解析一次固定 Case 版本集合。
2. 为每个 Case 绑定同一个 Snapshot Hash。
3. baseline/candidate 使用同一个 EvaluationPolicy。
4. 生成独立 Run/Attempt/Evidence。
5. Comparison 只引用两边不可变结果。

---

## 10. Simulation 设计

### 10.1 Tool Simulation Engine

确定性部分：

- Exact Fixture 匹配。
- 顺序 Script 回放。
- Approved Sample Replay。
- 参数匹配。
- StatePatch。
- Schema 校验。
- Snapshot Hash。
- Provenance。

### 10.2 Simulation Curator Port

```python
class SimulationCuratorPort(Protocol):
    async def propose(
        self,
        request: SimulationRequest,
        context: SimulationContext,
    ) -> SimulationCandidate: ...
```

Curator 不获得：

- 数据库写权限。
- Gate 权限。
- TestCase 修改权限。
- 真实高风险写工具权限。

### 10.3 v1 Provider 顺序

```text
Fixture
  → Approved Replay
  → Allowed Real
  → SimulationRequest
       → Curator Candidate（可选）
       → deterministic validation
       → approval
       → Frozen Snapshot
```

### 10.4 Snapshot 冻结条件

必须全部满足：

- Tool Contract 可用。
- 结果可以 JSON 序列化。
- Output Schema/Shape 校验通过。
- 约束校验通过。
- StatePatch 合法。
- 多步状态无冲突。
- Provenance 完整。
- Approval Policy 满足。
- 内容 Hash 生成成功。

### 10.5 来源状态

```text
FIXTURE
REPLAY_APPROVED
REAL
SYNTHETIC_CANDIDATE
FROZEN_SYNTHETIC
```

只有前三类和满足 Policy 的 FROZEN_SYNTHETIC 可进入 Gating。

### 10.6 当前 SynthProvider 迁移

当前 hash cache 不等于 Snapshot：

- cache 没有审批。
- 没有完整状态约束。
- 没有 Case/Revision 绑定。
- 没有版本化 Provenance。

迁移后 SynthProvider 只负责生成 SimulationCandidate；缓存可以作为内部优化，但不能替代
Snapshot Repository。

---

## 11. Evidence 与 Judge

### 11.1 Evidence 是唯一事实依据

Judge 不能读取：

- 候选代码实现细节（默认）。
- CC/Codex 的主观结论。
- 未落盘的进程内对象。

Judge 读取：

- TestCase/Rubric。
- TargetRevision 摘要。
- EvidenceBundle。
- RuleEvaluationResult。
- Simulation Provenance。
- baseline/candidate comparison。

### 11.2 EvidenceJudgePort

```python
class EvidenceJudgePort(Protocol):
    async def evaluate(
        self,
        request: JudgeRequest,
    ) -> SemanticEvaluationDraft: ...
```

Application Service 必须验证：

- status 合法。
- 每个 FAIL/INCONCLUSIVE 有 EvidenceRef。
- EvidenceRef 属于当前 Job。
- ReasonCode 属于注册表。
- 基础设施错误不被标为 Agent regression。

### 11.3 Judge 输出

```json
{
  "status": "fail",
  "reason_codes": ["required_action_missing"],
  "rationale": "candidate 未在确认后调用 write_file",
  "evidence_refs": [
    "evidence://attempt/a_12/tool-call/3",
    "evidence://attempt/a_13/tool-call/4"
  ],
  "failure_owner": "agent",
  "confidence": 0.91,
  "limitations": []
}
```

### 11.4 Rule 与 Judge 关系

- 安全 Rule FAIL：Gate 必须 BLOCK，Judge 不能覆盖。
- 普通 Rule FAIL + Judge PASS：EvaluationReport 标记 conflict，转 NEEDS_REVIEW。
- Rule PASS + Judge FAIL：保留语义 FAIL，Gate 按 Policy。
- Judge INCONCLUSIVE：关键 Case 不得自动 PASS。
- Judge ERROR：不是 Agent FAIL。

### 11.5 AI Judge 迁移

当前 AI Judge 的二元 Verdict 迁为：

- 固定 JudgeRequest Schema。
- 固定 SemanticEvaluation Schema。
- 版本化 Prompt/Model fingerprint。
- EvidenceRef 强制。
- INCONCLUSIVE/ERROR 独立状态。

---

## 12. MCP v1 协议设计

### 12.1 通用返回信封

所有 Tool 返回稳定 JSON：

```json
{
  "schema_version": "1",
  "ok": true,
  "data": {},
  "error": null,
  "meta": {
    "request_id": "req_...",
    "server_version": "0.2.0",
    "warnings": []
  }
}
```

错误：

```json
{
  "schema_version": "1",
  "ok": false,
  "data": null,
  "error": {
    "code": "case_not_found",
    "message": "case not found",
    "retryable": false,
    "details": {}
  },
  "meta": {
    "request_id": "req_..."
  }
}
```

禁止把 Python traceback 作为公开错误返回。

### 12.2 命名规则

MCP 工具按用户要操作的对象分组。前缀不是内部模块名，而是让 CC/Codex 能快速判断“这个
工具会影响哪类数据”：

| 前缀 | 用户正在做什么 | 为什么独立 |
|---|---|---|
| `system_*` | 检查服务和查询支持能力 | 不读取或修改具体项目数据 |
| `catalog_*` | 搜索正式用例和覆盖信息 | 只读正式资产，不与草稿编辑混在一起 |
| `cases_*` | 校验、保存和审批用例草稿 | 会改变测试资产，需要幂等和审计 |
| `samples_*` | 管理真实工具调用样本 | 样本来源和审批规则不同于人工 Fixture |
| `simulations_*` | 准备、检查和冻结工具环境 | 动态生成结果必须经过独立的校验生命周期 |
| `evaluations_*` | 提交、等待、取消和重试评测任务 | 对应长任务状态机 |
| `evidence_*` | 读取 Trace、差异和证据包 | 只读原始事实，避免报告逻辑污染证据 |
| `governance_*` | 读取门禁建议、记录最终决定 | 发布建议和发布授权必须分离 |

FastMCP 若不支持带点名称，使用下划线；文档中的逻辑名称可以保留 `catalog.search_cases`。

### 12.3 System

#### `system_ping`

用途：健康检查。

#### `system_get_capabilities`

返回：

- server version
- schema versions
- enabled capabilities
- deployment profile
- available drivers/boundaries
- simulation curator availability
- evidence judge availability
- supported MCP tool versions

### 12.4 Catalog

#### `catalog_search_cases`

输入：

```json
{
  "project_id": "p_...",
  "query": "write tool confirmation",
  "tags": ["write", "permission"],
  "tool_names": ["write_file"],
  "status": "approved",
  "limit": 20,
  "cursor": null
}
```

输出每条包括：

- case_ref
- name
- coverage summary
- tags/tools
- last result summary
- status

#### `catalog_get_case`

输入明确 `case_id` + `version`；不传 version 时只用于浏览，RunSpec 仍必须解析固定版本。

#### `catalog_get_suite`

返回固定或最新可浏览 Suite。

#### `catalog_get_coverage`

按：

- tool
- capability
- prompt/skill
- tag
- change hint

返回 CoverageDescription 和 Gap。

### 12.5 Cases

#### `cases_get_schema`

替代当前硬编码文档，返回 TestCase Draft Schema 和 expectation kinds。

#### `cases_validate_draft`

只校验，不持久化。

#### `cases_upsert_draft`

Command，必须带 `idempotency_key`。

规则：

- 只能创建/更新 draft。
- approved 版本不能原地覆盖。
- 更新 approved Case 时创建新 draft version。

#### `cases_submit_for_approval`

将 draft 标记为 waiting_review。v1 不自动批准。

#### `cases_list_versions`

查询历史版本。

### 12.6 Samples

#### `samples_search`

只读，支持：

- tool name
- argument pattern
- status
- source
- target revision

默认不返回敏感原始字段，只返回脱敏 Artifact。

#### `samples_import_draft`

导入真实 Sample Draft，带来源证明。

#### `samples_update_status`

需要 reviewer 权限；approved/rejected。

### 12.7 Simulations

#### `simulations_prepare_snapshot`

输入：

```json
{
  "project_id": "p_...",
  "case_refs": ["case://write-confirm@4"],
  "revision_ids": ["rev_base", "rev_candidate"],
  "policy": {
    "allow_real_read": false,
    "allow_synthetic_candidate": true,
    "require_human_approval_for_synthetic": true
  },
  "idempotency_key": "..."
}
```

返回：

- ready snapshots
- simulation requests
- blocked reasons

#### `simulations_get_snapshot`

返回元数据和 ArtifactRef，不默认内联大型内容。

#### `simulations_approve_snapshot`

高风险 Command，需要 reviewer 权限。可延后至 v1.1；v1 可通过 CLI 完成。

### 12.8 Evaluations

#### `evaluations_submit`

输入：

```json
{
  "run_spec": {
    "schema_version": "1",
    "project_id": "p_...",
    "controller": {
      "type": "external_coding_agent",
      "identity": "codex",
      "session_ref": "optional"
    },
    "target_id": "target_...",
    "mode": "baseline_candidate",
    "baseline_revision_id": "rev_base",
    "candidate_revision_id": "rev_candidate",
    "scope": {
      "case_refs": [
        {"case_id": "write-confirm", "version": 4}
      ]
    },
    "execution_policy": {
      "profile": "remote-mcp-proxy",
      "timeout_seconds": 120,
      "max_attempts": 2,
      "concurrency": 2
    },
    "simulation_policy": {
      "require_frozen_snapshot": true,
      "allow_real": false
    },
    "evaluation_policy": {
      "rule": true,
      "semantic_judge": true
    },
    "selection_reason": "write_file schema and confirmation prompt changed"
  },
  "idempotency_key": "..."
}
```

返回：

```json
{
  "evaluation_job_id": "ej_...",
  "run_spec_id": "rs_...",
  "state": "submitted"
}
```

#### `evaluations_get`

返回：

- state
- progress
- case counts
- active/blocked stage
- simulation gaps
- report/recommendation refs

#### `evaluations_wait`

只读等待：

- `timeout_seconds` 最大 60。
- 状态变化或超时即返回。
- 用于减少 CC/Codex 忙轮询。

#### `evaluations_cancel`

Command，幂等。

#### `evaluations_retry`

只允许重试明确失败 Attempt；不允许修改 RunSpec。

#### `evaluations_list`

分页查询历史。

### 12.9 Evidence

#### `evidence_get_bundle`

返回 EvidenceBundle 元数据与 ArtifactRefs。

#### `evidence_get_trace`

支持分页和事件类型过滤。

#### `evidence_compare_runs`

对 baseline/candidate：

- 首个工具调用差异
- 参数差异
- 顺序差异
- 文本差异
- metrics 差异

先提供确定性结构 Diff。

#### `evidence_export_capsule`

输出给 CC/Codex 的精简交接：

```yaml
case_ref: case://write-confirm@4
status: fail
first_divergence: attempt://a_candidate/tool-call/3
baseline_ref: evidence://...
candidate_ref: evidence://...
rule_reasons:
  - forbidden_tool_before_confirmation
semantic_summary: candidate 在确认前调用写工具
suspected_scope:
  - prompt
limitations: []
```

### 12.10 Governance

#### `governance_get_report`

返回 EvaluationReport。

#### `governance_get_recommendation`

返回 PASS/BLOCK/NEEDS_REVIEW。

#### `governance_record_decision`

v1 默认不向普通 CC/Codex 暴露；只有受信 Human/CI Identity 可调用。

---

## 13. CC/Codex Skill 设计

MCP v1 的产品体验不能只靠工具名称。Skill 负责让 Coding Agent 正确使用工具。

### 13.1 `discover-regression-cases`

流程：

1. 阅读 Git diff。
2. 提取 changed tools/prompts/skills/capabilities。
3. 调 Catalog/Coverage。
4. 输出选择理由和覆盖缺口。
5. 不自动提交 Run。

### 13.2 `author-regression-case`

流程：

1. 查重。
2. 查询 approved real samples。
3. 读取 Case Schema。
4. 设计可观察断言。
5. `validate_draft`。
6. `upsert_draft`。
7. 请求用户批准。

### 13.3 `harvest-tool-samples`

流程：

1. 读取真实 Trace。
2. 过滤 real source。
3. 脱敏。
4. `samples_import_draft`。
5. 请求 reviewer。

### 13.4 `run-agent-regression`

流程：

1. 确认固定 Case 版本。
2. 预览 RunSpec。
3. 请求用户确认。
4. `evaluations_submit`。
5. `evaluations_wait/get`。
6. 不自行改变失败分类。

### 13.5 `inspect-regression-result`

流程：

1. 获取 Report/Recommendation。
2. 对失败取 Evidence Capsule。
3. 区分 Agent、Simulation、Fixture、Infra 和 Judge 问题。
4. 回到代码定位。
5. 不修改原始 Evidence。

### 13.6 Skill 验收

每个 Skill 需要：

- 触发与不触发条件。
- 输入输出。
- 依赖 MCP Tool。
- 用户确认点。
- 失败处理。
- 示例。
- 契约测试。
- 版本和回滚。

---

## 14. Application Service 设计

### 14.1 CatalogService

职责：

- 搜索和查询。
- Coverage 聚合。
- 解析固定版本引用。

不负责 Case 写入。

### 14.2 CaseAuthoringService

职责：

- Draft 校验。
- 创建/更新版本。
- 状态流转。
- 审批审计。

### 14.3 RunSpecService

职责：

- 将浏览态 scope 解析为固定 Case/Suite 版本。
- 校验 Revision、Policy 和 Gating Eligibility。
- 计算 RunSpec Hash。
- 保存不可变 RunSpec。

### 14.4 EvaluationJobService

职责：

- Submit/Get/Wait/Cancel/Retry。
- 状态机。
- 后台任务调度。
- 进度聚合。

### 14.5 SimulationService

职责：

- 查找 Fixture/Replay。
- 创建 SimulationRequest。
- 调 Curator Port。
- 验证 Candidate。
- 冻结 Snapshot。

### 14.6 ExecutionEngine

职责：

- Run/CaseRun/Attempt 生命周期。
- ConversationDriver/ToolBoundary。
- Event/Evidence。
- 错误分类和 Retry。

### 14.7 EvaluationService

职责：

- Rule Evaluator。
- 调 Judge Port。
- 校验 SemanticEvaluation。
- 构建 Report。

### 14.8 GateService

职责：

- 按版本化 Policy 聚合。
- 输出 Recommendation。
- 不执行发布。

---

## 15. 存储设计

### 15.1 v1 存储组合

```text
SQLite:
  metadata / state / indexes / audit

Local Artifact Store:
  transcripts / traces / snapshots / evidence / reports
```

### 15.2 建议表

```text
projects
agent_targets
target_revisions

test_cases
test_case_versions
test_suites
test_suite_versions
test_suite_members

run_specs
evaluation_jobs
runs
case_runs
attempts

tool_samples
simulation_requests
simulation_candidates
simulation_snapshots

events
artifacts
rule_results
semantic_evaluations
evaluation_reports
gate_recommendations
approvals
audit_events
```

### 15.3 关键字段

所有可变状态表：

- `id`
- `version` 乐观锁
- `state`
- `created_at`
- `updated_at`

所有版本对象：

- stable logical ID
- version number
- content hash
- status

### 15.4 Artifact URI

```text
artifact://{project_id}/{artifact_type}/{content_hash}
```

本地映射：

```text
.agentrig/artifacts/
  sha256/ab/cd/<full_hash>
```

Metadata 存：

- content type
- size
- hash
- creator
- created_at
- encryption/redaction status

### 15.5 Event

```json
{
  "event_id": "ev_...",
  "event_type": "AttemptStarted",
  "aggregate_type": "attempt",
  "aggregate_id": "a_...",
  "aggregate_version": 3,
  "occurred_at": "...",
  "actor": {"type": "service", "id": "execution-engine"},
  "correlation": {
    "evaluation_job_id": "ej_...",
    "run_id": "run_...",
    "trace_id": "trace_..."
  },
  "payload": {}
}
```

v1 不要求完整 Event Sourcing，但关键状态变化必须追加 Event。

### 15.6 Repository Port

按聚合拆分：

- ProjectRepository
- CatalogRepository
- RunSpecRepository
- EvaluationJobRepository
- RunRepository
- SimulationRepository
- EvaluationRepository
- GovernanceRepository

禁止创建一个万能 `DatabaseRepository`。

---

## 16. 后台任务与并发

### 16.1 TaskRunnerPort

```python
class TaskRunnerPort(Protocol):
    async def submit(
        self,
        task: EvaluationTask,
        *,
        idempotency_key: str,
    ) -> TaskRef: ...

    async def cancel(self, task_ref: TaskRef) -> None: ...
```

v1 Adapter 可以使用：

- FastAPI lifespan 内 asyncio task group。
- 持久化 Job 状态。
- 进程重启后扫描非终态 Job 并标记/恢复。

### 16.2 不依赖进程内任务作为事实

任务丢失后，Repository 能识别：

- Job 状态。
- 最后 Event。
- 已完成 Artifact。
- 是否可以安全重试。

### 16.3 RunContext

每个 Attempt 显式携带：

```python
class RunContext:
    project_id: ProjectId
    job_id: EvaluationJobId
    run_id: RunId
    case_run_id: CaseRunId
    attempt_id: AttemptId
    trace_id: str
    snapshot_ref: SimulationSnapshotRef | None
    execution_policy: ExecutionPolicy
```

禁止通过可变全局 Runtime 切换 inline mock。

### 16.4 并发

- concurrency 由 RunSpec 限制。
- 同一 Target 可配置最大并发。
- SQLite 使用 WAL + busy timeout。
- Artifact 写入使用临时文件 + 原子 rename。
- Snapshot 和 Case Version 只读，可安全共享。

---

## 17. 错误模型

### 17.1 分类

```text
validation_error
authorization_error
target_unreachable
driver_error
tool_boundary_error
simulation_gap
simulation_invalid
timeout
cancelled
rule_evaluation_error
judge_error
artifact_error
internal_error
```

### 17.2 Agent Failure 与 Infra Error 分离

只有被测行为不满足 Case/Rubric 时才是 Agent FAIL。

以下不能直接计为 Agent FAIL：

- 目标服务无法连接。
- Simulation Gap。
- Snapshot 无效。
- Artifact 写失败。
- Judge Provider 超时。
- AgentRig 内部异常。

### 17.3 Retry Policy

可重试：

- transient target/driver/network error
- rate limit
- judge provider transient error

默认不可重试：

- invalid RunSpec
- permission denied
- invalid Snapshot
- deterministic Rule FAIL

Retry 必须：

- 新建 Attempt。
- 保留旧错误。
- 使用相同 Case/Snapshot/Policy。

---

## 18. 安全与权限

### 18.1 MCP 鉴权

v1 支持 Bearer Token，至少区分：

- reader
- author
- runner
- reviewer
- admin

### 18.2 Tool 权限

CC/Codex：

- 可以查询 Catalog/Evidence。
- 可以创建 Draft。
- 可以提交 RunSpec。
- 默认不能批准 Snapshot/TestCase。
- 不能记录 ReleaseDecision。

### 18.3 真实工具

- 默认禁止真实写工具。
- Read-only Pass-through 按 Project Policy。
- 写工具需要 sandbox 或显式审批。
- Tool Boundary 记录所有调用和结果来源。

### 18.4 Prompt Injection

- Tool Result/Trace/Artifact 视为不可信数据。
- Judge/Curator Prompt 明确区分指令和 Evidence。
- 外部内容不能调用未授权工具。
- Curator/Judge 第一版不获得通用 MCP Tool 权限。

### 18.5 敏感数据

- Sample 导入前脱敏。
- Artifact 标记 sensitivity。
- MCP 默认返回摘要和 Ref，不内联大型敏感内容。
- Audit 记录读取主体。

---

## 19. 可观测性

### 19.1 Trace 层级

```text
MCP request span
  → application command span
    → evaluation job span
      → run/case/attempt span
        → target conversation span
        → tool boundary span
        → curator/judge span
```

### 19.2 日志字段

- request_id
- project_id
- controller
- evaluation_job_id
- run_id
- case_run_id
- attempt_id
- trace_id
- tool_name
- source
- error_code

### 19.3 Metrics

- Job duration/state count
- Case pass/fail/infra/inconclusive
- Tool source distribution
- Simulation Gap/Snapshot reuse
- Judge latency/error/inconclusive
- MCP request latency/error
- Artifact bytes
- Retry/cancel count

---

## 20. 配置

建议：

```toml
[server]
host = "127.0.0.1"
port = 8000
api_token = ""

[database]
url = "sqlite:///.agentrig/agentrig.db"

[artifacts]
path = ".agentrig/artifacts"

[execution]
default_timeout_seconds = 120
default_max_attempts = 1
default_concurrency = 2

[simulation]
allow_real_read = false
allow_synthetic_candidate = false
require_frozen_snapshot = true

[judge]
enabled = false
provider = ""
model = ""

[profiles.remote_mcp_proxy]
conversation_driver = "streaming_chat"
tool_boundary = "mcp_proxy"
```

环境变量只放密钥和部署覆盖，不把业务状态放环境变量。

---

## 21. CLI

```text
agentrig serve
agentrig doctor
agentrig demo
agentrig db migrate
agentrig db status
agentrig artifacts verify
agentrig jobs recover
```

### `doctor`

检查：

- DB 可写。
- Artifact 可写。
- MCP Server。
- Target endpoint。
- Proxy backends。
- LLM Provider（如果启用）。
- schema/migration version。

---

## 22. 测试策略

### 22.1 Domain Unit

- 状态机合法/非法转换。
- RunSpec 不可变。
- Gate Policy。
- Simulation source/gating eligibility。
- Error classification。

### 22.2 Application Unit

使用 Fake Ports：

- submit/idempotency。
- preflight。
- simulation gap。
- retry/cancel。
- baseline/candidate same snapshot。
- report/gate。

### 22.3 Port Contract

每个 Adapter 必须通过共享契约：

- ConversationDriver contract。
- ToolBoundary contract。
- Repository contract。
- ArtifactStore contract。
- Curator/Judge contract。

### 22.4 MCP Contract

每个 Tool 验证：

- JSON Schema。
- success/error envelope。
- auth。
- idempotency。
- pagination。
- stable error code。

### 22.5 Integration

- SQLite migration/repository。
- Artifact hash/atomic write。
- FastMCP lifespan。
- Background task recovery。
- streaming-chat driver。
- MCP proxy boundary。

### 22.6 E2E

场景一：固定 Fixture 单 Case。

场景二：Simulation Gap → Snapshot → 新 Attempt。

场景三：baseline/candidate 同 Snapshot，candidate Rule FAIL。

场景四：Judge INCONCLUSIVE → NEEDS_REVIEW。

场景五：CC/Codex 通过 MCP 完成：

```text
search → draft → approve boundary → submit → wait → evidence → report
```

### 22.7 并发与恢复

- 10 个 Case concurrency=2。
- 两个 Job 不串 Snapshot/Trace。
- 进程重启后非终态 Job 可恢复或明确失败。
- Cancel 不留下运行中状态。

### 22.8 Security

- 无权限不能写 Draft/Run/Approval。
- Path traversal。
- Artifact 越权读取。
- Prompt injection Evidence。
- 真实写工具默认拒绝。

---

## 23. 兼容策略

### 23.1 当前 MCP Tool

当前：

- `list_test_cases`
- `get_test_case`
- `upsert_test_case`
- `run_single_case`
- `run_case_proxy`
- `get_real_tool_samples`
- `list_runs`
- `get_verdict`
- `list_traces`

迁移方式：

- v1 新工具与旧工具并存一个短周期。
- 旧工具内部调用新 Application Service。
- 返回 warnings 标记 deprecated。
- 新 Skills 只使用新工具。
- 一个小版本后删除 compatibility。

### 23.2 TestCase 数据

当前 TestCase 自动迁移为 version=1：

- `user_message` → Stimulus。
- `expected_tools` → Expectation。
- `mock` → Fixture Draft。
- `expectations` → typed Expectation。
- `rubric/judge_mode` → EvaluatorPolicy。
- 缺少 Coverage/Provenance 标记 migration warning。

### 23.3 当前 Run 历史

进程内 `_runs` 不迁移；它不是可靠数据源。正式 v1 启用后只记录新 Run。

### 23.4 当前 Trace/Sample

可通过导入工具迁为 Sample Draft，不能自动 approved。

---

## 24. 实施 PR 拆分

### PR 0：RFC 与 ADR

- 通过本设计。
- 锁定核心命名和依赖方向。
- 建 ADR：
  - RunSpec boundary
  - unified execution
  - snapshot gating
  - evidence immutability

验收：没有代码行为变化。

### PR 1：Package Skeleton 与核心 Schema

- 新建 domain/application/ports/adapters/bootstrap。
- IDs、errors、RunSpec、Job、Run/Attempt。
- Pydantic DTO 与 Domain model 分离。

验收：

- mypy strict。
- schema snapshot tests。
- 旧功能不回归。

### PR 2：SQLite 与 Artifact Store

- migrations。
- repositories。
- event/artifact。
- 移除 REST `_runs` 依赖。

验收：

- restart persistence。
- concurrent repository tests。
- artifact hash verify。

### PR 3：统一 Execution Engine

- ConversationDriver。
- ToolBoundary。
- 合并 CaseRunner/ProxyScenarioRunner。
- RunContext 隔离。

验收：

- transport/proxy 同一 engine contract。
- 旧 e2e 用例迁移。
- 并发不串状态。

### PR 4：Simulation Lifecycle

- SimulationRequest/Candidate/Snapshot。
- Fixture/Replay/Real routing。
- Synth 只产 Candidate。
- Calibration/Freeze。

验收：

- 未冻结 synth 不可 gating。
- baseline/candidate same snapshot。
- stateful fixture test。

### PR 5：Evidence/Evaluation/Gate

- EvidenceBundle。
- Rule Result。
- Judge Port/Adapter。
- EvaluationReport。
- GateRecommendation。

验收：

- EvidenceRef。
- INCONCLUSIVE/ERROR。
- Rule/Judge conflict。

### PR 6：MCP v1 Tools

- 新 tool groups。
- envelope。
- auth/idempotency/pagination。
- compatibility wrapper。

验收：

- contract tests。
- restart + wait/cancel。
- no Tool direct repository access。

### PR 7：CC/Codex Skills

- 五个 Skills。
- examples。
- contract tests。
- Codex/Claude Code 配置文档。

验收：外部 Coding Agent 可完成完整闭环。

### PR 8：Demo、可靠性与发布准备

- doctor/demo。
- recovery。
- security tests。
- quickstart。
- metrics/report。

验收：一键 Demo + 全套质量检查。

---

## 25. v1 验收标准

### 25.1 产品闭环

用户在 Codex/Claude Code 中可以：

1. 查询本次改动相关用例。
2. 查看 Coverage Gap。
3. 构建 Draft。
4. 经用户确认提交 RunSpec。
5. 跟踪持久化 EvaluationJob。
6. 查看 Evidence 和 Recommendation。
7. 根据 Evidence 修复代码。

全程无需访问 AgentRig 内部数据库或直接调用 REST。

### 25.2 工程

- `ruff` 通过。
- `mypy --strict` 通过。
- 全部测试通过。
- Domain 不导入 FastAPI/MCP/DB/LLM SDK。
- MCP Tool 不直接导入 SQLite Adapter。
- 无进程内权威 `_runs`。
- 两种执行模式共用一个 Engine。

### 25.3 可重复性

- Case/Suite/Revision/RunSpec 全部固定版本。
- baseline/candidate 使用同一 Snapshot Hash。
- Retry 产生新 Attempt。
- Snapshot/Evidence 内容 Hash 可验证。

### 25.4 安全

- 未冻结 Synthetic 进入 Gating 数量为 0。
- 真实写工具默认拒绝。
- Judge 每个 FAIL/INCONCLUSIVE 有 EvidenceRef。
- Infra Error 不计为 Agent FAIL。
- 高风险审批有 AuditEvent。

### 25.5 恢复

- 服务重启后 Job/Run 可查询。
- 非终态 Job 能恢复或进入明确终态。
- Cancel 幂等。
- 相同 idempotency key 不创建重复 Job。

---

## 26. 后续 Managed 版本如何复用

MCP v1 完成后，Managed Evaluation Assistant 不重写 Core：

```text
MCP v1:
Codex/CC → MCP → Application → Core

Managed v2:
Regression Manager → 同一 MCP/Application → 同一 Core
```

Managed v2 新增：

- EvaluationRequest。
- ChangeSet Adapter。
- SelectionPlan。
- Regression Manager。
- Web Chat。
- Agent Registry/Assignment。
- AgentTeams Adapter。

保持不变：

- TestCase/TestSuite。
- RunSpec。
- EvaluationJob。
- SimulationSnapshot。
- Execution Engine。
- EvidenceBundle。
- Evidence Judge 契约。
- EvaluationReport/Gate。

因此 MCP v1 最关键的架构投资是稳定 Application Command 和领域 Artifact，而不是把逻辑
写死在某个 MCP Tool 名称中。

---

## 27. 已确认决策

1. MCP v1 由 CC/Codex 作为唯一评测 Controller。
2. MCP v1 不实现 Regression Manager 和 Web Evaluation Assistant。
3. Simulation Curator、Evidence Judge 先实现为受约束智能工作流。
4. AgentTeams 延后，不进入 v1 关键路径。
5. RunSpec 是外部 Controller 和 AgentRig Core 的统一边界。
6. MCP Tool 只调用 Application Service。
7. 执行统一为 ConversationDriver + ToolBoundary。
8. 动态 Simulation 必须经过 Candidate/Validation/Freeze。
9. Evidence 是 Rule/Judge/Gate 的事实依据。
10. GateRecommendation 与 ReleaseDecision 分离。
11. SQLite + Local Artifact 是 v1 默认存储。
12. 当前功能通过 compatibility 渐进迁移，不大爆炸重写。

---

## 28. 待拍板问题

1. v1 是否必须支持 baseline/candidate，还是 v1.1。
2. 第一批 Coverage Index 采用 tags/tools，还是同时支持 file/prompt mapping。
3. TestCase Approval 第一版由 CLI 还是 MCP reviewer tool 完成。
4. FROZEN_SYNTHETIC 是否进入 v1，还是只实现 Fixture/Replay。
5. EvaluationJob 后台任务采用纯 asyncio，还是一开始引入本地持久队列。
6. MCP Tool 名称采用下划线还是 namespace 点号。
7. MCP 返回使用 structured content 还是兼容 JSON text + structured content。
8. REST 是否保留写接口，还是只保留 Web 查询。
9. Artifact 是否需要 v1 即支持加密。
10. Judge v1 是否默认关闭。
11. compatibility 工具保留几个小版本。
12. ReleaseDecision 是否完全排除出 v1 MCP。

---

## 29. 建议的第一步

先不要直接移动代码。第一步应完成三个可评审产物：

1. `RunSpec/EvaluationJob/Run/Attempt` JSON Schema。
2. MCP v1 Tool 清单与每个 Tool 的请求/响应 Schema。
3. 当前模块到目标模块的迁移依赖图。

评审通过后，从 PR 1 的 Package Skeleton 开始，用 compatibility tests 保证现有 150 个测试
持续通过。

---

## 30. 一句话心智模型

```text
CC/Codex 决定测什么并通过 MCP 提交不可变 RunSpec；
AgentRig 用确定性 Core 准备环境、执行、保存证据和聚合门禁；
Simulation Curator 只补可信环境，Evidence Judge 只解释不可变证据；
MCP v1 稳定后，再让 Regression Manager 替代 CC/Codex 成为第二种 Controller。
```
