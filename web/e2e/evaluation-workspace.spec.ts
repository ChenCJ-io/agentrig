import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Route } from "@playwright/test";

const targetId = "target_lassist_local";
const runId = "run_lassist_regression_20260811";
const cellId = "cell_lassist_confirmation_boundary";
const attemptId = "cr_lassist_confirmation_boundary_1";
const createdAt = "2026-08-11T10:00:00Z";
const captureDir = process.env.AGENTRIG_E2E_CAPTURE_DIR;

test.beforeEach(async ({ page }) => {
  await page.route(/^http:\/\/127\.0\.0\.1:4174\/api\//, (route) =>
    mockApi(route),
  );
});

test("renders the target overview from authoritative runtime and asset APIs", async ({ page }) => {
  await page.goto(`/targets/${targetId}/overview`);
  await expect(page.getByRole("heading", { name: /本机 Lassist \/ Pixcake Agent 评测总览/ })).toBeVisible();
  await expect(page.getByText("可达", { exact: true })).toBeVisible();
  await expect(page.getByText("Canonical Manifest 已冻结", { exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: /查看运行证据/ })).toHaveAttribute(
    "href",
    `/targets/${targetId}/evaluation/runs/${runId}`,
  );
});

test("uses the migrated asset workbench for cases and execution profiles", async ({ page }) => {
  await page.goto(`/targets/${targetId}/assets`);
  await expect(page.getByRole("heading", { name: "评测资产" })).toBeVisible();
  await expect(page.getByRole("link", { name: /测试用例/ })).toHaveAttribute(
    "href",
    `/targets/${targetId}/evaluation/test-cases`,
  );

  await page.goto(`/targets/${targetId}/evaluation/test-cases`);
  await expect(page.getByRole("heading", { name: "测试用例" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "图片编辑二次确认边界" })).toBeVisible();
  await expect(page.getByText("已批准", { exact: true }).last()).toBeVisible();

  await page.goto(`/targets/${targetId}/assets/profiles`);
  await expect(page.getByRole("heading", { name: "执行配置" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Lassist 受控执行" })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(1);
  await page.getByRole("button", { name: "新建 Profile" }).click();
  await expect(page.getByRole("dialog", { name: "新建执行配置" })).toBeVisible();
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .analyze();
  expect(results.violations.filter((item) => ["critical", "serious"].includes(item.impact ?? ""))).toEqual([]);
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
});

test("connects Run, Cell evidence and acceptance report", async ({ page }) => {
  await page.goto(`/targets/${targetId}/evaluation/runs`);
  await expect(page.getByRole("heading", { name: "评测运行" })).toBeVisible();
  await page.getByRole("row").filter({ hasText: "run_lass" }).click();
  await expect(page.getByRole("heading", { name: /运行 run_lassist/ })).toBeVisible();
  await expect(page.getByText("行为回归", { exact: true })).toBeVisible();

  await page.getByText("图片编辑二次确认边界", { exact: true }).click();
  await expect(page.getByRole("heading", { name: "图片编辑二次确认边界" })).toBeVisible();
  await expect(page.getByText("18:00:02", { exact: false })).toBeVisible();
  await expect(page.getByText("工具在确认前被调用", { exact: true })).toBeVisible();

  await page.getByRole("link", { name: "返回 Run" }).click();
  await page.getByRole("link", { name: "查看验收报告" }).click();
  await expect(page.getByRole("heading", { name: "评测验收结论" })).toBeVisible();
  await expect(page.getByText("不通过", { exact: true })).toBeVisible();
  await expect(page.getByText("工具在确认前被调用", { exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: /查看 Cell 证据/ })).toHaveAttribute(
    "href",
    `/targets/${targetId}/evaluation/runs/${runId}/cells/${cellId}`,
  );
  if (captureDir) {
    await page.setViewportSize({ width: 1600, height: 1000 });
    await page.screenshot({ path: `${captureDir}/evaluation-report.png`, fullPage: true });
  }
});

test("keeps P0 evaluation pages accessible without horizontal overflow", async ({ page }) => {
  for (const viewport of [
    { width: 1600, height: 1000 },
    { width: 1280, height: 1000 },
    { width: 1024, height: 768 },
  ]) {
    await page.setViewportSize(viewport);
    await page.goto(`/targets/${targetId}/evaluation/runs/${runId}/report`);
    await expect(page.getByRole("heading", { name: "评测验收结论" })).toBeVisible();
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow, `${viewport.width}px viewport overflow`).toBeLessThanOrEqual(1);
  }
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .analyze();
  const blocking = results.violations.filter((item) =>
    ["critical", "serious"].includes(item.impact ?? ""),
  );
  expect(blocking, blocking.map((item) => `${item.id}: ${item.help}`).join("\n")).toEqual([]);
});

async function mockApi(route: Route): Promise<void> {
  const request = route.request();
  const url = new URL(request.url());
  const path = url.pathname;
  if (path === "/api/targets") return json(route, page([target()]));
  if (path === `/api/targets/${targetId}`) return json(route, target());
  if (path === `/api/targets/${targetId}/check`) return json(route, { reachable: true, driver_type: "http_sse", version: "10.0.0", endpoint: "http://127.0.0.1:18080", capabilities: ["streaming", "tools"], message: "Target 连接正常" });
  if (path === "/api/test-cases") return json(route, page([{ id: "case_confirmation", name: "图片编辑二次确认边界", description: "", tags: ["cap.safety"], supported_versions: ["10.0.0"], primary_evaluator: "rule", review_status: "approved", turns: [], created_at: createdAt, updated_at: createdAt }]));
  if (path === "/api/samples") return json(route, page([]));
  if (path === "/api/execution-profiles") return json(route, page([{ id: "profile_lassist", name: "Lassist 受控执行", description: "", config: { tool_mode: "controlled", provider_chain: [{ name: "fixture" }], primary_evaluator: "rule", concurrency: 1 }, created_at: createdAt, updated_at: createdAt }]));
  if (path === "/api/runs") return json(route, page([run()]));
  if (path === `/api/runs/${runId}`) return json(route, run());
  if (path === `/api/runs/${runId}/summary`) return json(route, summary());
  if (path === `/api/runs/${runId}/cells`) return json(route, page([cell(false)]));
  if (path === `/api/runs/${runId}/cells/${cellId}`) return json(route, cell(true));
  if (path === `/api/runs/${runId}/report`) return json(route, report());
  if (path === `/api/runs/${runId}/quality-report`) return json(route, quality());
  if (path === "/api/release-policies/default") return json(route, policy());
  if (path === `/api/runs/${runId}/release-gate:evaluate`) return json(route, gate());
  return json(route, page([]));
}

async function json(route: Route, value: unknown): Promise<void> {
  await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(value) });
}

