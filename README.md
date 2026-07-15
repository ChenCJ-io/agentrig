# AgentRig

> 面向 AI agent 的 MCP 原生测试台。
>
> *每次改动都在长用例，每次发版都跑全量。*
>
> *The MCP-native test rig for AI agents. Every change grows the suite, every
> release runs it all.*（开源发布时本 README 翻译为英文）

AgentRig 是一个为 MCP 时代构建的 agent 回归测试平台。它让你的编码 agent
（Claude Code、Codex）拥有业务 agent 的回归闭环 —— 构建测试场景、通过工具层
proxy 回放、随开发持续积累回归用例。

## 状态

🚧 早期开发（`v0.1.0a0`），尚未生产可用。

设计文档见 [`docs/`](./docs/)。CC 测试 skill 包见 [`skills/`](./skills/)。一键验收 `uv run agentrig demo`（见 [`验收清单`](./docs/acceptance.md)）。

## 快速开始

需 Python 3.12+ 和 [uv](https://docs.astral.sh/uv/)。

```bash
uv sync --extra dev
uv run agentrig serve
```

MCP server 暴露在 `http://127.0.0.1:8000/mcp`。健康检查：

```bash
curl -X POST http://127.0.0.1:8000/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","clientInfo":{"name":"t"},"capabilities":{}}}'

curl -X POST http://127.0.0.1:8000/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"ping","arguments":{}}}'
# → result.content[0].text == "pong"
```

完整端到端（构建用例 → 跑 → 看判定）见 [`docs/quickstart.md`](./docs/quickstart.md)。

## 开发

```bash
uv run ruff check      # 代码规范检查
uv run mypy            # 类型检查（strict 模式）
uv run pytest          # 单元测试
```

## License

MIT —— 见 [LICENSE](./LICENSE)。
