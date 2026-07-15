# AgentRig

English | [中文](./README.md)

> The MCP-native test rig for AI agents.
>
> *Every change grows the suite. Every release runs it all.*

AgentRig is a regression testing platform for the MCP era. It gives your coding
agent (Claude Code, Codex) a regression loop for business agents — build test
scenarios, replay them through a tool-layer proxy, and accumulate regression
cases as you develop.

## Status

🚧 Early development (`v0.1.0a0`), not production-ready.

Design docs: [`docs/`](./docs/). CC test skill pack: [`skills/`](./skills/).
One-command acceptance: `uv run agentrig demo` (see [`acceptance`](./docs/acceptance.md)).

## Quick start

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync --extra dev
uv run agentrig serve
```

The MCP server is at `http://127.0.0.1:8000/mcp`. Health check:

```bash
curl -X POST http://127.0.0.1:8000/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","clientInfo":{"name":"t"},"capabilities":{}}}'

curl -X POST http://127.0.0.1:8000/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"ping","arguments":{}}}'
# → result.content[0].text == "pong"
```

For the full end-to-end (build a case → run → see the verdict), see
[`docs/quickstart.md`](./docs/quickstart.md).

## Development

```bash
uv run ruff check      # lint
uv run mypy            # type check (strict)
uv run pytest          # tests
```

## License

MIT — see [LICENSE](./LICENSE).
