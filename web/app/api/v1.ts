import { apiDownload, apiRequest, jsonBody, type ApiFile } from "./client";

export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export interface TestCase {
  id: string;
  name: string;
  description: string;
  tags: string[];
  supported_versions: string[];
  primary_evaluator: string;
  review_status: "draft" | "approved" | "rejected";
  turns: Array<Record<string, unknown>>;
  created_at: string;
  updated_at: string;
  [key: string]: unknown;
}

export interface Target {
  id: string;
  name: string;
  driver_type: string;
  endpoint: string | null;
  versions: Array<{ version: string }>;
  created_at: string;
  updated_at: string;
  [key: string]: unknown;
}

export interface TargetCheck {
  reachable: boolean;
  driver_type: string;
  version: string | null;
  endpoint: string | null;
  capabilities: string[];
  message: string;
}

export interface ExecutionProfile {
  id: string;
  name: string;
  description: string;
  config: {
    tool_mode: string;
    provider_chain: Array<{ name: string }>;
    primary_evaluator: string | null;
    concurrency: number;
    [key: string]: unknown;
  };
  created_at: string;
  updated_at: string;
  [key: string]: unknown;
}

export interface Sample {
  id: string;
  name: string;
  tool_name: string | null;
  sample_kind: "single" | "sequence";
  status: "draft" | "approved" | "disabled";
  source_type: string;
  supported_versions: string[];
  created_at: string;
  updated_at: string;
  [key: string]: unknown;
}

export type FailureClass =
  | "behavior_regression"
  | "target_unreachable"
  | "tool_result_unavailable"
  | "contract_incompatible"
  | "timeout"
  | "evaluation_error"
  | "policy_denied"
  | "cancelled"
  | "interrupted"
  | "internal_error"
  | "unknown";

export interface RunManifest {
  manifest_schema_version: "agentrig.run-manifest.v1";
  canonical_serialization_version: "canonical-json.v1";
  selection: Record<string, unknown>;
  cells: Array<{
    cell_key: string;
    case_id: string;
    target_id: string;
    target_role: "baseline" | "candidate";
    version: string | null;
    disposition: "run" | "skip";
    code: string | null;
    message: string | null;
    attempts: Array<{ attempt_index: number; repeat_index: number }>;
  }>;
  repeat_count: number;
  cell_count: number;
  attempt_count: number;
  skipped_cell_count: number;
  skipped_attempt_count: number;
  [key: string]: unknown;
}

export interface Run {
  id: string;
  status: "queued" | "running" | "completed" | "failed" | "cancelled" | "interrupted";
  resolved_case_ids: string[];
  target_snapshots: Array<{ id?: string; version?: string | null; [key: string]: unknown }>;
  manifest_schema_version: string | null;
  manifest_hash: string | null;
  manifest: RunManifest | null;
  recovery_of_run_id: string | null;
  recovery_reason: string | null;
  cell_count: number;
  attempt_count: number;
  finished_attempt_count: number;
  total_count: number;
  completed_count: number;
  failed_count: number;
  skipped_count: number;
  cancelled_count: number;
  created_at: string;
  finished_at: string | null;
  [key: string]: unknown;
}

export interface CaseRun {
  id: string;
  run_id: string;
  case_id: string;
  version: string | null;
  repeat_index: number;
  comparison_pair_id: string | null;
  comparison_role: string | null;
  cell_key: string;
  attempt_id: string;
  attempt_index: number;
  status: string;
  primary_evaluator: string;
  evaluation_state: string;
  error_code: string | null;
  error_message: string | null;
  failure_class: FailureClass | null;
  recovery_of_case_run_id: string | null;
  summary: Record<string, unknown>;
  target_snapshot?: Record<string, unknown>;
  profile_snapshot?: Record<string, unknown>;
  capability_snapshot?: {
    snapshot_id: string;
    collection_status: "complete" | "partial" | "unavailable" | "invalid" | "legacy_unavailable";
    snapshot_hash: string;
    runtime: Record<string, unknown>;
    permissions?: Record<string, unknown>;
    features: Record<string, { status: string; value: unknown; evidence_refs: string[] }>;
    missing_fields: string[];
    limitations: string[];
    partition_hashes: Record<string, string>;
  } | null;
  events?: Array<{
    id: string;
    seq: number;
    event_type: string;
    payload: Record<string, unknown>;
    created_at: string;
  }>;
  evaluations?: Array<Record<string, unknown>>;
  [key: string]: unknown;
}

