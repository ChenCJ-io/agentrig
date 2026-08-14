# AgentScope 2.0 与 AG-UI Driver 方案

> 专题 ID：AR-V23-WP03
>
> 状态：Implemented（本地协议验收完成；AgentScope v2.0.6 Live 待执行）
>
> 优先级：P1
>
> 目标里程碑：V2.3

## 0. 实施状态（2026-08-11）

- `DriverEvent v2` 以严格 Schema 增量扩展 v1，覆盖 session/model/thinking/data/tool/permission/
  external execution/interrupt/resume/agent/memory/workspace 事件；
- 通用 `AgUiDriver` 与 `AgentScopeDriver` 已注册到 Driver registry，支持有序 cursor、事件
  去重、Agent path、Capability probe 及结构化 usage；
- 执行器将运行时事件归一到 RunEvent；thinking 只保存长度/类型，Memory、Data 和 Artifact 正文只
  保存摘要 hash，不导出 Secret；
- AgentScope live compatibility report 只保存 endpoint hash、版本、事件类型/序号/path/payload key 和
  usage key，不保存 prompt、reasoning 或 Tool body；
- `scripts/run_agentscope_live_acceptance.py` 与 opt-in live test 已实现。无 AgentScope endpoint 时测试
  明确 skip，不能用 mock report 替代 v2.0.6 Live 结果。

## 1. 目标

建立不绑定单一业务项目的 AgentScope 2.0 接入，并将 Runtime 的关键状态统一为 AgentRig 可保存、
评判和重放的证据。交付包括：

- 通用 `ag_ui` Driver；
- `agentscope_service` 原生 profile/adapter；
- 向后兼容的 `DriverEvent v2`；
- fire-and-forget 请求、长连接 stream、permission、interrupt/resume 状态机；
- AgentScope v2.0.6 固定兼容测试；
- Pixcake 现有专属 Driver 继续工作，不在首版删除。

## 2. 边界与原则

- AgentScope 是被测 Runtime，不进入 AgentRig Core。
- AG-UI 是通用互操作入口；原生 adapter 只处理 AgentScope 特有探针和 profile 默认值。
- Target 的 permission result 只是测试证据，AgentRig 的 Real Tool/外部写操作仍由 Core 授权。
- 不保存隐藏 chain-of-thought；thinking 只保存公开类型、长度、时间和 Runtime 明确允许的脱敏摘要。
- Driver v1 的现有事件继续可读；v2 通过新增事件和可选结构字段扩展。

## 3. Driver 架构

```text
AgentDriver v2 Protocol
  ├─ Existing drivers
  │    └─ v1 event compatibility adapter
  ├─ AGUIAgentDriver
  │    └─ standard run/event mapping
  └─ AgentScopeServiceDriver
       ├─ configurable endpoints
       ├─ session status/stream
       ├─ permission & external result resume
       └─ AgentScope capability probe
```

建议新增可选协议：

```text
DescribableAgentDriver.describe_capabilities(context)
ResumableAgentDriver.resume(session, input)
ExternalExecutionAgentDriver.submit_external_result(session, result)
ArtifactAwareAgentDriver.list_artifacts(session)
```

Planner 只依据 capability 决定用例可执行性，不使用 `isinstance` 判断某个具体 Runtime。

## 4. DriverEvent v2

### 4.1 事件类型

在现有事件基础上新增：

```text
SESSION_STATUS_CHANGED
MODEL_CALL_STARTED / MODEL_CALL_COMPLETED
THINKING_STARTED / THINKING_DELTA / THINKING_COMPLETED
DATA_PART
TOOL_CALL_STARTED / TOOL_CALL_ARGUMENTS_DELTA / TOOL_CALL_COMPLETED
TOOL_RESULT_OBSERVED
PERMISSION_REQUESTED / PERMISSION_RESOLVED
EXTERNAL_EXECUTION_REQUESTED / EXTERNAL_EXECUTION_RESOLVED
INTERRUPT_REQUESTED / INTERRUPTED / RESUMED
AGENT_STARTED / AGENT_COMPLETED
MEMORY_OPERATION
WORKSPACE_ARTIFACT
USAGE
COMPLETED / ERROR
```

