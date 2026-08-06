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

export interface Run {
  id: string;
  status: "queued" | "running" | "completed" | "failed" | "cancelled" | "interrupted";
  resolved_case_ids: string[];
  target_snapshots: Array<{ id?: string; version?: string | null; [key: string]: unknown }>;
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
  status: string;
  primary_evaluator: string;
  evaluation_state: string;
  error_code: string | null;
  error_message: string | null;
  summary: Record<string, unknown>;
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

export function getRunReport(runId: string): Promise<RunReport> {
  return apiRequest<RunReport>(`/api/runs/${encodeURIComponent(runId)}/report`);
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
