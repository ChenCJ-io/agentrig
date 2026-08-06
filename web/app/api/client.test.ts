import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, apiDownload } from "./client";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("apiDownload", () => {
  it("preserves the server filename and binary response", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        new Response("complete export", {
          headers: {
            "Content-Disposition": 'attachment; filename="agentrig-export.json"',
            "Content-Type": "application/json",
          },
        }),
      ),
    );

    const file = await apiDownload("/api/export");

    expect(file.filename).toBe("agentrig-export.json");
    expect(await file.blob.text()).toBe("complete export");
  });

  it("surfaces structured download failures", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        new Response(JSON.stringify({ message: "export exceeds limit" }), {
          status: 400,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );

    await expect(apiDownload("/api/export")).rejects.toEqual(
      expect.objectContaining<ApiError>({
        name: "ApiError",
        message: "export exceeds limit",
        status: 400,
      }),
    );
  });
});
