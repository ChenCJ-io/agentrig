# Project 边界与耐久执行基础方案

> 专题 ID：AR-V23-WP09
>
> 状态：Implemented（SQLite/契约与 PostgreSQL 17.7 双 Worker 集成验收完成）
>
> 优先级：P2/P3
>
> 目标里程碑：V2.4—V2.5

## 0. 实施状态（2026-08-11）

- migration `20260810_0005` 新建 default Project/Environment/API key、生产证据、审核治理、Failure
  Pattern 和 ExecutionJob/Attempt/Worker 表，并为现有核心资产回填 `project_id`；
- Repository/Service 默认使用显式 Project scope，跨 Project ID/列表/后台任务均拒绝；Project API key
  使用一次性 token、hash、prefix、expiry/revoke 与 read/ingest/run/review/admin scope，中间件按路由
  最小权限校验；
- Durable Job 支持数据库 claim、lease token、heartbeat、reaper、attempt、cancel、idempotency 与 fencing；
  Real Tool 在发起外部请求前按 attempt 自动持久化副作用 fence；过期或 stale attempt 进入 dead，
  不自动重放；
- 每个 CaseRun 只允许一个 Durable Job；整批 dispatch 在单事务中可见，并以 `dispatch_intent` 区分直接
  Run 与 EvaluationPlan。API/Worker 重启会补派 direct 或已 submitted Plan 的缺失 Job，不会误执行尚未
  submitted 的 staged Plan；
- Job/Attempt/Run 的竞争更新使用行锁；Run 级取消、单 Job 取消、lease reaper 与晚到 executor 都会把
  CaseRun/Run 收敛到同一终态。多 Worker 竞争收尾只有一个提交者触发 Assistant 通知与可选 OTLP 导出，
  listener 失败不回滚已提交终态；
- `agentrig worker` 支持独立 worker/`--once`，默认仍是兼容 SQLite 的单进程 Scheduler；SQLite 主动
  拒绝第二个 durable worker；
- SQLite migration 往返和确定性状态机测试已完成。PostgreSQL 17.7
  `FOR UPDATE SKIP LOCKED` 双 worker、crash recovery、旧 token fencing 与 retention round-trip 已在一次性
  真实 cluster 执行通过。

## 1. 目标

在不破坏本地单机体验的前提下，为生产 Trace、多环境策略、长期运行和未来多副本建立最小基础：

- 逻辑 Project 隔离；
- Project 级 environment/release/retention/API key；
- PostgreSQL durable scheduler lease/heartbeat；
- API 与 worker 的可拆分边界；
- 后续 OIDC/RBAC、Helm 和多副本的演进路径。

本专题是产品基础，不应抢占 V2.3 Gate/Driver/Snapshot 的交付顺序。

## 2. Project 最小模型

```text
Project
  id, slug, name, status,
  default_environment,
  redaction_policy_id,
  retention_policy_id,
  created_at, archived_at

Environment
  id, project_id, name, kind,
  release_metadata_schema, protected

ProjectApiKey
  id, project_id, name, key_hash,
  scopes, expires_at, last_used_at, revoked_at
```

首个 migration 创建 `default` Project，并把现有资产、Session、Plan、Run、Decision、Invocation 和配置
归属到它。SQLite 也执行相同逻辑，用户无需手动迁移本地数据。

## 3. Project 归属范围

必须有 `project_id`：

- TestCase、Target、ExecutionProfile、Sample；
- AssistantSession、EvaluationPlan、DecisionRecord；
- Run、CaseRun、Evaluation、AgentInvocation；
- ProductionSession/Trace/Span、Annotation、FailurePattern；
- ReleasePolicy binding、IngestSource、API key、Retention policy。

RunEvent 可通过 CaseRun 继承 Project，查询必须 join/过滤；高频表是否冗余 `project_id` 由 PostgreSQL
性能测试决定。任何 repository 方法不得依赖调用方“记得过滤”。

## 4. 迁移策略

采用 expand/migrate/contract：

### 4.1 Expand

