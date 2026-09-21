import { expect, test } from "@playwright/test";

const registration = "浙ICP备2026076087号-1";

for (const route of [
  "/pharma/login",
  "/login",
  "/setup",
  "/workspace",
  "/blog",
  "/en/docs",
  "/zh/docs",
  "/artifacts/view",
  "/page-that-does-not-exist",
]) {
  test(`registration remains visible on ${route}`, async ({ page }) => {
    await page.goto(route);
    const link = page.getByRole("link", { name: registration, exact: true });
    await expect(link).toBeVisible();
    await expect(link).toHaveAttribute("href", "https://beian.miit.gov.cn/");
    await expect(link).toBeInViewport();
    await page.setViewportSize({ width: 390, height: 844 });
    await expect(link).toBeInViewport();
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth),
    ).toBeLessThanOrEqual(390);
  });
}

test("PharmaScount owns its branding and tab icons without replacing DeerFlow", async ({
  page,
}) => {
  await page.goto("/pharma/login");
  await expect(page).toHaveTitle("PharmaScount · 医药研发情报");
  await expect(page.locator(".ph-brand")).toHaveText(
    "PharmaScount医药研发情报",
  );
  await expect(page.locator(".ph-brand img")).toHaveAttribute(
    "src",
    "/pharma/brand/logo.svg",
  );
  await expect(
    page.locator('link[rel="icon"][type="image/svg+xml"]'),
  ).toHaveAttribute("href", "/pharma/brand/logo.svg");
  for (const asset of ["logo.svg", "icon-32.png", "apple-touch-icon.png"]) {
    const response = await page.request.get(`/pharma/brand/${asset}`);
    expect(response.ok()).toBe(true);
    expect(response.headers()["content-type"]).toContain("image/");
  }
  await page.goto("/login");
  await expect(page).toHaveTitle(/DeerFlow/);
  await expect(page.locator('link[rel="icon"][href*="/pharma/"]')).toHaveCount(
    0,
  );
});
