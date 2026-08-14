import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

const enabled = process.env.AGENTRIG_E2E_EDITFLOW_RECORDING === "1";
const targetId = "target_editflow_http_sse";
const runId = process.env.AGENTRIG_E2E_EDITFLOW_RUN_ID ?? "run_38a956103b0c495b81bffaf0c272e84a";
const sessionId = process.env.AGENTRIG_E2E_EDITFLOW_SESSION_ID ?? "asst_b0c42e2e33834864b5ac64b17fa8f9d7";
const captureDir = process.env.AGENTRIG_E2E_CAPTURE_DIR;

test.skip(!enabled, "set AGENTRIG_E2E_EDITFLOW_RECORDING=1 for live EditFlow captures");

test("captures the real EditFlow candidate matrix and assistant plan", async ({ page, request }) => {
  const cellsResponse = await request.get(`/api/runs/${encodeURIComponent(runId)}/cells?limit=20`);
  expect(cellsResponse.ok()).toBeTruthy();
  const cells = await cellsResponse.json() as {
    items: Array<{ cell_id: string; case_id: string; evaluation_state: string; attempt_count: number }>;
  };
  expect(cells.items).toHaveLength(6);
  expect(cells.items.every((item) => item.evaluation_state === "pass" && item.attempt_count === 5)).toBeTruthy();

  await page.setViewportSize({ width: 1600, height: 1000 });
  await page.goto(`/targets/${targetId}/overview`);
  await expect(page.getByRole("heading", { name: /EditFlow public Agno image agent 评测总览/ })).toBeVisible();
  if (captureDir) await page.screenshot({ path: `${captureDir}/editflow-01-overview.png`, fullPage: true });

  await page.goto(`/targets/${targetId}/evaluation/runs/${runId}`);
  await expect(page.getByRole("heading", { name: `运行 ${runId.slice(0, 18)}` })).toBeVisible();
  await expect(page.getByText("30 / 30 Attempts", { exact: true })).toBeVisible();
  if (captureDir) await page.screenshot({ path: `${captureDir}/editflow-02-candidate-run.png`, fullPage: true });

  const mixed = cells.items.find((item) => item.case_id === "case_editflow_mixed_chain");
  expect(mixed).toBeTruthy();
  await page.goto(`/targets/${targetId}/evaluation/runs/${runId}/cells/${encodeURIComponent(mixed!.cell_id)}`);
  await expect(page.getByRole("heading", { name: "case_editflow_mixed_chain" })).toBeVisible();
  await expect(page.getByText("调用工具", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("返回工具结果", { exact: true }).first()).toBeVisible();
  if (captureDir) await page.screenshot({ path: `${captureDir}/editflow-03-timeline.png`, fullPage: true });

  await page.goto(`/targets/${targetId}/evaluation/runs/${runId}/report`);
  await expect(page.getByRole("heading", { name: "评测验收结论" })).toBeVisible();
  await expect(page.getByText("通过", { exact: true }).first()).toBeVisible();
  if (captureDir) await page.screenshot({ path: `${captureDir}/editflow-04-acceptance.png`, fullPage: true });

  await page.goto(`/targets/${targetId}/assistant?session=${sessionId}`);
  await expect(page.getByRole("heading", { name: "EditFlow 普通用户回归验收" })).toBeVisible();
  await expect(page.getByText(/case_editflow_brighten_only/).first()).toBeVisible();
  if (captureDir) await page.screenshot({ path: `${captureDir}/editflow-05-assistant.png`, fullPage: true });

  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .analyze();
  const blocking = results.violations.filter((item) => ["critical", "serious"].includes(item.impact ?? ""));
  expect(blocking, blocking.map((item) => `${item.id}: ${item.help}`).join("\n")).toEqual([]);
});
