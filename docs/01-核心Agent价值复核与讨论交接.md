# AgentRig 实现与接入

> 状态：Implemented（当前实现基线）
>
> 更新：2026-09-09
>
> 本文替代早期 Agent 价值讨论交接文档，记录当前代码结构与接入方式。系统边界与执行模型见
> [总体架构](./00-总体架构.md)。

## 1. 代码模块

```text
src/agentrig/
├── cases/                  TestCase、Turn、Selector、审核规则
├── targets/
│   ├── drivers/            ACP、HTTP/SSE、AG-UI、AgentScope、OpenAI、Python、subprocess、python_agent
│   ├── driver_schemas.py   Driver 级 JSON Schema 发现
│   └── agentscope_compat.py
├── profiles/               ExecutionProfile 与配置合并
├── tool_results/
│   ├── providers/          Fixture、Sample、Curator、Real Tool
│   ├── chain.py            顺序降级
│   └── validator.py        Schema、大小和敏感字段校验
├── agents/                 Simulation Curator、Evidence Judge、ModelClient 端口
├── runs/                   Planner、Scheduler、Executor、Manifest、Event、Redactor
├── jobs/                   耐久 Job 队列、lease/heartbeat、reaper、副作用围栏
├── capabilities/           Capability 快照规范化、observed 合并、A/B diff
├── evaluations/            Rule、Judge、External 判定存档
├── reporting/              RunReport、QualityReport、Comparison、ReleaseEvidence、导出
├── gates/                  版本化发布门禁
├── safety/
│   └── manifests/          安全套件清单与四态安全报告
├── production/             接入源、OTLP 归一、网关、Trace/Span、retention、Trace→Case
├── reviews/                ReviewItem、Annotation、GoldLabel、Evaluator 版本与对齐
├── failures/               FailureSignal、Pattern、Monitor、Webhook、复发时间线
├── projects/               Project、Environment、API Key 与 scope 鉴权
├── observability/          终态 Run 的 best-effort 元数据 OTLP 导出
├── assistant/              V2 助手会话、EvaluationPlan 状态机、Run 终态回写
├── target_chat.py          Target 直连探索会话（不产生 Run 与权威 Evaluation）
├── proxy/                  MCP 聚合与 CaseRun Scope
├── sdk/                    被测解释器内的 harness 与 Agno/LangGraph/函数适配（只依赖标准库）
├── casefiles/              仓库内的 project.yaml 与用例文件、agentrig test
├── infrastructure/
│   ├── database/           ORM、async Session、9 个 SQL Repository
│   ├── secrets.py          只解析 env: 引用
│   ├── http_policy.py      出站 URL、私网、DNS 与主机 allowlist 校验
│   └── validation.py
├── mcp/tools/              原子 MCP Tools
├── v1_api.py  v2_api.py    HTTP API
├── bootstrap.py            唯一 Service 装配点
└── app.py                  HTTP / MCP / Proxy / OTLP / Gateway / Web 进程入口
```

依赖方向从入口指向 Service、Repository 和 Driver/Provider 协议。MCP/HTTP 工具不直接访问
ORM，也不互相编排。

## 2. 数据库

默认 SQLite：

```bash
uv run agentrig db upgrade
```

PostgreSQL：

```bash
export AGENTRIG_DATABASE__URL='postgresql+asyncpg://user:pass@localhost/agentrig'
uv run agentrig db upgrade
```

持久化数据库不会由 ORM 元数据静默补表。服务启动时会校验 Alembic revision；数据库未初始化
或版本落后时直接失败，并提示先执行 `uv run agentrig db upgrade`。只有隔离的内存测试库会由
测试装配代码创建表。

