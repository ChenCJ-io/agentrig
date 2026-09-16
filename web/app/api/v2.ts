import {
  ApiError,
  apiRequest,
  authRequiredEvent,
  getAuthHeaders,
  jsonBody,
  resolveApiUrl,
} from "./client";
import type { Page, Sample, TestCase } from "./v1";

export interface AssistantSession {
  id: string;
  workspace_id: string;
  title: string;
  status: "active" | "archived";
  active_plan_id: string | null;
  last_event_seq: number;
  created_by: string;
  created_at: string;
  updated_at: string;
}

export interface AssistantSessionPage {
  items: AssistantSession[];
  total: number;
  limit: number;
  offset: number;
}

export interface AssistantEvent {
  id: string;
  session_id: string;
  seq: number;
  event_type: string;
  actor_type: "user" | "manager" | "system";
  actor_id: string;
  payload: Record<string, unknown>;
  turn_id: string | null;
  plan_id: string | null;
  run_id: string | null;
  case_run_id: string | null;
  delivery_status: "local" | "failed";
  last_error: string | null;
  created_at: string;
}

export interface AssistantEventPage {
  items: AssistantEvent[];
  total: number;
  limit: number;
  after_seq: number;
}

export interface AssistantTurn {
  id: string;
  session_id: string;
  trigger_event_id: string;
  status:
    "queued" | "dispatched" | "running" | "completed" | "failed" | "cancelled";
  started_at: string | null;
  finished_at: string | null;
  error_code: string | null;
  error_message: string | null;
  model_metadata: Record<string, unknown>;
  created_at: string;
}

export interface EvidenceRef {
  kind: string;
  resource_id: string;
  version: string | null;
  snapshot_hash: string | null;
  label: string | null;
}

export interface PlanConfirmation {
  required: boolean;
  reasons: string[];
  confirmation_event_id: string | null;
  confirmed_by: string | null;
  confirmed_at: string | null;
}

export interface EvaluationPlan {
  id: string;
  session_id: string;
  revision: number;
  status: "draft" | "confirmed" | "submitted" | "cancelled";
  goal: Record<string, unknown>;
  selection: Record<string, unknown>;
  reasoning_summary: Record<string, unknown>;
  preview: {
    resolved_case_ids?: string[];
    planned_case_runs?: number;
    skipped_items?: Array<Record<string, unknown>>;
    primary_evaluators?: string[];
    providers?: string[];
  };
  confirmation: PlanConfirmation;
  run_id: string | null;
  last_error: Record<string, unknown> | null;
  updated_at: string;
}

export interface AssistantProviderHealth {
  enabled: boolean;
  available: boolean;
  provider: "openai_compatible" | "none";
  message: string;
}

export interface MessageReceipt {
  event_id: string;
  turn_id: string;
  delivery_status: string;
}

export interface AssistantPlanAction {
  action_type: "confirm_plan" | "submit_plan" | "cancel_plan";
  plan_id: string;
  revision: number;
}

export interface TargetChatEvent {
  seq: number;
  event_type: string;
  payload: Record<string, unknown>;
  created_at: string;
}

export interface TargetChatSession {
  id: string;
  target_id: string;
  profile_id: string | null;
  version: string | null;
  status: string;
  events: TargetChatEvent[];
  created_at: string;
  updated_at: string;
}

export function listAssistantSessions(): Promise<AssistantSessionPage> {
  return apiRequest("/api/v2/assistant/sessions?limit=100");
}

export function createAssistantSession(
  title: string,
  workspaceId = "default",
): Promise<AssistantSession> {
  return apiRequest("/api/v2/assistant/sessions", {
    method: "POST",
    ...jsonBody({ title, workspace_id: workspaceId }),
  });
}

export function getAssistantSession(id: string): Promise<AssistantSession> {
  return apiRequest(`/api/v2/assistant/sessions/${encodeURIComponent(id)}`);
}

export function getAssistantTurn(id: string): Promise<AssistantTurn> {
  return apiRequest(`/api/v2/assistant/turns/${encodeURIComponent(id)}`);
}

export function listAssistantEvents(id: string): Promise<AssistantEventPage> {
  return apiRequest(
    `/api/v2/assistant/sessions/${encodeURIComponent(id)}/events?limit=500`,
  );
}

