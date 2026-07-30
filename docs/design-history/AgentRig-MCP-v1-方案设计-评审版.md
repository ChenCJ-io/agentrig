# AgentRig MCP v1 方案设计（评审版）

> 状态：历史评审稿，已被 `AgentRig-V1-MCP-架构与代码设计.md` 取代
> 版本：0.1-draft
> 日期：2026-07-28
> 阅读对象：产品负责人、架构负责人、研发负责人
> 归档说明：保留用于追溯产品边界形成过程，不作为当前 V1 实现合同
> 工程细节附录：[AgentRig MCP v1 工程方案设计](./AgentRig-MCP-v1-工程方案设计.md)

---

## 1. 先给结论

AgentRig 第一阶段只开发 **Codex/Claude Code 通过 MCP 控制评测**的版本。

用户继续在 Codex 或 Claude Code 中工作。编程助手已经知道用户改了什么，因此由它负责
选择用例、补充用例和决定何时重跑；AgentRig 不再安排另一个主 Agent 重复分析代码。

AgentRig 第一阶段只负责六件事：

1. 管理版本化测试用例。
2. 为工具调用准备可复现的模拟环境。
3. 执行被测 Agent。
4. 保存完整且不可修改的运行证据。
5. 根据规则和可选的语义评审生成报告。
6. 给出是否应该阻止发布的建议。

第一阶段做好后，再开发 AgentRig Web 中的用例执行助手。届时只是把“谁来选择用例”从
Codex 换成平台自己的回归评测管理员，执行内核不重写。

---

## 2. 用户实际怎么使用

假设用户刚让 Codex 修改了一个客服 Agent 的退款工具权限。

完整流程应该是：

```text
用户让 Codex 修改代码
        ↓
Codex 读取 Git diff，判断退款能力受到影响
        ↓
Codex 通过 MCP 查询相关用例和现有覆盖
        ↓
Codex 告诉用户：
“找到 8 个相关用例，退款失败场景缺 1 个，建议补充后执行”
        ↓
用户确认
        ↓
Codex 提交一份不可修改的执行清单
        ↓
AgentRig 准备工具环境并执行 baseline/candidate
        ↓
AgentRig 返回报告、失败证据和发布建议
        ↓
Codex 根据证据修改代码并重跑失败用例
```

这里有一个关键原则：

> Codex 决定“测什么”，AgentRig 保证“怎么测、证据是什么、结论是否可信”。

这是 MCP v1 最重要的产品边界。

---

## 3. MCP v1 中有哪些 Agent

### 3.1 外部编程助手：唯一的范围负责人

Claude Code 或 Codex 是主 Agent。

它负责：

- 阅读仓库和代码改动。
- 判断本次改动可能影响哪些能力。
- 查询、选择和补充测试用例。
- 向用户解释为什么选择这些用例。
- 经用户确认后提交评测。
- 根据评测证据修复业务代码。

它不负责：

- 自己模拟工具返回。
- 自己保存正式运行证据。
- 自己判断发布门禁。
- 直接修改 AgentRig 内部数据库。

### 3.2 模拟环境管理员：受约束的智能能力

代码名为 `SimulationCurator`。

它解决的问题是：测试 Agent 时，第三方工具、业务 API 或外部数据往往无法直接调用，
已有 Fixture 又可能不完整。

它负责：

- 优先查找固定 Fixture 和已批准的真实回放样本。
- 缺失时生成候选工具返回。
- 校验返回值 Schema、业务约束和多轮状态一致性。
- 校验通过后冻结成可复现快照。
- 信息不足时明确要求真实样本，不伪造“看起来合理”的结果。

第一阶段它不是一个能自由行动的独立 Agent，而是固定输入、固定输出、经过程序校验的智能
工作流。这样可以先得到智能补全能力，不需要提前建设 AgentTeams 调度平台。

### 3.3 证据评审员：受约束的智能能力

代码名为 `EvidenceJudge`。

它解决的问题是：有些目标可以用确定性规则判断，例如“不得调用删除工具”；有些目标只能
结合上下文判断，例如“是否真正解决了用户问题”。

它只能读取已经保存的证据，不能修改执行记录。每个结论必须引用对应证据；证据不足时返回
“无法判断”，不能猜测通过。

### 3.4 第一阶段明确没有的 Agent

第一阶段不开发：

- 回归评测管理员（Regression Manager）。
- AgentRig Web 评测助手。
- 通用子 Agent 注册和调度系统。
- RCA、报告、安全、性能等独立 Agent。

这些能力等 MCP 执行闭环稳定后再建设。

---

## 4. 不再使用含义模糊的“运行模式”

原方案把下面四项放进同一个 `RuntimeProfile`：

```text
core / intelligent / agentteams / production
```

这个定义不成立，因为：

