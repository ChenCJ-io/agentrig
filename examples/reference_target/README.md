# Public Reference Target

这是 AgentRig 的公开、确定性 HTTP/SSE 被测 Agent。它不调用模型、不访问外部网络，也不包含
lassist/Pixcake 的私有业务逻辑；用途是在干净环境中复现 AgentRig 的协议、受控工具、规则评判、
A/B 回归和失败恢复链路。

## 启动

```bash
uv sync --extra dev
uv run uvicorn examples.reference_target.app:app \
  --host 127.0.0.1 \
  --port 8091 \
  --workers 1
```

另开一个终端检查：

```bash
curl --fail http://127.0.0.1:8091/healthz
curl --fail http://127.0.0.1:8091/
```

服务使用内存会话状态，因此 Reference CI 和本机演示必须保持单 Worker。它是协议靶场，不是生产
Agent 服务。

## AgentRig 资产

[`agentrig_assets.py`](./agentrig_assets.py) 提供可复用的构造器：

- Target：`target_reference_http_sse`，端点为 `http://127.0.0.1:8091`；
- 版本：`baseline` 和 `candidate-regression`；
- Profile：`profile_reference_fixture_only`，只使用 Fixture + Rule，不需要 Key；
- TestCase：成功、策略回归、恢复 Attempt 1 和恢复 Attempt 2。

等价的 Target 核心配置为：

```json
{
  "id": "target_reference_http_sse",
  "name": "Public deterministic HTTP/SSE reference target",
  "driver_type": "http_sse",
  "endpoint": "http://127.0.0.1:8091",
  "options": {
    "healthcheck_url": "http://127.0.0.1:8091/healthz"
  },
  "versions": [
    {"version": "baseline"},
    {"version": "candidate-regression"}
  ]
}
```

场景由 TestCase 的 `initial_state.reference` 精确选择：

| 场景 | 固定行为 | AgentRig 预期 |
|---|---|---|
| `reference_success` | 调用 `reference_lookup`，接收 Fixture 后完成 | Rule `pass` |
| `reference_policy_regression` | baseline 先确认后执行；candidate 先执行 | baseline `pass`，candidate `fail` |
| `reference_recovery` / `attempt=1` | 返回 HTTP 503 | CaseRun `failed`，错误码 `target_unreachable` |
| `reference_recovery` / `attempt=2` | 调用 `reference_healthcheck` 后完成 | 新 Run `pass`，旧失败 Run 不变 |

恢复场景故意拆成两个 TestCase 和两个 Run。AgentRig 不会覆盖第一次失败，也不会在没有授权时无限
重试；控制方明确创建第二个 Run 才进入恢复路径。

## HTTP/SSE 契约

初始消息：

```json
{
  "type": "chat",
  "message": "run",
  "version": "baseline",
  "initial_state": {
    "reference": {"scenario": "reference_success"}
  }
}
```

工具结果使用同一 `/chat/stream` 端点回灌：

```json
{
  "type": "tool_result",
  "session_id": "reference-session-000001",
  "version": "baseline",
  "tool_results": [
    {
      "tool_call_id": "reference-session-000001:reference_lookup",
      "name": "reference_lookup",
      "result": "{\"status\":\"ok\"}",
      "status": "success"
    }
  ]
}
```

成功响应为 `text/event-stream`，包含 `request_started`、`session_created`、文本或工具调用、
`usage`、`request_completed` 和 `[DONE]`。Request ID 由会话、请求类型和会话内序号组成；测试只
断言业务行为，不把具体 ID 当作结论。

## 验证

以下测试通过 ASGI transport 走真实 FastAPI 路由和正式 `HttpSseDriver`，再装配内存数据库、
RunExecutor、Fixture Provider、Rule Evaluator 和证据仓库：

```bash
uv run pytest -q tests/reference_target tests/v1/test_drivers.py
```

它会验证：

1. 健康检查和 SSE 协议；
2. 成功场景及 Fixture 证据；
3. 同一 Run 内 baseline/candidate 的稳定差异；
4. 503 被归类为 `target_unreachable`；
5. 恢复使用新 Run，第一次失败记录保持不变；
6. HTTP 错误正文和连接异常细节不会被投影到安全错误消息。

统一的 `scripts/reference_demo.sh` 编排入口属于下一实施切片；当前实现已提供它将复用的 Target、
Profile、TestCase 和端到端验收基线。
