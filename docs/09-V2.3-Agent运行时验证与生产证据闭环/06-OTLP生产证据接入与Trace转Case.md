# OTLP 生产证据接入与 Trace 转 Case 方案

> 专题 ID：AR-V23-WP06
>
> 状态：Implemented（SQLite/契约与 PostgreSQL 17.7 集成验收完成；容量基线待目标环境）
>
> 优先级：P2
>
> 目标里程碑：V2.4
>
> 前置：Project 最小边界、Redactor、配额与保留策略

## 0. 实施状态（2026-08-11）

- 新增独立 ProductionSession/Trace/Span、IngestSource、TraceCaseLineage 和治理审计表，未复用
  Run/CaseRun 状态机；
- `/v1/traces` 支持 OTLP/HTTP protobuf、source token hash、Project/source scope、service allowlist、
  request/span/attribute 上限、每分钟限流、日配额、partial success、幂等和冲突拒绝；
- Redactor 在持久化前删除 Authorization/Cookie/Secret/PII/hidden thinking，正文预览必须由 source
  policy 显式开启；
- Trace 查询、Span 时间线、dry-run/apply retention、lineage tombstone、Trace→Case mapping preview/
  draft/review API 与治理 Web 已实现；
- SQLite 测试覆盖 OTLP、Project 隔离、二次脱敏、draft lineage 与 retention；PostgreSQL 17.7
  的 ingest/retention/tombstone round-trip 已在一次性真实 cluster 执行通过。

## 1. 目标

让 AgentRig 能接收 AgentScope 及其他 Agent Runtime 的标准生产遥测，把经确认的失败转化为带完整
来源关系的 TestCase/Sample 草稿，再进入现有审核和回归执行链。

完整流程：

```text
Agent Runtime
  → OTLP/HTTP（可经 Collector）
  → validate / authenticate / quota / redact
  → normalize GenAI Session/Trace/Span
  → score / review
  → create TestCase or Sample draft with lineage
  → human approve
  → SuiteVersion / Run / Gate
```

## 2. 关键边界

- ProductionTrace 不是 Run；采样、迟到和缺失不能污染测试执行事实。
- ingest 默认关闭，启用前必须配置 Project、API key、配额、保留和脱敏策略。
- Trace 正文默认不进入测试资产；转换时只选择明确字段并再次脱敏。
- 自动转换只创建 draft，不自动 approved，不自动触发生产写工具。
- AgentRig 首版不依赖 ClickHouse、Temporal 或 Kafka。
- AgentRig 的 OTLP export 与本专题 ingest 是两个独立方向，配置和权限必须分开。

## 3. 接入拓扑

推荐生产方式：

```text
Agent/SDK → OpenTelemetry Collector
             ├─ existing observability backend
             └─ AgentRig OTLP/HTTP ingest
```

开发环境允许 Agent 直接发送至 AgentRig。首版支持 OTLP/HTTP protobuf；JSON 可作为调试 profile，gRPC
后置。Collector 可以做批处理和初步过滤，但 AgentRig 仍执行自己的认证、限制和 Redactor。

## 4. 数据模型

### 4.1 IngestSource

```text
id, project_id, name, type,
api_key_hash, allowed_service_names,
redaction_policy_id, retention_policy_id,
rate_limit, enabled, created_at, last_seen_at
```

API key 只展示一次，数据库保存 hash。source 不能跨 Project 写入。

### 4.2 ProductionSession

```text
id, project_id, source_id, external_session_id_hash,
started_at, ended_at, environment, release,
user_identity_hash, trace_count, status,
attributes_allowlisted, created_at
```

### 4.3 ProductionTrace

```text
id, project_id, source_id, session_id,
external_trace_id, root_span_id,
name, started_at, ended_at, status,
service_name, environment, release,
input_preview_redacted, output_preview_redacted,
attributes, token_usage, cost_snapshot,
ingest_status, content_hash, created_at
```

### 4.4 ProductionSpan

```text
id, project_id, trace_id,
external_span_id, parent_external_span_id,
kind, name, started_at, ended_at, status,
agent_path, model_call, tool_call, tool_result,
permission, memory_operation, artifact_refs,
attributes, events, content_hash, received_at
```

正文、大 artifact 和多模态内容不直接塞入行；使用受控 artifact ref，设置单独保留和访问策略。

### 4.5 TraceCaseLineage

```text
id, project_id,
source_trace_id, source_span_ids,
annotation_ids, failure_pattern_id,
draft_case_id, draft_sample_ids,
mapping_version, mapping_hash,
created_by, reviewed_by, status, created_at
```

一个 Trace 可生成多个 Case，一个 Case 也可引用多个同类 Trace。来源删除后保留 tombstone/hash 和依法
允许的最小审计信息。

## 5. OTLP 归一化

优先识别 OpenTelemetry GenAI semantic conventions，并允许 source-specific mapping：

```text
resource/service → project ingest source
trace → ProductionTrace
session/conversation id → ProductionSession
span kind/name → model/tool/agent/memory/workspace operation
token attributes → UsageSnapshot
status/error → normalized outcome
```

未知属性只在 project allowlist 内保留；默认拒绝任意高基数或正文属性。外部 trace/span ID 按 Project
唯一，不作为 Metric label。

## 6. Ingest Pipeline

### 6.1 请求阶段

1. 验证 Project/source API key；
2. 检查 content type、压缩格式、请求和批次大小；
3. 应用 rate limit、每日 ingest 配额和并发限制；
4. 解析 protobuf，拒绝畸形 payload；
5. 对 resource/service/environment 执行 allowlist；
6. Redactor 处理属性、event 和正文；
7. 以 external ID/content hash 幂等写入；
8. 返回 OTLP partial success 和结构化拒绝数量。