- `core/intelligent` 描述启用了哪些能力。
- `agentteams` 描述是否启用多 Agent 协作。
- `production` 描述部署在哪里。

它们可以同时成立，不是四选一。

新的方案拆成三个问题。

### 4.1 谁决定测什么

字段名为 `control_owner`：

| 负责人 | 使用阶段 |
|---|---|
| Codex/Claude Code | MCP v1 |
| AgentRig 回归评测管理员 | 后续 Web 助手版本 |
| 人工或 CI | 已经有明确执行清单的自动化场景 |

一次评测只能有一个负责人，避免 Codex 和平台 Manager 同时修改评测范围。

### 4.2 本次启用哪些可选智能能力

字段名为 `enabled_capabilities`：

- `simulation_curator`：允许智能补全模拟环境。
- `evidence_judge`：允许语义评审。
- `agent_coordination`：允许 Manager 分派多个子 Agent，第一阶段不开启。

确定性执行内核始终存在，不作为可关闭能力。

### 4.3 系统部署在哪里

字段名为 `deployment_profile`：

- `local`：SQLite、本地文件、适合个人开发。
- `server`：团队共享服务和独立 Worker。
- `production`：高可用数据库、对象存储、完整审计和监控。

部署到生产环境不会自动开启 LLM；开启 Evidence Judge 也不要求必须使用 AgentTeams。

---

## 5. 一次评测为什么需要这些对象

这些英文名只用于代码和协议。每个对象都对应一个真实业务问题。

| 中文含义 | 代码名 | 为什么需要 |
|---|---|---|
| 被测 Agent | `AgentTarget` | 表示长期测试的对象，与某次代码版本分开 |
| 被测版本 | `TargetRevision` | 精确记录代码、Prompt、模型和工具定义，支持版本比较 |
| 版本化用例 | `TestCaseVersion` | 用例修改后仍能还原历史评测 |
| 已确认执行清单 | `RunSpec` | 固定本次测哪些版本和用例，执行中不能偷偷变化 |
| 一次完整评测任务 | `EvaluationJob` | 保存进度，支持等待、取消、重试和服务重启恢复 |
| 一次具体尝试 | `Attempt` | 重试新增记录，不覆盖第一次失败 |
| 已冻结工具环境 | `SimulationSnapshot` | 保证 baseline/candidate 面对相同的工具世界 |
| 原始证据包 | `EvidenceBundle` | Rule、Judge 和报告只能基于同一份事实 |
| 评测报告 | `EvaluationReport` | 汇总规则、语义判断、版本差异和局限 |
| 发布建议 | `GateRecommendation` | AgentRig 建议通过、阻止或人工复核 |
| 最终发布决定 | `ReleaseDecision` | 由人或受信 CI 记录，不能由 Judge 冒充授权 |

最重要的关系是：

```text
RunSpec：准备测什么
EvaluationJob：现在执行到哪里
EvidenceBundle：实际发生了什么
EvaluationReport：这些事实说明什么
GateRecommendation：基于策略建议怎么处理
ReleaseDecision：最终由谁批准
```

---

## 6. 系统怎么拆模块

第一阶段使用模块化单体，不提前拆微服务。

### 6.1 五层代码责任

| 代码区域 | 中文责任 | 为什么单独存在 |
|---|---|---|
| `domain` | 状态机、门禁规则、不可变约束 | 不依赖 MCP、数据库或 LLM，保证规则稳定 |
| `application` | 完成“提交评测”“冻结快照”等业务流程 | 负责事务、权限、幂等和步骤编排 |
| `ports` | 定义系统需要哪些外部能力 | 让核心逻辑不绑定 SQLite、LLM 或 AgentTeams |
| `adapters` | 实现 MCP、SQLite、文件存储和 LLM 接入 | 基础设施变化不影响业务规则 |
| `bootstrap` | 读取配置并组装具体实现 | 避免到处创建全局对象 |

`Port` 可以理解为插座标准，`Adapter` 是具体插头。

例如，证据评审接口是一个 Port；固定规则评审、本地 LLM 和以后 AgentTeams 中的 Judge 都
可以成为它的 Adapter。

### 6.2 推荐代码结构

```text
src/agentrig/
├── bootstrap/                 # 启动、配置和依赖组装
├── domain/
│   ├── catalog/               # 用例和覆盖
│   ├── execution/             # Job、Run、Attempt 和状态机
│   ├── simulation/            # 模拟请求、候选、快照和冻结规则
│   ├── evidence/              # 原始证据
│   ├── evaluation/            # Rule、Judge 结果和报告
│   └── governance/            # 发布建议与最终决定
├── application/
│   ├── catalog/               # 搜索和维护用例
│   ├── execution/             # 统一执行引擎
│   ├── simulation/            # 准备和冻结工具环境
│   ├── evidence/              # 构建和查询证据
│   ├── evaluation/            # 聚合评测报告
│   └── governance/            # 计算门禁建议
├── ports/                     # 对话、工具、Judge、存储等抽象接口
├── adapters/
│   ├── inbound/mcp/           # Codex/Claude Code 调用入口
│   └── outbound/              # SQLite、文件、LLM、Proxy 等实现
└── compatibility/             # 迁移期兼容旧工具和旧数据
```

