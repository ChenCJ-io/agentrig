# 一站式 Trace 接入与生产回归闭环 RFC

> RFC ID：AR-RFC-0005
>
> 状态：Accepted / Partially implemented（M1—M3 已落地，M4 待实施）
>
> 版本：0.2
>
> 日期：2026-09-08（提出）／2026-09-09（状态更新）
>
> 范围：生产 Trace 的采集车道、接入体验、存储与隐私策略，以及 Trace 转用例的自动化
>
> 前置文档：[生产证据接入与 Trace 转 Case](./09-V2.3-Agent运行时验证与生产证据闭环/06-OTLP生产证据接入与Trace转Case.md)、
> [总体架构](./00-总体架构.md)
>
> 用户操作入口已固化为[生产 Trace 接入指南](./04-Trace接入指南.md)；本文保留方案取舍与分期
> 依据，实施状态见 §13。

**一句话目标：让任何 LLM 应用在五分钟内把线上请求的输入输出流进 AgentRig；
让流进来的每一条失败，都能低成本地变成一条可重放的回归用例。**

评审时只需要回答三个问题：

1. 三条接入车道的取舍对不对（第 5 节）；
2. 全文存储的隐私默认值可不可以接受（第 6 节）；
3. 分期顺序是否同意（第 8 节）。

---

## 1. 为什么做

用户的真实期望是一站式：数据在哪个平台，看问题、建用例、跑回归就都想在那个平台完成。
今天 AgentRig 的评测能力是完整的，但数据进不来——用户必须手工创建用例，冷启动成本
挡住了大多数人。

同时要清醒一件事：**观测采集本身已经不是差异化战场**。OpenTelemetry 的 GenAI 语义约定
把"怎么记录一次 LLM 调用"标准化了，各家框架的埋点由社区维护。我们的差异化在采集之后：
生产失败 → 人工审核 → 冻结成用例与工具样本 → 不触发真实副作用地重放 → 发布门禁拦截回归。
这条右半段闭环，观测类产品都没有。

所以本 RFC 的立场是：**Trace 是进水口和获客入口，不是产品本体**。接入要做到行业最低门槛，
但工程投入要克制，把力气留给闭环。

## 2. 业界怎么做

四个代表产品的采集设计，结论先行：**终局都是 OTel 标准，拉新靠零代码入口**。

- **Langfuse**：SDK 起家（装饰器、替换 import 的 OpenAI 包装客户端、框架回调），采集在后台
  线程异步攒批，绝不阻塞用户应用。2025 年 Python SDK 整个重写在 OTel 之上，服务端同时开了
  标准 OTLP 接收端点，直接吃社区埋点。闭环做到"trace 加入 dataset、对 dataset 跑实验"，
  但没有工具重放。
- **Helicone**：网关起家。用户把 `base_url` 改成它的代理域名、加一个认证头即完成接入；
  代理顺手提供缓存、限流、key 保管。接受"在请求路径上"的代价。
- **LangSmith**：生态绑定。用 LangChain 时设两个环境变量即全量上报，零代码；后来也补了
  OTLP 接收。
- **Phoenix**：一开始就是纯 OTel，自定 OpenInference 语义约定，平台只做接收和展示。

对我们有效的五条规律：

1. 自研每个框架的 SDK 是无底洞，接标准即可；
2. 零代码入口（环境变量、改 base_url、替换 import）决定采用率；
3. 带外上报（异步、不挡请求）与带内代理（网关）是互补的两种信任模型；
4. 存储分层（对象存储 + OLAP）是规模问题，起步期一个数据库够用；
5. 它们的 dataset 相当于我们的 Case，但都没有受控工具重放——这是我们要守住的。

## 3. 我们已经有什么

V2.3 时按 09/06 方案落地的 `src/agentrig/production/` 模块，接收侧其实建了一半：

- 标准 OTLP/HTTP 接收端点 `POST /v1/traces`（protobuf，支持 gzip），按
  `X-AgentRig-Project`、`X-AgentRig-Source` 和接入源 Bearer token 鉴权；
- 已解析 OTel GenAI 语义约定与 OpenInference 属性（`gen_ai.input.messages`、
  `gen_ai.usage.*`、`input.value` 等），会话 ID、操作类型、token 用量、成本快照入库；
