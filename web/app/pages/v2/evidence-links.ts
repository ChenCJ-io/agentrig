import type { DecisionRecord, EvidenceRef } from "~/api/v2";

const TARGET_RESOURCE_KINDS = new Set([
  "case_run",
  "evaluation",
  "execution_profile",
  "run",
  "run_event",
  "test_case",
  "tool_sample",
]);

export function evidenceSourcePath(
  evidence: EvidenceRef,
  decision: DecisionRecord,
  pathname: string,
): string {
  const targetId = targetFromPath(pathname) ?? targetFromDecision(decision);
  const targetBase = targetId ? `/targets/${encodeURIComponent(targetId)}` : null;
  const resourceId = encodeURIComponent(evidence.resource_id);

  switch (evidence.kind) {
    case "assistant_event":
      return `${pathname}#assistant-event-${resourceId}`;
    case "evaluation_plan":
      return `${pathname}#evaluation-plan`;
    case "target":
    case "target_check":
      return `/targets/${resourceId}/overview`;
    case "test_case":
      return targetBase
        ? `${targetBase}/evaluation/test-cases?case_id=${resourceId}`
        : auditFallback(evidence);
    case "execution_profile":
      return targetBase
        ? `${targetBase}/assets/profiles?profile_id=${resourceId}`
        : auditFallback(evidence);
    case "tool_sample":
      return targetBase
        ? `${targetBase}/assets/tool-results?sample_id=${resourceId}`
        : auditFallback(evidence);
    case "run":
      return targetBase
        ? `${targetBase}/evaluation/runs/${resourceId}`
        : auditFallback(evidence);
    case "case_run":
    case "run_event":
    case "evaluation": {
      const run = decision.evidence_refs.find((item) => item.kind === "run");
      return targetBase && run
        ? `${targetBase}/evaluation/runs/${encodeURIComponent(run.resource_id)}?evidence_kind=${encodeURIComponent(evidence.kind)}&evidence_id=${resourceId}#evidence-workbench`
        : targetBase
          ? `${targetBase}/observability?evidence_kind=${encodeURIComponent(evidence.kind)}&evidence_id=${resourceId}`
          : auditFallback(evidence);
    }
    case "agent_invocation":
      return `/evaluator-teams?invocation_id=${resourceId}`;
    case "runtime_health":
      return "/evaluator-teams";
    default:
      return auditFallback(evidence);
  }
}

function targetFromPath(pathname: string): string | null {
  const matched = pathname.match(/^\/targets\/([^/]+)/);
  return matched?.[1] ? decodeURIComponent(matched[1]) : null;
}

function targetFromDecision(decision: DecisionRecord): string | null {
  const target = decision.evidence_refs.find((item) => item.kind === "target");
  if (target) return target.resource_id;
  const selectedTarget = decision.selected_action.parameters.target_id;
  return typeof selectedTarget === "string" && selectedTarget ? selectedTarget : null;
}

function auditFallback(evidence: EvidenceRef): string {
  const params = new URLSearchParams({
    resource_kind: evidence.kind,
    resource_id: evidence.resource_id,
  });
  return `/audit?${params.toString()}`;
}

export function evidenceNeedsTarget(kind: string): boolean {
  return TARGET_RESOURCE_KINDS.has(kind);
}
