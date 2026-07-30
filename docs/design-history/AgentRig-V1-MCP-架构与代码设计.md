# AgentRig V1：MCP 架构与代码设计

> 状态：V1 开工设计基线；当前实现与接口以父目录权威文档为准
> 日期：2026-07-29
> 适用仓库：AgentRig
> 讨论依据：[AgentRig-MCP-架构讨论记录.md](./AgentRig-MCP-架构讨论记录.md)
> 归档说明：保留完整开工设计用于追溯；实现过程中已按验收反馈做过简化和调整。

---

## 1. 先看结论

AgentRig V1 是一个由 Claude Code/Codex 控制的 Agent 回归测试平台。

Claude Code/Codex 负责：

- 阅读业务代码和变更；
- 查询、选择或创建测试用例；
- 发起单用例或批量执行；
- 读取原始运行证据；
- 在不使用平台 Judge 时自行判断并回写结论。

AgentRig 负责：

- 管理用例、被测目标、版本、执行方案和工具结果样本；
- 在可控制的工具环境中执行被测 Agent；
- 持续保存对话、工具调用、工具结果和校验证据；
- 提供确定性 Rule 评判；
- 按需调用 Simulation Curator 和 Evidence Judge；
- 通过 MCP 和 HTTP 暴露原子能力。

V1 平台内部只有两个 Agent：

1. **Simulation Curator**：Fixture 和 Sample 都未命中时，生成合理的工具结果。
2. **Evidence Judge**：根据完整执行证据和评测要求给出语义判定。

V1 不包含：

- Regression Manager；
- 平台内置用例选择 Agent；
- 平台内置对话执行助手；
- Comparison Engine；
- 多 Agent 评测与用例归属；
- 分布式任务队列。

平台内置执行助手属于 V2。它未来替代 Claude Code/Codex 当前承担的选案、编排和结果分析职责，
但不会改变 V1 的执行核心。

---

## 2. 名词为什么存在

| 中文含义 | 代码名称 | 为什么需要 |
|---|---|---|
| 测试用例 | `TestCase` | 定义测什么，包括多轮输入、工具结果、评测要求和适用版本 |
| 被测目标 | `Target` | 定义怎样连接被测 Agent，也就是“测谁” |
| 目标版本 | `TargetVersion` | 同一 Agent 的不同版本可能使用不同地址或启动参数 |
| 执行方案 | `ExecutionProfile` | 保存 Provider 顺序、评判方式、并发和超时，也就是“怎么测” |
| 一次运行 | `Run` | 一次 MCP 提交产生的父任务，可包含一个或多个用例 |
| 单项执行 | `CaseRun` | 某个用例 × 某个版本 × 某次重复的实际执行 |
| 用例内工具结果 | `Fixture` | 用例作者为特定场景明确填写、只属于该用例的工具返回 |
| 共享工具样本 | `Sample` | 人工审核通过、可被多个用例确定性复用的工具返回 |
| 工具结果来源 | `Provider` | Fixture、Sample、Curator、Real Tool 都是工具结果来源 |
| 模拟生成 Agent | `SimulationCurator` | 前两个来源未命中时，根据当前上下文生成工具结果 |
| 证据评判 Agent | `EvidenceJudge` | 根据用例要求和完整证据做语义判断 |

三个维度不能混在一起：

```text
case_ids / selector    决定测什么
Target + version       决定测谁
ExecutionProfile       决定怎么测
```

---

## 3. 产品边界

### 3.1 V1 的主要使用方式

```text
开发者提出测试目标
  ↓
Claude Code / Codex 读取代码与 diff
  ↓
通过 MCP 查询和选择用例
  ↓
AgentRig 异步执行并保存证据
  ↓
平台 Judge 或 Claude Code / Codex 评判
  ↓
Claude Code / Codex 继续定位和修复代码
```

单用例和批量执行没有两套架构。运行一个用例只是 `run_cases` 收到一个 `case_id`。

### 3.2 V1 的部署边界

- 单工作区；
- 单个后端进程；
- 同一端口提供 `/mcp/`、`/api/` 和健康检查；
- 进程内 `asyncio` 调度；
- SQLite 用于本地快速启动；
- PostgreSQL 用于正式部署；
- Web 前端为独立 React 工程，通过 HTTP API 使用后端；
- 不提供账号、组织和 RBAC；
- MCP 与 HTTP 可配置统一访问 Token，本地使用时可关闭。

---

## 4. 总体架构

```text
┌─────────────────────────────────────────────────────────┐
│ Claude Code / Codex                                     │
│ 代码理解、选案、发起执行、读取原子证据、可选外部判定     │
└───────────────────────┬─────────────────────────────────┘
                        │ MCP
┌───────────────────────▼─────────────────────────────────┐
│ AgentRig 单体后端                                       │
│                                                         │
│ MCP / HTTP / CLI 薄入口                                 │
│           │                                             │
│ 用例服务 / Target 服务 / Profile 服务 / Sample 服务     │
│           │                                             │
│ Run Planner → RunScheduler → CaseExecutor               │
│                              │                          │
│             ┌────────────────┼────────────────┐         │
│             │                │                │         │
│          Driver       Tool Result Chain    Evaluators   │
│             │        Fixture → Sample       Rule        │
│             │        → Curator → Real       Judge       │
│             │                                 External  │
│             └────────────────┬────────────────┘         │
│                              │                          │
│                   Repository + Run Events               │
└───────────────────────┬─────────────────────────────────┘
                        │
┌───────────────────────▼─────────────────────────────────┐
│ 被测 Agent、MCP Tool Server、Real Tool、模型服务         │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│ Web 前端                                                │
│ 用例审核、配置管理、运行详情、Sample 审核                │
└───────────────────────┬─────────────────────────────────┘
                        │ HTTP API
                        └────────→ 同一个 AgentRig 后端
```

MCP 和 HTTP 只负责协议转换，不拥有自己的执行逻辑。V2 的平台助手也必须调用同一套业务服务，
不能复制执行链路。

