import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Route } from "@playwright/test";

const targetId = "target_reference_http_sse";
const sessionId = "session_demo";
const planId = "plan_demo";
const runId = "run_demo";
const createdAt = "2026-08-05T03:00:00Z";

test.beforeEach(async ({ page }) => {
  await page.route(/^http:\/\/127\.0\.0\.1:4174\/api\//, (route) =>
    mockApi(route),
  );
});

test("renders the assistant timeline and links the submitted run", async ({
  page,
}) => {
  await page.goto(`/targets/${targetId}/assistant`);

  await expect(
    page.getByRole("heading", { name: "Reference 回归验收" }),
  ).toBeVisible({
    timeout: 15_000,
  });
  await expect(page.getByText("计划已提交运行", { exact: true })).toBeVisible();
  await expect(
    page.getByText("11:00:00 · 北京时间", { exact: true }),
  ).toBeVisible();
  await expect(page.getByRole("link", { name: /查看 Run/ })).toHaveAttribute(
    "href",
    `/targets/${targetId}/evaluation/runs/${runId}`,
  );

  const workspace = page.locator("#main-content");
  const box = await workspace.boundingBox();
  expect(box?.width).toBeGreaterThan(1100);
  expect(box?.height).toBeGreaterThan(850);
});

test("has no serious or critical accessibility violations", async ({
  page,
}) => {
  await page.goto(`/targets/${targetId}/assistant`);
  await expect(
    page.getByRole("heading", { name: "Reference 回归验收" }),
  ).toBeVisible({
    timeout: 15_000,
  });

  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .analyze();
  const blocking = results.violations.filter((item) =>
    ["critical", "serious"].includes(item.impact ?? ""),
  );
  expect(
    blocking,
    blocking.map((item) => `${item.id}: ${item.help}`).join("\n"),
  ).toEqual([]);
});

test("keeps session creation and draft plan actions readable", async ({
  page,
}) => {
  await page.route(
    `http://127.0.0.1:4174/api/v2/evaluation-plans/${planId}`,
    (route) =>
      json(route, {
        ...plan(),
        status: "draft",
        run_id: null,
      }),
  );
  await page.goto(`/targets/${targetId}/assistant`);

  const titleInput = page.getByLabel("新会话标题");
  const createButton = page.getByRole("button", { name: "新建" });
  await expect(titleInput).toBeVisible({ timeout: 15_000 });
  await expect(createButton).toBeVisible();
  await expect(createButton).toHaveCSS("white-space", "nowrap");

  const creationLayout = await titleInput.evaluate((input) => {
    const form = input.parentElement;
    const button = form?.querySelector("button");
    const formBox = form?.getBoundingClientRect();
    const inputBox = input.getBoundingClientRect();
    const buttonBox = button?.getBoundingClientRect();
    return {
      aligned: buttonBox
        ? Math.abs(inputBox.top - buttonBox.top) < 1 &&
          Math.abs(inputBox.height - buttonBox.height) < 1
        : false,
      contained:
        Boolean(formBox && buttonBox) && buttonBox!.right <= formBox!.right + 1,
    };
  });
  expect(creationLayout).toEqual({ aligned: true, contained: true });

  const actionButtons = ["编辑计划", "确认计划", "取消计划"].map((name) =>
    page.getByRole("button", { name }),
  );
  for (const button of actionButtons) {
    await expect(button).toBeVisible();
    await expect(button).toHaveCSS("white-space", "nowrap");
  }
  const widths = await Promise.all(
    actionButtons.map(
      async (button) => (await button.boundingBox())?.width ?? 0,
    ),
  );
  expect(Math.min(...widths)).toBeGreaterThan(90);
  expect(Math.max(...widths) - Math.min(...widths)).toBeLessThan(2);
});

