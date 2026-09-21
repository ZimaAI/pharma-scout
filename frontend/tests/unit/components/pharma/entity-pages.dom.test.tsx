import {
  afterEach,
  beforeEach,
  describe,
  expect,
  rs,
  test,
} from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

import { usePharma, useResource } from "@/components/pharma/context";
import {
  PublicationDetail,
  TrialDetail,
  TrialsPage,
} from "@/components/pharma/entity-pages";
import { SubscriptionsPage } from "@/components/pharma/subscriptions-page";
import type { Publication, Trial } from "@/core/pharma/contracts";

rs.mock("next/navigation", () => ({
  useRouter: rs.fn(),
  usePathname: rs.fn(),
  useSearchParams: rs.fn(),
}));
rs.mock("@/components/pharma/context", () => ({
  usePharma: rs.fn(),
  useResource: rs.fn(),
  useEvidence: rs.fn(),
}));

const emptyPage = { items: [], has_more: false, next_cursor: null };
let resources: Record<string, unknown>;
const base = {
  id: "record-1",
  workspace_id: "workspace-1",
  created_at: "2026-09-21T00:00:00Z",
  updated_at: "2026-09-21T00:00:00Z",
  current_snapshot_id: null,
  current_observation_id: null,
  canonical_url: "https://untrusted.example.invalid/redirect",
  is_demo: false,
};
const trial: Trial = {
  ...base,
  source: "ctgov",
  external_id: "NCT12345678",
  kind: "trial",
  current_projection: {
    title: "Synthetic trial only",
    raw_status: "COMPLETED",
    status: "COMPLETED",
    phases: [],
    conditions: [],
    sponsor: null,
    enrollment: null,
    has_results: null,
    source_updated: {
      value: null,
      precision: "unknown",
      kind: "unknown",
    },
    primary_outcomes: [],
  },
};
const publication: Publication = {
  ...base,
  source: "pubmed",
  external_id: "12345678",
  kind: "publication",
  current_projection: {
    title: "Synthetic publication only",
    authors: [],
    journal: null,
    doi: null,
    pmid: "12345678",
    publication_date: {
      value: null,
      precision: "unknown",
      kind: "unknown",
    },
    abstract_text: null,
    publication_types: [],
    correction_relations: [],
  },
};

beforeEach(() => {
  rs.clearAllMocks();
  resources = {
    "/trials/record-1": trial,
    "/publications/record-1": publication,
  };
  rs.mocked(usePharma).mockReturnValue({
    workspace: { role: "reader" },
    request: rs.fn(),
    refresh: rs.fn(),
  } as unknown as ReturnType<typeof usePharma>);
  rs.mocked(useResource).mockImplementation(
    <T,>(path: string | null) =>
      ({
        data: path ? (resources[path] ?? emptyPage) : undefined,
        isPending: false,
        isFetching: false,
        error: null,
        refetch: rs.fn(),
      }) as unknown as ReturnType<typeof useResource<T>>,
  );
  rs.mocked(useSearchParams).mockReturnValue(
    new URLSearchParams() as ReturnType<typeof useSearchParams>,
  );
  rs.mocked(usePathname).mockReturnValue("/pharma/trials");
  rs.mocked(useRouter).mockReturnValue({
    replace: rs.fn(),
  } as unknown as ReturnType<typeof useRouter>);
});
afterEach(cleanup);

describe("PharmaScope entity and subscription integration boundaries", () => {
  test("reader sees an explicit subscription permission state without a protected query", () => {
    render(
      <QueryClientProvider client={new QueryClient()}>
        <SubscriptionsPage />
      </QueryClientProvider>,
    );
    expect(screen.getByText("当前角色为只读成员")).toBeTruthy();
    expect(
      screen.getByRole("link", { name: "查看已发布报告" }).getAttribute("href"),
    ).toBe("/pharma/reports");
    expect(
      rs.mocked(useResource).mock.calls.every(([path]) => path === null),
    ).toBe(true);
    expect(screen.queryByRole("alert")).toBeNull();
  });

  test("preserves backend filter names and treats an empty result filter as filtered data", () => {
    rs.mocked(useSearchParams).mockReturnValue(
      new URLSearchParams(
        "has_results=false&observed_since=2026-09-20T00%3A00%3A00Z",
      ) as ReturnType<typeof useSearchParams>,
    );
    render(<TrialsPage />);
    expect(screen.getByText("没有符合筛选条件的资料")).toBeTruthy();
    const path = rs.mocked(useResource).mock.calls[0]?.[0];
    const params = new URLSearchParams(path?.split("?")[1]);
    expect(params.get("has_results")).toBe("false");
    expect(params.get("observed_since")).toBe("2026-09-20T00:00:00Z");
  });

  test("builds the official trial URL from a validated ID instead of an arbitrary stored URL", () => {
    render(<TrialDetail id="record-1" />);
    const link = screen.getByRole("link", { name: "查看官方来源" });
    expect(link.getAttribute("href")).toBe(
      "https://clinicaltrials.gov/study/NCT12345678",
    );
    expect(link.getAttribute("rel")).toContain("noopener");
  });

  test("never presents a DEMO trial as an official source link", () => {
    resources["/trials/record-1"] = { ...trial, is_demo: true };
    render(<TrialDetail id="record-1" />);
    expect(screen.queryByRole("link", { name: "查看官方来源" })).toBeNull();
    expect(screen.getByText("虚构演示资料 · 无官方链接")).toBeTruthy();
  });

  test("rejects PubMed identifiers outside the adapter's supported range", () => {
    resources["/publications/record-1"] = {
      ...publication,
      external_id: "012345678",
    };
    render(<PublicationDetail id="record-1" />);
    expect(screen.queryByRole("link", { name: "查看官方来源" })).toBeNull();
    expect(screen.getByText("来源标识无法生成官方链接")).toBeTruthy();
  });
});
