"use client";

import { useMutation } from "@tanstack/react-query";
import {
  ArrowLeft,
  ArrowRight,
  ExternalLink,
  FlaskConical,
  Plus,
  RefreshCw,
  Search,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useRef, useState, type ReactNode } from "react";

import type {
  AliasPage,
  Change,
  Diff,
  Drug,
  DrugInput,
  DrugPage,
  EntityLink,
  EntityLinkPage,
  Event,
  EventPage,
  EventRevisionPage,
  Job,
  ObservationPage,
  Publication,
  PublicationPage,
  SourceSnapshot,
  Trial,
  TrialPage,
} from "@/core/pharma/contracts";

import { usePharma, useResource } from "./context";
import {
  Badge,
  Coverage,
  DateText,
  Empty,
  ErrorPanel,
  EvidenceButton,
  Field,
  Loading,
  PageHeader,
  Panel,
  Timestamp,
} from "./ui";

type Command = {
  path: string;
  method?: string;
  body?: unknown;
  revision?: number | string;
};

export function usePharmaWrite() {
  const { request, refresh } = usePharma();
  const retry = useRef<{ signature: string; key: string } | null>(null);
  return useMutation({
    mutationFn: async ({ path, ...options }: Command) => {
      const signature = JSON.stringify({ path, ...options });
      if (retry.current?.signature !== signature) {
        retry.current = { signature, key: crypto.randomUUID() };
      }
      const response = await request<Record<string, unknown>>(path, {
        method: "POST",
        ...options,
        idempotencyKey: retry.current.key,
      });
      await refresh();
      retry.current = null;
      return response;
    },
  });
}

