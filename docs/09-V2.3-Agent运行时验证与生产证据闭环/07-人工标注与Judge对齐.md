# 人工标注与 Judge 对齐方案

> 专题 ID：AR-V23-WP07
>
> 状态：Implemented（本地确定性验收完成）
>
> 优先级：P2
>
> 目标里程碑：V2.4

## 0. 实施状态（2026-08-11）

- ReviewItem 统一接收 CaseRun、ProductionTrace 和 ProductionSpan，只保存 subject snapshot/ref，不复制
  正文；
- Annotation 为 append-only revision，supersede 不删除旧记录；双审、disputed 和 adjudication 保留
  明确状态；
- GoldLabel、EvaluatorVersion 与 AlignmentReport 均有 canonical content/source hash，cohort metrics 支持
  risk/Suite/Runtime/source 任意键分层；
- Judge 版本从 draft→alignment replay→独立 evaluator_admin 审批→active，作者不能单独批准自己的
  候选版本，历史 Evaluation 引用不改写；
- Review Queue、标注、金标、Evaluator/Alignment HTTP API 与 Governance Web 工作台已实现，并有权限/
  状态机/false-pass 回归测试。

## 1. 目标

建立自动评测与人工判断之间的版本化校准机制，回答：

- Judge 与审核者在什么类型的样本上经常不一致？
- 当前 Judge 版本是否比旧版本更接近人工金标？
- 某次 Gate 使用的究竟是哪一个 prompt/model/policy？
- Judge 改进后会不会修复一类判断，同时破坏另一类判断？
- 人工意见存在分歧时，系统如何表示不确定性？

本专题不改变当前 `pass = 要求满足` 的语义，也不把人工标注变成模型隐藏推理训练集。

## 2. 核心原则

1. 人工标注是独立事实，不覆盖原 Evaluation。
2. Evaluator/Judge 的 prompt、model、参数、tool/skill 和代码规则都以不可变版本保存。
3. 自动生成的 Judge 改进只能成为 draft，必须回放、对齐和审批后激活。
4. `pass/fail/inconclusive/evaluation_error` 保持离散语义；数值分只作辅助维度。
5. 评估 Judge 时按风险域、Suite、Runtime 和样本来源分层，不能只看一个总准确率。
6. 人工分歧不强行多数表决为真值；可以进入 adjudication 或保持 disputed。

## 3. 数据模型

### 3.1 ReviewItem

统一指向可审核对象，不复制正文：

```text
id, project_id,
subject_kind: case_run | production_trace | production_span,
subject_id, subject_snapshot_hash,
queue, priority, assignment,
status: open | in_review | adjudication | resolved | dismissed,
created_reason, created_at, resolved_at
```

### 3.2 Annotation

```json
{
  "schema_version": "agentrig.annotation.v1",
  "id": "ann_xxx",
  "review_item_id": "review_xxx",
  "reviewer_id": "user_xxx",
  "label": "fail",
  "criteria": [],
  "evidence_refs": [],
  "rationale_summary": "...",
  "confidence": "high",
  "status": "submitted",
  "supersedes": null,
  "created_at": "..."
}
```

Annotation 追加式写入。修改通过新记录 `supersedes` 旧记录，不覆盖历史。rationale 是公开、简短的判断
依据，不要求 reviewer 提供思维过程。

### 3.3 GoldLabel

金标是由一条或多条 Annotation 经策略解析后的版本化事实：

```text
id, review_item_id, label,
source_annotation_ids, resolution_method,
adjudicator_id, status: resolved | disputed,
schema_version, content_hash, created_at
```

高风险安全 Case 可要求双人审核和 adjudicator；普通 Case 可使用单人审核。`disputed` 不进入阻断式
对齐分母。

### 3.4 EvaluatorVersion

```text
id, evaluator_kind: rule | evidence_judge | external,
name, semantic_version, status: draft | active | retired,
code_revision, prompt_version/hash, model_id,
model_parameters_hash, tool/skill hashes,
output_schema_hash, created_by, approved_by, created_at
```

Rule 版本也要记录代码和配置 hash；不能只版本化 LLM Judge。

### 3.5 AlignmentRun/Report

AlignmentRun 选择固定 GoldLabel snapshot、EvaluatorVersion 和 SuiteVersion 后重放。Report 包含：

```text
coverage, agreement, confusion matrix,
precision/recall by label,
false_pass_rate, false_fail_rate,
inconclusive_rate, evaluation_error_rate,
results by suite/risk/runtime/source,
disagreements[], missing[], limitations[],
source_snapshot_hash
```

安全场景重点关注 false pass；低风险体验场景可关注 false fail 和 inconclusive。

## 4. Label 与评分语义

### 4.1 主标签

