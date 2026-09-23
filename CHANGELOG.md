# Changelog

本文件记录 AgentRig 的版本变更。格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循 [SemVer](https://semver.org/lang/zh-CN/)。

## [Unreleased]

按 RFC AR-RFC-0005 落地生产 Trace 接入的前三个里程碑：把"能收 trace"变成"好接入、能转用例"。
M4（失败聚类建议、会话转多轮用例、批量导入车道、CI 门禁 Action）尚未实施。

### Added

- 新增 OpenAI 兼容网关车道 `POST /gateway/{source_id}/v1/{suffix}`：按接入源鉴权与路由、SSE
  透传时边转发边攒完整响应、响应结束后旁路落 trace；上游 key 只接受 `env:` 引用，出站复用
  `TargetHttpPolicy` 防 SSRF；上游错误原样透传并记录失败 trace，网关自身不重试、不降级。
- `/v1/traces` 增加 OTLP/JSON 编码分支，与 protobuf 复用同一套归一化、鉴权、限流和幂等逻辑；
  补齐 Traceloop/OpenLLMetry 与 OpenInference 方言映射，并固化为方言回归测试。
- 新增 `save_full_content` 第三档正文策略：默认关闭，开启后保存脱敏后的完整消息数组与工具
  参数/结果，受单条体积上限约束并随接入源 `retention_days` 一起清理。
- Trace 转用例在开启全文后自动把成对的 `tool_call` / `tool_result` 提取为 Sample 草稿，经人工
  审核即可用于不触发真实副作用的重放；动作沿用既有不可变 lineage 记录来源。
- 新增 Web「接入」向导页：选车道、建接入源（token 只显示一次）、复制按车道生成的配置片段、
  驻留探测第一条 trace 到达；配套浏览器 E2E 与 `scripts/send_demo_traces.py` 本地自检脚本。
- 新增[生产 Trace 接入指南](./docs/04-Trace接入指南.md)，覆盖两条车道配方、语义方言识别范围与
  隐私三档策略。

### Changed

- Simulation Curator 更稳健：`json_object` 输出模式也附上结构 Schema；模型返回合法 JSON 但外壳不是
  `{result, state_updates}` 时，按校验反馈纠正一次，而不是直接让 CaseRun 失败。
- 文档基线同步到当前实现：重写[总体架构](./docs/00-总体架构.md)（六个对外入口、分层模块地图、
  Run/Cell/Attempt 执行模型、39 张表与两种执行形态），更新[实现与接入](./docs/01-核心Agent价值复核与讨论交接.md)
  的包结构与 MCP 工具面，修正快速开始中早已移除的 `/mcp/manager`、`/mcp/curator`、`/mcp/judge`
  端点，并为 AR-RFC-0003 与 AR-RFC-0005 补逐条实施状态。

### Migrations

- `20260908_0009_gateway_ingest_sources`：接入源增加网关车道配置列。
- `20260908_0010_trace_full_content`：Trace 增加脱敏全文列。

## [0.3.0a0] - 2026-09-07

在 V2.3 运行时验证与生产证据能力之上，移除不属于公开范围的交付材料与外部多 Agent 协作
集成，收敛为面向单被测 Agent 的开源回归评测平台。

### Added

- 新增从终态 Run 不可变事实派生的 `QualityReport`、A/B `ComparisonReport` 和版本化
  `ReleaseGateResult`，提供 JSON/Markdown HTTP API、CLI、稳定来源/结果哈希及默认门禁策略。
- 新增 ExecutionProfile 冻结价格快照与严格成本归因，缺模型或 token/cache 分项时保持未知而不填零。
- 新增 DriverEvent v2、AG-UI 与 AgentScope Driver，覆盖有序 cursor、permission、interrupt/resume、
  memory/workspace、model call 和嵌套 Agent 证据。
- 新增 Target Capability Snapshot/diff/运行计划、19 个 AgentScope 安全用例的四态报告与
  独立安全门禁。
- 新增标准 OTLP/HTTP protobuf 生产证据接入、双重脱敏、幂等 Trace/Span、retention/tombstone、
  Trace→Case 预览、人工审批和不可变 lineage；终态 Run 支持 best-effort 元数据 OTLP 导出。
- 新增 append-only Review/Annotation/GoldLabel、Judge 版本与分 cohort alignment gate，以及
  Failure Signal→Pattern→Monitor 治理、签名幂等 Webhook 和复发时间线。
- 新增 Project/Environment/API Key 隔离、PostgreSQL lease/heartbeat durable worker、取消与旧 token
  fencing，以及外部 Real Tool 请求前自动持久化的 no-retry 副作用围栏。
- Durable dispatch 按 Run 批量原子入队、每个 CaseRun 唯一 Job，并可在重启后按 intent 补派；Run/Job
  取消、reaper、晚到 executor 与多 Worker 收尾统一收敛，Assistant/OTLP completion hook 单次触发。
- 新增 Production Evidence、Review、Failure Pattern 和 Durable Job 的 Project-scoped Web 工作台、
  Browser→FastAPI→SQLite→Reference Target 真后端 E2E 与 `scripts/accept_v23.sh`。
- 新增按 Run 查询 AgentInvocation 的 Repository/Service 契约，使质量报告可以汇总 Worker 调用结果。
- Public Reference Demo 将已知 A/B 回归作为门禁负向控制，并把 Quality、Comparison 和 Gate JSON
  纳入 ReleaseEvidence 与离线校验的 `SHA256SUMS`。

### Changed

- 全部 Skill 升级为可机械验证的严格 contract，固定输入输出 Schema、工具权限和
  内容 hash，构建时拒绝漂移或越权。
- 持久化 schema 扩展 Project、Capability、Production Evidence、Review、Failure Governance 和
  Durable Job 域，并增加 SQLite/PostgreSQL migration 往返验证。
- 重构中英文项目首页，增加价值定位、真实界面、架构、可验证场景、分层 Quick Start、成熟度与
  文档导航，移除首页中过度密集的部署细节。
- 新增统一快速开始/安全部署手册与支持指南，重构文档门户、贡献指南、安全策略、Issue 表单和
  PR 模板，并使所有校验命令与当前 CI 保持一致。
- 补齐包和 GitHub 仓库的对外描述、文档/安全入口与主题元数据。
- 持久化数据库启动前强制校验 Alembic revision，避免 ORM 自动建表与迁移历史分叉。
- Run 选择、重复展开、CaseRun 数量及 API 分页增加部署级上限。
- V2 调用方身份默认不再信任客户端自报 Header，仅允许可信代理显式配置身份 Header。
- Target HTTP(S) 出站增加 URL、私网地址、DNS 解析和主机 allowlist 校验。
- Run 报告与 Target 数据导出改由服务端遍历完整分页生成，统一脱敏并拒绝超限或并发变化下的残缺文件。
- CI 增加锁定 Python 运行时依赖和前端依赖漏洞审计。

### Removed

- 移除不属于开源范围的交付材料：专项演示与录制脚本、录制截图 E2E 用例及相关 Git tag。
- 整体移除外部多 Agent 协作集成：聊天协议 Bridge、三角色 MCP 工具面、Worker 调用域、
  自适应决策记录域、8 项角色 Skill、`deploy/` 部署包与兼容 CLI。迁移 `20260907_0008` 删除
  三张对应表及全部相关列，并清理协作期历史事件；降级不恢复数据。
- 移除仅适配单一私有产品的专属 HTTP/SSE Driver；通用 `http_sse` Driver 继续覆盖同类协议。
- 质量报告随协作指标移除升级为 `agentrig.quality-report.v2`；运行证据导出更名为
  `agentrig.run-evidence.v1`。
- 私有被测对象的名称、示例 ID 与截图全部替换为公开 Reference Target。

### Security

- 将 Vite/PostCSS 的传递依赖 Nano ID 锁定到 `3.3.18`，修复可能由零长度自定义生成器触发的
  无限循环拒绝服务风险（GHSA-2v37-7h3g-55p8）。

## 0.3.0a0 之前

0.3.0a0 之前的版本在本仓库的公开范围之外：相应实现或已被上述 Removed 条目移除，或只存在于
维护者本地的开发历史中。当前实现的权威边界见 [docs/00-总体架构](./docs/00-总体架构.md)。