现有 `TOOL_CALLS` 和文本事件保留。新 Driver 优先发细粒度事件；Event Normalizer 可派生兼容的聚合
事件供旧执行器消费，但不得重复计数。

### 4.2 公共结构

```json
{
  "schema_version": "agentrig.driver-event.v2",
  "event_id": "runtime-event-id",
  "type": "permission_requested",
  "occurred_at": "2026-08-10T00:00:00Z",
  "session_id": "...",
  "request_id": "...",
  "sequence": 12,
  "parent_event_id": "...",
  "agent_path": ["root", "researcher"],
  "payload": {},
  "raw_type": "REQUIRE_USER_CONFIRM",
  "source": "agentscope_service",
  "redaction": {"applied": true, "fields": []}
}
```

`event_id + source` 用于去重；`sequence` 只用于同一 stream 的顺序提示，不能假设跨连接全局连续。迟到
事件保留原时间，并记录 `received_at`。

### 4.3 结构化 payload

避免所有内容都进入任意字典，至少定义：

- `ModelCallPayload`：model、parameters hash、finish reason、usage；
- `PermissionPayload`：request id、action/tool、risk、allowed decisions、deadline；
- `InterruptPayload`：initiator、reason、graceful/forced、resume token ref；
- `AgentLifecyclePayload`：agent id、parent id、role、delegation reason summary；
- `MemoryOperationPayload`：read/write/delete、namespace hash、item refs、content exported=false；
- `WorkspaceArtifactPayload`：path hash/safe relative path、media type、size、digest、operation；
- `DataPartPayload`：media type、size、artifact ref，不默认内联二进制。

## 5. AgentScope Service 会话状态机

默认路径通过 Target options 配置，不写死在 Driver：

```text
POST chat request
  → accepted + session/request id
  → connect/reconnect session stream
  → running
     ├─ awaiting_permission → submit decision → running
     ├─ awaiting_external_result → submit result → running
     ├─ interrupting → interrupted → optional resume
     └─ idle/completed/error
```

关键规则：

- POST 超时但有 idempotency/request ID 时先查询状态，不直接重复提交；
- SSE/AG-UI 断开按 `Last-Event-ID` 或 Runtime 支持的 cursor 恢复；
- 不支持 cursor 时允许重新连接并依赖 event ID 去重；
- permission deadline 到期生成明确终态，不自动允许；
- CaseRun cancel 先请求 graceful interrupt，超过 deadline 才本地标记 interrupted；
- Driver close 不等于 Runtime cancel；两种事件分别保存。

## 6. 事件映射

| Runtime/AG-UI 语义 | DriverEvent v2 | RunEvent | 评测用途 |
|---|---|---|---|
| text message/chunk | thinking 或 assistant text | assistant_text/message | 输出质量、TTFT |
| model call begin/end | model_call_* | model_call | 延迟、usage、循环 |
| tool call/result | tool_call_*/result_observed | tool_call/tool_result | 参数、结果、权限 |
| require confirm | permission_requested | permission | 是否等待授权 |
| confirm result | permission_resolved | permission | 授权来源和决定 |
| external execution | external_execution_* | external_execution | 外部执行边界 |
| interrupt/resume | interrupted/resumed | lifecycle | 恢复完整性 |
| child agent | agent_started/completed | agent_lifecycle | 委派 provenance |
| memory middleware | memory_operation | memory_operation | 隔离/污染 |
| workspace output | workspace_artifact | workspace_artifact | 产物完整性 |

RunEvent 枚举可新增类型，但数据库 payload 继续使用统一 Redactor。不存在可靠 Runtime 事件时返回
`not_observed`，不得从文本猜测 permission 或 memory 行为。

## 7. Target 配置

