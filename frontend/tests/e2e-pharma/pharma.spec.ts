import { randomUUID } from "node:crypto";
import { mkdirSync, readFileSync } from "node:fs";
import path from "node:path";

import {
  expect,
  test,
  type APIRequestContext,
  type BrowserContext,
  type Page,
} from "@playwright/test";
import { z } from "zod";

const API = "/api/pharma/v1";
const Credential = z.object({ email: z.string(), password: z.string() });
const Account = Credential.extend({
  role: z.string(),
  workspace_id: z.string(),
});
const Session = z.object({
  csrf_token: z.string().min(1),
  user: z.object({ id: z.string() }),
  memberships: z.array(
    z.object({
      workspace_id: z.string(),
      workspace_name: z.string(),
      data_mode: z.enum(["demo", "live"]),
      role: z.string(),
    }),
  ),
});
const Configuration = z.object({
  data_mode: z.enum(["demo", "live"]),
  model_configured: z.boolean(),
});
const Run = z.object({
  id: z.string(),
  status: z.string(),
  runtime_mode: z.string(),
  report_id: z.string().nullable(),
});
const Report = z.object({
  id: z.string(),
  state: z.string(),
  current_version_id: z.string(),
  published_version_id: z.string().nullable(),
});
const Version = z.object({ id: z.string(), content_hash: z.string() });
const Inbox = z.object({
  items: z.array(z.object({ id: z.string(), report_id: z.string() })),
});
const EntityPage = z.object({ items: z.array(z.object({ id: z.string() })) });
const Subscription = z.object({
  id: z.string(),
  revision: z.number(),
  name: z.string(),
  drug_ids: z.array(z.string()),
  source_allowlist: z.array(z.string()),
  schedule: z.unknown(),
  channels: z.array(z.string()),
  enabled: z.boolean(),
});
type Credentials = z.infer<typeof Credential>;
type AuthSession = z.infer<typeof Session>;

function privateJson(file: string): unknown {
  try {
    return JSON.parse(readFileSync(file, "utf8")) as unknown;
  } catch {
    throw new Error(
      "Private Pharma E2E credentials are unavailable. See docs/pharma-deployment-handoff.md.",
    );
  }
}

function administrator(): Credentials {
  return Credential.parse(
    privateJson(
      process.env.PHARMA_E2E_ADMIN_FILE ??
        path.resolve("../.deer-flow/deployment/admin-credentials.json"),
    ),
  );
}

function roleAccount(role: "analyst" | "reviewer"): Credentials {
  const accounts = z
    .array(Account)
    .parse(
      privateJson(
        process.env.PHARMA_E2E_ACCOUNTS_FILE ??
          path.resolve("../.deer-flow/pharma/accounts.json"),
      ),
    );
  const account = accounts.find((item) => item.role === role);
  if (!account || account.password === "unchanged") {
    throw new Error(`A usable independent ${role} test account is required.`);
  }
  return Credential.parse(account);
}

async function apiLogin(
  context: BrowserContext,
  credentials: Credentials,
): Promise<AuthSession> {
  // Deliberately do not include response bodies or credentials in assertions.
  const response = await context.request.post(`${API}/auth/login`, {
    data: credentials,
  });
  expect(response.status(), "Real Pharma authentication must succeed").toBe(
    200,
  );
  return Session.parse(await response.json());
}

function demoMembership(session: AuthSession) {
  const membership = session.memberships.find(
    (item) => item.data_mode === "demo",
  );
  if (!membership) {
    throw new Error(
      "A seeded DEMO workspace is required; live data is never reset.",
    );
  }
  return membership;
}

async function requireDemo(request: APIRequestContext, workspaceId: string) {
  const response = await request.get(
    `${API}/workspaces/${workspaceId}/configuration`,
  );
  expect(response.status()).toBe(200);
  const configuration = Configuration.parse(await response.json());
  expect(configuration.data_mode, "Mutations are limited to DEMO").toBe("demo");
}

