import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

const enabled = process.env.AGENTRIG_E2E_LASSIST_BACKEND === "1";
const assistantEnabled = process.env.AGENTRIG_E2E_BASIC_ASSISTANT === "1";
const targetId = process.env.AGENTRIG_E2E_LASSIST_TARGET_ID ?? "target_lassist_local";
const requestedRunId = process.env.AGENTRIG_E2E_LASSIST_RUN_ID;
const expectedOutcome = process.env.AGENTRIG_E2E_LASSIST_EXPECTED_OUTCOME ?? "pass";
const captureDir = process.env.AGENTRIG_E2E_CAPTURE_DIR;

test.skip(!enabled, "set AGENTRIG_E2E_LASSIST_BACKEND=1 to validate a live lassist Run");

test("renders one real lassist Run from overview through Cell evidence and acceptance", async ({ page, request }) => {
  const targetResponse = await request.get(`/api/targets/${encodeURIComponent(targetId)}`);
  expect(targetResponse.ok()).toBeTruthy();
  const target = await targetResponse.json() as { id: string; name: string };

  const runsResponse = await request.get(`/api/runs?target_id=${encodeURIComponent(targetId)}&limit=50`);
  expect(runsResponse.ok()).toBeTruthy();
  const runs = await runsResponse.json() as { items: Array<{ id: string; status: string; manifest_hash: string | null; total_count: number; completed_count: number }> };
  const run = requestedRunId
    ? runs.items.find((item) => item.id === requestedRunId)
    : runs.items.find((item) => item.status === "completed" && item.manifest_hash);
  expect(run, "a completed canonical lassist Run is required").toBeTruthy();
  const runId = run!.id;

  const cellsResponse = await request.get(`/api/runs/${encodeURIComponent(runId)}/cells`);
  expect(cellsResponse.ok()).toBeTruthy();
  const cells = await cellsResponse.json() as { items: Array<{ cell_id: string; case_id: string; evaluation_state: string; attempt_count: number; finished_attempt_count: number }> };
  expect(cells.items).toHaveLength(1);
  const cell = cells.items[0];
  expect(cell.evaluation_state).toBe(expectedOutcome);

  await page.goto(`/targets/${encodeURIComponent(targetId)}/overview`);
  await expect(page.getByRole("heading", { name: `${target.name} 评测总览` })).toBeVisible();
  await expect(page.getByText("可达", { exact: true })).toBeVisible();
  await expect(page.getByText("Canonical Manifest 已冻结", { exact: true })).toBeVisible();
  if (captureDir) {
    await page.setViewportSize({ width: 1600, height: 1000 });
    await page.screenshot({ path: `${captureDir}/lassist-${expectedOutcome}-01-overview.png`, fullPage: true });
  }

  await page.goto(`/targets/${encodeURIComponent(targetId)}/evaluation/runs/${encodeURIComponent(runId)}`);
  await expect(page.getByRole("heading", { name: `运行 ${runId.slice(0, 18)}` })).toBeVisible();
  await expect(page.getByText(`${run!.completed_count} / ${run!.total_count} Attempts`, { exact: true })).toBeVisible();
  await expect(page.getByText(cell.case_id, { exact: true })).toBeVisible();
  const cellRow = page.getByRole("link", { name: new RegExp(cell.case_id) });
  await expect(cellRow).toContainText(`${cell.attempt_count}/${cell.attempt_count}`);
  if (captureDir) {
    await page.screenshot({ path: `${captureDir}/lassist-${expectedOutcome}-02-run.png`, fullPage: true });
  }

  await page.goto(`/targets/${encodeURIComponent(targetId)}/evaluation/runs/${encodeURIComponent(runId)}/cells/${encodeURIComponent(cell.cell_id)}`);
  await expect(page.getByRole("heading", { name: cell.case_id })).toBeVisible();
  await expect(page.getByText("调用工具", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("返回工具结果", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("rule 评判完成", { exact: true }).first()).toBeVisible();
  if (captureDir) {
    await page.screenshot({ path: `${captureDir}/lassist-${expectedOutcome}-03-cell.png`, fullPage: true });
  }

  await page.goto(`/targets/${encodeURIComponent(targetId)}/evaluation/runs/${encodeURIComponent(runId)}/report`);
  await expect(page.getByRole("heading", { name: "评测验收结论" })).toBeVisible();
  const conclusion = page.getByText("验收结论", { exact: true }).locator("..");
  await expect(conclusion.getByText(expectedOutcome === "pass" ? "通过" : "不通过", { exact: true })).toBeVisible();
  await expect(page.getByText("单目标 Run 无需 A/B 发布门禁", { exact: true })).toBeVisible();
  if (expectedOutcome === "pass") {
    await expect(page.getByText("没有业务失败项", { exact: true })).toBeVisible();
  } else {
    await expect(page.getByText(cell.case_id, { exact: true }).first()).toBeVisible();
  }

  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow).toBeLessThanOrEqual(1);
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .analyze();
  const blocking = results.violations.filter((item) =>
    ["critical", "serious"].includes(item.impact ?? ""),
  );
  expect(blocking, blocking.map((item) => `${item.id}: ${item.help}`).join("\n")).toEqual([]);

  if (captureDir) {
    await page.screenshot({ path: `${captureDir}/lassist-${expectedOutcome}-04-acceptance.png`, fullPage: true });
  }
});

test("renders a real model-backed assistant answer without AgentTeams topology", async ({ page, request }) => {
  test.skip(!assistantEnabled, "set AGENTRIG_E2E_BASIC_ASSISTANT=1 after a real provider turn");
  const healthResponse = await request.get("/api/v2/assistant/provider-health");
  expect(healthResponse.ok()).toBeTruthy();
  expect(await healthResponse.json()).toMatchObject({
    available: true,
    provider: "openai_compatible",
  });
  const sessionsResponse = await request.get("/api/v2/assistant/sessions?limit=5");
  const sessions = await sessionsResponse.json() as { items: Array<{ id: string; title: string }> };
  expect(sessions.items.length).toBeGreaterThan(0);
  const latest = sessions.items[0];
  const eventsResponse = await request.get(`/api/v2/assistant/sessions/${encodeURIComponent(latest.id)}/events`);
  const events = await eventsResponse.json() as { items: Array<{ id: string; event_type: string; payload: { content?: string; source?: string } }> };
  const reply = events.items.find((item) =>
    item.event_type === "assistant_message" && item.payload.source === "basic_model_provider",
  );
  expect(reply?.payload.content).toBeTruthy();

  await page.goto(`/targets/${encodeURIComponent(targetId)}/assistant`);
  await expect(page.getByRole("heading", { name: latest.title })).toBeVisible();
  await expect(page.getByText("基础评测助手已就绪", { exact: true })).toBeVisible();
  const assistantReply = page.locator(`#assistant-event-${reply!.id}`);
  await expect(assistantReply.getByText("已根据请求生成评测计划，等待确认后才会执行，当前不会产生任何真实图片副作用。")).toBeVisible();
  await expect(assistantReply.getByText(/compat_tc_from_error_099/)).toBeVisible();
  await expect(assistantReply.getByText(/profile_lassist_fixture_rule/)).toBeVisible();
  await expect(page.getByText("草稿", { exact: true })).toBeVisible();
  await expect(page.getByText("Assistant", { exact: true })).toBeVisible();
  await expect(page.getByText("Run / Cell 证据", { exact: true })).toBeVisible();
  await expect(page.getByText("Curator", { exact: true })).toHaveCount(0);
  await expect(page.getByText("Judge", { exact: true })).toHaveCount(0);

  if (captureDir) {
    await page.setViewportSize({ width: 1600, height: 1000 });
    await page.screenshot({ path: `${captureDir}/lassist-assistant-plan.png`, fullPage: true });
  }
});