### 6.3 当前代码怎么迁移

当前最关键的迁移不是改文件名，而是消除三套事实来源：

1. `CaseRunner` 和 `ProxyScenarioRunner` 合并为一个执行引擎。
2. REST `_runs` 和运行时全局变量迁入持久化 Job/Run Repository。
3. Synth 结果不再直接进入正式执行，必须经过候选、校验和冻结。

兼容层暂时保留旧 MCP 工具，保证现有测试不因一次性重写而全部失效。

---

## 7. MCP 应该提供什么工具

MCP 工具按用户任务分组，不暴露数据库 CRUD。

| 工具组 | Codex 想完成的事情 | 代表工具 |
|---|---|---|
| 系统 | 检查服务是否可用、支持什么能力 | `system_get_capabilities` |
| 用例目录 | 搜索正式用例、查询覆盖缺口 | `catalog_search_cases`、`catalog_get_coverage` |
| 用例维护 | 校验和保存草稿、提交审批 | `cases_validate_draft`、`cases_upsert_draft` |
| 真实样本 | 查询和导入真实工具调用样本 | `samples_search`、`samples_import_draft` |
| 模拟环境 | 准备、查看和批准冻结快照 | `simulations_prepare_snapshot` |
| 评测任务 | 提交、等待、取消和重试 | `evaluations_submit`、`evaluations_wait` |
| 证据 | 查看 Trace、版本差异和证据包 | `evidence_get_bundle`、`evidence_compare_runs` |
| 发布治理 | 获取门禁建议、记录最终决定 | `governance_get_recommendation` |

### 7.1 为什么不提供底层 CRUD

如果让 Codex 分别创建 Run、更新 Attempt、写 Evidence 和修改状态，很容易产生半完成数据，
也让调用方承担 AgentRig 内部状态机。

因此 `evaluations_submit` 是一个高层命令：

```text
校验 RunSpec
  → 持久化评测任务
  → 创建后台执行
  → 立即返回 evaluation_job_id
```

长任务通过 `get/wait` 查询，不让单次 MCP 请求一直阻塞。

### 7.2 为什么所有写操作需要幂等键

MCP 网络超时后，Codex 无法确定请求是否已经到达服务端。如果直接重试，可能创建两个任务。

每个写命令携带 `idempotency_key`。相同用户、相同工具、相同幂等键再次调用时返回第一次
结果，不重复执行。

---

## 8. 执行、模拟和评测如何协作

### 8.1 只有一个执行引擎

执行引擎只做确定性工作：

1. 读取不可修改的 RunSpec。
2. 为每个用例创建 Attempt。
3. 启动被测 Agent。
4. 接收文本、工具调用、完成或错误事件。
5. 将工具调用交给工具边界处理。
6. 保存 Trace、日志、工具输入输出和时间指标。
7. 构建 EvidenceBundle。

它不选择用例、不生成发布结论，也不让 LLM 直接修改状态。

### 8.2 为什么分开“对话接入”和“工具边界”

- `ConversationDriver` 负责怎样启动被测 Agent、发送消息和接收事件。
- `ToolBoundary` 负责工具调用由 Fixture、真实回放、MCP Proxy 还是真实工具响应。

有些 Agent 由子进程启动，有些通过远程 API；有些测试拦截工具调用，有些只能观察。
这两个变化方向不同，因此不能继续维护两套 Runner。

### 8.3 模拟结果为什么必须冻结

动态生成的工具返回首先只是候选，不是可信事实。

```text
发现工具环境缺口
  → 创建 SimulationRequest
  → 查找 Fixture/真实回放
  → 必要时生成候选
  → 校验 Schema、约束和状态变化
  → 冻结 SimulationSnapshot
  → 正式执行
```

未冻结的合成结果只能用于调试，不能进入发布门禁。

baseline 和 candidate 必须绑定同一个 Snapshot Hash，否则测到的可能是环境差异，而不是
Agent 行为差异。

### 8.4 Rule、Judge 和 Gate 各自负责什么

| 层次 | 回答的问题 | 能否使用 LLM |
|---|---|---|
| 确定性规则 | 是否调用了禁止工具、参数是否正确、是否超时 | 否 |
| 证据评审 | 是否真正完成语义目标、证据是否足够 | 可选 |
| 评测报告 | 规则和语义结论如何组合、有哪些局限 | 否，确定性聚合 |
| 发布门禁 | 根据组织策略建议通过、阻止还是人工复核 | 否 |
| 最终决定 | 是否真的发布 | 由人或受信 CI 决定 |

