import { afterEach, beforeEach, describe, expect, it, rs } from "@rstest/core";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { useRouter, useSearchParams } from "next/navigation";

rs.mock("next/navigation", () => ({
  useRouter: rs.fn(),
  useSearchParams: rs.fn(),
}));
rs.mock("@/components/pharma/context", () => ({
  usePharma: rs.fn(),
  useResource: rs.fn(),
  useEvidence: rs.fn(),
}));

import {
  useEvidence,
  usePharma,
  useResource,
} from "@/components/pharma/context";
import {
  mergeRunEvents,
  ResearchDetail,
  ResearchNew,
  ReportDetail,
  reviewEligibility,
} from "@/components/pharma/research-pages";
import { PharmaAPIError } from "@/core/pharma/client";
import type {
  Report,
  ReportVersion,
  ResearchRun,
  RunEvent,
} from "@/core/pharma/contracts";

const date = "2026-09-20T09:00:00Z";
const report: Report = {
  id: "report-1",
  workspace_id: "workspace-1",
  created_at: date,
  updated_at: date,
  run_id: "run-1",
  title: "虚构药物观察",
  created_by: "author",
  state: "in_review",
  current_version_id: "version-1",
  published_version_id: null,
};
const version: ReportVersion = {
  id: "version-1",
  workspace_id: "workspace-1",
  created_at: date,
  report_id: report.id,
  version_no: 1,
  content_hash: "a".repeat(64),
  created_by: "author",
  runtime_mode: "replay",
  claim_ids: [],
  content: {
    schema_version: "1.0",
    title: report.title,
    summary: "仅供虚构流程验证",
    scope: {
      drug_ids: ["drug-1"],
      time_range: {
        start: "2026-09-01T00:00:00Z",
        end_exclusive: date,
        timezone: "Asia/Shanghai",
      },
      knowledge_cutoff: date,
    },
    coverage: [
      {
        source: "ctgov",
        status: "partial",
        as_of: date,
        records_count: 1,
        truncated: false,
        limitations: ["这是演示资料"],
      },
    ],
    sections: [
      { heading: "观察摘要", text: "资料需要人工核对。", claim_keys: ["C1"] },
    ],
    claims: [
      {
        claim_key: "C1",
        category: "fact",
        statement: "这是虚构观察。",
        qualifiers: {
          population: null,
          trial_ids: [],
          time_scope: null,
          limitations: [],
        },
        evidence_links: [{ evidence_id: "evidence-1", relation: "supports" }],
      },
    ],
    limitations: ["仅展示工作流程"],
    unanswered_questions: [],
    event_revision_ids: [],
  },
};
const run: ResearchRun = {
  id: "run-1",
  workspace_id: "workspace-1",
  created_at: date,
  updated_at: date,
  created_by: "author",
  question: "检查虚构药物的试验变化与证据",
  status: "running",
  runtime_mode: "replay",
  attempt: 0,
  frozen_request: {
    question: "检查虚构药物的试验变化与证据",
    drug_ids: ["drug-1"],
    time_range: version.content.scope.time_range,
    source_allowlist: ["ctgov"],
  },
  coverage: [],
  usage: {
    model_calls: 0,
    tool_calls: 1,
    input_tokens: null,
    output_tokens: null,
    usage_quality: "unknown",
    estimated_cost: null,
    currency: null,
  },
  event_seq: 0,
  report_id: null,
  stop_reason: null,
};
const emptyPage = { items: [], has_more: false, next_cursor: null };
const request = rs.fn();
const push = rs.fn();
const refetch = rs.fn();
const openEvidence = rs.fn();
let resources: Record<string, unknown>;
let context: ReturnType<typeof usePharma>;

