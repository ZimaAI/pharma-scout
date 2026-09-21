"use client";

import { useMutation } from "@tanstack/react-query";
import { ArrowRight, Bell, Check, RefreshCw, Settings2 } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import {
  type AuditPage,
  type DeliveryPage,
  type EventPage,
  type JobPage,
  type MemberPage,
  type Role,
  type SourceHealthList,
} from "@/core/pharma/contracts";

import { usePharma, useResource } from "./context";
import {
  Badge,
  Empty,
  ErrorPanel,
  Loading,
  PageHeader,
  Panel,
  Timestamp,
} from "./ui";

export function SettingsPage() {
  const { workspace, config, request, refresh } = usePharma();
  const admin = workspace.role === "admin";
  const sources = useResource<SourceHealthList>("/sources");
  const members = useResource<MemberPage>(admin ? "/members" : null);
  const jobs = useResource<JobPage>("/jobs?limit=20", 10_000);
  const [tab, setTab] = useState("sources");
  const mutation = useMutation({
    mutationFn: async ({
      path,
      method,
      body,
    }: {
      path: string;
      method: string;
      body: unknown;
    }) => {
      await request(path, { method, body });
      await refresh();
    },
  });
  return (
    <div className="ph-stack">
      <PageHeader
        eyebrow="WORKSPACE SETTINGS"
        title="工作区设置"
        description="管理数据来源、成员权限与后台任务。所有时间显示为北京时间。"
      />
      <div className="ph-tabs" role="tablist" aria-label="设置分类">
        {[
          { key: "sources", label: "数据与环境" },
          { key: "jobs", label: "同步任务" },
          ...(admin
            ? [
                { key: "members", label: "成员管理" },
                { key: "audit", label: "审计记录" },
              ]
            : []),
        ].map((item) => (
          <button
            key={item.key}
            role="tab"
            aria-selected={tab === item.key}
            className={tab === item.key ? "active" : ""}
            onClick={() => setTab(item.key)}
          >
            {item.label}
          </button>
        ))}
      </div>
      {mutation.error && <ErrorPanel error={mutation.error} />}
      {tab === "sources" && (
        <>
          <Panel
            title="数据来源"
            actions={<span className="ph-muted">仅管理员可修改启用状态</span>}
          >
            {sources.isPending ? (
              <Loading />
            ) : sources.error ? (
              <ErrorPanel error={sources.error} />
            ) : (
              <div className="ph-grid">
                {sources.data.items.map((source) => (
                  <div className="ph-source-card" key={source.source}>
                    <div className="ph-row">
                      <h3>
                        {source.source === "ctgov"
                          ? "ClinicalTrials.gov"
                          : "PubMed"}
                      </h3>
                      <Badge status={source.state} />
                    </div>
                    <p>
                      {source.source === "ctgov"
                        ? "临床试验注册、状态、入组与终点定义"
                        : "生物医学文献、摘要与更正关系"}
                    </p>
                    <small>
                      最近成功：
                      <Timestamp value={source.last_success_at} />
                    </small>
                    {source.last_error_code && (
                      <p className="ph-notice">
                        最近错误：{source.last_error_code}
                      </p>
                    )}
                    <label className="ph-checkbox">
                      <input
                        type="checkbox"
                        checked={source.enabled}
                        disabled={!admin || mutation.isPending}
                        onChange={(event) =>
                          mutation.mutate({
                            path: `/sources/${source.source}`,
                            method: "PATCH",
                            body: { enabled: event.target.checked },
                          })
                        }
                      />
                      启用该来源
                    </label>
                  </div>
                ))}
              </div>
            )}
          </Panel>
          <Panel title="研究与投递配置">
            <dl className="ph-definition">
              <div>
                <dt>工作区模式</dt>
                <dd>
                  <Badge
                    status={
                      config?.data_mode ?? workspace.data_mode ?? "unknown"
                    }
                  />
                </dd>
              </div>
              <div>
                <dt>研究模型</dt>
                <dd>
                  {config?.model_configured
                    ? "已检测到模型配置"
                    : "待管理员在服务器配置"}
                </dd>
              </div>
              <div>
                <dt>邮件渠道</dt>
                <dd>
                  {config?.email_enabled
                    ? "已启用 SMTP"
                    : "尚未启用 · 可使用站内通知"}
                </dd>
              </div>
            </dl>
            <p className="ph-notice">
              真实研究使用 DeerFlow
              已配置的模型。凭据由服务器管理员管理，页面不展示密钥。
            </p>
          </Panel>
          {config?.data_mode === "demo" && (
            <Panel title="演示时间推进">
              <p>
                当前 D{config.demo_day ?? 1}。D1–D5
                逐日展示首次抓取、无变化、内容更新、来源更正与内容回退；推进后历史报告保留原版本。
              </p>
              <div className="ph-actions">
                <button
                  className="ph-button ph-button-secondary"
                  disabled={
                    workspace.role === "reader" ||
                    mutation.isPending ||
                    (config.demo_day ?? 1) >= 5
                  }
                  onClick={() =>
                    mutation.mutate({
                      path: "/demo/advance",
                      method: "POST",
                      body: { day: (config.demo_day ?? 1) + 1 },
                    })
                  }
                >
                  <RefreshCw size={15} />
                  推进至下一日
                </button>
                <span className="ph-muted">仅演示工作区 · 使用虚构资料</span>
              </div>
            </Panel>
          )}
        </>
      )}
      {tab === "jobs" && (
        <Panel title="后台任务">
          <p className="ph-muted">
            每 10 秒更新一次。进度来自服务端已处理记录。
          </p>
          {jobs.isPending ? (
            <Loading />
          ) : jobs.error ? (
            <ErrorPanel error={jobs.error} />
          ) : !jobs.data.items.length ? (
            <Empty
              title="暂无后台任务"
              description="同步来源和研究任务将在这里显示。"
            />
          ) : (
            <div className="ph-table-wrap">
              <table className="ph-table">
                <thead>
                  <tr>
                    <th>任务</th>
                    <th>状态</th>
                    <th>处理记录</th>
                    <th>尝试次数</th>
                    <th>创建时间</th>
                  </tr>
                </thead>
                <tbody>
                  {jobs.data.items.map((job) => (
                    <tr key={job.id}>
                      <td>
                        <strong>
                          {job.kind === "ingest"
                            ? "来源同步"
                            : job.kind === "research"
                              ? "专题研究"
                              : "报告投递"}
                        </strong>
                        <small className="ph-mono">{job.id.slice(0, 8)}</small>
                        {job.error_code && (
                          <small className="ph-text-danger">
                            {job.error_code}
                          </small>
                        )}
                      </td>
                      <td>
                        <Badge status={job.state} />
                      </td>
                      <td>
                        {job.progress.processed}
                        {job.progress.total !== null
                          ? ` / ${job.progress.total}`
                          : ""}
                      </td>
                      <td>{job.attempt}</td>
                      <td>
                        <Timestamp value={job.created_at} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Panel>
      )}
      {tab === "members" && admin && (
        <Panel title="工作区成员">
          {members.isPending ? (
            <Loading />
          ) : members.error ? (
            <ErrorPanel error={members.error} />
          ) : (
            <div className="ph-table-wrap">
              <table className="ph-table">
                <thead>
                  <tr>
                    <th>成员</th>
                    <th>角色</th>
                    <th>启用</th>
                  </tr>
                </thead>
                <tbody>
                  {members.data.items.map((member) => (
                    <tr key={member.user.id}>
                      <td>
                        <strong>{member.user.display_name}</strong>
                        <small>{member.user.email}</small>
                      </td>
                      <td>
                        <select
                          className="ph-select"
                          aria-label={`${member.user.display_name}的角色`}
                          value={member.role}
                          disabled={mutation.isPending}
                          onChange={(event) =>
                            mutation.mutate({
                              path: `/members/${member.user.id}`,
                              method: "PATCH",
                              body: { role: event.target.value as Role },
                            })
                          }
                        >
                          {(
                            ["reader", "analyst", "reviewer", "admin"] as const
                          ).map((role) => (
                            <option key={role} value={role}>
                              {role === "reader"
                                ? "只读成员"
                                : role === "analyst"
                                  ? "研究员"
                                  : role === "reviewer"
                                    ? "审核员"
                                    : "管理员"}
                            </option>
                          ))}
                        </select>
                      </td>
                      <td>
                        <label className="ph-checkbox">
                          <input
                            type="checkbox"
                            checked={member.enabled}
                            disabled={mutation.isPending}
                            onChange={(event) =>
                              mutation.mutate({
                                path: `/members/${member.user.id}`,
                                method: "PATCH",
                                body: { enabled: event.target.checked },
                              })
                            }
                          />
                          <span>{member.enabled ? "已启用" : "已停用"}</span>
                        </label>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <p className="ph-muted">
            新账户由管理员通过服务器命令创建；最后一位管理员不能被降级或停用。
          </p>
        </Panel>
      )}
      {tab === "audit" && admin && <AuditLog />}
    </div>
  );
}
function AuditLog() {
  const [cursor, setCursor] = useState<string | null>(null);
  const audit = useResource<AuditPage>(
    `/audit?limit=30${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`,
  );
  return (
    <Panel title="不可变审计记录">
      {audit.isPending ? (
        <Loading />
      ) : audit.error ? (
        <ErrorPanel error={audit.error} />
      ) : (
        <>
          <div className="ph-table-wrap">
            <table className="ph-table">
              <thead>
                <tr>
                  <th>操作</th>
                  <th>对象</th>
                  <th>操作者</th>
                  <th>时间</th>
                </tr>
              </thead>
              <tbody>
                {audit.data.items.map((item) => (
                  <tr key={item.id}>
                    <td className="ph-mono">{item.action}</td>
                    <td>
                      {item.target_type}
                      <small className="ph-mono">
                        {item.target_id?.slice(0, 12) ?? "—"}
                      </small>
                    </td>
                    <td className="ph-mono">
                      {item.actor_id?.slice(0, 12) ?? "系统"}
                    </td>
                    <td>
                      <Timestamp value={item.created_at} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="ph-pagination">
            <button
              className="ph-button ph-button-secondary"
              onClick={() => setCursor(null)}
              disabled={!cursor}
            >
              返回最新
            </button>
            <button
              className="ph-button ph-button-secondary"
              disabled={!audit.data.has_more}
              onClick={() => setCursor(audit.data.next_cursor)}
            >
              下一页
            </button>
          </div>
        </>
      )}
    </Panel>
  );
}
export function EventsPage() {
  const [cursor, setCursor] = useState<string | null>(null);
  const events = useResource<EventPage>(
    `/events?limit=20${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`,
  );
  return (
    <div className="ph-stack">
      <PageHeader
        eyebrow="OBSERVED CHANGES"
        title="研发事件"
        description="按本工作区观测时间记录来源变化，保留每次修订与可核验的差异。"
      />
      <Panel title="全部观测事件">
        {events.isPending ? (
          <Loading />
        ) : events.error ? (
          <ErrorPanel error={events.error} />
        ) : !events.data.items.length ? (
          <Empty
            title="暂无研发事件"
            description="同步药物相关资料后，来源变化会在这里呈现。"
          />
        ) : (
          <>
            <div className="ph-list">
              {events.data.items.map((event) => (
                <Link
                  className="ph-list-row"
                  href={`/pharma/events/${event.id}`}
                  key={event.id}
                >
                  <div>
                    <Badge status={event.category} />
                    <h3>{event.title}</h3>
                    <small>
                      <Timestamp value={event.updated_at} />
                    </small>
                  </div>
                  <ArrowRight size={18} />
                </Link>
              ))}
            </div>
            <div className="ph-pagination">
              <button
                className="ph-button ph-button-secondary"
                disabled={!cursor}
                onClick={() => setCursor(null)}
              >
                返回最新
              </button>
              <button
                className="ph-button ph-button-secondary"
                disabled={!events.data.has_more}
                onClick={() => setCursor(events.data.next_cursor)}
              >
                下一页
              </button>
            </div>
          </>
        )}
      </Panel>
    </div>
  );
}
export function InboxPage() {
  const { request, refresh } = usePharma();
  const [cursor, setCursor] = useState<string | null>(null);
  const inbox = useResource<DeliveryPage>(
    `/inbox?limit=20${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`,
    30_000,
  );
  const read = useMutation({
    mutationFn: async (id: string) => {
      await request(`/inbox/${id}/read`, { method: "POST" });
      await refresh();
    },
  });
  return (
    <div className="ph-stack">
      <PageHeader
        eyebrow="RESEARCH UPDATES"
        title="通知中心"
        description="查看已审核发布报告的投递与阅读状态。"
        actions={
          <Link
            href="/pharma/subscriptions"
            className="ph-button ph-button-secondary"
          >
            <Settings2 size={16} />
            管理订阅
          </Link>
        }
      />
      {read.error && <ErrorPanel error={read.error} />}
      <Panel title="站内通知">
        {inbox.isPending ? (
          <Loading />
        ) : inbox.error ? (
          <ErrorPanel error={inbox.error} />
        ) : !inbox.data.items.length ? (
          <Empty
            title="暂无新通知"
            description="订阅报告经独立审核发布后，将投递到这里。"
          />
        ) : (
          <>
            <div className="ph-list">
              {inbox.data.items.map((delivery) => (
                <div className="ph-list-row" key={delivery.id}>
                  <span className="ph-list-icon">
                    <Bell size={20} />
                  </span>
                  <div>
                    <h3>
                      <Link
                        className="ph-link"
                        href={`/pharma/reports/${delivery.report_id}?version=${delivery.report_version_id}`}
                      >
                        研究报告已发布 · 阅读报告
                      </Link>
                    </h3>
                    <small>
                      版本{" "}
                      <span className="ph-mono">
                        {delivery.report_version_id.slice(0, 12)}
                      </span>{" "}
                      · <Timestamp value={delivery.accepted_at} />
                    </small>
                    <Badge status={delivery.read_at ? "read" : "unread"} />
                  </div>
                  {!delivery.read_at && (
                    <button
                      className="ph-button ph-button-secondary"
                      disabled={read.isPending}
                      onClick={() => read.mutate(delivery.id)}
                    >
                      <Check size={15} />
                      标为已读
                    </button>
                  )}
                </div>
              ))}
            </div>
            <div className="ph-pagination">
              <button
                className="ph-button ph-button-secondary"
                disabled={!cursor}
                onClick={() => setCursor(null)}
              >
                返回最新
              </button>
              <button
                className="ph-button ph-button-secondary"
                disabled={!inbox.data.has_more}
                onClick={() => setCursor(inbox.data.next_cursor)}
              >
                下一页
              </button>
            </div>
          </>
        )}
      </Panel>
    </div>
  );
}
