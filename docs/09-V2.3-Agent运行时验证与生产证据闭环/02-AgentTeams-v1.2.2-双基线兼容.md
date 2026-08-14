# AgentTeams v1.2.2 双基线兼容方案

> 专题 ID：AR-V23-WP02
>
> 状态：Implemented（本地契约验收完成；双基线 Live 验收待执行）
>
> 优先级：P0
>
> 目标里程碑：V2.3

## 0. 实施状态（2026-08-11）

- `deploy/agentteams/profiles/` 同时保留只读 v1.1.2 competition profile 和新增 v1.2.2 current
  profile；后者固定 CRD Schema hash 与多架构 OCI digest，不接受 tag/`latest`；
- profile adapter 校验版本、资源 group、三角色 identity/MCP route、Skill observed hash、canary、
  private room membership 和 Invocation correlation；
- `agentrig.agentteams-compat-report.v1` 对失败与限制分域，source/result hash 稳定，两个 profile 的
  报告互不覆盖；
- v1.2.2 package manifest 嵌入严格 Skill contract manifest hash、contract version 和内容 hash；
- `scripts/build_agentteams_compat_report.py` 和 `scripts/accept_v23.sh live` 已提供真实观测验收入口，
  退出码为 complete=0、failure=2、limitation=3、usage error=64。

本地 fixture/contract/package 验收已经完成。真实 v1.1.2 与 v1.2.2 集群观测尚未在本工作区执行，
因此不将合成 observation 报告表述为 Live 证据。

## 1. 决策

AgentRig 采用双基线，而不是原地升级：

| Profile | 目的 | 资源/API | 状态 |
|---|---|---|---|
| `agentteams-v1.1.2-competition` | 重放并保留 GOAI 竞争事实 | legacy `hiclaw.io/v1beta1` | 冻结维护 |
| `agentteams-v1.2.2-current` | 当前开发、Release 与后续生产 | `agentteams.io/v1beta1`、QwenPaw | 新增支持 |

v1.1.2 的资源、VERSION、证据、截图和 package 继续保留。任何迁移脚本不得修改历史 evidence bundle
或把旧 Run 标记成由 v1.2.2 产生。

## 2. 外部变化与影响

v1.2.x 需要重点适配：

- AgentTeams 统一命名与新资源 group；
- Manager/Worker 资源关系和 `spec.workerMembers`；
- QwenPaw 统一 Manager/Worker Runtime；
- TeamHarness/Matrix 任务状态和原子交接；
- Manager-to-Worker Skill 上传、校验、分配、热刷新和启用；
- Manager Skill 热加载；
- Matrix team room membership 收敛；
- 自定义模型视觉/推理能力、token 轮换和 runtime reliability。

这些变化要求 AgentRig 从“资源 apply 成功”升级为“所需能力确实运行且内容可证明”。

## 3. 目录与配置

建议部署目录调整为：

```text
deploy/agentteams/
  VERSION                         # 保留 competition baseline 的明确说明
  profiles/
    v1.1.2-competition/
      resources.yaml
      manifest.json
      README.md
    v1.2.2-current/
      resources.yaml
      manifest.json
      README.md
  packages/
    manager/
    curator/
    judge/
  dist/
```

配置新增显式选择，禁止从远端 `latest` 推断：

```toml
[agentteams]
enabled = true
profile = "v1.2.2-current"
version = "v1.2.2"
runtime = "qwenpaw"
resource_api_version = "agentteams.io/v1beta1"
```

启动时 profile、version、resource API 不一致必须失败；不能静默 fallback 到 legacy。

## 4. 兼容适配层

把版本差异隔离在 integration adapter，不泄漏到 AssistantSession、DecisionRecord、AgentInvocation 和
Run 核心：

```text
AgentTeamsAdapter
  discover_runtime()
  apply_resources()
  reconcile_membership()
  deliver_skill()
  describe_worker()
  verify_invocation_route()
  rotate_transport_token()
```

实现两个 adapter：

- `LegacyAgentTeams112Adapter`
- `AgentTeams122Adapter`

共同输出归一化的 `AgentTeamsCapabilityReport`，至少包含：

```text
agentteams_version, runtime_name, runtime_version,
resource_api_version, manager_id, worker_ids,
skill_delivery_mode, room_membership_mode,
transport_health, observed_at, evidence_refs
```

## 5. v1.2.2 资源模型

新 profile 声明一个 Manager 和 Curator/Judge 两个独立 Worker，由 Manager 的 worker membership 明确
引用。具体字段以固定 v1.2.2 CRD 为准，生成资源前通过本地 vendored JSON Schema 校验，避免运行时
才发现字段漂移。

要求：

