"use client";

import { BellPlus, CalendarClock, Pause, Play, Plus } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useState } from "react";

import type {
  Drug,
  DrugPage,
  Schedule,
  SchedulePreview,
  Source,
  Subscription,
  SubscriptionInput,
  SubscriptionPage,
} from "@/core/pharma/contracts";

import { usePharma, useResource } from "./context";
import {
  Pagination,
  useListLocation,
  usePharmaWrite,
  useUnsavedWarning,
} from "./entity-pages";
import {
  Badge,
  Empty,
  ErrorPanel,
  Field,
  Loading,
  PageHeader,
  Panel,
  Timestamp,
} from "./ui";

const DAYS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"];

export function subscriptionInput(
  subscription: Subscription,
  enabled = subscription.enabled,
): SubscriptionInput {
  return {
    name: subscription.name,
    drug_ids: [...subscription.drug_ids],
    source_allowlist: [...subscription.source_allowlist],
    schedule: { ...subscription.schedule },
    channels: [...subscription.channels],
    enabled,
  };
}

export function SubscriptionForm({
  initial,
  initialDrugId,
  drugs,
  emailEnabled,
  busy,
  error,
  onSave,
  onCancel,
  onPreview,
}: {
  initial?: Subscription;
  initialDrugId?: string;
  drugs: Drug[];
  emailEnabled: boolean;
  busy: boolean;
  error?: unknown;
  onSave: (value: SubscriptionInput) => Promise<void>;
  onCancel: () => void;
  onPreview: (value: Schedule) => Promise<SchedulePreview>;
}) {
  const [name, setName] = useState(initial?.name ?? "");
  const [drugIds, setDrugIds] = useState(
    initial?.drug_ids ?? (initialDrugId ? [initialDrugId] : []),
  );
  const [sources, setSources] = useState<Source[]>(
    initial?.source_allowlist ?? ["ctgov", "pubmed"],
  );
  const [channels, setChannels] = useState<SubscriptionInput["channels"]>(
    initial?.channels ?? ["in_app"],
  );
  const [enabled, setEnabled] = useState(initial?.enabled ?? true);
  const [schedule, setSchedule] = useState<Schedule>(
    initial?.schedule ?? {
      frequency: "weekly",
      local_time: "09:00",
      weekday: 1,
      timezone: "Asia/Shanghai",
    },
  );
  const [dirty, setDirty] = useState(false);
  const [validation, setValidation] = useState("");
  const [preview, setPreview] = useState<{
    input: string;
    data: SchedulePreview;
  } | null>(null);
  const [previewError, setPreviewError] = useState<unknown>(null);
  const [previewBusy, setPreviewBusy] = useState(false);
  useUnsavedWarning(dirty && !busy);
  const previewCurrent = preview?.input === JSON.stringify(schedule);
  const toggleDrug = (id: string) =>
    setDrugIds((current) =>
      current.includes(id)
        ? current.filter((value) => value !== id)
        : [...current, id],
    );
  const selectedMissing = drugIds.filter(
    (id) => !drugs.some((drug) => drug.id === id),
  );
  return (
    <form
      className="ph-stack"
      onChange={() => setDirty(true)}
      onSubmit={async (event) => {
        event.preventDefault();
        if (
          !name.trim() ||
          !drugIds.length ||
          drugIds.length > 5 ||
          !sources.length ||
          !channels.length
        ) {
          setValidation(
            "请填写订阅名称，选择 1～5 个研究对象、至少一个来源和交付渠道。",
          );
          return;
        }
        if (enabled && channels.includes("email") && !emailEnabled) {
          setValidation("邮件交付未启用，请移除邮件渠道或暂停订阅。");
          return;
        }
        try {
          new Intl.DateTimeFormat("zh-CN", {
            timeZone: schedule.timezone,
          }).format();
        } catch {
          setValidation("请输入有效的 IANA 时区，例如 Asia/Shanghai。");
          return;
        }
        setValidation("");
        await onSave({
          name: name.trim(),
          drug_ids: drugIds,
          source_allowlist: sources,
          schedule,
          channels,
          enabled,
        });
      }}
    >
      <Field label="订阅名称 *">
        <input
          autoFocus
          className="ph-input"
          required
          maxLength={200}
          value={name}
          onChange={(event) => setName(event.target.value)}
          placeholder="例如：PX-101 每周研发进展"
        />
      </Field>
      <fieldset>
        <legend className="mb-2 text-sm font-medium">
          关注的研究对象 *{" "}
          <span className="ml-2 text-xs font-normal text-slate-500">
            {drugIds.length} / 5
          </span>
        </legend>
        <div className="grid max-h-64 gap-2 overflow-y-auto rounded-lg border border-slate-200 p-3 sm:grid-cols-2">
          {drugs.map((drug) => (
            <label
              className={`flex items-start gap-3 rounded-lg p-3 text-sm ${drugIds.includes(drug.id) ? "bg-blue-50" : "bg-slate-50"}`}
              key={drug.id}
            >
              <input
                className="mt-1"
                type="checkbox"
                checked={drugIds.includes(drug.id)}
                disabled={!drugIds.includes(drug.id) && drugIds.length >= 5}
                onChange={() => toggleDrug(drug.id)}
              />
              <span>
                <strong className="block font-medium">
                  {drug.display_name}
                </strong>
                <span className="text-xs text-slate-500">
                  {drug.development_code ?? "暂无研发代号"}
                </span>
              </span>
            </label>
          ))}
          {!drugs.length && (
            <p className="p-2 text-sm text-slate-500">
              尚无可订阅对象，请先建立药物档案。
            </p>
          )}
          {selectedMissing.map((id) => (
            <label className="flex gap-2 p-2 text-xs text-amber-800" key={id}>
              <input type="checkbox" checked onChange={() => toggleDrug(id)} />
              此前选择的对象不在本批列表 / 已归档（可取消选择）
            </label>
          ))}
        </div>
      </fieldset>
      <fieldset>
        <legend className="mb-3 text-sm font-medium">必需来源 *</legend>
        <div className="ph-actions">
          {(["ctgov", "pubmed"] as const).map((source) => (
            <label className="flex items-center gap-2 text-sm" key={source}>
              <input
                type="checkbox"
                checked={sources.includes(source)}
                onChange={() =>
                  setSources(
                    sources.includes(source)
                      ? sources.filter((value) => value !== source)
                      : [...sources, source],
                  )
                }
              />
              {source === "ctgov" ? "ClinicalTrials.gov" : "PubMed"}
            </label>
          ))}
        </div>
        <p className="mt-2 text-xs leading-6 text-slate-500">
          必需来源失败时显示部分完成，不能当作“没有新增资料”。
        </p>
      </fieldset>
      <div className="ph-form-grid">
        <Field label="频率">
          <select
            className="ph-select"
            value={schedule.frequency}
            onChange={(event) => {
              const frequency = event.target.value as Schedule["frequency"];
              setSchedule({
                ...schedule,
                frequency,
                weekday: frequency === "daily" ? null : (schedule.weekday ?? 1),
              });
            }}
          >
            <option value="daily">每天</option>
            <option value="weekly">每周</option>
          </select>
        </Field>
        {schedule.frequency === "weekly" && (
          <Field label="星期">
            <select
              className="ph-select"
              value={schedule.weekday ?? 1}
              onChange={(event) =>
                setSchedule({
                  ...schedule,
                  weekday: Number(event.target.value),
                })
              }
            >
              {DAYS.map((day, index) => (
                <option key={day} value={index + 1}>
                  {day}
                </option>
              ))}
            </select>
          </Field>
        )}
        <Field label="当地时间">
          <input
            className="ph-input"
            type="time"
            required
            value={schedule.local_time}
            onChange={(event) =>
              setSchedule({ ...schedule, local_time: event.target.value })
            }
          />
        </Field>
        <Field label="IANA 时区">
          <input
            className="ph-input"
            list="pharma-subscription-timezones"
            required
            maxLength={100}
            value={schedule.timezone}
            onChange={(event) =>
              setSchedule({ ...schedule, timezone: event.target.value })
            }
          />
          <datalist id="pharma-subscription-timezones">
            <option value="Asia/Shanghai" />
            <option value="America/Los_Angeles" />
            <option value="Europe/London" />
            <option value="UTC" />
          </datalist>
        </Field>
      </div>
      <section className="rounded-lg border border-slate-200 bg-slate-50 p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <p className="max-w-lg text-xs leading-6 text-slate-500">
            夏令时跳过的当地时刻顺延到下一合法时刻；重复时刻只触发第一次。预览来自后端实际排程规则。
          </p>
          <button
            className="ph-button-secondary"
            type="button"
            disabled={previewBusy || busy}
            onClick={async () => {
              setPreviewBusy(true);
              setPreviewError(null);
              const input = JSON.stringify(schedule);
              try {
                const data = await onPreview(schedule);
                setPreview({ input, data });
              } catch (error) {
                setPreviewError(error);
              } finally {
                setPreviewBusy(false);
              }
            }}
          >
            <CalendarClock size={15} />
            {previewBusy ? "计算中…" : "预览未来 5 次"}
          </button>
        </div>
        {!!previewError && <ErrorPanel error={previewError} />}
        {preview && !previewCurrent && (
          <p className="mt-3 text-xs text-amber-800">
            排程已修改，请重新预览。
          </p>
        )}
        {previewCurrent && preview && (
          <ol className="mt-4 divide-y divide-slate-200">
            {preview.data.occurrences.map((occurrence, index) => (
              <li
                className="flex flex-wrap items-center justify-between gap-2 py-3 text-sm"
                key={occurrence.utc}
              >
                <span>
                  <span className="mr-3 text-slate-400">{index + 1}</span>
                  <time dateTime={occurrence.utc}>
                    {occurrence.local.replace("T", " ")}
                  </time>
                  {occurrence.dst_adjusted && (
                    <span className="ml-2 text-xs text-amber-700">
                      夏令时顺延
                    </span>
                  )}
                </span>
                <span className="font-mono text-xs text-slate-500">
                  UTC {occurrence.utc.replace("T", " ")}
                </span>
              </li>
            ))}
          </ol>
        )}
      </section>
      <fieldset>
        <legend className="mb-3 text-sm font-medium">报告交付渠道 *</legend>
        <div className="ph-actions">
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={channels.includes("in_app")}
              onChange={() =>
                setChannels(
                  channels.includes("in_app")
                    ? channels.filter((channel) => channel !== "in_app")
                    : [...channels, "in_app"],
                )
              }
            />
            站内通知
          </label>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={channels.includes("email")}
              disabled={!emailEnabled && !channels.includes("email")}
              onChange={() =>
                setChannels(
                  channels.includes("email")
                    ? channels.filter((channel) => channel !== "email")
                    : [...channels, "email"],
                )
              }
            />
            邮件
          </label>
        </div>
        {!emailEnabled && (
          <p className="mt-2 text-xs text-slate-500">
            管理员尚未启用邮件交付，可使用站内通知。收件地址来自账户配置。
          </p>
        )}
      </fieldset>
      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={enabled}
          onChange={(event) => setEnabled(event.target.checked)}
        />
        启用后续定时研究
      </label>
      <p className="ph-notice">
        订阅生成待审草稿；报告通过独立人工审核并发布后才交付。暂停订阅不会取消已经运行的任务。
      </p>
      {validation && (
        <p className="ph-error" role="alert">
          {validation}
        </p>
      )}
      {!!error && <ErrorPanel error={error} />}
      <div className="ph-actions">
        <button
          className="ph-button"
          disabled={busy || (!drugs.length && !initial)}
        >
          {busy ? "保存中…" : "保存订阅"}
        </button>
        <button
          className="ph-button-secondary"
          type="button"
          disabled={busy}
          onClick={() => {
            if (!dirty || window.confirm("订阅配置尚未保存，确定放弃修改吗？"))
              onCancel();
          }}
        >
          取消
        </button>
      </div>
    </form>
  );
}

