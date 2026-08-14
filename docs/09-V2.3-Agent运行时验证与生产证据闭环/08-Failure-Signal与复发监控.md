# Failure Signal、失败模式与复发监控方案

> 专题 ID：AR-V23-WP08
>
> 状态：Implemented（本地确定性验收完成）
>
> 优先级：P2
>
> 目标里程碑：V2.5
>
> 依赖：Production Evidence、Annotation/GoldLabel、Release Gate

## 0. 实施状态（2026-08-11）

- FailureSignal 以 source/detector version 幂等，FailurePattern、Membership、definition version 和
  PatternEvent 分表保存，candidate 不会自动冒充 confirmed；
- 生命周期强制合法迁移，`resolved` 必须同时引用 approved Case、SuiteVersion 和实际 verified Run；
  ReleaseGate 可作为内容寻址链接附加；Critical exact recurrence 可生成 `regressed` 事件，其余候选
  保持人工确认；
- Monitor 保存 cursor、窗口、freshness/错误和 recurrence count；确定性 signature/cohort 不依赖向量
  或 LLM；
- Webhook payload 只含 Pattern 元数据/计数/相对链接，使用 env Secret HMAC、idempotency key、重试与
  dead 状态，发送失败不改变 Pattern；
- Signal/Pattern/Membership/lifecycle/link/monitor/timeline API 与 Governance Web 工作台已经落地。

## 1. 目标

把零散 Run/Trace 失败组织为可以负责、修复、验证和监控复发的问题单元。首版优先做人工可解释的
规则和 cohort，不以语义聚类作为前置条件。

```text
failed Evaluation / GoldLabel / production score
  → candidate membership
  → Failure Pattern review
  → confirmed pattern
  → link TestCase/Suite/Gate/Release
  → resolved after verified fix
  → production monitor
  → regressed when matching evidence returns
```

## 2. 术语

### 2.1 Signal

Signal 是某个事实上的单次失败迹象，例如 Rule fail、Judge fail、人工 fail、异常 error code 或用户手动
标记。Signal 不等于已确认产品问题。

### 2.2 Failure Pattern

Failure Pattern 是经人工确认、具有稳定定义和生命周期的一组相关失败。它包含匹配规则、代表证据、
影响范围、负责人和验证用例。

### 2.3 Monitor

Monitor 定期或持续检查新 Trace/Run 是否匹配已确认 Pattern。Monitor 是投影和通知源，不修改原始
Evidence/Evaluation。

## 3. 数据模型

### 3.1 FailureSignal

```text
id, project_id,
source_kind: evaluation | annotation | trace_score | manual,
source_id, source_snapshot_hash,
signal_type, severity, label,
environment, release, target/runtime,
detector_version, evidence_refs,
created_at
```

同一来源和 detector version 幂等。Detector 升级生成新 Signal，不覆盖旧记录。

### 3.2 FailurePattern

```text
id, project_id, title, description,
status: candidate | new | escalating | ongoing | resolved | regressed | ignored,
severity, priority, owner,
definition_version, matcher,
first_seen_at, last_seen_at,
resolved_at, ignored_reason,
representative_signal_ids,
linked_case_ids, linked_suite_versions,
linked_release_gate_ids, created_at, updated_at
```

Pattern 定义变化创建新 `definition_version`。状态变化追加 audit event。

### 3.3 PatternMembership

```text
pattern_id, definition_version, signal_id,
match_kind: exact | rule | semantic | manual,
match_score, explanation, status: candidate | confirmed | rejected,
reviewed_by, created_at
```

Semantic score 只是候选依据，不能自动变为 confirmed。

### 3.4 PatternEvent

记录 created、confirmed、assigned、linked_case、fix_verified、resolved、regressed、ignored、reopened 和通知
结果，形成可审计时间线。

## 4. Pattern 发现阶段

### 4.1 第一阶段：确定性与人工 cohort

- 相同 Rule/criterion failure；
- 相同 normalized error code/tool name；
- 相同 permission/sandbox invariant；
- 相同 Case/Suite regression；
- 保存的 Trace 搜索条件；
- 用户手动选择 Signal 建组。

这部分不需要 embedding，优先保证解释、重放和低误报。

### 4.2 第二阶段：文本/语义候选

数据量足够后，可使用脱敏 summary embedding 或 LLM clustering 产生 candidate：

- model/prompt/version 进入 detector version；
- cluster label 和摘要不作为事实；
- 每个候选展示代表样本、反例和差异；
- 人工确认 definition/matcher 后才进入 lifecycle；
- raw production content 不发送到未授权第三方模型。

## 5. 生命周期

```text
candidate → new → ongoing → resolved → regressed
              ↘ escalating      ↘ ignored（需理由）
```

规则：