export function useUnsavedWarning(dirty: boolean) {
  useEffect(() => {
    if (!dirty) return;
    const warn = (event: BeforeUnloadEvent) => {
      event.preventDefault();
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);
}

export function useListLocation() {
  const router = useRouter();
  const pathname = usePathname();
  const search = useSearchParams();
  const [previous, setPrevious] = useState<string[]>([]);
  const cursor = search.get("cursor") ?? "";
  const update = (changes: Record<string, string>) => {
    const next = new URLSearchParams(search.toString());
    for (const [key, value] of Object.entries(changes)) {
      if (value) next.set(key, value);
      else next.delete(key);
    }
    router.replace(`${pathname}${next.size ? `?${next.toString()}` : ""}`, {
      scroll: false,
    });
  };
  return {
    search,
    cursor,
    filter: (changes: Record<string, string>) => {
      setPrevious([]);
      update({ ...changes, cursor: "" });
    },
    next: (next: string) => {
      setPrevious([...previous, cursor]);
      update({ cursor: next });
    },
    back: () => {
      const next = [...previous];
      update({ cursor: next.pop() ?? "" });
      setPrevious(next);
    },
  };
}

export function Pagination({
  next,
  cursor,
  onNext,
  onBack,
  busy,
}: {
  next?: string | null;
  cursor: string;
  onNext: (cursor: string) => void;
  onBack: () => void;
  busy?: boolean;
}) {
  if (!cursor && !next) return null;
  return (
    <nav className="ph-actions mt-5 justify-end" aria-label="资料分页">
      <button
        className="ph-button-secondary"
        disabled={!cursor || busy}
        onClick={onBack}
      >
        <ArrowLeft size={15} />
        上一批
      </button>
      <button
        className="ph-button-secondary"
        disabled={!next || busy}
        onClick={() => next && onNext(next)}
      >
        下一批
        <ArrowRight size={15} />
      </button>
    </nav>
  );
}

function splitLabels(text: string) {
  return [
    ...new Set(
      text
        .split(/[,，\n]/)
        .map((part) => part.trim())
        .filter(Boolean),
    ),
  ];
}

export function DrugForm({
  initial,
  onSave,
  onCancel,
  busy,
  error,
}: {
  initial?: Drug;
  onSave: (value: DrugInput) => Promise<void>;
  onCancel: () => void;
  busy: boolean;
  error?: unknown;
}) {
  const [name, setName] = useState(initial?.display_name ?? "");
  const [code, setCode] = useState(initial?.development_code ?? "");
  const [description, setDescription] = useState(initial?.description ?? "");
  const [indications, setIndications] = useState(
    initial?.indications.join("，") ?? "",
  );
  const [targets, setTargets] = useState(initial?.targets.join("，") ?? "");
  const [changed, setChanged] = useState(false);
  const [validation, setValidation] = useState("");
  useUnsavedWarning(changed && !busy);
  return (
    <form
      className="ph-stack"
      onChange={() => setChanged(true)}
      onSubmit={async (event) => {
        event.preventDefault();
        if (!name.trim()) {
          setValidation("请填写药物或研究对象名称。");
          return;
        }
        if (
          splitLabels(indications).length > 20 ||
          splitLabels(targets).length > 20
        ) {
          setValidation("每类研究标签最多 20 个。");
          return;
        }
        setValidation("");
        await onSave({
          display_name: name.trim(),
          development_code: code.trim() || null,
          description: description.trim() || null,
          indications: splitLabels(indications),
          targets: splitLabels(targets),
        });
      }}
    >
      <div className="ph-form-grid">
        <Field label="对象名称 *">
          <input
            autoFocus
            className="ph-input"
            required
            maxLength={200}
            value={name}
            onChange={(event) => setName(event.target.value)}
          />
        </Field>
        <Field label="研发代号">
          <input
            className="ph-input"
            maxLength={100}
            value={code}
            onChange={(event) => setCode(event.target.value)}
            placeholder="例如：PX-101"
          />
        </Field>
        <Field
          label="适应证研究标签"
          hint="多个标签用逗号分隔；不代表已批准适应证。"
        >
          <input
            className="ph-input"
            value={indications}
            onChange={(event) => setIndications(event.target.value)}
          />
        </Field>
        <Field label="靶点研究标签" hint="仅作研究分类，不自动认定机制已证实。">
          <input
            className="ph-input"
            value={targets}
            onChange={(event) => setTargets(event.target.value)}
          />
        </Field>
      </div>
      <Field label="档案说明">
        <textarea
          className="ph-textarea"
          rows={3}
          maxLength={3000}
          value={description}
          onChange={(event) => setDescription(event.target.value)}
        />
      </Field>
      {validation && (
        <p className="ph-error" role="alert">
          {validation}
        </p>
      )}
      {!!error && <ErrorPanel error={error} />}
      <div className="ph-actions">
        <button className="ph-button" type="submit" disabled={busy}>
          {busy ? "保存中…" : "保存档案"}
        </button>
        <button
          className="ph-button-secondary"
          type="button"
          disabled={busy}
          onClick={() => {
            if (!changed || window.confirm("尚有未保存的修改，确定放弃吗？"))
              onCancel();
          }}
        >
          取消
        </button>
      </div>
    </form>
  );
}

export function DrugsPage() {
  const { workspace } = usePharma();
  const router = useRouter();
  const location = useListLocation();
  const query = location.search.get("query") ?? "";
  const archived = location.search.get("archived") === "true";
  const [search, setSearch] = useState(query);
  const [creating, setCreating] = useState(false);
  const action = usePharmaWrite();
  const resource = useResource<DrugPage>(
    `/drugs?limit=20&query=${encodeURIComponent(query)}&archived=${archived}&cursor=${encodeURIComponent(location.cursor)}`,
  );
  return (
    <div className="ph-stack">
      <PageHeader
        eyebrow="RESEARCH OBJECTS"
        title="药物档案"
        description="从一个清晰的研究对象开始，连接试验、文献与可追溯的证据。"
        actions={
          workspace.role !== "reader" && (
            <button className="ph-button" onClick={() => setCreating(true)}>
              <Plus size={17} />
              建立档案
            </button>
          )
        }
      />
      {creating && (
        <Panel title="建立研究对象">
          <DrugForm
            busy={action.isPending}
            error={action.error}
            onCancel={() => setCreating(false)}
            onSave={async (value) => {
              try {
                const result = await action.mutateAsync({
                  path: "/drugs",
                  body: value,
                });
                setCreating(false);
                if (typeof result.id === "string")
                  router.push(`/pharma/drugs/${result.id}`);
              } catch {
                /* Keep entered fields and the server error. */
              }
            }}
          />
        </Panel>
      )}
      <Panel>
        <form
          className="ph-actions mb-5"
          onSubmit={(event) => {
            event.preventDefault();
            location.filter({ query: search.trim() });
          }}
        >
          <div className="relative min-w-48 flex-1">
            <Search
              size={17}
              className="pointer-events-none absolute top-3 left-3 text-slate-400"
            />
            <input
              className="ph-input pl-10!"
              aria-label="搜索药物名称、代号或已确认别名"
              placeholder="搜索名称、研发代号或已确认别名"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
            />
          </div>
          <button className="ph-button-secondary" type="submit">
            搜索档案
          </button>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={archived}
              onChange={(event) =>
                location.filter({
                  archived: event.target.checked ? "true" : "",
                })
              }
            />
            已归档
          </label>
        </form>
        {resource.isPending ? (
          <Loading />
        ) : resource.error ? (
          <ErrorPanel
            error={resource.error}
            onRetry={() => void resource.refetch()}
          />
        ) : !resource.data?.items.length ? (
          <Empty
            title={
              query
                ? "没有匹配的档案"
                : archived
                  ? "暂无归档对象"
                  : "建立首个药物档案"
            }
            description={
              query
                ? "尝试调整名称或研发代号。此处只搜索本工作区资料。"
                : "建档后确认别名，即可同步受控官方来源并持续研究进展。"
            }
          />
        ) : (
          <div className="ph-table-wrap">
            <table className="ph-table">
              <thead>
                <tr>
                  <th>研究对象</th>
                  <th>研发代号</th>
                  <th>研究标签</th>
                  <th>档案更新</th>
                  <th>状态</th>
                </tr>
              </thead>
              <tbody>
                {resource.data.items.map((drug) => (
                  <tr key={drug.id}>
                    <td>
                      <Link
                        className="font-semibold text-blue-700"
                        href={`/pharma/drugs/${drug.id}`}
                      >
                        {drug.display_name}
                      </Link>
                      <p className="mt-1 max-w-sm truncate text-xs text-slate-500">
                        {drug.description ?? "暂无档案说明"}
                      </p>
                    </td>
                    <td className="font-mono">
                      {drug.development_code ?? "未提供"}
                    </td>
                    <td>
                      {drug.indications.slice(0, 3).join(" · ") || "尚未添加"}
                    </td>
                    <td>
                      <Timestamp value={drug.updated_at} />
                    </td>
                    <td>
                      <Badge status={drug.archived ? "archived" : "active"}>
                        {drug.archived ? "已归档" : "研究中"}
                      </Badge>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <Pagination
          next={resource.data?.next_cursor}
          cursor={location.cursor}
          onNext={location.next}
          onBack={location.back}
          busy={resource.isFetching}
        />
      </Panel>
    </div>
  );
}

function DetailField({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <div>
      <dt className="mb-1 text-xs text-slate-500">{label}</dt>
      <dd className="text-sm leading-relaxed break-words">{children}</dd>
    </div>
  );
}

function DecisionEditor({ path, title }: { path: string; title: string }) {
  const action = usePharmaWrite();
  const [note, setNote] = useState("");
  const [decision, setDecision] = useState("approve");
  return (
    <details className="mt-3 rounded-lg border border-slate-200 p-3">
      <summary className="cursor-pointer text-sm font-medium text-blue-700">
        审核{title}
      </summary>
      <form
        className="ph-stack mt-3"
        onSubmit={async (event) => {
          event.preventDefault();
          try {
            await action.mutateAsync({
              path,
              body: { decision, note: note.trim() },
            });
            setNote("");
          } catch {
            /* Persistent inline error. */
          }
        }}
      >
        <Field label="审核决定">
          <select
            className="ph-select"
            value={decision}
            onChange={(event) => setDecision(event.target.value)}
          >
            <option value="approve">确认</option>
            <option value="reject">驳回</option>
            <option value="revoke">撤销此前确认</option>
          </select>
        </Field>
        <Field label="审核依据 *">
          <textarea
            className="ph-textarea"
            required
            minLength={1}
            maxLength={2000}
            rows={2}
            value={note}
            onChange={(event) => setNote(event.target.value)}
            placeholder="说明来源依据或歧义，不因名称相似直接合并。"
          />
        </Field>
        {action.error && <ErrorPanel error={action.error} />}
        {action.isSuccess && (
          <p className="ph-notice" role="status">
            审核结果已保存。
          </p>
        )}
        <button
          className="ph-button-secondary"
          disabled={action.isPending || !note.trim()}
        >
          {action.isPending ? "提交中…" : "保存审核决定"}
        </button>
      </form>
    </details>
  );
}

function Aliases({ drugId }: { drugId: string }) {
  const { workspace } = usePharma();
  const aliases = useResource<AliasPage>(`/drugs/${drugId}/aliases?limit=100`);
  const action = usePharmaWrite();
  const [adding, setAdding] = useState(false);
  const [alias, setAlias] = useState("");
  const [namespace, setNamespace] = useState("development_code");
  const [note, setNote] = useState("");
  return (
    <Panel
      title="名称与别名"
      actions={
        workspace.role !== "reader" && (
          <button
            className="ph-button-secondary"
            onClick={() => setAdding(!adding)}
          >
            <Plus size={14} />
            提出别名
          </button>
        )
      }
    >
      <p className="mb-4 text-sm text-slate-500">
        仅已确认的别名用于官方来源发现。相同名称可能对应不同研究对象。
      </p>
      {aliases.isPending ? (
        <Loading />
      ) : aliases.error ? (
        <ErrorPanel error={aliases.error} />
      ) : !aliases.data?.items.length ? (
        <Empty
          title="尚未确认检索别名"
          description="提出别名并填写人工依据，由审核员确认后用于资料召回。"
        />
      ) : (
        <div className="ph-stack">
          {aliases.data.items.map((entry) => (
            <div
              key={entry.id}
              className="rounded-lg border border-slate-200 p-4"
            >
              <div className="flex flex-wrap items-center justify-between gap-2">
                <strong className="text-sm">{entry.alias}</strong>
                <Badge status={entry.status} />
              </div>
              <p className="mt-2 text-sm text-slate-600">{entry.note}</p>
              {entry.evidence_id && <EvidenceButton id={entry.evidence_id} />}
              {["reviewer", "admin"].includes(workspace.role) && (
                <DecisionEditor
                  path={`/aliases/${entry.id}/decision`}
                  title="别名"
                />
              )}
            </div>
          ))}
        </div>
      )}
      {adding && (
        <form
          className="ph-stack mt-5 border-t border-slate-200 pt-5"
          onSubmit={async (event) => {
            event.preventDefault();
            try {
              await action.mutateAsync({
                path: `/drugs/${drugId}/aliases`,
                body: { alias: alias.trim(), namespace, note: note.trim() },
              });
              setAlias("");
              setNote("");
              setAdding(false);
              await aliases.refetch();
            } catch {
              /* Retain draft. */
            }
          }}
        >
          <Field label="别名 *">
            <input
              className="ph-input"
              value={alias}
              required
              maxLength={200}
              onChange={(event) => setAlias(event.target.value)}
            />
          </Field>
          <Field label="名称类型">
            <select
              className="ph-select"
              value={namespace}
              onChange={(event) => setNamespace(event.target.value)}
            >
              <option value="development_code">研发代号</option>
              <option value="common_name">通用名称</option>
              <option value="source_name">来源名称</option>
              <option value="other">其他名称</option>
            </select>
          </Field>
          <Field label="来源依据 / 人工说明 *">
            <textarea
              className="ph-textarea"
              required
              maxLength={2000}
              rows={3}
              value={note}
              onChange={(event) => setNote(event.target.value)}
            />
          </Field>
          {action.error && <ErrorPanel error={action.error} />}
          <button
            className="ph-button"
            disabled={action.isPending || !alias.trim() || !note.trim()}
          >
            {action.isPending ? "提交中…" : "提交待确认别名"}
          </button>
        </form>
      )}
    </Panel>
  );
}

function SyncObject({ drugId }: { drugId: string }) {
  const action = usePharmaWrite();
  const [jobId, setJobId] = useState<string | null>(null);
  const job = useResource<Job>(jobId ? `/jobs/${jobId}` : null, 2500);
  return (
    <div className="ph-stack">
      <div className="ph-actions">
        <button
          className="ph-button-secondary"
          disabled={
            action.isPending ||
            job.data?.state === "queued" ||
            job.data?.state === "running"
          }
          onClick={async () => {
            try {
              const result = await action.mutateAsync({
                path: "/sources/sync",
                body: {
                  sources: ["ctgov", "pubmed"],
                  drug_ids: [drugId],
                  mode: "discovery",
                  record_limit: 50,
                },
              });
              if (typeof result.id === "string") setJobId(result.id);
            } catch {
              /* Display request error. */
            }
          }}
        >
          <RefreshCw size={15} />
          {action.isPending ? "提交同步…" : "同步官方来源"}
        </button>
      </div>
      {action.error && <ErrorPanel error={action.error} />}
      {job.error && <ErrorPanel error={job.error} />}
      {job.data && (
        <div className="ph-notice">
          <div className="mb-2 flex items-center gap-3">
            来源同步
            <Badge status={job.data.state} />
          </div>
          <p className="text-sm">
            已处理 {job.data.progress.processed ?? 0}{" "}
            条；任务状态与资料覆盖分别核对。
          </p>
          <Coverage items={job.data.coverage} />
        </div>
      )}
    </div>
  );
}

export function DrugDetail({ id }: { id: string }) {
  const { workspace } = usePharma();
  const resource = useResource<Drug>(`/drugs/${id}`);
  const trials = useResource<TrialPage>(`/trials?drug_id=${id}&limit=8`);
  const publications = useResource<PublicationPage>(
    `/publications?drug_id=${id}&limit=5`,
  );
  const events = useResource<EventPage>(`/events?drug_id=${id}&limit=8`);
  const [editing, setEditing] = useState(false);
  const action = usePharmaWrite();
  if (resource.isPending) return <Loading />;
  if (resource.error || !resource.data)
    return (
      <ErrorPanel
        error={resource.error}
        onRetry={() => void resource.refetch()}
      />
    );
  const drug = resource.data;
  return (
    <div className="ph-stack">
      <Link
        className="inline-flex items-center gap-2 text-sm text-slate-500"
        href="/pharma/drugs"
      >
        <ArrowLeft size={14} />
        药物档案
      </Link>
      <PageHeader
        eyebrow={drug.development_code ?? "RESEARCH OBJECT"}
        title={drug.display_name}
        description="以研究对象组织公开资料；标签和试验状态不代表监管批准或临床有效性。"
        actions={
          workspace.role !== "reader" && (
            <>
              <Link
                className="ph-button-secondary"
                href={`/pharma/subscriptions?drug_id=${id}&new=true`}
              >
                建立订阅
              </Link>
              <Link
                className="ph-button"
                href={`/pharma/research/new?drug_id=${id}`}
              >
                <FlaskConical size={16} />
                发起研究
              </Link>
            </>
          )
        }
      />
      {editing && (
        <Panel title="编辑档案">
          <DrugForm
            initial={drug}
            busy={action.isPending}
            error={action.error}
            onCancel={() => setEditing(false)}
            onSave={async (value) => {
              try {
                await action.mutateAsync({
                  path: `/drugs/${id}`,
                  method: "PATCH",
                  body: value,
                  revision: drug.revision,
                });
                setEditing(false);
                await resource.refetch();
              } catch {
                /* Preserve conflict information. */
              }
            }}
          />
        </Panel>
      )}
      <div className="grid items-start gap-6 xl:grid-cols-[minmax(0,2fr)_minmax(300px,1fr)]">
        <div className="ph-stack">
          <Panel
            title="研究对象概览"
            actions={
              workspace.role !== "reader" && (
                <button
                  className="ph-button-secondary"
                  onClick={() => setEditing(true)}
                >
                  编辑档案
                </button>
              )
            }
          >
            <dl className="grid gap-5 sm:grid-cols-2">
              <DetailField label="研发代号">
                {drug.development_code ?? "未提供"}
              </DetailField>
              <DetailField label="档案状态">
                <Badge status={drug.archived ? "archived" : "active"}>
                  {drug.archived ? "已归档" : "研究中"}
                </Badge>
              </DetailField>
              <DetailField label="适应证研究标签">
                {drug.indications.join(" · ") || "尚未添加"}
              </DetailField>
              <DetailField label="靶点研究标签">
                {drug.targets.join(" · ") || "尚未添加"}
              </DetailField>
            </dl>
            {drug.description && (
              <p className="mt-5 text-sm leading-7 whitespace-pre-wrap text-slate-600">
                {drug.description}
              </p>
            )}
            {workspace.role !== "reader" && !drug.archived && (
              <div className="mt-5 border-t border-slate-100 pt-5">
                <SyncObject drugId={id} />
              </div>
            )}
          </Panel>
          <Panel
            title="关联临床试验"
            actions={
              <Link
                className="text-sm text-blue-700"
                href={`/pharma/trials?drug_id=${id}`}
              >
                查看全部 →
              </Link>
            }
          >
            {trials.isPending ? (
              <Loading />
            ) : trials.error ? (
              <ErrorPanel error={trials.error} />
            ) : trials.data?.items.length ? (
              <TrialTable items={trials.data.items} />
            ) : (
              <Empty
                title="暂无已确认关联的试验"
                description="同步结果先进入候选关联，由审核员核对研究对象及干预角色。"
              />
            )}
          </Panel>
          <Panel
            title="研究文献"
            actions={
              <Link
                className="text-sm text-blue-700"
                href={`/pharma/literature?drug_id=${id}`}
              >
                查看全部 →
              </Link>
            }
          >
            {publications.isPending ? (
              <Loading />
            ) : publications.error ? (
              <ErrorPanel error={publications.error} />
            ) : publications.data?.items.length ? (
              <PublicationList items={publications.data.items} />
            ) : (
              <Empty
                title="暂无已确认关联的文献"
                description="未检索到不代表不存在；请结合来源覆盖评估。"
              />
            )}
          </Panel>
        </div>
        <aside className="ph-stack">
          <Aliases drugId={id} />
          <Panel title="进展时间线">
            {events.isPending ? (
              <Loading />
            ) : events.error ? (
              <ErrorPanel error={events.error} />
            ) : events.data?.items.length ? (
              <ol className="space-y-5">
                {events.data.items.map((event) => (
                  <li
                    className="border-l-2 border-blue-100 pl-4"
                    key={event.id}
                  >
                    <Link
                      className="text-sm font-semibold text-blue-700"
                      href={`/pharma/events/${event.id}`}
                    >
                      {event.title}
                    </Link>
                    <p className="mt-1 text-xs text-slate-500">
                      系统更新时间 · <Timestamp value={event.updated_at} />
                    </p>
                  </li>
                ))}
              </ol>
            ) : (
              <Empty
                title="尚无已观察到的字段变化"
                description="首次采集建立基线，后续版本会保留前后证据。"
              />
            )}
          </Panel>
          {workspace.role !== "reader" && !drug.archived && (
            <Panel title="档案管理">
              <p className="mb-3 text-sm text-slate-500">
                归档停止后续自动跟踪，已保存证据与报告仍可核对。
              </p>
              <button
                className="ph-button-secondary"
                disabled={action.isPending}
                onClick={async () => {
                  if (
                    !window.confirm(
                      `确定归档“${drug.display_name}”并停止自动跟踪吗？`,
                    )
                  )
                    return;
                  try {
                    await action.mutateAsync({
                      path: `/drugs/${id}/archive`,
                      revision: drug.revision,
                    });
                    await resource.refetch();
                  } catch {
                    /* Inline error. */
                  }
                }}
              >
                归档对象
              </button>
              {!editing && action.error && <ErrorPanel error={action.error} />}
            </Panel>
          )}
        </aside>
      </div>
    </div>
  );
}

function TrialTable({ items }: { items: Trial[] }) {
  return (
    <div className="ph-table-wrap">
      <table className="ph-table">
        <thead>
          <tr>
            <th>临床试验 / 注册号</th>
            <th>阶段</th>
            <th>招募状态</th>
            <th>入组数量</th>
            <th>来源更新</th>
          </tr>
        </thead>
        <tbody>
          {items.map((trial) => (
            <tr key={trial.id}>
              <td>
                <Link
                  className="line-clamp-2 max-w-md font-medium text-blue-700"
                  href={`/pharma/trials/${trial.id}`}
                >
                  {trial.current_projection.title}
                </Link>
                <p className="mt-1 font-mono text-xs text-slate-500">
                  {trial.external_id}
                  {trial.is_demo ? " · DEMO" : ""}
                </p>
              </td>
              <td>
                {trial.current_projection.phases.join(" / ") ||
                  "不适用 / 未提供"}
              </td>
              <td>
                <Badge status={trial.current_projection.status} />
              </td>
              <td>
                {trial.current_projection.enrollment ? (
                  <>
                    {trial.current_projection.enrollment.count}
                    <span className="ml-1 text-xs text-slate-500">
                      {trial.current_projection.enrollment.type === "actual"
                        ? "实际"
                        : trial.current_projection.enrollment.type ===
                            "estimated"
                          ? "预计"
                          : "类型未知"}
                    </span>
                  </>
                ) : (
                  "来源未提供"
                )}
              </td>
              <td>
                <DateText value={trial.current_projection.source_updated} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function PublicationList({ items }: { items: Publication[] }) {
  return (
    <div className="divide-y divide-slate-100">
      {items.map((publication) => (
        <article key={publication.id} className="py-5 first:pt-0 last:pb-0">
          <div className="mb-2 flex flex-wrap items-center gap-2">
            <Badge status="pubmed">PubMed</Badge>
            {publication.is_demo && <Badge status="demo">DEMO</Badge>}
            <span className="font-mono text-xs text-slate-500">
              PMID {publication.external_id}
            </span>
          </div>
          <Link
            href={`/pharma/literature/${publication.id}`}
            className="leading-relaxed font-semibold text-blue-700"
          >
            {publication.current_projection.title}
          </Link>
          <p className="mt-2 text-sm text-slate-500">
            {publication.current_projection.journal ?? "期刊未提供"} ·{" "}
            <DateText value={publication.current_projection.publication_date} />
          </p>
          <p className="mt-3 line-clamp-2 text-sm leading-6 text-slate-600">
            {publication.current_projection.abstract_text ??
              "来源未提供摘要，当前仅保留文献元数据。"}
          </p>
        </article>
      ))}
    </div>
  );
}

function RecordList({ kind }: { kind: "trial" | "publication" }) {
  const location = useListLocation();
  const [search, setSearch] = useState(location.search.get("query") ?? "");
  const params = new URLSearchParams({ limit: "20" });
  for (const key of [
    "query",
    "cursor",
    "drug_id",
    "status",
    "has_results",
    "observed_since",
  ]) {
    const value = location.search.get(key);
    if (value) params.set(key, value);
  }
  const resource = useResource<TrialPage | PublicationPage>(
    `/${kind === "trial" ? "trials" : "publications"}?${params.toString()}`,
  );
  const isTrial = kind === "trial";
  return (
    <div className="ph-stack">
      <PageHeader
        eyebrow={isTrial ? "CLINICAL TRIALS" : "RESEARCH LITERATURE"}
        title={isTrial ? "临床试验" : "研究文献"}
        description={
          isTrial
            ? "跟踪注册记录的真实变化，把状态、日期与结果结构分别理解。"
            : "阅读文献元数据与原始摘要，沿着版本化引用核对研究依据。"
        }
      />
      <Panel>
        <form
          className="ph-actions mb-5"
          onSubmit={(event) => {
            event.preventDefault();
            location.filter({ query: search.trim() });
          }}
        >
          <input
            aria-label={
              isTrial ? "搜索试验标题或注册号" : "搜索文献标题或 PMID"
            }
            className="ph-input min-w-48 flex-1"
            placeholder={
              isTrial ? "搜索试验标题、NCT 标识" : "搜索文献标题、PMID"
            }
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
          <button className="ph-button-secondary">
            <Search size={15} />
            搜索资料
          </button>
          {isTrial && (
            <>
              <select
                aria-label="招募状态"
                className="ph-select w-auto!"
                value={location.search.get("status") ?? ""}
                onChange={(event) =>
                  location.filter({ status: event.target.value })
                }
              >
                <option value="">全部招募状态</option>
                <option value="RECRUITING">招募中</option>
                <option value="NOT_YET_RECRUITING">尚未招募</option>
                <option value="ACTIVE_NOT_RECRUITING">进行中，不再招募</option>
                <option value="COMPLETED">已完成</option>
                <option value="TERMINATED">已终止</option>
                <option value="SUSPENDED">已暂停</option>
                <option value="WITHDRAWN">已撤回</option>
                <option value="UNKNOWN">未知</option>
              </select>
              <select
                aria-label="结果结构"
                className="ph-select w-auto!"
                value={location.search.get("has_results") ?? ""}
                onChange={(event) =>
                  location.filter({ has_results: event.target.value })
                }
              >
                <option value="">全部结果状态</option>
                <option value="true">已提供结果结构</option>
                <option value="false">未提供结果结构</option>
              </select>
            </>
          )}
          {location.search.get("drug_id") && (
            <button
              type="button"
              className="ph-button-secondary"
              onClick={() => location.filter({ drug_id: "" })}
            >
              清除对象筛选 ×
            </button>
          )}
        </form>
        {resource.isPending ? (
          <Loading />
        ) : resource.error ? (
          <ErrorPanel
            error={resource.error}
            onRetry={() => void resource.refetch()}
          />
        ) : !resource.data?.items.length ? (
          <Empty
            title={
              params.has("query") ||
              params.has("drug_id") ||
              params.has("status") ||
              params.has("has_results") ||
              params.has("observed_since")
                ? "没有符合筛选条件的资料"
                : "尚未同步此类资料"
            }
            description="列表仅覆盖当前工作区已摄入资料。可前往药物档案确认别名并同步官方来源。"
            action={
              <Link className="ph-button-secondary" href="/pharma/drugs">
                前往药物档案
              </Link>
            }
          />
        ) : isTrial ? (
          <TrialTable items={resource.data.items as Trial[]} />
        ) : (
          <PublicationList items={resource.data.items as Publication[]} />
        )}
        <Pagination
          next={resource.data?.next_cursor}
          cursor={location.cursor}
          onNext={location.next}
          onBack={location.back}
          busy={resource.isFetching}
        />
      </Panel>
      <p className="text-xs leading-6 text-slate-500">
        {isTrial
          ? "试验完成不等于研发成功。结果结构的存在不代表结果积极，也不代表监管批准。"
          : "仅元数据与可获得摘要；全文摄入未启用，不自动访问付费内容。"}
      </p>
    </div>
  );
}

export function TrialsPage() {
  return <RecordList kind="trial" />;
}
export function LiteraturePage() {
  return <RecordList kind="publication" />;
}

export function ChangeList({ changes }: { changes: Change[] }) {
  if (!changes.length)
    return (
      <Empty
        title="内容未变化"
        description="本次抓取已记录，内容快照可被重复观察引用。"
      />
    );
  return (
    <div className="space-y-4">
      {changes.map((change, index) => (
        <section
          className="overflow-hidden rounded-lg border border-slate-200"
          key={`${change.path}:${index}`}
        >
          <div className="flex flex-wrap items-center justify-between gap-2 bg-slate-50 px-4 py-3">
            <code className="text-xs">{change.path}</code>
            <Badge status={change.type}>
              {change.type === "added"
                ? "新增字段"
                : change.type === "removed"
                  ? "字段移除"
                  : "字段变化"}
            </Badge>
          </div>
          <div className="grid divide-y divide-slate-100 sm:grid-cols-2 sm:divide-x sm:divide-y-0">
            <div className="min-w-0 p-4">
              <p className="mb-2 text-xs text-slate-500">此前观察</p>
              <pre className="text-sm break-words whitespace-pre-wrap">
                {change.type === "added"
                  ? "此前未提供此字段"
                  : JSON.stringify(change.before, null, 2)}
              </pre>
            </div>
            <div className="min-w-0 p-4">
              <p className="mb-2 text-xs text-slate-500">本次观察</p>
              <pre className="text-sm break-words whitespace-pre-wrap">
                {change.type === "removed"
                  ? "本次已移除此字段"
                  : JSON.stringify(change.after, null, 2)}
              </pre>
            </div>
          </div>
        </section>
      ))}
    </div>
  );
}

function RecordHistory({ recordId }: { recordId: string }) {
  const [cursor, setCursor] = useState("");
  const observations = useResource<ObservationPage>(
    `/records/${recordId}/observations?limit=30&cursor=${encodeURIComponent(cursor)}`,
  );
  const successful =
    observations.data?.items.filter((observation) => observation.snapshot_id) ??
    [];
  const [selectedBefore, setBefore] = useState("");
  const [selectedAfter, setAfter] = useState("");
  const [snapshotId, setSnapshotId] = useState<string | null>(null);
  const before =
    selectedBefore !== "" ? selectedBefore : (successful[1]?.id ?? "");
  const after =
    selectedAfter !== "" ? selectedAfter : (successful[0]?.id ?? "");
  const diff = useResource<Diff>(
    before && after
      ? `/records/${recordId}/diff?before_observation_id=${before}&after_observation_id=${after}`
      : null,
  );
  const snapshot = useResource<SourceSnapshot>(
    snapshotId ? `/snapshots/${snapshotId}` : null,
  );
  return (
    <Panel title="版本观察与字段对比">
      <p className="mb-5 text-sm leading-6 text-slate-500">
        比较两次观察，而非假定每次抓取都是新版本。来源回退时可复用此前快照；失败观察不覆盖有效资料。
      </p>
      {observations.isPending ? (
        <Loading />
      ) : observations.error ? (
        <ErrorPanel error={observations.error} />
      ) : (
        <>
          <div className="ph-form-grid mb-5">
            <Field label="此前观察">
              <select
                className="ph-select"
                value={before}
                onChange={(event) => setBefore(event.target.value)}
              >
                <option value="">选择此前观察</option>
                {successful.map((item) => (
                  <option key={item.id} value={item.id}>
                    #{item.observation_seq} ·{" "}
                    {new Date(item.fetched_at).toLocaleString("zh-CN")} ·{" "}
                    {item.outcome}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="本次观察">
              <select
                className="ph-select"
                value={after}
                onChange={(event) => setAfter(event.target.value)}
              >
                <option value="">选择本次观察</option>
                {successful.map((item) => (
                  <option key={item.id} value={item.id}>
                    #{item.observation_seq} ·{" "}
                    {new Date(item.fetched_at).toLocaleString("zh-CN")} ·{" "}
                    {item.outcome}
                  </option>
                ))}
              </select>
            </Field>
          </div>
          {before && after ? (
            diff.isPending ? (
              <Loading />
            ) : diff.error ? (
              <ErrorPanel error={diff.error} />
            ) : (
              diff.data && (
                <>
                  <ChangeList changes={diff.data.changes} />
                  <div className="ph-actions mt-4">
                    {[...new Set(diff.data.evidence_ids)].map((id, index) => (
                      <EvidenceButton
                        key={id}
                        id={id}
                        label={`核对证据 ${index + 1}`}
                      />
                    ))}
                  </div>
                </>
              )
            )
          ) : (
            <Empty
              title="尚不足两次成功观察"
              description="当前版本作为基线保留，下一次同步后可核对变化。"
            />
          )}
          <details className="mt-5 rounded-lg border border-slate-200 p-4">
            <summary className="cursor-pointer text-sm font-semibold">
              查看抓取观察记录
            </summary>
            <div className="ph-table-wrap mt-3">
              <table className="ph-table">
                <thead>
                  <tr>
                    <th>观察序号</th>
                    <th>抓取时间</th>
                    <th>结果</th>
                    <th>快照</th>
                  </tr>
                </thead>
                <tbody>
                  {observations.data?.items.map((item) => (
                    <tr key={item.id}>
                      <td>#{item.observation_seq}</td>
                      <td>
                        <Timestamp value={item.fetched_at} />
                      </td>
                      <td>
                        <Badge status={item.outcome} />
                        {item.error_code && (
                          <p className="text-xs text-red-700">
                            {item.error_code}
                          </p>
                        )}
                      </td>
                      <td>
                        {item.snapshot_id ? (
                          <button
                            className="text-sm text-blue-700 underline underline-offset-4"
                            onClick={() => setSnapshotId(item.snapshot_id)}
                          >
                            查看原始快照
                          </button>
                        ) : (
                          "本次无快照"
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Pagination
              next={observations.data?.next_cursor}
              cursor={cursor}
              onNext={(next) => {
                setCursor(next);
                setBefore("");
                setAfter("");
              }}
              onBack={() => {
                setCursor("");
                setBefore("");
                setAfter("");
              }}
            />
          </details>
        </>
      )}
      {snapshotId && (
        <section className="mt-5 rounded-lg border border-blue-200 bg-blue-50/40 p-4">
          <div className="mb-3 flex items-center justify-between">
            <h3 className="font-semibold">不可变来源快照</h3>
            <button
              className="ph-button-secondary"
              onClick={() => setSnapshotId(null)}
            >
              收起
            </button>
          </div>
          {snapshot.isPending ? (
            <Loading />
          ) : snapshot.error ? (
            <ErrorPanel error={snapshot.error} />
          ) : (
            snapshot.data && (
              <>
                <p className="mb-2 font-mono text-xs break-all text-slate-500">
                  SHA-256 {snapshot.data.content_hash}
                </p>
                <p className="mb-4 text-sm">
                  首次观察：
                  <Timestamp value={snapshot.data.first_observed_at} /> ·{" "}
                  {snapshot.data.normalizer_version}
                </p>
                <details>
                  <summary className="cursor-pointer text-sm font-medium">
                    规范化字段
                  </summary>
                  <pre className="mt-3 max-h-96 overflow-auto text-xs break-all whitespace-pre-wrap">
                    {JSON.stringify(snapshot.data.normalized, null, 2)}
                  </pre>
                </details>
                <details className="mt-3">
                  <summary className="cursor-pointer text-sm font-medium">
                    已保存的原始来源数据
                  </summary>
                  <pre className="mt-3 max-h-96 overflow-auto text-xs break-all whitespace-pre-wrap">
                    {JSON.stringify(snapshot.data.raw_payload, null, 2)}
                  </pre>
                </details>
              </>
            )
          )}
        </section>
      )}
    </Panel>
  );
}

const RELATIONS: Record<EntityLink["relation"], string> = {
  investigational: "研究干预",
  comparator: "对照干预",
  background: "背景治疗",
  unspecified: "角色尚未确认",
  mentions: "文献提及",
};

function RecordLinks({ recordId }: { recordId: string }) {
  const { workspace } = usePharma();
  const links = useResource<EntityLinkPage>(
    `/entity-links?record_id=${recordId}&limit=100`,
  );
  const drugs = useResource<DrugPage>("/drugs?limit=100");
  return (
    <Panel title="药物关联与研究角色">
      {links.isPending ? (
        <Loading />
      ) : links.error ? (
        <ErrorPanel error={links.error} />
      ) : !links.data?.items.length ? (
        <Empty
          title="暂无已提出的药物关联"
          description="请从药物档案发起来源同步，召回候选资料后确认关联。"
        />
      ) : (
        <div className="ph-stack">
          {links.data.items.map((link) => (
            <div
              className="rounded-lg border border-slate-200 p-4"
              key={link.id}
            >
              <Link
                className="text-sm font-semibold text-blue-700"
                href={`/pharma/drugs/${link.drug_id}`}
              >
                {drugs.data?.items.find((drug) => drug.id === link.drug_id)
                  ?.display_name ?? "查看关联研究对象"}
              </Link>
              <div className="mt-2 flex flex-wrap items-center gap-2">
                <Badge status={link.status} />
                <span className="text-xs text-slate-500">
                  {RELATIONS[link.relation]}
                </span>
              </div>
              <p className="mt-2 text-sm leading-6 text-slate-600">
                {link.note}
              </p>
              {link.evidence_id && <EvidenceButton id={link.evidence_id} />}
              {["reviewer", "admin"].includes(workspace.role) && (
                <DecisionEditor
                  path={`/entity-links/${link.id}/decision`}
                  title="关联"
                />
              )}
            </div>
          ))}
        </div>
      )}
    </Panel>
  );
}

function SourceLink({ record }: { record: Trial | Publication }) {
  const href =
    record.source === "ctgov" && /^NCT\d{8}$/.test(record.external_id)
      ? `https://clinicaltrials.gov/study/${record.external_id}`
      : record.source === "pubmed" && /^[1-9]\d{0,11}$/.test(record.external_id)
        ? `https://pubmed.ncbi.nlm.nih.gov/${record.external_id}/`
        : null;
  return href && !record.is_demo ? (
    <a
      className="ph-button-secondary"
      href={href}
      target="_blank"
      rel="noopener noreferrer"
    >
      <ExternalLink size={15} />
      查看官方来源
    </a>
  ) : record.is_demo ? (
    <Badge status="demo">虚构演示资料 · 无官方链接</Badge>
  ) : (
    <Badge status="unknown">来源标识无法生成官方链接</Badge>
  );
}

export function TrialDetail({ id }: { id: string }) {
  const resource = useResource<Trial>(`/trials/${id}`);
  if (resource.isPending) return <Loading />;
  if (resource.error || !resource.data)
    return <ErrorPanel error={resource.error} />;
  const record = resource.data;
  const trial = record.current_projection;
  return (
    <div className="ph-stack">
      <Link
        className="inline-flex items-center gap-2 text-sm text-slate-500"
        href="/pharma/trials"
      >
        <ArrowLeft size={14} />
        临床试验
      </Link>
      <PageHeader
        eyebrow={record.external_id}
        title={trial.title}
        description="ClinicalTrials.gov 注册记录 · 按来源字段如实呈现"
        actions={<SourceLink record={record} />}
      />
      <div className="grid items-start gap-6 xl:grid-cols-[minmax(0,2fr)_minmax(300px,1fr)]">
        <div className="ph-stack">
          <Panel title="试验信息">
            <dl className="grid gap-6 sm:grid-cols-2">
              <DetailField label="招募状态">
                <Badge status={trial.status} />
                {trial.raw_status !== trial.status && (
                  <span className="ml-2 text-xs">
                    来源原值：{trial.raw_status ?? "未提供"}
                  </span>
                )}
              </DetailField>
              <DetailField label="研究阶段">
                {trial.phases.join(" / ") || "不适用 / 来源未提供"}
              </DetailField>
              <DetailField label="研究条件 / 疾病">
                {trial.conditions.join(" · ") || "来源未提供"}
              </DetailField>
              <DetailField label="申办者">
                {trial.sponsor ?? "来源未提供"}
              </DetailField>
              <DetailField label="入组数量">
                {trial.enrollment
                  ? `${trial.enrollment.count}（${trial.enrollment.type === "actual" ? "实际" : trial.enrollment.type === "estimated" ? "预计" : "类型未知"}）`
                  : "来源未提供"}
              </DetailField>
              <DetailField label="是否提供结果结构">
                {trial.has_results === null
                  ? "来源未提供"
                  : trial.has_results
                    ? "已提供；不代表结果积极"
                    : "尚未提供结果结构"}
              </DetailField>
              <DetailField label="来源更新时间">
                <DateText value={trial.source_updated} />
              </DetailField>
              <DetailField label="预计 / 实际开始">
                <DateText value={trial.start_date} />
              </DetailField>
              <DetailField label="主要完成日期">
                <DateText value={trial.primary_completion_date} />
              </DetailField>
              <DetailField label="研究完成日期">
                <DateText value={trial.completion_date} />
              </DetailField>
            </dl>
          </Panel>
          <Panel title="研究干预">
            {trial.interventions?.length ? (
              <div className="ph-stack">
                {trial.interventions.map((item, index) => (
                  <div
                    key={`${item.name}:${index}`}
                    className="border-b border-slate-100 pb-4 last:border-0 last:pb-0"
                  >
                    <h3 className="text-sm font-semibold">{item.name}</h3>
                    <p className="mt-1 text-xs text-slate-500">
                      {item.type ?? "类型未提供"} · 来源分组：
                      {item.arm_group_labels.join("、") || "未提供"}
                    </p>
                    {item.description && (
                      <p className="mt-2 text-sm leading-6 whitespace-pre-wrap">
                        {item.description}
                      </p>
                    )}
                  </div>
                ))}
              </div>
            ) : (
              <Empty
                title="来源未提供干预字段"
                description="不会仅凭名称推断研究药物或对照角色。"
              />
            )}
          </Panel>
          <Panel title="主要终点描述">
            {trial.primary_outcomes.length ? (
              <div className="ph-stack">
                {trial.primary_outcomes.map((outcome, index) => (
                  <section key={`${outcome.measure}:${index}`}>
                    <h3 className="text-sm font-semibold">{outcome.measure}</h3>
                    <p className="mt-1 text-xs text-slate-500">
                      观察窗口：{outcome.time_frame ?? "来源未提供"}
                    </p>
                    {outcome.description && (
                      <p className="mt-2 text-sm leading-7 whitespace-pre-wrap">
                        {outcome.description}
                      </p>
                    )}
                  </section>
                ))}
              </div>
            ) : (
              <Empty title="来源未提供主要终点" />
            )}
          </Panel>
          <RecordHistory recordId={id} />
        </div>
        <aside className="ph-stack">
          <div className="ph-notice">
            试验状态、结果结构和监管批准是不同概念。本页不提供有效性或成功率认证。
          </div>
          <RecordLinks recordId={id} />
        </aside>
      </div>
    </div>
  );
}

export function PublicationDetail({ id }: { id: string }) {
  const resource = useResource<Publication>(`/publications/${id}`);
  if (resource.isPending) return <Loading />;
  if (resource.error || !resource.data)
    return <ErrorPanel error={resource.error} />;
  const record = resource.data;
  const publication = record.current_projection;
  return (
    <div className="ph-stack">
      <Link
        className="inline-flex items-center gap-2 text-sm text-slate-500"
        href="/pharma/literature"
      >
        <ArrowLeft size={14} />
        研究文献
      </Link>
      <PageHeader
        eyebrow={`PUBMED · ${record.external_id}`}
        title={publication.title}
        description="保留来源原文与日期精度，摘要缺失不等于没有研究结论。"
        actions={<SourceLink record={record} />}
      />
      <div className="grid items-start gap-6 xl:grid-cols-[minmax(0,2fr)_minmax(300px,1fr)]">
        <div className="ph-stack">
          <Panel title="文献资料">
            <dl className="grid gap-5 sm:grid-cols-2">
              <DetailField label="作者">
                {publication.authors.join(" · ") || "来源未提供"}
              </DetailField>
              <DetailField label="期刊">
                {publication.journal ?? "来源未提供"}
              </DetailField>
              <DetailField label="发表日期">
                <DateText value={publication.publication_date} />
              </DetailField>
              <DetailField label="文献类型">
                {publication.publication_types.join(" · ") || "来源未提供"}
              </DetailField>
              <DetailField label="PMID">
                <span className="font-mono">{publication.pmid}</span>
              </DetailField>
              <DetailField label="DOI">
                <span className="font-mono">
                  {publication.doi ?? "来源未提供"}
                </span>
              </DetailField>
            </dl>
          </Panel>
          <Panel title="原始摘要">
            {publication.abstract_text ? (
              <p className="text-[15px] leading-8 whitespace-pre-wrap text-slate-700">
                {publication.abstract_text}
              </p>
            ) : (
              <Empty
                title="来源未提供摘要"
                description="当前仅可核对元数据，不能据此推断研究结果。"
              />
            )}
            <p className="mt-5 border-t border-slate-100 pt-4 text-xs text-slate-500">
              保留来源语言 · 仅元数据 / 摘要 · 未摄入全文
            </p>
          </Panel>
          {publication.correction_relations.length > 0 && (
            <Panel title="来源提供的撤稿 / 更正关系">
              <ul className="space-y-3">
                {publication.correction_relations.map((relation) => (
                  <li
                    key={`${relation.relation}:${relation.external_id}`}
                    className="ph-notice"
                  >
                    {relation.relation} · PMID {relation.external_id}
                  </li>
                ))}
              </ul>
            </Panel>
          )}
          <RecordHistory recordId={id} />
        </div>
        <aside>
          <RecordLinks recordId={id} />
        </aside>
      </div>
    </div>
  );
}

export function EventDetail({ id }: { id: string }) {
  const resource = useResource<Event>(`/events/${id}`);
  const [cursor, setCursor] = useState("");
  const revisions = useResource<EventRevisionPage>(
    `/events/${id}/revisions?limit=20&cursor=${encodeURIComponent(cursor)}`,
  );
  if (resource.isPending) return <Loading />;
  if (resource.error || !resource.data)
    return <ErrorPanel error={resource.error} />;
  return (
    <div className="ph-stack">
      <PageHeader
        eyebrow="OBSERVATION HISTORY"
        title={resource.data.title}
        description="以观察顺序追踪每一次有意义的变化。系统发现时间不替代真实临床事件日期。"
      />
      <Panel title="事件版本时间线">
        {revisions.isPending ? (
          <Loading />
        ) : revisions.error ? (
          <ErrorPanel error={revisions.error} />
        ) : revisions.data?.items.length ? (
          <div className="space-y-8">
            {revisions.data.items.map((revision) => (
              <section key={revision.id}>
                <div className="mb-4 flex flex-wrap items-center gap-3">
                  <strong>变化版本 {revision.revision_no}</strong>
                  <Badge status={revision.severity} />
                  <span className="text-xs text-slate-500">
                    系统发现 · <Timestamp value={revision.observed_at} />
                  </span>
                </div>
                <ChangeList changes={revision.changes} />
                <div className="ph-actions mt-4">
                  {revision.evidence_ids.map((evidence, index) => (
                    <EvidenceButton
                      key={evidence}
                      id={evidence}
                      label={`核对证据 ${index + 1}`}
                    />
                  ))}
                </div>
              </section>
            ))}
          </div>
        ) : (
          <Empty title="暂无可访问的事件版本" />
        )}
        <Pagination
          next={revisions.data?.next_cursor}
          cursor={cursor}
          onNext={setCursor}
          onBack={() => setCursor("")}
        />
      </Panel>
    </div>
  );
}