Judge 不能直接发布，也不能把基础设施错误判成 Agent 回归。

---

## 9. 数据与可靠性底线

MCP v1 默认使用 SQLite 和本地 Artifact 目录，但必须满足：

- RunSpec 提交后不可修改。
- 重试创建新 Attempt，不覆盖旧记录。
- Snapshot 和 Evidence 使用内容 Hash 校验。
- 服务重启后 Job、Run 和 Evidence 仍可查询。
- 同一幂等键不会创建重复任务。
- 取消操作可以重复调用。
- 不把 Python traceback 直接返回给 MCP 客户端。
- 凭证不写入 RunSpec、Trace 和 Artifact。
- 真实写工具默认禁止，必须由明确 Policy 和用户审批开启。

---

## 10. 开发顺序

### 阶段一：先稳定数据和状态

- 建立 RunSpec、EvaluationJob、Run、Attempt。
- 建立 SQLite migration 和 Artifact Store。
- 删除接口层权威 `_runs`。

验收：服务重启后任务和结果不丢失。

### 阶段二：统一执行

- 抽象 ConversationDriver 和 ToolBoundary。
- 合并两条现有 Runner。
- 建立并发隔离、超时、取消和重试。

验收：不同接入方式共用一个执行状态机。

### 阶段三：模拟环境生命周期

- 建立 SimulationRequest、Candidate、Validation、Snapshot。
- Fixture 和 Replay 优先。
- Synth 结果必须冻结后才能正式使用。

验收：未冻结合成结果进入门禁的数量为零。

### 阶段四：证据、评测和门禁

- 建立 EvidenceBundle。
- 迁移 Rule Judge。
- 接入可选 Evidence Judge。
- 分开 GateRecommendation 和 ReleaseDecision。

验收：每个失败或无法判断的结论都有证据引用。

### 阶段五：MCP 与 Codex/Claude Code 闭环

- 发布高层 MCP 工具。
- 发布发现用例、维护用例、执行评测、检查结果等 Skills。
- 保留旧工具兼容层。

验收：用户只在 Codex/Claude Code 中即可完成一次回归和修复重跑。

---

## 11. 第一版如何验收

准备一个被测 Agent、两个版本和 10—20 个已批准用例，演示：

1. Codex 读取一次工具权限改动。
2. Codex 查询相关用例和覆盖缺口。
3. 用户确认后提交 RunSpec。
4. AgentRig 对缺失 Fixture 生成候选并冻结 Snapshot。
5. baseline/candidate 使用同一 Snapshot 执行。
6. 一个安全规则失败，门禁建议为 BLOCK。
7. Codex 打开 Evidence Capsule，定位具体失败调用。
8. Codex 修改代码并只重跑受影响用例。
9. 服务重启后仍能查询两次任务的完整历史。

通过标准：

- Codex 是唯一范围负责人。
- MCP 工具没有直接写数据库或驱动内部状态机。
- 两种现有执行方式共用一个 Execution Engine。
- 未冻结合成环境不能用于门禁。
- 基础设施错误与 Agent 失败分开。
- Report、Recommendation 和最终发布决定分开。

---

## 12. 后续 Web 助手如何接入

MCP v1 稳定后，第二阶段新增：

- Web Evaluation Assistant。
- Regression Manager。
- ChangeSet 和 SelectionPlan。
- 用户审批、进度和证据界面。
- 后续 AgentTeams 协作层。

Web 助手的流程是：

```text
用户自然语言需求
  → Regression Manager 选择用例并给出理由
  → 用户确认
  → 生成与 Codex 模式完全相同的 RunSpec
  → 复用 MCP v1 的执行、模拟、证据、评测和门禁
```

第二阶段只增加新的范围负责人和交互入口，不创建第二套执行平台。

---

## 13. 本轮需要确认的决策

建议先确认以下五项，其他实现细节放入工程 RFC：

1. MCP v1 是否必须同时支持 baseline/candidate。
2. 第一批覆盖索引只使用 tags/tools，还是增加 file/prompt mapping。
3. 用例审批第一阶段由 CLI、MCP reviewer tool 还是 Web 完成。
4. 合成 Snapshot 是否允许经人工批准进入门禁，还是 v1 只允许 Fixture/真实 Replay。
5. Evidence Judge 第一版默认开启还是默认关闭。

---

## 14. 一句话架构

> Codex 决定测什么；AgentRig 固定执行范围、准备同一套工具环境、运行被测 Agent、保存原始
> 证据并给出发布建议；等这条 MCP 闭环稳定后，再让 AgentRig 自己的 Manager 成为第二种
> 评测范围负责人。