- `pass`：全部 blocking requirement 有证据满足；
- `fail`：至少一项 requirement 有证据不满足；
- `inconclusive`：证据不足、冲突或能力不可观察；
- `evaluation_error`：评估器执行/Schema/引用失败。

### 4.2 Criteria

Annotation 可对 rubric criteria 分项标注，格式沿用 Evaluation criteria 和 evidence refs。分项结果不能
通过平均值掩盖 blocking failure。

### 4.3 Confidence

`low/medium/high` 代表审核者对当前证据充分性的信心，不代表通过概率。低 confidence 可进入二审队列，
但不得被系统自动改成 inconclusive。

## 5. 工作流

```text
Run/Trace 被规则、用户或 Pattern 标记
  → 创建 ReviewItem
  → 分配 reviewer
  → 提交 Annotation
  → 可选第二审核
  → resolve/disputed GoldLabel
  → 选择 EvaluatorVersion 回放
  → AlignmentReport
  → draft evaluator proposal
  → regression replay + approval
  → activate new version
```

Judge 新版本激活只影响新 EvaluationPlan/Run。历史 Evaluation 继续引用旧版本；如需重评，创建新的
AlignmentRun 或显式 re-evaluation，不覆盖历史主 Evaluation。

## 6. Review Queue

进入队列的来源：

- Judge 与 Rule 不一致；
- 自动 Evaluation 与已有 GoldLabel 不一致；
- Gate regression/inconclusive；
- 新生产 release 的抽样；
- Failure Pattern candidate；
- 用户手动标记。

优先级可由风险级别、release、用户影响和新颖性决定，但规则必须可解释。首版不使用 LLM 自动计算
业务影响。

## 7. Judge 改进治理

### 7.1 允许的自动辅助

- 汇总 disagreement；
- 提出 rubric/prompt draft；
- 生成候选 fixture 和对照样本；
- 在固定数据集上运行候选 Judge；
- 输出哪些 cohort 改善/退化。

### 7.2 禁止自动执行

- 原地修改 active prompt；
- 将 Judge 自己的输出作为金标；
- 删除不利样本或只挑选改善 cohort；
- 无审批激活新版本；
- 用总体准确率覆盖 Critical false pass 退化。

### 7.3 激活门槛

默认要求：

- GoldLabel snapshot 固定；
- 关键安全 cohort 无新增 false pass；
- overall coverage 不下降；
- evaluation_error 不上升；
- 所有退化样本有人工解释；
- Prompt/model/price/usage 变化进入报告；
- 至少一名非作者审批。

## 8. API 与 Web

```text
POST /api/review-items
GET  /api/review-items
POST /api/review-items/{id}/annotations
POST /api/review-items/{id}:resolve
GET  /api/evaluators/versions
POST /api/evaluators/versions/{id}/alignment-runs
GET  /api/alignment-runs/{id}/report
POST /api/evaluators/versions/{id}:activate
```

Web 提供队列、并排证据、Annotation 表单、分歧处理、confusion matrix 和 cohort drill-down。Reviewer
看到的所有 evidence refs 必须链接回脱敏事实，不复制一份可能漂移的文本。

## 9. 权限与审计

- `reviewer` 可提交自己的 Annotation；
- `adjudicator` 可解析分歧；
- `evaluator_admin` 可审批激活；
- 作者不能单独审批自己创建的高风险 Judge 版本；
- 所有 assignment、resolve、activate/retire 记录审计事件；
- reviewer identity 不发送给被测 Target 或 Judge；
- 导出时根据 Project policy 匿名化 reviewer。

## 10. 测试

- Annotation append/supersede 和证据归属；
- 双审/分歧/adjudication 状态机；
- GoldLabel snapshot/hash 稳定；
- confusion matrix、缺失和 disputed 分母；
- active evaluator 不可变；
- 候选 Judge 不能自动激活；
- Critical false pass 阻断；
- Project/reviewer 权限隔离；
- 历史 Evaluation 始终引用原 EvaluatorVersion。

## 11. 验收标准

- [x] CaseRun 和 ProductionTrace 均可进入同一审核队列但保持来源类型；
- [x] Annotation 追加式、可追溯且引用有效 evidence；
- [x] disputed 样本不会被伪装成金标；
- [x] 每个版本化 Judge Evaluation 可解析到完整 EvaluatorVersion；
- [x] AlignmentReport 可按风险/Suite/Runtime/source 分层；
- [x] Judge draft、回放、审批、激活状态机有权限测试；
- [x] active Judge 不会被后台任务静默修改；
- [x] 新版本退化时可以继续使用旧版本，无需改写历史数据。

## 12. 回滚

EvaluatorVersion 不删除。发现问题时把旧版本重新设为后续新 Run 的 active，并将问题版本标记 retired；
已经产生的 Evaluation 保持原引用。错误 GoldLabel 通过 superseding Annotation 和新 GoldLabel version
修正，历史 AlignmentReport 不覆盖。
