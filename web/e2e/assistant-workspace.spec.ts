import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Route } from "@playwright/test";

const sessionId = "session_demo";
const planId = "plan_demo";
const runId = "run_demo";
const createdAt = "2026-08-05T03:00:00Z";

test.beforeEach(async ({ page }) => {
  await page.route(/^http:\/\/127\.0\.0\.1:4174\/api\//, (route) => mockApi(route));
});

test("renders an auditable assistant decision and navigates to its source", async ({ page }) => {
  await page.goto("/targets/target_lassist_local/assistant");

  await expect(page.getByRole("heading", { name: "Lassist 回归验收" })).toBeVisible();
  await expect(page.getByRole("article").getByText("生成有界评测计划", { exact: true })).toBeVisible();
  await expect(page.getByText("计划已提交运行", { exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: /查看 Run/ })).toHaveAttribute(
    "href",
    `/targets/target_lassist_local/evaluation/runs/${runId}`,
  );

  const workspace = page.locator("#main-content");
  const box = await workspace.boundingBox();
  expect(box?.width).toBeGreaterThan(1100);
  expect(box?.height).toBeGreaterThan(850);

  await page.getByText("查看决策依据与取舍", { exact: true }).click();
  const caseLink = page.getByTitle("打开测试用例：case_lassist_three_agent_demo");
  await expect(caseLink).toBeVisible();
  await expect(caseLink).toHaveAttribute(
    "href",
    "/targets/target_lassist_local/evaluation/test-cases?case_id=case_lassist_three_agent_demo",
  );
  await caseLink.click();
  await expect(page).toHaveURL(/\/evaluation\/test-cases\?case_id=case_lassist_three_agent_demo$/);
});

test("has no serious or critical accessibility violations", async ({ page }) => {
  await page.goto("/targets/target_lassist_local/assistant");
  await expect(page.getByRole("heading", { name: "Lassist 回归验收" })).toBeVisible();

  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .analyze();
  const blocking = results.violations.filter((item) => ["critical", "serious"].includes(item.impact ?? ""));
  expect(blocking, blocking.map((item) => `${item.id}: ${item.help}`).join("\n")).toEqual([]);
});

async function mockApi(route: Route): Promise<void> {
  const request = route.request();
  const url = new URL(request.url());
  const path = url.pathname;

  if (path.endsWith("/stream")) {
    await route.fulfill({ status: 200, contentType: "text/event-stream", body: "" });
    return;
  }
  if (path === "/api/targets") {
    await json(route, page([target()]));
    return;
  }
  if (path === "/api/v2/assistant/sessions") {
    await json(route, page([session()]));
    return;
  }
  if (path === `/api/v2/assistant/sessions/${sessionId}`) {
    await json(route, session());
    return;
  }
  if (path === `/api/v2/assistant/sessions/${sessionId}/events`) {
    await json(route, { ...page(events()), after_seq: 0 });
    return;
  }
  if (path === `/api/v2/assistant/sessions/${sessionId}/decisions`) {
    await json(route, page([decision()]));
    return;
  }
  if (path === `/api/v2/assistant/sessions/${sessionId}/decision-metrics`) {
    await json(route, {
      decision_count: 3,
      terminal_count: 3,
      succeeded_count: 3,
      failed_count: 0,
      in_flight_count: 0,
      success_rate: 1,
      evidence_reference_count: 9,
      evidence_kind_coverage: ["assistant_event", "evaluation_plan", "run", "target", "test_case"],
      confirmation_bound_count: 2,
      provenance_linked_count: 3,
      provenance_link_rate: 1,
      latest_decision_at: createdAt,
    });
    return;
  }
  if (path === `/api/v2/evaluation-plans/${planId}`) {
    await json(route, plan());
    return;
  }
  if (path === `/api/v2/assistant/sessions/${sessionId}/invocations`) {
    await json(route, page([invocation()]));
    return;
  }
  if (path === "/api/v2/agentteams/health") {
    await json(route, {
      enabled: true,
      configured: true,
      matrix_reachable: true,
      runtime_reachable: true,
      message: "AgentTeams runtime ready",
    });
    return;
  }

  await json(route, page([]));
}

async function json(route: Route, value: unknown): Promise<void> {
  await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(value) });
}

function page(items: unknown[]) {
  return { items, total: items.length, limit: 100, offset: 0 };
}

function target() {
  return {
    id: "target_lassist_local",
    name: "PixCake / Lassist",
    driver_type: "openai_compatible",
    endpoint: "http://127.0.0.1:8000",
    versions: [{ version: "local" }],
    created_at: createdAt,
    updated_at: createdAt,
  };
}

function session() {
  return {
    id: sessionId,
    workspace_id: "default",
    title: "Lassist 回归验收",
    status: "active",
    matrix_room_id: "!demo:localhost",
    active_plan_id: planId,
    last_event_seq: 4,
    created_by: "web-user",
    created_at: createdAt,
    updated_at: createdAt,
  };
}