---

## 5. 代码模块结构

### 5.1 仓库结构

```text
agentrig/
├── src/agentrig/
├── web/
├── migrations/
├── tests/
├── docs/
├── examples/
└── pyproject.toml
```

### 5.2 Python 后端结构

```text
src/agentrig/
├── cases/
│   ├── models.py
│   ├── schemas.py
│   ├── service.py
│   └── repository.py
│
├── targets/
│   ├── models.py
│   ├── schemas.py
│   ├── service.py
│   ├── repository.py
│   ├── registry.py
│   └── drivers/
│       ├── base.py
│       ├── http_sse.py
│       ├── pixcake_http_sse.py
│       ├── openai_compatible.py
│       └── subprocess.py
│
├── profiles/
│   ├── models.py
│   ├── schemas.py
│   ├── resolver.py
│   ├── service.py
│   └── repository.py
│
├── tool_results/
│   ├── models.py
│   ├── chain.py
│   ├── validator.py
│   ├── matcher.py
│   ├── service.py
│   ├── repository.py
│   └── providers/
│       ├── base.py
│       ├── fixture.py
│       ├── sample.py
│       ├── simulation_curator.py
│       └── real_tool.py
│
├── agents/
│   ├── model_client.py
│   ├── simulation_curator.py
│   ├── evidence_judge.py
│   ├── prompts/
│   └── schemas.py
│
├── evaluations/
│   ├── models.py
│   ├── rule_evaluator.py
│   ├── evidence_evaluator.py
│   ├── external_evaluator.py
│   ├── resolver.py
│   ├── service.py
│   └── repository.py
│
├── runs/
│   ├── models.py
│   ├── schemas.py
│   ├── planner.py
│   ├── scheduler.py
│   ├── executor.py
│   ├── event_recorder.py
│   ├── redactor.py
│   ├── service.py
│   └── repository.py
│
├── infrastructure/
│   ├── config.py
│   ├── secrets.py
│   ├── logging.py
│   └── database/
│       ├── session.py
│       ├── orm.py
│       └── repositories/
│
├── mcp/
│   ├── server.py
│   └── tools/
│
├── api/
│   ├── app.py
│   ├── dependencies.py
│   └── routes/
│
├── cli/
│   └── main.py
│
└── __main__.py
```

### 5.3 模块依赖规则

1. `api`、`mcp`、`cli` 只能调用各业务模块公开的 Service。
2. 业务模块不能导入 MCP、FastAPI 或前端概念。
3. SQLAlchemy ORM 和数据库 Session 只出现在 `infrastructure/database`。
4. 各业务模块声明 Repository 接口，数据库实现放在 infrastructure。
5. `runs` 负责执行编排，但不实现具体 Driver、Provider 或 Evaluator。
6. `agents` 只实现两个模型驱动的专用 Agent，不负责运行调度。
7. 不新建 `core`、`common`、`utils` 等容易无限堆放代码的目录；跨模块代码必须有明确归属。

### 5.4 当前 Alpha 代码如何处理

本次是重构，不维护内部兼容：

| 当前代码 | V1 归宿 |
|---|---|
| `case_runner.py`、`scenario_runner.py` | 重写到 `runs/executor.py` |
| `batch_runner.py` | 重写到 `runs/scheduler.py` |
| `simulator/`、`mock/` | 合并到 `tool_results/` |
| `judges/` | 拆到 `evaluations/` 和 `agents/` |
| `transports/`、`providers/` | 合并为 `targets/drivers/` |
| `storage/` | 重写为 SQLAlchemy Repository |
| `mcp_tools/` | 按业务组迁移到 `mcp/tools/` |
| `ab.py` | 不建设 Comparison Engine，只保留配对字段 |

---

## 6. 测试用例模型

### 6.1 一个用例的结构

```json
{
  "id": "case_...",
  "name": "创建订单后再次查询",
  "description": "验证多次工具调用之间的状态连续性",
  "review_status": "draft",
  "tags": ["cap.order.create", "cap.order.query", "L1"],
  "supported_versions": ["1.0.0", "1.1.0"],
  "primary_evaluator": "evidence_judge",
  "initial_state": {
    "tenant_id": "demo",
    "asset_refs": ["asset://seed/orders.json"]
  },
  "case_assertions": [],
  "case_rubric": "最终应确认订单已经创建，并返回同一个订单编号",
  "turns": [
    {
      "position": 1,
      "user_message": "帮我创建一个订单",
      "simulation_instruction": "库存充足，创建成功",
      "fixtures": [],
      "assertions": [],
      "rubric": null
    },
    {
      "position": 2,
      "user_message": "再查一下刚才的订单",
      "simulation_instruction": null,
      "fixtures": [],
      "assertions": [],
      "rubric": null
    }
  ]
}
```

这只是表达结构的示例，最终字段由 Pydantic Schema 固化。

### 6.2 多轮执行规则

- 一个用例包含一个或多个用户轮次；
- 每轮内部允许被测 Agent 多次调用工具；
- 当前轮 Agent 完成回复后，执行器才发送下一轮用户消息；
- 所有轮次共享本次 CaseRun 的对话历史和模拟状态；
- 不同 CaseRun 之间完全隔离。

### 6.3 初始化数据

`initial_state` 是任意 JSON 对象：

- AgentRig 核心不解释业务字段；
- Driver 的 `prepare()` 负责使用它初始化环境；
- Driver 可以提供可选 Schema 做提前校验；
- 文件使用资产引用，密钥使用 `env:` 引用；
- 二进制文件和明文密钥不能直接写入用例。

### 6.4 审核状态

| 状态 | MCP 可修改 | MCP 可删除 | 可执行 |
|---|---:|---:|---:|
| `draft` | 是 | 是 | 是 |
| `approved` | 否 | 否 | 是 |
| `rejected` | 是 | 是 | 是 |

只有人工可以通过 Web/HTTP API 将用例设为 `approved` 或 `rejected`。

V1 不建设用例修订历史：

