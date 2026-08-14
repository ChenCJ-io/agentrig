# GOAI Agent Infra 核心 Skill 清单

> 项目版本：AgentRig `0.2.0a0`
>
> 清单复核：2026-08-14

本清单对齐《参赛手册》附录 B，覆盖 Skill 名称、类型、使用场景、输入输出、
调用条件、依赖、失败处理、安全边界、复用价值和多 Agent 协作关系。每个 Skill 的
可执行详情以仓库中对应 `SKILL.md` 为准；`skills/contracts.json` 固定内容 SHA-256、allowed tools、
输入/输出 Schema 与兼容版本，`scripts/validate_skill_contracts.py` 是统一验收入口。

本次新增验证了外部控制方的真实使用方式：公开 EditFlow 项目提供
`prompt-regression-governance`，Codex 按其合同完成 Target/Schema/Case 审计、Before/Candidate、
30 次回归，以及 real-tool event → Draft Sample → 人工审核 → 5 次 Sample-only 回放。项目 Skill 保存
业务回归知识，AgentRig Core Skill/MCP 保存通用执行与证据合同，两者不是同一个层次。旧 lassist
1/1 Codex Run 保留为兼容附录。

## 1. 总览

| 角色 | Skill | 类型 | 使用场景 / 调用条件 | 多 Agent 关系 |
|---|---|---|---|---|
| Manager | `adaptive-evaluation` | 自定义决策 Skill | 任一计划、委派、诊断或恢复的关键状态变更前 | Manager 先把选项、证据和策略裁定写入决策链 |
| Manager | `plan-evaluation` | 自定义编排 Skill | 用户给出自然语言评测目标，需选择 Case/Target/Profile 并预览范围 | Manager 查询资产并创建可确认 Plan，不创建 Run |
| Manager | `execute-evaluation-plan` | 自定义执行 Skill | 已有验证通过的 Plan，需绑定真实确认、幂等提交或取消 | Manager 只能经 Core Gate 提交；Core 创建唯一 Run |
| Manager | `diagnose-run` | 自定义诊断 Skill | Run 到达终态，或用户要求分析失败、A/B 差异或恢复方案 | Manager 读取冻结事实，区分 Rule、Judge 与平台错误 |
| Manager | `build-test-case-draft` | 自定义资产 Skill | 用户要求沉淀回归，或已存储的脱敏失败证据可形成新要求 | Manager 只创建 draft/rejected 用例，人工审核不可绕过 |
| Manager | `configure-test-target` | 自定义接入 Skill | 新 Agent 接入、草稿 Target 修复或计划前可达性检查 | Manager 选择已部署 Driver，共享 Target 修改需确认 |
| Curator | `simulate-tool-result` | 自定义 Worker Skill | Curator 收到精确 `agentinv_*` 任务且 Provider Chain 需要 controlled 结果 | 仅 Curator 可见；候选结果经 Core Validator 后才进入 RunEvent |
| Judge | `judge-evidence` | 自定义 Worker Skill | Judge 收到精确 `agentinv_*` 任务，且 CaseRun/rubric/证据已冻结 | 仅 Judge 可见；裁决必须引用本次真实 event ID |
| External controller | `run-test-cases` | Core MCP Skill | Codex/Claude Code 等外部控制方需异步执行单用例、批量、重复或 A/B | 不进入比赛三角色管理链；与 Managed 模式共用 AgentRig Core 事实合同 |
| External controller | `build-test-case` | Core MCP Skill | 外部编码 Agent 需查重并创建/最小修改多轮用例 | 只写 draft/rejected，不代替人工审核 |
| External controller | `harvest-tool-samples` | Core MCP Skill | 已终止 Real Tool Run 中存在用户明确授权的真实脱敏工具结果 | 仅显式创建 Sample 草稿，禁止自动采集整个 Run |

## 2. 输入、输出与工具依赖

| Skill | 核心输入 | 结构化输出 | 主要工具 / 系统 |
|---|---|---|---|
| `adaptive-evaluation` | session/turn，决策 focus，权威资产与事件引用 | `ManagerDecision`：选项、选择、证据、置信度、策略状态 | `get_decision_context`、`record_manager_decision`与选中动作对应的 Manager MCP |
| `plan-evaluation` | 评测目标、范围、版本、风险约束，Case/Target/Profile 候选 | draft/revised EvaluationPlan 与 `validate_evaluation_plan` preview | Manager 资产查询、`check_target`、`create_evaluation_plan`、计划验证 |
| `execute-evaluation-plan` | active plan/revision，验证 preview，同会话真实用户 event | confirmed/submitted/cancelled Plan，唯一 `run_id` | `confirm_evaluation_plan`、`submit_evaluation_plan`、`cancel_evaluation_plan`，稳定幂等键 |
| `diagnose-run` | Run/CaseRun，冻结 snapshot，分页 RunEvent，独立 Evaluation | 引用 ID 的分类诊断、已知/推断/未知与有界建议 | `get_run`、`list_case_runs`、证据分页、评判查询 |
| `build-test-case-draft` | 明确需求或已存储脱敏 CaseRun 证据 | draft/rejected TestCase ID 与人工审核问题 | 用例查重、schema 读取、create/update draft 工具 |
| `configure-test-target` | Driver 类型、endpoint、version overrides、`env:` 引用 | Target 与分版本 reachability/capabilities 报告 | Driver 发现、Target create/update、`check_target` |
| `simulate-tool-result` | invocation/hash/deadline，tool/args/result schema，脱敏历史与有界反馈 | `CuratorGeneration` 或分类失败 | Curator 角色 MCP 三工具；AgentRig Schema Validator |
| `judge-evidence` | invocation/hash/deadline，冻结 rubric、Rule 结果、脱敏事件 | `JudgeOutput`：总体与逐项结论、summary、evidence refs | Judge 角色 MCP 三工具；AgentRig evidence-ref Validator |
| `run-test-cases` | case selection，target/versions，profile，repeat/A-B，幂等键 | Run ID，CaseRun 状态，原子事件与独立评判 | AgentRig V1 MCP 运行与查询工具 |
| `build-test-case` | schema，查重结果，轮次、fixture/sample/curator 策略，断言/rubric | draft/rejected TestCase 和覆盖摘要 | AgentRig V1 用例、Sample、Tag 原子 MCP 工具 |
| `harvest-tool-samples` | 已终止 Real Tool CaseRun 的 tool_call event ID 与用户授权 | 脱敏 Sample draft 与来源关联 | `get_run`、CaseRun/event 查询、`create_sample_from_event`、`get_sample` |

