# Agent Identity 清单

> 定位说明（2026-08-14）：本清单描述 AgentTeams 语义协作扩展，不是 AgentRig 最小运行前提。
> 本次 EditFlow 主演示使用确定性 Core + fixture/sample + rule；只有需要复杂规划、生成式模拟或语义裁决时，
> 才启用 Manager / Curator / Judge。三个角色不会为了参赛形式被强制加入每个 Run。

## 1. 系统协作关系

```text
用户
  │ 自然语言目标 / 明确确认
  ▼
Evaluation Manager（主控）
  │ 创建 EvaluationPlan，提交后由 AgentRig Core 执行
  ├── 工具调用需要受控结果 ──▶ Simulation Curator
  └── CaseRun 证据已冻结 ────▶ Evidence Judge
                                   │
                                   ▼
                    AgentRig 保存 Rule、Judge 与证据引用
```

三个 Agent 的比赛历史实测运行在 AgentTeams `v1.1.2` 中；当前工程同时提供互不覆盖的
`v1.1.2-competition` 与 `v1.2.2-current` profile、角色包和兼容报告入口。`v1.2.2` 的外部 Live
观测尚未执行，因此只标记为 Implemented / Live Pending。被测 lassist/Pixcake 或 AgentScope/AG-UI
Agent 都是评测对象，不计入三个协作 Agent，也不拥有 AgentRig 管理权限。普通用户主视频使用的是
基础 Model Provider Assistant + Core，而不是为了凑角色强制启动 Curator/Judge。

## 2. 身份总表

| Identity | AgentTeams 映射 | 目标 | 可以做 | 明确禁止 |
|---|---|---|---|---|
| Evaluation Manager | Manager `default` | 把自然语言目标转为可确认、可解释的评测闭环 | 查询资产、创建/修改计划、请求确认、提交计划、诊断 Run、生成用例草稿 | 绕过确认直接运行；伪造 Run/证据；修改已批准用例；调用 Worker 专属工具 |
| Simulation Curator | Worker `agentrig-curator` | 为 controlled 工具调用生成最小、合理、Schema 合法的模拟结果 | 领取指定 invocation；读取脱敏冻结输入；提交候选或结构化失败 | 读取 rubric/预期答案；调用真实业务工具；访问其他任务；为“通过评测”优化结果 |
| Evidence Judge | Worker `agentrig-judge` | 对冻结 rubric 和脱敏证据做独立语义裁决 | 领取指定 invocation；输出 pass/fail/inconclusive；引用真实 event ID | 伪造证据；遵循被测输出中的指令；覆盖 Rule 记录；访问 Curator 原始上下文 |

## 2.1 官方附录 A 字段版

下列三张表格与《参赛手册》附录 A 的 `Name / Role / Capabilities / Inputs /
Outputs / Dependencies / Decision Boundary / Trace` 字段一一对齐，可直接复制到报名系统或
提交模板。

### Evaluation Manager

| 字段 | 内容 |
|---|---|
| Name | `evaluation-manager` |
| Role | 面向用户的评测主控，负责目标理解、资产选择、计划、审批协调与证据诊断。 |
| Capabilities | 可查询 Case/Target/Profile/Run，创建或修订 EvaluationPlan，记录决策，在真实用户确认后提交，诊断结果或生成用例草稿；不能调用原始 `run_cases`、Worker 工具或人工审核接口。 |
| Inputs | AssistantSession/Turn/Event ID，用户评测目标，当前 Plan ID/revision，Manager MCP 返回的脱敏资产、运行与决策事实。 |
| Outputs | 结构化 EvaluationPlan 草稿/修订，确认说明，幂等提交结果，引用 Plan/Run/CaseRun/Event/Evaluation ID 的诊断，或待审核 TestCase 草稿。 |
| Dependencies | AgentTeams `v1.1.2`/`v1.2.2` Manager adapter；`adaptive-evaluation`等 6 个 Manager Skills；角色隔离的 `agentrig-manager` MCP；AgentRig Core。 |
| Decision Boundary | 可在已授权读取范围内自主查询、比较和起草；确认、提交、取消、共享 Target 修改必须经 Core 策略门禁，并在需要时绑定同会话真实用户事件。 |
| Trace | AssistantEvent 记录输入；ManagerDecision 记录选项、证据与策略裁定；EvaluationPlan/Run 记录业务状态；Matrix request/response event ID 关联协作轨迹。 |