async function selectWorkspace(page: Page, workspaceId: string) {
  const selector = page.getByRole("combobox", { name: "工作区", exact: true });
  await expect(selector).toBeVisible();
  await selector.selectOption(workspaceId);
  await expect(selector).toHaveValue(workspaceId);
}

async function openDemo(
  context: BrowserContext,
  page: Page,
  credentials: Credentials = administrator(),
) {
  const session = await apiLogin(context, credentials);
  const membership = demoMembership(session);
  await requireDemo(context.request, membership.workspace_id);
  await page.goto("/pharma/dashboard", { waitUntil: "domcontentloaded" });
  await selectWorkspace(page, membership.workspace_id);
  await expect(page.getByRole("main")).toBeVisible();
  return { session, membership };
}

async function noDocumentOverflow(page: Page) {
  await expect
    .poll(async () =>
      page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth + 1,
      ),
    )
    .toBe(true);
}

async function screenshot(page: Page, filename: string) {
  const directory = path.resolve("../.deer-flow/pharma/e2e/screenshots");
  mkdirSync(directory, { recursive: true, mode: 0o700 });
  await expect(page.locator(".ph-loading")).toHaveCount(0);
  await page.screenshot({
    path: path.join(directory, filename),
    fullPage: true,
    animations: "disabled",
    // Account identifiers are private even though the research data is synthetic.
    mask: [
      page.locator('input[type="email"]'),
      page.locator('[data-testid="pharma-account"]'),
    ],
  });
}

test("real login selects the demo workspace without publishing credentials", async ({
  page,
  context,
}) => {
  await page.goto("/pharma/dashboard", { waitUntil: "domcontentloaded" });
  await expect(page.getByLabel("邮箱", { exact: true })).toBeVisible();
  await expect(page.getByLabel("密码", { exact: true })).toBeVisible();
  const credentials = administrator();
  try {
    await page.getByLabel("邮箱", { exact: true }).fill(credentials.email);
    await page.getByLabel("密码", { exact: true }).fill(credentials.password);
  } catch {
    throw new Error("Could not fill the private login form.");
  }
  await page.getByRole("button", { name: "登录工作台", exact: true }).click();
  await expect(page.getByRole("main")).toBeVisible();
  const response = await context.request.get(`${API}/auth/me`);
  expect(response.status()).toBe(200);
  const membership = demoMembership(Session.parse(await response.json()));
  await selectWorkspace(page, membership.workspace_id);
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await noDocumentOverflow(page);
});

test("all authorized product routes read the real API", async ({
  context,
  page,
}) => {
  test.setTimeout(60_000);
  const { membership } = await openDemo(context, page);
  const clientErrors: string[] = [];
  page.on("pageerror", (error) => clientErrors.push(error.name));
  for (const route of [
    "dashboard",
    "drugs",
    "trials",
    "literature",
    "events",
    "research",
    "reports",
    "subscriptions",
    "inbox",
    "review",
    "settings",
  ]) {
    await page.goto(`/pharma/${route}`, { waitUntil: "domcontentloaded" });
    await expect(page.getByRole("main")).toBeVisible();
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await expect(page.locator(".ph-loading")).toHaveCount(0);
    await expect(page.getByText("404", { exact: true })).toHaveCount(0);
    await noDocumentOverflow(page);
  }
  for (const [apiRoute, pageRoute] of [
    ["drugs", "drugs"],
    ["trials", "trials"],
    ["publications", "literature"],
    ["events", "events"],
  ]) {
    const response = await context.request.get(
      `${API}/workspaces/${membership.workspace_id}/${apiRoute}`,
    );
    expect(response.status()).toBe(200);
    const entity = EntityPage.parse(await response.json()).items[0];
    if (!entity && apiRoute === "publications") {
      // The deployment intentionally starts at D3; the first fictional
      // publication is observed on D4 and must not be preloaded early.
      test.info().annotations.push({
        type: "fixture",
        description: "D3 literature is empty; publication detail requires D4.",
      });
      continue;
    }
    expect(entity, `Seeded ${apiRoute} detail is required`).toBeDefined();
    await page.goto(`/pharma/${pageRoute}/${entity!.id}`, {
      waitUntil: "domcontentloaded",
    });
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await expect(page.locator(".ph-loading")).toHaveCount(0);
    await noDocumentOverflow(page);
  }
  expect(clientErrors).toEqual([]);
});