- 每个 span 归一出 `model_call`、`tool_call`、`tool_result`、`permission` 等结构化字段；
- 接入源（IngestSource）有创建、启停、独立 token、保留期与脱敏策略；
- Trace→Case 已有 API：预览草稿、创建草稿、lineage 人工审核
  （`/production/traces/{id}/case-drafts` 一族）；
- 失败治理模块（Signal → Pattern → Monitor）可复用于失败聚类。

差距也要摆清楚：

- 正文只存脱敏预览（`save_input_preview` / `save_output_preview`，默认关），转用例时信息不够；
- 只收 protobuf，不收 OTLP/JSON，部分轻量 exporter 只发 JSON；
- 没有任何"怎么接入"的用户引导：无文档配方、无向导页、无兼容性实测；
- 没有网关车道；
- Trace 列表与详情的 Web 界面较薄，转用例动线未打磨。

## 4. 目标与非目标

**目标**

1. 三种主流形态的应用（直连 OpenAI 兼容 API、用框架埋点、有存量日志）都有一条五分钟内
   走通的接入路径；
2. 接入向导做到"复制粘贴、等指示灯变绿"；
3. 一条生产 trace 能一键转为用例，其中真实工具调用自动生成 Sample 草稿；
4. 隐私默认值保持保守：不显式开启就不存正文。

**非目标**

- 不自研任何语言的采集 SDK；
- 不做 ClickHouse/对象存储等规模化存储分层（记录为演进方向，不进本期）;
- 不做 prompt 管理、在线打分看板等观测类产品功能；
- 网关不做缓存、限流、计费等增值功能。

## 5. 总体设计：三条车道，一个向导

```text
应用侧                          AgentRig
─────────                      ─────────────────────────────
改 base_url ──────── 车道 A ──► /gateway/{source}/v1/…（新建）─┐
                                                              ├─► ProductionTrace/Span
OTel 埋点 ────────── 车道 B ──► /v1/traces（已存在）───────────┤    （同一套存储与策略）
                                                              │
历史日志 JSONL ───── 车道 C ──► 批量导入（后置）───────────────┘
```

三条车道落到同一套 Trace 存储和策略上，后续的工作台、转用例、门禁不感知数据来自哪条车道。

### 5.1 车道 B：标准 OTel 接入（先做）

接收端已存在，本期工作是把"能收"变成"好接"：

1. **兼容性实测矩阵**。用 OpenLLMetry、OpenInference 和 AgentScope 自带埋点各接一个最小
   应用，实测发送→入库→字段映射，把映射差异补进 `otlp.py` 并固化为测试。这是文档能承诺
   "五分钟"的底气。
2. **补 OTLP/JSON 编码**。`/v1/traces` 增加 `application/json` 分支，复用同一归一化逻辑。
3. **配方文档**。每种埋点一页，核心是让用户只做一件事——设环境变量：

```bash
export OTEL_EXPORTER_OTLP_TRACES_ENDPOINT="https://你的agentrig/v1/traces"
export OTEL_EXPORTER_OTLP_TRACES_HEADERS="authorization=Bearer <接入源token>,x-agentrig-project=default,x-agentrig-source=<source_id>"
```

采集全程在应用后台线程异步发送（OTel SDK 默认行为），AgentRig 不可达时应用无感知。
这条车道能看到框架内部的嵌套 Agent 与工具 span，是生产环境的推荐路径。

### 5.2 车道 A：OpenAI 兼容网关（第二步）

给"没有埋点、直连模型 API"的应用一个零代码入口。

**用户视角**：在控制台把接入源类型选为"网关"，填上游地址和 `env:` 引用的上游 key，
拿到一个 AgentRig key。然后客户端只改两行：

```python
client = OpenAI(
    base_url="https://你的agentrig/gateway/src_abc123/v1",
    api_key="<AgentRig 接入源 token>",
)
```

**设计要点**：

- 路由 `/gateway/{source_id}/v1/chat/completions`，source_id 进路径，鉴权和上游配置都由
  接入源决定，一个部署可以同时代理多个上游；
- 上游 key 只存 `env:VARIABLE_NAME` 引用（沿用全局 Secret 规则），应用端从此不再持有
  厂商 key，换模型在控制台改一处即可——这是网关对用户的独立价值；
- 流式请求做 SSE 透传加旁路记录：边转发边攒完整响应，请求结束后写一条 trace
  （messages、工具定义、用量、延迟、TTFT）；
