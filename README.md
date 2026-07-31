# AgentRig

[English](./README.en.md) | 中文

> 面向 AI Agent 的 MCP 原生回归测试台。

AgentRig V1 由 Codex、Claude Code 或人工控制评测：控制方通过原子 MCP Tools 选择/构建
用例、提交异步 Run、读取脱敏证据，并可回写自己的判定。AgentRig 负责确定性执行、
工具结果控制、证据归档和多评判器存档。

V1 内置两个可选智能 Agent：

- **Simulation Curator**：在 Fixture 和 approved Sample 未命中时，根据当前 CaseRun
  上下文生成并校验工具结果。
- **Evidence Judge**：根据 rubric 和已存档证据输出 pass、fail 或 inconclusive。

两者都不是必需项。Core 模式无需模型 Key；控制方也可以关闭 Evidence Judge，自行读取
CaseRun 后调用 `submit_external_verdict`。

## 已实现能力

- 单用例、批量、多版本、重复和双 Target A/B 共用一个异步 `run_cases`。
- stdio ACP（官方 Python SDK）、HTTP/SSE、Pixcake HTTP/SSE、OpenAI-compatible、
  allowlisted Python Driver，以及实验性 JSONL subprocess Driver。
- controlled、CaseRun 级 MCP proxy、observe-only 三种工具控制方式。
- ACP Target 可按 CaseRun 注入 MCP Proxy，并隔离 Agent 的运行目录、会话数据和日志。
- Fixture → Sample → Simulation Curator → Real Tool 可配置 Provider 顺序。
- Rule、Evidence Judge、External Controller 分别存档，主评判器决定当前状态。
- SQLite / PostgreSQL async SQLAlchemy、11 张核心表、Alembic 迁移和运行快照。
- HTTP API、Streamable HTTP MCP、React 管理界面和三份 Codex/CC Skill。

## 快速开始

要求 Python 3.12+、[uv](https://docs.astral.sh/uv/)；构建 Web 需要 Node.js 20+。

```bash
uv sync --extra dev
cd web && npm ci && npm run build && cd ..
uv run agentrig db upgrade
uv run agentrig serve
```

默认地址：

| 入口 | 地址 |
|---|---|
| Web | `http://127.0.0.1:8000/` |
| HTTP API | `http://127.0.0.1:8000/api/` |
| 编码 Agent MCP | `http://127.0.0.1:8000/mcp/` |
| 被测 Agent 工具 Proxy | `http://127.0.0.1:8000/proxy` |

Codex MCP 配置：

```toml
[mcp_servers.agentrig]
url = "http://127.0.0.1:8000/mcp/"
```

首次可先跑不依赖外部服务的纵向验收：

```bash
uv run agentrig demo
```

## 最小配置

`agentrig.toml`：

```toml
[server]
host = "127.0.0.1"
port = 8000
# 公网或共享环境建议启用；这里只保存环境变量引用。
# api_token_ref = "env:AGENTRIG_ACCESS_TOKEN"

[database]
url = "sqlite+aiosqlite:///./.agentrig/agentrig.db"

[proxy]
public_url = "http://127.0.0.1:8000/proxy"
backends = { business = "http://127.0.0.1:9001/mcp/" }

[execution]
real_tool_allowlist = []
python_driver_allowlist = []
subprocess_allowlist = []
```

Target 和模型凭据只保存 `env:VARIABLE_NAME` 引用，不接受明文 Key。Real Tool 还需要部署
allowlist、ExecutionProfile Provider 链和用户授权同时成立。

如启用访问鉴权，先设置实际 Token，再在配置中引用：

```bash
export AGENTRIG_ACCESS_TOKEN='replace-with-a-random-token'
```

## 开发校验

```bash
uv run ruff check src tests examples
uv run mypy src/agentrig
uv run pytest
cd web && npm run typecheck && npm run build
```

架构、接口边界和模块说明见 [docs](./docs/README.md)，编码 Agent 工作流见
[skills](./skills/README.md)。

## 状态

当前版本为 `0.1.0a0`。V1 核心链路已实现，仍处于 Alpha 阶段，不建议直接作为无人值守的
生产发布门禁。

## License

MIT — 见 [LICENSE](./LICENSE)。