class TestEventSource {
  static instances: TestEventSource[] = [];
  handlers = new Map<string, (event: MessageEvent) => void>();
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  close = rs.fn();
  constructor(readonly url: string) {
    TestEventSource.instances.push(this);
  }
  addEventListener(type: string, callback: (event: MessageEvent) => void) {
    this.handlers.set(type, callback);
  }
  dispatch(event: RunEvent) {
    this.handlers.get(event.type)?.(
      new MessageEvent(event.type, { data: JSON.stringify(event) }),
    );
  }
}

beforeEach(() => {
  request.mockReset().mockResolvedValue({});
  push.mockReset();
  refetch.mockReset().mockResolvedValue({});
  openEvidence.mockReset();
  context = {
    me: {
      user: {
        id: "reviewer",
        email: "reviewer@example.test",
        display_name: "独立审核员",
        is_active: true,
      },
      memberships: [],
      csrf_token: "test-csrf",
    },
    workspace: {
      workspace_id: "workspace-1",
      workspace_name: "虚构工作区",
      role: "reviewer",
      data_mode: "demo",
    },
    workspaceId: "workspace-1",
    config: {
      data_mode: "demo",
      model_configured: false,
      email_enabled: false,
      demo_day: 3,
    },
    request: request as ReturnType<typeof usePharma>["request"],
    refresh: refetch,
  };
  resources = {
    "/drugs?limit=100": {
      ...emptyPage,
      items: [
        {
          id: "drug-1",
          display_name: "虚构药物 PX-001",
          development_code: "PX-001",
        },
      ],
    },
    "/reports/report-1": structuredClone(report),
    "/reports/report-1/versions?limit=100": { ...emptyPage, items: [version] },
    "/reports/report-1/versions/version-1": structuredClone(version),
    "/research/runs/run-1": structuredClone(run),
  };
  rs.mocked(usePharma).mockImplementation(() => context);
  rs.mocked(useEvidence).mockReturnValue(openEvidence);
  rs.mocked(useResource).mockImplementation(
    <T,>(path: string | null) =>
      ({
        data: path ? (resources[path] ?? emptyPage) : undefined,
        error: null,
        isLoading: false,
        isFetching: false,
        refetch,
      }) as unknown as ReturnType<typeof useResource<T>>,
  );
  rs.mocked(useRouter).mockReturnValue({
    push,
    replace: rs.fn(),
  } as unknown as ReturnType<typeof useRouter>);
  rs.mocked(useSearchParams).mockReturnValue(
    new URLSearchParams() as ReturnType<typeof useSearchParams>,
  );
  TestEventSource.instances = [];
  rs.stubGlobal("EventSource", TestEventSource);
});
afterEach(() => {
  cleanup();
  rs.unstubAllGlobals();
});

function event(
  seq: number,
  type: RunEvent["type"] = "tool.completed",
  runId = run.id,
): RunEvent {
  return {
    schema_version: "1.0",
    run_id: runId,
    seq,
    occurred_at: date,
    type,
    payload: { tool: "inspect_evidence" },
  };
}

