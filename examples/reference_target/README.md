# Public Reference Target

这是 AgentRig 的公开、确定性 HTTP/SSE 被测 Agent。它不调用模型、不访问外部网络，也不包含
lassist/Pixcake 的私有业务逻辑；用途是在干净环境中复现 AgentRig 的协议、受控工具、规则评判、
A/B 回归和失败恢复链路。

## 一键复现

要求 Python 3.12+、uv、Node.js 20+、npm 和 curl。首次安装依赖需要访问相应的软件源；Target
及场景执行本身不访问外部服务，也不需要 Docker、私有仓库或模型 Key。

```bash
scripts/reference_demo.sh all --profile reference-ci
```

`all` 会依次完成锁定依赖安装、Web 构建、SQLite migration、两个回环服务启动、幂等种子、
服务和能力验证、三个场景执行、结论校验及脱敏证据导出。默认地址为：

| 服务 | 地址 |
|---|---|
| AgentRig Web/API | `http://127.0.0.1:8020` |
| Reference Target | `http://127.0.0.1:8091` |

运行状态保存在被 Git 忽略的 `.agentrig/reference-demo/`：

- `latest-runs.json`：已核验的场景与 Run/CaseRun ID；
- `evidence/reference-demo-*/reference-evidence.json`：紧凑证据包；
- `reference-evidence.md`：可读摘要；
- `SHA256SUMS`：JSON/Markdown 完整性校验；
- `agentrig.db` 和 `logs/`：可继续查询的本地状态与排障日志。

可拆分执行：

```bash
scripts/reference_demo.sh setup
scripts/reference_demo.sh verify
scripts/reference_demo.sh run --scenario all
scripts/reference_demo.sh evidence
scripts/reference_demo.sh status
scripts/reference_demo.sh down
```

`setup` 和种子操作可重复执行；每次 `run` 都创建新的不可变 Run。`down` 只停止 PID 文件确认属于
本 Demo 的两个进程，保留数据库、日志和证据。端口和状态目录可通过
`AGENTRIG_REFERENCE_SERVER_PORT`、`AGENTRIG_REFERENCE_TARGET_PORT` 和
`AGENTRIG_REFERENCE_STATE_DIR` 覆盖。

当前公开入口交付的是完全确定性的 `reference-ci`。需要第三方凭据与 Matrix 的
`reference-agentteams` 完整协作模式是后续实施切片，不能用 CI 结果冒充三 Agent 协作证据。

## 仅启动 Target

协议开发时也可以单独启动靶场：

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

GitHub Actions 的 `Public reference demo` job 会从 checkout 直接运行同一个 `all` 命令并上传证据
artifact，避免文档命令与实际验收路径分叉。
