import { afterEach, describe, expect, test } from "@rstest/core";
import { cleanup, render, screen } from "@testing-library/react";

import { Badge, DateText, Field } from "@/components/pharma/ui";

afterEach(cleanup);

describe("PharmaScope accessible clinical presentation", () => {
  test("keeps the field label separate from its accessible description", () => {
    render(
      <Field label="研究日期" hint="保留来源提供的日期精度。">
        <input />
      </Field>,
    );
    const input = screen.getByRole("textbox", { name: "研究日期" });
    const description = input.getAttribute("aria-describedby");
    expect(description).toBeTruthy();
    expect(document.getElementById(description!)?.textContent).toBe(
      "保留来源提供的日期精度。",
    );
  });

  test("select values and textarea content never become part of their field names", () => {
    render(
      <>
        <Field label="频率" hint="在指定时区执行">
          <select defaultValue="weekly">
            <option value="daily">每日</option>
            <option value="weekly">每周</option>
          </select>
        </Field>
        <Field label="研究问题">
          <textarea defaultValue="已有研究内容" />
        </Field>
      </>,
    );
    expect(screen.getByRole("combobox", { name: "频率" })).toBeTruthy();
    expect(screen.getByRole("textbox", { name: "研究问题" })).toBeTruthy();
  });

  test("does not invent a day for month precision or turn unknown into a date", () => {
    const view = render(<DateText value={null} />);
    expect(screen.getByText("未知")).toBeTruthy();
    view.rerender(
      <DateText
        value={{
          value: "2026-11",
          precision: "month",
          kind: "estimated",
        }}
      />,
    );
    expect(screen.getByText("2026-11（月精度） · 预计")).toBeTruthy();
    expect(view.container.textContent).not.toContain("2026-11-01");
    view.rerender(
      <DateText
        value={{
          value: null,
          precision: "unknown",
          kind: "actual",
        }}
      />,
    );
    expect(view.container.textContent).toBe("未知");
  });

  test("clinical trial completion stays neutral and distinct from task success", () => {
    const view = render(<Badge status="COMPLETED" />);
    expect(screen.getByText("试验已完成")).toBeTruthy();
    expect(view.container.querySelector(".ph-badge-success")).toBeNull();
    view.rerender(<Badge status="completed" />);
    expect(screen.getByText("已完成")).toBeTruthy();
    expect(view.container.querySelector(".ph-badge-success")).not.toBeNull();
  });
});