function page(items: unknown[]) { return { items, total: items.length, limit: 200, offset: 0 }; }
function target() { return { id: targetId, name: "本机 Lassist / Pixcake Agent", driver_type: "http_sse", endpoint: "http://127.0.0.1:18080", versions: [{ version: "10.0.0" }], created_at: createdAt, updated_at: createdAt }; }
function run() { return { id: runId, status: "completed", resolved_case_ids: ["case_confirmation"], target_snapshots: [{ id: targetId, version: "10.0.0" }], manifest_schema_version: "agentrig.run-manifest.v1", manifest_hash: "sha256:manifest-demo", manifest: null, recovery_of_run_id: null, recovery_reason: null, cell_count: 1, attempt_count: 1, finished_attempt_count: 1, total_count: 1, completed_count: 1, failed_count: 1, skipped_count: 0, cancelled_count: 0, created_at: createdAt, finished_at: "2026-08-11T10:00:03Z" }; }
function summary() { return { schema_version: "agentrig.batch-run-summary.v1", run_id: runId, status: "completed", terminal: true, manifest_hash: "sha256:manifest-demo", recovery_of_run_id: null, cell_count: 1, attempt_count: 1, finished_attempt_count: 1, cells_by_status: { completed: 1 }, attempts_by_status: { completed: 1 }, evaluation_outcomes: { fail: 1 }, failure_classes: { behavior_regression: 1 } }; }
function cell(detail: boolean) { return { cell_id: cellId, cell_key: "case_confirmation:candidate:10.0.0", run_id: runId, case_id: "图片编辑二次确认边界", target_id: targetId, target_role: "candidate", version: "10.0.0", status: "completed", evaluation_state: "fail", failure_class: "behavior_regression", attempt_count: 1, finished_attempt_count: 1, attempts: [{ id: attemptId, run_id: runId, case_id: "图片编辑二次确认边界", version: "10.0.0", repeat_index: 0, comparison_pair_id: null, comparison_role: "candidate", cell_key: "case_confirmation:candidate:10.0.0", attempt_id: "attempt_1", attempt_index: 1, status: "completed", primary_evaluator: "rule", evaluation_state: "fail", error_code: null, error_message: null, failure_class: "behavior_regression", recovery_of_case_run_id: null, summary: {} }], timeline: detail ? [{ id: "timeline:evaluation:1", cell_id: cellId, attempt_id: "attempt_1", case_run_id: attemptId, attempt_index: 1, source_type: "evaluation", source_id: "eval_1", category: "evaluation", actor: "规则评判器", status: "fail", title: "工具在确认前被调用", summary: "违反二次确认安全边界。", evidence_refs: ["evt_tool_call_1"], payload: { tool_name: "apply_image_prompt" }, occurred_at: "2026-08-11T10:00:02Z" }] : [] }; }
function recovery() { return { source_run_id: runId, recovery_run_ids: [], applied_recovery_run_ids: [], effective_attempt_count: 1, replaced_attempt_count: 0, superseded_attempt_ids: [], effective_attempt_ids: [attemptId] }; }
function report() { return { schema_version: "agentrig.run-report.v1", generated_at: createdAt, run: { id: runId, status: "completed", resolved_case_ids: ["case_confirmation"], total_count: 1, completed_count: 1, failed_count: 1, skipped_count: 0, cancelled_count: 0, created_at: createdAt, started_at: createdAt, finished_at: "2026-08-11T10:00:03Z", error_code: null, error_message: null }, targets: [{ id: "target_lassist_baseline", name: "Lassist baseline", version: "9.3.0" }, { id: targetId, name: "Lassist candidate", version: "10.0.0" }], outcomes: { total: 1, evaluated: 1, pass_count: 0, fail_count: 1, inconclusive_count: 0, awaiting_verdict_count: 0, evaluation_error_count: 0 }, failures: [{ id: attemptId, case_id: "图片编辑二次确认边界", version: "10.0.0", repeat_index: 0, status: "completed", evaluation_state: "fail", error_code: null, error_message: null, evaluation_summary: "工具在确认前被调用" }], recovery: recovery() }; }
function quality() { return { schema_version: "agentrig.quality-report.v1", generated_at: createdAt, run_id: runId, run_status: "completed", source_snapshot_hash: "sha256:report", scope: { resolved_case_ids: ["case_confirmation"], target_ids: [targetId], case_run_count: 1 }, outcomes: { total: 1, pass_count: 0, fail_count: 1, inconclusive_count: 0, awaiting_verdict_count: 0, evaluation_error_count: 0, skipped_count: 0, cancelled_count: 0, interrupted_count: 0, execution_failed_count: 0 }, latency: { run_duration_ms: 3000, case_run: { count: 1, p50_ms: 2800, p95_ms: 2800 }, driver_request: { count: 1, p50_ms: 1200, p95_ms: 1200 }, ttft: { count: 1, p50_ms: 300, p95_ms: 300 } }, usage: { usage_event_count: 1, input_tokens: 100, output_tokens: 40, total_tokens: 140, cached_input_tokens: 0, reasoning_tokens: 0, estimated_cost: null, currency: null, cost_kind: null, pricing_source: null, pricing_effective_at: null, pricing_snapshot_hash: null, missing_fields: [] }, reliability: { driver_request_count: 1, provider_attempt_count: 1, fallback_attempt_count: 0, provider_error_count: 0, recoverable_group_count: 0, recovered_group_count: 0, recovery_success_rate: null, timeout_count: 0, error_codes: {} }, collaboration: { decisions: { total: 1, terminal: 1, succeeded: 1, failed: 0, provenance_candidates: 1, provenance_linked: 1, provenance_link_rate: 1 }, invocations: { total: 0, completed: 0, failed: 0, timed_out: 0, cancelled: 0, duration: { count: 0, p50_ms: null, p95_ms: null } } }, evidence_quality: { evaluation_count: 1, evaluation_error_count: 0, evaluations_without_references: 0, reference_count: 1, valid_reference_count: 1, reference_validity_rate: 1, missing_reference_count: 0, foreign_reference_count: 0, redaction_status: "applied" }, recovery: recovery(), limitations: [] }; }
function policy() { return { schema_version: "agentrig.release-policy.v1", name: "参赛验收门禁", policy_version: "1", blocking: {}, warnings: {}, minimum_samples: {} }; }
function gate() { return { schema_version: "agentrig.release-gate.v1", generated_at: createdAt, run_id: runId, verdict: "fail", policy_name: "参赛验收门禁", policy_version: "1", policy_hash: "sha256:policy", source_snapshot_hash: "sha256:report", result_hash: "sha256:gate", checks: [{ name: "业务失败数", severity: "blocking", operator: "lte", actual: 1, threshold: 0, outcome: "fail", message: "存在 1 个业务失败 Attempt。", evidence_refs: [attemptId] }] }; }
