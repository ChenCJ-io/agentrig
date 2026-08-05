# AgentRig

[English](./README.en.md) | 中文

> 面向 AI Agent 的 MCP 原生回归测试台。

AgentRig V2 在 V1 确定性评测内核上增加智能评测助手：AgentTeams Manager 把自然语言目标
整理成可预览、确认和幂等提交的 EvaluationPlan；Simulation Curator 与 Evidence Judge
作为两个职责隔离的 Worker，在准确的执行节点接受任务。AgentRig 仍负责运行、权限、证据和
评判事实，AgentTeams 负责多 Agent 协作，不替代 V1 Core。

两个专业 Agent 既可使用 V1 本地模型适配器，也可切换到 AgentTeams Worker：

- **Simulation Curator**：在 Fixture 和 approved Sample 未命中时，根据当前 CaseRun
  上下文生成并校验工具结果。
- **Evidence Judge**：根据 rubric 和已存档证据输出 pass、fail 或 inconclusive。

AgentTeams 默认关闭，因此原有 V1 HTTP、MCP、Web 和 CLI 行为保持兼容。Core 模式无需模型
Key；控制方也可以关闭 Evidence Judge，自行读取 CaseRun 后调用
`submit_external_verdict`。

## 已实现能力

- 单用例、批量、多版本、重复和双 Target A/B 共用一个异步 `run_cases`。
- stdio ACP（官方 Python SDK）、HTTP/SSE、Pixcake HTTP/SSE、OpenAI-compatible、
  allowlisted Python Driver，以及实验性 JSONL subprocess Driver。
- controlled、CaseRun 级 MCP proxy、observe-only 三种工具控制方式。
- ACP Target 可按 CaseRun 注入 MCP Proxy，并隔离 Agent 的运行目录、会话数据和日志。
- Fixture → Sample → Simulation Curator → Real Tool 可配置 Provider 顺序。
- Rule、Evidence Judge、External Controller 分别存档，主评判器决定当前状态。
- SQLite / PostgreSQL async SQLAlchemy、17 张表、Alembic 迁移和运行快照。
- V2 会话事件流、EvaluationPlan 状态机、AgentInvocation 生命周期与断线恢复。
- V2.1 结构化 DecisionRecord、证据存在性校验、Core 策略门禁、并发幂等和质量指标。
- Matrix Bridge、AgentTeams 三角色部署包和 Manager/Worker 独立 MCP 权限面。
- HTTP/SSE API、Streamable HTTP MCP、React 管理界面和 10 份控制/协作 Skill。

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
| V2 助手 API | `http://127.0.0.1:8000/api/v2/` |
| 编码 Agent MCP | `http://127.0.0.1:8000/mcp/` |
| Manager MCP | `http://127.0.0.1:8000/mcp/manager/` |
| Curator / Judge MCP | `http://127.0.0.1:8000/mcp/curator/`、`/mcp/judge/` |
| 被测 Agent 工具 Proxy | `http://127.0.0.1:8000/proxy` |

Codex MCP 配置：

```toml
[mcp_servers.agentrig]
url = "http://127.0.0.1:8000/mcp/"
# 启用 server.api_token_ref 时取消下一行注释；Codex 从环境变量读取 Token。
# bearer_token_env_var = "AGENTRIG_ACCESS_TOKEN"
```

首次可先跑不依赖外部服务的纵向验收：

```bash
uv run agentrig demo
```

本仓库已提供 lassist/Pixcake + AgentTeams v1.1.2 + DeepSeek V4 Flash 的本机
一键演示配置。真实 Key 只放在被 Git 忽略的 `.env.local-agentteams`：

```bash
scripts/local_demo.sh all
```

命令会保留本地 SQLite 和 AgentTeams Docker volume，可重复运行。完成后直接访问
`http://127.0.0.1:8010/targets/target_lassist_local/assistant`。完整搭建、交互和验收说明见
[本机演示与验收](./docs/04-本机演示与验收.md)。

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

本地 ACP Target 的启动脚本必须先由部署管理员加入 `subprocess_allowlist`。编码 Agent
可通过 MCP 的 `list_driver_types` 查看 Driver 是否已部署就绪，再用
`get_target_schema(driver_type="acp")` 获取完整 options Schema 和无凭据示例。
`check_target` 会检查 command、cwd、allowlist、Secret 引用和隔离配置，并实际完成一次
不发送 prompt 的 ACP initialize/session 探针。

如启用访问鉴权，先设置实际 Token，再在配置中引用：

```bash
export AGENTRIG_ACCESS_TOKEN='replace-with-a-random-token'
```

浏览器首次收到 401 时会自动显示“设置访问令牌”对话框，也可以从右上角用户菜单打开。
令牌只保存在当前浏览器的本地存储中。Codex 需继承同名环境变量，并在 MCP 配置中设置
`bearer_token_env_var`。

容器内 ACP Agent 需要访问宿主机上的 Proxy。此时不要继续使用回环地址；应同时启用
Token，并显式配置容器可达地址：

```toml
[server]
host = "0.0.0.0"
port = 8000
api_token_ref = "env:AGENTRIG_ACCESS_TOKEN"

[proxy]
public_url = "http://host.docker.internal:8000/proxy"
```

AgentRig 会把服务 Token 和 CaseRun 的短期 Scope 一起注入 ACP MCP 配置。不要在
`agentrig.toml`、Target 或 Codex 配置中写入实际 Token。

## 开发校验

```bash
uv run ruff check src tests examples
uv run mypy src/agentrig
uv run pytest
cd web && npm run typecheck && npm run test:coverage && npm run e2e && npm run build
```

架构、接口边界和模块说明见 [docs](./docs/README.md)，编码 Agent 工作流见
[skills](./skills/README.md)。AgentTeams 比赛环境配置、三角色包构建和部署步骤见
[deploy/agentteams](./deploy/agentteams/README.md)。

## 状态

当前版本为 `0.2.0a0`。V2 实现已落地，并提供真实 AgentTeams、Matrix、lassist 和
DeepSeek 的本机联调路径；仍处于 Alpha 阶段，不建议直接作为无人值守的生产发布门禁。

## License

MIT — 见 [LICENSE](./LICENSE)。
