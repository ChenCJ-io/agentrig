# AgentRig V2：智能评测助手与 AgentTeams 开发设计

> 状态：V2 开发基线
> 版本：1.0
> 日期：2026-08-01
> V1 基线：AgentRig `0.1.0a1`
> AgentTeams 基线：稳定版 `v1.1.2`
> 适用范围：AgentRig Web 智能助手、AgentTeams 比赛版本、后续开源 Managed 模式
> 替代文档：`design-history/AgentRig-V2-智能评测助手与AgentTeams-完整架构方案-v0.1.md`

本文是 V2 的直接开发、评审和验收依据。`design-history/` 中的 V2 文档只用于追溯讨论过程；
若历史草稿与本文冲突，以本文为准。实现中需要改变本文确定的对象语义、权限边界、执行主链或
Agent 分工时，必须先形成新的架构决策记录并更新本文，不能只在代码中改变。

外部约束：

- [GOAI 2026 Agent Infra 赛道要求](https://www.goaihz.com/tracks?track=infra)；
- [AgentTeams 官方仓库](https://github.com/agentscope-ai/AgentTeams)；
- [AgentTeams 官方架构](https://github.com/agentscope-ai/AgentTeams/blob/main/docs/architecture.md)。

---

## 0. 最终结论

AgentRig V2 不重写 V1。V2 在 V1 已有的测试资产、执行器和证据系统之外，增加一个用户可直接
对话的智能评测助手，并通过 AgentTeams 运行一个主 Agent 和两个专业 Worker。

三个 Agent 先按 AgentRig 的业务职责、输入输出和权限边界设计，再映射到 AgentTeams：

| AgentRig 业务角色 | AgentTeams 身份 | 核心职责 |
|---|---|---|
| 智能评测助手 | Manager Agent | 理解目标、查询资产、生成计划、提交运行、组织专业能力、解释结果 |
| Simulation Curator | Worker Agent | 在运行时根据受限上下文生成结构化模拟工具结果 |
| Evidence Judge | Worker Agent | 根据冻结要求和脱敏证据生成可引用证据的语义评判 |

本方案确定以下开发原则：

1. AgentTeams Manager 就是 V2 的智能评测助手运行身份，不在 AgentRig 内再建设一套重复的主
   Agent 模型循环。
2. AgentRig 保存助手会话、执行计划、Run、CaseRun、Evidence 和 Evaluation，是产品业务事实的
   唯一来源。
3. AgentTeams 保存 Agent 身份、任务分派、Matrix 消息、Worker 状态和协作轨迹，是协作过程的
   权威来源。
4. AgentRig 与 AgentTeams 并行部署，通过角色隔离的 MCP、Matrix 和一个薄的 AgentTeams Adapter
   集成，不把 AgentTeams 类型写入 V1 Domain。
5. Manager 通过 AgentRig MCP 使用业务能力；Curator/Judge 通过专业任务桥接获取严格受限的输入并
   提交结构化输出。
6. V1 `run_cases`、Planner、Scheduler、CaseExecutor、Provider Chain、Validator、Event 和
   Evaluation 继续是唯一执行链。
7. Curator 与 Judge 抽象为稳定 Port。默认 Core 模式使用当前本地实现；Managed/比赛模式使用
   AgentTeams Worker Adapter。
8. 自研 Web 只连接 AgentRig 后端。AgentRig 后端负责把用户消息投递到 Matrix 并把 Manager 回复和
   协作状态投影回 Web，浏览器不持有 Matrix 管理凭据。
9. 第一版使用“一段 AgentRig 会话对应一个 Matrix 协作房间”，AgentTeams 的临时会话记忆不是产品
   事实库；上下文丢失时由 Manager 通过 MCP 恢复必要状态。
10. 比赛演示必须至少有一条链路让三个 Agent 都完成真实、不可替代的工作，但普通产品运行不强制每次
    调用全部 Worker。
11. AgentRig Core 在没有 AgentTeams、没有模型 Key 时仍可运行；比赛 Profile 才强制启用
    AgentTeams。
12. 第一版不建设第二套任务执行引擎、通用 Agent 调度平台、自动发布 Gate 或自动修复系统。

最终主链为：

```text
用户自然语言
  → AgentRig Assistant Session
  → Matrix Bridge
  → AgentTeams Manager（智能评测助手）
  → AgentRig Manager MCP
  → EvaluationPlan
  → V1 run_cases
  → Run / CaseRun
  → 必要时 AgentTeams Curator / Judge Worker
  → V1 Event / Evaluation
  → Manager 读取证据并解释
  → AgentRig Web
```

---

## 1. 目标、范围与非目标

### 1.1 V2 解决的问题

V1 已经允许 Codex、Claude Code、CI 或专业用户直接通过 MCP/HTTP 使用 AgentRig，但要求控制方
理解 TestCase、Target、ExecutionProfile、Provider、Evaluator、Run 和 CaseRun。

V2 要让用户只描述业务目标，例如：

> “帮我检查 9.3 版本的项目打开功能，上次失败的场景重点跑一下。”

智能评测助手应当完成：

1. 主动查询现有用例、Target、Profile、版本和历史 Run；
2. 判断哪些信息已经明确，哪些缺失会实质改变范围、成本、风险或结论；
3. 必要时追问，不把平台能够自行查询的问题退回用户；
4. 生成可查看、可编辑、可确认的结构化执行计划；
5. 通过 V1 `run_cases` 提交运行；
6. 跟踪运行，不依赖浏览器连接存活；
7. 读取规则、语义评判和原始证据，解释通过、失败、跳过或无法判断的原因；
8. 在用户要求时，把失败证据整理为新的 TestCase 草稿；
9. 用 AgentTeams 展示 Manager 与专业 Worker 的真实协作和状态。

### 1.2 第一版产品范围

第一版覆盖三个纵向闭环：

| 闭环 | 用户结果 | 优先级 |
|---|---|---:|
| 测试与诊断 | 从自然语言目标到计划、Run、证据和解释 | P0 |
| 用例构建 | 从描述或已有证据生成可审核 TestCase 草稿 | P1 |
| 配置辅助 | 查询并在权限内创建/修改 Target 与 Profile，解释兼容性 | P1 |

比赛验收优先完成“测试与诊断”闭环，并在同一条可运行链路中展示 Manager、Curator 和 Judge。

### 1.3 明确不做

V2 第一版不做：

- 第二套 Run、CaseRun、Evidence 或 Evaluation；
- 用聊天文本代替执行计划和运行快照；
- 通用 Agent Marketplace、Capability Registry 或任意 Agent 动态编排平台；
- 通用 Assignment Scheduler、租约、心跳和分布式工作队列；
- 自动修改或发布被测 Agent 代码；
- 自动批准 TestCase 或 Sample；
- 修改服务器 executable allowlist；
- 在对话、Matrix 或日志中传递明文密钥；
- 自动扩大用户或外部 Coding Agent 已经确定的测试范围；
- 为满足比赛数量而把普通函数、队列或规则包装成 Agent；
- 整套引入 Agno AgentOS 或再建设一套与 AgentTeams 重叠的 Session/Trace/Eval；
- V2 第一版的多租户组织、细粒度项目 RBAC 和跨组织 Matrix 联邦。

### 1.4 第一版运行假设

- AgentRig 继续是单实例模块化单体，Scheduler 与 Proxy Scope 仍在进程内；
- PostgreSQL 是 Managed/比赛部署的推荐数据库，SQLite 继续用于本地 Core 体验；
- 第一版按单工作区/管理员语义设计，但所有表保留 `workspace_id` 扩展位置；
- 每个 AssistantSession 对应一个独立 Matrix room；
- Manager 和两个 Worker 在部署期创建，不在每次用户请求时动态创建；
- AgentTeams 不可用时，Web 智能助手不可用，但 V1 MCP、HTTP、人工 Web 和已提交 Run 继续工作。

---

## 2. 术语与职责边界

### 2.1 Agent

本文中的 Agent 必须同时具备：

- 明确身份和目标；
- 独立的模型判断；
- 有边界的上下文；
- 明确的 Skill 和工具权限；
- 结构化输入输出；
- 自主决策边界和人工确认边界；
- 可追踪的任务状态和结果。

确定性 Planner、Scheduler、Validator、RuleEvaluator 和消息投递器不是 Agent。

### 2.2 AgentTeams

AgentTeams 是外部多 Agent 协作运行平台，负责 Manager/Worker 生命周期、Matrix 通信、共享文件、
Higress 网关、协作状态和人工介入。它不替代 AgentRig 的领域模型和评测执行。

### 2.3 Skill

Skill 是可复用的任务方法，使用 `SKILL.md` 和可选的 `scripts/`、`references/`、`assets/` 描述：

- 何时触发；
- 需要什么输入；
- 按什么步骤调用哪些工具；
- 成功标准；
- 失败、重试和降级；
- 权限与安全边界；
- 输出结构。

Skill 不重新实现 MCP 服务，也不保存业务事实。

### 2.4 MCP

MCP 是 Agent 调用 AgentRig 原子业务能力的协议边界。Manager、Curator 和 Judge 使用不同的
MCP 入口和凭据，不能共用全权限工具集。

### 2.5 被测 Agent

Target 指向的被测 Agent 是评测对象，不属于 AgentTeams 的三个协作 Agent，也不计入比赛的三个
Agent 身份。它只能通过现有 Driver/MCP Proxy 进入 CaseRun。

### 2.6 两种调度

系统必须区分：

1. 语义调度：Manager 决定测什么、采用什么 Profile、是否启用 Curator/Judge；
2. 确定性调度：V1 Planner/Scheduler 展开 CaseRun，控制并发、超时、取消和执行顺序。

Manager 是评测大脑，但不管理线程、队列或 Driver 状态机。

---

## 3. V1 复用基线

V2 必须复用 V1 `0.1.0a1` 的以下对象和能力：

| V1 对象/服务 | V2 用途 | V2 是否改变原语义 |
|---|---|---:|
| TestCase / CaseTurn / Tag | 计划选案、用例构建 | 否 |
| Target / TargetVersion | 选择被测 Agent 和版本 | 否 |
| ExecutionProfile | 工具模式、Provider、评判、并发和超时 | 否 |
| Sample / Fixture | 可重复工具结果 | 否 |
| Run / CaseRun | 实际执行事实 | 否 |
| RunEvent | 脱敏执行证据 | 否 |
| Evaluation | Rule/Judge/External 独立评判 | 否 |
| RunPlanner | 解析选择、版本、能力并冻结快照 | 仅提取可复用预览逻辑 |
| RunScheduler / CaseExecutor | 异步执行和状态管理 | 否 |
| Provider Chain | Fixture/Sample/Curator/Real Tool 降级 | 只替换 Curator Port 实现 |
| Evidence Judge | 语义评判 | 只替换 Judge Port 实现 |
| HTTP / MCP / Web | 人工、外部 Agent 和 CI 入口 | 保持兼容并新增 V2 入口 |

V1 当前直接在 `bootstrap.py` 装配本地 `SimulationCurator` 与 `EvidenceJudge`。V2 只把两者提取为
Port 并增加 AgentTeams Adapter，不改变已有输入输出 Schema、Validator、Evaluation 存档或
Provider 降级语义。

### 3.1 三种控制方式继续并存

| 模式 | 控制方 | 是否经过 AgentTeams Manager | 适用场景 |
|---|---|---:|---|
| Core MCP | Codex / Claude Code | 否 | 开发中结合代码和 diff 做回归 |
| Managed Web | 用户 + AgentTeams Manager | 是 | 自然语言计划、执行和诊断 |
| HTTP / CI | 人工配置或流水线 | 否 | 固定自动化流程 |

三种入口共享 V1 事实和执行链。Managed Web 不能改变另外两种模式的行为。

---

## 4. 总体架构

```text
┌──────────────────────────────────────────────────────────────────────┐
│                           用户入口                                   │
│ AgentRig Web Assistant │ Codex/Claude MCP │ HTTP/CI │ 人工管理界面   │
└───────────────┬─────────────────────┬───────────────┬────────────────┘
                │                     │               │
                ▼                     │               │
┌───────────────────────────────────┐ │               │
│       AgentRig V2 应用层          │ │               │
│ AssistantSession / Event / Turn   │ │               │
│ EvaluationPlan / Policy / SSE     │ │               │
│ Matrix Bridge / Agent Invocation  │ │               │
└───────────────┬───────────────────┘ │               │
                │ Matrix              │               │
                ▼                     │               │
┌───────────────────────────────────┐ │               │
│      AgentTeams 协作运行平台       │ │               │
│ Manager：智能评测助手              │ │               │
│ ├─ Worker：Simulation Curator      │ │               │
│ └─ Worker：Evidence Judge          │ │               │
│ Matrix / Higress / MinIO / Trace   │ │               │
└───────────────┬───────────────────┘ │               │
                │ 角色隔离 MCP         │               │
                └───────────┬─────────┴───────────────┘
                            ▼
┌──────────────────────────────────────────────────────────────────────┐
│                     AgentRig V1 Core                                │
│ Catalog │ Planner │ Scheduler │ Executor │ Provider │ Evaluation    │
│ Run / CaseRun │ Event / Evidence │ Driver │ MCP Proxy              │
└───────────────────────────────┬──────────────────────────────────────┘
                                ▼
┌──────────────────────────────────────────────────────────────────────┐
│                    被测 Agent 与业务工具系统                          │
│ AgentScope/Pixcake │ Goose/ACP │ OpenAI-compatible │ 自定义 Driver   │
└──────────────────────────────────────────────────────────────────────┘
```

### 4.1 AgentRig V2 应用层

负责产品事实和集成：

- 保存助手会话、消息投影、回合和执行计划；
- 提供 V2 HTTP/SSE API；
- 把 Web 消息可靠投递到 Matrix；
- 把 Manager 回复和协作事件投影回 Web；
- 提供角色隔离的 MCP；
- 创建并关联专业 Agent Invocation；
- 执行权限、确认、幂等和脱敏策略；
- 将计划提交到 V1 `run_cases`；
- 不运行第二套模型 Agent 循环。

### 4.2 AgentTeams 协作层

负责：

- 运行一个可定制的 Manager 和两个 Worker；
- 加载 AgentRig 自定义 Skill；
- 通过 Higress 为不同身份配置模型和 MCP 权限；
- 通过 Matrix 传递任务、进度、结果和人工干预；
- 保存完整协作轨迹；
- 管理 Agent 容器生命周期和健康状态；
- 使用 MinIO/OSS 保存 AgentTeams 自身的共享任务文件。

AgentTeams 的 Matrix 和 MinIO 不保存 AgentRig 的权威 TestCase、Plan、Run、Event 或 Evaluation。

### 4.3 V1 Core

继续负责：

- 用例、Target、Profile、Sample 的业务规则；
- 版本展开、能力检查和快照冻结；
- Run/CaseRun 调度、超时和取消；
- Driver、MCP Proxy 和 Provider Chain；
- 统一 Validator、事件脱敏和证据落库；
- Rule、Evidence Judge、External 三类评判存档；
- 重启时中断状态处理。

---

## 5. 三个 Agent 的完整定义

### 5.1 Manager：智能评测助手

#### 身份

唯一直接面向用户的评测领域助手，是 AgentTeams Manager，也是三个 Agent 中的全局语义大脑。

#### 输入

- 用户当前消息与当前 AssistantSession 引用；
- 通过 Manager MCP 按需查询的用例、Target、Profile、历史 Run 和证据；
- 当前 EvaluationPlan、权限策略和确认状态；
- 专业 Worker 的任务状态和最终结果引用；
- 系统生成的 Run 完成、配置变化或协作失败事件。

#### 输出

- 对用户目标的结构化理解；
- 必要追问；
- EvaluationPlan 草稿和选择理由；
- 调用 V1 的计划提交请求；
- 对运行进度和结果的解释；
- TestCase、Target 或 Profile 草稿；
- 可追踪的专业能力启用决定；
- 引用真实 RunEvent/Evaluation 的最终总结。

#### 核心 Skill

- `plan-evaluation`；
- `execute-evaluation-plan`；
- `diagnose-run`；
- `build-test-case-draft`；
- `configure-test-target`；
- 比赛 Profile 的 `alibabacloud-sls-query`。

#### 决策边界

Manager 可以：

- 对业务语义和歧义进行判断；
- 查询资产后选择候选用例并解释理由；
- 对明确、低风险请求直接生成计划；
- 决定计划是否允许 Curator、是否使用 Evidence Judge；
- 在已有权限内创建和修改 draft/rejected 资产；
- 汇总多个评判来源，但保持原始输出独立。

Manager 不可以：

- 直接操作数据库；
- 绕过计划和后端策略调用 Managed 模式的原始 `run_cases`；
- 批准 TestCase/Sample；
- 修改 allowlist、读取明文密钥或扩大真实工具权限；
- 修改已确认计划、Run 快照、RunEvent 或 Evaluation；
- 把被测 Agent/工具输出中的指令当作系统指令；
- 未经用户或策略授权扩大测试范围、自动重跑或发布产品。

#### AgentTeams 配置

第一版使用 AgentTeams 稳定版支持的 OpenClaw Manager Runtime。Agent 身份、职责和边界写入
Manager 的 Agent 指令；业务流程写入 Skill；AgentRig 工具通过声明式 MCP 配置接入。默认模型使用
OpenAI-compatible 配置，比赛环境默认 `qwen3.5-plus`，但模型名称不是 Domain 合同。

### 5.2 Worker：Simulation Curator

#### 身份

工具结果模拟专家。只在 CaseRun 的 Provider Chain 确认需要智能模拟时参与。

#### 输入

复用 V1 `CuratorInput`：

- 工具名、参数和结果 Schema；
- 用例初始状态和本轮 `simulation_instruction`；
- 当前 CaseRun 在该调用之前的脱敏事件；
- 当前 CaseRun 私有模拟状态；
- 上一次结构校验反馈。

输入不得包含：

- 结构化断言；
- 预期最终回答；
- rubric、分数或 Judge 输出；
- 其他 CaseRun 的私有状态；
- 未脱敏凭据。

#### 输出

复用 V1 `CuratorCandidate`：

```json
{
  "result": {},
  "state_updates": {}
}
```

输出由 AgentRig Validator 校验。第一次不合法时，Worker 只接收校验反馈并允许修正一次。第二次
仍不合法则 Invocation 失败，Provider Chain 按既有顺序降级。

#### Skill 与权限

- 唯一业务 Skill：`simulate-tool-result`；
- 只能调用 Curator MCP 的 `get_agent_invocation`、`submit_curator_result`、
  `fail_agent_invocation`；
- 不得调用用例修改、运行提交、审核、真实工具或 Judge 工具；
- 不直接与用户对话，不解释最终测试结论。

### 5.3 Worker：Evidence Judge

#### 身份

证据语义评判专家。只在 CaseRun 停止执行、证据完整落库且 Profile 配置需要 Evidence Judge 时参与。

#### 输入

- 冻结 TestCase 和逐轮 rubric；
- CaseRun 执行状态和错误；
- Rule Evaluation；
- 脱敏 RunEvent；
- 合法 Evidence ID 集合；
- 上一次输出校验反馈。

#### 输出

复用 V1 `JudgeOutput`：

- `pass`、`fail` 或 `inconclusive`；
- summary；
- 逐项 criteria；
- 只引用当前 CaseRun 真实 event ID 的 `evidence_refs`。

未知 Evidence 引用会触发一次修正；第二次仍无效时保存独立的 Evaluation Error，不能转换为测试
失败，也不能覆盖 Rule/External 评判。

#### Skill 与权限

- 唯一业务 Skill：`judge-evidence`；
- 只能调用 Judge MCP 的 `get_agent_invocation`、`submit_judge_result`、
  `fail_agent_invocation`；
- 不能启动或取消 Run，不能修改 rubric 或证据；
- 不直接向用户给出最终平台结论。

### 5.4 哪些组件不是 Agent

以下组件必须继续使用确定性代码：

- 选案查询、版本组合展开和计划预览；
- Run/CaseRun 并发、超时、取消和状态机；
- Driver request/session 管理；
- Provider 顺序和降级；
- JSON Schema、大小和敏感字段校验；
- Rule 断言；
- Evidence ID 合法性验证；
- 事件脱敏、落库和幂等；
- 权限、确认和密钥策略；
- Matrix 投递、重试、去重和游标推进。

---

## 6. Skill 设计

### 6.1 目录

V2 在现有 `skills/core/` 之外增加：

```text
skills/
├── core/                              # 现有外部 Coding Agent Skills
├── manager/
│   ├── plan-evaluation/
│   │   └── SKILL.md
│   ├── execute-evaluation-plan/
│   │   └── SKILL.md
│   ├── diagnose-run/
│   │   └── SKILL.md
│   ├── build-test-case-draft/
│   │   └── SKILL.md
│   └── configure-test-target/
│       └── SKILL.md
└── workers/
    ├── simulate-tool-result/
    │   ├── SKILL.md
    │   └── references/output-schema.json
    └── judge-evidence/
        ├── SKILL.md
        └── references/output-schema.json
```

比赛部署另外从阿里云官方来源安装并锁定 `alibabacloud-sls-query`，不把第三方内容复制成
AgentRig 自有 Skill。

### 6.2 Skill 最低合同

每个 Skill 必须声明：

- 唯一名称、版本和触发描述；
- 适用 Agent 身份；
- 必要输入和输出 Schema；
- 可调用的 MCP 工具白名单；
- 逐步流程、分支和停止条件；
- 成功标准；
- 可重试与不可重试错误；
- 权限、确认和提示词注入边界；
- 至少一个正常样例和一个失败样例；
- 与其他 Agent/Skill 的关系。

### 6.3 Skill 与代码的边界

- Skill 负责“什么时候做、按什么方法做”；
- MCP Tool 负责执行原子业务操作；
- Pydantic/后端代码负责 Schema、权限和状态转换；
- AgentTeams 负责 Agent 身份和协作；
- Skill 不能通过脚本直接写 AgentRig 数据库；
- Skill 中不得包含 API Key、Matrix Token、环境真实路径或审批绕过说明。

---

## 7. MCP 与权限分面

### 7.1 保留外部 MCP

现有 `/mcp/` 保持兼容，继续面向 Codex/Claude Code 等外部控制方，工具集和 V1 行为不因 V2 改变。

### 7.2 新增角色隔离 MCP

V2 新增三个独立入口：

```text
/mcp/manager/
/mcp/curator/
/mcp/judge/
```

每个入口创建独立 FastMCP 实例、工具注册表和鉴权 Principal。不能只在 Prompt 中要求 Worker
“不要调用其他工具”。

#### Manager MCP

第一阶段提供：

```text
会话与计划:
  get_assistant_context
  create_evaluation_plan
  update_evaluation_plan
  validate_evaluation_plan
  confirm_evaluation_plan
  cancel_evaluation_plan
  submit_evaluation_plan

资产只读:
  list_tags
  list_test_cases
  get_test_case
  find_cases_by_tool
  list_targets
  get_target
  check_target
  list_execution_profiles
  get_execution_profile
  list_samples

运行与证据:
  get_run
  list_case_runs
  get_case_run
  list_case_run_events
  cancel_run

草稿写入（阶段二/三）:
  create_test_case
  update_test_case
  create_target
  update_target
  create_execution_profile
  update_execution_profile
```

Managed 模式不向 Manager 暴露原始 `run_cases`。`submit_evaluation_plan` 完成确认、权限、幂等和
资产重校验后，才在服务端调用 V1 `run_cases`。

Manager 永远不获得：

- TestCase/Sample 审核；
- Sample approved 状态修改；
- approved TestCase 修改；
- allowlist 和明文 Secret；
- 数据库、任意文件或 Shell；
- 绕过计划的运行入口。

#### Curator MCP

```text
get_agent_invocation(invocation_id)
submit_curator_result(invocation_id, result, idempotency_key)
fail_agent_invocation(invocation_id, error_code, message, retryable)
```

#### Judge MCP

```text
get_agent_invocation(invocation_id)
submit_judge_result(invocation_id, result, idempotency_key)
fail_agent_invocation(invocation_id, error_code, message, retryable)
```

专业端点不提供任务列表。Worker 只能通过不可预测的 Invocation ID 读取与自己角色相符、尚未终止的
任务。

### 7.3 Principal 与凭据

后端至少识别：

```text
external_controller
web_user
agentteams_bridge
agentteams_manager
agentteams_curator
agentteams_judge
```

每个 AgentTeams 身份使用独立 Higress consumer 和 AgentRig Bearer Token。配置只保存
`env:VARIABLE_NAME` 引用。AgentRig 根据入口和 Principal 双重校验工具权限；即使 Higress 配错，
Worker 也不能越权。

### 7.4 MCP 调用关联

所有 V2 MCP 调用必须附带或显式传入可关联 ID：

- `assistant_session_id`；
- `assistant_turn_id`；
- `evaluation_plan_id`；
- `agent_invocation_id`；
- `run_id` / `case_run_id`。

审计日志只保存工具名、Principal、结果状态、耗时和资源引用，不重复记录完整敏感输入输出。

---

## 8. Agent Port 与 AgentTeams Adapter

### 8.1 稳定 Port

在 `src/agentrig/agents/ports.py` 定义：

```python
class SimulationCuratorPort(Protocol):
    async def generate(
        self,
        value: CuratorInput,
        *,
        model_config: ModelConfigRef,
        timeout_seconds: float,
        context: AgentInvocationContext,
    ) -> CuratorGeneration: ...


class EvidenceJudgePort(Protocol):
    async def evaluate(
        self,
        detail: CaseRunDetail,
        *,
        rule_result: EvaluationResult | None,
        model_config: ModelConfigRef,
        timeout_seconds: float,
        context: AgentInvocationContext,
    ) -> EvaluationDraft: ...
```

`AgentInvocationContext` 只包含关联信息，不包含业务判断：

```text
assistant_session_id?
evaluation_plan_id?
run_id
case_run_id
tool_call_event_id?
attempt
```

### 8.2 两类实现

```text
SimulationCuratorPort
├─ LocalSimulationCurator       # 当前直接模型调用
└─ AgentTeamsCuratorAdapter     # 创建 Invocation，通知 Worker，等待结果

EvidenceJudgePort
├─ LocalEvidenceJudge           # 当前直接模型调用
└─ AgentTeamsJudgeAdapter       # 创建 Invocation，通知 Worker，等待结果
```

V1 Domain 和 CaseExecutor 只依赖 Port，不导入 Matrix、AgentTeams Controller 或 Higress SDK。

### 8.3 AgentTeams Adapter 模块

```text
src/agentrig/integrations/agentteams/
├── client.py             AgentTeams 健康/资源查询的薄客户端
├── matrix_client.py      建房、发消息、sync、去重
├── bridge.py             AssistantEvent 与 Matrix Event 双向投影
├── dispatcher.py         专业 Invocation 通知和关联
├── curator.py            SimulationCuratorPort 实现
├── judge.py              EvidenceJudgePort 实现
├── schemas.py            任务信封与外部引用
└── errors.py             可分类集成错误
```

Adapter 不创建新的 Run，不决定 Provider 顺序，也不保存 Judge 的最终业务结论。

### 8.4 专业任务信封

Matrix 中只发送紧凑信封：

```json
{
  "schema_version": "1",
  "task_id": "agentinv_...",
  "task_type": "simulation_curator",
  "target_role": "agentteams_curator",
  "run_id": "run_...",
  "case_run_id": "case_run_...",
  "input_ref": "agentrig://agent-invocations/agentinv_...",
  "deadline": "2026-08-01T12:00:00Z",
  "attempt": 1
}
```

完整输入由 Worker 使用角色 MCP 按需获取；大体积事件不复制到 Matrix 或 MinIO。

### 8.5 Invocation 状态机

```text
created → dispatched → running → completed
    │          │           ├──→ failed
    │          │           ├──→ timed_out
    │          │           └──→ cancelled
    │          ├──────────────→ failed
    └─────────────────────────→ cancelled
```

规则：

- `task_id` 是幂等主键；
- 同一个调用尝试只能有一个成功结果；
- 重复 `submit_*` 使用 `idempotency_key` 返回第一次结果；
- 终态不可回退；
- Worker 获取任务时从 `dispatched` 转为 `running`；
- AgentRig 在自己的组件超时到达时写 `timed_out`，迟到结果返回 conflict；
- CaseRun 取消时，尚未终止的 Curator Invocation 一并取消；
- AgentRig 重启后把运行中 CaseRun 标记 interrupted，同时把其非终态 Invocation 标记 cancelled；
- 第一版不恢复被中断的模型调用，也不自动重跑。

### 8.6 触发和路由

Manager 在 EvaluationPlan 中决定是否允许智能模拟和是否使用 Evidence Judge。V1 Core 根据准确的
运行时位置创建 Invocation：

- Provider Chain 到达 Curator 时创建 `simulation_curator` Invocation；
- CaseRun 结束且需要 Evidence Judge 时创建 `evidence_judge` Invocation。

Adapter 按固定角色路由，不再调用一个 LLM 判断“应该交给哪个 Worker”。语义选择已经由 Manager 在
计划/Profile 中完成，运行时路由属于确定性工作。

---

## 9. 助手会话、回合与 Matrix Bridge

### 9.1 会话模型

AssistantSession 表示用户围绕一个评测目标持续工作的空间。每个 Session 创建一个独立 Matrix room，
成员至少包含：

- `agentrig-bridge` 服务身份；
- AgentTeams Manager；
- 需要时加入 Curator/Judge Worker；
- 用户通过 AgentRig Web 参与，不直接获得 Matrix 管理凭据。

Session 状态：

```text
active → archived
```

第一版不支持恢复已归档 Session；可以创建新 Session 并引用旧 Plan/Run。

### 9.2 Agent 回合

每条用户消息、一次用户确认或一个 Run 终态系统事件产生一个 AssistantTurn：

```text
queued → dispatched → running → completed
                         ├──────→ failed
                         └──────→ cancelled
```

`dispatched` 表示消息已获得 Matrix Event ID；`running` 表示收到 Manager 的处理/工具活动；
`completed` 表示收到该回合最终回复。停止生成只取消当前 Turn，不取消已提交 Run。

### 9.3 消息可靠性

AgentRig 先在数据库保存用户事件和幂等键，再异步投递 Matrix：

```text
HTTP 接收消息
  → 事务内写 AssistantEvent(pending_delivery)
  → 返回 event_id / turn_id
  → Bridge 投递 Matrix
  → 保存 matrix_event_id 并标记 delivered
```

约束：

- `(session_id, client_message_id)` 唯一，浏览器重试不会创建两条消息；
- `matrix_event_id` 唯一，Matrix sync 重放不会产生两条 AssistantEvent；
- Matrix 事件按 room 和 origin timestamp 投影，但 AgentRig 使用自己的单调 `seq` 给 Web 消费；
- 投递失败使用有限指数退避，超过上限保留 failed 状态并允许用户显式重试；
- 不因 Web SSE 断开丢失任何状态。

### 9.4 上下文恢复

AgentTeams Runtime 可以清理短期模型会话，因此 Manager 不能只依赖内存或完整 Matrix 历史。
`get_assistant_context` 返回紧凑状态：

- 当前用户目标和最近用户约束；
- 活跃 EvaluationPlan 及状态；
- 关联 Run/CaseRun 汇总；
- 未解决问题和待确认项；
- 最近有效业务消息引用；
- 允许进一步查询的资源 ID。

大体积 RunEvent 仍通过分页 MCP 按需读取。

### 9.5 自研 Web 与 Element

- AgentRig Web 是正式产品入口；
- Element 只用于开发排障、比赛协作轨迹验证和人工介入；
- 正式 Web 不嵌入 Element 管理账户，不读取 Matrix Access Token；
- 用户在 Element 中的人工干预可被 Bridge 投影为 `collaboration_intervention` 事件；
- 同一 Session 中来自 Web 和 Element 的用户指令必须带来源，后端权限策略仍然生效。

---

## 10. EvaluationPlan

### 10.1 作用

EvaluationPlan 是 V2 唯一新增的评测准备对象，回答：

1. 用户想验证什么；
2. Manager 准备实际执行什么；
3. 为什么这样选择；
4. 哪些假设、风险和确认仍然存在。

Plan 不是 Run。Plan 描述准备执行的内容，Run/CaseRun 快照记录实际执行事实。

### 10.2 结构

```text
id
assistant_session_id
source_turn_id
parent_plan_id?
revision
status

goal:
  user_request
  normalized_goal
  constraints

selection:
  case_ids / selector
  selected_cases[{case_id, reason, source}]
  targets[]
  profile_id
  overrides
  repeat_count

reasoning_summary:
  assumptions[]
  unresolved_questions[]
  selection_rationale[]

preview:
  resolved_case_ids[]
  planned_case_runs
  skipped_items[]
  provider/evaluator summary
  estimated_risk

confirmation:
  required
  reasons[]
  confirmed_by?
  confirmation_event_id?
  confirmed_at?

submission:
  idempotency_key?
  run_id?
  submitted_at?
  last_error?
```

`selection` 必须能够无损转换为 V1 `RunCasesRequest`，不能创造第二套运行表达。

### 10.3 状态机

```text
draft ──confirm──→ confirmed ──submit──→ submitted
  │                    │
  └────cancel──────────┴──────────────→ cancelled
```

规则：

- draft 可由 Manager 和用户修改；
- confirmed 内容冻结，任何调整都基于原计划创建新 revision；
- submitted 必须关联唯一 `run_id`；
- cancelled 不可提交；
- 提交失败不把计划伪装为 submitted，保持 confirmed 并保存结构化 `last_error`；
- 同一 Plan 的重复 submit 使用 idempotency key 返回同一个 Run；
- 用户取消 Plan 与取消已存在 Run 是两个动作。

### 10.4 预览和提交

V2 从 V1 Planner 提取共享的只读解析步骤，形成 `RunPreparationService`：

```text
prepare(RunCasesRequest)
  → 解析 case/selector
  → 合并 Target/Profile/overrides
  → 展开版本、重复和 A/B
  → 检查 Driver/Provider/Evaluator
  → 返回 PreparedRun（不落 Run）
```

Plan 预览使用 `PreparedRun`。V1 `run_cases` 也复用同一准备逻辑后再创建 Run/CaseRun 和冻结快照，
避免 V2 复制版本与能力规则。

提交前必须重新 prepare。若资产 revision、审核状态、权限或兼容性与确认时不一致：

- 不创建 Run；
- 返回 `plan_stale` 或具体业务错误；
- confirmed Plan 保持冻结；
- Manager 基于旧 Plan 创建新 draft 向用户说明变化。

### 10.5 确认策略

后端返回三种裁决：

```text
allow
require_confirmation
deny
```

Manager 负责理解语义，后端强制执行底线：

| 场景 | 默认裁决 |
|---|---|
| 明确范围的只读查询 | allow |
| 明确范围、无真实工具、数量在阈值内的普通模拟运行 | allow 或项目策略确认 |
| Manager 根据语义自行选择一批用例 | require_confirmation |
| A/B、大批量、高重复或超过成本阈值 | require_confirmation |
| Real Tool | require_confirmation 且必须满足部署/Profile allowlist |
| 修改共享 Target/Profile | require_confirmation |
| 删除共享资产 | deny（第一版 Manager 不具备工具） |
| 批准 TestCase/Sample | deny |
| 明文密钥、修改服务器 allowlist | deny |

自然语言确认必须关联真实用户事件。Manager 不能自己生成一句“已确认”作为授权。

---

## 11. 数据模型与事实归属

### 11.1 新增表

V2 在 V1 的 11 张表之外新增六张表：

```text
assistant_sessions
assistant_events
assistant_turns
evaluation_plans
agent_invocations
integration_cursors
```

不增加 EvaluationJob、RunSpec、SelectionPlan、Artifact Store 或通用任务队列表。

### 11.2 `assistant_sessions`

| 字段 | 类型/约束 | 说明 |
|---|---|---|
| `id` | string PK | `asst_...` |
| `workspace_id` | string，默认 `default` | 预留工作区边界 |
| `title` | string | 会话标题 |
| `status` | `active/archived` | 会话状态 |
| `matrix_room_id` | nullable unique string | 对应 Matrix room |
| `active_plan_id` | nullable string | 当前工作计划引用，不做事实复制 |
| `last_event_seq` | integer | AgentRig Web 单调事件序号 |
| `created_by` | string | 创建 Principal |
| `created_at/updated_at` | datetime | 审计时间 |

### 11.3 `assistant_events`

这是 Web 可恢复事件流和 Matrix 投影，不是完整原始 Matrix 存档。

| 字段 | 类型/约束 | 说明 |
|---|---|---|
| `id` | string PK | `asstevt_...` |
| `session_id` | FK | 所属会话 |
| `seq` | integer，`(session_id, seq)` unique | Web 顺序 |
| `event_type` | enum | 见下方 |
| `actor_type/actor_id` | string | user/manager/worker/system |
| `payload` | JSON | 脱敏后的 UI 投影 |
| `turn_id` | nullable FK | 关联回合 |
| `plan_id/run_id/case_run_id/invocation_id` | nullable string | 资源关联 |
| `client_message_id` | nullable string | 浏览器幂等键 |
| `matrix_event_id` | nullable unique string | Matrix 去重和跳转 |
| `delivery_status` | enum | local/pending/delivered/failed |
| `delivery_attempts/last_error` | integer/string | 投递恢复 |
| `created_at` | datetime | 创建时间 |

事件类型第一版固定为：

```text
user_message
assistant_message
assistant_activity
plan_created
plan_updated
plan_confirmed
plan_submitted
run_status
agent_invocation_status
collaboration_intervention
system_notice
error
```

模型 Token 流不逐 Token 落库。前端流式展示可使用临时 delta，完成后只保存最终
`assistant_message`，避免数据库膨胀和断线后重放半条回复。

### 11.4 `assistant_turns`

| 字段 | 说明 |
|---|---|
| `id` | `asstturn_...` |
| `session_id` | 所属会话 |
| `trigger_event_id` | 用户/系统触发事件 |
| `status` | queued/dispatched/running/completed/failed/cancelled |
| `matrix_request_event_id` | 投递请求 |
| `matrix_response_event_id` | 最终响应 |
| `started_at/finished_at` | 生命周期 |
| `error_code/error_message` | 分类错误 |
| `model_metadata` | 只保存模型、Token、耗时等非敏感摘要 |

同一 `trigger_event_id` 只能创建一个 Turn。

### 11.5 `evaluation_plans`

| 字段 | 说明 |
|---|---|
| `id` | `plan_...` |
| `session_id/source_turn_id` | 来源 |
| `parent_plan_id/revision` | 不可变 revision 链 |
| `status` | draft/confirmed/submitted/cancelled |
| `goal` | JSON |
| `selection` | 可转换为 `RunCasesRequest` 的 JSON |
| `reasoning_summary` | 假设、问题、选择理由 |
| `preview` | `PreparedRun` 的用户投影 |
| `confirmation` | 是否需要确认及真实事件引用 |
| `selection_hash` | 确认时内容校验 |
| `submit_idempotency_key` | nullable unique |
| `run_id` | nullable unique |
| `last_error` | nullable JSON |
| `created_by/confirmed_by` | Principal |
| `created_at/updated_at/confirmed_at/submitted_at` | 时间 |

### 11.6 `agent_invocations`

这是 AgentRig 与 AgentTeams 的最小关联和生命周期投影，不是通用 Agent 调度系统。

| 字段 | 说明 |
|---|---|
| `id` | `agentinv_...` |
| `agent_role` | simulation_curator/evidence_judge |
| `status` | created/dispatched/running/completed/failed/timed_out/cancelled |
| `session_id/plan_id` | nullable关联 |
| `run_id/case_run_id` | 运行关联 |
| `tool_call_event_id` | Curator 可选关联 |
| `attempt` | 校验修正尝试 |
| `input_snapshot` | 已脱敏、已冻结的专业输入 |
| `input_hash` | 审计校验 |
| `result_payload` | Worker 提交后、Core 消费前的短暂持久化中转；建立结果引用后清空 |
| `result_ref` | ProviderAttempt/Evaluation 等权威结果引用 |
| `result_hash` | 输出校验摘要，不复制权威完整结果 |
| `matrix_room_id/request_event_id/response_event_id` | 协作轨迹引用 |
| `assigned_agent` | AgentTeams Worker 身份 |
| `deadline` | 组件超时边界 |
| `idempotency_key` | 结果提交去重 |
| `error_code/error_message/retryable` | 分类错误 |
| `created_at/started_at/finished_at` | 时间 |

`input_snapshot` 必须经过 V1 Redactor；Worker 输出先持久化以支持断线恢复，Core 校验并写入
RunEvent/Evaluation 后清除 `result_payload`，Invocation 最终只保存引用和 Hash。

### 11.7 `integration_cursors`

| 字段 | 说明 |
|---|---|
| `integration` | PK，例如 `agentteams_matrix` |
| `cursor` | Matrix `/sync` since token |
| `metadata` | 非敏感状态 |
| `updated_at` | 更新时间 |

游标只能在当前批次 Matrix 事件全部幂等落库后推进。

### 11.8 事实来源

| 问题 | 权威来源 |
|---|---|
| 用户在 AgentRig Web 说了什么 | AssistantEvent |
| Manager/Worker 的完整协作消息 | AgentTeams Matrix |
| Web 应显示哪条协作摘要 | AssistantEvent 投影 |
| 助手准备执行什么 | EvaluationPlan |
| 实际执行了什么 | Run/CaseRun 快照 |
| 执行中发生了什么 | RunEvent |
| 各评判器如何判断 | Evaluation |
| 专业任务生命周期与外部引用 | AgentInvocation |
| AgentTeams 共享文件 | AgentTeams MinIO/OSS，仅为协作产物 |

---

## 12. HTTP、SSE 与前端合同

### 12.1 V2 HTTP API

统一位于 `/api/v2`：

```text
POST   /assistant/sessions
GET    /assistant/sessions
GET    /assistant/sessions/{session_id}
POST   /assistant/sessions/{session_id}/archive

POST   /assistant/sessions/{session_id}/messages
GET    /assistant/sessions/{session_id}/events
GET    /assistant/sessions/{session_id}/stream
POST   /assistant/turns/{turn_id}/cancel
POST   /assistant/events/{event_id}/retry-delivery

GET    /evaluation-plans/{plan_id}
PATCH  /evaluation-plans/{plan_id}
POST   /evaluation-plans/{plan_id}/validate
POST   /evaluation-plans/{plan_id}/confirm
POST   /evaluation-plans/{plan_id}/cancel
POST   /evaluation-plans/{plan_id}/submit

GET    /agent-invocations/{invocation_id}
GET    /assistant/sessions/{session_id}/agent-invocations

GET    /agentteams/health
GET    /agentteams/collaboration/{session_id}
```

浏览器不能调用专业 Worker MCP，也不能直接提交 AgentInvocation 结果。

### 12.2 发送消息

请求：

```json
{
  "client_message_id": "uuid-from-browser",
  "content": "帮我测试项目打开相关能力",
  "active_plan_id": null
}
```

响应使用 `202 Accepted`：

```json
{
  "event_id": "asstevt_...",
  "turn_id": "asstturn_...",
  "delivery_status": "pending"
}
```

### 12.3 SSE

`GET /stream?after_seq=N` 发送：

```text
event: assistant_event
id: 42
data: {AssistantEvent JSON}
```

并定期发送 heartbeat。断线重连使用最后一个 `seq`，不依赖内存队列。第一版不建设 WebSocket；
取消、确认、编辑等动作继续使用 HTTP。

### 12.4 API 错误

沿用 V1 结构：

```json
{
  "code": "plan_stale",
  "message": "confirmed plan no longer matches current assets",
  "details": {},
  "retryable": false
}
```

V2 新增错误码至少包括：

```text
agentteams_unavailable
matrix_delivery_failed
assistant_turn_conflict
plan_confirmation_required
plan_stale
plan_already_submitted
agent_invocation_not_ready
agent_invocation_timed_out
agent_result_invalid
agent_role_forbidden
```

---

## 13. 关键时序

### 13.1 自然语言计划与运行

```text
User → Web → Assistant API
  1. 保存 user_message 和 Turn
  2. Bridge 投递到 Session Matrix room
  3. Manager 收到消息
  4. Manager 调 Manager MCP 查询资产和历史
  5. Manager 创建/更新 EvaluationPlan draft
  6. AgentRig 保存 plan 事件，Web 实时展示计划卡片
  7. 若需确认，Manager 等待用户
  8. 用户确认，后端记录 confirmation_event_id
  9. Manager 调 submit_evaluation_plan
 10. 后端重校验并调用 V1 run_cases
 11. Plan submitted 并关联 run_id
 12. Run 独立执行，Web 断开不影响
```

### 13.2 Curator Worker

```text
CaseExecutor → ProviderChain → AgentTeamsCuratorAdapter
  1. 创建 AgentInvocation(input_snapshot, deadline)
  2. 在 Matrix room @curator 投递任务信封
  3. Curator Worker 加载 simulate-tool-result Skill
  4. 调 Curator MCP 获取输入
  5. 生成 CuratorCandidate
  6. 调 Curator MCP 提交结果
  7. AgentRig 校验角色、状态、Schema、敏感字段和幂等
  8. Adapter 收到完成信号
  9. Provider 再使用统一 ToolResultValidator
 10. 合法则记录 ProviderAttempt/ToolResult 并继续 Driver
 11. 不合法则带反馈创建下一 attempt；仍失败则 Provider 降级
```

AgentTeams/Matrix 故障不得导致已落库 CaseRun 证据被修改或丢失。

### 13.3 Judge Worker

```text
CaseExecutor 完成执行证据
  1. RuleEvaluator 先保存确定性结果（如有）
  2. AgentTeamsJudgeAdapter 创建 Invocation
  3. Matrix 通知 Judge Worker
  4. Judge 通过 MCP 获取冻结 rubric、Rule 和事件
  5. 提交 JudgeOutput
  6. AgentRig 校验所有 evidence_refs
  7. 合法输出保存为 Evidence Judge Evaluation
  8. Invocation.result_ref 指向 evaluation_id
  9. Manager 读取各独立评判并向用户解释
```

### 13.4 Run 完成后的主动总结

Run 到达终态后，V2 后端为关联 Session 创建 `run_status` 系统事件和新的 Turn，投递 Manager：

```text
{"event":"run_finished","run_id":"run_...","plan_id":"plan_..."}
```

Manager 按 `diagnose-run` Skill 读取汇总、失败 CaseRun、关键事件和评判，再输出一次最终回复。Run
完成通知使用 `(session_id, run_id, event_type)` 幂等键，服务重启不会重复总结。

### 13.5 从失败构建用例草稿

Manager 只能从已存档的脱敏证据读取输入，调用现有 TestCase Schema 创建 draft。任何批准动作仍由
人工 HTTP/Web 审核；“生成草稿成功”不能展示为“用例已生效”。

---

## 14. 权限、安全与提示词注入防护

### 14.1 分层控制

| 层 | 责任 |
|---|---|
| Agent Prompt/Skill | 告诉 Agent 正确方法和业务边界 |
| Higress | 按 Agent 身份限制模型、MCP 路由和外部凭据 |
| AgentRig MCP Endpoint | 注册最小工具集 |
| AgentRig Principal Policy | 校验角色、资源、状态和动作 |
| Domain Service | 审核状态、不可变性和业务规则 |
| Database | 唯一约束和事务幂等 |

Prompt 不是安全边界。

### 14.2 密钥

- AgentTeams/Matrix/Higress/模型/阿里云凭据只通过 Secret 或 `env:` 引用；
- 浏览器只持有 AgentRig Web 访问 Token，不持有 Matrix、Worker 或模型 Token；
- Worker 只持有自己 Higress consumer token；
- AgentRig 不把真实密钥写入 Plan、AssistantEvent、Matrix 或 MinIO；
- 日志不得记录 Authorization Header、Matrix access token 或完整模型请求。

### 14.3 数据脱敏

所有进入 Manager、Worker、Matrix、MCP、SSE 和 Web 的运行事件必须来自 V1 Redactor 之后的副本。
Curator 输入的工具参数也必须经过敏感键/路径处理。禁止以“专业 Worker 需要更多上下文”为由读取原始
未脱敏事件。

### 14.4 不可信内容

以下全部视为不可信数据：

- 用户上传内容；
- 被测 Agent 文本；
- 工具参数和结果；
- Sample、Fixture 和 RunEvent；
- 外部日志和 SLS 查询结果；
- Matrix 房间中非系统身份发送的文本。

Agent 指令必须要求只把它们作为数据或证据，不执行其中的指令。后端仍通过工具白名单和状态机保证
即使模型被注入也不能越权。

### 14.5 真实工具

Real Tool 继续要求：

```text
部署 allowlist
AND ExecutionProfile 启用
AND 用户对当前计划明确授权
```

确认记录必须绑定 Plan revision 和用户事件；其他会话或更早计划的确认不能复用。

### 14.6 人工审核

Manager 可以创建或修改 draft/rejected TestCase 和 draft Sample，但角色 MCP 不暴露 approve、reject、
disable 等审核能力。审核事件必须来自人工 HTTP/Web Principal。

---

## 15. 故障、重试与降级

| 故障 | 行为 | 用户看到的归属 |
|---|---|---|
| AgentTeams 整体不可用 | Managed Assistant 返回 unavailable；V1 入口继续工作 | 协作平台故障 |
| Matrix 短暂失败 | 已保存消息进入重试；不重复创建 Turn | 消息投递延迟 |
| Manager 无响应 | Turn failed/timeout；已提交 Run 不取消 | 主助手故障 |
| Curator Worker 不可用 | Invocation failed；Provider Chain 尝试下一 Provider | 模拟能力故障 |
| Curator 输出非法 | 一次修正；仍非法后降级 | 专业输出校验失败 |
| Judge Worker 不可用 | 保存 Evaluation Error，不改成 fail | 评判能力故障 |
| Judge 引用未知事件 | 一次修正；仍非法保存 Evaluation Error | 证据引用错误 |
| Worker 重复提交 | 返回第一次结果 | 幂等命中 |
| Worker 迟到提交 | 返回 conflict，不修改终态 | 专业任务已超时 |
| AgentRig 重启 | V1 in-progress 中断；Invocation 取消；会话/计划可恢复 | 平台重启中断 |
| 浏览器断线 | Run/Matrix/Bridge 继续；重连按 seq 恢复 | 无业务故障 |
| Run 失败 | 保存真实 Run/CaseRun 错误，Manager 解释 | 执行层故障 |

重试原则：

- 只对网络投递和明确 retryable 的模型/协作错误有限重试；
- 有副作用调用必须使用幂等键；
- 不自动扩大范围、不自动创建新 Run；
- 用户请求“重跑”时生成新的 EvaluationPlan revision 和新的 Run；
- Curator 的一次格式修正沿用 V1 规则，不等同于重新执行 CaseRun。

---

## 16. 可观测、审计与比赛证据

### 16.1 统一关联链

```text
assistant_session_id
  → assistant_turn_id
    → evaluation_plan_id
      → agentteams_room_id / matrix_event_id
        → agent_invocation_id
          → run_id
            → case_run_id
              → run_event_id / evaluation_id
```

每个结构化日志和 Trace Span 至少带其中可获得的关联 ID。

### 16.2 Trace

建议 Span：

```text
assistant.turn
assistant.matrix.send
assistant.matrix.receive
manager.mcp.call
evaluation_plan.validate
evaluation_plan.submit
agent_invocation.dispatch
agent_invocation.wait
agent_invocation.validate
run.execute
case_run.execute
provider.resolve
evaluation.judge
```

第一版可以先以结构化日志实现，OTel Exporter 作为 Managed/比赛部署开关；不能为了 Trace 改写 V1
事件事实。

### 16.3 Metrics

至少统计：

- AssistantSession/Turn 数和成功率；
- 用户消息到 Manager 首次活动、最终回复的延迟；
- Plan 创建、确认、提交和 stale 数；
- Run/CaseRun 状态；
- 按 Agent 角色的 Invocation 数、耗时、失败和超时；
- MCP 工具成功率和延迟；
- Curator 校验修正率和 Provider 降级率；
- Judge inconclusive、非法引用和 Evaluation Error；
- 模型 Token/成本摘要；
- Matrix 投递积压和重试。

### 16.4 比赛官方 Skill

比赛 Profile 使用阿里云官方 `alibabacloud-sls-query` Skill。用途限定为：

- 当 Run/AgentInvocation/平台日志已发送到指定 SLS Project/Logstore 时；
- Manager 在诊断平台或 Target 集成故障时查询相关时间窗和 Trace ID；
- 查询结果作为补充诊断材料，不覆盖 AgentRig RunEvent；
- 所有查询只读，凭据由 Higress/环境注入；
- 未配置 SLS 时 Skill 明确返回 unavailable，核心测试闭环仍可完成。

比赛 Demo 必须展示一次真实、有价值的查询，不能只把 Skill 安装在目录中。

### 16.5 协作视图

Web 默认展示摘要：

- 哪个 Agent 在做什么；
- 关联哪个 Plan/Run/CaseRun；
- 状态、耗时和结果引用；
- 人工是否介入；
- 故障属于 Manager、Worker、模型、Matrix、AgentRig 还是被测 Agent。

原始 Matrix 房间用于高级排障和比赛验证，不默认向普通用户展示全部模型内部消息。

---

## 17. 部署设计

### 17.1 Core Profile

```text
AgentRig + SQLite/PostgreSQL
```

- AgentTeams 关闭；
- 外部 MCP/HTTP/Web 人工功能全部可用；
- Curator/Judge 可以关闭，或使用本地 Direct Model 实现；
- 不需要 Matrix、Higress、MinIO 或模型 Key 才能完成 Rule/Fixture/Sample 回归。

### 17.2 Managed/比赛 Profile

```text
PostgreSQL
AgentRig API/MCP/Web
AgentTeams Controller
  ├─ Higress
  ├─ Tuwunel Matrix
  ├─ MinIO
  └─ Element Web
AgentTeams Manager
AgentTeams Curator Worker
AgentTeams Judge Worker
可选 OTel/SLS Exporter
```

本地使用 Docker，生产候选使用 AgentTeams Helm/Kubernetes。第一版不要求 AgentRig 自身多副本。

### 17.3 版本固定

| 组件 | 第一版选择 |
|---|---|
| AgentTeams | `v1.1.2` stable |
| Manager Runtime | OpenClaw |
| Worker Runtime | OpenClaw |
| 模型协议 | OpenAI-compatible |
| 比赛默认模型 | `qwen3.5-plus`，可配置 |
| AgentRig 数据库 | PostgreSQL 17 推荐，SQLite 兼容 |

AgentTeams `v1.2.0-beta.1` 已完成公开名称迁移并提供插件/WorkerFlow，但不是开发基线。Adapter 和部署
文件统一使用 AgentTeams 业务命名，并把 v1.1.2 中遗留的旧环境变量/资源名限制在部署适配目录；
升级到 v1.2 stable 前必须跑完整契约和纵向回归。

### 17.4 网络

容器网络中：

```text
AgentTeams/Higress → http://agentrig:8000/mcp/manager/
Curator Worker      → http://agentrig:8000/mcp/curator/
Judge Worker        → http://agentrig:8000/mcp/judge/
AgentRig Bridge     → Matrix Client-Server API（内部地址）
```

公网只暴露 AgentRig Web/API 和必要的 HTTPS 入口。Controller API、MinIO、Matrix 管理接口、Higress
Console 和专业 MCP 不直接暴露公网。

### 17.5 配置

新增配置示意：

```toml
[assistant]
enabled = true
turn_timeout_seconds = 180
event_stream_heartbeat_seconds = 15
max_context_events = 100

[agentteams]
enabled = true
version = "v1.1.2"
matrix_base_url = "http://agentteams-controller:18080"
matrix_user = "agentrig-bridge"
matrix_token_ref = "env:AGENTTEAMS_MATRIX_TOKEN"
manager_user = "manager"
curator_user = "simulation-curator"
judge_user = "evidence-judge"
dispatch_timeout_seconds = 10

[agentteams.auth]
manager_token_ref = "env:AGENTRIG_MANAGER_TOKEN"
curator_token_ref = "env:AGENTRIG_CURATOR_TOKEN"
judge_token_ref = "env:AGENTRIG_JUDGE_TOKEN"

[agents]
runtime = "agentteams" # local | agentteams
```

所有 Secret 值只存在环境或部署 Secret 中。

---

## 18. 前端设计

### 18.1 信息架构

```text
┌──────────────┬────────────────────────────┬─────────────────────────┐
│ 会话列表     │ 对话与活动流               │ 当前工作区              │
│ 新建/归档    │ 用户/Manager 消息          │ EvaluationPlan          │
│ 标题/状态    │ 查询/工具/Agent 状态摘要   │ Run / CaseRun / Evidence│
│              │ 确认和系统事件             │ TestCase 草稿           │
└──────────────┴────────────────────────────┴─────────────────────────┘
```

窄屏使用页签切换，不删除结构化工作区。

### 18.2 必要组件

- Assistant Session 列表和新建入口；
- 消息输入、停止生成、断线重连和失败重试；
- EvaluationPlan 卡片：目标、用例、理由、Target、版本、Profile、数量、跳过、风险、确认；
- Run 进度卡和跳转到现有 Run/CaseRun 详情；
- Agent Collaboration 卡：Manager/Curator/Judge、状态、耗时、关联资源；
- TestCase 草稿结构化编辑；
- 权限/真实工具确认；
- 明确区分测试失败、评判错误、Worker 故障和平台故障。

### 18.3 前端事实规则

- Plan 卡片只读取 `evaluation_plans`，不从聊天 Markdown 解析；
- Run 状态只读取 V1 API；
- Agent 状态读取 `agent_invocations`/协作投影；
- AssistantEvent 文本中的资源 ID 自动链接到对应结构化页面；
- 前端编辑 draft Plan 后，Manager 下一回合通过 `get_assistant_context` 看到同一版本；
- 已确认/已提交 Plan 不显示原地编辑；
- 不展示或保存 Matrix Access Token、模型 Prompt 原文或未脱敏事件。

---

## 19. 代码结构

在现有模块化单体内增量增加：

```text
src/agentrig/
├── assistant/
│   ├── models.py
│   ├── schemas.py
│   ├── repository.py
│   ├── service.py
│   ├── plan_service.py
│   └── run_notifier.py
├── agents/
│   ├── ports.py
│   ├── invocation_models.py
│   ├── invocation_schemas.py
│   ├── invocation_repository.py
│   ├── invocation_service.py
│   └── invocation_coordinator.py
├── integrations/
│   └── agentteams/
│       ├── matrix_client.py
│       ├── bridge.py
│       ├── transport.py
│       └── adapters.py
├── mcp/
│   └── v2/
│       ├── manager.py
│       └── workers.py
├── infrastructure/database/repositories/
│   ├── assistant.py
│   └── agent_invocations.py
├── v2_api.py
└── bootstrap.py

web/app/
├── api/v2.ts
└── pages/v2/

skills/manager/
skills/workers/
deploy/agentteams/
scripts/build_agentteams_packages.py
tests/v2/
```

Repository 继续通过抽象接口访问 SQLAlchemy，HTTP/MCP/Bridge 不直接访问 ORM。所有装配仍集中在
`ServiceContainer.build()`。

---

## 20. 开发阶段与交付顺序

### Phase 0：AgentTeams 兼容性探针

交付：

- 固定 AgentTeams `v1.1.2`；
- 本地启动 Controller/Manager/两个 Worker；
- Manager 通过 Higress 调用 AgentRig `ping` 和只读 MCP；
- Matrix room 创建、消息投递、sync 和去重验证；
- 记录官方资源字段和旧命名适配。

退出条件：可以从 Matrix 向 Manager 发消息，并在 AgentRig 审计日志中看到带 Manager Principal 的 MCP
调用。

### Phase 1：V2 状态和计划

交付：

- 六张新表与 Alembic migration；
- AssistantSession/Event/Turn Service；
- EvaluationPlan、共享 RunPreparation 和确认策略；
- V2 HTTP/SSE；
- Manager 角色 MCP；
- Fake Matrix/Manager 的离线测试。

退出条件：没有真实 AgentTeams 时，测试可以创建会话、可靠投递假消息、生成/确认/提交计划并关联 V1
Run。

### Phase 2：Manager 纵向闭环

交付：

- AgentTeams Manager 身份、Prompt 和 Skills；
- AgentRig Matrix Bridge；
- 自然语言查询、计划、提交、运行结束总结；
- Web 对话、Plan 卡片和 Run 进度。

退出条件：用户只通过 Web 自然语言完成一次 Fixture + Rule 回归。

### Phase 3：Evidence Judge Worker

交付：

- AgentInvocation Service；
- Judge 角色 MCP、Skill、Worker 配置和 Adapter；
- Evidence ID 校验、一次修正、超时和错误存档；
- 协作视图。

退出条件：Evidence Judge 不再由 AgentRig 进程直接调用模型，而由真实 AgentTeams Worker 完成，并
保存合法 Evaluation 和 Matrix 协作轨迹。

### Phase 4：Simulation Curator Worker

交付：

- Curator 角色 MCP、Skill、Worker 配置和 Adapter；
- Provider Chain 实时等待、取消、超时、一次修正和降级；
- 与 Sample/Real Tool 的回归。

退出条件：真实被测 Agent 的工具调用由 Curator Worker 生成合法结果，CaseRun 继续执行并留下完整
Provider/Event/Invocation/Matrix 证据。

### Phase 5：构建、配置和比赛完善

交付：

- 用例构建和配置辅助；
- 阿里云 SLS 官方 Skill；
- OTel/指标和协作 Trace；
- Docker/Helm 配置、README、样例和 Demo 视频脚本；
- 三 Agent 完整比赛链路和失败分支。

---

## 21. 测试策略

### 21.1 单元测试

- Plan 状态、不可变 revision、hash 和幂等；
- 确认策略 allow/confirm/deny；
- AssistantEvent seq 和 client id 去重；
- Matrix Event 去重和游标推进；
- Invocation 所有合法/非法状态转换；
- Principal 与角色工具权限；
- Curator/Judge 输出校验和迟到结果；
- AgentTeams/local Port 选择。

### 21.2 Repository 与 migration

- SQLite/PostgreSQL upgrade/current/downgrade/upgrade；
- 六张新表唯一约束和 FK；
- 并发消息 seq；
- Plan 重复提交只产生一个 Run；
- Invocation 并发提交只接受一次。

### 21.3 MCP 合同

- 外部 `/mcp/` 工具集保持 V1；
- Manager/Curator/Judge 工具集精确匹配本文；
- 每个角色调用越权工具得到 permission denied；
- 专业 Worker 不能枚举其他任务；
- 审计日志不包含完整输入、结果或凭据。

### 21.4 Matrix/AgentTeams 合同

默认测试使用 Fake Matrix Client 和 Fake Agent Dispatcher，不访问网络或真实模型。条件测试使用固定
AgentTeams 版本验证：

- room 创建和成员；
- Manager/Worker 消息；
- 重复 `/sync`；
- AgentRig MCP 经 Higress 调用；
- Worker 中断/重启；
- Matrix 暂时不可用后重试；
- 协作引用可以跳回 Plan/Run/CaseRun。

### 21.5 纵向测试

必须持续运行：

1. Web/Fake Manager → Plan → V1 Fixture → Rule → Manager 总结；
2. Manager → Run → AgentTeams Judge → Evidence Evaluation；
3. Manager → Run → 被测 Agent 工具调用 → AgentTeams Curator → Judge → 总结；
4. Curator 超时 → Sample/Real Tool 降级或明确 Provider Exhausted；
5. Judge 输出未知 Evidence ID → 修正失败 → Evaluation Error；
6. 页面断线、服务消息重投和重复确认不产生重复 Run；
7. AgentTeams 故障后 V1 Core MCP 仍能完成 Rule 回归。

### 21.6 V1 回归

现有 ruff、mypy strict、pytest、React build、CLI demo、wheel、AgentScope/Pixcake 和 Goose/ACP
验收不得退化。默认自动化仍不得要求真实模型、AgentTeams 或阿里云账户。

---

## 22. V2 第一版验收标准

全部满足才视为完成：

1. 用户只描述测试目标，Manager 能主动查询资产，不要求用户理解平台模型；
2. Manager 是 AgentTeams 中真实运行的自定义评测助手身份；
3. EvaluationPlan 可视化、可编辑、可确认、不可变并可幂等提交；
4. Managed 模式只能通过 `submit_evaluation_plan` 进入 V1 `run_cases`；
5. Run 与浏览器/Agent 回合解耦，断线重连能恢复；
6. Simulation Curator 和 Evidence Judge 是不同 AgentTeams Worker；
7. 至少一条 Demo 中三个 Agent 都完成真实工作并留下 Matrix 状态和关联 ID；
8. Curator/Judge 继续使用 V1 Schema、Validator、证据引用和错误语义；
9. 未启用专业 Worker 时，Core 模式按当前 V1 行为运行；
10. AgentTeams、Matrix 或模型故障不损坏已保存 Run/Event/Evaluation；
11. Rule、Judge 和 External 评判在 UI 和数据库中保持独立；
12. Manager/Worker 不能批准资产、读取明文密钥或绕过 Real Tool 授权；
13. Web 不持有 Matrix/Worker 管理凭据；
14. 对话、计划、协作、运行和证据可以通过 ID 全链路追踪；
15. 阿里云官方 SLS Skill 在比赛 Demo 中完成一次真实只读诊断；
16. V1 外部 MCP、HTTP、人工 Web、CLI Demo 和所有自动化继续通过；
17. AgentScope/Pixcake 与 Goose/ACP 至少各完成一次 V2 端到端复验；
18. 提供从干净环境启动 AgentRig + AgentTeams 的部署说明、样例配置和验收脚本。

---

## 23. 比赛要求映射

| 赛题要求 | AgentRig V2 证据 |
|---|---|
| 至少 3 个不同职能 Agent | Manager、Simulation Curator、Evidence Judge |
| AgentTeams 为协作基点 | 三个身份真实运行于 AgentTeams，Matrix/Invocation 可追踪 |
| 任务拆解 | Manager 生成 Plan 并决定专业能力，Core 在准确节点分派 Invocation |
| 上下文传递 | 任务信封 + 角色 MCP + 脱敏输入引用 |
| 协同执行和状态追踪 | AssistantTurn、AgentInvocation、Matrix Event、Run/CaseRun |
| Skill 必选 | Manager 5 项、Worker 2 项自有 Skill + 官方 SLS Skill |
| 工具集成 | AgentRig 角色 MCP、被测 Agent Driver/MCP Proxy |
| 结果验证 | Rule + Evidence Judge + External 独立评判 |
| 执行证据 | RunEvent、Evaluation、AgentInvocation、Matrix Trace |
| 高风险审批/回滚/审计 | Plan confirmation、Real Tool 三重授权、Run cancel、不可变快照 |
| 上下文能力至少 2 项 | AgentRig 会话/计划状态 + 共享运行状态 + 全链路轨迹 |
| 开放/开源价值 | AgentRig Core、MCP、Skill、接口合同和 Demo 数据 |

初赛方案可以用本文和架构图作为依据；复赛必须提供真实 AgentTeams 代码包、可运行 Demo 和运行证据，
不能以 Fake Adapter 作为参赛交付。

---

## 24. 开发约束与变更控制

以下是不可在普通实现 PR 中隐式改变的基线：

- AgentTeams Manager 是主 Agent，AgentRig 不再自建重复主模型循环；
- V1 Run/CaseRun/Event/Evaluation 是唯一执行和证据事实；
- AgentTeams 只通过 Adapter/MCP/Matrix 进入，不进入 V1 Domain；
- 专业 Worker 使用角色隔离工具和既有 Schema；
- Managed 模式先有 Plan，再提交 Run；
- 确认、审核和密钥安全由代码兜底；
- Core 模式不依赖 AgentTeams；
- 默认测试不依赖外部网络、模型 Key 或云账户。

可以在不改变 Domain 的情况下调整：

- Manager/Worker 具体模型；
- AgentTeams Runtime 和部署方式；
- Matrix/AgentTeams API 的兼容适配；
- OTel/SLS 后端；
- 前端视觉和布局；
- Skill 文案和样例，但不得放宽权限与输出合同。

升级 AgentTeams、改变 Agent 数量、增加自动重跑/发布、引入多租户或改变计划/运行事实归属时，必须先
补充 ADR、迁移方案、威胁模型和回归计划。

---

## 25. 最终判断

AgentRig V2 不是把聊天框、三个 Prompt 和比赛框架拼在一起，而是把三类不同性质的能力组合成一条
可靠链路：

1. AgentTeams Manager 理解用户目标并组织智能判断；
2. Curator/Judge Worker 在受限上下文中完成专业任务；
3. AgentRig V1 Core 以确定性代码执行、校验、存证和守住权限边界。

用户看到的是一个懂评测、能持续协作的助手；开发者仍然可以通过原子 MCP 精确控制；评审者能够从
Plan、Matrix、Invocation、Run、CaseRun、Event 和 Evaluation 逐层验证真实过程。只有在这三者共享
同一业务事实且故障互不污染时，V2 才真正从测试工具升级为可运行、可验证、可审计的智能评测团队。

---

## 26. `0.2.0a0` 实现状态

截至 2026-08-01，本方案对应的仓库实现已经包括：六张 V2 表及迁移、Assistant/Event/Turn、
EvaluationPlan 全状态机、AgentInvocation 生命周期、三角色最小权限 MCP、Matrix Bridge、
本地/AgentTeams 双适配器、Run 终态回投、SSE 断线续传、计划编辑/确认/提交界面、七项 Skill、
三角色 AgentTeams 包及固定 `v1.1.2` 的部署覆盖层。

默认自动化使用本地数据库和 Matrix/Worker 合同替身，不需要外部账户。带真实凭据的
AgentTeams/Matrix、SLS、AgentScope/Pixcake 和 Goose/ACP 比赛环境复验仍属于部署验收，不应把
Mock 合同测试描述成真实比赛运行证据。部署者必须按第 21、22 节补齐外部验收记录后，才能宣布
比赛环境整体完成。