describe("Pharma research and report boundaries", () => {
  it("orders replayed events, ignores duplicates and foreign runs, and bounds retained frames", () => {
    const first = mergeRunEvents([event(3)], event(1), run.id);
    expect(first.map((item) => item.seq)).toEqual([1, 3]);
    expect(mergeRunEvents(first, event(3), run.id)).toBe(first);
    expect(
      mergeRunEvents(first, event(4, "run.failed", "different-run"), run.id),
    ).toBe(first);
    expect(mergeRunEvents(first, event(-1), run.id)).toBe(first);
    const many = Array.from({ length: 500 }, (_, index) => event(index + 1));
    const bounded = mergeRunEvents(many, event(501), run.id);
    expect(bounded).toHaveLength(500);
    expect(bounded[0]?.seq).toBe(2);
  });

  it("keeps historical clarification replay open for the resumed run", async () => {
    render(<ResearchDetail id="run-1" />);
    const stream = TestEventSource.instances[0]!;
    expect(stream.url).toContain(
      "/workspaces/workspace-1/research/runs/run-1/events",
    );
    act(() => {
      stream.dispatch(event(2, "clarification.required"));
      stream.dispatch(event(3, "tool.completed"));
    });
    expect(stream.close).not.toHaveBeenCalled();
    expect(screen.getByTestId("run-timeline").textContent).toContain(
      "领域工具已完成",
    );
    act(() => stream.dispatch(event(4, "run.completed")));
    expect(stream.close).toHaveBeenCalledTimes(1);
  });

  it("blocks live model execution when deployment has no configured model", () => {
    context.workspace.data_mode = "live";
    context.config = { ...context.config!, data_mode: "live" };
    render(<ResearchNew />);
    expect(screen.getByText(/真实模型将在后续配置/)).not.toBeNull();
    expect(
      screen.getByRole<HTMLButtonElement>("button", { name: "开始研究" })
        .disabled,
    ).toBe(true);
    expect(request).not.toHaveBeenCalled();
  });

  it("validates time bounds and submits server-compatible timezone and budgets once", async () => {
    request.mockResolvedValueOnce({ id: "next-run" });
    render(<ResearchNew />);
    fireEvent.click(screen.getByRole("checkbox", { name: /虚构药物 PX-001/ }));
    fireEvent.change(screen.getByLabelText("开始时间"), {
      target: { value: "2026-09-20T10:00" },
    });
    fireEvent.change(screen.getByLabelText("结束时间（不含）"), {
      target: { value: "2026-09-19T10:00" },
    });
    fireEvent.submit(screen.getByTestId("research-new-form"));
    expect(screen.getByRole("alert").textContent).toContain(
      "结束时间需晚于开始时间",
    );
    expect(request).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText("结束时间（不含）"), {
      target: { value: "2026-09-21T10:00" },
    });
    fireEvent.submit(screen.getByTestId("research-new-form"));
    fireEvent.submit(screen.getByTestId("research-new-form"));
    await waitFor(() =>
      expect(push).toHaveBeenCalledWith("/pharma/research/next-run"),
    );
    expect(request).toHaveBeenCalledTimes(1);
    expect(request).toHaveBeenCalledWith(
      "/research/runs",
      expect.objectContaining({
        method: "POST",
        idempotencyKey: expect.any(String),
        body: expect.objectContaining({
          drug_ids: ["drug-1"],
          time_range: {
            start: "2026-09-20T02:00:00+00:00",
            end_exclusive: "2026-09-21T02:00:00+00:00",
            timezone: "Asia/Shanghai",
          },
          budget: {
            max_tool_calls: 30,
            max_model_calls: 12,
            max_wall_seconds: 600,
            max_records: 200,
          },
        }),
      }),
    );
  });

  it("binds independent approval to the exact displayed version and hash", async () => {
    render(<ReportDetail id="report-1" />);
    fireEvent.change(screen.getByLabelText("审核意见"), {
      target: { value: "已逐条核对引用和范围" },
    });
    fireEvent.click(
      screen.getByRole<HTMLButtonElement>("button", { name: "批准此版本" }),
    );
    await waitFor(() =>
      expect(request).toHaveBeenCalledWith(
        "/reports/report-1/reviews",
        expect.objectContaining({
          method: "POST",
          body: {
            version_id: version.id,
            content_hash: version.content_hash,
            decision: "approve",
            note: "已逐条核对引用和范围",
          },
        }),
      ),
    );
    expect(screen.getByTestId("report-review-panel").textContent).toContain(
      version.content_hash,
    );
  });

  it("disables self-review and review of a stale version", () => {
    context.me.user.id = "author";
    render(<ReportDetail id="report-1" />);
    expect(
      screen.getByRole<HTMLButtonElement>("button", { name: "批准此版本" })
        .disabled,
    ).toBe(true);
    expect(screen.getByText(/不能审核自己的报告/)).not.toBeNull();
    expect(
      reviewEligibility(
        report,
        { ...version, id: "old-version" },
        "reviewer",
        "reviewer",
      ).allowed,
    ).toBe(false);
    expect(reviewEligibility(report, version, "reader", "reader").allowed).toBe(
      false,
    );
  });

  it("preserves edited content after a stale-version rejection and keeps evidence bindings", async () => {
    request.mockRejectedValueOnce(
      new PharmaAPIError(409, "STALE_VERSION", "版本已更新"),
    );
    render(<ReportDetail id="report-1" />);
    fireEvent.click(
      screen.getByRole<HTMLButtonElement>("button", { name: "编辑新版本" }),
    );
    fireEvent.change(screen.getByLabelText<HTMLTextAreaElement>("报告摘要"), {
      target: { value: "尚未保存的修订摘要" },
    });
    fireEvent.change(screen.getByLabelText("修改说明"), {
      target: { value: "核对资料限制" },
    });
    fireEvent.click(
      screen.getByRole<HTMLButtonElement>("button", { name: "保存新版本" }),
    );
    await screen.findByRole("alert");
    expect(screen.getByLabelText<HTMLTextAreaElement>("报告摘要").value).toBe(
      "尚未保存的修订摘要",
    );
    expect(screen.getByRole("alert").textContent).toContain(
      "当前编辑内容仍保留",
    );
    expect(request).toHaveBeenCalledWith(
      "/reports/report-1/versions",
      expect.objectContaining({
        body: {
          base_version_id: version.id,
          edit_note: "核对资料限制",
          content: { ...version.content, summary: "尚未保存的修订摘要" },
        },
      }),
    );
  });

  it("shows only the published report to a reader and opens bound evidence", () => {
    context.workspace.role = "reader";
    resources["/reports/report-1"] = {
      ...report,
      current_version_id: null,
      published_version_id: version.id,
      state: "published",
    };
    render(<ReportDetail id="report-1" />);
    expect(screen.queryByTestId("report-review-panel")).toBeNull();
    expect(screen.getByTestId("report-content").textContent).toContain(
      version.content.summary,
    );
    fireEvent.click(
      screen.getByRole<HTMLButtonElement>("button", { name: "证据 1" }),
    );
    expect(openEvidence).toHaveBeenCalledWith("evidence-1");
    expect(
      screen.getByRole("link", { name: "Markdown" }).getAttribute("href"),
    ).toContain("version_id=version-1");
  });

  it("honors an inbox version link without switching silently to the current draft", () => {
    const delivered = {
      ...version,
      id: "version-previous",
      version_no: 0,
      content_hash: "b".repeat(64),
      content: { ...version.content, summary: "已投递的历史版本摘要" },
    };
    rs.mocked(useSearchParams).mockReturnValue(
      new URLSearchParams("version=version-previous") as ReturnType<
        typeof useSearchParams
      >,
    );
    resources["/reports/report-1/versions/version-previous"] = delivered;
    resources["/reports/report-1/versions?limit=100"] = {
      ...emptyPage,
      items: [version, delivered],
    };
    render(<ReportDetail id="report-1" />);
    expect(screen.getByTestId("report-content").textContent).toContain(
      "已投递的历史版本摘要",
    );
    expect(screen.getByTestId("report-review-panel").textContent).toContain(
      delivered.content_hash,
    );
    expect(
      screen.getByRole("link", { name: "Markdown" }).getAttribute("href"),
    ).toContain("version_id=version-previous");
    expect(
      screen.getByRole<HTMLButtonElement>("button", { name: "批准此版本" })
        .disabled,
    ).toBe(true);
  });

  it("hides editor actions after an author's role becomes reader", () => {
    context.me.user.id = "author";
    context.workspace.role = "reader";
    resources["/reports/report-1"] = {
      ...report,
      current_version_id: null,
      published_version_id: version.id,
      state: "published",
    };
    render(<ReportDetail id="report-1" />);
    expect(screen.queryByRole("button", { name: "编辑新版本" })).toBeNull();
    expect(screen.queryByTestId("report-review-panel")).toBeNull();
  });
});