test("locks chat and plan actions while the assistant turn is running", async ({
  page,
}) => {
  await page.route(
    `http://127.0.0.1:4174/api/v2/evaluation-plans/${planId}`,
    (route) => json(route, { ...plan(), status: "draft", run_id: null }),
  );
  await page.route(
    "http://127.0.0.1:4174/api/v2/assistant/turns/turn_demo",
    (route) =>
      json(route, {
        id: "turn_demo",
        session_id: sessionId,
        trigger_event_id: "event_user",
        status: "running",
        started_at: createdAt,
        finished_at: null,
        error_code: null,
        error_message: null,
        model_metadata: {},
        created_at: createdAt,
      }),
  );
  await page.goto(`/targets/${targetId}/assistant`);

  await expect(
    page.getByPlaceholder("评测助手 正在处理上一条请求…"),
  ).toBeDisabled({ timeout: 15_000 });
  await expect(page.getByRole("button", { name: "确认计划" })).toBeDisabled();
  await expect(page.getByRole("button", { name: "取消计划" })).toBeDisabled();
  await expect(
    page.getByText("评测助手 正在处理", { exact: true }),
  ).toBeVisible();
});

async function mockApi(route: Route): Promise<void> {
  const request = route.request();
  const url = new URL(request.url());
  const path = url.pathname;

  if (path.endsWith("/stream")) {
    await route.fulfill({
      status: 200,
      contentType: "text/event-stream",
      body: "",
    });
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
  if (path === "/api/v2/assistant/turns/turn_demo") {
    await json(route, {
      id: "turn_demo",
      session_id: sessionId,
      trigger_event_id: "event_user",
      status: "completed",
      started_at: createdAt,
      finished_at: createdAt,
      error_code: null,
      error_message: null,
      model_metadata: {},
      created_at: createdAt,
    });
    return;
  }
  if (path === `/api/v2/evaluation-plans/${planId}`) {
    await json(route, plan());
    return;
  }
  if (path === "/api/v2/assistant/provider-health") {
    await json(route, {
      enabled: true,
      available: true,
      provider: "openai_compatible",
      message: "评测助手模型 Provider 已就绪",
    });
    return;
  }

  await json(route, page([]));
}

async function json(route: Route, value: unknown): Promise<void> {
  await route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify(value),
  });
}

function page(items: unknown[]) {
  return { items, total: items.length, limit: 100, offset: 0 };
}

function target() {
  return {
    id: targetId,
    name: "Reference HTTP/SSE Agent",
    driver_type: "http_sse",
    endpoint: "http://127.0.0.1:8091",
    versions: [{ version: "baseline" }],
    created_at: createdAt,
    updated_at: createdAt,
  };
}

function session() {
  return {
    id: sessionId,
    workspace_id: "default",
    title: "Reference 回归验收",
    status: "active",
    active_plan_id: planId,
    last_event_seq: 3,
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
      payload: { content: "使用已批准用例评测 Reference Target。" },
      turn_id: "turn_demo",
      plan_id: null,
      run_id: null,
      case_run_id: null,
      client_message_id: "message-1",
      delivery_status: "local",
      delivery_attempts: 1,
      last_error: null,
      created_at: createdAt,
    },
    {
      id: "event_plan",
      session_id: sessionId,
      seq: 2,
      event_type: "plan_submitted",
      actor_type: "manager",
      actor_id: "assistant",
      payload: {},
      turn_id: "turn_demo",
      plan_id: planId,
      run_id: runId,
      case_run_id: null,
      client_message_id: null,
      delivery_status: "local",
      delivery_attempts: 1,
      last_error: null,
      created_at: createdAt,
    },
    {
      id: "event_run",
      session_id: sessionId,
      seq: 3,
      event_type: "run_status",
      actor_type: "system",
      actor_id: "agentrig-core",
      payload: { status: "completed" },
      turn_id: "turn_demo",
      plan_id: planId,
      run_id: runId,
      case_run_id: null,
      client_message_id: null,
      delivery_status: "local",
      delivery_attempts: 1,
      last_error: null,
      created_at: createdAt,
    },
  ];
}

function plan() {
  return {
    id: planId,
    session_id: sessionId,
    revision: 1,
    status: "submitted",
    goal: { summary: "验证 Reference Target 成功场景" },
    selection: {
      targets: [
        {
          role: "candidate",
          target_id: targetId,
          version: "baseline",
        },
      ],
      case_ids: ["case_reference_success"],
      profile_id: "profile_reference_fixture_only",
    },
    reasoning_summary: { summary: "使用已批准资产执行最小回归" },
    preview: {
      resolved_case_ids: ["case_reference_success"],
      planned_case_runs: 1,
      skipped_items: [],
      primary_evaluators: ["rule"],
      providers: ["fixture"],
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
