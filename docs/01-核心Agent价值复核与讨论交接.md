# AgentRig V1 实现与接入

> 本文替代早期 Agent 价值讨论交接文档，记录当前代码结构和接入方式。

## 1. 代码模块

```text
src/agentrig/
├── cases/                  TestCase、Turn、Selector、审核规则
├── targets/
│   └── drivers/            HTTP/SSE、Pixcake、OpenAI、Python、subprocess
├── profiles/               ExecutionProfile 与配置合并
├── tool_results/
│   ├── providers/          Fixture、Sample、Curator、Real Tool
│   ├── chain.py            顺序降级
│   └── validator.py        Schema、大小和敏感字段校验
├── agents/                 Simulation Curator、Evidence Judge、ModelClient
├── runs/                   Planner、Scheduler、Executor、Event、Redactor
├── evaluations/            Rule、External 与评判存档
├── proxy/                  MCP 聚合与 CaseRun Scope
├── infrastructure/
│   └── database/           ORM、async Session、SQL Repository
├── mcp/tools/              V1 原子 MCP Tools
├── v1_api.py               V1 HTTP API
├── bootstrap.py            唯一 Service 装配点
└── app.py                  HTTP/MCP/Proxy/Web 进程入口
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

开发启动时 `ServiceContainer.initialize()` 也会 `create_all`，方便内存测试和首次本地使用；
正式部署应以 Alembic 为准。

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
  "name": "Local Pixcake Agent",
  "driver_type": "pixcake_http_sse",
  "endpoint": "http://127.0.0.1:8000",
  "secret_ref": null,
  "options": {
    "user_id": 10001,
    "device_info": {
      "device_id": "agentrig",
      "os": "macOS",
      "os_version": "15.7",
      "app_version": "9.2.0",
      "tool_version": 4
    },
    "chat_channel": "pixcake_client"
  },
  "versions": [
    {"version": "9.2.0"},
    {
      "version": "9.3.0",
      "options": {
        "device_info": {
          "device_id": "agentrig",
          "os": "macOS",
          "os_version": "15.7",
          "app_version": "9.3.0",
          "tool_version": 5
        }
      }
    }
  ]
}
```

`endpoint` 是被测 Agent 地址，不是 TS Agent Scope 管理平台的 `/mcp/` 地址。Driver 会在
基地址后补 `/chat/stream`。Pixcake 用例如果需要项目或附件上下文，可在
`initial_state.pixcake_request` 中提供 `metadata`、`attachments` 等附加请求字段；Target
中的 `request_defaults` 提供所有用例共享的默认值。身份字段只能由 Target 配置，不能被
用例覆盖。

内置 Driver：

| 类型 | 用途 |
|---|---|
| `http_sse` | 通用外置 tool-calling SSE 协议 |
| `pixcake_http_sse` | Pixcake `/chat/stream`，补齐 `user_id`、`device_info` 和通道身份 |
| `openai_compatible` | OpenAI Chat Completions tool-calling |
| `python` | 已安装且位于部署 allowlist 的 `module:Class` |
| `subprocess` | 实验性 allowlisted executable + stdin/stdout JSONL |

自定义 Python Driver 必须实现 `AgentDriver` Protocol，并由部署配置：

```toml
[execution]
python_driver_allowlist = ["my_package.driver:MyDriver"]
```

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

Profile 不保存 case IDs、Target 版本、自动重跑规则或明文 Key。合并优先级：

```text
本次 run_cases overrides > 保存 Profile > 项目默认
```

## 5. MCP 工具

部署实例只暴露以下 V1 工具和 `ping`：

```text
用例:
  list_tags, list_test_cases, get_test_case, find_cases_by_tool,
  get_test_case_schema, create_test_case, update_test_case, delete_test_case

执行:
  check_target, get_run_cases_schema, run_cases, get_run, list_case_runs,
  get_case_run, list_case_run_events, cancel_run, submit_external_verdict

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

没有 `run_single_case`、rerun、comparison 汇总、Judge 重判或审核工具。详尽调用顺序由
[`skills/`](../skills/) 维护。

## 6. HTTP 与 Web

HTTP API 统一位于 `/api`，包含与 MCP 相同的资产/执行能力，并额外提供：

- 用例 approve/reject；
- Sample approve/disable；
- Run 列表；
- Web 所需分页和详情。

业务错误统一返回：

```json
{
  "code": "permission_denied",
  "message": "approved test cases are immutable and cannot be deleted",
  "details": {"case_id": "case_..."},
  "retryable": false
}
```

Web 提供：

- 总览；
- TestCase 列表、JSON 编辑和人工审核；
- Target/version 编辑与检查；
- ExecutionProfile 编辑；
- Run 提交、进度、CaseRun 事件和各评判器输出；
- Sample 编辑与人工审核。

V1 不包含对话式执行助手。

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

## 8. 测试与验收

```bash
uv run agentrig demo
uv run ruff check src tests examples
uv run mypy src/agentrig
uv run pytest
cd web
npm run typecheck
npm run build
```

PostgreSQL 集成测试在提供 `AGENTRIG_TEST_POSTGRES_URL` 时运行。没有该环境变量时跳过，
不影响 SQLite 默认测试。