- 新建 projects 和 default Project；
- 各表添加 nullable `project_id`；
- API 暂时默认 current/default Project；
- 新写入同时填 project_id。

### 4.2 Migrate

- 批量回填历史数据；
- 验证跨表归属一致；
- 创建复合唯一索引，例如 `(project_id, slug)`；
- PostgreSQL/SQLite 均跑完整 migration test。

### 4.3 Contract

- `project_id` 改为 non-null；
- Repository 入口强制 ProjectContext；
- 删除隐式全局查询；
- API URL 或 token context 明确 Project。

迁移前后历史 ID、Run hash 和 evidence refs 不改变。Project ID 加入访问上下文，但历史业务 snapshot
hash 是否包含 Project 要按 Schema 版本处理，不重算 v1 hash。

## 5. 访问控制演进

### 5.1 V2.4 最小范围

- Project-scoped API key；
- scope：read、run、review、ingest、admin；
- Web 当前用户只能选择被授权 Project；
- 所有跨 Project ID lookup 返回统一 not found，避免枚举；
- 审计 Project 切换和关键写操作。

### 5.2 V2.5 以后

- OIDC 登录；
- role：viewer、operator、reviewer、evaluator_admin、project_admin；
- service account 和短期 token；
- 组织/Workspace 层级仅在真实需求出现后新增。

首版不建设复杂 ABAC。Core 的 Real Tool/confirmation 权限继续独立，Project role 不能自动批准外部动作。

## 6. Release 与环境

新增标准 `ReleaseRef`：

```text
environment, version, git_sha,
build_id, image_digests,
deployed_at, metadata, content_hash
```

ProductionTrace、Capability Snapshot、Run 和 Failure Pattern link 都使用 ReleaseRef。`production` 是受保护
environment，写入 release metadata 需要独立 scope。未知 release 明确为 null/unknown，不用 `latest`。

## 7. 耐久 Scheduler

### 7.1 当前问题

现有进程内 Scheduler 在重启时把 queued/running 标记 interrupted，不支持多副本领取或断点恢复。生产
Trace 和长期 suite 增加后，需要 PostgreSQL 上的耐久 claim。

### 7.2 Job/Lease 模型

建议首版增加：

```text
ExecutionJob
  id, project_id, run_id, case_run_id,
  status: queued | leased | running | completed | failed | cancelled | dead,
  priority, available_at,
  lease_owner, lease_token_hash, lease_expires_at,
  heartbeat_at, attempt, max_attempts,
  idempotency_key, last_error_code,
  created_at, updated_at
```

领取使用 PostgreSQL `FOR UPDATE SKIP LOCKED`。worker 获得随机 lease token，只能更新自己的当前 lease。
heartbeat 延长 lease；超时后由 reaper 按 retry policy 重新排队或标记 interrupted/dead。

### 7.3 幂等和副作用

- Run/CaseRun 先冻结并记录 dispatch intent；同一 Run 的缺失 Job 在一个事务内整批创建，重启恢复只
  补派 direct 或已提交 EvaluationPlan；
- 每次 execution attempt 有独立 ID；
- Provider/Tool 调用继续使用 CaseRun scope 与幂等 key；
- 已确认产生外部副作用的 attempt 不自动重跑；
- cancel 写入持久状态，worker 在每个边界检查；
- 晚到 worker 不能用过期 lease 改写新 attempt；
- 旧 Attempt 的事件保留，并关联 `attempt_id`。

### 7.4 SQLite 行为

SQLite 保持单进程 scheduler，不宣传多副本安全。使用同一 ExecutionJob Schema 便于开发，但禁用
`SKIP LOCKED` 路径，并在启动第二 worker 时明确拒绝。

## 8. API/Worker 拆分

```text
agentrig serve       # API/Web/MCP，可选本地 worker
agentrig worker      # PostgreSQL durable worker
agentrig scheduler   # 可并入 worker 的 claim/reaper loop
```

首版仍允许单进程默认值。拆分后：

