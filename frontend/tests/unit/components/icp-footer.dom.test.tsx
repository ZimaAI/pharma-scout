import { afterEach, expect, test } from "@rstest/core";
import { cleanup, render, screen } from "@testing-library/react";

import { IcpFooter } from "@/components/icp-footer";

afterEach(cleanup);

test("provides the registration link with a safe external destination", () => {
  render(<IcpFooter />);
  const link = screen.getByRole("link", { name: "浙ICP备2026076087号-1" });
  expect(link.getAttribute("href")).toBe("https://beian.miit.gov.cn/");
  expect(link.getAttribute("target")).toBe("_blank");
  expect(link.getAttribute("rel")).toBe("noopener noreferrer");
  expect(screen.getByRole("contentinfo", { name: "网站备案" })).toBeTruthy();
});
