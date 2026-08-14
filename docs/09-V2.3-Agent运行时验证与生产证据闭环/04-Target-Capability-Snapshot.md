# Target Capability Snapshot 方案

> 专题 ID：AR-V23-WP04
>
> 状态：Implemented（本地确定性验收完成）
>
> 优先级：P1
>
> 目标里程碑：V2.3

## 0. 实施状态（2026-08-11）

- 新 CaseRun 由 Planner 在入队前冻结 `agentrig.target-capability-snapshot.v1`，执行前可再合并 Driver
  的 observed 结果；历史快照只读；
- Snapshot 分区覆盖 runtime/model/tool/skill/permission/workspace/memory/collaboration/features，并为
  总体和各分区生成 canonical hash；
- Capability diff/policy 支持阻断字段、显式 allowed difference、unknown/legacy 语义，并接入
  ComparisonReport 的 `incomparable_environment`；
- Target probe、CaseRun snapshot、CaseRun diff HTTP API 和 Web 展示已经落地；
- canonicalization、字段漂移、allowed difference、legacy/partial、敏感正文排除及 Planner skip/
  inconclusive 均有确定性测试。

## 1. 要解决的问题

Agent 的行为不仅由代码版本决定，还受到 Runtime、模型、工具 Schema、Skill、权限、Memory、Workspace
和热加载状态影响。当前 CaseRun 虽冻结 Target/Profile 配置，但无法完整证明实际运行环境。

典型风险：

- Target ID 和版本相同，实际模型或参数已经变化；
- Skill 名称相同，内容已经热更新；
- Tool 名称相同，JSON Schema 不同；
- A/B 两边使用不同权限模式、Memory backend 或 Workspace image；
- 配置声明支持 resume，Runtime 实际没有验证；
- 历史报告按当前价格、当前镜像或当前 Skill 被错误解释。

本专题引入 `TargetCapabilitySnapshot`，在 CaseRun 执行前冻结声明、观测和验证结果。

## 2. 设计决策

1. Snapshot 是 CaseRun 冻结快照的一部分，不是可变的 Target 资产属性。
2. 首版不新增独立数据库表；在 CaseRun snapshot JSON 中保存，并追加一个 snapshot RunEvent。
3. Snapshot 只记录可公开元数据、摘要和 hash，不记录 Secret、完整 Memory 或 Tool 输出。
4. Capability 分为 `declared`、`observed`、`verified`，不能用配置声明冒充真实验证。
5. A/B Gate 在比较产品结果前先比较阻断级 Capability。

## 3. Schema

```json
{
  "schema_version": "agentrig.target-capability-snapshot.v1",
  "snapshot_id": "capsnap_xxx",
  "case_run_id": "cr_xxx",
  "collected_at": "2026-08-10T00:00:00Z",
  "collection_status": "complete",
  "source": {
    "driver": "agentscope_service",
    "probe_version": "1",
    "target_config_hash": "sha256:..."
  },
  "runtime": {
    "framework": "agentscope",
    "framework_version": "2.0.6",
    "service_version": "...",
    "protocol": "agentscope-2.0",
    "protocol_version": "...",
    "image_digest": "sha256:..."
  },
  "models": [],
  "tools": [],
  "skills": [],
  "permissions": {},
  "workspace": {},
  "memory": {},
  "collaboration": {},
  "features": {},
  "missing_fields": [],
  "limitations": [],
  "snapshot_hash": "sha256:..."
}
```

### 3.1 Runtime

记录 framework/runtime/service/protocol 版本、构建 SHA、镜像 digest、操作系统/架构的安全摘要。命令行
路径、主机目录和容器内部 Secret 路径不进入快照。

### 3.2 Model

每个模型记录：

```text
role, provider, model_id, revision,
parameters_hash, tokenizer_id, capabilities,
pricing_snapshot_hash, source_status
```

不保存 API key、base URL 中的凭据或完整 system prompt。Prompt 使用独立 version/hash 引用。

### 3.3 Tool

记录 tool name、namespace、description hash、input/output Schema hash、执行模式、来源 MCP server identity
和是否受 AgentRig controlled/proxy/observe_only 管理。排序、description 空白和 JSON object key 顺序不
应改变 Schema canonical hash。

### 3.4 Skill

记录 Skill ID、contract version、source、package/content hash、assigned target、runtime observed hash、
enabled 状态和验证 canary。AgentTeams v1.2.2 必须同时记录 declared 与 observed 值。

### 3.5 Permission

记录默认 permission mode、可确认动作类别、是否支持 HITL/resume、AgentRig Real Tool 是否启用，以及
来源状态。绝不记录实际 authorization token。

### 3.6 Workspace 与 Memory

Workspace：backend、隔离方式、base image digest、network policy ID、mount policy hash、artifact support。

Memory：backend、scope、namespace hash、snapshot/version、reset support、cross-session policy。内容本身不
进入 Capability Snapshot。

### 3.7 Collaboration

记录 AgentTeams/runtime version、Manager/Worker stable identity、room/team ID hash、Skill delivery mode 和
子 Agent 支持。历史比赛 profile 明确标记 `agentteams_version=v1.1.2`。

## 4. 状态语义

### 4.1 字段来源

