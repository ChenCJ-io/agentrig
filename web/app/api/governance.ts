import {
  getOne,
  getPage,
  postAction,
  type Page,
} from "./v1";

export interface Project {
  id: string;
  slug: string;
  name: string;
  status: "active" | "archived";
  default_environment: string;
}

export interface IngestSource {
  id: string;
  name: string;
  allowed_service_names: string[];
  retention_days: number;
  enabled: boolean;
  last_seen_at: string | null;
}

export interface ProductionTrace {
  id: string;
  source_id: string;
  session_id: string | null;
  external_trace_id: string;
  name: string;
  started_at: string;
  ended_at: string | null;
  status: string;
  service_name: string;
  environment: string | null;
  release: Record<string, unknown> | null;
  attributes: Record<string, unknown>;
  token_usage: Record<string, unknown>;
  ingest_status: string;
  content_hash: string;
  redaction_policy_hash: string;
}

export interface ProductionSpan {
  id: string;
  external_span_id: string;
  parent_external_span_id: string | null;
  span_kind: string;
  name: string;
  started_at: string;
  ended_at: string | null;
  status: string;
  agent_path: string[];
  model_call: Record<string, unknown> | null;
  tool_call: Record<string, unknown> | null;
  tool_result: Record<string, unknown> | null;
  permission: Record<string, unknown> | null;
  memory_operation: Record<string, unknown> | null;
  artifact_refs: Array<Record<string, unknown>>;
  attributes: Record<string, unknown>;
  events: Array<Record<string, unknown>>;
  content_hash: string;
  received_at: string;
}

export interface ProductionTraceDetail {
  trace: ProductionTrace;
  spans: ProductionSpan[];
  missing_parent_span_ids: string[];
}

export interface TraceCaseDraftPreview {
  source_trace_id: string;
  selected_span_ids: string[];
  generalized_user_message: string;
  expected_behavior: string;
  removed_fields: string[];
  mapping_version: string;
  mapping_hash: string;
}

export interface TraceCaseDraftResult {
  preview: TraceCaseDraftPreview;
  case_id: string;
  lineage: {
    id: string;
    status: "draft" | "approved" | "rejected";
    mapping_hash: string;
  };
}

export interface ReviewItem {
  id: string;
  subject_kind: "case_run" | "production_trace" | "production_span";
  subject_id: string;
  subject_snapshot_hash: string;
  queue: string;
  priority: number;
  assignment: string | null;
  cohort: string | null;
  status: "open" | "in_review" | "adjudication" | "resolved" | "dismissed";
  required_reviews: number;
  created_reason: string;
  created_by: string;
  created_at: string;
  resolved_at: string | null;
}

export interface Annotation {
  id: string;
  revision: number;
  reviewer_id: string;
  label: "pass" | "fail" | "inconclusive" | "evaluation_error";
  evidence_refs: string[];
  rationale_summary: string;
  confidence: "low" | "medium" | "high";
  supersedes: string | null;
  created_at: string;
}

export interface FailureSignal {
  id: string;
  signal_type: string;
  category: string;
  severity: "low" | "medium" | "high" | "critical";
  summary: string;
  environment: string | null;
  signature: string;
  occurred_at: string;
}

export interface PatternMembership {
  signal_id: string;
  match_kind: string;
  explanation: string;
  status: "candidate" | "confirmed" | "rejected";
  reviewed_by: string | null;
}

export interface FailurePattern {
  id: string;
  title: string;
  description: string;
  category: string;
  severity: "low" | "medium" | "high" | "critical";
  priority: number;
  status: "candidate" | "new" | "escalating" | "ongoing" | "resolved" | "regressed" | "ignored";
  signature: string;
  definition_version: number;
  owner: string | null;
  representative_signal_ids: string[];
  linked_case_ids: string[];
  linked_suite_versions: string[];
  linked_release_gate_ids: string[];
  first_seen_at: string;
  last_seen_at: string;
  resolved_at: string | null;
  memberships: PatternMembership[];
}