- YAML 中不写明文模型 key、Matrix token 或 AgentRig MCP token；
- Manager、Curator、Judge 继续使用三个隔离 MCP route；
- Manager 不能直接获得 `run_cases`；
- Curator/Judge 不能获得跨角色写工具；
- Worker identity 与 AgentRig 配置一一对应，不按显示名猜测；
- 当前 profile 的 CRD、controller/runtime 镜像 digest 进入 Capability Snapshot。

## 6. Skill 分发与可验证热加载

v1.2.2 使用正式分发链路：

```text
build deterministic package
  → validate local manifest/content hash
  → upload to Manager
  → assign to Worker.spec.skills
  → observe distribution status
  → verify runtime enabled state
  → execute canary invocation
```

每个角色记录：

- Skill ID、contract version、package SHA-256；
- 上传/存储对象版本或内容 hash；
- `Worker.spec.skills` 分配结果；
- runtime observed version 和 enabled 状态；
- 热刷新完成时间；
- canary 输入、响应 Schema 和 Matrix event ID。

只有“文件出现在容器目录”不算验收通过。配置漂移时产生明确 `skill_drift`，不得自动用当前本地文件
覆盖远端后继续测试。

## 7. Matrix 与任务交接验证

v1.2.2 live acceptance 至少验证：

1. Manager、bridge、Curator、Judge 在期望 room 中的 join 状态收敛；
2. 非成员无法读取 private room；
3. Manager 到 Worker 的任务具有稳定 invocation/correlation ID；
4. 重复/迟到 Matrix event 不产生重复副作用；
5. atomic handoff 后只有一个 Worker 获得任务所有权；
6. token 轮换期间已有任务得到有界终态，新任务使用新 token；
7. room membership 变化记录为审计证据，不进入 prompt 正文。

## 8. 版本兼容矩阵

| 验收项 | v1.1.2 | v1.2.2 |
|---|---:|---:|
| 安装/版本探针 | 必须 | 必须 |
| Manager/Curator/Judge 身份 | 必须 | 必须 |
| 三角色 MCP 隔离 | 必须 | 必须 |
| private Matrix session | 必须 | 必须 |
| Skill package hash | 本地/zip | 本地 + 远端 observed |
| Skill 热加载 | 不适用 | 必须 |
| QwenPaw runtime | 不适用 | 必须 |
| worker membership | legacy 方式 | `spec.workerMembers` + room convergence |
| 成功/失败 Invocation | 必须 | 必须 |
| 断网/重复/乱序恢复 | 必须 | 必须 |

普通 PR 使用 fake transport/contract fixture；nightly 或 Release 分别运行两个固定环境。live job 失败
必须区分安装、控制面、Matrix、Runtime、模型和 AgentRig bridge。

## 9. 迁移与灰度

### 9.1 阶段 A：只读探针

增加 v1.2.2 版本发现、CRD Schema 和 capability report，不创建资源。

### 9.2 阶段 B：隔离环境部署

使用独立 namespace/volume/Matrix room/credentials 部署 v1.2.2，不复用比赛 v1.1.2 runtime state。

### 9.3 阶段 C：双写配置，不双写任务

同一 suite 可分别跑两个 profile，但一个 AssistantSession/Invocation 只绑定一个 profile，避免一个任务
被两个 Runtime 同时消费。

### 9.4 阶段 D：默认 profile 切换

v1.2.2 连续通过 version matrix、三角色 live acceptance 和 AgentScope 安全 suite 后，开发默认值切换
为 v1.2.2；competition profile 仍保留显式入口。

## 10. 自动化与证据

新增产物 `agentrig.agentteams-compat-report.v1`：

```text
profile/version/runtime
resource schema hash
component image digests
role identities
skill distribution evidence
room membership evidence
invocation results
failures/limitations
source git SHA and generated_at
```

产物进入 ReleaseEvidence artifact 列表，但不修改 ReleaseEvidence v1 字段语义。

## 11. 验收标准

- [x] v1.1.2 的 VERSION、资源、包和历史证据未被覆盖；
- [x] v1.2.2 profile 固定版本、CRD Schema 和镜像 digest，不使用 `latest`；
- [x] 三角色资源、identity、MCP route 和权限完全隔离；
- [x] compat report 可查询每个远端 Skill 的本地 hash、分配、observed hash 和 enabled 状态；
- [x] Skill canary 引用观测内容 hash，历史 Invocation/profile 快照不被热更新改写；
- [x] adapter 对 room membership 排序去重并验证期望成员，消息 correlation 保持幂等；
- [ ] 在真实 v1.1.2 与 v1.2.2 环境各生成一份独立 complete compat report；
- [x] 关闭 AgentTeams 后 V1 Rule、HTTP/MCP 和已存证据继续可用。

## 12. 回滚

默认 profile 可切回 v1.1.2，但不能用旧 Runtime 读取并改写 v1.2.2 的 runtime state。回滚只改变新
Session 的路由；已启动 Invocation 继续在原 profile 完成或被明确取消。Skill package 和资源产物均
按内容寻址保留。