| 状态 | 含义 | 可否用于阻断式可比性 |
|---|---|---|
| `declared` | 来自 Target/Profile 配置 | 仅低风险字段 |
| `observed` | 由 Runtime API/事件看到 | 可用于说明，取决于策略 |
| `verified` | 通过 canary/签名/schema 实际验证 | 可以 |
| `unsupported` | Runtime 明确不支持 | 可以判断用例不适用 |
| `unknown` | 无法查询或探针失败 | 默认不可比/inconclusive |

### 4.2 collection_status

- `complete`：策略要求字段全部 observed/verified；
- `partial`：允许执行但有限制；
- `unavailable`：探针失败；
- `invalid`：发现自相矛盾或不安全数据。

是否允许 partial 执行由 ExecutionProfile 决定。Release A/B 默认不接受阻断字段 unknown。

## 5. 采集流程

```text
Planner 解析 Target/Profile
  → 静态配置 canonicalize
  → Driver.validate_configuration
  → Driver.prepare/probe
  → describe_capabilities
  → Tool/Skill/Runtime canary（按 profile）
  → Redactor + Schema validation
  → canonical hash
  → freeze in CaseRun
  → execute prompt
```

采集必须发生在首条用户消息前。若 Runtime 在采集后、执行前报告版本变化，CaseRun 终止为
`inconclusive/environment_changed`，不使用新状态继续执行。

## 6. Canonical Hash

规则：

- RFC 8785 风格稳定 JSON 或项目明确实现的等价 canonical JSON；
- object key 排序，数组按语义决定是否排序；
- 时间戳、probe duration、展示 label 不进入业务 hash；
- `unknown` 与字段缺失是不同值；
- Secret/ref 的实际值永不参与，只有稳定 secret reference name 的 hash 可选参与；
- hash 算法固定 SHA-256，并在 Schema 版本内不得改变。

同时生成分区 hash：`runtime_hash`、`model_hash`、`tools_hash`、`skills_hash`、`permissions_hash`、
`workspace_hash`、`memory_hash`，便于定位漂移。

## 7. A/B 可比性

新增纯函数 `compare_capabilities(baseline, candidate, policy)`：

```text
comparable
warning_difference
incomparable_environment
unknown
```

默认阻断差异：

- 用例未明确要求的模型版本不同；
- Tool input/output Schema 不同；
- Skill content hash 不同；
- permission、Real Tool 或 network policy 不同；
- Workspace image/隔离方式不同；
- Memory scope/snapshot 不同；
- Runtime/framework major/minor 不同且策略未允许。

允许差异必须在 TestCase/ComparisonPolicy 中显式声明，例如测试本身就是比较模型或 Skill 版本。报告
展示允许差异的理由，不能简单忽略。

## 8. API 与 UI

```text
GET /api/case-runs/{case_run_id}/capability-snapshot
GET /api/case-runs/{case_run_id}/capability-diff/{other_case_run_id}
POST /api/targets/{target_id}:probe-capabilities
```

Target 探针返回当前观测，不写入历史 CaseRun。Web 在 CaseRun 顶部展示 Snapshot hash、状态和漂移；
A/B 页先展示环境差异，再展示产品结果。

## 9. 安全与容量

- Schema/description/system prompt 只保存 hash 或经过审核的公开字段；
- Tool Server 地址按现有网络策略脱敏；
- Snapshot 大小设置上限，完整 SBOM/Tool schema 作为 artifact 单独按 hash 引用；
- 探针不得执行真实写工具；canary 仅使用显式 safe probe；
- probe failure 不触发无限重试；
- Snapshot 导出继续使用 Redactor 和 filename/path 安全策略。

## 10. 测试

- canonicalization/property tests；
- 相同配置顺序不同得到相同 hash；
- Skill/Tool/permission 任一阻断字段变化得到不可比；
- declared 不被错误升级为 verified；
- Secret、绝对路径和 prompt 正文不进入 JSON；
- Runtime 在 probe 后漂移时执行停止；
- v1 Driver 无 describe 能力时生成 partial，而非崩溃；
- SQLite/PostgreSQL snapshot 序列化一致。

## 11. 验收标准

- [x] 每个新 CaseRun 在首条 prompt 前冻结 Capability Snapshot；
- [x] AgentScope、AgentTeams v1.1.2/v1.2.2 和 reference target 都有适配；
- [x] Tool/Skill/permission/workspace/memory 的 hash 可独立比较；
- [x] Secret、隐藏思维和完整 Memory 内容扫描结果为 0；
- [x] A/B 环境差异能够产生 `incomparable_environment`；
- [x] 显式比较 Runtime/模型版本的用例可通过 policy 允许差异；
- [x] 历史 CaseRun 始终返回原 Snapshot，不随 Target 当前状态变化；
- [x] 缺少 capability 时不会误报 pass。

## 12. 迁移

历史 CaseRun 没有 Snapshot 时返回 `legacy_unavailable`，不做猜测回填。迁移只增加可空 snapshot 字段
或扩展已有 snapshot JSON。历史报告保持可读；只有明确要求 Capability Gate 的新策略才将 legacy Run
判为 inconclusive。

## 13. 灰度与回滚

先以 `observe_only` 方式采集并展示 diff，不影响 Planner/Gate；字段稳定后再对新 A/B Run 启用
`incomparable_environment`，最后才升级为 blocking。回滚时关闭 capability gate，但保留已经冻结的
Snapshot；不得删除快照或用当前 Target 状态重建历史值。