export interface PatternEvent {
  id: string;
  event_type: string;
  actor: string;
  details: Record<string, unknown>;
  created_at: string;
}

export interface FailureMonitor {
  id: string;
  status: "active" | "paused";
  environment: string | null;
  shadow_mode: boolean;
  recurrence_count: number;
  last_seen_at: string | null;
  last_error: string | null;
}

export interface ExecutionJob {
  id: string;
  run_id: string;
  case_run_id: string;
  status: "queued" | "leased" | "running" | "completed" | "failed" | "cancelled" | "dead";
  priority: number;
  available_at: string;
  lease_owner: string | null;
  lease_expires_at: string | null;
  attempt: number;
  max_attempts: number;
  external_side_effect: boolean;
  cancel_requested_at: string | null;
  last_error_code: string | null;
  created_at: string;
  updated_at: string;
}

export interface ExecutionAttempt {
  id: string;
  attempt: number;
  lease_owner: string;
  status: "leased" | "running" | "completed" | "failed" | "cancelled" | "interrupted";
  started_at: string;
  finished_at: string | null;
  error_code: string | null;
  external_side_effect: boolean;
}

export function projectApiPath(projectId: string, suffix: string): string {
  return `/api/projects/${encodeURIComponent(projectId)}${suffix}`;
}

export function listProjects(): Promise<Page<Project>> {
  return getPage<Project>("/api/projects?limit=100");
}

export function listProductionTraces(projectId: string): Promise<Page<ProductionTrace>> {
  return getPage<ProductionTrace>(projectApiPath(projectId, "/production/traces?limit=100"));
}

export function getProductionTrace(projectId: string, traceId: string): Promise<ProductionTraceDetail> {
  return getOne<ProductionTraceDetail>(projectApiPath(projectId, `/production/traces/${encodeURIComponent(traceId)}`));
}

export function listIngestSources(projectId: string): Promise<IngestSource[]> {
  return getOne<IngestSource[]>(projectApiPath(projectId, "/production/ingest-sources"));
}

export function listReviewItems(projectId: string): Promise<Page<ReviewItem>> {
  return getPage<ReviewItem>(projectApiPath(projectId, "/review-items?limit=100"));
}

export function listAnnotations(projectId: string, reviewId: string): Promise<Annotation[]> {
  return getOne<Annotation[]>(projectApiPath(projectId, `/review-items/${encodeURIComponent(reviewId)}/annotations`));
}

export function listFailureSignals(projectId: string): Promise<Page<FailureSignal>> {
  return getPage<FailureSignal>(projectApiPath(projectId, "/failure-signals?limit=100"));
}

export function listFailurePatterns(projectId: string): Promise<Page<FailurePattern>> {
  return getPage<FailurePattern>(projectApiPath(projectId, "/failure-patterns?limit=100"));
}

export function listPatternTimeline(projectId: string, patternId: string): Promise<PatternEvent[]> {
  return getOne<PatternEvent[]>(projectApiPath(projectId, `/failure-patterns/${encodeURIComponent(patternId)}/timeline`));
}

export function listPatternMonitors(projectId: string, patternId: string): Promise<FailureMonitor[]> {
  return getOne<FailureMonitor[]>(projectApiPath(projectId, `/failure-patterns/${encodeURIComponent(patternId)}/monitors`));
}

export function listExecutionJobs(projectId: string): Promise<Page<ExecutionJob>> {
  return getPage<ExecutionJob>(projectApiPath(projectId, "/execution-jobs?limit=100"));
}

export function listExecutionAttempts(projectId: string, jobId: string): Promise<ExecutionAttempt[]> {
  return getOne<ExecutionAttempt[]>(projectApiPath(projectId, `/execution-jobs/${encodeURIComponent(jobId)}/attempts`));
}

export function projectAction<T>(projectId: string, suffix: string, value?: unknown): Promise<T> {
  return postAction<T>(projectApiPath(projectId, suffix), value);
}
