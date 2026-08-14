export type UiStatus =
  | "draft"
  | "pending"
  | "queued"
  | "running"
  | "passed"
  | "failed"
  | "partial"
  | "cancelled"
  | "interrupted"
  | "unknown";

export interface IdentityVM {
  id: string;
  label: string;
  shortId: string;
  version?: string | null;
}

export interface MetricVM {
  label: string;
  value: string | number;
  help?: string;
  tone?: "neutral" | "accent" | "success" | "warning" | "danger";
}

export interface PlanPreviewVM {
  status: UiStatus;
  target: IdentityVM;
  cases: IdentityVM[];
  cellCount: number;
  attemptCount: number;
  skippedCount: number;
  rejected: Array<{ id: string; reason: string }>;
  providers: string[];
  evaluators: string[];
  manifestHash: string;
  confirmationRequired: boolean;
}

export interface RunListItemVM {
  id: string;
  shortId: string;
  status: UiStatus;
  rawStatus: string;
  target: IdentityVM;
  progress: { completed: number; total: number; percent: number };
  cellCount: number;
  attemptCount: number;
  failedCount: number;
  createdAt: string;
  finishedAt: string;
  recoveryOfRunId?: string | null;
  manifestHash?: string | null;
}

export interface EvidenceEventVM {
  id: string;
  occurredAt: string;
  kind: "input" | "assistant" | "tool_call" | "tool_result" | "evaluation" | "error" | "system";
  actor: string;
  title: string;
  summary?: string | null;
  status?: string | null;
  payload: unknown;
  evidenceRefs: string[];
  attemptId: string;
  attemptIndex: number;
}

export interface EvaluationAttemptVM {
  id: string;
  repeatIndex: number;
  status: UiStatus;
  verdict: UiStatus;
  failureClass?: string | null;
}

export interface EvaluationCellVM {
  id: string;
  shortId: string;
  caseIdentity: IdentityVM;
  targetIdentity: IdentityVM;
  status: UiStatus;
  verdict: UiStatus;
  failureClass?: string | null;
  attemptCount: number;
  finishedAttemptCount: number;
  attempts: EvaluationAttemptVM[];
  timeline: EvidenceEventVM[];
}
