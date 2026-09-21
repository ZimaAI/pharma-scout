import { afterEach, describe, expect, rs, test } from "@rstest/core";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";

import { ChangeList, DrugForm } from "@/components/pharma/entity-pages";
import {
  SubscriptionForm,
  subscriptionInput,
} from "@/components/pharma/subscriptions-page";
import type {
  Drug,
  SchedulePreview,
  Subscription,
} from "@/core/pharma/contracts";

afterEach(cleanup);

const drug: Drug = {
  id: "00000000-0000-4000-8000-000000000001",
  workspace_id: "00000000-0000-4000-8000-000000000002",
  created_at: "2026-09-21T00:00:00Z",
  updated_at: "2026-09-21T00:00:00Z",
  display_name: "PX-101 虚构研究对象",
  development_code: "PX-101",
  description: null,
  indications: [],
  targets: [],
  revision: 1,
  archived: false,
};
const subscription: Subscription = {
  id: "00000000-0000-4000-8000-000000000003",
  workspace_id: drug.workspace_id,
  owner_id: "00000000-0000-4000-8000-000000000004",
  created_at: drug.created_at,
  name: "虚构周日报告",
  drug_ids: [drug.id],
  source_allowlist: ["ctgov", "pubmed"],
  channels: ["in_app"],
  enabled: true,
  revision: 7,
  schedule: {
    frequency: "weekly",
    weekday: 7,
    local_time: "09:00",
    timezone: "Asia/Shanghai",
  },
  next_run_at: null,
  last_outcome: null,
};
const emptyPreview = async (): Promise<SchedulePreview> => ({
  occurrences: [],
});

describe("PharmaScount entity forms", () => {
  test("saves explicit research tags and leaves unknown optional fields null", async () => {
    const save = rs.fn(async () => undefined);
    render(<DrugForm busy={false} onCancel={() => undefined} onSave={save} />);
    fireEvent.change(screen.getByLabelText("对象名称 *"), {
      target: { value: "  Synthetic PX  " },
    });
    fireEvent.change(screen.getByLabelText(/^适应证研究标签/), {
      target: { value: "研究A，研究B,研究A" },
    });
    fireEvent.click(screen.getByRole("button", { name: "保存档案" }));
    await waitFor(() =>
      expect(save).toHaveBeenCalledWith({
        display_name: "Synthetic PX",
        development_code: null,
        description: null,
        indications: ["研究A", "研究B"],
        targets: [],
      }),
    );
  });

  test("keeps entered fields when a revision conflict is shown", () => {
    const view = render(
      <DrugForm
        initial={drug}
        busy={false}
        onCancel={() => undefined}
        onSave={async () => undefined}
      />,
    );
    fireEvent.change(screen.getByLabelText("对象名称 *"), {
      target: { value: "尚未保存的更正" },
    });
    view.rerender(
      <DrugForm
        initial={drug}
        busy={false}
        onCancel={() => undefined}
        onSave={async () => undefined}
        error={new Error("档案已被更新，请核对版本")}
      />,
    );
    expect(screen.getByLabelText<HTMLInputElement>("对象名称 *").value).toBe(
      "尚未保存的更正",
    );
    expect(screen.getByRole("alert").textContent).toContain("档案已被更新");
  });

  test("field removal remains distinct from explicit null in a version comparison", () => {
    render(
      <ChangeList
        changes={[
          {
            path: "/enrollment",
            type: "removed",
            before: { count: 120, type: "estimated" },
            after: null,
          },
          {
            path: "/sponsor",
            type: "changed",
            before: "Synthetic sponsor",
            after: null,
          },
        ]}
      />,
    );
    expect(screen.getByText("本次已移除此字段")).toBeTruthy();
    expect(screen.getByText("null")).toBeTruthy();
    expect(screen.getByText(/"count": 120/)).toBeTruthy();
  });
});

describe("PharmaScount subscription form", () => {
  test("preserves ISO Sunday and clears weekday only when switching to daily", async () => {
    const save = rs.fn(async () => undefined);
    render(
      <SubscriptionForm
        initial={subscription}
        drugs={[drug]}
        emailEnabled={false}
        busy={false}
        onCancel={() => undefined}
        onPreview={emptyPreview}
        onSave={save}
      />,
    );
    expect(screen.getByLabelText<HTMLSelectElement>("星期").value).toBe("7");
    fireEvent.click(screen.getByRole("button", { name: "保存订阅" }));
    await waitFor(() =>
      expect(save).toHaveBeenCalledWith(subscriptionInput(subscription)),
    );
    fireEvent.change(screen.getByLabelText("频率"), {
      target: { value: "daily" },
    });
    expect(screen.queryByLabelText("星期")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "保存订阅" }));
    await waitFor(() =>
      expect(save).toHaveBeenLastCalledWith({
        ...subscriptionInput(subscription),
        schedule: {
          ...subscription.schedule,
          frequency: "daily",
          weekday: null,
        },
      }),
    );
  });

  test("disables unavailable email and limits selected objects to five", () => {
    const drugs = Array.from({ length: 6 }, (_, index) => ({
      ...drug,
      id: `synthetic-${index}`,
      display_name: `虚构对象 ${index + 1}`,
    }));
    render(
      <SubscriptionForm
        drugs={drugs}
        emailEnabled={false}
        busy={false}
        onCancel={() => undefined}
        onPreview={emptyPreview}
        onSave={async () => undefined}
      />,
    );
    expect(screen.getByLabelText<HTMLInputElement>("邮件").disabled).toBe(true);
    for (let index = 1; index <= 5; index++)
      fireEvent.click(screen.getByLabelText(new RegExp(`虚构对象 ${index}`)));
    expect(screen.getByLabelText<HTMLInputElement>(/虚构对象 6/).disabled).toBe(
      true,
    );
  });

  test("never displays an old preview as the current schedule after editing", async () => {
    const preview = rs.fn(
      async (): Promise<SchedulePreview> => ({
        occurrences: [
          {
            utc: "2026-11-01T08:30:00Z",
            local: "2026-11-01T01:30:00-07:00",
            dst_adjusted: false,
          },
        ],
      }),
    );
    render(
      <SubscriptionForm
        initial={subscription}
        drugs={[drug]}
        emailEnabled={false}
        busy={false}
        onCancel={() => undefined}
        onPreview={preview}
        onSave={async () => undefined}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "预览未来 5 次" }));
    await waitFor(() =>
      expect(screen.getByText("2026-11-01 01:30:00-07:00")).toBeTruthy(),
    );
    fireEvent.change(screen.getByLabelText("当地时间"), {
      target: { value: "10:30" },
    });
    expect(screen.queryByText("2026-11-01 01:30:00-07:00")).toBeNull();
    expect(screen.getByText("排程已修改，请重新预览。")).toBeTruthy();
  });

  test("sends only editable fields when pausing an existing subscription", () => {
    const input = subscriptionInput(subscription, false);
    expect(input.enabled).toBe(false);
    expect(input).not.toHaveProperty("owner_id");
    expect(input).not.toHaveProperty("workspace_id");
    expect(input).not.toHaveProperty("revision");
    expect(input.schedule.weekday).toBe(7);
  });
});