- draft/rejected 原地修改；
- approved 不可修改；
- 每次运行保存完整 `case_snapshot`；
- 历史运行不依赖当前用例。

### 6.5 标签

- `cap.*` 表示能力标签，但不要求对应真实工具；
- `L0`、`P0`、`origin:error` 等都是普通标签；
- 标签直接保存在用例中；
- 不建设标签注册表；
- `list_tags` 动态聚合唯一标签和使用数量。

### 6.6 selector

V1 selector 字段：

```json
{
  "capabilities": ["cap.search", "cap.faq"],
  "tool_names": ["search_knowledge"],
  "tags": ["L0"],
  "review_status": ["draft", "approved"]
}
```

组合规则：

- 同一字段多个值为 OR；
- 不同字段之间为 AND；
- `tool_names` 同时检查 `cap.<tool>` 和轮次预期工具；
- 不支持嵌套布尔表达式；
- 未填写 `review_status` 时默认选择 draft + approved，排除 rejected；
- 明确传 `case_ids` 时不应用 selector 默认审核过滤。

selector 只在提交时解析一次。Run 保存实际选中的 `resolved_case_ids`，执行中不动态变化。

---

## 7. Target、版本和 Driver

### 7.1 Target

Target 表示怎样连接被测 Agent：

```yaml
id: local-photo-agent
name: 本地图片 Agent
driver_type: pixcake_http_sse
endpoint: http://localhost:8000/chat
secret_ref: env:LOCAL_AGENT_TOKEN
options:
  request_headers:
    x-client: agentrig
```

Target 可以预先保存，也可以在 `run_cases` 中临时传入。临时 Target 只进入本次运行快照，
不自动保存为长期资产。

MCP 可以创建、修改和删除 Target。Target 的创建/修改请求同时维护其版本列表，不再增加一组
TargetVersion MCP 工具。删除 Target 时一并删除其版本配置；历史运行继续使用自己的 Target
快照。

### 7.2 TargetVersion

版本是任意不透明字符串，不要求 SemVer：

```text
1.3.0
feature/search-v2
git:a84c120
model:gpt-5.2-prompt-07
```

TargetVersion 只保存相对 Target 的覆盖配置，例如：

```yaml
version: 1.3.0
endpoint: http://localhost:8013/chat
options:
  prompt_version: prompt-07
```

版本规划规则：

1. `run_cases` 明确传 version，只跑该版本。
2. 未传 version，按每个用例的 `supported_versions` 全部展开。
3. Target 有该版本独立配置时使用独立配置。
4. 没有独立配置时，使用默认 Target 配置并让 Driver 透传版本。
5. 用例支持 `*` 且 Target 登记了多个版本时，运行 Target 的全部版本。
6. 用例和 Target 都没有版本信息时，运行一次无版本任务。
7. 不实现版本范围、排序或自动兼容推断。

不兼容项进入结构化 skipped 列表，不阻塞其他任务。如果没有任何可执行任务，不创建 Run。

### 7.3 Driver 基础契约

```python
class AgentDriver(Protocol):
    def capabilities(self) -> DriverCapabilities: ...
    async def prepare(self, context: DriverPrepareContext) -> DriverSession: ...
    async def send_user_message(
        self, session: DriverSession, message: str
    ) -> AsyncIterator[DriverEvent]: ...
    async def send_tool_results(
        self, session: DriverSession, results: list[ToolResult]
    ) -> AsyncIterator[DriverEvent]: ...
    async def cancel(self, session: DriverSession) -> None: ...
    async def close(self, session: DriverSession) -> None: ...
```

正式 Driver 必须能：

- 建立执行；
- 发送用户输入；
- 输出文本或结构化事件；
- 报告完成或错误；
- 响应超时与取消；
- 关闭资源。

可选能力：

```text
streaming
multi_turn
tool_call_observation
tool_result_injection
session_resume
usage_metrics
full_trace
```

用例在运行前声明需要的能力。缺少能力时明确跳过，不能静默降级。

### 7.4 Driver 支持范围

正式支持：

- 通用 HTTP/SSE；
- Pixcake HTTP/SSE；
- OpenAI-compatible；
- 自定义 Python Driver 接口。

实验性支持：

- 本地 subprocess，只保证其明确声明的基础能力。

V1 不内置“被测 Agent 自身通过 MCP 工具暴露 chat/run”的 Driver。这类特殊目标使用自定义
Python Driver。

自定义 Driver 使用本地插件入口：

```yaml
driver_type: python
entrypoint: my_package.driver:MyAgentDriver
options:
  any_business_config: ...
```

MCP 不能上传或执行动态 Python 代码。插件必须已经安装在部署环境中，修改后重启服务生效。

### 7.5 统一 DriverEvent

所有 Driver 将协议转换为有限的统一事件：

```text
session_started
assistant_text_delta
assistant_message_completed
tool_calls
usage
completed
error
```

逐 Token 或 SSE 分片只在 Driver 和执行器内流转。持久化时合并为完整
`assistant_message`，不保存每个底层分片。

---

## 8. 三种工具控制方式

### 8.1 controlled

```text
被测 Agent 输出工具调用
  ↓
AgentRig 解析工具调用
  ↓
Provider 链生成工具结果
  ↓
AgentRig 将结果回传给被测 Agent
```

适用于当前 AgentScope 的外部工具循环。

### 8.2 proxy

```text
被测 Agent
  ↓ MCP
AgentRig MCP Proxy
  ↓
模拟返回或真实 MCP Tool Server
```

AgentRig 在代理层观察、替换或放行工具结果。被测 Agent 的业务工具挂载在 MCP Server 上，
属于该模式。

### 8.3 observe_only

被测 Agent 自己执行工具，AgentRig 只采集能够获得的 Trace，不注入结果。

Curator 只适用于 controlled 和 proxy。用例要求模拟工具结果但 Target 只有 observe_only
能力时，运行前直接跳过。

---

## 9. 工具结果 Provider 链

### 9.1 统一模型

Provider 链由 ExecutionProfile 配置：

