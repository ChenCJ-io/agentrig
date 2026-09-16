import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Route } from "@playwright/test";

const sourceId = "ingest_demo_source";
const token = "agit_demo_token_shown_once";

test("walks from source creation to the first received trace", async ({ page }) => {
  let traceRequests = 0;
  await page.route(/^http:\/\/127\.0\.0\.1:4174\/api\//, (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === "/api/projects") {
      return json(route, {
        items: [{ id: "default", slug: "default", name: "default", status: "active", default_environment: "local" }],
        total: 1,
        limit: 100,
        offset: 0,
      });
    }
    if (
      url.pathname === "/api/projects/default/production/ingest-sources" &&
      route.request().method() === "POST"
    ) {
      return json(route, {
        source: {
          id: sourceId,
          name: "my-agent",
          allowed_service_names: ["my-agent"],
          retention_days: 30,
          enabled: true,
          last_seen_at: null,
        },
        token,
      });
    }
    if (url.pathname === "/api/projects/default/production/traces") {
      traceRequests += 1;
      const items =
        traceRequests < 2
          ? []
          : [
              {
                id: "trace_first",
                source_id: sourceId,
                session_id: null,
                external_trace_id: "0a".repeat(16),
                name: "chat demo",
                started_at: "2026-09-08T03:00:00Z",
                ended_at: "2026-09-08T03:00:01Z",
                status: "unset",
                service_name: "my-agent",
                environment: "demo",
                release: null,
                attributes: {},
                token_usage: {},
                ingest_status: "accepted",
                content_hash: "sha256:demo",
              },
            ];
      return json(route, { items, total: items.length, limit: 100, offset: 0 });
    }
    return json(route, { items: [], total: 0, limit: 100, offset: 0 });
  });

  await page.goto("/onboarding");
  await expect(
    page.getByRole("heading", { name: "把线上 LLM 调用接入 AgentRig" }),
  ).toBeVisible({ timeout: 15_000 });

  await expect(page.getByText("先完成第 1 步。")).toBeVisible();
  await page.getByRole("button", { name: "创建并签发 token" }).click();

  await expect(page.getByText("token 只显示这一次", { exact: false })).toBeVisible();
  await expect(page.getByText(token, { exact: true })).toBeVisible();
  await expect(page.getByText(`x-agentrig-source=${sourceId}`, { exact: false })).toBeVisible();

  await page.getByRole("tab", { name: "Python 代码" }).click();
  await expect(page.getByText("OTLPSpanExporter", { exact: false })).toBeVisible();

  await expect(
    page.getByText("已收到第一条 trace，接入完成。", { exact: true }),
  ).toBeVisible({ timeout: 15_000 });
  await expect(page.getByRole("link", { name: "查看生产证据 →" })).toHaveAttribute(
    "href",
    "/production",
  );
});

test("onboarding page has no serious or critical accessibility violations", async ({
  page,
}) => {
  await page.route(/^http:\/\/127\.0\.0\.1:4174\/api\//, (route) =>
    json(route, { items: [], total: 0, limit: 100, offset: 0 }),
  );
  await page.goto("/onboarding");
  await expect(
    page.getByRole("heading", { name: "把线上 LLM 调用接入 AgentRig" }),
  ).toBeVisible({ timeout: 15_000 });

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

async function json(route: Route, value: unknown): Promise<void> {
  await route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify(value),
  });
}

test("creates a gateway source and shows the base_url snippet", async ({ page }) => {
  await page.route(/^http:\/\/127\.0\.0\.1:4174\/api\//, (route) => {
    const url = new URL(route.request().url());
    if (
      url.pathname === "/api/projects/default/production/ingest-sources" &&
      route.request().method() === "POST"
    ) {
      const body = route.request().postDataJSON() as {
        source_type?: string;
        gateway?: { upstream_base_url?: string };
      };
      if (body.source_type !== "openai_gateway" || !body.gateway?.upstream_base_url) {
        return route.fulfill({ status: 422, body: "{}" });
      }
      return json(route, {
        source: {
          id: "ingest_gateway_source",
          name: "my-agent",
          allowed_service_names: ["my-agent"],
          retention_days: 30,
          enabled: true,
          last_seen_at: null,
        },
        token: "aing_gateway_token",
      });
    }
    return json(route, { items: [], total: 0, limit: 100, offset: 0 });
  });

  await page.goto("/onboarding");
  await page.getByRole("radio", { name: "网关代理（改 base_url 即接入）" }).click();
  await expect(page.getByText("上游 base_url（OpenAI 兼容）")).toBeVisible();
  await page.getByRole("button", { name: "创建并签发 token" }).click();

  await expect(page.getByRole("tab", { name: "OpenAI 客户端" })).toBeVisible();
  await expect(
    page.getByText("/gateway/ingest_gateway_source/v1", { exact: false }),
  ).toBeVisible();
  await page.getByRole("tab", { name: "curl 测试" }).click();
  await expect(
    page.getByText("chat/completions", { exact: false }),
  ).toBeVisible();
});