function events() {
  return [
    {
      id: "event_user",
      session_id: sessionId,
      seq: 1,
      event_type: "user_message",
      actor_type: "user",
      actor_id: "web-user",
      payload: { content: "使用已批准用例评测本机 Lassist。" },
      turn_id: "turn_demo",
      plan_id: null,
      run_id: null,
      case_run_id: null,
      invocation_id: null,
      decision_id: null,
      matrix_event_id: null,
      delivery_status: "delivered",
      last_error: null,
      created_at: createdAt,
    },
    {
      id: "event_decision",
      session_id: sessionId,
      seq: 2,
      event_type: "decision_recorded",
      actor_type: "manager",
      actor_id: "评测主控 Manager",
      payload: {},
      turn_id: "turn_demo",
      plan_id: planId,
      run_id: null,
      case_run_id: null,
      invocation_id: null,
      decision_id: "decision_demo",
      matrix_event_id: "$decision",
      delivery_status: "delivered",
      last_error: null,
      created_at: createdAt,
    },
    {
      id: "event_plan",
      session_id: sessionId,
      seq: 3,
      event_type: "plan_submitted",
      actor_type: "manager",
      actor_id: "评测主控 Manager",
      payload: {},
      turn_id: "turn_demo",
      plan_id: planId,
      run_id: runId,
      case_run_id: null,
      invocation_id: null,
      decision_id: null,
      matrix_event_id: "$plan",
      delivery_status: "delivered",
      last_error: null,
      created_at: createdAt,
    },
    {
      id: "event_run",
      session_id: sessionId,
      seq: 4,
      event_type: "run_status",
      actor_type: "system",
      actor_id: "agentrig-core",
      payload: { status: "completed" },
      turn_id: "turn_demo",
      plan_id: planId,
      run_id: runId,
      case_run_id: null,
      invocation_id: null,
      decision_id: null,
      matrix_event_id: null,
      delivery_status: "local",
      last_error: null,
      created_at: createdAt,
    },
  ];
}

function decision() {
  return {
    id: "decision_demo",
    session_id: sessionId,
    turn_id: "turn_demo",
    parent_decision_id: null,
    ordinal: 1,
    schema_version: "1",
    trigger: "user_message",
    decision_kind: "planning",
    status: "succeeded",
    objective: "用最小范围验证 Lassist",
    observation_summary: {
      known: ["被测 Agent 可达", "用例已批准"],
      unknown: [],
      constraints: ["不扩大范围"],
    },
    options: [{ action_type: "create_plan", label: "创建计划", expected_effect: "生成可确认预览" }],
    selected_action: {
      action_type: "create_plan",
      parameters: { target_id: "target_lassist_local" },
    },
    rationale_summary: {
      summary: "正式资产与运行时健康证据充分，创建最小评测计划。",
      tradeoffs: ["覆盖面较小，但可快速验收完整证据链"],
    },
    evidence_refs: [
      { kind: "target", resource_id: "target_lassist_local", version: "local", snapshot_hash: null, label: "Lassist" },
      { kind: "test_case", resource_id: "case_lassist_three_agent_demo", version: "approved", snapshot_hash: null, label: "三 Agent 演示" },
      { kind: "evaluation_plan", resource_id: planId, version: "1", snapshot_hash: null, label: "评测计划" },
      { kind: "run", resource_id: runId, version: null, snapshot_hash: null, label: "评测运行" },
    ],
    confidence: 0.96,
    context_hash: "context_hash",
    policy_verdict: { verdict: "allow", reasons: ["资产已审核"], rule_version: "v2.1" },
    confirmation_event_id: "event_user",
    action_idempotency_key: "action_demo",
    action_ref_type: "evaluation_plan",
    action_ref_id: planId,
    error_code: null,
    error_message: null,
    proposed_by: "manager",
    created_at: createdAt,
    authorized_at: createdAt,
    started_at: createdAt,
    finished_at: createdAt,
  };
}

function plan() {
  return {
    id: planId,
    session_id: sessionId,
    revision: 1,
    status: "submitted",
    origin_decision_id: "decision_demo",
    goal: { summary: "验证 Lassist 三 Agent 链路" },
    selection: {
      targets: [{ role: "candidate", target_id: "target_lassist_local", version: "9.2.0" }],
      case_ids: ["case_lassist_three_agent_demo"],
      profile_id: "profile_lassist_agentteams",
    },
    reasoning_summary: { summary: "使用已批准资产执行最小回归" },
    preview: {
      resolved_case_ids: ["case_lassist_three_agent_demo"],
      planned_case_runs: 1,
      skipped_items: [],
      primary_evaluators: ["evidence_judge"],
      providers: ["simulation_curator"],
    },
    confirmation: {
      required: true,
      reasons: ["评测会调用被测 Agent"],
      confirmation_event_id: "event_user",
      confirmed_by: "web-user",
      confirmed_at: createdAt,
    },
    run_id: runId,
    last_error: null,
    updated_at: createdAt,
  };
}

function invocation() {
  return {
    id: "invocation_demo",
    agent_role: "simulation_curator",
    status: "succeeded",
    session_id: sessionId,
    plan_id: planId,
    run_id: runId,
    case_run_id: "case_run_demo",
    tool_call_event_id: "run_event_demo",
    input_hash: "input_hash",
    result_ref: "sample_demo",
    result_hash: "result_hash",
    matrix_room_id: "!demo:localhost",
    request_event_id: "$request",
    response_event_id: "$response",
    assigned_agent: "simulation_curator",
    deadline: "2026-08-05T03:05:00Z",
    error_message: null,
    created_at: createdAt,
    started_at: createdAt,
    finished_at: createdAt,
  };
}
