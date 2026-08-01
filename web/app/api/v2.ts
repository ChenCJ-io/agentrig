import {
  ApiError,
  apiRequest,
  authRequiredEvent,
  getAuthHeaders,
  jsonBody,
  resolveApiUrl,
} from "./client";

export interface AssistantSession {
  id: string;
  workspace_id: string;
  title: string;
  status: "active" | "archived";
  matrix_room_id: string | null;
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
  actor_type: "user" | "manager" | "worker" | "system";
  actor_id: string;
  payload: Record<string, unknown>;
  turn_id: string | null;
  plan_id: string | null;
  run_id: string | null;
  invocation_id: string | null;
  delivery_status: "local" | "pending" | "delivered" | "failed";
  last_error: string | null;
  created_at: string;
}

export interface AssistantEventPage {
  items: AssistantEvent[];
  total: number;
  limit: number;
  after_seq: number;
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

export interface AgentInvocation {
  id: string;
  agent_role: "simulation_curator" | "evidence_judge";
  status: string;
  run_id: string;
  case_run_id: string;
  assigned_agent: string | null;
  error_message: string | null;
  created_at: string;
}

export interface AgentInvocationPage {
  items: AgentInvocation[];
  total: number;
  limit: number;
  offset: number;
}

export interface AgentTeamsHealth {
  enabled: boolean;
  configured: boolean;
  matrix_reachable: boolean;
  runtime_reachable: boolean | null;
  message: string;
}

export interface MessageReceipt {
  event_id: string;
  turn_id: string;
  delivery_status: string;
}

export function listAssistantSessions(): Promise<AssistantSessionPage> {
  return apiRequest("/api/v2/assistant/sessions?limit=100");
}

export function createAssistantSession(title: string): Promise<AssistantSession> {
  return apiRequest("/api/v2/assistant/sessions", {
    method: "POST",
    ...jsonBody({ title }),
  });
}

export function getAssistantSession(id: string): Promise<AssistantSession> {
  return apiRequest(`/api/v2/assistant/sessions/${encodeURIComponent(id)}`);
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
): Promise<MessageReceipt> {
  return apiRequest(
    `/api/v2/assistant/sessions/${encodeURIComponent(sessionId)}/messages`,
    {
      method: "POST",
      ...jsonBody({
        client_message_id: crypto.randomUUID(),
        content,
        active_plan_id: activePlanId,
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
  return apiRequest(`/api/v2/evaluation-plans/${encodeURIComponent(id)}/confirm`, {
    method: "POST",
    ...jsonBody({
      confirmation_event_id: confirmationEventId,
      confirmed_by: "web-user",
    }),
  });
}

export function submitEvaluationPlan(id: string): Promise<unknown> {
  return apiRequest(`/api/v2/evaluation-plans/${encodeURIComponent(id)}/submit`, {
    method: "POST",
    ...jsonBody({ idempotency_key: crypto.randomUUID() }),
  });
}

export function cancelEvaluationPlan(id: string): Promise<EvaluationPlan> {
  return apiRequest(`/api/v2/evaluation-plans/${encodeURIComponent(id)}/cancel`, {
    method: "POST",
  });
}

export function listAgentInvocations(id: string): Promise<AgentInvocationPage> {
  return apiRequest(
    `/api/v2/assistant/sessions/${encodeURIComponent(id)}/agent-invocations?limit=100`,
  );
}

export function getAgentTeamsHealth(): Promise<AgentTeamsHealth> {
  return apiRequest("/api/v2/agentteams/health");
}