- 记录动作在响应结束后异步落库，不增加转发路径的数据库等待；
- 失败语义从简：上游错误原样透传并记录失败 trace；网关自身不重试、不降级。文档明确
  定位：开发与预发首选，生产环境推荐车道 B（带外，不挡请求）；
- 出站地址复用现有 `TargetHttpPolicy` 校验，防 SSRF。

首版只覆盖 `chat/completions`（含流式）与 `embeddings`；其余端点透传但不记录。

### 5.3 车道 C：批量导入（后置）

一个接收 JSONL 的导入接口，每行一条历史调用记录，映射为一条 trace。用于存量日志回填与
离线评测数据集。实现简单，但没有前两条车道的验证价值，放在 M4。

### 5.4 接入向导页（与车道 B 同期）

控制台新增"接入"页，四步：

1. 选车道（三选一，附一句话适用判断）；
2. 建接入源，token 只显示一次（机制已有）；
3. 展示可复制的配置片段（按所选车道生成，含真实 endpoint 和 source_id）；
4. 页面驻留一个"等待第一条 trace"探测，数据到达后变绿并直接链去 trace 列表。

低成本高回报：行业里"接入体验好"的口碑一半来自这个页面。

## 6. 数据与隐私策略

现状默认不存任何正文（连预览都要显式开启），这个保守默认**保留不变**，它是面向企业用户的
卖点，不是缺陷。

本期新增第三档：`save_full_content`。三档语义：

| 策略 | 存什么 | 用途 |
|---|---|---|
| 默认（全关） | 只有元数据、用量、结构化 span 字段 | 纯指标与失败信号 |
| `save_*_preview` | 脱敏后的输入输出截断预览 | 看板排查 |
| `save_full_content` | 脱敏后的完整消息数组与工具参数 | 转用例、重放 |

约束：全文同样先过 Redactor 脱敏；单条 trace 正文设体积上限（超限截断并标记）；保留期
沿用接入源的 `retention_days`，全文与预览一起被 retention 清理。正文外置对象存储记录为
将来演进，不进本期。

## 7. 从 Trace 到用例

这一节是本 RFC 的价值所在：接进来的数据要能变成回归资产，闭环才成立。

在现有 Trace→Case API 之上做四件事：

1. **一键转用例**。Trace 详情页出"转为用例"按钮，用户消息、多轮上下文、预期行为要点从
   全文自动预填，人只做确认与修剪（依赖 `save_full_content`）。
2. **工具调用自动生成 Sample 草稿**。span 里已经有 `tool_call` 与 `tool_result`；转用例时
   把它们成对提取为 Sample 草稿，走既有人工审核后，重放就用真实的生产工具结果，不触发
   真实副作用。这是观测类产品给不了的能力，必须做顺。
3. **会话转多轮用例**。同一 `session_id` 下的多条 trace 可合并预览为一个多轮用例。
4. **失败聚类批量建议**。复用失败治理模块，对失败 trace 聚类后提示"这一簇 N 条相似失败，
   建议沉淀 1 个代表用例"，避免逐条手工挑。

lineage（哪条用例来自哪条 trace）机制已有，全部动作沿用它记录来源。

## 8. 分期与验收

| 里程碑 | 内容 | 粗估 | 出口条件 |
|---|---|---:|---|
| M1 | 车道 B 兼容实测 + OTLP/JSON + 配方文档 + 接入向导页 | 1 周 | 三种埋点各有一个最小应用实测接入成功；新用户照文档五分钟内在向导页看到指示灯变绿 |
| M2 | 车道 A 网关（chat/completions 流式与非流式、embeddings） | 1.5 周 | 真实上游联调通过；断流、上游 4xx/5xx、大响应均有测试；旁路记录不增加转发首字节延迟 |
| M3 | 全文存储策略 + Trace 工作台补强 + 一键转用例（含 Sample 草稿自动化） | 1.5 周 | 从一条真实生产 trace 出发，转成用例并用生成的 Sample 重放通过 |
| M4 | 失败聚类建议 + 会话转多轮 + 批量导入 + CI 门禁 Action | 1 周 | 端到端演示：接入一个真实应用运行数日，沉淀若干用例，一次故意的坏 prompt 变更被门禁拦下 |

M4 的端到端演示同时就是对外的旗舰案例，完成后写进 README。

## 9. 待拍板的决策