export function SubscriptionsPage() {
  const { workspace, request, config } = usePharma();
  const search = useSearchParams();
  const location = useListLocation();
  const allowed = workspace.role !== "reader";
  const resource = useResource<SubscriptionPage>(
    allowed
      ? `/subscriptions?limit=20&cursor=${encodeURIComponent(location.cursor)}`
      : null,
  );
  const drugs = useResource<DrugPage>(allowed ? "/drugs?limit=100" : null);
  const [editor, setEditor] = useState<Subscription | "new" | null>(
    search.get("new") === "true" ? "new" : null,
  );
  const [triggered, setTriggered] = useState<{
    name: string;
    runId: string | null;
  } | null>(null);
  const action = usePharmaWrite();
  if (!allowed)
    return (
      <Empty
        title="当前角色为只读成员"
        description="订阅和后台研究由研究员、审核员或管理员创建。已发布报告仍可查看。"
        action={
          <Link className="ph-button-secondary" href="/pharma/reports">
            查看已发布报告
          </Link>
        }
      />
    );
  return (
    <div className="ph-stack">
      <PageHeader
        eyebrow="YOUR RESEARCH RADAR"
        title="我的订阅"
        description="把重要的研究对象纳入持续观察，让新增变化在核对后抵达。"
        actions={
          <button
            className="ph-button"
            onClick={() => {
              action.reset();
              setEditor("new");
            }}
          >
            <Plus size={17} />
            建立订阅
          </button>
        }
      />
      {editor && (
        <Panel
          title={editor === "new" ? "建立进展订阅" : `编辑：${editor.name}`}
        >
          {drugs.isPending ? (
            <Loading />
          ) : drugs.error ? (
            <ErrorPanel
              error={drugs.error}
              onRetry={() => void drugs.refetch()}
            />
          ) : (
            <SubscriptionForm
              key={editor === "new" ? "new" : `${editor.id}:${editor.revision}`}
              initial={editor === "new" ? undefined : editor}
              initialDrugId={search.get("drug_id") ?? undefined}
              drugs={drugs.data?.items ?? []}
              emailEnabled={config?.email_enabled === true}
              busy={action.isPending}
              error={action.error}
              onCancel={() => setEditor(null)}
              onPreview={(schedule) =>
                request<SchedulePreview>("/subscriptions/preview", {
                  method: "POST",
                  body: schedule,
                })
              }
              onSave={async (value) => {
                try {
                  await action.mutateAsync({
                    path:
                      editor === "new"
                        ? "/subscriptions"
                        : `/subscriptions/${editor.id}`,
                    method: editor === "new" ? "POST" : "PATCH",
                    body: value,
                    revision: editor === "new" ? undefined : editor.revision,
                  });
                  setEditor(null);
                  await resource.refetch();
                } catch {
                  /* Retain draft and revision on conflict. */
                }
              }}
            />
          )}
          {drugs.data?.has_more && (
            <p className="mt-3 text-xs text-slate-500">
              选择器显示前 100
              个档案。可从目标药物详情页进入订阅并携带对象选择。
            </p>
          )}
        </Panel>
      )}
      {triggered && (
        <div className="ph-notice" role="status">
          “{triggered.name}”已提交后台研究，完成后仍需人工审核。
          {triggered.runId && (
            <Link
              className="ml-2 font-semibold text-blue-700 underline"
              href={`/pharma/research/${triggered.runId}`}
            >
              查看研究任务 →
            </Link>
          )}
        </div>
      )}
      {!editor && action.error && <ErrorPanel error={action.error} />}
      <Panel
        title="持续观察计划"
        actions={
          <span className="text-xs text-slate-500">
            仅本人订阅 · 已交付进度按渠道记录
          </span>
        }
      >
        {resource.isPending ? (
          <Loading />
        ) : resource.error ? (
          <ErrorPanel
            error={resource.error}
            onRetry={() => void resource.refetch()}
          />
        ) : !resource.data?.items.length ? (
          <Empty
            title="建立你的第一个研究订阅"
            description="选择关注对象、来源和时间，系统会定期生成有证据的待审草稿。"
            action={
              <button
                className="ph-button-secondary"
                onClick={() => setEditor("new")}
              >
                <BellPlus size={16} />
                创建进展订阅
              </button>
            }
          />
        ) : (
          <div className="ph-table-wrap">
            <table className="ph-table">
              <thead>
                <tr>
                  <th>订阅与对象</th>
                  <th>排程</th>
                  <th>下次研究</th>
                  <th>渠道 / 状态</th>
                  <th>最近结果</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                {resource.data.items.map((subscription) => (
                  <tr key={subscription.id}>
                    <td>
                      <strong className="block max-w-xs truncate">
                        {subscription.name}
                      </strong>
                      <p className="mt-1 max-w-xs text-xs leading-6 text-slate-500">
                        {subscription.drug_ids
                          .map(
                            (id) =>
                              drugs.data?.items.find((drug) => drug.id === id)
                                ?.display_name ?? "研究对象",
                          )
                          .join(" · ")}
                      </p>
                      <p className="mt-1 text-xs text-slate-400">
                        {subscription.source_allowlist
                          .map((source) =>
                            source === "ctgov"
                              ? "ClinicalTrials.gov"
                              : "PubMed",
                          )
                          .join(" + ")}
                      </p>
                    </td>
                    <td>
                      {subscription.schedule.frequency === "daily"
                        ? "每天"
                        : `每${DAYS[(subscription.schedule.weekday ?? 1) - 1] ?? "周"}`}{" "}
                      {subscription.schedule.local_time}
                      <p className="mt-1 text-xs text-slate-500">
                        {subscription.schedule.timezone}
                      </p>
                    </td>
                    <td>
                      {subscription.enabled ? (
                        <Timestamp value={subscription.next_run_at} />
                      ) : (
                        <span className="text-slate-500">已暂停后续触发</span>
                      )}
                    </td>
                    <td>
                      <div className="space-y-2">
                        <Badge
                          status={subscription.enabled ? "active" : "paused"}
                        >
                          {subscription.enabled ? "已启用" : "已暂停"}
                        </Badge>
                        <p className="text-xs text-slate-500">
                          {subscription.channels
                            .map((channel) =>
                              channel === "in_app" ? "站内" : "邮件",
                            )
                            .join(" / ")}
                        </p>
                      </div>
                    </td>
                    <td>
                      {subscription.last_outcome ? (
                        <Badge status={subscription.last_outcome} />
                      ) : (
                        <span className="text-xs text-slate-500">尚未执行</span>
                      )}
                    </td>
                    <td>
                      <div className="flex flex-wrap gap-2">
                        <button
                          className="ph-button-secondary"
                          disabled={action.isPending}
                          onClick={() => {
                            action.reset();
                            setEditor(subscription);
                          }}
                        >
                          编辑
                        </button>
                        <button
                          className="ph-button-secondary"
                          disabled={action.isPending}
                          onClick={async () => {
                            try {
                              await action.mutateAsync({
                                path: `/subscriptions/${subscription.id}`,
                                method: "PATCH",
                                body: subscriptionInput(
                                  subscription,
                                  !subscription.enabled,
                                ),
                                revision: subscription.revision,
                              });
                              await resource.refetch();
                            } catch {
                              /* Keep API error visible. */
                            }
                          }}
                        >
                          {subscription.enabled ? (
                            <Pause size={13} />
                          ) : (
                            <Play size={13} />
                          )}
                          {subscription.enabled ? "暂停" : "恢复"}
                        </button>
                        <button
                          className="ph-button-secondary"
                          disabled={action.isPending}
                          onClick={async () => {
                            try {
                              const result = await action.mutateAsync({
                                path: `/subscriptions/${subscription.id}/trigger`,
                              });
                              setTriggered({
                                name: subscription.name,
                                runId:
                                  typeof result.run_id === "string"
                                    ? result.run_id
                                    : null,
                              });
                            } catch {
                              /* Keep API error visible. */
                            }
                          }}
                        >
                          <Play size={13} />
                          立即生成
                        </button>
                      </div>
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
      <div className="ph-notice">
        暂停仅阻止新的定时触发；正在运行的任务可在研究详情页单独取消。邮件显示“已接受”仅表示
        SMTP 接受，未确认送达或阅读。
      </div>
    </div>
  );
}