```text
Fixture Provider
  → Sample Provider
  → Simulation Curator Provider
  → Real Tool Provider
  → fail
```

前一个 Provider 未配置、不可用或未命中时，继续下一个。每次尝试都写入
`provider_attempt` 事件。

默认开源配置：

```text
fixture → sample → fail
```

Curator 和 Real Tool 默认不启用。

### 9.2 Fixture Provider

Fixture 是用例作者直接写在某个用户轮次中的工具结果。

每轮 Fixture 是有序列表：

```json
{
  "tool_name": "create_order",
  "match_arguments": {
    "sku": "A-100"
  },
  "result": {
    "order_id": "O-001",
    "status": "created"
  },
  "repeatable": false
}
```

匹配规则：

1. 按工具名和可选参数条件匹配；
2. 未填写参数条件时匹配该工具的任意参数；填写时要求这些字段是实际调用参数的子集；
3. 返回第一个尚未消费的匹配项；
4. 默认只消费一次；
5. `repeatable=true` 时允许重复使用；
6. 未命中则进入 Sample Provider。

Fixture 只属于用例，不自动进入共享样本库。V1 不提供 Fixture 提升为 Sample 的操作。

### 9.3 Sample Provider

Sample 是共享、确定性、经过人工审核的工具结果。

Sample 可以保存：

- 单次工具调用结果；
- 有顺序的多步工具调用序列。

匹配规则：

1. 只查询 `approved` Sample；
2. 匹配工具、版本和规范化参数；
3. 可按工具配置需要忽略的动态字段；
4. 规范化后精确比较；
5. 命中多个时按稳定存储顺序返回第一条；
6. 不使用优先级、评分、LLM 选样或自定义 Python Matcher。

每次使用记录 `sample_id` 和匹配依据。

Sample 状态：

| 状态 | 是否可命中 | MCP 可修改/删除 |
|---|---:|---:|
| `draft` | 否 | 是 |
| `approved` | 是 | 否 |
| `disabled` | 否 | 否 |

批准和停用只能由人工通过 Web/HTTP API 操作。

### 9.4 Simulation Curator Provider

Provider 链包含 `simulation_curator` 本身就代表用户允许智能生成，不增加第二个授权开关。

Curator 输入：

- 当前工具名、调用参数和返回 Schema；
- 当前 CaseRun 此前的全部对话；
- 此前工具调用和实际采用的工具结果；
- 当前模拟状态；
- 用例场景背景和 `initial_state`；
- 本轮 `simulation_instruction`。

Curator 不能读取：

- 期望答案；
- Rule 断言；
- Evidence Judge rubric；
- 任何评分标准；
- 密钥或未脱敏认证信息。

这样避免 Curator 为了让用例通过而反向编造结果。

Curator 输出先进入统一 Validator：

1. 首次不合格，将明确校验错误反馈给 Curator；
2. 默认允许修正一次；
3. 仍不合格则本 Provider 失败并进入下一个 Provider；
4. 不合格结果绝不能交给被测 Agent。

同一 CaseRun 内的后一次 Curator 调用看到前面的全部可用上下文。不同 CaseRun、版本、重复轮次
和 A/B 分支完全隔离。

每次新 Run 默认重新生成，不跨运行缓存或复用。

保存的信息：

- 最终工具结果；
- 模型和配置版本；
- 各次生成与 Validator 成功/失败信息；
- 工具调用 ID 和 CaseRun ID。

完整上下文已经存在于运行事件中，不给 Curator 额外复制一份。

### 9.5 Real Tool Provider

Real Tool 可能产生副作用，必须同时满足：

1. 部署配置将工具或 Tool Server 加入允许列表；
2. ExecutionProfile 将 `real_tool` 放入 Provider 链。

默认允许列表为空。

Real Tool 的调用和结果自动保存为运行证据，但不会自动进入 Sample 库。用户明确调用
`create_sample(source_tool_call_id=...)` 后才创建 Sample 草稿，之后仍需人工审核。

取消运行不能自动回滚 Real Tool 已产生的副作用。

### 9.6 统一 Validator

所有 Provider 的最终结果都经过同一个 Validator，至少检查：

- 返回值符合工具结果 Schema；
- 必填字段存在；
- 数据大小不超过限制；
- 不包含禁止返回的敏感字段；
- Provider 声明的基础约束。

Validator 是确定性服务，不是 Agent。

---

## 10. 两个内置 Agent

### 10.1 实现方式

V1 不引入多 Agent 调度框架：

```text
SimulationCurator.generate(context) → ToolResultCandidate
EvidenceJudge.evaluate(evidence)    → EvaluationResult
```

两个 Agent：

- 各自有独立 Prompt；
- 各自有输入输出 Pydantic Schema；
- 各自保存 Prompt、模型和配置版本；
- 共用可替换的 `ModelClient`；
- 首先支持 OpenAI-compatible 模型服务。

模型配置只保存 `secret_ref: env:VARIABLE_NAME`，不保存 Key。

### 10.2 V2 如何复用

V2 平台助手只负责：

- 用例查询和选择；
- 组合 Target、版本和 Profile；
- 发起 Run；
- 查询证据；
- 调用已有 Curator/Judge；
- 形成用户可读结论。

它不会替换 V1 的 Planner、Scheduler、Executor、Provider 或 Evaluator。

---

## 11. 评判体系

### 11.1 三种主评判器

```text
rule
evidence_judge
external_controller
```

含义：

- `rule`：结构化规则给出主结论；
- `evidence_judge`：平台 Evidence Judge 给出主结论；
- `external_controller`：等待 Claude Code/Codex 回写主结论。

解析优先级：

```text
本次 run_cases 覆盖
  > ExecutionProfile 覆盖
  > 用例默认 primary_evaluator
```

最终配置按 CaseRun 冻结，同一 Run 内允许不同用例使用不同主评判器。

实际执行与主结论解析：