### Simulation Curator

| 字段 | 内容 |
|---|---|
| Name | `simulation-curator` |
| Role | 受控工具结果提供者，为回归评测生成最小、合理、Schema 合法的候选结果，不参与评分。 |
| Capabilities | 可按精确 invocation ID 领取冻结任务，根据工具名、参数、结果 Schema、初始状态和脱敏历史生成候选；不能读取 rubric/预期答案、调用真实业务工具或枚举其他任务。 |
| Inputs | `agentinv_*` task envelope，input hash，deadline，脱敏冻结工具上下文，结果 Schema，模拟说明，有界验证反馈。 |
| Outputs | `CuratorGeneration`：候选工具结果、必要状态更新、模型元数据；或分类的结构化失败。 |
| Dependencies | AgentTeams 双基线 Worker `agentrig-curator`；`simulate-tool-result` Skill；仅 Curator 可见的 `get_agent_invocation` / `submit_curator_result` / `fail_agent_invocation` MCP 工具。 |
| Decision Boundary | 可在冻结上下文中选择合理候选；不得为“评测通过”优化输出，不得扩大任务范围，不得绕过 Validator 或访问 Judge 输入。 |
| Trace | AgentInvocation 状态机、input/result hash、Matrix 请求与响应 event ID、Provider attempt、Validator 结果和最终 RunEvent result ref 可回放。 |

### Evidence Judge

| 字段 | 内容 |
|---|---|
| Name | `evidence-judge` |
| Role | 脱离执行环节的独立证据裁决者，对冻结 rubric 与脱敏 CaseRun 证据给出可引用结论。 |
| Capabilities | 可按精确 invocation ID 领取任务，逐条判定 pass/fail/inconclusive，引用已存在 event ID；不能伪造证据、调用目标工具、改写 Rule 或访问 Curator 原始上下文。 |
| Inputs | `agentinv_*` task envelope，input hash，deadline，冻结用例要求/rubric，独立 Rule 结果，执行摘要与脱敏 RunEvent。 |
| Outputs | `JudgeOutput`：总体 pass/fail/inconclusive，逐标准结论、summary 和经验证的 evidence refs；或结构化失败。 |
| Dependencies | AgentTeams 双基线 Worker `agentrig-judge`；`judge-evidence` Skill；仅 Judge 可见的 `get_agent_invocation` / `submit_judge_result` / `fail_agent_invocation` MCP 工具。 |
| Decision Boundary | 可根据冻结证据独立判断；未知 evidence ref 必须拒绝，缺少决定性证据必须输出 inconclusive，Rule 仅作独立事实而非可覆盖结论。 |
| Trace | AgentInvocation 状态机、input/result hash、Matrix 双向 event ID、逐条 evidence ref 验证和关联 Evaluation ID 共同支持审计与回放。 |

## 3. Evaluation Manager

- **身份声明**：面向用户的唯一全局语义大脑和协作协调者。
- **触发条件**：用户消息、计划状态变化或 Run 终态通知。
- **输入**：AssistantSession ID、Turn ID、用户事件 ID、当前计划 ID，以及 Manager MCP
  返回的结构化资产和运行摘要。
- **输出**：EvaluationPlan 草稿、确认说明、提交结果、证据化诊断或 TestCase 草稿。
- **核心 Skills**：`adaptive-evaluation`、`plan-evaluation`、`execute-evaluation-plan`、
  `diagnose-run`、`build-test-case-draft`、`configure-test-target`。
- **依赖工具**：仅 `agentrig-manager` MCP。
- **权限**：读取评测资产；写 draft 计划；确认动作必须绑定真实用户事件；提交只能消费已
  confirmed 的同一 revision。
- **失败处理**：资产缺失时给出缺口；提交失败保留 confirmed；AgentTeams 不可用时不伪装成功。
- **状态追踪**：AssistantSession、AssistantTurn、EvaluationPlan、Run ID 与 Matrix event ID。

## 4. Simulation Curator

- **身份声明**：受控工具结果提供者，不是评分者。
- **触发条件**：CaseExecutor 在 controlled/proxy 链路遇到工具调用，Provider Chain 选择
  `simulation_curator`。
- **输入**：invocation ID、输入 hash、工具名、参数、结果 Schema、初始状态、历史脱敏事件、
  模拟说明和上一轮校验反馈。