export async function streamAssistantEvents(
  id: string,
  afterSeq: number,
  onEvent: (event: AssistantEvent) => void,
  signal: AbortSignal,
): Promise<void> {
  const response = await fetch(
    resolveApiUrl(
      `/api/v2/assistant/sessions/${encodeURIComponent(id)}/stream?after_seq=${afterSeq}`,
    ),
    {
      credentials: "same-origin",
      headers: { Accept: "text/event-stream", ...getAuthHeaders() },
      signal,
    },
  );
  if (response.status === 401) {
    window.dispatchEvent(new Event(authRequiredEvent));
  }
  if (!response.ok) {
    throw new ApiError(`事件流连接失败 (${response.status})`, response.status);
  }
  if (!response.body) throw new Error("浏览器未提供可读事件流");

  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";
  while (!signal.aborted) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += value.replaceAll("\r\n", "\n");
    let boundary = buffer.indexOf("\n\n");
    while (boundary >= 0) {
      const block = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      const data = block
        .split("\n")
        .filter((line) => line.startsWith("data:"))
        .map((line) => line.slice(5).trimStart())
        .join("\n");
      if (data) onEvent(JSON.parse(data) as AssistantEvent);
      boundary = buffer.indexOf("\n\n");
    }
  }
}

export function sendAssistantMessage(
  sessionId: string,
  content: string,
  activePlanId: string | null,
  planAction: AssistantPlanAction | null = null,
): Promise<MessageReceipt> {
  return apiRequest(
    `/api/v2/assistant/sessions/${encodeURIComponent(sessionId)}/messages`,
    {
      method: "POST",
      ...jsonBody({
        client_message_id: crypto.randomUUID(),
        content,
        active_plan_id: activePlanId,
        plan_action: planAction,
      }),
    },
  );
}

export function getEvaluationPlan(id: string): Promise<EvaluationPlan> {
  return apiRequest(`/api/v2/evaluation-plans/${encodeURIComponent(id)}`);
}

export function updateEvaluationPlan(
  id: string,
  value: Pick<EvaluationPlan, "goal" | "selection" | "reasoning_summary">,
): Promise<EvaluationPlan> {
  return apiRequest(`/api/v2/evaluation-plans/${encodeURIComponent(id)}`, {
    method: "PATCH",
    ...jsonBody(value),
  });
}

export function confirmEvaluationPlan(
  id: string,
  confirmationEventId: string,
): Promise<EvaluationPlan> {
  return apiRequest(
    `/api/v2/evaluation-plans/${encodeURIComponent(id)}/confirm`,
    {
      method: "POST",
      ...jsonBody({
        confirmation_event_id: confirmationEventId,
        confirmed_by: "web-user",
      }),
    },
  );
}

export function submitEvaluationPlan(id: string): Promise<unknown> {
  return apiRequest(
    `/api/v2/evaluation-plans/${encodeURIComponent(id)}/submit`,
    {
      method: "POST",
      ...jsonBody({ idempotency_key: crypto.randomUUID() }),
    },
  );
}

export function cancelEvaluationPlan(id: string): Promise<EvaluationPlan> {
  return apiRequest(
    `/api/v2/evaluation-plans/${encodeURIComponent(id)}/cancel`,
    {
      method: "POST",
    },
  );
}

export function getAssistantProviderHealth(): Promise<AssistantProviderHealth> {
  return apiRequest("/api/v2/assistant/provider-health");
}

export function createTargetChat(
  targetId: string,
  profileId: string | null,
): Promise<TargetChatSession> {
  return apiRequest("/api/v2/target-chats", {
    method: "POST",
    ...jsonBody({ target_id: targetId, profile_id: profileId }),
  });
}

export function getTargetChat(sessionId: string): Promise<TargetChatSession> {
  return apiRequest(`/api/v2/target-chats/${encodeURIComponent(sessionId)}`);
}

export function listTargetChats(
  targetId: string,
): Promise<Page<TargetChatSession>> {
  return apiRequest(
    `/api/v2/target-chats?target_id=${encodeURIComponent(targetId)}&limit=100`,
  );
}

export function sendTargetChatMessage(
  sessionId: string,
  content: string,
): Promise<TargetChatSession> {
  return apiRequest(
    `/api/v2/target-chats/${encodeURIComponent(sessionId)}/messages`,
    {
      method: "POST",
      ...jsonBody({ content }),
    },
  );
}

export function closeTargetChat(sessionId: string): Promise<TargetChatSession> {
  return apiRequest(
    `/api/v2/target-chats/${encodeURIComponent(sessionId)}/close`,
    { method: "POST" },
  );
}

export function createDraftCaseFromTargetChat(
  sessionId: string,
): Promise<TestCase> {
  return apiRequest(
    `/api/v2/target-chats/${encodeURIComponent(sessionId)}/draft-case`,
    {
      method: "POST",
      ...jsonBody({}),
    },
  );
}

export function createDraftSampleFromTargetChat(
  sessionId: string,
  toolCallId: string,
): Promise<Sample> {
  return apiRequest(
    `/api/v2/target-chats/${encodeURIComponent(sessionId)}/draft-sample`,
    {
      method: "POST",
      ...jsonBody({ tool_call_id: toolCallId }),
    },
  );
}