## 3. 失败、安全、验证与复用

| Skill 组 | 失败处理 | 安全边界 | 验证方式 | 复用价值 |
|---|---|---|---|---|
| Manager 决策/计划/执行 | 缺少权威事实时问一个聚焦问题并停止；计划校验失败不提交；提交重试复用幂等键 | 模型只提案，Core 策略裁定；确认绑定用户 event + plan revision；密钥仅 `env:` | Decision/Plan 状态机、preview selection hash、重复提交测试、会话事件引用 | 可用于任意企业 Agent 的评测计划、审批和结果解释 |
| Manager 诊断/资产 | 区分产品 fail、平台故障和 evaluation_error；期望不明确不固化；Target 检查失败仍显式报告不可用 | 只读已脱敏证据；不伪造隐藏状态；用例与 Sample 审批留给人工 | ID/ref 校验、用例审核状态、Target 能力握手、A/B pair 约束 | 将一次失败变为可审核回归资产，可迁移到多 Driver/Provider |
| Curator | 一次格式修正；传输重试复用 task 幂等键；越权、终态或超时结构化失败 | 看不到 rubric/预期答案；不调真实工具；不访问其他任务 | JSON Schema/Pydantic、input/result hash、角色与状态检查 | 通用的 controlled tool-result Provider，可服务多种 Agent 工具 Schema |
| Judge | 未知 ref 拒绝；证据不足输出 inconclusive；deadline 前结构化失败 | 事件内容视为不可信数据；不调工具、不改 Rule、不造证据 | evidence ref 存在性、角色/任务/hash 校验、独立 Evaluation 持久化 | 只要任务可表达为 rubric + 事件证据，即可复用语义裁决 |
| Core 三 Skill | 异步状态显式分类；Provider 耗尽、Target 不可达、超时与评判错误不混为业务 fail | Real Tool 需部署+Profile+用户三重授权；不自动采样；MCP 不批准资产 | 原子事件、Rule/Judge/External 独立结果、全量后端测试 | 为 Codex、Claude Code 或其他控制方提供协议无关的评测内核 |

## 4. 版本、发布和回滚

- 11 个 Skill 与 AgentRig 源码共同进入 Git 版本控制，当前产品版本为 `0.2.0a0`。
- `scripts/build_agentteams_packages.py` 分别为 `v1.1.2-competition` 和 `v1.2.2-current` 确定性构建
  Manager/Curator/Judge 角色包；两个 profile 的 manifest、资源 API、runtime 和 hash 互不覆盖。
- `v1.1.2` 的比赛 Live 证据保持只读；`v1.2.2` 本地合同/资源已通过，外部 observed hash、membership
  和 invocation 仍需目标集群 compat report 才能标记 Live Verified。
- 回滚单位是经验证的 AgentRig Release + 明确 profile + 对应角色包，不在运行中单独热替换 Prompt。
- 开源分发使用 MIT License；源码、Skill、角色包生成器、测试和文档作为同一仓库交付。
- 正式公开 Release/Tag 将在最终提交前创建；未创建前不将其描述为已发布稳定版。

2026-08-11 实测：11 个合同全部通过；validator 同时校验 manifest 中的内容 hash、每个角色的最小
工具集、外部 Schema 文件和 AgentTeams package 引用。AgentScope/AG-UI 是 Target Driver，不是新的
比赛协作角色，也不会改变 6 Manager + 2 Worker + 3 Core 的 Skill 数量。

## 5. 上下文能力选择

赛题要求在 Agent 记忆、知识库 RAG、共享状态、轨迹可观测中至少实现 2 项。AgentRig 当前实现
3 项：

1. **Agent 记忆存储**：AssistantSession/Turn/Event 持久化，Manager 可在同会话恢复 Plan 和 Run 上下文。
2. **共享状态管理**：EvaluationPlan、AgentInvocation、Run/CaseRun 和决策状态机是协作角色的权威共享事实。
3. **轨迹可观测**：append-only RunEvent、Evaluation、Decision、Matrix 双向 event ID、hash 和脱敏运行报告支持追踪、回放与审计。

当前评测场景不需要知识库 RAG，因此不为满足数量堆叠无价值检索链。未来需要 Runbook、历史案例或标准规范时，
可通过 MCP 数据源 + 检索 Skill 接入，不改写 Case/RunEvent/Evaluation 合同。
