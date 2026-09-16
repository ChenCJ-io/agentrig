# 生产 Trace 接入指南

> 状态：Current
>
> 对应实现：`src/agentrig/production/`；方案背景见
> [一站式 Trace 接入 RFC](./11-一站式Trace接入与生产回归闭环-RFC.md)

把线上 LLM 调用的输入输出流进 AgentRig，之后就能在平台里看 trace、把生产失败沉淀为
回归用例。接入分三步：创建接入源、配置上报、发一条请求点亮指示灯。全程约五分钟。

## 0. 前置条件

生产接入默认关闭。在配置文件中开启：

```toml
[production_evidence]
enabled = true
```

启动服务后，Web 控制台左侧"接入"页就是接入向导；下文的所有操作也都可以用 API 完成。

## 1. 创建接入源

每个应用建一个接入源（IngestSource），各自独立 token、独立保留期，可随时停用。
在向导页填写名称与允许的 `service.name` 即可；等价的 API 调用：

```bash
curl -s -X POST http://127.0.0.1:8000/api/projects/default/production/ingest-sources \
  -H 'Content-Type: application/json' \
  -d '{
    "name": "my-agent",
    "allowed_service_names": ["my-agent"],
    "enabled": true,
    "retention_days": 30,
    "redaction_policy": {"save_input_preview": true, "save_output_preview": true}
  }'
```

响应中的 `token` **只出现这一次**，请立即保存。`allowed_service_names` 是白名单：
`service.name` 不在名单里的 span 会被拒收。

## 2. 配置上报

接收端点是标准 OTLP/HTTP：`POST /v1/traces`，同时支持 protobuf 与 JSON 两种编码，
支持 gzip。鉴权使用三个请求头：

| 请求头 | 值 |
|---|---|
| `Authorization` | `Bearer <接入源 token>` |
| `X-AgentRig-Project` | Project ID，默认 `default` |
| `X-AgentRig-Source` | 接入源 ID |

### 2.1 通用方式：OTel 环境变量（推荐）

任何基于 OpenTelemetry 的埋点（OpenLLMetry、OpenInference/Phoenix instrumentation、
框架自带的 OTel 输出）都读取标准环境变量。设置两个变量后正常启动应用即可：

```bash
export OTEL_EXPORTER_OTLP_TRACES_ENDPOINT="http://127.0.0.1:8000/v1/traces"
export OTEL_EXPORTER_OTLP_TRACES_HEADERS="authorization=Bearer <token>,x-agentrig-project=default,x-agentrig-source=<source_id>"
```

### 2.2 手动方式：在代码里创建 exporter

```python
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

provider = TracerProvider(resource=Resource.create({"service.name": "my-agent"}))
provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(
    endpoint="http://127.0.0.1:8000/v1/traces",
    headers={
        "Authorization": "Bearer <token>",
        "X-AgentRig-Project": "default",
        "X-AgentRig-Source": "<source_id>",
    },
)))
```

上报由 OTel SDK 在后台线程异步攒批完成：AgentRig 不可达时应用无感知，不会阻塞请求。

### 2.3 识别哪些字段

接收端按 OTel GenAI 语义约定归一化，并兼容两种常见社区方言，无需任何转换配置：

| 内容 | 官方约定 | OpenLLMetry 方言 | OpenInference 方言 |
|---|---|---|---|
| 输入消息 | `gen_ai.input.messages` | `gen_ai.prompt.{i}.role/.content` | `llm.input_messages.{i}.message.*` |
| 输出消息 | `gen_ai.output.messages` | `gen_ai.completion.{i}.*` | `llm.output_messages.{i}.message.*` |
| token 用量 | `gen_ai.usage.input_tokens` 等 | `gen_ai.usage.prompt_tokens` 等 | `llm.token_count.prompt` 等 |
| 模型名 | `gen_ai.request.model` | 同左 | `llm.model_name` |
| 操作类型 | `gen_ai.operation.name` | `llm.request.type` | `openinference.span.kind` |
| 工具调用 | `gen_ai.tool.name` | `traceloop.span.kind=tool` | `openinference.span.kind=TOOL` |
| 会话 | `gen_ai.conversation.id` / `session.id` | 同左 | `session.id` |

### 2.4 零代码方式：网关代理

不方便加埋点的应用可以走网关：把客户端的 `base_url` 改到 AgentRig，请求会被原样转发到
配置的上游（支持流式），每次调用自动记录为一条生产 trace。

在向导页把接入源类型选为"网关代理"，填上游地址和存放上游 key 的环境变量名；等价的 API：

```bash
curl -s -X POST http://127.0.0.1:8000/api/projects/default/production/ingest-sources \
  -H 'Content-Type: application/json' \
  -d '{
    "name": "my-agent",
    "source_type": "openai_gateway",
    "allowed_service_names": ["my-agent"],
    "enabled": true,
    "retention_days": 30,
    "gateway": {
      "upstream_base_url": "https://api.deepseek.com/v1",
      "upstream_secret_ref": "env:UPSTREAM_API_KEY"
    },
    "redaction_policy": {"save_input_preview": true, "save_output_preview": true}
  }'
```

客户端只改两行：

```python
client = OpenAI(
    base_url="http://127.0.0.1:8000/gateway/<source_id>/v1",
    api_key="<接入源 token>",
)
```

要点与边界：

- 上游 key 只以 `env:VARIABLE_NAME` 引用，设置在 AgentRig 服务端；应用端从此不再持有
  厂商 key，换模型在控制台改一处即可；
- 首版转发 `chat/completions`（含流式 SSE）与 `embeddings`，其余路径拒绝；
- 上游错误原样透传并记录为失败 trace；网关不重试、不降级；
- 网关在请求路径上：开发与预发首选；生产环境推荐 2.1 的带外上报；
- 上游地址受与 Target 相同的出站策略校验，默认拒绝私网地址。

## 3. 验证接入

最快的方式是仓库自带的发送脚本（纯标准库，无需安装任何依赖）：

```bash
uv run python scripts/send_demo_traces.py \
  --endpoint http://127.0.0.1:8000/v1/traces \
  --project default --source <source_id> --token <token>
```

它会发送一条成功和一条失败的示例 chat trace。发送后向导页的指示灯变绿；
或直接查询：

```bash
curl -s "http://127.0.0.1:8000/api/projects/default/production/traces?limit=10"
```

## 4. 数据与隐私

- **默认什么正文都不存**。三档策略逐级开启：`save_input_preview` / `save_output_preview`
  只保存脱敏后的截断预览；`save_full_content` 额外保存脱敏后的完整对话与工具参数/结果
  （单条有体积上限），供"转为用例"和样本生成使用，建议只在开发环境开启；
- 无论哪一档，邮箱、Bearer token、密码等模式在入库前就被替换；
- span 属性按接入源的 allowlist 过滤，输入输出类属性一律不进入属性存储；
- 每条 trace 按内容哈希幂等去重，重发不会产生重复记录；
- 到期数据由保留期清理（`retention_days`），清理留下 tombstone 记录；
- 每个接入源有独立的每日 span 配额与请求体积上限。

## 5. 下一步：从 trace 到回归用例

在"生产证据"页选中一条 trace，可以预览并创建测试用例草稿（Trace→Case）。开启
`save_full_content` 后，trace 里捕获的真实工具调用会自动生成对应的 Sample 草稿：用例与
样本分别通过人工审核后，回归重放直接使用生产捕获的工具结果，不触发任何真实副作用。
lineage 记录每条用例来自哪条 trace；lineage 只有在用例与全部样本都审核通过后才能批准。