### 6.2 迟到与乱序

- Span 可先于 parent 到达；先写 orphan relation，后续有界修复；
- 相同 external span ID、相同 content hash 是重复写入；
- 同 ID 不同内容记录 conflict，不静默覆盖；
- Trace 完成后在 grace period 内允许补充迟到 Span；
- 超过窗口的 Span作为 late evidence 保存，但不重写已发布的 TestCase/SuiteVersion。

### 6.3 故障处理

数据库不可用时返回可重试状态，不在内存无限排队。首版批量解析和事务写入保持有界；若吞吐达到容量
阈值，再引入 durable ingest queue，不提前建设。

## 7. 隐私、保留与删除

Project 级策略至少定义：

- 是否保存 input/output preview；
- 默认 deny 的属性名和正则；
- email、token、Cookie、Authorization、路径和业务 ID 的处理；
- artifact 类型/大小；
- Trace、正文、artifact 和审计 tombstone 的不同保留期；
- user deletion 请求如何定位 hash identity；
- export 权限和审计。

隐藏思维过程、明文 Secret、Authorization/Cookie 和未批准的二进制内容始终拒绝。Redactor 版本和
policy hash 写入 Trace。

## 8. Trace 查询与 Web

首版使用 PostgreSQL 索引和 JSONB：

```text
GET /api/projects/{project_id}/production/sessions
GET /api/projects/{project_id}/production/traces
GET /api/projects/{project_id}/production/traces/{trace_id}
GET /api/projects/{project_id}/production/traces/{trace_id}/spans
```

过滤：时间、environment、release、service、status、model、tool、annotation、failure pattern。首版不承诺
向量语义搜索；数据量和用户需求明确后再增加 pgvector。

Web Trace 详情展示时间线、Agent path、model/tool/permission/memory/artifact 元数据、脱敏状态和数据
缺失。生产页面与 Run 页面视觉上明确分域。

## 9. Trace 转 Case/Sample

### 9.1 创建草稿

```text
POST /api/production/traces/{trace_id}/case-drafts
```

请求明确选择：

- 输入消息/轮次；
- 需要保留的 Tool schema 和参数模板；
- 哪些 ToolResult 变成 Fixture、哪些创建 Sample draft；
- 期望行为/rubric 草稿；
- 目标版本和 required capabilities；
- 来源 Annotation/FailurePattern。

服务输出 mapping preview、将被删除/泛化的字段和 lineage。用户确认后才写 draft。

### 9.2 数据泛化

默认转换：

- 真实 user/account/resource ID 替换为稳定占位符；
- 时间、随机 ID 和环境地址参数化；
- ToolResult 只保留断言所需字段；
- PII/Secret 再次扫描；
- 生产 artifact 不直接复制，除非明确批准且满足 license/retention；
- expected output 优先使用人工 annotation，而不是把生产回答当作正确答案。

### 9.3 审核和发布

草稿沿用 Case/Sample 人工审核边界。审核人可以编辑，但 lineage 保存原 mapping hash 和变更 diff。
approved Case 加入新的 SuiteVersion；历史 suite 不原地增加用例。

## 10. 容量触发阈值

在以下现象持续出现后才评审专用 Trace 存储或队列：

- 日写入 Span 达到项目设定阈值且 PostgreSQL 写入占用明显影响 Run；
- 典型 24 小时查询在正确索引下仍超过产品 SLO；
- retention delete/vacuum 持续影响执行事务；
- ingest burst 无法通过 batch/rate limit 吸收；
- 多副本要求超过现有 lease/transaction 能力。

评审必须带真实 benchmark，而不是因 Latitude 使用某组件就直接复制。

## 11. 测试计划

- OTLP protobuf golden fixtures 和 semantic mapping；
- malformed/oversized/compressed payload；
- API key、Project 隔离、rate limit 和配额；
- PII/Secret/hidden thinking 拒绝；
- duplicate、conflict、orphan parent、late span；
- PostgreSQL 索引、分页和 retention；
- Trace→Case mapping、二次脱敏和 lineage；
- 删除源 Trace 后的 tombstone 行为；
- Collector/SDK live smoke，但不作为每 PR 强依赖。

## 12. 验收标准

- [x] ingest 默认关闭，未配置 Project/source/policy 无法启用；
- [x] OTLP partial success 能准确报告接受和拒绝数量；
- [x] 重复 payload 幂等，同 ID 冲突不覆盖；
- [x] ProductionTrace 与 Run API/表/状态明确分离；
- [x] Secret、Cookie、Authorization、hidden thinking 落库为 0；
- [x] 每条 Trace 可追溯 source、redaction policy 和 content hash；
- [x] Trace→Case 只能创建 draft，并保留 Annotation、Span 和 mapping lineage；
- [x] draft 可沿用 TestCase review 转 approved，并通过既有 Run/Suite manifest 路径重放；
- [x] retention/tombstone PostgreSQL 集成用例已在 PostgreSQL 17.7 执行通过；
- [x] OTLP ingest 故障不改变现有 Run 执行语义。

## 13. 灰度和回滚

先启用内部 Project、低配额、只保存元数据的 shadow 模式；再允许脱敏 preview；最后开放 Trace→Case。
关闭 source 后拒绝新 ingest，但保留已写数据至 retention 到期。回滚不能删除已生成的 Case lineage，
只能停止新转换。