export interface RunCell {
  cell_id: string;
  cell_key: string;
  run_id: string;
  case_id: string;
  target_id: string;
  target_role: "baseline" | "candidate";
  version: string | null;
  status: string;
  evaluation_state: string;
  failure_class: FailureClass | null;
  attempt_count: number;
  finished_attempt_count: number;
  attempts: CaseRun[];
  attempt_details?: CaseRun[];
  timeline?: Array<{
    id: string;
    cell_id: string;
    attempt_id: string;
    case_run_id: string;
    attempt_index: number;
    source_type: "event" | "evaluation";
    source_id: string;
    category: string;
    actor: string;
    status: string | null;
    title: string;
    summary: string | null;
    evidence_refs: string[];
    payload: Record<string, unknown>;
    occurred_at: string;
  }>;
}

export interface RunPreview {
  resolved_case_ids: string[];
  planned_case_runs: number;
  skipped_items: Array<Record<string, unknown>>;
  profile_snapshot: Record<string, unknown>;
  target_snapshots: Array<Record<string, unknown>>;
  primary_evaluators: string[];
  providers: string[];
  manifest_schema_version: string;
  manifest_hash: string;
  manifest: RunManifest;
  cell_count: number;
  attempt_count: number;
}

export interface RunSubmitResult {
  run_id: string;
  status: Run["status"];
  resolved_case_ids: string[];
  planned_case_runs: number;
  manifest_hash: string | null;
  cell_count: number;
  attempt_count: number;
  skipped_items: Array<Record<string, unknown>>;
  recovery_of_run_id?: string;
  recovery_reason?: string;
  selected_cell_ids?: string[];
}

export interface RunProgressSummary {
  schema_version: "agentrig.batch-run-summary.v1";
  run_id: string;
  status: Run["status"];
  terminal: boolean;
  manifest_hash: string | null;
  recovery_of_run_id: string | null;
  cell_count: number;
  attempt_count: number;
  finished_attempt_count: number;
  cells_by_status: Record<string, number>;
  attempts_by_status: Record<string, number>;
  evaluation_outcomes: Record<string, number>;
  failure_classes: Record<string, number>;
}

export interface RunReport {
  schema_version: "agentrig.run-report.v1";
  generated_at: string;
  run: {
    id: string;
    status: Run["status"];
    resolved_case_ids: string[];
    total_count: number;
    completed_count: number;
    failed_count: number;
    skipped_count: number;
    cancelled_count: number;
    created_at: string;
    finished_at: string | null;
    error_code: string | null;
    error_message: string | null;
  };
  targets: Array<{ id: string; name: string; version: string | null }>;
  outcomes: {
    total: number;
    evaluated: number;
    pass_count: number;
    fail_count: number;
    inconclusive_count: number;
    awaiting_verdict_count: number;
    evaluation_error_count: number;
  };
  failures: Array<{
    id: string;
    case_id: string;
    version: string | null;
    repeat_index: number;
    status: string;
    evaluation_state: string;
    error_code: string | null;
    error_message: string | null;
    evaluation_summary: string | null;
  }>;
  recovery: RecoveryProvenance | null;
}

export interface RecoveryProvenance {
  source_run_id: string;
  recovery_run_ids: string[];
  applied_recovery_run_ids: string[];
  effective_attempt_count: number;
  replaced_attempt_count: number;
  superseded_attempt_ids: string[];
  effective_attempt_ids: string[];
}