- 用例存在结构化断言时始终执行 Rule，并保存结果；
- 只有 `primary_evaluator=evidence_judge` 时自动调用 Evidence Judge；
- Codex/CC 提交外部判定属于显式动作，存在外部判定时以它作为当前主结论；
- 没有外部判定时，使用配置的 rule 或 evidence_judge 结果；
- `external_controller` 没有外部判定时保持 `awaiting_verdict`；
- 所有已经产生的评判结果分别展示，互不覆盖原始输出。

运行前检查：

- rule 至少有一条结构化断言；
- evidence_judge 至少有自然语言评测要求；
- external_controller 可以没有预设要求；
- 配置不完整时不调用被测 Agent，记录 `invalid_evaluation_config` 跳过项。

### 11.2 Rule Evaluator

V1 支持以下规则：

- 首个动作是工具调用、纯文本或拒绝；
- 必须调用指定工具；
- 禁止调用指定工具；
- 工具调用顺序；
- 工具参数期望值匹配；
- 工具参数符合指定 JSON Schema；
- 文本包含；
- 文本正则；
- 执行过程没有异常。

规则可以配置到具体轮次或整个用例。

V1 不支持：

- Python 脚本断言；
- 自定义表达式语言；
- 动态执行用户代码。

### 11.3 Evidence Judge

Judge 输入：

- 冻结用例和评测要求；
- 完整对话；
- 工具调用和工具结果；
- Provider 来源；
- Schema 校验；
- Rule 结果；
- 异常、超时和跳过原因。

Judge 输出：

```json
{
  "verdict": "pass | fail | inconclusive",
  "summary": "简短结论",
  "criteria": [
    {
      "criterion": "应返回创建后的订单编号",
      "verdict": "pass",
      "evidence_refs": ["evt_..."]
    }
  ],
  "evidence_refs": ["evt_..."]
}
```

不提供数值评分。

Judge 输出格式错误时允许一次内部修正重试。仍失败则记录 `evaluation_error`：

- 不伪装成 fail；
- 不伪装成 inconclusive；
- 被测 Agent 已经完成时，CaseRun 仍为 completed；
- Codex/CC 可以提交外部判定。

一次 CaseRun 只形成一份 Judge 结果或一份 evaluation_error，不建设 Judge 重判版本链。

### 11.4 外部判定

Codex/CC 使用与 Judge 相同的核心结构：

```text
verdict: pass | fail | inconclusive
summary
evidence_refs
```

每个 CaseRun 只保留一份当前外部判定。再次提交时重写这份判定，不保存
`supersedes_evaluation_id` 历史链。

外部判定只能修改自身结论，不能修改：

- 原始对话；
- 工具调用；
- 工具结果；
- Provider 轨迹；
- Rule 或 Judge 结果。

### 11.5 执行状态与评测结论分离

CaseRun 正常执行结束，即使判定为 fail，执行状态仍然是 completed。

评测结论：

```text
pass
fail
inconclusive
awaiting_verdict
evaluation_error
```

`external_controller` 尚未回写时为 `awaiting_verdict`，不自动回退到 Judge。

---

## 12. 统一执行流程

### 12.1 `run_cases` 提交

建议请求结构：

```json
{
  "case_ids": ["case_101", "case_102"],
  "selector": null,
  "targets": [
    {
      "role": "candidate",
      "target_id": "target_local",
      "version": null
    }
  ],
  "profile_id": "profile_core",
  "overrides": {
    "concurrency": 5
  },
  "repeat_count": 1
}
```

规则：

- `case_ids` 与 selector 二选一；
- targets 一个表示普通运行，两个表示 A/B；
- A/B 时角色为 baseline 和 candidate；
- V1 不接受三个以上 Target，避免进入多 Agent 评测；
- 可以使用保存的 Target，也可以传临时 Target；
- 不传 version 时按用例支持版本展开；
- 不传 Profile 时使用项目默认配置；
- 配置优先级为本次覆盖 > Profile > 项目默认。

### 12.2 Planner

Planner 按以下顺序工作：

1. 解析 case_ids 或 selector；
2. 加载用例并生成 case_snapshot；
3. 解析保存或临时 Target；
4. 展开版本；
5. 展开 repeat_count；
6. 按每个用例解析主评判器；
7. 检查审核状态、版本、Driver 能力和评判配置；
8. 将候选项分为可执行和 skipped；
9. 如果没有任何可执行项，直接返回错误和 skipped 列表；
10. 创建 Run，并为可执行项和 skipped 项分别创建 CaseRun；
11. 冻结 Profile、Target、版本和用例快照；
12. 将可执行 CaseRun 交给 Scheduler。

如果最终没有任何可执行 CaseRun，不创建 Run，直接返回结构化错误和 skipped 列表。

成功响应：

```json
{
  "run_id": "run_...",
  "status": "queued",
  "resolved_case_ids": ["case_101", "case_102"],
  "planned_case_runs": 4,
  "skipped_items": []
}
```

### 12.3 Scheduler

- 进程内 asyncio；
- 一个批次级 concurrency；
- 默认值和最大值来自部署配置；
- Profile 或本次调用可以请求 concurrency；
- 最终值不超过项目上限；
- 不做 Target、版本、Provider 多级限流；
- 单进程运行，不使用 Redis/Celery。

服务重启：

- 启动时将遗留 queued/running Run 和 CaseRun 标记为 interrupted；
- 不自动恢复；
- 已落库事件和结果保留；
- 是否重跑由 Codex/CC 决定。

### 12.4 CaseExecutor

```text
prepare Driver 与 initial_state
  ↓
发送当前用户轮次
  ↓
消费 DriverEvent
  ├─ 文本：累积
  ├─ 工具调用：写事件 → Provider 链 → 校验 → 回灌
  ├─ 错误：记录并结束
  └─ 完成：保存 assistant_message
  ↓
还有下一用户轮次？
  ├─ 是：继续，共享上下文和模拟状态
  └─ 否：运行 Evaluator
  ↓
更新 CaseRun 摘要与终态
```

### 12.5 异步查询