- `candidate`：自动或人工发现，尚未确认；
- `new`：已确认且首次进入治理；
- `escalating`：频率、severity 或受影响 release 增加；
- `ongoing`：已知但未验证修复；
- `resolved`：关联 fix release 且回归 suite/Gate 通过；
- `regressed`：resolved 后新生产 Signal 匹配并经策略确认；
- `ignored`：非问题/接受风险/重复项，必须记录原因和期限。

仅“代码已合并”不能变成 resolved。必须至少存在关联 TestCase/Suite 和一次满足 Capability 可比性的
验证 Run；高风险 Pattern 还应经过发布后 observation window。

## 6. Pattern 到回归门禁

每个 confirmed Pattern 应逐步绑定：

1. 一组代表 ProductionTrace/Run evidence；
2. 至少一个 approved TestCase；
3. 一个 SuiteVersion；
4. candidate fix 的 A/B Run；
5. ReleaseGate check；
6. 部署 release/environment；
7. 上线 Monitor。

Gate 可增加：

```text
no_regression_for_confirmed_critical_patterns
all_blocking_patterns_have_verified_cases
resolved_pattern_suite_pass_rate
```

Pattern 不能直接覆盖 Case Evaluation；它只引用结果并形成发布策略。

## 7. Monitor 与复发

### 7.1 Monitor 输入

- 新 ProductionTrace/Signal；
- 新 Run/Evaluation/Gate；
- release/environment metadata；
- Pattern definition version。

### 7.2 状态与窗口

Monitor 保存 cursor、last success、last error、matched count 和 observation window。迟到 Trace 根据其
`occurred_at` 进入相应 release 窗口，但通知需要标记 late evidence。

### 7.3 复发规则

Critical Pattern 可在一个 confirmed exact/rule match 后直接进入 `regressed`；语义匹配默认先创建复发
candidate，人工确认后变更状态。阈值和观察窗口按 Pattern 版本化。

## 8. 通知与外部协作

首版支持 Webhook，Slack 作为 adapter：

- 只发送 Pattern ID、标题、severity、release、计数和 AgentRig 链接；
- 不发送 prompt、ToolResult、PII 或 Secret；
- 签名、重试、幂等 key 和 dead-letter 状态；
- 通知失败不改变 Pattern 状态；
- 速率限制、聚合窗口和静默时段；
- ignored/resolved/regressed 等人工变更记录 actor。

GitHub Issue/编码 Agent 派发后置；即使增加，也只能在人工批准后提交最小脱敏上下文。

## 9. API 与 Web

```text
GET  /api/projects/{project_id}/failure-signals
POST /api/projects/{project_id}/failure-patterns
GET  /api/failure-patterns/{id}
POST /api/failure-patterns/{id}/memberships:review
POST /api/failure-patterns/{id}:transition
POST /api/failure-patterns/{id}/links
POST /api/failure-patterns/{id}/monitors
GET  /api/failure-patterns/{id}/timeline
```

Web 提供 Pattern inbox、代表证据、membership review、生命周期、关联 Case/Run/Gate/Release 和复发时间线。
所有计数允许 drill down 到分子、分母和缺失项。

## 10. 指标

- confirmed Pattern 数量与 severity；
- time to review、time to verified case、time to resolve；
- Pattern 中带 approved Case/Suite 的比例；
- resolved 后复发率；
- candidate→confirmed precision；
- semantic membership 人工接受率；
- Monitor freshness/lag/error；
- 通知成功和抑制数量。

指标只用于治理，不作为 Judge 真值。

## 11. 测试

- Signal 幂等、detector version 和 Project 隔离；
- Pattern 状态机合法/非法转换；
- 没有 verified Run 不能 resolved；
- resolved 后 exact match 触发 regressed；
- semantic candidate 不自动确认；
- late evidence/release window；
- Monitor cursor、重试、重复通知和 webhook 签名；
- ignored reason/expiry；
- 删除 Trace 后 membership tombstone；
- Gate 与 Pattern link 不改写 Evaluation。

## 12. 验收标准

- [x] Signal 与 Pattern 明确分离，candidate 不冒充 confirmed；
- [x] Pattern 定义和状态历史可审计；
- [x] resolved 必须引用 approved Case、SuiteVersion 和 verified Run；
- [x] 复发能链接到原 Pattern、原修复 release 和新生产证据；
- [x] 语义聚类关闭时，确定性/人工 cohort 仍完整可用；
- [x] 通知内容不含敏感正文，失败不改变业务状态；
- [x] Pattern 的 Gate/Run/Case/Suite 链接和 definition hash 可重放并引用具体 evidence；
- [x] 没有任何自动编码/PR/发布动作绕过人工批准。

## 13. 灰度与回滚

首版只启用 Signal inbox 和人工 Pattern，Monitor 以 shadow 模式计算匹配但不通知；随后开启 Webhook，
最后才允许已确认 Critical Pattern 自动进入 regressed。回滚时停用 detector/monitor 和通知，不删除
Signal、Pattern、Membership 或状态事件；错误定义通过新 definition version 和人工状态修正。
