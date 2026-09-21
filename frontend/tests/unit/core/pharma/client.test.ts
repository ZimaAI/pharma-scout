import { afterEach, expect, rstest, test } from "@rstest/core";

import {
  PharmaAPIError,
  pharmaFetch,
  safeSourceURL,
} from "@/core/pharma/client";

afterEach(() => {
  rstest.unstubAllGlobals();
});

test("workspace writes carry session CSRF, revision and the caller's retry key", async () => {
  const fetchMock = rstest
    .fn()
    .mockResolvedValue(
      new Response(JSON.stringify({ id: "created" }), { status: 200 }),
    );
  rstest.stubGlobal("fetch", fetchMock);
  await pharmaFetch(
    "/workspaces/w/reports/r/publish",
    {
      method: "POST",
      body: { version_id: "v1" },
      revision: 4,
      idempotencyKey: "stable-retry-key",
    },
    "csrf-value",
  );
  const [url, options] = fetchMock.mock.calls[0] as [string, RequestInit];
  const headers = new Headers(options.headers);
  expect(url).toBe("/api/pharma/v1/workspaces/w/reports/r/publish");
  expect(headers.get("X-CSRF-Token")).toBe("csrf-value");
  expect(headers.get("If-Match")).toBe('"4"');
  expect(headers.get("Idempotency-Key")).toBe("stable-retry-key");
  expect(options.credentials).toBe("same-origin");
  expect(options.cache).toBe("no-store");
});

test("version conflicts retain request identifiers without automatically retrying writes", async () => {
  const fetchMock = rstest.fn().mockResolvedValue(
    new Response(
      JSON.stringify({
        error: {
          code: "STALE_VERSION",
          message: "版本已更新",
          details: { current: 2 },
          request_id: "request-123",
        },
      }),
      { status: 409 },
    ),
  );
  rstest.stubGlobal("fetch", fetchMock);
  const failure = await pharmaFetch("/workspaces/w/drugs/d", {
    method: "PATCH",
    body: { display_name: "sample" },
  }).catch((error: unknown) => error);
  expect(failure).toBeInstanceOf(PharmaAPIError);
  expect(failure).toMatchObject({
    status: 409,
    code: "STALE_VERSION",
    requestId: "request-123",
  });
  expect(fetchMock).toHaveBeenCalledTimes(1);
});

test("proxy failures surface a usable error and credentials never leave the API origin", async () => {
  const fetchMock = rstest
    .fn()
    .mockResolvedValue(new Response("gateway offline", { status: 502 }));
  rstest.stubGlobal("fetch", fetchMock);
  await expect(pharmaFetch("/auth/me")).rejects.toMatchObject({
    status: 502,
    code: "HTTP_ERROR",
  });
  await expect(pharmaFetch("//outside.test/collect")).rejects.toThrow(
    "无效的请求路径",
  );
  await expect(pharmaFetch("/../outside")).rejects.toThrow("无效的请求路径");
  expect(fetchMock).toHaveBeenCalledTimes(1);
});

test("source hyperlinks are limited to the official HTTPS origins", () => {
  expect(safeSourceURL("https://clinicaltrials.gov/study/NCT00000001")).toBe(
    "https://clinicaltrials.gov/study/NCT00000001",
  );
  expect(safeSourceURL("https://pubmed.ncbi.nlm.nih.gov/123/")).toBe(
    "https://pubmed.ncbi.nlm.nih.gov/123/",
  );
  for (const url of [
    "javascript:alert(1)",
    "https://clinicaltrials.gov.attacker.test",
    "http://clinicaltrials.gov/study/1",
    "https://pubmed.ncbi.nlm.nih.gov@attacker.test/",
    "malformed",
  ])
    expect(safeSourceURL(url)).toBeUndefined();
});