```text
get_run(run_id)
  → 父任务状态、计数和基础信息

list_case_runs(run_id)
  → 分页的单项摘要

get_case_run(case_run_id)
  → 完整快照、事件和各评判器结果
```

单个 CaseRun 完成后立即可以查询，不必等待整批结束。

MCP 与 Web 都使用轮询。V1 不提供 Run 进度 WebSocket 或 SSE。

### 12.6 取消

`cancel_run`：

- queued CaseRun 直接 cancelled；
- running CaseRun 在下一个安全节点协作式停止；
- 不强行中断无法安全取消的外部请求；
- completed/failed/skipped 结果保留；
- 父 Run 最终为 cancelled；
- Real Tool 副作用不自动回滚。

### 12.7 失败和重跑

- CaseRun 失败后直接记录 failed；
- 平台不自动重跑；
- Curator/Judge 的一次格式修正不属于重跑；
- Codex/CC 要重跑时再次调用 `run_cases`；
- 新 Run 与旧 Run 没有 attempt 关系；
- V1 不实现幂等重试策略。

### 12.8 超时

只保留两层：

1. `case_timeout_seconds`：整个 CaseRun 总时限；
2. Driver、Real Tool、Curator、Judge 的单次请求超时。

不增加轮次超时或 Provider 链总超时。超时不自动重试。

---

## 13. A/B 运行

A/B 使用同一个执行入口和 TargetVersion 机制，不建设单独执行链路。

每对 CaseRun 保存：

```text
role = baseline | candidate
comparison_pair_id
```

两边：

- 独立执行；
- 独立保存事件；
- 独立执行 Rule/Judge；
- Curator 使用各自完整上下文独立生成；
- 不共享 Curator 结果。

V1 不提供：

- `get_comparison_pair` MCP 工具；
- 后端工具调用 Diff；
- 文本 Diff；
- 时延 Diff；
- 对比 Judge；
- Comparison Engine。

Codex/CC 通过 list_case_runs 和 get_case_run 获取两边原子结果并自行比较。前端也可以在展示层
读取两边数据。

严格要求两边工具环境一致时，应使用 Fixture 或 approved Sample，不依赖 Curator。

---

## 14. 运行状态与事件

### 14.1 状态

Run：

```text
queued
running
completed
cancelled
interrupted
failed
```

CaseRun：

```text
queued
running
completed
failed
skipped
cancelled
interrupted
```

父 Run 的 failed 只表示计划或调度器发生致命错误。部分 CaseRun failed/skipped 时，父 Run 在
所有单项收尾后仍为 completed。

### 14.2 事件存储

每个 CaseRun 使用统一、按序追加的事件流：

```text
event_id
case_run_id
seq
event_type
payload
created_at
```

核心事件：

```text
user_message
assistant_message
tool_call
provider_attempt
tool_result
validation
usage
error
```

规则：

- 不为每类 Trace 建专用表；
- 工具调用、Provider 尝试、工具结果和错误及时落库；
- 流式文本合并为完整 assistant_message；
- 不保存底层 HTTP/SSE 原始帧；
- Judge 和外部判定通过 event_id 引用证据。

### 14.3 脱敏

所有事件在落库前经过统一 Redactor：

- 默认遮盖 authorization、cookie、api_key、token、secret；
- 项目配置可增加 JSON 字段路径；
- Driver 可声明额外敏感字段；
- 敏感值统一替换为 `[REDACTED]`；
- 不保存未脱敏副本。

Curator、Judge、MCP、HTTP 和 Web 只能读取脱敏证据。

---

## 15. ExecutionProfile

Profile 保存一套可复用执行方案：

```yaml
id: intelligent-regression
name: 智能回归
tool_mode: controlled
provider_chain:
  - fixture
  - sample
  - simulation_curator
primary_evaluator: evidence_judge
concurrency: 5
case_timeout_seconds: 300
component_timeouts:
  driver: 120
  curator: 30
  judge: 60
```

可配置内容：

- tool_mode；
- Provider 链和 Provider 配置；
- 主评判器覆盖；
- concurrency；
- case timeout；
- 各外部组件单次请求 timeout；
- repeat_count 默认值；
- Curator/Judge 模型配置引用。

不包含：

- case_ids；
- Target 版本；
- 用例内容；
- 明文 Key；
- 自动重跑策略。

MCP 可以创建、读取、修改和删除 Profile。删除后历史 Run 仍使用自己的 Profile 快照。

---

## 16. MCP 工具设计

原则：优先提供原子工具，不替 Codex/CC 编排已有工具。

### 16.1 用例与发现

```text
list_tags
list_test_cases
get_test_case
find_cases_by_tool
get_test_case_schema
create_test_case
update_test_case
delete_test_case
```

说明：

- `get_test_case_schema` 返回当前可写 Schema；
- update/delete 只能操作 draft/rejected；
- 不提供 MCP 审核工具。

### 16.2 执行与结果

```text
check_target
run_cases
get_run
list_case_runs
get_case_run
cancel_run
submit_external_verdict
```

不提供：

- run_single_case；
- rerun_case；
- get_comparison_pair；
- Judge 重判工具。

### 16.3 Target

```text
list_targets
get_target
create_target
update_target
delete_target
```

Target 详情包含 TargetVersion 列表，create/update 在同一个原子操作中维护版本配置。

### 16.4 ExecutionProfile

```text
list_execution_profiles
get_execution_profile
create_execution_profile
update_execution_profile
delete_execution_profile
```

### 16.5 Sample

```text
list_samples
get_sample
create_sample
update_sample
delete_sample
```

`create_sample` 支持两种输入：

- 直接提交样本内容；
- 提交 `source_tool_call_id`，从已保存 Real Tool 证据创建草稿。

MCP 不能批准或停用 approved Sample。

### 16.6 MCP 实现约束

