"use client";

import {
  ArrowLeft,
  ArrowRight,
  Check,
  ClipboardCheck,
  Download,
  FileText,
  FlaskConical,
  Loader2,
  Plus,
  RefreshCw,
  ShieldCheck,
  Square,
  Undo2,
} from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useRef, useState, type FormEvent } from "react";

import {
  type Alias,
  type ClaimPage,
  type DrugPage,
  type EntityLink,
  type Report,
  type ReportNoticePage,
  type ReportVersion,
  type ReportVersionPage,
  type ResearchInput,
  type ResearchOutput,
  type ResearchRun,
  type RunEvent,
  type RunStatus,
  type Source,
  type ToolCallPage,
} from "@/core/pharma/contracts";
import {
  utcToZonedLocalInput,
  validZonedLocalToUtcIso,
} from "@/core/scheduled-tasks/cron";

import { usePharma, useResource } from "./context";
import {
  Badge,
  Coverage,
  Empty,
  ErrorPanel,
  EvidenceButton,
  Field,
  Loading,
  PageHeader,
  Panel,
  Timestamp,
} from "./ui";

type Collection<T> = {
  items: T[];
  next_cursor: string | null;
  has_more: boolean;
};
const RUN_FILTERS: Array<{ value: RunStatus; label: string }> = [
  { value: "queued", label: "排队中" },
  { value: "running", label: "研究中" },
  { value: "awaiting_input", label: "等待澄清" },
  { value: "completed", label: "已完成" },
  { value: "partial", label: "部分完成" },
  { value: "failed", label: "失败" },
  { value: "cancelled", label: "已取消" },
  { value: "recovery_required", label: "需要重试" },
];
const TERMINAL = new Set([
  "completed",
  "partial",
  "failed",
  "cancelled",
  "recovery_required",
  "awaiting_input",
]);
const EVENT_LABELS: Record<string, string> = {
  "run.queued": "研究已加入队列",
  "run.started": "开始研究",
  "plan.updated": "正在核对研究资料",
  "tool.started": "开始调用领域工具",
  "tool.completed": "领域工具已完成",
  "tool.failed": "领域工具未完成",
  "evidence.added": "已获取可核对证据",
  "clarification.required": "需要补充研究范围",
  "report.ready": "研究草稿已生成",
  "run.partial": "研究部分完成",
  "run.completed": "研究已完成",
  "run.failed": "研究未完成",
  "run.cancel_requested": "已请求取消",
  "run.cancelled": "研究已取消",
  "run.recovery_required": "执行中断，需要新建尝试",
};
const TOOL_LABELS: Record<string, string> = {
  resolve_drug: "核对药物身份",
  search_trials: "检索试验记录",
  search_publications: "检索研究文献",
  read_source_snapshot: "读取版本快照",
  compare_trial_observations: "比较前后观察",
  search_workspace_evidence: "检索工作区证据",
  inspect_evidence: "核对引用原文",
  request_clarification: "确认研究范围",
  submit_research_draft: "校验并提交草稿",
};
const STOP_LABELS: Record<string, string> = {
  answered: "本次研究已完成，请结合来源覆盖与资料限制阅读。",
  no_verified_change:
    "所覆盖资料中未发现可验证变化，不代表其他来源不存在进展。",
  insufficient_evidence: "资料不足，部分问题仍需补充证据。",
  source_unavailable: "来源不可用，请检查覆盖状态。",
  budget_exhausted: "已达到本次研究预算，未完成的问题需要后续研究。",
  user_cancelled: "任务已取消。",
  runtime_error: "研究未完成。请检查模型配置及工具记录后创建新的尝试。",
};

export function mergeRunEvents(
  previous: RunEvent[],
  incoming: RunEvent,
  runId: string,
): RunEvent[] {
  if (
    incoming.run_id !== runId ||
    !Number.isInteger(incoming.seq) ||
    incoming.seq < 1 ||
    !EVENT_LABELS[incoming.type]
  )
    return previous;
  if (previous.some((event) => event.seq === incoming.seq)) return previous;
  return [...previous, incoming].sort((a, b) => a.seq - b.seq).slice(-500);
}

export function reviewEligibility(
  report: Report,
  version: ReportVersion,
  userId: string,
  role: string,
): { allowed: boolean; reason: string } {
  if (!["reviewer", "admin"].includes(role))
    return { allowed: false, reason: "报告需由审核员或管理员独立审核。" };
  if (userId === report.created_by || userId === version.created_by)
    return {
      allowed: false,
      reason: "研究发起人和本版本编辑人不能审核自己的报告。",
    };
  if (report.current_version_id !== version.id)
    return { allowed: false, reason: "这是历史版本，请切换到当前版本后审核。" };
  if (report.state !== "in_review")
    return { allowed: false, reason: "当前版本尚未提交审核。" };
  return { allowed: true, reason: "审核将绑定下方指定版本及内容哈希。" };
}

