# Contributing to AgentRig

感谢你帮助 AgentRig 变得更可靠。AgentRig 的核心承诺是：评测事实可复现、权限边界可验证、失败
不会被漂亮的输出掩盖。代码、测试和文档改动都应维护这些承诺。

提交前请先阅读[行为准则](./CODE_OF_CONDUCT.md)。使用问题见[支持指南](./SUPPORT.md)；安全漏洞
必须按[安全策略](./SECURITY.md)私密报告。

## 开始之前

- 搜索现有 Issue，避免重复工作；
- Bug 请提供最小复现、环境和脱敏日志；
- 较大的功能或架构改动先创建 Issue，说明动机、边界和兼容性；
- 不要在 Issue、PR、Fixture、截图或日志中提交 Token、Cookie、业务数据和本机绝对路径。

## 开发环境

需要 Python 3.12+、[uv](https://docs.astral.sh/uv/) 和 Node.js 20+。

```bash
git clone https://github.com/ChenCJ-io/agentrig.git
cd agentrig
uv sync --extra dev
cd web && npm ci && cd ..
```

验证安装：

```bash
uv run agentrig db upgrade
uv run agentrig demo
```

## 分支与改动范围

1. 从最新 `main` 创建短生命周期分支，例如 `feat/evidence-filter` 或 `fix/run-timeout`；
2. 让每个提交只表达一个可审阅意图；
3. 行为变化必须有测试，接口或工作流变化必须同步文档；
4. 不要混入本机数据库、生成缓存、Secret 或无关格式化；
5. 提交信息使用约定式前缀：`feat:`、`fix:`、`docs:`、`refactor:`、`test:`、`chore:`。

## 架构不变量

改动不应破坏以下边界：

- HTTP/MCP 入口只调用 Service，不直接访问 ORM；
- AgentTeams/Matrix 是可替换协作 Adapter，不进入 V1 Core 领域模型；
- Agent 输出不能直接改写 RunEvent、Rule 或执行终态；
- `completed` 只表示调度结束，不等于评测 `pass`；
- Manager、Curator、Judge 使用职责隔离的 MCP 工具面；
- Secret 只保存 `env:VARIABLE_NAME` 引用，持久化和导出必须脱敏；
- 重试、恢复和重复回执必须幂等，不能覆盖已经发生的历史；
- Real Tool、Python Driver 和 subprocess 必须经过部署 allowlist 与用户授权。

当前权威边界见[文档中心](./docs/README.md)。若实现与文档不一致，应在同一个 PR 中收敛。

## 验证矩阵

### Python

```bash
uv run ruff check src tests scripts examples
uv run mypy src/agentrig
uv run pytest
```

### Web

```bash
cd web
npm run typecheck
npm run test:coverage
npm run e2e
npm run build
```

### 公开纵向验收

```bash
scripts/reference_demo.sh all --profile reference-ci
scripts/reference_demo.sh validate-evidence --require-clean-source
scripts/reference_demo.sh down
```

### PostgreSQL

提供隔离测试库后运行：

```bash
export AGENTRIG_TEST_POSTGRES_URL='postgresql+asyncpg://user:pass@127.0.0.1/agentrig_test'
uv run pytest -q tests/v1/test_postgresql.py
```

PR 至少运行与改动相关的检查。合并到 `main` 前，CI 会覆盖 Python 3.12/3.13、PostgreSQL、
依赖审计、Reference Demo、证据校验、Web 单元/E2E/可访问性测试、构建和 wheel 隔离安装。

## 本地开发

```bash
# 终端 1：后端和生产 Web 静态资源
uv run agentrig serve

# 终端 2：前端热重载，/api 代理到后端
cd web && npm run dev
```

默认后端地址为 `http://127.0.0.1:8000`。完整配置、鉴权和网络安全边界见
[快速开始与安全部署](./docs/08-快速开始与安全部署.md)。

## 目录速览

```text
src/agentrig/
├── assistant/             会话、EvaluationPlan 与证据化决策
├── cases/                 TestCase、Turn、Selector 与审核规则
├── targets/drivers/       ACP、HTTP/SSE、Pixcake、OpenAI 等 Driver
├── profiles/              ExecutionProfile 与配置合并
├── tool_results/          Fixture、Sample、Curator、Real Tool Provider 链
├── agents/                Curator/Judge 端口与 invocation 生命周期
├── evaluations/           Rule、Judge、External 判定
├── runs/                  Planner、Scheduler、Executor、Event 与脱敏
├── integrations/agentteams/ Matrix Bridge 与协作 Adapter
├── mcp/                   Controller 与三角色 MCP 工具面
├── reporting/             报告、导出与 Release Evidence
└── infrastructure/        数据库、迁移、Secret 和网络策略

web/                       React Router 管理界面
skills/                    Core、Manager 与 Worker 的 11 项 Skill
examples/reference_target/ 公开确定性 Target 与场景资产
deploy/agentteams/          三角色部署包和配置模板
docs/                       权威架构、运行手册与比赛证据
```

## 文档和生成材料

- Markdown 以短段落、可执行命令和明确状态为主，避免把草稿写成已实现事实；
- Skill 必须声明输入、输出、依赖工具、失败处理、安全边界与版本；
- 中文 README 与英文 README 的能力、命令和成熟度必须同步；
- PPT、PDF 和视频由 `scripts/build_competition_deck.py`、`scripts/build_competition_video.py`
  重复构建，不手工制造与源文档不一致的副本；
- 截图和证据必须来自真实运行，并在提交前完成脱敏检查。

## Pull Request 要求

PR 描述应包含：

- 为什么需要这项改动；
- 做了什么，以及明确没有做什么；
- 风险、兼容性、migration 或回滚方式；
- 实际执行的验证命令与结果；
- 用户可见变化的截图、日志或证据引用。

维护者可以要求缩小范围、补测试或补文档。通过 CI 不代表一定合并，架构和安全边界同样属于
验收条件。