- 工具只做参数解析、访问上下文和结果投影；
- 每个工具调用对应一个公开 Service 方法；
- 工具描述必须写清默认值、权限和返回大小；
- 不在 MCP 工具内直接访问 ORM；
- 不在 MCP 工具内编排另一个 MCP 工具；
- 服务错误统一转换为结构化错误码；
- MCP 不返回 secret_ref 对应的环境变量值。

### 16.7 MCP 服务形态

- 使用 Streamable HTTP，挂载在 `/mcp/`；
- MCP 请求本身保持无状态，Run 状态全部在数据库和 Scheduler 中；
- V1 只提供 Tools，不增加 MCP Resources 和 Prompts；
- Codex/Claude Code 的调用方法通过仓库 Skill 维护，不把长工作流复制进 Tool 描述；
- Skill 可以组合原子工具，但不能绕过后端权限和校验。

---

## 17. HTTP API 与 Web

HTTP API 与 MCP 使用相同 Service。

HTTP 独有的人工能力：

- approve/reject TestCase；
- approve/disable Sample。

V1 核心页面：

1. 用例列表和筛选；
2. 用例编辑；
3. 用例人工审核；
4. Target 与版本配置；
5. ExecutionProfile 配置；
6. Run 列表和进度；
7. CaseRun 完整事件与评判详情；
8. Sample 草稿和人工审核。

实施顺序：

```text
V1 阶段 1：核心模块 + 数据库 + HTTP + MCP
V1 阶段 2：接通核心 Web 页面
V2：平台内置对话执行助手
```

Web 使用 HTTP 定时查询进度，不建设 Run WebSocket/SSE。

---

## 18. 数据库设计

V1 使用 11 张核心表。

### 18.1 test_cases

关键字段：

```text
id
name
description
review_status
supported_versions JSON
primary_evaluator
initial_state JSON
case_assertions JSON
case_rubric
created_at
updated_at
```

### 18.2 case_turns

```text
id
case_id
position
user_message
simulation_instruction
fixtures JSON
assertions JSON
rubric
```

`(case_id, position)` 唯一。

### 18.3 case_tags

```text
case_id
tag
```

`(case_id, tag)` 唯一。`list_tags` 基于该表聚合。

### 18.4 samples

```text
id
name
tool_name
sample_kind
content JSON
match_arguments JSON
ignored_argument_paths JSON
supported_versions JSON
status
source_type
source_tool_call_id
created_at
updated_at
```

### 18.5 targets

```text
id
name
driver_type
endpoint
secret_ref
options JSON
created_at
updated_at
```

### 18.6 target_versions

```text
id
target_id
version
endpoint_override
options_override JSON
created_at
updated_at
```

`(target_id, version)` 唯一。

### 18.7 execution_profiles

```text
id
name
description
config JSON
created_at
updated_at
```

### 18.8 runs

```text
id
status
selection_snapshot JSON
resolved_case_ids JSON
profile_snapshot JSON
target_snapshots JSON
total_count
completed_count
failed_count
skipped_count
cancelled_count
created_at
started_at
finished_at
error_code
error_message
```

### 18.9 case_runs

```text
id
run_id
case_id
case_snapshot JSON
target_snapshot JSON
profile_snapshot JSON
version
repeat_index
comparison_pair_id
comparison_role
status
primary_evaluator
evaluation_state
started_at
finished_at
error_code
error_message
summary JSON
```

### 18.10 run_events

```text
id
case_run_id
seq
event_type
payload JSON
created_at
```

`(case_run_id, seq)` 唯一。

### 18.11 evaluations

```text
id
case_run_id
evaluator_type
evaluator_source
status
verdict
summary
criteria JSON
evidence_refs JSON
config_snapshot JSON
model_metadata JSON
created_at
updated_at
```

`(case_run_id, evaluator_type)` 唯一：

- Rule 只保存一次；
- Judge 只保存一次；
- external_controller 再次提交时更新当前记录。

### 18.12 数据库实现

- SQLAlchemy 2.x；
- Alembic migration；
- SQLite 和 PostgreSQL 使用同一领域 Schema；
- 数据库差异限制在 infrastructure；
- 测试套件至少包含 SQLite 全量测试和 PostgreSQL 核心集成测试；
- V1 不支持 MySQL。

---

## 19. 配置与密钥

部署配置保存：

- database URL；
- 默认并发和最大并发；
- 默认 Profile；
- Driver 插件允许列表；
- Real Tool 允许列表；
- 默认超时；
- 脱敏字段；
- MCP/HTTP 访问 Token 引用。

用户可管理数据保存在数据库：

- Target 和 TargetVersion；
- ExecutionProfile；
- TestCase；
- Sample；
- Run 与 Evidence。

密钥只支持：

```text
secret_ref: env:VARIABLE_NAME
```

V1 不支持：

- Vault；
- 云 Secret Manager；
- 自定义 Secret Resolver；
- 数据库明文 Key；
- MCP 提交明文 Key。

---

## 20. 错误模型

所有入口使用统一错误结构：

```json
{
  "code": "invalid_evaluation_config",
  "message": "rule evaluator requires at least one assertion",
  "details": {
    "case_id": "case_101"
  },
  "retryable": false
}
```

建议错误分类：

```text
validation_error
not_found
permission_denied
target_unreachable
driver_capability_missing
version_incompatible
invalid_evaluation_config
provider_exhausted
tool_result_invalid
case_timeout
component_timeout
cancelled
interrupted
evaluation_error
internal_error
```

`retryable` 只是向 Codex/CC 提供事实，不触发平台自动重试。

---

## 21. 实施顺序

### 阶段 0：冻结契约

- 将本文作为 V1 架构基线；
- 为核心 Pydantic Schema 写契约测试；
- 固定错误码和状态枚举；
- 清理旧文档中“三个核心 Agent 已确认”等冲突结论。

### 阶段 1：数据与业务骨架

- 新建模块化目录；
- SQLAlchemy ORM 和 Alembic；
- TestCase、Target、Profile、Sample CRUD；
- SQLite + PostgreSQL Repository；
- 审核权限规则；
- 部署配置与 env secret resolver。

### 阶段 2：最小可运行纵切

