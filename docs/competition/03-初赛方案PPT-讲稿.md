# 初赛方案 PPT 讲稿

建议 12 页，正式陈述控制在 8 分钟；初赛提交版可以保留完整备注。

## 01｜封面：让企业 Agent 的每次变化都有证据

- AgentRig：多 Agent 可审计评测基础设施
- GOAI 2026 · Agent Infra 新智基座
- 关键词：AgentTeams / MCP / Evaluation / Evidence / Audit

讲解：Agent 不缺一次成功的 Demo，缺的是每次升级后都能回答“哪里变了、为什么通过、证据
是什么、能否安全重跑”。

## 02｜问题：传统测试方法不适配 Agent

- 输出具有随机性，字符串快照既脆弱又无法解释语义。
- Agent 会调用工具，真实工具昂贵、有副作用，纯 mock 又缺乏合理性。
- LLM-as-Judge 容易看到预期答案、接受伪造证据或与运行事实脱节。
- 多轮状态、版本、工具链和审批使问题从“接口测试”升级为“执行治理”。

讲解：我们解决的不是聊天质量打分，而是企业 Agent 的持续验证基础设施。

## 03｜用户价值：从一句目标到可审计 Run

1. 用户描述目标，不需要先理解平台数据模型。
2. Manager 查询现有 Case、Target、Profile 和历史 Run。
3. 页面预览范围、版本、数量、Provider、Evaluator 和风险。
4. 用户明确确认后才提交。
5. 系统执行、验证、裁决并保存证据。
6. Manager 解释结果或把失败沉淀为新用例草稿。

## 04｜三 Agent：职责分离，不为数量而拆分

| Agent | 不可替代工作 | 为什么不能合并 |
|---|---|---|
| Manager | 目标理解、资产选择、计划、审批、诊断 | 需要全局业务上下文，但不能持有 Worker 越权能力 |
| Curator | 在看不到 rubric 的前提下生成合理工具结果 | 防止根据预期答案“作弊式模拟” |
| Judge | 在执行结束后独立裁决并引用证据 | 防止执行者自评和结论污染事实 |

## 05｜AgentTeams 如何真实进入系统

- AgentTeams v1.1.2 管理 Manager/Worker 生命周期、身份和工作区。
- Matrix 完成定向唤醒、任务投递、进度与最终回执。
- MinIO 保存 AgentTeams 角色工作区和 Skills。
- Higress 为三个身份提供相互隔离的 MCP route。
- AgentRig Adapter 把 AgentTeams 协作投影到业务 invocation，不把框架类型写入 Core。

讲解：不是在 PPT 中“提到 AgentTeams”，三个身份和双向 Matrix event ID 都可以现场核验。

## 06｜闭环架构：协作层与事实层分离

```text
Web → AgentTeams Manager → Manager MCP → EvaluationPlan
                                     ↓ 用户确认
AgentRig Core → lassist/Pixcake → Tool Call
       │              ▲
       ├→ Curator Worker ─→ controlled ToolResult
       └→ Judge Worker  ─→ evidence-linked verdict
       ↓
SQLite/PostgreSQL：Case / Plan / Run / RunEvent / Evaluation / Invocation
```

讲解：AgentTeams 管“谁协作”，AgentRig Core 管“什么是事实”。任一 Agent 不能通过聊天文本
改写权威运行记录。

## 07｜Skill 与 MCP：可复用能力，不是一次性 Prompt

- 6 个 Manager Skills：证据化决策、规划、执行、诊断、用例草稿、Target 配置。
- 2 个 Worker Skills：工具结果模拟、证据裁决。
- 3 个 Core Skills：运行、用例构建、样本收集。
- 每个比赛核心 Skill 定义触发条件、输入输出、依赖工具、失败、重试、安全边界和版本合同。
- 三个角色 MCP 工具集物理隔离，Manager 没有原始 `run_cases`，Worker 不能枚举任务。

## 08｜可信评测：防止“Judge 说通过就通过”

- TestCase、Target、Profile 在计划阶段形成不可变快照。
- Rule Evaluator 提供确定性断言；Judge 提供语义判断，两份结果独立保存。
- Judge 只能引用本次 Run 中存在的 event ID。
- Curator 永远看不到 rubric、分数和预期答案。
- Worker 输出先经过 Pydantic/JSON Schema/证据引用校验，再进入事实库。

## 09｜安全、审批与恢复

- draft → confirmed → submitted，确认必须绑定真实用户事件和同一 revision。
- 密钥只通过 `env:`/Secret 引用，Matrix、日志和 Skill 不保存明文。
- Redactor 对模型和 Worker 输入统一脱敏。
- 幂等键防重复提交；超时、取消、失败均为显式终态。
- AgentTeams 不可用时，智能助手返回 unavailable，但 V1 Core 与已保存证据不受损。

## 10｜真实 Demo：成功、失败与证据

- 被测对象：本机 lassist/Pixcake Agent，不是伪造 Driver。
- 成功场景：背景增强 → `apply_image_prompt` → Curator 模拟成功 → Judge pass → Rule 3/3。
- 失败场景：策略要求编辑前二次确认，但被测 Agent 直接调用工具 → Rule/Judge fail。
- 安全场景：未确认计划不能提交；Worker/MCP 错误保留结构化状态和已有 RunEvent。
- 页面展示 Session、Plan、三个 Agent、Invocation、Run 和 Matrix 双向 event ID。

## 11｜工程与开放价值

- Python 3.12、FastAPI、SQLAlchemy、React、MCP；MIT License。
- Driver 支持 Pixcake HTTP-SSE、OpenAI compatible、ACP、subprocess。
- SQLite 用于本机体验，Repository 可切换 PostgreSQL。
- AgentTeams 是可替换协作 Adapter；Core 无模型、无 AgentTeams 仍可运行。
- 提供一键部署、示例配置、11 个 Skills、接口契约、安全文档和自动测试。

## 12｜路线图与愿景

- 初赛：公开设计、身份清单、真实三 Agent Demo。
- 复赛：失败/恢复视频、可执行代码包、Trace/运行报告与性能指标。
- 决赛：PostgreSQL/Kubernetes 部署、OTel/SLS 可观测、跨 Agent 版本对比与发布门禁。
- 愿景：成为不同企业 Agent 共用的开源质量与发布基础设施。

收束句：AgentRig 不替 Agent 做决定，而是让每个决定都经过分工、验证并留下证据。