当前 39 张表、10 个 migration，head 为 `20260908_0010_trace_full_content`。表的域划分见
[总体架构 §10](./00-总体架构.md#10-数据与安全)。

共享或公网部署需启用 MCP/HTTP Bearer 鉴权。配置只保存环境变量引用：

```toml
[server]
api_token_ref = "env:AGENTRIG_ACCESS_TOKEN"
```

```bash
export AGENTRIG_ACCESS_TOKEN='replace-with-a-random-token'
```

常用命令：

```bash
uv run agentrig db current
uv run agentrig db upgrade
uv run agentrig db downgrade
```

## 3. Target 与 Driver

Target 定义如何连接被测 Agent：

```json
{
  "id": "target_reference_http_sse",
  "name": "Public deterministic HTTP/SSE reference target",
  "driver_type": "http_sse",
  "endpoint": "http://127.0.0.1:8091",
  "secret_ref": null,
  "options": {
    "healthcheck_url": "http://127.0.0.1:8091/healthz"
  },
  "versions": [
    {"version": "baseline"},
    {"version": "candidate-regression"}
  ]
}
```

`endpoint` 是被测 Agent 地址。版本级 `options` 与 Target 公共配置递归合并；身份和默认
请求字段只能由 Target 配置，不能被用例覆盖。

内置 Driver：

| 类型 | 用途 |
|---|---|
| `acp` | stdio Agent Client Protocol（Goose 等） |
| `http_sse` | 通用外置 tool-calling SSE 协议 |
| `ag_ui` | AgentScope 2.x 等 AG-UI 协议 Agent |
| `agentscope` | AgentScope 原生运行时适配 |
| `openai_compatible` | OpenAI Chat Completions tool-calling |
| `python` | 已安装且位于部署 allowlist 的 `module:Class` |
| `subprocess` | 实验性 allowlisted executable + stdin/stdout JSONL |
| `python_agent` | 用被测项目自己的解释器运行 harness，Agno、LangGraph 或普通函数 Agent 不改代码即可接管工具，见 [Python Agent 接入指南](./05-Python-Agent接入指南.md) |

所有 Driver 都把协议事件归一到 `DriverEvent`（`agentrig.driver-event.v2`，31 种类型），并通过
`DriverCapabilities` 的 19 个布尔位声明能力；Planner 以此做 preflight，不兼容项结构化跳过。

自定义 Python Driver 必须实现 `AgentDriver` Protocol，并由部署配置：

```toml
[execution]
python_driver_allowlist = ["my_package.driver:MyDriver"]
```

可选实现以下 Protocol 以获得对应能力（见 `targets/drivers/base.py`）：

| Protocol | 作用 |
|---|---|
| `ConfigurableAgentDriver` | 在启动 Agent 前静态校验 Target options |
| `ProbeableAgentDriver` | `check_target` 时执行一次不产生业务对话的连通性探针 |
| `DescribableAgentDriver` | 首条用户消息前采集运行时元数据，合入 Capability 快照 |
| `ResumableAgentDriver` / `PermissionResponseAgentDriver` / `ExternalExecutionAgentDriver` | 恢复、权限应答与外部执行回灌 |

MCP 不能上传或执行动态 Python 代码。

## 4. ExecutionProfile

```json
{
  "name": "Intelligent",
  "config": {
    "tool_mode": "controlled",
    "provider_chain": [
      {"name": "fixture"},
      {"name": "sample"},
      {"name": "simulation_curator"}
    ],
    "primary_evaluator": "evidence_judge",
    "concurrency": 4,
    "case_timeout_seconds": 300,
    "component_timeouts": {
      "driver": 120,
      "real_tool": 60,
      "curator": 30,
      "judge": 60
    },
    "repeat_count": 1,
    "curator_model": {
      "base_url": "https://model.example/v1",
      "model": "model-name",
      "secret_ref": "env:MODEL_API_KEY",
      "options": {}
    },
    "judge_model": {
      "base_url": "https://model.example/v1",
      "model": "model-name",
      "secret_ref": "env:MODEL_API_KEY",
      "options": {}
    }
  }
}
```

`tool_mode` 取 `controlled` / `proxy` / `observe_only`；`primary_evaluator` 取 `rule` /
`evidence_judge` / `external_controller`。Profile 可另带 `pricing_snapshot` 冻结价格，用于
严格成本归因——缺模型或 token/cache 分项时保持未知而不填零。

Profile 不保存 case IDs、Target 版本、自动重跑规则或明文 Key。合并优先级：

```text
本次 run_cases overrides > 保存 Profile > 项目默认
```

## 5. MCP 工具面

部署实例暴露 41 个原子工具和 `ping`：

```text
用例:
  list_tags, list_test_cases, get_test_case, find_cases_by_tool,
  get_test_case_schema, create_test_case, update_test_case, delete_test_case

执行:
  check_target, get_run_cases_schema, preview_run_cases, run_cases,
  get_run, get_run_summary, list_case_runs, get_case_run,
  list_run_cells, get_run_cell, retry_run_cells,
  list_case_run_events, cancel_run, submit_external_verdict

Target:
  list_targets, get_target, list_driver_types, get_target_schema,
  create_target, update_target, delete_target

Profile:
  list_execution_profiles, get_execution_profile, get_execution_profile_schema,
  create_execution_profile, update_execution_profile, delete_execution_profile

Sample:
  list_samples, get_sample, get_sample_schema,
  create_sample, update_sample, delete_sample
```

没有 `run_single_case`、rerun、comparison 汇总、Judge 重判或审核工具；生产证据、Review、
Failure Pattern 和 Project 管理也不通过 MCP 暴露。详尽调用顺序由 [`skills/`](../skills/) 维护。

协议调用边界会记录最小化审计日志（工具名、结果状态、耗时、资源 ID），不记录入参或完整结果，
见 `mcp_server.py` 的 `AuditedFastMCP`。

## 6. HTTP 与 Web

HTTP API 统一位于 `/api`。V1 面包含与 MCP 相同的资产/执行能力，并额外提供：

- 用例 approve/reject、Sample approve/disable；
- Run 列表、Cell 列表与详情、`retry-cells` 恢复；
- 报告与门禁：`report`、`quality-report`、`comparison-report`、`release-gate:evaluate`、
  `safety-report`、`safety-gate:evaluate`；
- Target `:probe-capabilities`、Capability 快照与 diff、Target 数据导出；
- 项目域治理（全部在 `/api/projects/{project_id}/` 下）：Environment、API Key、
  `review-items`、`evaluators/versions`、`alignment-runs`、`failure-signals`、
  `failure-patterns`、`failure-monitors`、`execution-jobs`、`production/*`。

V2 面位于 `/api/v2`：助手会话与轮询式 SSE、EvaluationPlan 的
create/validate/confirm/cancel/submit、provider-health、Target 直连会话（`target-chats`）。
契约与不变量见[智能评测助手架构](./03-智能评测助手架构.md)。

业务错误统一返回：

```json
{
  "code": "permission_denied",
  "message": "approved test cases are immutable and cannot be deleted",
  "details": {"case_id": "case_..."},
  "retryable": false
}
```

Web（React Router SPA，`web/`）提供：

| 页面 | 内容 |
|---|---|
| 总览 / 产品页 | 入口、资源抽屉与当前被测 Agent 上下文 |
| Target 工作区 | Target/version 编辑与检查、运行时与 Capability 摘要 |
| 资产 | TestCase 列表与 JSON 编辑、人工审核、ExecutionProfile、Sample 审核 |
| 评测 | Run 提交、进度、CaseRun 事件、各评判器输出与报告 |
| 智能助手 | 会话、计划预览与确认、Run 终态回写 |
| 治理 | 生产 Trace、Review/对齐、Failure Pattern、耐久 Job |
| 接入 | 生产 Trace 接入向导（选车道 → 建接入源 → 复制配置 → 等指示灯变绿） |

Web 访问令牌可在界面设置；API 返回 401 时自动弹出认证对话框。

## 7. Proxy 接入

Proxy backend：

```toml
[proxy]
public_url = "http://127.0.0.1:8000/proxy"
backends = { business = "http://127.0.0.1:9001/mcp/" }
```

工具以 `namespace__tool` 暴露。Proxy 模式运行时，HTTP/SSE 和 subprocess Driver 会把：

```json
{
  "tool_proxy": {
    "url": "http://127.0.0.1:8000/proxy",
    "headers": {
      "X-AgentRig-Proxy-Scope": "proxy_..."
    }
  }
}
```

交给被测 Agent。自定义 Driver 通过 `DriverPrepareContext.tool_proxy_url` 和
`tool_proxy_headers` 获得相同信息。被测 Agent 必须用该 URL/headers 创建 MCP Client。

## 8. 生产接入与治理

生产 Trace 走两条车道，落到同一套存储与策略：

```toml
[production_evidence]
enabled = true
```

| 车道 | 入口 | 适用 |
|---|---|---|
| OTel 带外上报 | `POST /v1/traces`（protobuf 与 JSON，支持 gzip） | 生产推荐，不挡请求，可见框架内部嵌套 span |
| OpenAI 兼容网关 | `POST /gateway/{source_id}/v1/{suffix}` | 零代码接入，开发与预发首选 |

两者都按接入源（IngestSource）鉴权：独立 Bearer token、限流、`retention_days` 与脱敏策略。
`/v1/traces` **不接受**部署级 API token，只认接入源 token。网关的上游 key 只存
`env:VARIABLE_NAME` 引用，出站复用 `TargetHttpPolicy` 校验。

Trace 转用例：`production/traces/{trace_id}/case-drafts:preview` 与 `:create`，再由
`production/case-lineages/{lineage_id}:review` 人工审核。开启 `save_full_content` 后，trace 中
捕获的真实工具调用会自动生成 Sample 草稿，审核通过即可用于不触发副作用的重放。

配方、向导与隐私三档策略见[生产 Trace 接入指南](./04-Trace接入指南.md)。

耐久执行：

```toml
[execution]
durable_scheduler_enabled = true
```

开启后 Run 按批量原子入队，每个 CaseRun 一个 Job，支持 lease/heartbeat、reaper、取消与旧
token fencing、多 Worker 收尾。独立 Worker 进程用 `uv run agentrig worker` 启动。

## 9. 测试与验收

```bash
uv run agentrig demo
uv run ruff check src tests scripts examples
uv run mypy src/agentrig
uv run pytest
cd web
npm run typecheck
npm run test:coverage
npm run e2e
npm run build
```

公开纵向验收：

```bash
scripts/reference_demo.sh all --profile reference-ci
scripts/reference_demo.sh validate-evidence --require-clean-source
scripts/reference_demo.sh down
```

PostgreSQL 集成测试在提供 `AGENTRIG_TEST_POSTGRES_URL` 时运行。没有该环境变量时跳过，
不影响 SQLite 默认测试。V2.3 起的完整验收范围见
[验收运行手册](./09-V2.3-Agent运行时验证与生产证据闭环/11-验收运行手册.md)。
