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
- HTTP/SSE API、Streamable HTTP MCP、React 管理界面和 11 份控制/协作 Skill。

## 快速开始

要求 Python 3.12+、[uv](https://docs.astral.sh/uv/)；构建 Web 需要 Node.js 20+。

```bash
uv sync --extra dev
cd web && npm ci && npm run build && cd ..
uv run agentrig db upgrade
uv run agentrig serve
```

持久化数据库不会再由 ORM 静默补表：服务启动时会校验 Alembic revision，未初始化或版本
落后会直接报错，请先执行 `uv run agentrig db upgrade`。内存 SQLite 测试库仍会自动建表。

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

仓库还提供不依赖私有项目、模型或网络的
[Public Reference Target](./examples/reference_target/README.md)，用于稳定复现成功、策略回归和
显式恢复三种场景：

```bash
scripts/reference_demo.sh all --profile reference-ci
```

该命令会启动 AgentRig 与公开 Target，执行成功、A/B 策略回归和显式恢复场景，并生成可离线
验真的提交证据目录：`agentrig.release-evidence.v1` manifest、紧凑运行证据、CycloneDX 1.6
SBOM、公开配置、依赖锁文件快照和 `SHA256SUMS`。在干净 checkout 中可执行严格验收：

```bash
scripts/reference_demo.sh validate-evidence --require-clean-source
```

产物和子命令详见 Reference Target 文档。

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
# 仅当可信反向代理会剥离并重写身份 Header 时启用。
# trusted_principal_header = "x-authenticated-user"

[database]
url = "sqlite+aiosqlite:///./.agentrig/agentrig.db"

[proxy]
public_url = "http://127.0.0.1:8000/proxy"
backends = { business = "http://127.0.0.1:9001/mcp/" }

[execution]
default_concurrency = 4
max_concurrency = 20
max_repeat_count = 20
max_cases_per_run = 200
max_planned_case_runs = 1000
real_tool_allowlist = []
python_driver_allowlist = []
subprocess_allowlist = []

[target_network]
allow_private_networks = false
# 本地开发默认允许以下三个主机；共享/生产环境应收窄为实际 Target 主机。
allowed_hosts = ["localhost", "127.0.0.1", "::1"]

[reporting]
# 超限时明确拒绝，避免浏览器静默下载不完整报告或证据包。
max_report_case_runs = 10000
max_export_records = 10000
```

Target 和模型凭据只保存 `env:VARIABLE_NAME` 引用，不接受明文 Key。Real Tool 还需要部署
allowlist、ExecutionProfile Provider 链和用户授权同时成立。

Target 的 HTTP(S) 地址在保存和每次运行前都会经过出站策略校验。未显式放行时，链路本地、
回环、私网和解析到非公网地址的主机会被拒绝；生产环境不要使用
`allow_private_networks = true`，应在 `allowed_hosts` 中逐项配置受信主机（支持 `*.example.com`）。

评测报告和 JSON/Markdown/HTML 数据导出由服务端遍历完整分页生成，并复用运行证据脱敏器。
生成期间数据集合发生变化会返回可重试冲突；超过 `[reporting]` 上限会明确拒绝，不会截断文件。

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
uv run ruff check src tests scripts examples
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
