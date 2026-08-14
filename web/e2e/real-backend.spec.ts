import { expect, test } from "@playwright/test";

const enabled = process.env.AGENTRIG_E2E_REAL_BACKEND === "1";
const competitionCaptureDir = process.env.AGENTRIG_COMPETITION_CAPTURE_DIR;

test.describe("real AgentRig backend", () => {
  test.skip(!enabled, "set AGENTRIG_E2E_REAL_BACKEND=1 with the reference services running");

  test("creates a real Run and renders server quality/gate evidence without API mocks", async ({ page }) => {
    await page.goto("/targets/target_reference_http_sse/evaluation/comparisons");
    await expect(page.getByRole("heading", { name: "版本对比" })).toBeVisible();

    await page.getByRole("button", { name: "新建版本对比" }).click();
    await page.getByLabel("执行配置").selectOption("profile_reference_fixture_only");
    const choices = page.locator("fieldset").getByRole("checkbox");
    const policyChoice = page.locator("label", {
      hasText: "Reference confirmation policy regression",
    }).getByRole("checkbox");
    for (let index = 0; index < await choices.count(); index += 1) {
      const choice = choices.nth(index);
      const isPolicyCase = await choice.evaluate((node) =>
        node.closest("label")?.textContent?.includes("Reference confirmation policy regression"),
      );
      if (!isPolicyCase) await choice.uncheck();
    }
    await policyChoice.check();
    const submitted = page.waitForResponse((response) =>
      response.url().endsWith("/api/runs")
      && response.request().method() === "POST"
      && response.status() === 202,
    );
    await page.getByRole("button", { name: "确认并运行" }).click();
    const runId = String((await (await submitted).json()).run_id);
    await expect(page).toHaveURL(new RegExp(`/evaluation/runs/${runId}$`));

    await expect.poll(async () => {
      const response = await page.request.get(`/api/runs/${encodeURIComponent(runId)}`);
      return String((await response.json()).status);
    }, { timeout: 30_000 }).toBe("completed");
    await page.reload();
    await page.getByRole("link").filter({ hasText: "candidate-regression" }).click();
    const capabilityHeading = page.getByText("Capability Snapshot", { exact: true });
    await expect(capabilityHeading).toBeVisible();
    if (competitionCaptureDir) {
      await page.setViewportSize({ width: 1440, height: 870 });
      await capabilityHeading.evaluate((node) => node.scrollIntoView({ block: "center" }));
      await page.screenshot({
        path: `${competitionCaptureDir}/v23-capability-run.png`,
      });
    }

    await page.goto(`/targets/target_reference_http_sse/evaluation/runs/${runId}/report`);
    await expect(page.getByRole("heading", { name: "评测验收结论" })).toBeVisible();
    await expect(page.getByText("质量门禁检查", { exact: true })).toBeVisible();
    await expect(page.getByText("不通过", { exact: true })).toBeVisible();
    if (competitionCaptureDir) {
      const gateHeading = page.getByText("质量门禁检查", { exact: true });
      await gateHeading.evaluate((node) => node.scrollIntoView({ block: "start" }));
      await page.screenshot({
        path: `${competitionCaptureDir}/v23-quality-gate.png`,
      });
    }

    const quality = await page.request.get(
      `/api/runs/${encodeURIComponent(runId)}/quality-report`,
    );
    const comparison = await page.request.get(
      `/api/runs/${encodeURIComponent(runId)}/comparison-report`,
    );
    expect(quality.ok()).toBe(true);
    expect(comparison.ok()).toBe(true);
    expect((await quality.json()).source_snapshot_hash).toBe(
      (await comparison.json()).source_snapshot_hash,
    );
  });
});
