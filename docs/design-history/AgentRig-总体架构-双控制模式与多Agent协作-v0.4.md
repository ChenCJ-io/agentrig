# AgentRig 总体架构：双控制模式与可扩展多 Agent 协作

> 状态：V2 目标架构讨论稿，不属于当前 V1 实现合同
> 版本：0.4-draft
> 日期：2026-07-28
> 文档归属：AgentRig 目标架构
> 归档说明：保留用于后续内置助手与多 Agent 设计，不约束当前 V1
> 适用范围：AgentRig 开源产品、Web 产品、CC/Codex 集成、AgentTeams 比赛方案
> 外部约束：[GOAI 2026 Agent Infra 赛道要求](https://www.goaihz.com/tracks?track=infra)
> 第一阶段方案：[AgentRig MCP v1 方案设计（评审版）](./AgentRig-MCP-v1-方案设计-评审版.md)

---

## 0. 文档结论

AgentRig 采用同一个确定性质量内核，提供两种互斥的评测控制模式：

1. **外部编程助手控制**
   - Claude Code/Codex 读取仓库和 Git diff。
   - 通过 AgentRig MCP 查询、选用例、构建草稿、提交 RunSpec、跟踪结果。
   - AgentRig 内置主 Agent 不参与范围决策。

2. **AgentRig 内置助手控制**
   - 用户在 AgentRig Web 中与 Evaluation Assistant 对话。
   - Evaluation Assistant 的运行身份是 Regression Manager Agent。
   - Regression Manager 读取 ChangeSet、Catalog、历史结果和风险策略，自主选择用例并组织评测。
   - Regression Manager 调用 Simulation Curator、Evidence Judge，以及后续新增的专业子 Agent。

两种模式必须在同一个边界汇合：

```text
评测范围负责人
    │
    ▼
已确认且不可修改的执行清单（RunSpec）
    │
    ▼
AgentRig 确定性执行内核
```

AgentRig Managed 目标架构的首批三个核心 Agent 为：

1. **回归评测管理员（Regression Manager）**：用户可见的主 Agent；选案、制定评测计划、分派子 Agent、汇总进度。
2. **模拟环境管理员（Simulation Curator）**：构建、验证和冻结可复现的工具环境。
3. **证据评审员（Evidence Judge）**：基于不可变证据进行语义评测。

后续 Agent 不是继续塞进固定主流程，而是通过 Agent Capability Registry 注册，由主 Agent
按任务需要调用。Execution Engine、状态机、规则校验、Evidence、Gate、存储和审计始终
保持为确定性软件组件。

这里的“三个核心 Agent”是目标架构清单，不是 MCP v1 的首版交付清单。实际实施顺序为：

1. 先完成**外部编程助手控制模式**：CC/Codex 是唯一的评测范围负责人，通过 MCP
   完成用例发现、用例维护、模拟快照准备、执行、证据检查和发布建议读取。
2. MCP v1 中，Simulation Curator 和 Evidence Judge 先以固定输入输出、可校验、可替换的
   Intelligence Workflow/Port 落地，不先引入通用多 Agent 调度运行时。
3. MCP v1 验收稳定后，再建设 Web Evaluation Assistant、Regression Manager 和
   AgentTeams 协作层；它们复用相同的 RunSpec、Execution Engine、Evidence 和 Gate。

### 0.1 阅读约定

本文优先使用中文描述业务含义，英文只保留为代码、接口和协议中的稳定名字。例如：

- “已确认执行清单”在代码中叫 `RunSpec`。
- “一次完整评测任务”在代码中叫 `EvaluationJob`。
- “证据包”在代码中叫 `EvidenceBundle`。

英文名不是额外的业务概念。每个重要名词都应该回答四个问题：它解决什么问题、由谁创建、
何时不能再修改、为什么不能与相邻概念合并。如果一个名词不能回答这四个问题，就不应该
进入领域模型。

---

## 1. 产品定义

### 1.1 一句话定位

> AgentRig 是面向 AI Agent 的回归测试与发布治理平台：开发者可以让 Claude Code/Codex
> 直接控制评测，也可以在 AgentRig Web 中通过内置评测助手完成选案、执行、评测和证据审查。

英文定位：

> The evidence-driven regression test and release gate for AI agents, controlled
> by your coding agent or AgentRig's own evaluation team.

### 1.2 核心价值

1. **双入口**：既适合 Coding Agent 驱动的开发闭环，也支持平台自主评测。
2. **工具层可控**：在被测 Agent 最容易失控的工具调用层提供模拟、回放和证据。
3. **可信评测**：确定性规则和 Evidence Judge 分层，所有语义结论引用原始证据。
4. **发布治理**：把评测结果转化为结构化、可审计的 Gate Recommendation。
5. **持续积累**：将真实 Sample、失败 Evidence 和用户确认转化为长期测试资产。
6. **Agent 可扩展**：主 Agent 可以按需调用专业子 Agent，而不污染确定性内核。

### 1.3 核心用户

- AI Agent 开发者
- Claude Code/Codex 等 Coding Agent
- 测试与评测工程师
- CI/CD 和平台工程师
- 发布负责人
- 需要通过 Web 对话完成评测的非专业用户

### 1.4 非目标

AgentRig 不做：

- 通用业务 Agent 开发框架。
- 通用多 Agent 框架；AgentTeams 是协作运行时之一。
- 通用代码生成或代码修复平台。
- 替代 Claude Code/Codex 的完整仓库理解能力。
- 通用 CI/CD 或部署系统。
- 无人工边界的自动发布系统。
- 让 LLM 修改原始 Trace、Rule Result 或 Gate Policy。
- 为了满足 Agent 数量而把普通函数包装成 Agent。

---

## 2. 先说清系统里的三类配置

### 2.1 第一类配置：谁负责决定“测什么”

一次评测开始前，必须有人决定选择哪些用例、是否比较两个版本、允许多长时间以及哪些失败
会阻止发布。本文把这个责任叫作**评测范围控制权**，代码字段名为 `control_owner`。

| 业务上的负责人 | 代码值 | 什么时候使用 | 为什么单独定义 |
|---|---|---|---|
| Claude Code 或 Codex | `external_coding_agent` | 用户正在编程助手中修改被测项目 | 它已经掌握仓库、diff 和修改意图，不需要平台重复理解代码 |
| AgentRig 内置评测助手 | `agentrig_manager` | 用户以后在 AgentRig Web 中直接发起评测 | 平台需要自己理解需求、选择用例并解释范围 |
| 人工或 CI | `human_or_ci` | 调用方已经准备好明确的执行清单 | AgentRig 只执行，不再替调用方做范围判断 |

这里不再使用含义模糊的 `ControlMode`。`control_owner` 更准确，因为它记录的是“本次任务
由谁对评测范围负责”，而不是整个系统切换到了某种永久模式。

### 2.2 第二类配置：本次评测启用哪些能力

所有评测都必须经过确定性执行内核：执行用例、记录轨迹、运行规则和保存证据。这是系统
底座，不做成可关闭的“能力”。

在底座之上，本次评测还可以启用若干可选智能能力。它们不是互斥档位，而是一组可以组合的
开关，代码字段名为 `enabled_capabilities`：

| 能力 | 代码值 | 作用 | 未启用时如何运行 |
|---|---|---|---|
| 智能模拟环境补全 | `simulation_curator` | 工具返回缺失时构建并校验候选环境 | 只允许使用固定 Fixture 或真实回放 |
| 证据语义评审 | `evidence_judge` | 对规则难以判断的目标进行语义评测 | 只输出确定性规则结果 |
| 多 Agent 协作 | `agent_coordination` | 由 Manager 分派和跟踪多个专业 Agent | Controller 直接调用应用服务 |

这里不再定义 `RuntimeProfile = core/intelligent/agentteams/production`。原定义把能力组合与
部署方式混在了一起，而且这些值并不互斥。例如，AgentTeams 完全可以运行在生产环境中，
生产环境也可以只启用确定性内核。

### 2.3 第三类配置：系统部署在哪里

部署方式单独使用 `deployment_profile` 表示：

| 部署方式 | 代码值 | 含义 |
|---|---|---|
| 本地开发 | `local` | SQLite、本地文件、单进程或本地 Worker |
| 共享服务 | `server` | 团队共用服务、持久化数据库、独立 Worker |
| 生产环境 | `production` | 高可用、对象存储、完整审计、限流和监控 |

它只决定基础设施，不决定谁选用例，也不自动开启任何 LLM 或 AgentTeams 能力。

### 2.4 三类配置如何组合

| 用户看到的使用方式 | 评测范围负责人 | 启用能力 | 部署方式 |
|---|---|---|---|
| Codex 基础回归 | Codex | 无可选智能能力 | 本地开发 |
| Codex 智能回归 | Codex | 模拟补全 + 证据评审 | 本地或共享服务 |
| AgentRig Web 助手 | Regression Manager | 模拟补全 + 证据评审 | 共享服务 |
| 完整多 Agent 团队 | Regression Manager | 模拟补全 + 证据评审 + 多 Agent 协作 | 共享服务或生产环境 |

这就是“正交”的实际含义：更换评测范围负责人，不要求重写执行内核；增加智能能力，也不
会偷偷改变谁有权扩大评测范围。

### 2.5 一次评测任务只能有一个范围负责人

一次完整评测任务在代码中叫 `EvaluationJob`。它创建时就要记录 `control_owner`，运行中
不得静默切换。

```yaml
control_owner:
  type: external_coding_agent | agentrig_manager | human_or_ci
  identity: codex | claude-code | regression-manager | ci
  session_ref: optional
  selection_plan_ref: artifact://selection-plan/...
```

之所以这样设计，是为了避免 Codex 已经确认了一组用例后，平台内置 Manager 又在后台
扩大范围，导致成本、结果和责任都无法解释。

规则：

- CC/Codex 负责时，Regression Manager 不重新选择或扩大范围。
- AgentRig 内置助手负责时，CC/Codex 可以读取结果，但不能在同一任务中抢占控制权。
- 确实需要移交时，创建新的评测任务，并记录它来源于哪个旧任务。

### 2.6 Agent 做语义决策，确定性内核执行动作

Agent 可以：

- 理解用户评测意图。
- 分析 ChangeSet 与用例覆盖。
- 选择候选用例。
- 判断需要哪个专业子 Agent。
- 形成结构化建议和解释。

Agent 不可以：

- 直接操作数据库内部表。
- 驱动被测 Agent 的逐事件状态机。
- 修改原始 Evidence。
- 绕过审批冻结 Snapshot。
- 直接改变 Gate Policy。
- 直接批准高风险发布。

### 2.7 对话不是事实数据库

聊天记录用于交互和解释，不是 EvaluationJob 的唯一状态来源。

所有重要结果必须物化为结构化对象：

- SelectionPlan
- RunSpec
- Assignment
- SimulationSnapshot
- EvidenceBundle
- SemanticEvaluation
- EvaluationReport
- GateRecommendation
- Approval

### 2.8 Agent 间通过不可变产物交接

Agent 间不能只传自由文本。本文把可保存、可引用、不可原地修改的结构化产物称为
`Artifact`。大型上下文只传 Artifact 引用；短文本只用于摘要、请求和解释。

### 2.9 智能模拟先校准、后冻结、再门禁

动态生成结果只能形成 SimulationCandidate，不能直接进入正式 Gating Attempt。

### 2.10 开源默认不强制 AgentTeams 或 LLM

AgentRig Core 必须能够：

- 本地启动。
- 使用固定 Fixture/Replay。
- 运行确定性 Rule Evaluator。
- 在没有 LLM Key、没有 AgentTeams 时完成基础回归。

---

## 3. 两种主要使用模式

### 3.1 外部编程助手控制

#### 适用场景

- 开发者正在使用 Claude Code/Codex 修改业务 Agent。
- Coding Agent 已掌握完整代码、Prompt、工具 Schema 和 Git diff。
- 用户希望在 IDE/终端中完成回归闭环。

#### 主流程

```text
代码/Prompt/Skill/工具 Schema 变化
               │
               ▼
Claude Code / Codex
读取仓库、diff 和用户意图
               │
               ├── catalog.search_cases
               ├── catalog.get_coverage
               ├── evidence.search_history
               ├── cases.submit_draft
               └── evaluations.submit_run_spec
               │
               ▼
AgentRig Core + 可选专业 Agent
               │
               ▼
EvaluationReport / Evidence Capsule
               │
               ▼
Claude Code / Codex 定位并修复代码
```

#### CC/Codex 负责

- 读取完整仓库和 diff。
- 识别本次变化影响面。
- 选择已有 TestCase/TestSuite。
- 发现覆盖缺口时构建或更新用例草稿。
- 经用户确认后提交不可变 RunSpec。
- 根据 EvaluationReport 和 Evidence 回到代码修复。

#### AgentRig 负责

- Catalog、Coverage、历史 Evidence 查询。
- RunSpec 校验和持久化。
- Simulation、Execution、Evidence、Evaluation、Gate。
- 长任务状态、取消、重试、审计和报告。

#### 明确边界

- Regression Manager 不在后台二次改写 CC/Codex 的用例范围。
- 平台可以提供非约束性的覆盖提示，但不能静默追加用例。
- CC/Codex 不直接写原始 Evidence 或 EvaluationResult。

---

### 3.2 AgentRig 内置评测助手控制

#### 适用场景

- 用户不使用 Claude Code/Codex。
- Web 用户希望通过自然语言管理评测。
- CI、定时回归或无人值守评测。
- 企业希望由平台统一执行选案策略、权限和预算。

#### 主流程

```text
用户 / CI
   │
   ▼
Evaluation Assistant Chat
   │
   ▼
Regression Manager Agent
   │
   ├── 读取 EvaluationRequest
   ├── 获取 ChangeSet
   ├── 查询 Catalog / Coverage / History
   ├── 形成 SelectionPlan
   ├── 请求用户确认（按 Policy）
   └── 提交 RunSpec
           │
           ▼
     AgentRig Core
           │
           ├── Simulation Curator
           ├── Evidence Judge
           └── 后续专业子 Agent
```

#### Managed 模式的必要输入

Regression Manager 没有天然的完整代码上下文，平台必须为其提供结构化 ChangeSet：

- baseline/candidate commit
- changed files
- diff 或 diff summary
- Prompt/Skill 版本变化
- Tool Schema 变化
- 模型和参数变化
- 依赖变化
- 用户提供的风险说明
- TargetRevision 指纹

如果 ChangeSet 信息不足，Manager 必须：

1. 请求用户或 Git Adapter 补充；
2. 降级为用户显式指定 Suite；
3. 或选择全量 Suite；
4. 不能假装已经完成准确影响分析。

#### SelectionPlan

Managed 模式中，Manager 先生成可预览的 SelectionPlan：

```yaml
selection_plan_id: sp_...
change_set_ref: artifact://change-set/cs_...
selected_cases:
  - case_ref: case://tool-write-confirmation@4
    reasons:
      - write_file schema changed
      - historical failure cluster FC-12
    risk: high
excluded_cases:
  - case_ref: case://image-read-only@2
    reason: no impacted capability
coverage_gaps:
  - capability: batch-write rollback
    reason: no approved case
estimated:
  attempts: 24
  duration_seconds: 260
  model_cost_class: medium
confidence: 0.82
```

用户确认后，SelectionPlan 才被编译成不可变 RunSpec。

---

## 4. 用户体验与界面模型

### 4.1 主对话栏的身份变化

AgentScope 时代的对话栏主要用于直接测试被测 Agent。AgentRig Web 的主对话栏改为：

> 用户与 AgentRig Evaluation Assistant 对话，由它管理用例、运行、子 Agent 和评测结果。

Evaluation Assistant 是产品名称；其底层 Agent Identity 是 Regression Manager。

### 4.2 被测 Agent 不再是主聊天对象

被测 Agent 作为 AgentTarget 在后台运行，其会话展示在：

- Run Detail
- Transcript
- Tool Trace
- Evidence Timeline
- Target Playground

不能把 Evaluation Assistant 的管理对话与被测 Agent 的运行对话混为一条消息流。

### 4.3 Web 工作区建议

```text
┌───────────────────────────────────────────────────────────┐
│ Project / Target / Revision / control_owner               │
├──────────────────────┬────────────────────────────────────┤
│ Evaluation Assistant │ Plan / Run / Evidence Workspace    │
│                      │                                    │
│ 用户自然语言          │ SelectionPlan Preview              │
│ Manager 回复          │ EvaluationJob Timeline             │
│ Agent 活动摘要        │ Sub-agent Assignments              │
│ 审批请求              │ Trace / Evidence / Gate            │
│                      │                                    │
├──────────────────────┴────────────────────────────────────┤
│ Approvals / Cost / Status / Cancel / Retry / Export       │
└───────────────────────────────────────────────────────────┘
```

### 4.4 对话式评测示例

```text
用户：
帮我评测这次工具权限相关的修改。

Evaluation Assistant：
检测到 tool_policy.py 和 write_file Schema 发生变化。
建议执行 12 个用例：
- 7 个写工具权限用例
- 3 个禁止调用用例
- 2 个多轮确认用例

发现 1 个覆盖缺口：批量写入失败后的回滚行为。
预计 4 分钟，使用 baseline/candidate 相同 Snapshot。
是否提交本次评测？

用户：
开始。

Evaluation Assistant：
已创建 EvaluationJob EJ-102。
Simulation Curator 正在准备工具环境：8/12。
Execution Engine 正在执行 candidate：6/12。
Evidence Judge 已完成 10/12。
```

### 4.5 Target Playground

保留独立的 Target Playground：

- 用户直接与被测 Agent 对话。
- 可手动触发工具调用。
- 可录制 Trace 和真实 Sample。
- 可以把一次会话提交为 RegressionCandidate。

Playground 是调试入口，不是正式 Gating 入口。

---

## 5. 多 Agent 团队

Managed 模式采用一个用户可见的主 Agent 和按 Capability 注册的专业子 Agent：

```text
Regression Manager Agent
├── Simulation Curator Agent            P0
├── Evidence Judge Agent                P0
├── Change Impact Analyst Agent         P1
├── Regression Curator Agent            P1
├── RCA Analyst Agent                   P1
├── Adversarial Scenario Agent          P2
├── Safety Auditor Agent                P2
├── Performance Analyst Agent           P2
├── Behavior Drift Agent                P2
└── Report Agent                        P3
```

这棵树表示任务委派关系，不表示所有 Agent 每次都启动。External CC/Codex 模式不启动
Regression Manager；CC/Codex 作为外部 Controller 直接通过 MCP 提交 RunSpec，并按需
调用同一组专业能力。

### 5.1 回归评测管理员（Regression Manager）

AgentTeams 映射：`Manager`

#### 使命

在 AgentRig Managed 模式中理解用户评测意图，基于 ChangeSet、Catalog、Coverage、历史证据
和 Policy 制定评测范围，创建 RunSpec，并按任务需要调用专业子 Agent。

#### 输入

- EvaluationRequest
- ChangeSet
- AgentTarget/TargetRevision
- TestCase/TestSuite Catalog
- Coverage Index
- Historical Evaluation Summary
- Execution/Simulation/Evaluation/Gate Policy
- 用户预算和时间要求

#### 输出

- SelectionPlan
- CoverageGap
- RunSpec
- Assignment
- ProgressSummary
- EscalationRequest
- EvaluationCompletionSummary

#### 可以做的决策

- 选择增量用例还是全量 Suite。
- 按风险和预算排序用例。
- 判断是否需要 Simulation Curator。
- 判断是否需要额外的专业评测 Agent。
- 对 `INCONCLUSIVE` 结果请求补充证据或人工复核。
- 汇总多个 Worker 的状态和 Artifact。

#### 禁止动作

- 修改已提交的 RunSpec。
- 自己驱动被测 Agent 的事件循环。
- 自己生成工具返回。
- 修改 Evidence 或 Rule Result。
- 自己给出最终 Semantic PASS/FAIL。
- 覆盖 Gate Policy。
- 自动批准高风险发布。

#### 为什么它是 Agent

它的核心价值不是进度轮询，而是：

- 理解自然语言评测意图。
- 将 ChangeSet 语义映射到测试覆盖。
- 在风险、成本、时间和历史失败之间做选择。
- 识别覆盖缺口并解释选择理由。
- 判断需要调用哪个专业子 Agent。

如果一个实现只会按固定流程调用 API，则它只是 Workflow Service，不应标记为 Regression Manager Agent。

---

### 5.2 模拟环境管理员（Simulation Curator）

AgentTeams 映射：`Worker`

#### 使命

把未知或不完整的工具环境转化为可信、可验证、可冻结、可复现的 SimulationSnapshot。

#### 输入

- SimulationRequest
- Tool Contract/Input Schema/Output Schema
- TestCase 场景与约束
- Approved Real Samples
- 历史 Fixture
- 前序 ToolCall 和 Session State
- Simulation Policy

#### 输出

- SimulationCandidate
- ValidationResult
- StatePatch
- Provenance
- SimulationSnapshot
- `NEEDS_REAL_SAMPLE`
- `STATE_CONFLICT`
- `UNSAFE_TO_GATE`

#### 可以做的决策

- 复用 Fixture、Replay Sample，还是生成候选。
- 选择最接近的真实 Sample。
- 修复候选的 Schema 和状态一致性问题。
- 判断信息是否足够冻结。
- 拒绝不可信模拟并请求真实 Sample。

#### 禁止动作

- 修改 TestCase 预期以适配模拟结果。
- 把动态生成结果直接用于门禁。
- 将合成结果写入真实 Sample 库。
- 调用未经授权的真实写工具。
- 修改 Run Trace。

---

### 5.3 证据评审员（Evidence Judge）

AgentTeams 映射：`Worker`

#### 使命

基于不可变 Evidence、Rule Result、Rubric 和 baseline/candidate 差异进行语义评测。

#### 输入

- TestCase/RunSpec
- EvidenceBundle
- RuleEvaluationResult
- Baseline/Candidate Diff
- Rubric
- Simulation Provenance
- Evaluation Policy

#### 输出

- SemanticEvaluation
- PASS / FAIL / INCONCLUSIVE / ERROR
- ReasonCode
- Evidence 引用
- Evidence Sufficiency
- 初步失败分类
- 建议补充证据

#### 可以做的决策

- 判断语义目标是否完成。
- 判断 baseline/candidate 是否发生行为回归。
- 判断失败更可能来自 Agent、Fixture、环境还是基础设施。
- 证据不足时返回 INCONCLUSIVE。

#### 禁止动作

- 修改 TestCase、Snapshot、Trace 或 Rule Result。
- 无 Evidence 引用地判定。
- 把基础设施错误当成 Agent 回归。
- 直接批准发布。

---

### 5.4 后续专业子 Agent

主 Agent 未来可以调用更多专业 Agent，但这些 Agent 不默认进入每次运行。

| Agent | 核心职责 | 触发条件 | 建议阶段 |
|---|---|---|---|
| Change Impact Analyst | 深化 ChangeSet 与能力影响分析 | 大型仓库、复杂依赖 | P1 |
| Regression Curator | 从真实失败中形成 RegressionCandidate | 生产 Trace/失败积累 | P1 |
| RCA Analyst | 首个分叉、失败聚类、根因假设 | 批量失败或无人值守 | P1 |
| Adversarial Scenario Agent | 设计故障注入和边界场景 | 安全/鲁棒性专项 | P2 |
| Safety Auditor | 独立安全策略与越权审查 | 高风险工具 | P2 |
| Performance Analyst | 延迟、成本和资源回归分析 | 性能门禁 | P2 |
| Behavior Drift Agent | 跨版本行为漂移检测 | 历史数据充足 | P2 |
| Report Agent | 面向不同受众生成报告 | 多受众沟通需求 | P3 |

#### Agent 升级标准

一个能力升级为独立 Agent 前，必须同时满足：

1. 存在无法稳定编码的语义决策。
2. 有独立输入和结构化输出 Artifact。
3. 有独立工具或权限边界。
4. 有独立模型、Prompt、Skill 或运行预算的必要性。
5. 可以被单独评测。
6. 主流程能够在它失败时降级或转人工。

否则优先实现为：

```text
确定性函数 → Application Service → Skill → 独立 Agent
```

---

## 6. Agent 能力注册表（`Agent Capability Registry`）

主 Agent 不应硬编码所有 Worker 名称，而应面向 Capability 分派任务。

这里的“能力”是一个可分派动作，例如“冻结模拟快照”，不是 Agent 的自然语言职位名称。
注册表存在的原因是让同一种能力可以由确定性函数、本地 Agent、AgentTeams Worker 或人工
评审者替换实现。

### 6.1 Agent 身份（`AgentIdentity`）

```yaml
identity_id: agentrig-simulation-curator
version: 1.0.0
role: worker
capabilities:
  - simulation.resolve_gap
  - simulation.validate_candidate
  - simulation.freeze_snapshot
skills:
  - resolve-simulation-request@1
  - validate-simulation-candidate@1
allowed_tools:
  - samples.search
  - simulation.create_candidate
  - simulation.validate
  - simulation.freeze
permissions:
  evidence: read
  simulation: write_candidate
  real_tools: read_only_by_policy
  gate: none
input_schemas:
  - SimulationRequest@1
output_schemas:
  - SimulationSnapshot@1
failure_modes:
  - NEEDS_REAL_SAMPLE
  - STATE_CONFLICT
  - UNSAFE_TO_GATE
```

### 6.2 按能力分派

Regression Manager 创建 Assignment：

```yaml
assignment_id: as_...
evaluation_job_id: ej_...
capability: simulation.freeze_snapshot
input_artifact_refs:
  - artifact://simulation-request/sr_...
required_output_schema: SimulationSnapshot@1
budget:
  timeout_seconds: 180
  max_model_calls: 4
  max_cost_class: medium
permissions_profile: simulation-curator-default
```

Scheduler 根据 Registry 选择满足条件的 Worker。

### 6.3 可替换性

同一 Capability 可以有多个实现：

- deterministic adapter
- local LLM agent
- hosted agent
- AgentTeams Worker
- human reviewer

Domain Core 不依赖具体 Agent 框架。

### 6.4 初期层级限制

P0/P1 阶段：

- 只有 Regression Manager 可以创建跨 Agent Assignment。
- Worker 不直接继续生成 Worker。
- 最大 Agent 层级为两层。

后续确需层级委派时，必须通过 Scheduler 和 Policy 显式授权，不能让 Worker 任意递归生成 Agent。

---

## 7. 逻辑系统架构

```text
┌────────────────────── Experience & Control Plane ───────────────────────┐
│ AgentRig Web / Evaluation Assistant                                    │
│ Claude Code / Codex Skills + MCP                                       │
│ CLI / CI / REST                                                        │
│ Target Playground                                                      │
└────────────────────────────────┬─────────────────────────────────────────┘
                                 │ Commands / Queries / Chat Intent
┌────────────────────────────────▼─────────────────────────────────────────┐
│                         Agent Coordination Plane                         │
│ Regression Manager │ Agent Registry │ Assignment Scheduler              │
│ Agent Runtime Port │ Human Review │ AgentTeams Adapter                  │
└────────────────────────────────┬─────────────────────────────────────────┘
                                 │ Application Commands / Artifact Refs
┌────────────────────────────────▼─────────────────────────────────────────┐
│                           Application Layer                              │
│ Catalog Service │ EvaluationJob Service │ Run Service                   │
│ Simulation Service │ Evidence Service │ Evaluation Service              │
│ Gate Service │ Approval Service │ Artifact Service                      │
└────────────────────────────────┬─────────────────────────────────────────┘
                                 │
┌────────────────────────────────▼─────────────────────────────────────────┐
│                         Deterministic Domain Core                         │
│ Catalog │ Planning Contracts │ Execution │ Simulation │ Evidence         │
│ Evaluation │ Governance │ State Machines │ Policies                     │
└────────────────────────────────┬─────────────────────────────────────────┘
                                 │ Ports
┌────────────────────────────────▼─────────────────────────────────────────┐
│                                Adapters                                  │
│ Git/ChangeSet │ ConversationDriver │ ToolBoundary │ LLM Providers        │
│ Repositories │ Artifact/Event Store │ AgentTeams │ OTel │ CI/CD          │
└──────────────────────────────────────────────────────────────────────────┘
```

### 7.1 用户入口与控制层（Experience & Control Plane）

入口只负责：

- 身份解析。
- 协议转换。
- 请求校验。
- DTO 映射。
- 对话呈现。

入口不得：

- 持有进程内权威 Run 状态。
- 自己计算 Verdict。
- 绕过 Application Service 写 Repository。
- 把聊天历史当成 EvaluationJob 数据库。

### 7.2 Agent 协作层（Agent Coordination Plane）

负责：

- Agent Identity 和 Capability 发现。
- Assignment 创建、租约、心跳、超时和取消。
- Agent 权限和预算注入。
- Artifact 引用交接。
- AgentTeams/本地 Agent Runtime 适配。
- Human Review 任务映射。

### 7.3 应用服务层（Application Layer）

负责：

- 权限、事务和幂等。
- 创建领域对象。
- 驱动确定性状态机。
- 调用 Agent Runtime Port。
- 写 Event、Artifact 和 Audit。
- 返回稳定 DTO。

### 7.4 确定性领域内核（Domain Core）

Domain 只包含：

- 领域模型。
- 状态机。
- 策略。
- Port 接口。
- 纯计算规则。

禁止 Domain 导入：

- FastAPI
- MCP SDK
- AgentTeams SDK
- 数据库 SDK
- 具体 LLM SDK

---

## 8. 统一领域模型

这一节不是数据库表清单，而是在拆分一条评测事实链：

```text
评测意图
  → 可审查的选案计划
  → 不可修改的执行清单
  → 可恢复的评测任务
  → 具体执行与重试
  → 原始证据
  → 评测报告
  → 发布建议与最终决定
```

只有生命周期、修改权限或审计责任不同的对象才单独建模。

### 8.1 项目空间（`Project`）

测试资产、Target、权限、Policy 和审计的顶层命名空间。

单独定义它是为了隔离不同团队或产品的用例、凭证和运行记录。

### 8.2 被测 Agent（`AgentTarget`）

被测 Agent 的逻辑身份，包含：

- 能力描述
- ConversationDriver 引用
- ToolBoundary 引用
- 默认接入绑定（`ExecutionBinding`）引用
- 凭证引用

不保存明文凭证。

它表示“我们长期在测试谁”，不能和某次代码版本合并，因为一个 Agent 会持续产生多个待
比较版本。

### 8.3 被测版本（`TargetRevision`）

不可变被测版本指纹：

- code commit
- Prompt/Skill 版本
- 模型与参数
- Tool Schema 版本
- 配置摘要
- 构建产物摘要

版本必须不可变，否则同一个结果无法回答当时究竟测试了哪份代码、Prompt 和工具定义。

### 8.4 版本变化说明（`ChangeSet`）

描述 baseline 与 candidate 的变化：

- changed files
- diff artifact
- prompt/tool/skill/model/config changes
- capability tags
- user risk note
- provenance

它只描述“变了什么”，不直接决定“要测什么”。后一个问题属于 SelectionPlan。

### 8.5 版本化用例（`TestCase`）

可版本化的最小回归意图：

- Stimulus
- Fixture Requirement
- Expectations/Rubric
- Evaluator Policy
- Coverage Description
- Provenance
- DRAFT / APPROVED / DEPRECATED

用例内容需要版本化，确保历史评测仍然能找到当时使用的输入、预期和规则。

### 8.6 用例集合（`TestSuite`）

TestCase 版本的可复用集合。

它只是便于复用和批量选择，不复制 TestCase 内容。

### 8.7 用户评测意图（`EvaluationRequest`）

用户或 CI 的原始评测意图：

- Project/Target
- ChangeSet
- 用户目标
- 风险偏好
- 时间/成本预算
- 评测范围负责人（`control_owner`）

它允许保留自然语言和不完整信息，不能直接交给执行器。

### 8.8 可审查的选案计划（`SelectionPlan`）

评测范围负责人形成的可审查测试范围：

- selected/excluded cases
- selection reasons
- coverage gaps
- estimated cost/time
- confidence
- 范围负责人及其来源记录

它保存“为什么选这些、为什么排除那些”，供用户确认；确认前仍可以修改。

### 8.9 已确认执行清单（`RunSpec`）

经确认后不可变：

- 评测范围负责人引用（`ControlOwnerRef`）
- TestCase/TestSuite 版本
- Baseline/Candidate Revision
- 单次运行限制（`ExecutionPolicy`）
- SimulationPolicy
- EvaluationPolicy
- Timeout/Retry/Concurrency
- Gating Eligibility
- SelectionPlan 引用

它是评测范围负责人与执行内核的交接边界。之所以确认后不可修改，是为了防止运行过程中用例、
版本或规则悄悄变化。

### 8.10 一次完整评测任务（`EvaluationJob`）

一次完整评测的顶层对象：

- EvaluationRequest
- RunSpec
- 评测范围负责人
- Assignment 引用
- Run/Evidence/Evaluation 引用
- Approval 引用
- 当前状态

RunSpec 是静态清单，EvaluationJob 是它的运行实例；只有后者需要进度、取消、恢复和失败
状态，所以两者不能合并。

### 8.11 子 Agent 工作单（`Assignment`）

Agent 协作任务：

- capability
- from/to identity
- input/output schema
- artifact refs
- deadline/budget
- accepted/blocked/completed/rejected

它只在后续 Managed/AgentTeams 版本需要。MCP v1 的应用服务可以直接工作，不必为了形式
提前制造 Assignment。

### 8.12 执行层级：`Run`、`CaseRun`、`Attempt`

- Run：一个 TargetRevision 执行一个 RunSpec。
- CaseRun：Run 中一个 TestCase 的结果。
- Attempt：CaseRun 的一次具体尝试。

分三层是为了准确表达“某个版本整体执行”“其中一个用例”“这个用例的第几次尝试”。
重试只新增 Attempt，不覆盖旧证据。

### 8.13 工具环境缺口（`SimulationRequest`）

描述工具环境缺口：

- ToolCall/Arguments
- Tool Contract
- Scenario Context
- Session State
- Existing Samples
- Required Constraints

它是执行器发现缺口后发出的结构化请求，防止智能模拟在执行过程中暗中生成数据。

### 8.14 已冻结工具环境（`SimulationSnapshot`）

冻结、内容寻址、可回放：

- 匹配规则
- Tool Result
- 前置状态
- StatePatch
- 顺序/消耗约束
- Schema/Constraint Validation
- Provenance
- Creator/Approver
- Hash/Version
- Gating Eligibility

Snapshot 与动态 Candidate 分开，是为了保证只有经过 Schema、状态和来源校验的环境才能
进入正式门禁，并让 baseline/candidate 使用完全相同的工具世界。

### 8.15 事件与不可变产物（`Event` / `Artifact`）

Event 是追加写事实；Artifact 是不可变大对象。

- Event 回答“何时发生了什么”，适合恢复状态机和审计。
- Artifact 保存“发生时产生的完整内容”，例如长 Trace、报告或 Snapshot。

二者分开是为了避免把大对象重复写进事件流，也避免只保存文件却无法恢复过程状态。

关键 Event：

- EvaluationRequested
- SelectionPlanProposed
- RunSpecApproved
- AssignmentCreated/Completed
- SimulationRequested
- SimulationSnapshotFrozen
- Run/AttemptStarted
- ToolCalled/Returned
- EvidenceReady
- JudgeCompleted
- GateRecommended
- ApprovalRecorded

关键 Artifact：

- ChangeSet
- SelectionPlan
- Transcript
- Tool Trace
- Log/Metrics
- SimulationSnapshot
- EvidenceBundle
- SemanticEvaluation
- EvaluationReport
- RegressionCandidate

### 8.16 评测报告（`EvaluationReport`）

包含：

- RuleEvaluationResult
- SemanticEvaluation
- Baseline/Candidate Diff
- Failure Classification
- Evidence 引用
- Simulation Provenance
- Limitations

报告负责汇总和解释，不代表系统已经批准发布。

### 8.17 发布建议与最终决定（`GateRecommendation` / `ReleaseDecision`）

- GateRecommendation：确定性 Gate Policy 的 PASS/BLOCK/NEEDS_REVIEW 建议。
- ReleaseDecision：Human 或外部受信 Policy 的最终记录。

两者不能合并。

分开后，AgentRig 可以坚定地指出风险并建议 BLOCK，但最终是谁批准、基于什么组织策略批准，
仍由 Human 或受信 CI Policy 留下独立责任记录。

---

## 9. EvaluationJob 状态机

```text
DRAFT
  │
  ▼
PLANNING
  ├── insufficient context ─────► WAITING_FOR_INPUT
  └── SelectionPlan ready
  │
  ▼
WAITING_FOR_SCOPE_APPROVAL（按 Policy 可跳过）
  ├── rejected ─────────────────► CANCELLED
  └── approved
  │
  ▼
SUBMITTED
  │
  ▼
PREFLIGHT
  ├── invalid ──────────────────► REJECTED
  ├── simulation gap ───────────► WAITING_FOR_SIMULATION
  │                                  │
  │                                  ▼
  │                            SNAPSHOT_READY
  └──────────────────────────────────┘
  │
  ▼
CALIBRATING（可选，NON_GATING）
  ├── gap/conflict ─────────────► WAITING_FOR_SIMULATION
  └── stable
  │
  ▼
RUNNING
  ├── retryable infra ──────────► RETRY_SCHEDULED ─► RUNNING
  ├── fatal ────────────────────► FAILED
  └── evidence ready
  │
  ▼
AWAITING_JUDGMENT
  ├── evidence gap ─────────────► NEEDS_REVIEW / DIAGNOSTIC_REQUESTED
  └── evaluation ready
  │
  ▼
GATE_EVALUATING
  │
  ▼
COMPLETED / BLOCKED / NEEDS_REVIEW
```

规则：

- 状态转换由 Application Service 执行。
- Agent 只能提出 Command，不能直接写状态。
- 每次重试产生新 Attempt/Assignment。
- Calibration 结果标记 NON_GATING。
- Worker 超时不会删除已有 Artifact。
- Controller 取消后，所有未开始 Assignment 被取消，运行中的任务按 Policy 终止。

---

## 10. 统一执行架构

### 10.1 两个正交端口

#### ConversationDriver

如何启动和继续被测 Agent：

- Remote Session
- In-process
- Command/Subprocess
- Imported Trace

#### ToolBoundary

如何观察和控制工具调用：

- External Tool Loop
- MCP Proxy
- Observe Only
- No Tool

```text
ExecutionContext =
  ExecutionBinding（如何接入）
  + ExecutionPolicy（本次限制）
  + SimulationSnapshot（本次工具环境）
```

`ExecutionBinding` 绑定 ConversationDriver、ToolBoundary 和环境隔离方式；`ExecutionPolicy`
只保存本次运行的超时、最大轮数、重试和并发。这样不会用一个含义宽泛的 Profile 同时承担
长期接入配置和单次执行限制。

Transport 和 Proxy 不再是两套独立 Runner。

### 10.2 Execution Engine

唯一执行器负责：

1. 校验 RunSpec。
2. 创建 Run/CaseRun/Attempt。
3. 由接入绑定、运行限制和快照构造隔离的 ExecutionContext。
4. 驱动 AgentTarget。
5. 调用 ToolBoundary。
6. 记录 Event、Trace 和 Metrics。
7. 保存 Artifact/Provenance。
8. 输出不可变 EvidenceBundle。

不负责：

- 选择用例。
- 修改 Fixture。
- 调用 LLM 决定流程状态。
- 语义判断。
- 发布。

### 10.3 并发与隔离

- 每个 Run 独立 Simulation Session 和 Trace Context。
- 不使用进程全局变量切换 Mock Policy。
- Attempt 不共享可变会话状态。
- 外部写工具默认禁用或沙箱化。
- 并发、限流和超时由 ExecutionPolicy 控制。

---

## 11. 工具环境架构

### 11.1 Tool Simulation Engine

确定性服务，负责：

- Fixture/Replay/Real Provider 路由。
- Snapshot 加载和内容 Hash 校验。
- Schema/硬约束校验。
- StatePatch 应用。
- 顺序和消耗次数。
- Provenance 记录。
- Simulation Gap 输出。

### 11.2 结果来源

| 来源 | 说明 | 可门禁 |
|---|---|---|
| FIXTURE | 人工编写并冻结 | 是 |
| REPLAY | 已批准真实脱敏 Sample | 是 |
| REAL | 真实工具 Pass-through | 按 Policy |
| SYNTHETIC | Agent 动态生成候选 | 否 |
| FROZEN_SYNTHETIC | 校验、批准并冻结 | 是，必须展示来源 |

### 11.3 解析顺序

1. 精确 Fixture。
2. Approved Replay。
3. 允许的 Real Pass-through。
4. 输出 SimulationRequest。

动态 Agent 生成不是隐藏 fallback。

### 11.4 Stateful Snapshot

Snapshot 不只是 `tool_name → result`，还必须包含：

- 参数匹配条件
- 前置状态
- StatePatch
- 后续可见实体
- 调用顺序
- 消耗次数

例如 `create_project` 后，后续 `list_projects` 必须能看到同一项目。

### 11.5 防止自证循环

- 模拟 Trace 不进入真实 Sample 库。
- Sample 必须引用真实 Run 和 Tool Result。
- 合成内容记录模型、Prompt、参数和 Hash。
- Gate 报告展示来源占比。
- Fixture 不能根据 Candidate 行为临时修改预期。
- baseline/candidate 必须绑定同一 Snapshot 版本。

---

## 12. Evaluation 与 Gate

### 12.1 确定性 Rule Evaluator

- Schema Validity
- Expected/Forbidden Tool
- Argument Constraint
- Tool Order
- Text/Structured Output
- Error/Timeout
- Latency/Cost Budget
- Security Policy

### 12.2 Evidence Judge

语义维度：

- Task Completion
- Rubric Fulfillment
- Baseline Regression
- Failure Classification
- Evidence Sufficiency

### 12.3 结论分层

```text
Rule Result + SemanticEvaluation
                 │
                 ▼
         EvaluationReport
                 │
                 ▼
      Deterministic Gate Policy
                 │
                 ▼
        GateRecommendation
                 │
                 ▼
       Human / CI ReleaseDecision
```

### 12.4 Gate 原则

- 明确安全规则失败立即 BLOCK。
- 基础设施错误不等于 Agent 回归。
- 关键项 INCONCLUSIVE 不得自动 PASS。
- Judge 不能单独放行高风险发布。
- A/B 使用相同 Case、Snapshot 和 EvaluationPolicy。
- 每个结论引用 Evidence 和 Evaluator 版本。

---

## 13. 子 Agent 调用协议

### 13.1 Assignment Envelope

```json
{
  "schema_version": "1",
  "evaluation_job_id": "ej_...",
  "assignment_id": "as_...",
  "capability": "simulation.freeze_snapshot",
  "from": "agentrig-regression-manager",
  "to": "agentrig-simulation-curator",
  "status": "ready",
  "artifact_refs": [
    "artifact://simulation-request/sr_..."
  ],
  "requested_output": "SimulationSnapshot@1",
  "deadline": "2026-07-28T12:00:00Z"
}
```

### 13.2 Worker 响应

Worker 必须返回：

- accepted
- blocked
- completed
- rejected

不能只发“我处理好了”。

### 13.3 冲突处理

- Simulation 无法可信生成：返回 NEEDS_REAL_SAMPLE。
- Rule 与 Judge 冲突：明确安全规则优先；其他情况转 INCONCLUSIVE。
- 多 Judge 冲突：按 EvaluationPolicy 进行复核或转人工。
- Worker 超时：Scheduler 可重派；不由 Manager 自行篡改任务状态。
- Agent 越权：拒绝操作并记录 AuditEvent。

### 13.4 预算

Assignment 必须包含：

- timeout
- max retries
- max model calls
- token/cost class
- deadline
- priority

Manager 不得无限派生诊断任务。

---

## 14. Skill 与 MCP

### 14.1 三层关系

- Skill：告诉 Agent 何时调用、如何判断和失败时怎么办。
- MCP Tool：稳定、结构化、可鉴权的系统能力。
- Application Service：执行事务、幂等、状态机和业务规则。

Skill 不直接访问数据库。

### 14.2 External CC/Codex Skills

| Skill | 用途 |
|---|---|
| discover-regression-cases | 根据 diff 查询用例和覆盖 |
| author-regression-case | 构建或修改用例草稿 |
| harvest-tool-samples | 获取真实脱敏样本 |
| run-agent-regression | 提交 RunSpec 和跟踪 Job |
| inspect-regression-result | 阅读 Evidence/Judge/Gate |

### 14.3 Regression Manager Skills

- understand-evaluation-request
- analyze-change-impact
- select-regression-scope
- estimate-evaluation-plan
- coordinate-evaluation-job
- request-human-review
- summarize-evaluation-result

### 14.4 Simulation Curator Skills

- resolve-simulation-request
- build-stateful-fixture
- validate-simulation-candidate
- freeze-simulation-snapshot
- request-real-sample

### 14.5 Evidence Judge Skills

- evaluate-run-evidence
- compare-baseline-candidate
- classify-regression
- assess-evidence-sufficiency
- summarize-evidence

### 14.6 MCP 能力分组

#### Catalog

- catalog.search_cases
- catalog.get_case
- catalog.get_coverage
- catalog.find_by_change
- catalog.get_suite

#### Planning

- planning.create_selection_plan
- planning.validate_selection_plan
- planning.submit_run_spec

#### Simulation

- simulation.search_samples
- simulation.create_request
- simulation.submit_candidate
- simulation.validate_candidate
- simulation.freeze_snapshot

#### Evaluation

- evaluations.get_job
- evaluations.list_assignments
- evaluations.cancel_job
- evaluations.retry_attempt
- evaluations.get_report

#### Evidence

- evidence.get_bundle
- evidence.get_trace
- evidence.compare_runs
- evidence.export_capsule

#### Governance

- approvals.request
- approvals.decide
- gate.get_recommendation
- releases.record_decision

---

## 15. 数据、共享状态与证据

### 15.1 数据分层

| 层 | 内容 |
|---|---|
| Metadata DB | Project、Case、RunSpec、Job、Assignment、状态 |
| Event Store | 追加写领域事件 |
| Artifact Store | Trace、Snapshot、Evidence、Report |
| Metrics Store | 延迟、成本、通过率、漂移指标 |
| Audit Store | 权限、审批、Override、Agent 调用 |

### 15.2 不可变性

- RunSpec 提交后不可修改。
- Snapshot 冻结后内容寻址。
- EvidenceBundle 生成后不可覆盖。
- Judge 重跑产生新 SemanticEvaluation。
- Gate 重算保留 Policy 版本和旧结果。

### 15.3 关联 ID

全链路至少传播：

- project_id
- evaluation_request_id
- evaluation_job_id
- assignment_id
- run_id
- case_run_id
- attempt_id
- trace_id
- artifact_id

### 15.4 数据生命周期

- Draft Candidate 可按 Policy 清理。
- Approved Case/Snapshot 保留版本历史。
- Evidence 和 Audit 按项目保留策略归档。
- 敏感真实 Sample 必须脱敏、审批并限制用途。

---

## 16. 权限、安全、审批与审计

### 16.1 最小权限矩阵

| Identity | Catalog | RunSpec | Simulation | Evidence | Gate | Release |
|---|---|---|---|---|---|---|
| CC/Codex | 读/草稿 | 创建 | 请求 | 读 | 读 | 无 |
| Regression Manager | 读 | 创建 | 请求 | 读摘要 | 读 | 无 |
| Simulation Curator | 读必要字段 | 无 | 候选/冻结受限 | 读必要上下文 | 无 | 无 |
| Evidence Judge | 读 | 读 | 读 Provenance | 只读 | 无 | 无 |
| Human Reviewer | 读 | 批准 | 批准 | 读 | Override 受限 | 决定 |
| Execution Service | 读 | 读 | 只读 Snapshot | 写原始 Evidence | 无 | 无 |

### 16.2 高风险动作

需要显式确认：

- 扩大执行范围到全量或高成本 Suite。
- 允许真实写工具。
- 批准 FROZEN_SYNTHETIC 进入门禁。
- 修改 Gate Policy。
- 发布 Override。
- 删除或缩短 Evidence/Audit 保留期。

### 16.3 Agent 输入防护

- Trace、工具结果和外部文档均视为不可信数据。
- Artifact 内容不能覆盖系统/Skill 指令。
- Agent Tool 参数由 Schema 校验。
- 输出进入 Application Service 前再次验证。

### 16.4 审计

记录：

- 谁选择了哪些用例及理由。
- 谁批准 RunSpec。
- 哪个 Agent/模型/Skill 生成 Candidate。
- Snapshot 如何冻结。
- Judge 使用的 Evidence 和版本。
- Gate Policy 版本。
- Human Override 理由。

---

## 17. 可观测性与可靠性

### 17.1 三类轨迹

1. **User/Controller Trace**：用户、CC 或 Manager 的评测命令。
2. **Agent Collaboration Trace**：Assignment、Agent 调用、Artifact 交接。
3. **Target Execution Trace**：被测 Agent 的消息、工具调用、结果和错误。

三类轨迹通过 EvaluationJob 关联，但展示上必须区分。

### 17.2 Metrics

- Selection precision/recall
- Full-suite reduction ratio
- Missed regression rate
- Simulation source distribution
- Snapshot reuse rate
- Judge INCONCLUSIVE rate
- Agent assignment success/timeout rate
- Run latency/cost
- Gate block rate
- Human override rate

### 17.3 可靠性

- Application Command 使用幂等键。
- Agent Assignment 使用租约和心跳。
- 重试产生新 Attempt，不复用半完成状态。
- Artifact 先落盘再发完成事件。
- AgentTeams/Matrix 不作为唯一状态存储。
- LLM/Agent 不可用时，Core Mode 仍可运行。

---

## 18. 推荐配置模板

本节给出的 Profile 只是方便用户选择的一组默认配置，不进入领域模型，也不表示四种互斥的
系统形态。系统最终会把模板展开成 `control_owner`、`enabled_capabilities` 和
`deployment_profile` 三类明确配置。

### 18.1 本地基础模板

```text
Human / CLI / CI / CC
          │
          ▼
AgentRig Core
Frozen Fixture/Replay
Deterministic Execution
Rule Evaluation
SQLite + Local Artifact
```

- 无 AgentTeams。
- 无 LLM。
- 默认开源体验。

展开后相当于：

```yaml
control_owner: external_coding_agent | human_or_ci
enabled_capabilities: []
deployment_profile: local
```

### 18.2 本地智能模板

```text
AgentRig Core
  + Simulation Curator Provider
  + Evidence Judge Provider
```

- 可由 CC/Codex 或 Human/CI 控制。
- 不强制 AgentTeams。

展开后是在本地基础模板上增加 `simulation_curator` 和 `evidence_judge`。这两个能力可以
独立开关，不要求同时启用。

### 18.3 Web 助手模板

```text
AgentRig Web
Evaluation Assistant
Regression Manager
Simulation Curator
Evidence Judge
AgentRig Core
```

- 用户通过 Web 对话。
- Agent Runtime 可以先用本地实现。

该模板把 `control_owner` 设置为 `agentrig_manager`，但是否使用 AgentTeams 仍由
`agent_coordination` 能力决定。

### 18.4 多 Agent 协作模板

```text
Human via Web/Element
        │
AgentTeams
  Regression Manager
  Simulation Curator
  Evidence Judge
  Future Workers
        │ Skill + MCP
AgentRig API/MCP
        │
Deterministic Core
```

- 用于比赛和团队协作。
- AgentTeams 是 Coordination Adapter，不进入 Domain 类型。

### 18.5 生产部署不是能力模板

- Agent Coordination Plane 与 Core 独立部署。
- PostgreSQL + 对象存储 + Event/Metrics 后端。
- Execution Worker 水平扩展。
- Gateway 统一鉴权、限流、路由和凭证。
- OTel 导出到用户选择的观测后端。

这些变化只把 `deployment_profile` 设置为 `production`，不会自动改变 `control_owner`，
也不会自动打开 LLM、Evidence Judge 或 AgentTeams。

---

## 19. 端到端闭环

### 19.1 Managed Evaluation 闭环

```text
用户输入评测目标
  → Regression Manager 形成 SelectionPlan
  → 用户/Policy 批准
  → RunSpec
  → Simulation Curator 准备 Snapshot
  → Execution Engine 跑 baseline/candidate
  → Rule Evaluator + Evidence Judge
  → EvaluationReport
  → GateRecommendation
  → Human/CI Decision
```

### 19.2 失败学习闭环

```text
失败 Run / 生产 Trace
  → RegressionCandidate
  → Regression Curator（未来）
  → Simulation Curator 重建环境
  → Evidence Judge 验证可复现性
  → CC/Codex 或 Manager 构建用例草稿
  → Human 批准
  → Catalog
```

平台不能自动把一次失败直接升级为正式门禁用例。

---

## 20. 比赛方案映射

| 赛道要求 | 本架构 |
|---|---|
| 3+ 不同职能 Agent | Regression Manager + Simulation Curator + Evidence Judge |
| AgentTeams 基点 | Agent Coordination Plane + AgentTeams Adapter |
| 任务拆解 | SelectionPlan + Assignment |
| 上下文传递 | Artifact Ref + Assignment Envelope |
| 工具调用 | Skill → MCP → Application Service |
| 结果验证 | Rule Evaluator + Evidence Judge |
| 执行证据 | Event/Trace/Metrics/EvidenceBundle |
| 异常处理 | Job 状态机 + NEEDS_REAL_SAMPLE + INCONCLUSIVE |
| 审批与审计 | Approval + AuditEvent |
| 经验沉淀 | RegressionCandidate → Catalog |
| Skill | 每个 Identity 的版本化 Skill |
| 共享状态 | EvaluationJob/Assignment Repository |
| 轨迹可观测 | Controller/Agent/Target 三类 Trace |

比赛展示使用 Managed + AgentTeams Profile；开源默认体验仍可使用 External CC/Codex + Core。

---

## 21. 分阶段实施

### Phase 0：架构拍板

- 确认双控制模式。
- 确认 Regression Manager/Simulation Curator/Evidence Judge。
- 确认 RunSpec 是统一控制边界。
- 建立 ADR。

### Phase 1：统一事实模型

- Project/AgentTarget/TargetRevision
- TestCaseVersion/TestSuiteVersion
- RunSpec/EvaluationJob
- Run/CaseRun/Attempt
- SimulationRequest/SimulationSnapshot
- Event/Artifact/EvidenceBundle
- EvaluationReport/Decision

### Phase 2：统一执行

- 唯一 Execution Engine。
- ConversationDriver + ToolBoundary。
- Run 级隔离。
- 持久化 Job/Run，消除接口层全局状态。

### Phase 3：工具环境

- SimulationRequest/Snapshot。
- Calibration → Freeze → Gating。
- Stateful Snapshot。
- Simulation Curator Skill/MCP。

### Phase 4：Judge 与 Gate

- RuleEvaluationResult。
- SemanticEvaluation。
- Evidence Judge。
- Recommendation/Decision 分层。

### Phase 5：External CC/Codex Mode

- Catalog/Coverage/Search MCP。
- Author/Run/Inspect Skills。
- 示例业务 Agent。

### Phase 6：Managed Web Mode

- Evaluation Assistant Chat。
- ChangeSet Adapter。
- EvaluationRequest。
- SelectionPlan Preview。
- Regression Manager。
- Approval/Progress/Evidence UI。

### Phase 7：AgentTeams

- Identity/Skill/权限包。
- Assignment。
- Agent Registry 和 Assignment Scheduler。
- Manager + 2 Worker 最小链路。
- 异常和人工介入 Demo。

### Phase 8：专业子 Agent

- Regression Curator。
- RCA Analyst。
- Adversarial Scenario。
- Safety/Performance/Drift。

---

## 22. 第一阶段：MCP v1 最小可运行切片

第一版只证明 CC/Codex 可以通过 MCP 完成可信、可恢复、可审计的评测闭环，不把 Web
助手和多 Agent 调度提前塞进首版：

1. 建立一个 Project、一个 AgentTarget 和 baseline/candidate 两个 TargetRevision。
2. 准备 10-20 个已批准、带 Coverage Description 的版本化 TestCase。
3. CC/Codex 读取仓库和 Git diff，通过 MCP 查询 Catalog、Coverage 和历史 Evidence。
4. CC/Codex 选择用例，必要时创建用例草稿或导入真实 Tool Sample。
5. 用户确认高风险操作后，CC/Codex 提交不可变 RunSpec。
6. Simulation Curator Workflow 对一个缺失 Fixture 构建候选、执行确定性校验并冻结
   SimulationSnapshot；未满足冻结条件时不得进入门禁执行。
7. 唯一 Execution Engine 使用同一 Snapshot 执行 baseline/candidate。
8. Rule Evaluator 与 Evidence Judge Workflow 基于不可变 EvidenceBundle 产生评测结果。
9. Gate Service 输出 BLOCK/ALLOW/REVIEW 建议，Human/CI 单独记录最终 Decision。
10. CC/Codex 获取 Evidence Capsule，定位失败、修改被测项目并重跑受影响用例。
11. 服务重启后，EvaluationJob、Run、Evidence 和 Decision 仍可查询和审计。

该切片证明：

- External Coding Agent 能独立完成发现、执行、检查和修复闭环。
- MCP 只是稳定控制协议，状态和业务规则都在 AgentRig Core。
- 模拟结果先验证、后冻结，baseline/candidate 共享同一快照。
- Judge 只基于 Evidence，Gate Recommendation 与最终 Decision 分离。
- 长任务、取消、重试、失败分类和重启恢复具备工程可用性。

Managed Evaluation 是第二阶段切片：在 MCP v1 验收稳定后，增加 EvaluationRequest、
ChangeSet、SelectionPlan、Regression Manager 和 Web Evaluation Assistant。它们仍然只负责
生成同一种 RunSpec，并复用第一阶段的执行、模拟、证据、评测和 Gate 能力，不重写 Core。

---

## 23. 验收指标

### 23.1 Regression Manager

- SelectionPlan 每个用例都有理由。
- 在标准 ChangeSet 数据集上的用例召回率。
- 相对全量 Suite 的执行缩减率。
- 高风险覆盖缺口不得静默忽略。
- 信息不足时能够降级或请求输入。

### 23.2 Simulation Curator

- Snapshot Schema/状态一致性通过率。
- baseline/candidate Snapshot 一致率 100%。
- 未冻结 Synthetic 进入 Gating 的数量为 0。
- NEEDS_REAL_SAMPLE 的拒绝准确性。

### 23.3 Evidence Judge

- 每个结论的 Evidence 引用完整率。
- 基础设施错误误判为 Agent 回归的比例。
- INCONCLUSIVE 校准质量。
- 与人工 Gold Set 的一致性。

### 23.4 系统

- CC/Codex 与 Managed Mode 对同一 RunSpec 的执行一致性。
- Job/Assignment 恢复率。
- 取消、超时、重试和人工介入可审计。
- Core 在无 LLM/AgentTeams 时可运行。

---

## 24. 已确认决策

1. AgentRig 提供 External CC/Codex 和 AgentRig Managed 两种控制模式。
2. 两种模式通过不可变 RunSpec 汇合到同一个 Core。
3. AgentRig Web 主对话对象是 Evaluation Assistant，不是被测 Agent。
4. Evaluation Assistant 的 Agent Identity 是 Regression Manager。
5. Regression Manager 在 Managed 模式中负责选案和子 Agent 编排。
6. CC/Codex 模式中 Regression Manager 不参与范围控制。
7. 首批 Worker 为 Simulation Curator 和 Evidence Judge。
8. 后续专业 Agent 通过 Capability Registry 注册。
9. Agent 通过结构化 Assignment/Artifact 交接。
10. Execution、Evidence、Rule、Gate 和审计保持确定性。
11. 智能模拟必须冻结后才能用于正式门禁。
12. AgentTeams 是可替换的协作运行时，不进入 Domain Core。

---

## 25. 待评审问题

1. Regression Manager 第一版读取完整 diff，还是只读取 ChangeSet Summary。
2. SelectionPlan 哪些风险级别必须人工批准。
3. CC/Codex 模式是否允许平台提供“建议追加用例”，以及如何避免抢控制权。
4. Managed 模式的 Coverage Index 第一版采用标签映射、文件映射还是语义检索。
5. Agent Runtime 第一版直接接 AgentTeams，还是先实现本地 Adapter。
6. SimulationSnapshot 使用事件脚本还是状态图表达。
7. FROZEN_SYNTHETIC 的自动批准边界。
8. Judge 采用单次、重复采样共识还是 pairwise baseline 模式。
9. Agent Registry 的版本选择和回滚策略。
10. Regression Curator 何时从 Skill 升级为独立 Worker。
11. Human Review 是嵌入 Web，还是同时映射到 AgentTeams/Element。
12. Controller 切换是否只允许创建新 Job，还是允许在 PLANNING 阶段移交。

---

## 26. 一句话心智模型

```text
CC/Codex 或 AgentRig Evaluation Assistant 决定“测什么”；
Simulation Curator 决定“怎样构造可信环境”；
Execution Engine 负责“确定性地跑”；
Evidence Judge 判断“证据说明什么”；
Gate Policy 和 Human/CI 决定“能否发布”。
```
