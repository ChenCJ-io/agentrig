import type { Run, RunCell, RunPreview, Target } from "~/api/v1";
import { formatChinaDateTime } from "~/utils/date-time";
import type {
  EvaluationCellVM,
  EvidenceEventVM,
  IdentityVM,
  PlanPreviewVM,
  RunListItemVM,
  UiStatus,
} from "~/view-models/evaluation";

export function shortId(value: string): string {
  return value.length > 18 ? `${value.slice(0, 9)}…${value.slice(-6)}` : value;
}

export function identity(id: string, label = id, version?: string | null): IdentityVM {
  return { id, label: label || id, shortId: shortId(id), version };
}

export function toUiStatus(value: string | null | undefined): UiStatus {
  if (value === "pass" || value === "passed" || value === "completed") return "passed";
  if (value === "fail" || value === "failed" || value === "evaluation_error") return "failed";
  if (value === "inconclusive" || value === "skipped") return "partial";
  if (value === "draft") return "draft";
  if (value === "pending" || value === "awaiting_verdict") return "pending";
  if (value === "queued") return "queued";
  if (value === "running") return "running";
  if (value === "cancelled") return "cancelled";
  if (value === "interrupted") return "interrupted";
  return "unknown";
}

export function toPlanPreview(preview: RunPreview, target?: Target): PlanPreviewVM {
  const targetSnapshot = preview.target_snapshots[0] ?? {};
  const targetId = String(targetSnapshot.id ?? target?.id ?? "unknown-target");
  return {
    status: "draft",
    target: identity(targetId, target?.name ?? targetId, String(targetSnapshot.version ?? "") || null),
    cases: preview.resolved_case_ids.map((caseId) => identity(caseId)),
    cellCount: preview.cell_count,
    attemptCount: preview.attempt_count,
    skippedCount: preview.skipped_items.length,
    rejected: preview.skipped_items.map((item, index) => ({
      id: String(item.case_id ?? `skipped-${index + 1}`),
      reason: String(item.message ?? item.code ?? "不可执行"),
    })),
    providers: preview.providers,
    evaluators: preview.primary_evaluators,
    manifestHash: preview.manifest_hash,
    confirmationRequired: true,
  };
}

export function toRunListItem(run: Run, target?: Target): RunListItemVM {
  const targetSnapshot = run.target_snapshots[0] ?? {};
  const targetId = String(targetSnapshot.id ?? target?.id ?? "unknown-target");
  const total = run.attempt_count || run.total_count;
  const completed = run.finished_attempt_count || (
    run.completed_count + run.failed_count + run.skipped_count + run.cancelled_count
  );
  const rawStatus = run.status;
  const status = rawStatus === "completed"
    ? run.failed_count > 0 || run.skipped_count > 0 ? "partial" : "passed"
    : toUiStatus(rawStatus);
  return {
    id: run.id,
    shortId: shortId(run.id),
    status,
    rawStatus,
    target: identity(targetId, target?.name ?? targetId, String(targetSnapshot.version ?? "") || null),
    progress: {
      completed,
      total,
      percent: total > 0 ? Math.min(100, Math.round((completed / total) * 100)) : 0,
    },
    cellCount: run.cell_count,
    attemptCount: run.attempt_count,
    failedCount: run.failed_count,
    createdAt: formatChinaDateTime(run.created_at),
    finishedAt: formatChinaDateTime(run.finished_at),
    recoveryOfRunId: run.recovery_of_run_id,
    manifestHash: run.manifest_hash,
  };
}

export function toEvaluationCell(cell: RunCell): EvaluationCellVM {
  return {
    id: cell.cell_id,
    shortId: shortId(cell.cell_id),
    caseIdentity: identity(cell.case_id),
    targetIdentity: identity(cell.target_id, cell.target_id, cell.version),
    status: toUiStatus(cell.status),
    verdict: toUiStatus(cell.evaluation_state),
    failureClass: cell.failure_class,
    attemptCount: cell.attempt_count,
    finishedAttemptCount: cell.finished_attempt_count,
    attempts: cell.attempts.map((attempt) => ({
      id: attempt.attempt_id || attempt.id,
      repeatIndex: attempt.attempt_index || attempt.repeat_index,
      status: toUiStatus(attempt.status),
      verdict: toUiStatus(attempt.evaluation_state),
      failureClass: attempt.failure_class,
    })),
    timeline: (cell.timeline ?? []).map(toEvidenceEvent),
  };
}

function toEvidenceEvent(item: NonNullable<RunCell["timeline"]>[number]): EvidenceEventVM {
  return {
    id: item.id,
    occurredAt: formatChinaDateTime(item.occurred_at),
    kind: timelineKind(item.category, item.source_type),
    actor: item.actor,
    title: item.title,
    summary: item.summary,
    status: item.status,
    payload: item.payload,
    evidenceRefs: item.evidence_refs,
    attemptId: item.attempt_id,
    attemptIndex: item.attempt_index,
  };
}

function timelineKind(
  category: string,
  sourceType: "event" | "evaluation",
): EvidenceEventVM["kind"] {
  if (sourceType === "evaluation") return "evaluation";
  if (category === "user_message") return "input";
  if (category === "assistant_text" || category === "assistant_message") return "assistant";
  if (category === "tool_call") return "tool_call";
  if (category === "tool_result" || category === "provider_attempt") return "tool_result";
  if (category === "error") return "error";
  return "system";
}