function useAction() {
  const [busy, setBusy] = useState(false);
  const inFlight = useRef(false);
  const [error, setError] = useState<unknown>();
  const [message, setMessage] = useState("");
  async function perform(fn: () => Promise<void>) {
    if (inFlight.current) return;
    inFlight.current = true;
    setBusy(true);
    setError(undefined);
    setMessage("");
    try {
      await fn();
    } catch (failure) {
      setError(failure);
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  }
  return { busy, error, message, setMessage, perform };
}

function ActionMessage({ action }: { action: ReturnType<typeof useAction> }) {
  return (
    <>
      {action.error ? <ErrorPanel error={action.error} /> : null}
      {action.message ? (
        <p className="ph-notice" role="status">
          {action.message}
        </p>
      ) : null}
    </>
  );
}

function usePages<T>(path: string | null, filter: string, interval?: number) {
  const { workspaceId } = usePharma();
  const key = `${workspaceId}:${path}:${filter}`;
  const [paging, setPaging] = useState<{
    key: string;
    cursors: Array<string | null>;
  }>({ key, cursors: [null] });
  const cursors = paging.key === key ? paging.cursors : [null];
  const cursor = cursors.at(-1);
  const query = useResource<Collection<T>>(
    path
      ? `${path}?limit=20${filter ? `&${filter}` : ""}${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`
      : null,
    cursors.length === 1 ? interval : undefined,
  );
  return {
    ...query,
    previous: () => setPaging({ key, cursors: cursors.slice(0, -1) }),
    next: () => {
      if (query.data?.next_cursor)
        setPaging({ key, cursors: [...cursors, query.data.next_cursor] });
    },
    hasPrevious: cursors.length > 1,
  };
}

function Pager({
  page,
}: {
  page: {
    hasPrevious: boolean;
    previous: () => void;
    next: () => void;
    isFetching: boolean;
    data?: { has_more: boolean };
  };
}) {
  return (
    <div className="ph-actions mt-4 justify-end">
      <button
        className="ph-button-secondary"
        onClick={page.previous}
        disabled={!page.hasPrevious || page.isFetching}
      >
        <ArrowLeft size={15} aria-hidden />
        上一页
      </button>
      <button
        className="ph-button-secondary"
        onClick={page.next}
        disabled={!page.data?.has_more || page.isFetching}
      >
        下一页
        <ArrowRight size={15} aria-hidden />
      </button>
    </div>
  );
}

function useFilter(name: string) {
  const params = useSearchParams();
  const router = useRouter();
  const value = params.get(name) ?? "";
  return [
    value,
    (next: string) => {
      const query = new URLSearchParams(params.toString());
      if (next) query.set(name, next);
      else query.delete(name);
      router.replace(`?${query.toString()}`, { scroll: false });
    },
  ] as const;
}

export function ResearchList() {
  const { workspace } = usePharma();
  const [status, setStatus] = useFilter("status");
  const runs = usePages<ResearchRun>(
    "/research/runs",
    status ? `status=${encodeURIComponent(status)}` : "",
    5000,
  );
  return (
    <div className="ph-stack">
      <PageHeader
        eyebrow="RESEARCH WORKSPACE"
        title="研究任务"
        description="从一个明确的问题开始，将公开资料整理为可追溯、可审核的研究草稿。"
        actions={
          workspace.role !== "reader" ? (
            <Link className="ph-button" href="/pharma/research/new">
              <Plus size={17} aria-hidden />
              发起研究
            </Link>
          ) : undefined
        }
      />
      <Panel>
        <div className="ph-actions mb-5 justify-between">
          <label className="flex items-center gap-3 text-sm">
            任务状态
            <select
              aria-label="任务状态"
              className="ph-select"
              value={status}
              onChange={(event) => setStatus(event.target.value)}
            >
              <option value="">全部状态</option>
              {RUN_FILTERS.map((item) => (
                <option key={item.value} value={item.value}>
                  {item.label}
                </option>
              ))}
            </select>
          </label>
          <button
            className="ph-button-secondary"
            onClick={() => void runs.refetch()}
            disabled={runs.isFetching}
          >
            <RefreshCw size={15} aria-hidden />
            刷新
          </button>
        </div>
        {runs.isLoading ? (
          <Loading />
        ) : runs.error ? (
          <ErrorPanel error={runs.error} onRetry={() => void runs.refetch()} />
        ) : !runs.data?.items.length ? (
          <Empty
            title={status ? "没有符合条件的研究" : "开始你的第一项研究"}
            description="先同步官方来源并确认实体关联，再选择药物和时间范围发起研究。"
          />
        ) : (
          <>
            <div className="ph-table-wrap">
              <table className="ph-table">
                <thead>
                  <tr>
                    <th>研究问题</th>
                    <th>状态</th>
                    <th>运行方式</th>
                    <th>创建时间</th>
                    <th>报告</th>
                  </tr>
                </thead>
                <tbody>
                  {runs.data.items.map((run) => (
                    <tr key={run.id}>
                      <td>
                        <Link
                          className="font-medium hover:underline"
                          href={`/pharma/research/${run.id}`}
                        >
                          {run.question}
                        </Link>
                        <div className="mt-1 text-xs text-slate-500">
                          尝试 {run.attempt + 1}
                        </div>
                      </td>
                      <td>
                        <Badge status={run.status} />
                      </td>
                      <td>
                        <Badge status={run.runtime_mode}>
                          {run.runtime_mode === "replay"
                            ? "DEMO · 回放"
                            : "LIVE · 模型研究"}
                        </Badge>
                      </td>
                      <td>
                        <Timestamp value={run.created_at} />
                      </td>
                      <td>
                        {run.report_id ? (
                          <Link
                            className="ph-button-secondary"
                            href={`/pharma/reports/${run.report_id}`}
                          >
                            阅读报告
                          </Link>
                        ) : (
                          "—"
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Pager page={runs} />
          </>
        )}
      </Panel>
    </div>
  );
}

export function ResearchNew() {
  const { request, workspace, config } = usePharma();
  const params = useSearchParams();
  const router = useRouter();
  const drugs = useResource<DrugPage>("/drugs?limit=100");
  const [selected, setSelected] = useState<string[]>(() => {
    const id = params.get("drug_id") ?? params.get("drug");
    return id ? [id] : [];
  });
  const [question, setQuestion] = useState(
    params.get("question") ??
      "请梳理所选药物在研究时间范围内的临床试验与文献变化，列出可核对证据和资料缺口。",
  );
  const [timezone, setTimezone] = useState("Asia/Shanghai");
  const [start, setStart] = useState(() =>
    utcToZonedLocalInput(
      new Date(Date.now() - 7 * 86400000).toISOString(),
      "Asia/Shanghai",
    ),
  );
  const [end, setEnd] = useState(() =>
    utcToZonedLocalInput(new Date().toISOString(), "Asia/Shanghai"),
  );
  const [sources, setSources] = useState<Source[]>(["ctgov", "pubmed"]);
  const [calls, setCalls] = useState(30);
  const [models, setModels] = useState(12);
  const [wall, setWall] = useState(600);
  const [records, setRecords] = useState(200);
  const [validation, setValidation] = useState("");
  const action = useAction();
  const modelMissing =
    workspace.data_mode === "live" && config?.model_configured === false;
  async function submit(event: FormEvent) {
    event.preventDefault();
    const from = validZonedLocalToUtcIso(start, timezone);
    const until = validZonedLocalToUtcIso(end, timezone);
    if (
      !selected.length ||
      selected.length > 5 ||
      !sources.length ||
      question.trim().length < 10 ||
      !from ||
      !until ||
      from >= until
    ) {
      setValidation(
        "请选择 1–5 个药物及至少一个来源，并填写至少 10 字的问题和有效的起止时间、IANA 时区。结束时间需晚于开始时间。",
      );
      return;
    }
    if (
      ![calls, models, wall, records].every(Number.isInteger) ||
      calls < 1 ||
      calls > 30 ||
      models < 1 ||
      models > 12 ||
      wall < 30 ||
      wall > 600 ||
      records < 1 ||
      records > 200
    ) {
      setValidation("预算超出允许范围，请核对工具、模型、时长和记录上限。");
      return;
    }
    setValidation("");
    await action.perform(async () => {
      const input: ResearchInput = {
        question: question.trim(),
        drug_ids: selected,
        time_range: { start: from, end_exclusive: until, timezone },
        source_allowlist: sources,
        budget: {
          max_tool_calls: calls,
          max_model_calls: models,
          max_wall_seconds: wall,
          max_records: records,
        },
      };
      const run = await request<ResearchRun>("/research/runs", {
        method: "POST",
        body: input,
        idempotencyKey: crypto.randomUUID(),
      });
      router.push(`/pharma/research/${run.id}`);
    });
  }
  if (workspace.role === "reader")
    return (
      <Empty
        title="当前账户为只读角色"
        description="请由分析员发起研究，你可以阅读已经发布的报告。"
      />
    );
  return (
    <div className="ph-stack">
      <PageHeader
        eyebrow="EVIDENCE-LED RESEARCH"
        title="发起研究"
        description="明确研究对象、时间与资料来源，让每条结论都能回到原始证据。"
      />
      {modelMissing ? (
        <p className="ph-notice" role="status">
          平台已部署，真实模型将在后续配置。当前工作区不能启动 LIVE
          研究；来源检索、证据浏览和已发布报告仍可使用。
        </p>
      ) : null}
      <form
        data-testid="research-new-form"
        className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_320px]"
        onSubmit={(event) => void submit(event)}
      >
        <div className="ph-stack">
          <Panel title="01 · 定义研究问题">
            <Field
              label="研究问题"
              hint="仅限公开研发资料，请勿填写病历、患者身份或个体用药信息。"
            >
              <textarea
                className="ph-textarea min-h-32"
                value={question}
                onChange={(event) => setQuestion(event.target.value)}
                minLength={10}
                maxLength={4000}
                required
              />
            </Field>
          </Panel>
          <Panel title="02 · 选择研究对象">
            <p className="mb-4 text-sm text-slate-500">
              最多选择 5 个已建档药物。检索使用审核通过的别名。
            </p>
            {drugs.isLoading ? (
              <Loading />
            ) : drugs.error ? (
              <ErrorPanel
                error={drugs.error}
                onRetry={() => void drugs.refetch()}
              />
            ) : !drugs.data?.items.length ? (
              <Empty
                title="工作区尚未建立药物档案"
                action={
                  <Link href="/pharma/drugs" className="ph-button-secondary">
                    前往药物档案
                  </Link>
                }
              />
            ) : (
              <div className="grid gap-3 sm:grid-cols-2">
                {drugs.data.items.map((drug) => (
                  <label
                    key={drug.id}
                    className="flex min-h-16 cursor-pointer items-start gap-3 rounded-lg border border-slate-200 p-4 has-[:checked]:border-blue-500 has-[:checked]:bg-blue-50"
                  >
                    <input
                      type="checkbox"
                      className="mt-1 size-4 accent-blue-600"
                      checked={selected.includes(drug.id)}
                      disabled={
                        !selected.includes(drug.id) && selected.length >= 5
                      }
                      onChange={(event) =>
                        setSelected(
                          event.target.checked
                            ? [...selected, drug.id]
                            : selected.filter((id) => id !== drug.id),
                        )
                      }
                    />
                    <span>
                      <span className="block font-medium">
                        {drug.display_name}
                      </span>
                      <span className="text-xs text-slate-500">
                        {drug.development_code ?? "已建档对象"}
                      </span>
                    </span>
                  </label>
                ))}
              </div>
            )}
            {drugs.data?.has_more ? (
              <p className="ph-notice mt-3">
                当前显示前 100 个对象。更多对象可从药物详情页发起研究。
              </p>
            ) : null}
          </Panel>
          <Panel title="03 · 固定研究范围">
            <div className="ph-form-grid">
              <Field label="开始时间">
                <input
                  type="datetime-local"
                  className="ph-input"
                  value={start}
                  onChange={(event) => setStart(event.target.value)}
                  required
                />
              </Field>
              <Field label="结束时间（不含）">
                <input
                  type="datetime-local"
                  className="ph-input"
                  value={end}
                  onChange={(event) => setEnd(event.target.value)}
                  required
                />
              </Field>
              <Field label="时区" hint="时间按此 IANA 时区解释。">
                <input
                  className="ph-input"
                  value={timezone}
                  onChange={(event) => setTimezone(event.target.value)}
                  list="pharma-timezones"
                  required
                />
                <datalist id="pharma-timezones">
                  <option value="Asia/Shanghai" />
                  <option value="UTC" />
                  <option value="America/New_York" />
                  <option value="Europe/London" />
                </datalist>
              </Field>
            </div>
            <fieldset className="mt-5">
              <legend className="mb-3 text-sm font-medium">资料来源</legend>
              <div className="ph-actions">
                {(
                  [
                    ["ctgov", "ClinicalTrials.gov"],
                    ["pubmed", "PubMed"],
                  ] as const
                ).map(([source, label]) => (
                  <label
                    className="flex items-center gap-2 text-sm"
                    key={source}
                  >
                    <input
                      type="checkbox"
                      checked={sources.includes(source)}
                      onChange={(event) =>
                        setSources(
                          event.target.checked
                            ? [...sources, source]
                            : sources.filter((value) => value !== source),
                        )
                      }
                    />
                    {label}
                  </label>
                ))}
              </div>
            </fieldset>
          </Panel>
        </div>
        <aside className="ph-stack">
          <Panel title="本次研究预算">
            <div className="ph-stack">
              <Field label="工具调用上限">
                <input
                  className="ph-input"
                  type="number"
                  min={1}
                  max={30}
                  value={calls}
                  onChange={(event) => setCalls(Number(event.target.value))}
                  required
                />
              </Field>
              <Field label="模型调用上限">
                <input
                  className="ph-input"
                  type="number"
                  min={1}
                  max={12}
                  value={models}
                  onChange={(event) => setModels(Number(event.target.value))}
                  required
                />
              </Field>
              <Field label="最长执行秒数">
                <input
                  className="ph-input"
                  type="number"
                  min={30}
                  max={600}
                  value={wall}
                  onChange={(event) => setWall(Number(event.target.value))}
                  required
                />
              </Field>
              <Field label="最多外部记录">
                <input
                  className="ph-input"
                  type="number"
                  min={1}
                  max={200}
                  value={records}
                  onChange={(event) => setRecords(Number(event.target.value))}
                  required
                />
              </Field>
            </div>
          </Panel>
          <Panel title="先同步，再研究">
            <p className="text-sm leading-7 text-slate-600">
              研究会固定资料截止时间。新抓取的资料晚于截止时间时，需要先确认关联，再创建新的研究任务。
            </p>
            <p className="mt-3 text-sm leading-7 text-slate-600">
              研究完成后生成草稿，由独立审核人批准指定版本后发布。
            </p>
            <Badge
              status={workspace.data_mode === "demo" ? "replay" : "deerflow"}
            >
              {workspace.data_mode === "demo"
                ? "DEMO · 虚构资料回放"
                : "LIVE · 公开资料研究"}
            </Badge>
          </Panel>
          {validation ? (
            <p className="ph-error" role="alert">
              {validation}
            </p>
          ) : null}
          <ActionMessage action={action} />
          <button
            className="ph-button justify-center"
            type="submit"
            disabled={action.busy || modelMissing || !drugs.data?.items.length}
          >
            {action.busy ? (
              <Loader2 className="animate-spin" size={17} aria-hidden />
            ) : (
              <FlaskConical size={17} aria-hidden />
            )}
            开始研究
          </button>
        </aside>
      </form>
    </div>
  );
}

function useRunStream(id: string, refresh: () => void) {
  const { workspaceId } = usePharma();
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [connection, setConnection] = useState("connecting");
  const [generation, setGeneration] = useState(0);
  const refreshRef = useRef(refresh);
  refreshRef.current = refresh;
  useEffect(() => {
    let closed = false;
    setEvents([]);
    setConnection("connecting");
    const stream = new EventSource(
      `/api/pharma/v1/workspaces/${encodeURIComponent(workspaceId)}/research/runs/${encodeURIComponent(id)}/events`,
    );
    stream.onopen = () => setConnection("connected");
    stream.onerror = () => {
      if (!closed) setConnection("reconnecting");
    };
    for (const type of Object.keys(EVENT_LABELS))
      stream.addEventListener(type, (raw) => {
        try {
          const event = JSON.parse(
            (raw as MessageEvent<string>).data,
          ) as RunEvent;
          if (event.run_id !== id) return;
          setEvents((previous) => mergeRunEvents(previous, event, id));
          refreshRef.current();
          if (
            [
              "run.completed",
              "run.partial",
              "run.failed",
              "run.cancelled",
              "run.recovery_required",
            ].includes(event.type)
          ) {
            closed = true;
            stream.close();
            setConnection("closed");
          }
        } catch {
          setConnection("reconnecting");
        }
      });
    return () => {
      closed = true;
      stream.close();
    };
  }, [id, workspaceId, generation]);
  return {
    events,
    connection,
    restart: () => setGeneration((value) => value + 1),
  };
}

export function ResearchDetail({ id }: { id: string }) {
  const { workspaceId } = usePharma();
  return <ResearchDetailBody key={`${workspaceId}:${id}`} id={id} />;
}

function ResearchDetailBody({ id }: { id: string }) {
  const { request, workspace, config, me } = usePharma();
  const router = useRouter();
  const run = useResource<ResearchRun>(`/research/runs/${id}`, 4000);
  const tools = useResource<ToolCallPage>(
    `/research/runs/${id}/tool-calls?limit=100`,
    5000,
  );
  const stream = useRunStream(id, () => {
    void run.refetch();
    void tools.refetch();
  });
  const [answer, setAnswer] = useState("");
  const [reason, setReason] = useState("");
  const [tab, setTab] = useState("timeline");
  const action = useAction();
  if (run.isLoading) return <Loading />;
  if (run.error || !run.data)
    return <ErrorPanel error={run.error} onRetry={() => void run.refetch()} />;
  const value = run.data;
  const canAct =
    ["reviewer", "admin"].includes(workspace.role) ||
    (workspace.role === "analyst" && value.created_by === me.user.id);
  const canCancel = [
    "queued",
    "running",
    "awaiting_input",
    "verifying",
  ].includes(value.status);
  const canRetry = [
    "partial",
    "failed",
    "cancelled",
    "recovery_required",
  ].includes(value.status);
  return (
    <div className="ph-stack">
      <PageHeader
        eyebrow="RESEARCH TRACE"
        title="研究任务"
        description={value.question}
        actions={
          <div className="ph-actions">
            <Badge status={value.status} />
            <button
              className="ph-button-secondary"
              onClick={() => void run.refetch()}
            >
              <RefreshCw size={15} aria-hidden />
              刷新
            </button>
            {canAct && canCancel ? (
              <button
                className="ph-button-secondary"
                disabled={action.busy}
                onClick={() =>
                  void action.perform(async () => {
                    await request(`/research/runs/${id}/cancel`, {
                      method: "POST",
                    });
                    await run.refetch();
                    action.setMessage("取消请求已提交，请以任务状态为准。");
                  })
                }
              >
                <Square size={14} aria-hidden />
                取消研究
              </button>
            ) : null}
          </div>
        }
      />
      <div className="ph-actions text-sm text-slate-500">
        <Badge status={value.runtime_mode}>
          {value.runtime_mode === "replay"
            ? "DEMO · 虚构资料回放"
            : "LIVE · 真实模型"}
        </Badge>
        <span>
          创建于 <Timestamp value={value.created_at} />
        </span>
        <span>尝试 {value.attempt + 1}</span>
      </div>
      <ActionMessage action={action} />
      {value.stop_reason ? (
        <p className="ph-notice">
          {STOP_LABELS[value.stop_reason] ?? value.stop_reason}
        </p>
      ) : null}
      {value.runtime_mode === "deerflow" &&
      config?.model_configured === false ? (
        <p className="ph-notice">
          当前尚未配置真实模型，新尝试暂不可启动。历史任务的调用情况请查看实际用量；系统不会自动切换到演示回放。
        </p>
      ) : null}
      {stream.connection === "reconnecting" && !TERMINAL.has(value.status) ? (
        <p className="ph-notice" role="status">
          连接恢复中，任务仍在后台运行。页面也会定期刷新已持久化的任务状态。
        </p>
      ) : null}
      {value.status === "awaiting_input" ? (
        <Panel title="补充研究范围">
          <form
            className="ph-stack"
            onSubmit={(event) => {
              event.preventDefault();
              if (!value.clarification?.question_id) return;
              void action.perform(async () => {
                await request(`/research/runs/${id}/clarifications`, {
                  method: "POST",
                  body: {
                    answer,
                    question_id: value.clarification?.question_id,
                  },
                });
                setAnswer("");
                await run.refetch();
                stream.restart();
                action.setMessage("澄清已提交，继续使用本次剩余预算。");
              });
            }}
          >
            <p>
              {value.clarification?.question ?? "请补充需要研究的对象或范围。"}
            </p>
            {value.clarification?.options?.length ? (
              <div className="ph-actions">
                {value.clarification.options.map((option) => (
                  <button
                    key={option}
                    type="button"
                    className="ph-button-secondary"
                    onClick={() => setAnswer(option)}
                  >
                    {option}
                  </button>
                ))}
              </div>
            ) : null}
            <Field label="澄清回答">
              <textarea
                className="ph-textarea"
                value={answer}
                onChange={(event) => setAnswer(event.target.value)}
                maxLength={4000}
                required
              />
            </Field>
            <button
              className="ph-button"
              disabled={
                !canAct || action.busy || !value.clarification?.question_id
              }
              type="submit"
            >
              提交澄清并继续
            </button>
          </form>
        </Panel>
      ) : null}
      <div
        className="ph-actions lg:hidden"
        role="tablist"
        aria-label="研究详情内容"
      >
        <button
          role="tab"
          aria-selected={tab === "timeline"}
          className="ph-button-secondary"
          onClick={() => setTab("timeline")}
        >
          行动轨迹
        </button>
        <button
          role="tab"
          aria-selected={tab === "results"}
          className="ph-button-secondary"
          onClick={() => setTab("results")}
        >
          报告与覆盖
        </button>
      </div>
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.15fr)]">
        <div
          className={`ph-stack min-w-0 ${tab !== "timeline" ? "hidden lg:flex" : ""}`}
        >
          <Panel
            title="行动轨迹"
            actions={
              <span className="text-xs text-slate-500">
                已记录 {stream.events.length} 条
              </span>
            }
          >
            <ol data-testid="run-timeline" className="space-y-5">
              {stream.events.map((event) => (
                <li className="flex gap-3" key={event.seq}>
                  <span className="mt-1 flex size-6 shrink-0 items-center justify-center rounded-full bg-blue-50 text-xs text-blue-700">
                    {event.seq}
                  </span>
                  <div className="min-w-0">
                    <p className="text-sm font-medium">
                      {EVENT_LABELS[event.type]}
                    </p>
                    {typeof event.payload.tool === "string" ? (
                      <p className="text-sm text-slate-600">
                        {TOOL_LABELS[event.payload.tool] ?? event.payload.tool}
                      </p>
                    ) : null}
                    {typeof event.payload.error_code === "string" &&
                    event.payload.error_code ? (
                      <p className="mt-1 text-xs break-all text-red-700">
                        {event.payload.error_code}
                      </p>
                    ) : null}
                    <div className="mt-1 text-xs text-slate-500">
                      <Timestamp value={event.occurred_at} />
                    </div>
                  </div>
                </li>
              ))}
            </ol>
            {!stream.events.length ? (
              <p className="text-sm text-slate-500">
                正在读取已持久化的行动记录。
              </p>
            ) : null}
          </Panel>
          <Panel title="领域工具记录">
            {tools.error ? (
              <ErrorPanel
                error={tools.error}
                onRetry={() => void tools.refetch()}
              />
            ) : tools.isLoading ? (
              <Loading />
            ) : !tools.data?.items.length ? (
              <p className="text-sm text-slate-500">尚未执行工具调用。</p>
            ) : (
              <div className="space-y-3">
                {tools.data.items
                  .slice()
                  .reverse()
                  .map((tool) => (
                    <details
                      className="rounded-lg border border-slate-200 p-3"
                      key={tool.id}
                    >
                      <summary className="flex cursor-pointer flex-wrap items-center justify-between gap-2 text-sm">
                        <span>{TOOL_LABELS[tool.tool] ?? tool.tool}</span>
                        <Badge status={tool.state} />
                      </summary>
                      <div className="mt-3 space-y-3 text-sm">
                        <p>
                          耗时：
                          {tool.duration_ms === null
                            ? "未知"
                            : `${tool.duration_ms} ms`}
                        </p>
                        {tool.error_code ? (
                          <p className="ph-error">{tool.error_code}</p>
                        ) : null}
                        <div className="ph-actions">
                          {tool.evidence_ids.map((evidence, index) => (
                            <EvidenceButton
                              key={evidence}
                              id={evidence}
                              label={`证据 ${index + 1}`}
                            />
                          ))}
                        </div>
                      </div>
                    </details>
                  ))}
              </div>
            )}
          </Panel>
        </div>
        <div
          className={`ph-stack min-w-0 ${tab !== "results" ? "hidden lg:flex" : ""}`}
        >
          <Panel title="研究产物">
            {value.report_id ? (
              <div className="ph-stack">
                <FileText className="text-blue-600" size={30} aria-hidden />
                <h3 className="text-lg font-semibold">研究草稿已就绪</h3>
                <p className="text-sm leading-7 text-slate-600">
                  草稿保留证据、资料缺口和版本信息。完成研究不等于结论已获批准，发布前仍需独立审核。
                </p>
                <Link
                  className="ph-button"
                  href={`/pharma/reports/${value.report_id}`}
                >
                  打开研究报告
                  <ArrowRight size={16} aria-hidden />
                </Link>
              </div>
            ) : (
              <Empty
                title={
                  TERMINAL.has(value.status)
                    ? "本次未生成可审核报告"
                    : "报告将在研究完成后出现"
                }
                description="模型缺失、资料不足或取消都不会被当作研究成功。请结合行动记录与覆盖状态判断。"
              />
            )}
          </Panel>
          <Panel title="来源覆盖">
            <Coverage items={value.coverage} />
          </Panel>
          <Panel title="实际用量">
            <dl className="grid grid-cols-2 gap-5 text-sm">
              <div>
                <dt className="text-slate-500">工具调用</dt>
                <dd className="mt-1 text-xl font-semibold tabular-nums">
                  {value.usage.tool_calls}
                  <span className="text-sm font-normal text-slate-500">
                    {" "}
                    / {value.frozen_request.budget?.max_tool_calls ?? 30}
                  </span>
                </dd>
              </div>
              <div>
                <dt className="text-slate-500">模型调用</dt>
                <dd className="mt-1 text-xl font-semibold tabular-nums">
                  {value.usage.model_calls}
                  <span className="text-sm font-normal text-slate-500">
                    {" "}
                    / {value.frozen_request.budget?.max_model_calls ?? 12}
                  </span>
                </dd>
              </div>
              <div>
                <dt className="text-slate-500">输入 / 输出 token</dt>
                <dd className="mt-1 tabular-nums">
                  {value.usage.input_tokens ?? "未知"} /{" "}
                  {value.usage.output_tokens ?? "未知"}
                </dd>
              </div>
              <div>
                <dt className="text-slate-500">费用</dt>
                <dd className="mt-1">
                  {value.usage.estimated_cost === null
                    ? "未配置单价，金额未知"
                    : `${value.usage.estimated_cost} ${value.usage.currency ?? ""}`}
                </dd>
              </div>
            </dl>
            <p className="mt-4 text-xs text-slate-500">
              用量口径：
              {
                {
                  reported: "供应商报告",
                  estimated: "包含估计值",
                  unknown: "未知",
                }[value.usage.usage_quality]
              }
            </p>
          </Panel>
          {canAct && canRetry ? (
            <Panel title="创建新的尝试">
              <form
                className="ph-stack"
                onSubmit={(event) => {
                  event.preventDefault();
                  void action.perform(async () => {
                    const next = await request<ResearchRun>(
                      `/research/runs/${id}/retry`,
                      {
                        method: "POST",
                        body: { reason },
                        idempotencyKey: crypto.randomUUID(),
                      },
                    );
                    router.push(`/pharma/research/${next.id}`);
                  });
                }}
              >
                <p className="text-sm text-slate-500">
                  新的尝试会重新固定资料截止时间，保留原任务与历史记录。
                </p>
                <Field label="重试原因">
                  <input
                    className="ph-input"
                    value={reason}
                    onChange={(event) => setReason(event.target.value)}
                    maxLength={1000}
                    required
                  />
                </Field>
                <button
                  className="ph-button-secondary"
                  disabled={
                    action.busy ||
                    (workspace.data_mode === "live" &&
                      config?.model_configured === false)
                  }
                >
                  <RefreshCw size={15} aria-hidden />
                  创建新尝试
                </button>
              </form>
            </Panel>
          ) : null}
        </div>
      </div>
    </div>
  );
}

export function ReportsList() {
  const [state, setState] = useFilter("state");
  const reports = usePages<Report>(
    "/reports",
    state ? `state=${encodeURIComponent(state)}` : "",
  );
  return (
    <div className="ph-stack">
      <PageHeader
        eyebrow="RESEARCH LIBRARY"
        title="报告中心"
        description="以版本保留研究，以证据核对结论。已发布的报告与后续修订分别保存。"
      />
      <Panel>
        <div className="ph-actions mb-5 justify-between">
          <label className="flex items-center gap-3 text-sm">
            报告状态
            <select
              className="ph-select"
              value={state}
              onChange={(event) => setState(event.target.value)}
            >
              <option value="">全部状态</option>
              {[
                ["draft", "草稿"],
                ["in_review", "待审核"],
                ["changes_requested", "需修改"],
                ["approved", "已批准"],
                ["published", "已发布"],
                ["retracted", "已撤回"],
              ].map(([value, label]) => (
                <option value={value} key={value}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          <button
            className="ph-button-secondary"
            onClick={() => void reports.refetch()}
            disabled={reports.isFetching}
          >
            <RefreshCw size={15} aria-hidden />
            刷新
          </button>
        </div>
        {reports.isLoading ? (
          <Loading />
        ) : reports.error ? (
          <ErrorPanel
            error={reports.error}
            onRetry={() => void reports.refetch()}
          />
        ) : !reports.data?.items.length ? (
          <Empty
            title={
              state ? "没有符合筛选条件的报告" : "报告库正在等待第一份研究"
            }
            description="研究任务生成草稿；独立审核通过后，工作区成员可以阅读发布版本。"
          />
        ) : (
          <>
            <div className="ph-table-wrap">
              <table className="ph-table">
                <thead>
                  <tr>
                    <th>报告名称</th>
                    <th>状态</th>
                    <th>更新时间</th>
                    <th>阅读</th>
                  </tr>
                </thead>
                <tbody>
                  {reports.data.items.map((report) => (
                    <tr key={report.id}>
                      <td>
                        <Link
                          className="font-medium hover:underline"
                          href={`/pharma/reports/${report.id}`}
                        >
                          {report.title}
                        </Link>
                        {report.published_version_id &&
                        report.current_version_id &&
                        report.published_version_id !==
                          report.current_version_id ? (
                          <p className="mt-1 text-xs text-amber-700">
                            有尚未发布的新版本
                          </p>
                        ) : null}
                      </td>
                      <td>
                        <Badge status={report.state} />
                      </td>
                      <td>
                        <Timestamp value={report.updated_at} />
                      </td>
                      <td>
                        <Link
                          className="ph-button-secondary"
                          href={`/pharma/reports/${report.id}`}
                        >
                          查看报告
                          <ArrowRight size={14} aria-hidden />
                        </Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Pager page={reports} />
          </>
        )}
      </Panel>
    </div>
  );
}

function useUnsavedWarning(dirty: boolean) {
  useEffect(() => {
    if (!dirty) return;
    const leave = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    const link = (event: MouseEvent) => {
      if (!(event.target instanceof Element)) return;
      const anchor = event.target.closest("a");
      if (
        anchor?.href &&
        !anchor.hasAttribute("download") &&
        !anchor.target &&
        anchor.href !== window.location.href &&
        !window.confirm("还有尚未保存的报告修改，确定离开？")
      ) {
        event.preventDefault();
        event.stopPropagation();
      }
    };
    window.addEventListener("beforeunload", leave);
    document.addEventListener("click", link, true);
    return () => {
      window.removeEventListener("beforeunload", leave);
      document.removeEventListener("click", link, true);
    };
  }, [dirty]);
}

function ReportContent({ version }: { version: ReportVersion }) {
  const claims = useResource<ClaimPage>(
    `/reports/${version.report_id}/versions/${version.id}/claims?limit=100`,
  );
  const statuses = new Map(
    claims.data?.items.map((claim) => [claim.claim_key, claim]),
  );
  return (
    <article
      data-testid="report-content"
      className="mx-auto max-w-[840px] space-y-8 text-[15px] leading-8"
    >
      <div>
        <p className="mb-3 text-xs font-semibold tracking-widest text-blue-600">
          RESEARCH BRIEF · V{version.version_no}
        </p>
        <h2 className="text-2xl leading-snug font-bold">
          {version.content.title}
        </h2>
        <p className="mt-5 whitespace-pre-wrap text-slate-600">
          {version.content.summary}
        </p>
      </div>
      {version.content.sections.map((section, index) => (
        <section key={`${section.heading}-${index}`}>
          <h3 className="mb-3 text-lg font-semibold">{section.heading}</h3>
          <p className="whitespace-pre-wrap">{section.text}</p>
          {section.claim_keys.length ? (
            <div className="mt-3 flex flex-wrap gap-3">
              {section.claim_keys.map((key) => (
                <a
                  href={`#claim-${key}`}
                  className="text-sm text-blue-700 underline underline-offset-4"
                  key={key}
                >
                  结论 {key}
                </a>
              ))}
            </div>
          ) : null}
        </section>
      ))}
      <section>
        <h3 className="mb-4 text-lg font-semibold">结论与引用依据</h3>
        {claims.error ? (
          <ErrorPanel
            error={claims.error}
            onRetry={() => void claims.refetch()}
          />
        ) : null}
        <div className="space-y-4">
          {version.content.claims.map((claim) => {
            const detail = statuses.get(claim.claim_key);
            return (
              <section
                id={`claim-${claim.claim_key}`}
                key={claim.claim_key}
                className="scroll-mt-24 rounded-xl border border-slate-200 p-5"
              >
                <div className="ph-actions mb-3">
                  <span className="font-mono text-xs font-semibold text-slate-500">
                    {claim.claim_key}
                  </span>
                  <Badge status={claim.category} />
                  {detail ? (
                    <Badge status={detail.verification_status} />
                  ) : null}
                </div>
                <p className="whitespace-pre-wrap">{claim.statement}</p>
                {claim.qualifiers.population ? (
                  <p className="mt-2 text-sm text-slate-500">
                    研究人群：{claim.qualifiers.population}
                  </p>
                ) : null}
                {claim.qualifiers.time_scope ? (
                  <p className="text-sm text-slate-500">
                    时间范围：{claim.qualifiers.time_scope}
                  </p>
                ) : null}
                {claim.qualifiers.limitations.map((text, index) => (
                  <p className="mt-2 text-sm text-slate-500" key={index}>
                    {text}
                  </p>
                ))}
                {detail?.numeric_check === "manual_check_required" ||
                detail?.numeric_check === "failed" ? (
                  <p className="ph-notice mt-3">
                    此结论中的数字需要人工核对，结构校验不代表事实已经确认。
                  </p>
                ) : null}
                <div className="ph-actions mt-4">
                  {claim.evidence_links.map((link, index) => (
                    <span
                      className="inline-flex items-center gap-2"
                      key={`${link.evidence_id}-${link.relation}`}
                    >
                      <EvidenceButton
                        id={link.evidence_id}
                        label={`证据 ${index + 1}`}
                      />
                      <span className="text-xs text-slate-500">
                        {
                          {
                            supports: "支持",
                            contradicts: "反驳",
                            context: "背景",
                          }[link.relation]
                        }
                      </span>
                    </span>
                  ))}
                  {!claim.evidence_links.length ? (
                    <span className="text-sm text-amber-700">
                      未绑定证据，仅作为资料缺口或待验证解释。
                    </span>
                  ) : null}
                </div>
              </section>
            );
          })}
        </div>
      </section>
      <section className="rounded-xl bg-slate-50 p-5">
        <h3 className="mb-3 text-base font-semibold">资料限制</h3>
        <ul className="list-disc space-y-2 pl-5 text-sm text-slate-600">
          {version.content.limitations.map((text, index) => (
            <li key={index}>{text}</li>
          ))}
        </ul>
        {version.content.unanswered_questions.length ? (
          <>
            <h4 className="mt-5 font-medium">尚未解决的问题</h4>
            <ul className="mt-2 list-disc pl-5 text-sm">
              {version.content.unanswered_questions.map((text, index) => (
                <li key={index}>{text}</li>
              ))}
            </ul>
          </>
        ) : null}
      </section>
    </article>
  );
}

function ReportEditor({
  initial,
  saving,
  onSave,
  onCancel,
}: {
  initial: ReportVersion;
  saving: boolean;
  onSave: (content: ResearchOutput, note: string) => Promise<void>;
  onCancel: () => void;
}) {
  const [draft, setDraft] = useState<ResearchOutput>(() =>
    structuredClone(initial.content),
  );
  const [note, setNote] = useState("");
  useUnsavedWarning(true);
  return (
    <form
      className="ph-stack"
      onSubmit={(event) => {
        event.preventDefault();
        void onSave(draft, note);
      }}
    >
      <p className="ph-notice">
        正在编辑 V{initial.version_no}{" "}
        的修订稿。保存会产生新版本，并要求重新审核；已有发布内容保持可追溯。
      </p>
      <Field label="报告标题">
        <input
          className="ph-input"
          value={draft.title}
          maxLength={300}
          required
          onChange={(event) =>
            setDraft({ ...draft, title: event.target.value })
          }
        />
      </Field>
      <Field label="报告摘要">
        <textarea
          className="ph-textarea min-h-28"
          value={draft.summary}
          maxLength={4000}
          required
          onChange={(event) =>
            setDraft({ ...draft, summary: event.target.value })
          }
        />
      </Field>
      {draft.sections.map((section, index) => (
        <Field key={index} label={`章节 ${index + 1} · ${section.heading}`}>
          <textarea
            className="ph-textarea min-h-24"
            value={section.text}
            maxLength={8000}
            onChange={(event) =>
              setDraft({
                ...draft,
                sections: draft.sections.map((item, at) =>
                  at === index ? { ...item, text: event.target.value } : item,
                ),
              })
            }
          />
        </Field>
      ))}
      {draft.claims.map((claim, index) => (
        <Field
          key={claim.claim_key}
          label={`结论 ${claim.claim_key}`}
          hint="修改表述后仍需逐条核对已绑定的原始证据。"
        >
          <textarea
            className="ph-textarea"
            value={claim.statement}
            maxLength={2000}
            required
            onChange={(event) =>
              setDraft({
                ...draft,
                claims: draft.claims.map((item, at) =>
                  at === index
                    ? { ...item, statement: event.target.value }
                    : item,
                ),
              })
            }
          />
        </Field>
      ))}
      <Field label="修改说明">
        <textarea
          className="ph-textarea"
          value={note}
          onChange={(event) => setNote(event.target.value)}
          minLength={1}
          maxLength={2000}
          required
        />
      </Field>
      <div className="ph-actions">
        <button className="ph-button" disabled={saving} type="submit">
          {saving ? (
            <Loader2 className="animate-spin" size={16} aria-hidden />
          ) : (
            <Check size={16} aria-hidden />
          )}
          保存新版本
        </button>
        <button
          className="ph-button-secondary"
          type="button"
          disabled={saving}
          onClick={onCancel}
        >
          放弃修改
        </button>
      </div>
    </form>
  );
}

export function ReportDetail({ id }: { id: string }) {
  const { workspaceId } = usePharma();
  return <ReportDetailBody key={`${workspaceId}:${id}`} id={id} />;
}

function ReportDetailBody({ id }: { id: string }) {
  const { workspace, workspaceId, me, request, refresh } = usePharma();
  const params = useSearchParams();
  const report = useResource<Report>(`/reports/${id}`);
  const versions = useResource<ReportVersionPage>(
    `/reports/${id}/versions?limit=100`,
  );
  const notices = useResource<ReportNoticePage>(
    `/reports/${id}/notices?limit=100`,
  );
  const [selected, setSelected] = useState<string | null>(() =>
    params.get("version"),
  );
  const [editing, setEditing] = useState(false);
  const [note, setNote] = useState("");
  const [retraction, setRetraction] = useState("");
  const action = useAction();
  const versionId =
    selected ??
    report.data?.current_version_id ??
    report.data?.published_version_id;
  const version = useResource<ReportVersion>(
    versionId ? `/reports/${id}/versions/${versionId}` : null,
  );
  if (report.isLoading) return <Loading />;
  if (report.error || !report.data)
    return (
      <ErrorPanel error={report.error} onRetry={() => void report.refetch()} />
    );
  const current = report.data;
  const editor =
    (workspace.role === "analyst" && me.user.id === current.created_by) ||
    ["reviewer", "admin"].includes(workspace.role);
  const activeVersion = version.data;
  const isCurrent = activeVersion?.id === current.current_version_id;
  const eligible = activeVersion
    ? reviewEligibility(current, activeVersion, me.user.id, workspace.role)
    : { allowed: false, reason: "正在加载版本" };
  async function act(path: string, extra: Record<string, unknown> = {}) {
    if (!activeVersion) return;
    await action.perform(async () => {
      await request(`/reports/${id}/${path}`, {
        method: "POST",
        body: {
          version_id: activeVersion.id,
          content_hash: activeVersion.content_hash,
          ...extra,
        },
        ...(path === "publish" ? { idempotencyKey: crypto.randomUUID() } : {}),
      });
      await refresh();
      action.setMessage(
        path === "publish"
          ? "指定版本已发布；投递状态请在通知与订阅中查看。"
          : path === "reviews"
            ? "审核结果已保存，并绑定当前版本与内容哈希。"
            : "当前版本已提交独立审核。",
      );
      setNote("");
    });
  }
  return (
    <div className="ph-stack">
      <PageHeader
        eyebrow="VERSIONED RESEARCH REPORT"
        title={current.title}
        back="/pharma/reports"
        actions={<Badge status={current.state} />}
      />
      <ActionMessage action={action} />
      {current.state === "retracted" ? (
        <p className="ph-error" role="alert">
          此报告已撤回。保留原版本以便追溯，请勿将其作为当前有效结论继续传播。
        </p>
      ) : null}
      {current.published_version_id &&
      current.current_version_id &&
      current.published_version_id !== current.current_version_id ? (
        <p className="ph-notice">
          当前修订稿尚未发布。
          <button
            className="ml-2 text-blue-700 underline"
            onClick={() => {
              if (!editing) setSelected(current.published_version_id);
            }}
            disabled={editing}
          >
            查看已发布版本
          </button>
        </p>
      ) : null}
      {notices.error ? (
        <ErrorPanel
          error={notices.error}
          onRetry={() => void notices.refetch()}
        />
      ) : (
        notices.data?.items.map((notice) => (
          <p className="ph-notice" key={notice.id}>
            <strong>
              {notice.type === "source_updated"
                ? "来源版本提示 · "
                : "撤回提示 · "}
            </strong>
            {notice.message} <Timestamp value={notice.created_at} />
          </p>
        ))
      )}
      <div className="ph-actions justify-between">
        <label className="flex items-center gap-3 text-sm">
          阅读版本
          <select
            className="ph-select"
            aria-label="阅读版本"
            disabled={editing || versions.isLoading}
            value={versionId ?? ""}
            onChange={(event) => setSelected(event.target.value)}
          >
            {versions.data?.items.map((item) => (
              <option key={item.id} value={item.id}>
                V{item.version_no}
                {item.id === current.current_version_id ? " · 当前" : ""}
                {item.id === current.published_version_id ? " · 已发布" : ""}
              </option>
            ))}
          </select>
        </label>
        {activeVersion ? (
          <div className="ph-actions">
            <a
              className="ph-button-secondary"
              href={`/api/pharma/v1/workspaces/${workspaceId}/reports/${id}/export?format=markdown&version_id=${activeVersion.id}`}
              download
            >
              <Download size={15} aria-hidden />
              Markdown
            </a>
            <a
              className="ph-button-secondary"
              href={`/api/pharma/v1/workspaces/${workspaceId}/reports/${id}/export?format=json&version_id=${activeVersion.id}`}
              download
            >
              <Download size={15} aria-hidden />
              JSON
            </a>
          </div>
        ) : null}
      </div>
      {versions.error ? (
        <ErrorPanel
          error={versions.error}
          onRetry={() => void versions.refetch()}
        />
      ) : null}
      {version.isLoading ? (
        <Loading />
      ) : version.error ? (
        <ErrorPanel
          error={version.error}
          onRetry={() => void version.refetch()}
        />
      ) : activeVersion ? (
        <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_320px]">
          <Panel className="min-w-0">
            {editing ? (
              <ReportEditor
                key={activeVersion.id}
                initial={activeVersion}
                saving={action.busy}
                onCancel={() => setEditing(false)}
                onSave={async (content, editNote) => {
                  await action.perform(async () => {
                    const saved = await request<ReportVersion>(
                      `/reports/${id}/versions`,
                      {
                        method: "POST",
                        body: {
                          base_version_id: activeVersion.id,
                          content,
                          edit_note: editNote,
                        },
                      },
                    );
                    setEditing(false);
                    setSelected(saved.id);
                    await refresh();
                    action.setMessage("新版本已保存，需要重新提交审核。");
                  });
                }}
              />
            ) : (
              <ReportContent version={activeVersion} />
            )}
          </Panel>
          <aside className="ph-stack min-w-0">
            <Panel title="版本与研究范围">
              <div className="ph-stack text-sm">
                <Badge status={activeVersion.runtime_mode}>
                  {activeVersion.runtime_mode === "replay"
                    ? "DEMO · 虚构资料 / 回放"
                    : "LIVE · 公开研究资料"}
                </Badge>
                <div>
                  <span className="text-slate-500">资料截止</span>
                  <p className="mt-1">
                    <Timestamp
                      value={activeVersion.content.scope.knowledge_cutoff}
                    />
                  </p>
                </div>
                <div>
                  <span className="text-slate-500">研究时间范围</span>
                  <p className="mt-1">
                    <Timestamp
                      value={activeVersion.content.scope.time_range.start}
                    />
                  </p>
                  <p>
                    至{" "}
                    <Timestamp
                      value={
                        activeVersion.content.scope.time_range.end_exclusive
                      }
                    />
                    （不含）
                  </p>
                  <p className="mt-1 text-xs text-slate-500">
                    {activeVersion.content.scope.time_range.timezone}
                  </p>
                </div>
                <Link
                  href={`/pharma/research/${current.run_id}`}
                  className="text-blue-700 underline underline-offset-4"
                >
                  查看研究任务与行动轨迹
                </Link>
              </div>
            </Panel>
            <Panel title="来源覆盖">
              <Coverage items={activeVersion.content.coverage} />
            </Panel>
            {editor && workspace.role !== "reader" ? (
              <Panel title="审核与发布">
                <div data-testid="report-review-panel" className="ph-stack">
                  <div className="rounded-lg bg-slate-50 p-3 text-sm">
                    <strong>指定版本 V{activeVersion.version_no}</strong>
                    <p className="mt-2 text-xs text-slate-500">
                      SHA-256 内容哈希
                    </p>
                    <code className="mt-1 block text-[13px] leading-5 break-all">
                      {activeVersion.content_hash}
                    </code>
                  </div>
                  <p className="text-sm leading-6 text-slate-600">
                    草稿已通过保存时的结构与引用校验；语义、数字和研究限制仍需人工核对。审核结果只对指定内容版本有效。
                  </p>
                  {isCurrent && current.state !== "retracted" && !editing ? (
                    <button
                      className="ph-button-secondary"
                      onClick={() => setEditing(true)}
                      disabled={action.busy}
                    >
                      <FileText size={15} aria-hidden />
                      编辑新版本
                    </button>
                  ) : null}
                  {isCurrent &&
                  ["draft", "changes_requested"].includes(current.state) &&
                  !editing ? (
                    <button
                      className="ph-button"
                      disabled={action.busy}
                      onClick={() => void act("submit-review")}
                    >
                      <ClipboardCheck size={16} aria-hidden />
                      提交审核
                    </button>
                  ) : null}
                  {["reviewer", "admin"].includes(workspace.role) &&
                  current.state === "in_review" ? (
                    <form
                      className="ph-stack"
                      onSubmit={(event) => {
                        event.preventDefault();
                        if (eligible.allowed)
                          void act("reviews", { decision: "approve", note });
                      }}
                    >
                      <p className="text-sm text-slate-600">
                        {eligible.reason}
                      </p>
                      <Field label="审核意见">
                        <textarea
                          className="ph-textarea"
                          value={note}
                          onChange={(event) => setNote(event.target.value)}
                          maxLength={4000}
                          required
                          disabled={!eligible.allowed || editing}
                        />
                      </Field>
                      <button
                        className="ph-button"
                        disabled={!eligible.allowed || action.busy || editing}
                        type="submit"
                      >
                        <ShieldCheck size={16} aria-hidden />
                        批准此版本
                      </button>
                      <button
                        className="ph-button-secondary"
                        disabled={
                          !eligible.allowed ||
                          action.busy ||
                          !note.trim() ||
                          editing
                        }
                        type="button"
                        onClick={() =>
                          void act("reviews", {
                            decision: "request_changes",
                            note,
                          })
                        }
                      >
                        <Undo2 size={15} aria-hidden />
                        退回修改
                      </button>
                    </form>
                  ) : null}
                  {isCurrent && current.state === "approved" && !editing ? (
                    <button
                      className="ph-button"
                      disabled={action.busy}
                      onClick={() => void act("publish")}
                    >
                      <Check size={16} aria-hidden />
                      发布此版本
                    </button>
                  ) : null}
                  {!isCurrent ? (
                    <p className="ph-notice">
                      当前阅读的是历史或已发布版本。修改、审核和发布需要切换到当前版本。
                    </p>
                  ) : null}
                  {["reviewer", "admin"].includes(workspace.role) &&
                  current.published_version_id &&
                  current.state !== "retracted" &&
                  !editing ? (
                    <details className="border-t border-slate-200 pt-4">
                      <summary className="cursor-pointer text-sm text-red-700">
                        撤回已发布版本
                      </summary>
                      <form
                        className="ph-stack mt-3"
                        onSubmit={(event) => {
                          event.preventDefault();
                          void action.perform(async () => {
                            await request(`/reports/${id}/retract`, {
                              method: "POST",
                              body: {
                                version_id: current.published_version_id,
                                reason: retraction,
                              },
                            });
                            await refresh();
                            action.setMessage(
                              "报告已撤回，尚未投递的通知将停止。已经外发的内容无法自动收回。",
                            );
                          });
                        }}
                      >
                        <Field label="撤回原因">
                          <textarea
                            className="ph-textarea"
                            value={retraction}
                            onChange={(event) =>
                              setRetraction(event.target.value)
                            }
                            maxLength={4000}
                            required
                          />
                        </Field>
                        <button
                          className="ph-button-secondary text-red-700!"
                          disabled={action.busy}
                        >
                          确认撤回发布版本
                        </button>
                      </form>
                    </details>
                  ) : null}
                </div>
              </Panel>
            ) : null}
          </aside>
        </div>
      ) : (
        <Empty
          title="暂无可阅读版本"
          description="请检查报告权限或重新加载。"
        />
      )}
    </div>
  );
}

function MappingReview({
  item,
  kind,
  drugName,
  onComplete,
}: {
  item: Alias | EntityLink;
  kind: "alias" | "link";
  drugName: string;
  onComplete: () => Promise<unknown>;
}) {
  const { request } = usePharma();
  const [note, setNote] = useState("");
  const action = useAction();
  const text =
    "alias" in item
      ? item.alias
      : {
          investigational: "试验药物",
          comparator: "对照药物",
          background: "背景治疗",
          unspecified: "角色待确认",
          mentions: "文献提及",
        }[item.relation];
  async function decide(decision: "approve" | "reject") {
    await action.perform(async () => {
      await request(
        `/${kind === "alias" ? "aliases" : "entity-links"}/${item.id}/decision`,
        { method: "POST", body: { decision, note } },
      );
      await onComplete();
    });
  }
  return (
    <article className="rounded-xl border border-slate-200 p-5">
      <div className="ph-actions justify-between">
        <strong>{text}</strong>
        <Badge status={item.status} />
      </div>
      <p className="mt-2 text-sm text-slate-500">药物对象：{drugName}</p>
      {"record_id" in item ? (
        <p className="mt-1 font-mono text-xs break-all text-slate-500">
          来源记录 {item.record_id}
        </p>
      ) : null}
      <p className="my-3 text-sm leading-7">{item.note}</p>
      {item.evidence_id ? (
        <EvidenceButton id={item.evidence_id} />
      ) : (
        <p className="ph-notice">
          尚未关联证据，请核对对象身份及关联说明，不能仅凭同名自动确认。
        </p>
      )}
      <form
        className="ph-stack mt-4"
        onSubmit={(event) => {
          event.preventDefault();
          void decide("approve");
        }}
      >
        <Field label={`审核说明 · ${text}`}>
          <input
            className="ph-input"
            value={note}
            onChange={(event) => setNote(event.target.value)}
            maxLength={4000}
            required
          />
        </Field>
        <ActionMessage action={action} />
        <div className="ph-actions">
          <button className="ph-button" disabled={action.busy} type="submit">
            <Check size={15} aria-hidden />
            {kind === "alias" ? "批准别名" : "确认关联"}
          </button>
          <button
            className="ph-button-secondary"
            disabled={action.busy || !note.trim()}
            type="button"
            onClick={() => void decide("reject")}
          >
            拒绝
          </button>
        </div>
      </form>
    </article>
  );
}

export function ReviewPage() {
  const { workspace } = usePharma();
  const allowed = ["reviewer", "admin"].includes(workspace.role);
  const reports = usePages<Report>(
    allowed ? "/reports" : null,
    "state=in_review",
  );
  const aliases = usePages<Alias>(
    allowed ? "/aliases" : null,
    "status=pending",
  );
  const links = usePages<EntityLink>(
    allowed ? "/entity-links" : null,
    "status=pending",
  );
  const drugs = useResource<DrugPage>(allowed ? "/drugs?limit=100" : null);
  if (!allowed)
    return (
      <Empty
        title="需要审核角色"
        description="此处用于独立审核报告及对象映射，请由工作区审核员或管理员处理。"
      />
    );
  const names = new Map(
    drugs.data?.items.map((drug) => [drug.id, drug.display_name]),
  );
  return (
    <div className="ph-stack">
      <PageHeader
        eyebrow="INDEPENDENT REVIEW"
        title="审核中心"
        description="先确认对象与证据，再批准指定内容版本。研究发起人与审核人相互独立。"
      />
      <Panel
        title="等待独立审核的报告"
        actions={
          <button
            className="ph-button-secondary"
            onClick={() => void reports.refetch()}
          >
            <RefreshCw size={15} aria-hidden />
            刷新
          </button>
        }
      >
        {reports.isLoading ? (
          <Loading />
        ) : reports.error ? (
          <ErrorPanel
            error={reports.error}
            onRetry={() => void reports.refetch()}
          />
        ) : !reports.data?.items.length ? (
          <Empty
            title="当前没有待审报告"
            description="分析员提交的研究版本会显示在这里。"
          />
        ) : (
          <div className="grid gap-4 md:grid-cols-2">
            {reports.data.items.map((report) => (
              <Link
                key={report.id}
                href={`/pharma/reports/${report.id}`}
                className="rounded-xl border border-slate-200 p-5 transition-colors hover:border-blue-400"
              >
                <div className="ph-actions mb-3 justify-between">
                  <FileText size={22} className="text-blue-600" aria-hidden />
                  <Badge status={report.state} />
                </div>
                <h3 className="leading-7 font-semibold">{report.title}</h3>
                <p className="mt-3 text-xs text-slate-500">
                  <Timestamp value={report.updated_at} />
                </p>
                <span className="mt-4 inline-flex items-center gap-2 text-sm text-blue-700">
                  阅读并审核
                  <ArrowRight size={14} aria-hidden />
                </span>
              </Link>
            ))}
          </div>
        )}
      </Panel>
      <Pager page={reports} />
      <div className="grid gap-6 xl:grid-cols-2">
        <Panel title="待确认的药物别名">
          {aliases.isLoading ? (
            <Loading />
          ) : aliases.error ? (
            <ErrorPanel
              error={aliases.error}
              onRetry={() => void aliases.refetch()}
            />
          ) : !aliases.data?.items.length ? (
            <Empty title="没有待确认别名" />
          ) : (
            <div className="ph-stack">
              {aliases.data.items.map((item) => (
                <MappingReview
                  key={item.id}
                  item={item}
                  kind="alias"
                  drugName={names.get(item.drug_id) ?? item.drug_id}
                  onComplete={() => aliases.refetch()}
                />
              ))}
            </div>
          )}
          <Pager page={aliases} />
        </Panel>
        <Panel title="待确认的实体关联">
          {links.isLoading ? (
            <Loading />
          ) : links.error ? (
            <ErrorPanel
              error={links.error}
              onRetry={() => void links.refetch()}
            />
          ) : !links.data?.items.length ? (
            <Empty
              title="没有待确认关联"
              description="官方来源检索召回的候选记录需要先确认对象与试验角色。"
            />
          ) : (
            <div className="ph-stack">
              {links.data.items.map((item) => (
                <MappingReview
                  key={item.id}
                  item={item}
                  kind="link"
                  drugName={names.get(item.drug_id) ?? item.drug_id}
                  onComplete={() => links.refetch()}
                />
              ))}
            </div>
          )}
          <Pager page={links} />
        </Panel>
      </div>
    </div>
  );
}