| 编号 | 问题 | 建议 |
|---|---|---|
| D1 | 网关是否托管上游 key | 是，仅 `env:` 引用，不落库。这是网关的独立价值 |
| D2 | `save_full_content` 默认值 | 默认关，向导页在开发场景显式建议打开 |
| D3 | 是否支持 OTLP/JSON | 支持，工作量小、覆盖面收益明确 |
| D4 | 网关是否做缓存/限流等增值 | 本期不做，避免滑向网关产品 |

## 10. 风险

| 风险 | 缓解 |
|---|---|
| 网关在请求路径上，故障即用户应用故障 | 定位为开发/预发首选并在文档写明；不做重试等复杂逻辑，保持行为可预测 |
| 全文存储引入隐私与体积压力 | 默认关、强制脱敏、单条上限、保留期清理；体积告警指向对象存储演进 |
| SQLite 承接高频写入 | 网关与高流量接入的文档明确推荐 PostgreSQL；攒批写入 |
| 语义约定各家有方言 | 以实测矩阵为准补映射，映射固化为测试防回归 |
| 转用例的预期行为难以自动生成 | 只做预填不做自动判定，预期断言始终由人确认 |

## 11. 被否决的方案

1. **自研采集 SDK**：维护成本无上限，且与"接标准"的行业终局背道而驰。
2. **先建 ClickHouse/对象存储**：当前量级用不上，复杂度先行会拖慢闭环验证。
3. **把观测做成产品本体**（看板、打分、prompt 管理全套）：正面进入红海，放弃自己的差异化。
4. **网关做成独立部署组件**：多一个进程多一份运维负担，先内置于 `agentrig serve`，
   将来有需要再拆。

## 12. Definition of Done

- [x] 车道 A、B 可用且共用同一套 Trace 存储与策略（车道 C 随 M4）；
- [x] 接入向导页上线，三种埋点配方文档实测通过；
- [x] `save_full_content` 策略落地，默认关闭，脱敏与保留期覆盖全文；
- [x] 一条真实 trace 可一键转为用例，工具调用自动生成 Sample 草稿并重放通过；
- [ ] 端到端旗舰演示完成并进入 README；
- [ ] 本 RFC 状态改为 Implemented，偏差记录在头部。

## 13. 实施状态

> 更新：2026-09-09

| 里程碑 | 状态 | 落地内容 | 证据 |
|---|---|---|---|
| M1 车道 B 接入体验 | Implemented | `/v1/traces` 增加 `application/json` 分支并复用同一归一化；补齐方言映射；接入向导页上线；接入指南成文 | `production/api.py`、`production/otlp.py`、`tests/test_otlp_ingest_dialects.py`、`web/app/pages/governance/onboarding-page.tsx`、`web/e2e/onboarding.spec.ts`、`scripts/send_demo_traces.py`、[04-Trace 接入指南](./04-Trace接入指南.md) |
| M2 车道 A 网关 | Implemented | `POST /gateway/{source_id}/v1/{suffix}`；SSE 透传边转发边攒；响应后异步落 trace；上游 key 只存 `env:` 引用；出站复用 `TargetHttpPolicy` | `production/gateway.py`、migration `20260908_0009`、`tests/test_gateway.py` |
| M3 全文存储与转用例 | Implemented | `save_full_content` 第三档策略；Trace 详情与转用例动线补强；真实工具调用自动生成 Sample 草稿 | `production/service.py`、`production/otlp.py`、migration `20260908_0010`、`tests/test_production_evidence.py`、治理页 Trace 工作台 |
| M4 聚类、多轮、导入与门禁 Action | Pending | 失败聚类建议、会话转多轮用例、车道 C 批量导入、CI 门禁 Action、端到端旗舰演示 | — |

与 RFC 原文的偏差：

1. **方言实测口径**。已固化为测试的是三个方言族——OTel GenAI（含 `gen_ai.prompt.N` /
   `gen_ai.completion.N` 的 Traceloop/OpenLLMetry 写法）与 OpenInference（`openinference.span.kind`、
   `llm.*`、`input.value` / `output.value`）。AgentScope 自带埋点走 GenAI 族，未单独留实测记录。
2. **网关端点范围**。首版按 RFC 覆盖 `chat/completions`（含流式）与 `embeddings`；其余 `/v1/*`
   端点透传但不记录。
3. **车道 C 与失败聚类**顺延到 M4，未进入当前实现承诺。

M4 完成后把本文状态改为 Implemented，并将旗舰演示写进 README。