export interface QualityReport {
  schema_version: "agentrig.quality-report.v1";
  generated_at: string;
  run_id: string;
  run_status: Run["status"];
  source_snapshot_hash: string;
  scope: { resolved_case_ids: string[]; target_ids: string[]; case_run_count: number };
  outcomes: {
    total: number;
    pass_count: number;
    fail_count: number;
    inconclusive_count: number;
    awaiting_verdict_count: number;
    evaluation_error_count: number;
    skipped_count: number;
    cancelled_count: number;
    interrupted_count: number;
    execution_failed_count: number;
  };
  latency: {
    run_duration_ms: number | null;
    case_run: { count: number; p50_ms: number | null; p95_ms: number | null };
    driver_request: { count: number; p50_ms: number | null; p95_ms: number | null };
    ttft: { count: number; p50_ms: number | null; p95_ms: number | null };
  };
  usage: {
    usage_event_count: number;
    input_tokens: number | null;
    output_tokens: number | null;
    total_tokens: number | null;
    cached_input_tokens: number | null;
    reasoning_tokens: number | null;
    estimated_cost: string | null;
    currency: string | null;
    cost_kind: string | null;
    pricing_source: string | null;
    pricing_effective_at: string | null;
    pricing_snapshot_hash: string | null;
    missing_fields: string[];
  };
  reliability: {
    driver_request_count: number;
    provider_attempt_count: number;
    fallback_attempt_count: number;
    provider_error_count: number;
    recoverable_group_count: number;
    recovered_group_count: number;
    recovery_success_rate: number | null;
    timeout_count: number;
    error_codes: Record<string, number>;
  };
  collaboration: {
    decisions: {
      total: number;
      terminal: number;
      succeeded: number;
      failed: number;
      provenance_candidates: number;
      provenance_linked: number;
      provenance_link_rate: number | null;
    };
    invocations: {
      total: number;
      completed: number;
      failed: number;
      timed_out: number;
      cancelled: number;
      duration: { count: number; p50_ms: number | null; p95_ms: number | null };
    };
  };
  evidence_quality: {
    evaluation_count: number;
    evaluation_error_count: number;
    evaluations_without_references: number;
    reference_count: number;
    valid_reference_count: number;
    reference_validity_rate: number | null;
    missing_reference_count: number;
    foreign_reference_count: number;
    redaction_status: "applied";
  };
  recovery: RecoveryProvenance | null;
  limitations: string[];
}

export interface ComparisonSide {
  case_run_id: string;
  target_id: string;
  version: string | null;
  status: string;
  outcome: string;
  evidence_refs: string[];
  duration_ms: number | null;
  total_tokens: number | null;
}

export interface ComparisonReport {
  schema_version: "agentrig.comparison-report.v1";
  generated_at: string;
  run_id: string;
  source_snapshot_hash: string;
  summary: {
    total_pairs: number;
    comparable_pairs: number;
    regression_count: number;
    fix_count: number;
    unchanged_pass_count: number;
    unchanged_fail_count: number;
    changed_inconclusive_count: number;
    infrastructure_error_count: number;
    incomplete_pair_count: number;
    incomparable_environment_count: number;
  };
  metrics: {
    duration_sample_count: number;
    duration_regression_ratio: number | null;
    token_sample_count: number;
    token_regression_ratio: number | null;
  };
  pairs: Array<{
    comparison_pair_id: string;
    case_id: string;
    repeat_index: number;
    classification: string;
    baseline: ComparisonSide | null;
    candidate: ComparisonSide | null;
    capability_comparison: string;
    limitations: string[];
  }>;
  recovery: RecoveryProvenance | null;
  limitations: string[];
}

export interface ReleasePolicy {
  schema_version: "agentrig.release-policy.v1";
  name: string;
  policy_version: string;
  blocking: Record<string, number>;
  warnings: Record<string, number>;
  minimum_samples: Record<string, number>;
}

export interface ReleaseGateResult {
  schema_version: "agentrig.release-gate.v1";
  generated_at: string;
  run_id: string;
  verdict: "pass" | "warn" | "fail" | "inconclusive";
  policy_name: string;
  policy_version: string;
  policy_hash: string;
  source_snapshot_hash: string;
  result_hash: string;
  checks: Array<{
    name: string;
    severity: "blocking" | "warning";
    operator: "lte" | "gte";
    actual: number | null;
    threshold: number;
    outcome: "pass" | "fail" | "inconclusive" | "not_evaluated";
    message: string;
    evidence_refs: string[];
  }>;
}

export interface TargetExportPreview {
  schema_version: "agentrig.export-preview.v1";
  target_id: string;
  counts: {
    runs: number;
    test_cases: number;
    samples: number;
    total_records: number;
  };
  max_export_records: number;
  within_limit: boolean;
}

export type TargetExportFormat = "json" | "markdown" | "html";

export async function getPage<T>(path: string): Promise<Page<T>> {
  return apiRequest<Page<T>>(path);
}