test("live workspace keeps its source mode and honest missing-model state", async ({
  context,
  page,
}) => {
  const session = await apiLogin(context, administrator());
  const live = session.memberships.find((item) => item.data_mode === "live");
  expect(
    live,
    "Deployment must retain a separate LIVE workspace",
  ).toBeDefined();
  await page.goto("/pharma/dashboard", { waitUntil: "domcontentloaded" });
  await selectWorkspace(page, live!.workspace_id);
  const response = await context.request.get(
    `${API}/workspaces/${live!.workspace_id}/configuration`,
  );
  expect(response.status()).toBe(200);
  const configuration = Configuration.parse(await response.json());
  expect(configuration.data_mode).toBe("live");
  if (!configuration.model_configured) {
    await expect(
      page.getByText("研究模型待配置", { exact: true }),
    ).toBeVisible();
    await page.goto("/pharma/research/new", { waitUntil: "domcontentloaded" });
    await expect(
      page.getByRole("button", { name: "开始研究", exact: true }),
    ).toBeDisabled();
  }
});

test("subscription schedule previews real occurrences and can be paused", async ({
  context,
  page,
}) => {
  const { session, membership } = await openDemo(
    context,
    page,
    roleAccount("analyst"),
  );
  const endpoint = `${API}/workspaces/${membership.workspace_id}/subscriptions`;
  const name = `浏览器验收订阅 ${randomUUID().slice(0, 8)}`;
  let created: z.infer<typeof Subscription> | undefined;
  try {
    await page.goto("/pharma/subscriptions", { waitUntil: "domcontentloaded" });
    await page.getByRole("button", { name: "建立订阅", exact: true }).click();
    await page.getByLabel("订阅名称 *", { exact: true }).fill(name);
    await page.getByRole("checkbox", { name: /PX-101/ }).check();
    await page.getByRole("combobox", { name: /^频率/ }).selectOption("weekly");
    await page.getByRole("combobox", { name: /^星期/ }).selectOption("7");
    await page.getByLabel("当地时间", { exact: true }).fill("23:59");
    await page.getByLabel(/^IANA 时区/).fill("Asia/Shanghai");
    await page
      .getByRole("checkbox", { name: "启用后续定时研究", exact: true })
      .uncheck();
    await page.getByRole("checkbox", { name: "站内通知", exact: true }).check();
    await page
      .getByRole("button", { name: "预览未来 5 次", exact: true })
      .click();
    await expect(page.locator("main form ol > li")).toHaveCount(5);
    await page.getByRole("button", { name: "保存订阅", exact: true }).click();
    const row = page.getByRole("row").filter({ hasText: name });
    await expect(row).toBeVisible();
    const response = await context.request.get(endpoint);
    created = z
      .object({ items: z.array(Subscription) })
      .parse(await response.json())
      .items.find((item) => item.name === name);
    expect(created).toBeDefined();
    expect(created!.enabled).toBe(false);
    expect(created!.channels).toEqual(["in_app"]);
    await row.getByRole("button", { name: "恢复", exact: true }).click();
    await expect(row.getByText("已启用", { exact: true })).toBeVisible();
    await row.getByRole("button", { name: "暂停", exact: true }).click();
    await expect(row.getByText("已暂停", { exact: true })).toBeVisible();
    const saved = await context.request.get(`${endpoint}/${created!.id}`);
    expect(Subscription.parse(await saved.json()).enabled).toBe(false);
  } finally {
    if (created) {
      const response = await context.request.get(`${endpoint}/${created.id}`);
      const current = Subscription.parse(await response.json());
      if (current.enabled) {
        const { id, revision, ...input } = current;
        const cleanup = await context.request.patch(`${endpoint}/${id}`, {
          headers: {
            "X-CSRF-Token": session.csrf_token,
            "If-Match": `"${revision}"`,
          },
          data: { ...input, enabled: false },
        });
        expect(cleanup.status(), "Test subscription must finish paused").toBe(
          200,
        );
      }
    }
  }
});

