"use client";

import {
  Activity,
  ArrowRight,
  ArrowUpRight,
  BookOpen,
  FileCheck2,
  FlaskConical,
  Microscope,
  Plus,
  Radar,
  ShieldCheck,
} from "lucide-react";
import Link from "next/link";

import {
  type Dashboard as DashboardData,
  type EventPage,
  type ReportPage,
  type ResearchRunPage,
} from "@/core/pharma/contracts";

import { usePharma, useResource } from "./context";
import { Badge, Empty, ErrorPanel, Loading, Panel, Timestamp } from "./ui";

export function Dashboard() {
  const { workspace, config } = usePharma();
  const dashboard = useResource<DashboardData>("/dashboard", 30_000);
  const events = useResource<EventPage>("/events?limit=5", 30_000);
  const runs = useResource<ResearchRunPage>("/research/runs?limit=4", 15_000);
  const reports = useResource<ReportPage>("/reports?limit=4");
  const canWrite = workspace.role !== "reader";
  if (dashboard.isPending) return <Loading />;
  if (dashboard.error)
    return (
      <ErrorPanel
        error={dashboard.error}
        onRetry={() => void dashboard.refetch()}
      />
    );
  const data = dashboard.data;
  return (
    <div className="ph-stack ph-dashboard">
      <div className="ph-welcome">
        <div>
          <span className="ph-eyebrow">RESEARCH INTELLIGENCE WORKSPACE</span>
          <h1>研发情报工作台</h1>
        </div>
        <span className="ph-muted">
          数据更新于 <Timestamp value={data.as_of} /> · 北京时间
        </span>
      </div>
      <section className="ph-hero">
        <div className="ph-hero-copy">
          <span className="ph-hero-kicker">
            <span /> EVIDENCE IN FOCUS
          </span>
          <h2>
            让每一条研发进展，
            <br />
            都有据可循。
          </h2>
          <p>
            连接临床试验与文献，从来源变化到可信研究结论。
            <br className="ph-desktop" />
            保留证据、理解差异，让研究判断更有依据。
          </p>
          <div className="ph-actions">
            <Link
              className="ph-button"
              href={canWrite ? "/pharma/research/new" : "/pharma/reports"}
            >
              {canWrite ? <Plus size={17} /> : <BookOpen size={17} />}
              {canWrite ? "发起专题研究" : "阅读已发布报告"}
              <ArrowRight size={16} />
            </Link>
            <Link href="/pharma/drugs" className="ph-hero-link">
              浏览药物档案 <ArrowUpRight size={16} />
            </Link>
          </div>
        </div>
        <div className="ph-hero-visual" aria-hidden="true">
          <div className="ph-orbit ph-orbit-one" />
          <div className="ph-orbit ph-orbit-two" />
          <div className="ph-orbit-center">
            <Microscope size={45} strokeWidth={1.4} />
          </div>
          <span className="ph-orbit-node ph-node-a">
            <FlaskConical size={18} />
            临床试验
          </span>
          <span className="ph-orbit-node ph-node-b">
            <BookOpen size={18} />
            文献证据
          </span>
          <span className="ph-orbit-node ph-node-c">
            <ShieldCheck size={18} />
            可追溯研究
          </span>
        </div>
      </section>
      {config?.data_mode === "live" && !config.model_configured && (
        <div className="ph-notice">
          <strong>研究模型待配置</strong> ·
          可先建档、确认别名并同步官方来源；配置模型后即可启动真实 Agent 研究。
        </div>
      )}
      <div className="ph-metrics">
        {[
          {
            label: "订阅关注药物",
            value: data.watched_drugs,
            note: "来自您的启用订阅",
            icon: FlaskConical,
            tone: "blue",
          },
          {
            label: "近 7 天观测事件",
            value: data.events_last_7_days,
            note: "本工作区记录的变化",
            icon: Activity,
            tone: "purple",
          },
          {
            label: "待审核报告",
            value: data.pending_reviews,
            note: "当前权限可见范围",
            icon: FileCheck2,
            tone: "amber",
          },
          {
            label: "已启用数据来源",
            value: data.source_health.filter((source) => source.enabled).length,
            note: "ClinicalTrials.gov / PubMed",
            icon: Radar,
            tone: "green",
          },
        ].map((metric) => (
          <div className="ph-metric" key={metric.label}>
            <div>
              <p>{metric.label}</p>
              <strong>{metric.value}</strong>
              <small>{metric.note}</small>
            </div>
            <div className={`ph-metric-icon ph-tone-${metric.tone}`}>
              <metric.icon size={22} />
            </div>
          </div>
        ))}
      </div>
      <div className="ph-dashboard-grid">
        <div className="ph-stack">
          <Panel
            title={
              <>
                <span className="ph-heading-line" />
                最新研发事件
              </>
            }
            actions={
              <Link className="ph-link" href="/pharma/events">
                查看全部 <ArrowRight size={14} />
              </Link>
            }
          >
            {events.error ? (
              <ErrorPanel error={events.error} />
            ) : events.isPending ? (
              <Loading />
            ) : !events.data.items.length ? (
              <Empty
                title="暂无观测事件"
                description="同步官方资料后，来源变化会显示在这里。"
                action={
                  canWrite && (
                    <Link className="ph-link" href="/pharma/drugs">
                      建立药物档案 <ArrowRight size={14} />
                    </Link>
                  )
                }
              />
            ) : (
              <div className="ph-event-list">
                {events.data.items.map((event) => (
                  <Link
                    className="ph-event-row"
                    key={event.id}
                    href={`/pharma/events/${event.id}`}
                  >
                    <div className="ph-timeline-dot">
                      <Activity size={16} />
                    </div>
                    <div>
                      <Badge status={event.category} />
                      <h3>{event.title}</h3>
                      <span className="ph-muted">
                        <Timestamp value={event.updated_at} />
                      </span>
                    </div>
                    <ArrowUpRight size={16} />
                  </Link>
                ))}
              </div>
            )}
          </Panel>
          <Panel
            title="最近研究任务"
            actions={
              <Link className="ph-link" href="/pharma/research">
                研究中心 <ArrowRight size={14} />
              </Link>
            }
          >
            {runs.error ? (
              <ErrorPanel error={runs.error} />
            ) : runs.isPending ? (
              <Loading />
            ) : !runs.data.items.length ? (
              <Empty
                title="从一个研究问题开始"
                description="选择药物、资料范围与时间窗，生成可核验的研究草稿。"
              />
            ) : (
              <div className="ph-list">
                {runs.data.items.map((run) => (
                  <Link
                    className="ph-list-row"
                    key={run.id}
                    href={`/pharma/research/${run.id}`}
                  >
                    <span className="ph-list-icon">
                      <Microscope size={19} />
                    </span>
                    <div>
                      <h3>{run.question}</h3>
                      <small>
                        <Timestamp value={run.created_at} /> ·{" "}
                        {run.runtime_mode === "replay"
                          ? "DEMO 回放"
                          : "LIVE 研究"}
                      </small>
                    </div>
                    <Badge status={run.status} />
                  </Link>
                ))}
              </div>
            )}
          </Panel>
        </div>
        <div className="ph-stack">
          <Panel title="数据来源">
            <div className="ph-stack">
              {data.source_health.map((source) => (
                <div className="ph-source-card" key={source.source}>
                  <div className="ph-row">
                    <span
                      className={`ph-source-mark ${source.source === "pubmed" ? "ph-source-pubmed" : ""}`}
                    >
                      {source.source === "ctgov" ? "CT" : "PM"}
                    </span>
                    <div>
                      <h3>
                        {source.source === "ctgov"
                          ? "ClinicalTrials.gov"
                          : "PubMed"}
                      </h3>
                      <small>
                        {source.source === "ctgov"
                          ? "临床试验注册与进展"
                          : "生物医学研究文献"}
                      </small>
                    </div>
                  </div>
                  <div className="ph-row">
                    <Badge
                      status={source.enabled ? source.state : "not_requested"}
                    >
                      {source.enabled ? undefined : "已停用"}
                    </Badge>
                    <span className="ph-muted">
                      {data.is_demo ? "演示资料" : "官方 API"}
                    </span>
                  </div>
                  <small>
                    最近成功：
                    <Timestamp value={source.last_success_at} />
                  </small>
                </div>
              ))}
            </div>
          </Panel>
          <Panel
            title="研究报告"
            actions={
              <Link className="ph-link" href="/pharma/reports">
                全部 <ArrowRight size={14} />
              </Link>
            }
          >
            {reports.error ? (
              <ErrorPanel error={reports.error} />
            ) : reports.isPending ? (
              <Loading />
            ) : !reports.data.items.length ? (
              <Empty
                title="暂无报告"
                description="研究完成后，报告将在此归档。"
              />
            ) : (
              <div className="ph-list">
                {reports.data.items.map((report) => (
                  <Link
                    className="ph-report-mini"
                    href={`/pharma/reports/${report.id}`}
                    key={report.id}
                  >
                    <span className="ph-report-icon">
                      <FileCheck2 size={18} />
                    </span>
                    <div>
                      <h3>{report.title}</h3>
                      <Badge status={report.state} />
                    </div>
                  </Link>
                ))}
              </div>
            )}
          </Panel>
          <div className="ph-guide-card">
            <ShieldCheck size={22} />
            <h3>证据先行，判断审慎</h3>
            <p>每条研究结论均可回到来源快照。AI 草稿经独立审核后才能发布。</p>
          </div>
        </div>
      </div>
    </div>
  );
}