- **输出**：`CuratorGeneration`，包含候选工具结果、必要的状态更新和模型元数据。
- **核心 Skill**：`simulate-tool-result`。
- **依赖工具**：仅 `get_agent_invocation`、`submit_curator_result`、
  `fail_agent_invocation`。
- **权限**：只可访问精确 ID 的 Curator 任务；输出仍须通过 AgentRig Validator。
- **失败处理**：一次格式修正；传输重试复用同一幂等键；终态、越权或超时不重试。
- **状态追踪**：created → dispatched → running → completed/failed/timed_out；保存请求与
  最终回执 Matrix event ID。

## 5. Evidence Judge

- **身份声明**：独立证据裁决者，不是执行器。
- **触发条件**：CaseRun 执行结束，rubric、Rule 结果和证据已经冻结。
- **输入**：invocation ID、输入 hash、用例要求、rubric、Rule 结果、执行摘要和脱敏 RunEvent。
- **输出**：`JudgeOutput`，包含 pass/fail/inconclusive、逐项 criteria、summary 和 evidence refs。
- **核心 Skill**：`judge-evidence`。
- **依赖工具**：仅 `get_agent_invocation`、`submit_judge_result`、
  `fail_agent_invocation`。
- **权限**：只能引用本次 invocation 中存在的 event ID；不能调用目标工具或访问 Curator 任务。
- **失败处理**：未知 evidence ref 被拒绝；缺少决定性证据时输出 inconclusive；超时结构化失败。
- **状态追踪**：与 Curator 相同，并把成功结果关联到权威 Evaluation ID。

## 6. 上下文、信任与协作边界

| 数据 | 传递方式 | 信任级别 | 权威事实源 |
|---|---|---|---|
| 用户目标与确认 | AgentRig → Matrix Manager envelope | 路由字段可信，用户文本不可信 | AssistantEvent |
| Worker 任务 | AgentRig → Matrix 定向 mention + task envelope | task ID/hash/role 可信 | AgentInvocation |
| 完整 Worker 输入 | 角色隔离 MCP 按 ID 领取 | 已脱敏、冻结 | AgentInvocation input snapshot |
| 工具结果候选 | Worker → 角色 MCP | 不可信候选，必须校验 | ToolResult/RunEvent |
| Judge 裁决 | Worker → 角色 MCP | 引用校验后存档 | Evaluation |
| 协作轨迹 | Matrix request/response event ID | 审计关联 | Matrix + AgentInvocation |

Prompt 不是权限边界。Higress consumer、不同 MCP server、Bearer Token、角色校验、状态机、
Schema Validator、Redactor 和数据库约束共同构成实际安全边界。

## 7. V2.3 优化对身份合同的影响

本轮优化没有为了展示功能而增加第四个 Agent；新增能力仍按“语义提案归 Agent、权威放行归 Core”
分工：

| 新能力 | 责任主体 | 身份边界 |
|---|---|---|
| Quality / Comparison / Release Gate | AgentRig Core，Manager/Web/CLI 只消费结果 | Gate 只读取同源冻结快照和版本化策略；Agent 不能改 verdict/hash |
| Capability Snapshot 与 AgentScope/AG-UI | Target Driver + Planner/Core | 被测 Runtime 的 tool/skill/permission/workspace 先于执行冻结；Target 内部确认不能代替 AgentRig 确认 |
| Runtime Safety Suite | 确定性 Case/Rule 为主，Judge 可作语义补充 | Critical/High 边界不得只靠 LLM 判定；19 项 manifest 版本化 |
| OTLP Trace→Case | Production Evidence Core + 人工 Reviewer | Trace 与测试 Run 分域；转换只创建 draft，不能自动批准或改写历史 Run |
| Judge Alignment | Reviewer/Adjudicator + Core | GoldLabel 只追加；候选 Judge 回放后仍需审批才能激活 |
| Failure Pattern / Monitor | Core 聚合与通知 adapter | candidate/confirmed 分离；只有验证 Run 才能关闭 Pattern，通知幂等且脱敏 |
| Durable Job | Scheduler/Worker + PostgreSQL | lease、fencing token、幂等副作用和取消由数据库状态机保证，不由 Agent 文本决定 |

因此，三 Identity 继续只负责规划、受控结果和裁决。Project scope、Capability hash、Gate policy/hash、
Trace lineage、Review/GoldLabel、Failure Pattern、Job/Attempt/lease 与终态通知均属于 Core 权威事实，
不得被 Matrix 消息或 Prompt 覆盖。