for (const viewport of [
  { width: 1440, height: 900 },
  { width: 1024, height: 768 },
  { width: 390, height: 844 },
]) {
  test(`demo layouts fit ${viewport.width}×${viewport.height}`, async ({
    context,
    page,
  }) => {
    await page.setViewportSize(viewport);
    await openDemo(context, page);
    if (viewport.width < 768) {
      const menuButton = page.getByRole("button", {
        name: "打开导航",
        exact: true,
      });
      await menuButton.click();
      const menu = page.getByRole("dialog", { name: "工作台导航" });
      await expect(menu).toBeVisible();
      await page.keyboard.press("Escape");
      await expect(menu).toHaveCount(0);
      await expect(menuButton).toBeFocused();
      await menuButton.click();
      await menu.getByRole("link", { name: "药物档案", exact: true }).click();
      await expect(page).toHaveURL(/\/pharma\/drugs$/);
      await expect(menu).toHaveCount(0);
    }
    for (const route of ["dashboard", "drugs", "trials", "reports"]) {
      await page.goto(`/pharma/${route}`, { waitUntil: "domcontentloaded" });
      await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
      await noDocumentOverflow(page);
      await screenshot(
        page,
        `${route}-${viewport.width}x${viewport.height}.png`,
      );
    }
  });
}