```json
{
  "driver": "agentscope_service",
  "options": {
    "base_url": "http://127.0.0.1:8090",
    "chat_path": "/chat/",
    "session_stream_path": "/sessions/{session_id}/stream",
    "interrupt_path": "/sessions/{session_id}/interrupt",
    "protocol_profile": "agentscope-2.0",
    "credential_ref": "env:AGENTSCOPE_TOKEN",
    "stream_idle_timeout_seconds": 30,
    "max_reconnects": 3
  }
}
```

URL、重定向、DNS 和 loopback/allowlist 继续遵守现有 HTTP policy。路径模板只允许声明的变量，禁止
用户输入拼接任意 URL。

## 8. Capability

DriverCapabilities 扩展：

```text
permission_observation, permission_response,
interrupt, resume, external_execution,
nested_agents, model_call_observation,
memory_observation, workspace_artifacts,
multimodal, ordered_event_cursor
```

每项区分 `declared`、`observed`、`verified`。Planner 对必需能力：

- verified：执行；
- declared/observed：按 policy 执行并标记限制；
- unsupported：结构化 skipped；
- unknown：默认 inconclusive，不降级为 pass。

## 9. 安全

- permission token、resume token 和 credential 仅通过 Secret ref/短期内存传递；
- thinking/raw events 默认不导出正文；
- Tool 参数/结果和 artifact 路径先脱敏再落库；
- Runtime 请求 AgentRig 执行外部动作时仍经过 Provider Chain 和 Real Tool 三重授权；
- agent_path 不能作为权限主体，权限使用稳定 runtime identity；
- stream payload、事件数和单事件大小均有上限；
- 多模态二进制进入受控 artifact store，事件只保存 digest/ref。

## 10. 测试计划

### 10.1 确定性 Reference AgentScope Service

提供测试 fixture 覆盖：正常 stream、重连、重复/乱序事件、permission、拒绝、external execution、
interrupt/resume、child agent、usage 和 oversized event。

### 10.2 Contract tests

- v1 Driver 事件到 v2 的兼容；
- 每种 v2 payload 严格 Schema；
- event ID 去重和迟到排序；
- session 状态机的全部合法/非法转换；
- cancel、close、interrupt 的不同语义；
- Redactor 与 artifact 限制。

### 10.3 Live compatibility

固定 AgentScope v2.0.6，运行最小 ReAct、permission、resume 和 workspace 场景。版本升级先进入非阻断
nightly，更新兼容矩阵后再成为默认版本。

## 11. 实施切片

1. 定义 Event v2/Payload Schema 和 v1 compatibility adapter。
2. 实现通用 stream cursor、去重和 session state machine。
3. 实现 AG-UI Driver。
4. 实现 AgentScope profile/probe/resume adapter。
5. 接入 RunEvent、UsageSnapshot 和 Capability Snapshot。
6. 完成 reference fixture、live compatibility 和 Web 证据展示。

## 12. 验收标准

- [x] 现有 Pixcake/HTTP SSE/OpenAI/ACP Driver 测试继续通过；
- [x] AgentScope 的 permission、拒绝、interrupt、resume 和 external execution 全部可查询；
- [x] SSE cursor/事件 ID 去重保证重连不丢终态、不重复 Tool 副作用；
- [x] Target 内部确认不会给 AgentRig Real Tool 自动授权；
- [x] child agent 事件具有稳定 parent/agent path；
- [x] usage 能进入归一 UsageSnapshot；
- [x] hidden thinking、Secret 和未脱敏 artifact 不进入报告；
- [ ] 在真实固定 AgentScope v2.0.6 环境生成版本化 complete live compatibility report；
- [x] Runtime 不支持的能力被 skipped/inconclusive，而不是误报 pass。

## 13. 回滚与兼容

新 Driver 通过 registry 增量注册；关闭 profile 即可回滚。v2 RunEvent 采用新增枚举和 payload，不改变旧
事件。前端和导出器遇到未知事件显示通用事件卡片，不能崩溃或丢弃原始证据引用。
