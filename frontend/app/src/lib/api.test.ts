import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiClient } from "./api";

describe("ApiClient", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("parses typed engine capabilities", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({
          items: [
            {
              engine_type: "postgres",
              metadata_discovery_supported: true,
              extraction_supported: true,
              artifact_publish_supported: true,
              baseline_refresh_supported: true,
              baseline_publish_supported: true,
              release_ready: true,
            },
          ],
        }),
      }),
    );

    const client = new ApiClient("http://example.internal");
    const response = await client.listEngineCapabilities();

    expect(response.items[0].engine_type).toBe("postgres");
    expect(response.items[0].release_ready).toBe(true);
  });

  it("surfaces backend error messages", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        json: async () => ({ error: "Something failed" }),
      }),
    );

    const client = new ApiClient("http://example.internal");

    await expect(client.listPublishJobs()).rejects.toThrow("Something failed");
  });
});
