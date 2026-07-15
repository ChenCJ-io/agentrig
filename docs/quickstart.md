# Quickstart：5 分钟跑通一条回归用例

用内置 demo agent 走完 AgentRig 的核心闭环：**起被测 agent → 编码工具（Claude Code）通过 MCP 构建用例 → 跑 → 看判定**。

## 前置

- Python 3.12+、[uv](https://docs.astral.sh/uv/)
- 装依赖：`uv sync --extra dev`

## 1. 起被测 agent（demo_agent）

`examples/demo_agent.py` 是内置的**确定性** agent（不经 LLM，按关键词路由）：
- 消息含 `echo` → 调 `echo` 工具
- 含 `reverse` → 调 `reverse` 工具
- 否则 → 直接回复文本

终端 A：

```bash
uv run uvicorn examples.demo_agent:app --port 9002
```

## 2. 起 AgentRig

终端 B（`AGENTRIG_AGENT__SERVER_URL` 指向 demo_agent → execution 走**真实 transport**）：

```bash
AGENTRIG_AGENT__SERVER_URL=http://127.0.0.1:9002 uv run agentrig serve
```

MCP 工具暴露在 `http://127.0.0.1:8000/mcp`。验证：

```bash
curl -sX POST http://127.0.0.1:8000/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","clientInfo":{"name":"qs","version":"0"},"capabilities":{}}}'
```

## 3. 把 AgentRig 配进 Claude Code

项目根 `.mcp.json`：

```json
{
  "mcpServers": {
    "agentrig": { "url": "http://127.0.0.1:8000/mcp" }
  }
}
```

装上 [`skills/core/`](../skills/) 三件套后，CC 就是「测试专家」，会按 skill 流程操作。

## 4. 让 CC 构建并跑用例

在 CC 里对它说：

> 用 agentrig 给 demo agent 写个用例：发 "please echo this"，期望它调用 echo 工具，然后跑。

CC 会（按 `build-test-case` skill）：
1. `upsert_test_case`（user_message + expected_tools=["echo"]）
2. 停下等你确认
3. 你确认后 `run_single_case`

## 5. 看判定

`run_single_case` 返回（关键字段）：

```json
{
  "passed": true,
  "reasons": [],
  "tool_calls": ["echo"],
  "transport": "real",
  "judge_mode": "rule",
  "missing_expected_tools": []
}
```

- `transport: "real"` → 连了真实 demo_agent（不是 echo 自测）
- `passed: true` → agent 调了 `echo`（符合 `expected_tools`）

若把 `expected_tools` 改成 `["reverse"]` 再跑 → `passed: false`，`reasons` 含 `expected_tools missing: ['reverse']`，`tool_calls: ["echo"]`——这就是一条能抓回归的用例。

## 6.（可选）proxy 模式 + 真实样本

让 agent 走 `/proxy` 用真实后端工具，录 trace 给 mock 当参考：

```bash
# 终端 C：真实后端 MCP server
uv run uvicorn examples.echo_backend:app --port 9001

# 终端 B 改成同时配 proxy 后端
AGENTRIG_AGENT__SERVER_URL=http://127.0.0.1:9002 \
AGENTRIG_PROXY__BACKENDS='{"echo":"http://127.0.0.1:9001/"}' \
uv run agentrig serve
```

agent 通过 `/proxy` 调工具后，让 CC 调 `get_real_tool_samples` 拿真实工具返回，写进下一条用例的 `mock`（零失真，贴合真实 agent 行为）。

---

## 降级模式（无被测 agent）

不配 `AGENTRIG_AGENT__SERVER_URL` 时，`run_single_case` 降级用 `EchoTransport`（按 `case.mock` 自呼自应）——**只能验证 mock 配置正确性，不测真实 agent**。适合 CI 冒烟 / 无 agent 环境的单测，不要当回归依据。

## 下一步

- [`skills/core/`](../skills/) —— CC 测试方法论三件套
- [`docs/`](./) —— 定位、执行模型、协议适配等设计文档