export async function getOne<T>(path: string): Promise<T> {
  return apiRequest<T>(path);
}

export async function createOne<T>(path: string, value: unknown): Promise<T> {
  return apiRequest<T>(path, {
    method: "POST",
    ...jsonBody(value),
  });
}

export async function patchOne<T>(
  path: string,
  value: unknown,
): Promise<T> {
  return apiRequest<T>(path, {
    method: "PATCH",
    ...jsonBody(value),
  });
}

export async function deleteOne(path: string): Promise<void> {
  await apiRequest<unknown>(path, { method: "DELETE" });
}

export async function postAction<T>(
  path: string,
  value?: unknown,
): Promise<T> {
  return apiRequest<T>(path, {
    method: "POST",
    ...(value === undefined ? {} : jsonBody(value)),
  });
}

export async function putOne<T>(path: string, value: unknown): Promise<T> {
  return apiRequest<T>(path, {
    method: "PUT",
    ...jsonBody(value),
  });
}

export function previewRunCases(value: unknown): Promise<RunPreview> {
  return apiRequest<RunPreview>("/api/runs/preview", {
    method: "POST",
    ...jsonBody(value),
  });
}

export function submitRunCases(value: unknown): Promise<RunSubmitResult> {
  return apiRequest<RunSubmitResult>("/api/runs", {
    method: "POST",
    ...jsonBody(value),
  });
}

export function listRunCells(runId: string): Promise<Page<RunCell>> {
  return apiRequest<Page<RunCell>>(
    `/api/runs/${encodeURIComponent(runId)}/cells?limit=200`,
  );
}

export function getRunSummary(runId: string): Promise<RunProgressSummary> {
  return apiRequest<RunProgressSummary>(
    `/api/runs/${encodeURIComponent(runId)}/summary`,
  );
}

export function getRunCell(runId: string, cellId: string): Promise<RunCell> {
  return apiRequest<RunCell>(
    `/api/runs/${encodeURIComponent(runId)}/cells/${encodeURIComponent(cellId)}`,
  );
}

export function retryRunCells(
  runId: string,
  value: { cell_ids: string[]; reason: string; override_behavior_fail?: boolean },
): Promise<RunSubmitResult> {
  return apiRequest<RunSubmitResult>(
    `/api/runs/${encodeURIComponent(runId)}/retry-cells`,
    { method: "POST", ...jsonBody(value) },
  );
}

export function cancelRun(runId: string): Promise<Run> {
  return apiRequest<Run>(
    `/api/runs/${encodeURIComponent(runId)}/cancel`,
    { method: "POST" },
  );
}

export function getRunReport(runId: string): Promise<RunReport> {
  return apiRequest<RunReport>(`/api/runs/${encodeURIComponent(runId)}/report`);
}

export function getQualityReport(runId: string): Promise<QualityReport> {
  return apiRequest<QualityReport>(
    `/api/runs/${encodeURIComponent(runId)}/quality-report`,
  );
}

export function getComparisonReport(runId: string): Promise<ComparisonReport> {
  return apiRequest<ComparisonReport>(
    `/api/runs/${encodeURIComponent(runId)}/comparison-report`,
  );
}

export function getDefaultReleasePolicy(): Promise<ReleasePolicy> {
  return apiRequest<ReleasePolicy>("/api/release-policies/default");
}

export function evaluateReleaseGate(
  runId: string,
  policy: ReleasePolicy,
): Promise<ReleaseGateResult> {
  return apiRequest<ReleaseGateResult>(
    `/api/runs/${encodeURIComponent(runId)}/release-gate:evaluate`,
    { method: "POST", ...jsonBody({ policy }) },
  );
}

export function downloadRunReport(runId: string): Promise<ApiFile> {
  return apiDownload(
    `/api/runs/${encodeURIComponent(runId)}/report?format=markdown`,
  );
}

export function getTargetExportPreview(
  targetId: string,
): Promise<TargetExportPreview> {
  return apiRequest<TargetExportPreview>(
    `/api/targets/${encodeURIComponent(targetId)}/export/preview`,
  );
}

export function downloadTargetExport(
  targetId: string,
  format: TargetExportFormat,
): Promise<ApiFile> {
  return apiDownload(
    `/api/targets/${encodeURIComponent(targetId)}/export?format=${encodeURIComponent(format)}`,
  );
}