- API 只规划和提交 Job；
- worker 执行 Driver/Provider/Judge；
- MCP Proxy scope 若仍是内存对象则必须 sticky/外部化后才能多副本；
- live SSE/ACP session 的 lease ownership 不能跨 worker 漂移；
- graceful shutdown 停止 claim、等待有界时间、释放或中断 lease。

在 Proxy scope 和 session ownership 未解决前，不宣称完全无状态多副本。

## 9. 容量与 SLO

先建立基线：

- queue wait p50/p95；
- claim/heartbeat/reaper 延迟；
- queued/running 数量；
- DB pool、lock wait 和 deadlock；
- event/trace 写入吞吐；
- worker crash/recovery 时间；
- cancel latency；
- Project retention job 时长。

只有实测证明 PostgreSQL 成为瓶颈后，才评审外部队列或 Temporal。

## 10. 部署路线

### 10.1 V2.4

单机/Compose：API + worker + PostgreSQL，OTLP ingest 默认内网。

### 10.2 V2.5

参考 Helm：API Deployment、Worker Deployment、migration Job、Secret refs、NetworkPolicy、PDB、readiness、
资源限制。数据库建议外部托管，不在 chart 中默认安装生产 PostgreSQL。

### 10.3 后续

OIDC、RBAC、多 region、独立 artifact store 和专用 Trace storage 按实际客户/容量需求评审。

## 11. 安全

- ProjectContext 在 HTTP/MCP/worker/后台任务全链路传递；
- API key hash、到期、撤销、scope 和轮换；
- lease token 不写日志；
- worker 只能访问分配 Project 所需 Secret refs；
- retention/delete job 有 dry-run、审计和 Project 精确目标；
- 生产 ingest 与 Run API 使用不同 key scope；
- Helm 默认拒绝公网暴露内部 Matrix、Collector、数据库和 worker。

## 12. 测试

- default Project 回填和 migration rollback/forward；
- 所有 Repository 的跨 Project 隔离；
- API key scope/expiry/revoke；
- 并发 claim 唯一性；
- worker crash、lease expiry、late worker fencing；
- cancel/claim/heartbeat 竞态；
- Run 取消与晚到 executor completion 的终态 fencing；
- dispatch 前崩溃后的 intent-aware 自动补派，以及 staged Plan 不被误派；
- 多 Worker 并发终态提交只触发一次 completion listener；
- 有外部副作用的 attempt 不自动重试；
- PostgreSQL 多 worker 压测；
- SQLite 第二 worker 明确拒绝；
- retention 只删除目标 Project 数据。

## 13. 验收标准

- [x] 所有现有数据通过 expand/backfill 迁入 default Project，迁移可 downgrade/upgrade；
- [x] 跨 Project ID/搜索/导出/后台任务隔离测试全部通过；
- [x] read/ingest/run/review/admin Project key scope 分离；
- [x] 两个 PostgreSQL worker 的 `SKIP LOCKED` 唯一领取测试已在 PostgreSQL 17.7 运行通过；
- [x] crash recovery/旧 token fencing 测试已在 PostgreSQL 17.7 运行通过；
- [x] 已知外部副作用不会因 lease 过期自动重复；
- [x] durable Run/单 Job 取消、晚到 executor、dead CaseRun 收敛与重启补派均有确定性测试；
- [x] PostgreSQL 并发终态提交通过 Run 行锁只触发一次 completion listener；
- [x] SQLite 单机体验和现有命令继续可用，并明确拒绝第二个 durable worker；
- [x] 多副本限制在文档、配置与 worker 注册行为中如实展示；
- [x] 生产化组件均为默认关闭，未成为 V2.3 核心门禁的前置负担。

## 14. 灰度与回滚

Project migration 在 contract 阶段前保持旧 API 的 default Project 兼容入口；回滚代码时不得删除已经
写入的 Project 归属。Durable scheduler 先以单 worker 启用，再扩到两个 worker；异常时停止新 claim，
让有效 lease 有界结束并切回单 worker。已经创建的 ExecutionJob/Attempt 保留为审计事实，不能退回
进程内 Scheduler 后伪装成从未执行。