test("analyst replay → independent review → publication → in-app delivery", async ({
  browser,
  context,
  page,
}) => {
  test.setTimeout(90_000);
  const { membership } = await openDemo(context, page, roleAccount("analyst"));
  const workspace = `${API}/workspaces/${membership.workspace_id}`;
  const reviewerContext = await browser.newContext({
    baseURL: new URL(page.url()).origin,
    locale: "zh-CN",
    timezoneId: "Asia/Shanghai",
  });
  try {
    await page.goto("/pharma/research/new", { waitUntil: "domcontentloaded" });
    await page
      .getByRole("textbox", { name: /^研究问题/ })
      .fill(
        `浏览器验收 ${randomUUID().slice(0, 8)}：核对 PX-101 公开试验注册记录变化及证据。`,
      );
    await page.getByRole("checkbox", { name: /PX-101/ }).check();
    await page.getByLabel("开始时间", { exact: true }).fill("2026-09-14T08:00");
    await page
      .getByLabel("结束时间（不含）", { exact: true })
      .fill("2026-09-21T08:00");
    await page.getByRole("button", { name: "开始研究", exact: true }).click();
    await expect(page).toHaveURL(/\/pharma\/research\/[0-9a-f-]{36}$/);
    const runId = new URL(page.url()).pathname.split("/").at(-1)!;
    const reportLink = page.getByRole("link", {
      name: "打开研究报告",
      exact: true,
    });
    await expect(reportLink).toBeVisible({ timeout: 90_000 });
    const runResponse = await context.request.get(
      `${workspace}/research/runs/${runId}`,
    );
    expect(runResponse.status()).toBe(200);
    const run = Run.parse(await runResponse.json());
    expect(run.status).toBe("completed");
    expect(run.runtime_mode).toBe("replay");
    expect(run.report_id).toBeTruthy();
    await reportLink.click();
    await expect(page.getByTestId("report-content")).toBeVisible();
    const citation = page
      .getByTestId("report-content")
      .getByRole("button", { name: /证据/ })
      .first();
    await citation.click();
    await expect(page.getByRole("dialog", { name: "证据溯源" })).toBeVisible();
    await expect(page.locator(".ph-evidence-drawer .ph-quote")).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(page.getByRole("dialog", { name: "证据溯源" })).toHaveCount(0);
    await expect(citation).toBeFocused();
    const reportUrl = `/pharma/reports/${run.report_id!}`;
    const reportResponse = await context.request.get(
      `${workspace}/reports/${run.report_id!}`,
    );
    const report = Report.parse(await reportResponse.json());
    const versionResponse = await context.request.get(
      `${workspace}/reports/${report.id}/versions/${report.current_version_id}`,
    );
    const version = Version.parse(await versionResponse.json());
    await page.getByRole("button", { name: "提交审核", exact: true }).click();
    await expect
      .poll(async () => {
        const response = await context.request.get(
          `${workspace}/reports/${report.id}`,
        );
        return Report.parse(await response.json()).state;
      })
      .toBe("in_review");

    const reviewerPage = await reviewerContext.newPage();
    const reviewer = await openDemo(
      reviewerContext,
      reviewerPage,
      roleAccount("reviewer"),
    );
    expect(reviewer.membership.workspace_id).toBe(membership.workspace_id);
    await reviewerPage.goto(reportUrl, { waitUntil: "domcontentloaded" });
    await reviewerPage
      .getByRole("textbox", { name: /^审核意见/ })
      .fill(
        "独立浏览器验收：已核对指定版本、证据与演示范围，保持临床研究边界。",
      );
    await reviewerPage
      .getByRole("button", { name: "批准此版本", exact: true })
      .click();
    await expect
      .poll(async () => {
        const response = await context.request.get(
          `${workspace}/reports/${report.id}`,
        );
        return Report.parse(await response.json()).state;
      })
      .toBe("approved");

    await page.reload();
    await page.getByRole("button", { name: "发布此版本", exact: true }).click();
    await expect
      .poll(async () => {
        const response = await context.request.get(
          `${workspace}/reports/${report.id}`,
        );
        return Report.parse(await response.json()).published_version_id;
      })
      .toBe(version.id);
    const immutable = await context.request.get(
      `${workspace}/reports/${report.id}/versions/${version.id}`,
    );
    expect(Version.parse(await immutable.json()).content_hash).toBe(
      version.content_hash,
    );
    for (const format of ["JSON", "Markdown"]) {
      const downloadPromise = page.waitForEvent("download");
      await page.getByRole("link", { name: format, exact: true }).click();
      const download = await downloadPromise;
      expect(await download.failure()).toBeNull();
      const file = await download.path();
      expect(file).toBeTruthy();
      const content = readFileSync(file, "utf8");
      if (format === "JSON") {
        expect(Version.parse(JSON.parse(content)).content_hash).toBe(
          version.content_hash,
        );
      } else {
        expect(content).toContain(version.content_hash);
        expect(content).toContain("DEMO");
      }
    }
    for (const viewport of [
      { width: 1440, height: 900 },
      { width: 1024, height: 768 },
      { width: 390, height: 844 },
    ]) {
      await page.setViewportSize(viewport);
      await noDocumentOverflow(page);
      await screenshot(
        page,
        `published-report-${viewport.width}x${viewport.height}.png`,
      );
      await citation.click();
      const drawer = page.getByRole("dialog", { name: "证据溯源" });
      await expect(drawer).toBeVisible();
      const bounds = await drawer.boundingBox();
      expect(bounds).not.toBeNull();
      expect(bounds!.width).toBeLessThanOrEqual(viewport.width + 1);
      await screenshot(
        page,
        `evidence-drawer-${viewport.width}x${viewport.height}.png`,
      );
      await page.keyboard.press("Escape");
      await expect(drawer).toHaveCount(0);
      await expect(citation).toBeFocused();
    }

    await expect
      .poll(
        async () => {
          const response = await context.request.get(`${workspace}/inbox`);
          return Inbox.parse(await response.json()).items.some(
            (item) => item.report_id === report.id,
          );
        },
        { timeout: 30_000 },
      )
      .toBe(true);
    await page.goto("/pharma/inbox", { waitUntil: "domcontentloaded" });
    await expect(
      page.locator(
        `main a[href="/pharma/reports/${report.id}?version=${version.id}"]`,
      ),
    ).toBeVisible();
  } finally {
    await reviewerContext.close();
  }
});