优先跑通：

```text
create_test_case
  → run_cases
  → HTTP/SSE Driver
  → Fixture Provider
  → Rule Evaluator
  → get_run / list_case_runs / get_case_run
```

该阶段就要支持：

- 单用例和批量共用入口；
- 异步 Run ID；
- 受限并发；
- 多轮；
- 事件持续落库；
- 取消和超时；
- 配置快照。

### 阶段 3：完整工具结果链

- Sample Provider；
- 统一 Validator；
- Simulation Curator；
- Real Tool 双重授权；
- controlled 和 observe_only；
- MCP Proxy 模式。

### 阶段 4：完整评判

- Evidence Judge；
- 外部判定；
- 三种主评判器；
- evidence_refs；
- evaluation_error；
- A/B 配对字段。

### 阶段 5：Driver 覆盖

- 通用 HTTP/SSE；
- Pixcake HTTP/SSE；
- OpenAI-compatible；
- 自定义 Python Driver；
- 实验性 subprocess；
- Driver capability contract tests。

### 阶段 6：MCP 与 Skill

- 完成本文定义的原子 MCP 工具；
- 重写 Codex/Claude Code Skill；
- Skill 只做调用顺序指导，不复制业务规则；
- 端到端验证 Codex 选案、执行、查询、回写判定。

### 阶段 7：Web

- 用例与 Sample 审核；
- Target/Profile 管理；
- Run/CaseRun 详情；
- 三类评判结果展示；
- HTTP 轮询。

---

## 22. 测试策略

### 22.1 单元测试

- selector OR/AND；
- 版本展开；
- Profile 解析优先级；
- Driver 能力匹配；
- Fixture 消费；
- Sample 规范化匹配；
- Provider 降级；
- Rule Evaluator；
- 状态转换；
- Redactor。

### 22.2 契约测试

- 每个正式 Driver 的 DriverEvent；
- 自定义 Driver 插件加载；
- MCP 输入输出 Schema；
- HTTP 与 MCP 调用同一 Service 后结果一致；
- SQLite/PostgreSQL Repository 行为一致；
- Curator/Judge 输出 Validator。

### 22.3 集成测试

- 单用例异步执行；
- 批量并发与部分完成查询；
- 多轮工具调用；
- Fixture → Sample → Curator → Real Tool；
- Evidence Judge 开关；
- external_controller 回写；
- A/B 配对；
- 取消；
- 服务重启标记 interrupted；
- Real Tool 未授权拒绝。

### 22.4 端到端验收

至少提供三个 Demo：

1. HTTP/SSE Agent + controlled Fixture；
2. OpenAI-compatible Agent + Evidence Judge；
3. Agent 使用 MCP 工具 + AgentRig Proxy + Sample/Curator。

Pixcake Driver 使用当前 AgentScope 用例做真实回归验证。

---

## 23. V1 完成标准

### 执行

- 一个 `run_cases` 同时覆盖单个和批量；
- 异步返回 Run ID；
- 支持明确 case_ids 和 selector；
- 支持多版本、重复执行和 A/B；
- 支持部分跳过；
- 支持取消、超时和服务重启中断；
- 支持执行中查询已完成单项。

### 工具环境

- Fixture、Sample、Curator、Real Tool Provider 可配置排序；
- Fixture 有序一次性消费；
- Sample 只使用 approved 数据；
- Curator 与评测答案隔离；
- Real Tool 默认关闭并双重授权；
- 每个工具结果来源可追溯。

### 评判

- Rule、Judge、External 结果分别保存；
- 支持每用例不同主评判器；
- Judge 不输出数值分；
- 外部判定可以重写当前外部结果；
- 执行状态与评测结论分开。

### 接入

- 四类正式 Driver 和一个实验性 Driver；
- controlled、proxy、observe_only；
- 自定义 Python Driver；
- Driver 能力不满足时明确跳过。

### 数据与安全

- SQLite 和 PostgreSQL；
- 11 张核心表；
- CaseRun 快照；
- 统一事件流；
- 落库前脱敏；
- 密钥仅引用环境变量；
- MCP 不提供人工审核能力。

### 界面

- 用例和 Sample 人工审核；
- Target/Profile 管理；
- Run/CaseRun 详情；
- 分别展示 Rule、Judge、Codex/CC 结果。

---

## 24. 明确延后

以下能力不进入 V1：

- Regression Manager；
- 平台内置对话执行助手；
- AgentTeams 编排；
- 多 Agent 评测与用例归属；
- 用例集/Suite；
- 标签注册表；
- 用例修订历史；
- Fixture 自动提升 Sample；
- Sample 优先级和 LLM 选样；
- 自定义 Sample Matcher；
- Curator 跨运行缓存；
- Judge 数值评分和多次重判；
- 外部判定版本链；
- 自动重跑与 attempt；
- Comparison Engine 和 A/B 聚合工具；
- 分布式队列和任务恢复；
- Target/Profile 软删除；
- 外部 Secret Manager；
- Run WebSocket/SSE；
- 逐 Token 和原始协议帧持久化；
- 开源 Core 内置 Pixcake chat_channel。

这些能力只有出现真实用户需求后才重新设计，不能为了未来可能性提前进入 V1。

---

## 25. 最终开发原则

1. Claude Code/Codex 很强，平台提供原子事实，不重复建设低上下文编排 Agent。
2. 只有需要模型推理的 Curator 和 Judge 才是 Agent。
3. 执行、校验、状态、路由和存储必须保持确定性。
4. 一个执行入口覆盖单个和批量，不提供重复包装。
5. 配置在启动时冻结，历史运行依赖自己的快照。
6. 工具结果必须可解释来源，智能生成必须先校验。
7. 评判不能修改证据，执行状态不能被 pass/fail 污染。
8. MCP 与 HTTP 都是薄入口，业务逻辑只实现一次。
9. V1 优先完成可工作的纵向闭环，再扩展协议覆盖和界面。
10. 没有真实需求的抽象、状态、表和聚合工具不进入 V1。
