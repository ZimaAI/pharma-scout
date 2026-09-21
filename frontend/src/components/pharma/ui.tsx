"use client";

import {
  AlertCircle,
  ArrowLeft,
  BookOpen,
  CheckCircle2,
  Circle,
  FileSearch,
  LoaderCircle,
  RefreshCw,
} from "lucide-react";
import Link from "next/link";
import { cloneElement, isValidElement, useId, type ReactNode } from "react";

import { PharmaAPIError } from "@/core/pharma/client";
import {
  type Coverage as CoverageItem,
  type DateValue,
} from "@/core/pharma/contracts";

import { useEvidence } from "./context";

const labels: Record<string, string> = {
  demo: "DEMO · 演示",
  live: "LIVE · 真实来源",
  replay: "演示回放",
  deerflow: "DeerFlow Agent",
  draft: "草稿",
  in_review: "待审核",
  changes_requested: "需修改",
  approved: "已批准",
  published: "已发布",
  retracted: "已撤回",
  pending: "待确认",
  rejected: "已拒绝",
  revoked: "已撤销",
  queued: "排队中",
  running: "运行中",
  verifying: "核验中",
  awaiting_input: "等待补充",
  completed: "已完成",
  succeeded: "已完成",
  complete: "完整覆盖",
  partial: "部分完成",
  failed: "失败",
  cancelling: "取消中",
  cancelled: "已取消",
  recovery_required: "需恢复",
  retry_wait: "等待重试",
  started: "执行中",
  supported: "证据支持",
  unverified: "待人工核对",
  insufficient: "证据不足",
  conflicted: "证据冲突",
  manual_check_required: "需人工核数",
  healthy: "可用",
  degraded: "服务降级",
  unavailable: "不可用",
  unknown: "尚未核验",
  not_requested: "未请求",
  accepted: "已接受",
  sending: "投递中",
  generated: "已生成",
  no_change: "无新增变化",
  read: "已读",
  unread: "未读",
  fact: "事实",
  hypothesis: "假设",
  gap: "资料缺口",
  supports: "支持",
  contradicts: "反驳",
  context: "背景",
  passed: "通过",
  not_applicable: "不适用",
  approve: "批准",
  request_changes: "退回修改",
  baseline: "首次观测",
  changed: "发现变化",
  unchanged: "未变化",
  reader: "只读成员",
  analyst: "研究员",
  reviewer: "审核员",
  admin: "管理员",
  ctgov: "ClinicalTrials.gov",
  pubmed: "PubMed",
  status_change: "状态变化",
  enrollment_change: "入组变化",
  date_change: "日期变化",
  outcome_definition_change: "终点定义变化",
  results_available: "结果可用",
  publication_added: "新增文献",
  correction: "更正",
  other: "其他变化",
  NOT_YET_RECRUITING: "尚未招募",
  RECRUITING: "招募中",
  ENROLLING_BY_INVITATION: "邀请入组",
  ACTIVE_NOT_RECRUITING: "进行中 · 停止招募",
  SUSPENDED: "暂停",
  TERMINATED: "提前终止",
  COMPLETED: "试验已完成",
  WITHDRAWN: "撤销",
  UNKNOWN: "未知",
  OTHER: "其他",
};
export function statusLabel(status: string) {
  return labels[status] ?? status;
}

export function PageHeader({
  eyebrow,
  title,
  description,
  actions,
  back,
}: {
  eyebrow?: string;
  title: string;
  description?: string;
  actions?: ReactNode;
  back?: string;
}) {
  return (
    <header className="ph-page-header">
      <div>
        {back && (
          <Link href={back} className="ph-back">
            <ArrowLeft size={15} />
            返回
          </Link>
        )}
        {eyebrow && <span className="ph-eyebrow">{eyebrow}</span>}
        <h1>{title}</h1>
        {description && <p>{description}</p>}
      </div>
      {actions && <div className="ph-actions">{actions}</div>}
    </header>
  );
}
export function Panel({
  title,
  actions,
  children,
  className = "",
}: {
  title?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`ph-panel ${className}`}>
      {(title ?? actions) && (
        <div className="ph-panel-header">
          <h2>{title}</h2>
          <div className="ph-actions">{actions}</div>
        </div>
      )}
      <div className="ph-panel-body">{children}</div>
    </section>
  );
}
export function Badge({
  status,
  children,
}: {
  status: string;
  children?: ReactNode;
}) {
  const success = [
    "published",
    "approved",
    "completed",
    "succeeded",
    "complete",
    "accepted",
    "healthy",
    "passed",
    "supported",
  ].includes(status);
  const danger = [
    "failed",
    "retracted",
    "conflicted",
    "unavailable",
    "rejected",
    "revoked",
  ].includes(status);
  const warning = [
    "partial",
    "insufficient",
    "unverified",
    "in_review",
    "pending",
    "degraded",
    "recovery_required",
    "changes_requested",
    "manual_check_required",
  ].includes(status);
  const Icon = success
    ? CheckCircle2
    : danger || warning
      ? AlertCircle
      : Circle;
  return (
    <span
      className={`ph-badge ${success ? "ph-badge-success" : danger ? "ph-badge-danger" : warning ? "ph-badge-warning" : "ph-badge-info"}`}
    >
      <Icon size={12} aria-hidden="true" />
      {children ?? statusLabel(status)}
    </span>
  );
}
export function Empty({
  title,
  description,
  action,
}: {
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <div className="ph-empty">
      <div className="ph-empty-icon">
        <FileSearch size={28} />
      </div>
      <h3>{title}</h3>
      {description && <p>{description}</p>}
      {action}
    </div>
  );
}
export function ErrorPanel({
  error,
  onRetry,
}: {
  error: unknown;
  onRetry?: () => void;
}) {
  return (
    <div className="ph-error" role="alert">
      <AlertCircle size={18} />
      <div>
        <strong>
          {error instanceof Error ? error.message : "暂时无法加载，请稍后重试"}
        </strong>
        {error instanceof PharmaAPIError && error.status === 409 && (
          <p>数据已发生变化。请刷新后重新核对，当前编辑内容仍保留。</p>
        )}
        {error instanceof PharmaAPIError && error.requestId && (
          <small>请求编号：{error.requestId}</small>
        )}
        {onRetry && (
          <button type="button" className="ph-link" onClick={onRetry}>
            <RefreshCw size={14} />
            重新加载
          </button>
        )}
      </div>
    </div>
  );
}
export function Loading() {
  return (
    <div className="ph-loading" role="status">
      <LoaderCircle size={22} className="ph-spin" />
      正在加载资料…
    </div>
  );
}
export function EvidenceButton({
  id,
  label = "查看证据",
}: {
  id: string;
  label?: string;
}) {
  const open = useEvidence();
  return (
    <button
      type="button"
      className="ph-evidence-button"
      onClick={() => open(id)}
    >
      <BookOpen size={13} />
      {label}
    </button>
  );
}
export function Field({
  label,
  children,
  hint,
}: {
  label: string;
  children: ReactNode;
  hint?: string;
}) {
  const fieldId = useId();
  const hintId = `${fieldId}-hint`;
  const control = isValidElement<{ id?: string; "aria-describedby"?: string }>(
    children,
  )
    ? children
    : null;
  const native =
    control &&
    typeof control.type === "string" &&
    ["input", "select", "textarea"].includes(control.type);
  const id = control?.props.id ?? fieldId;
  return (
    <div className="ph-field">
      {native ? (
        <>
          <label htmlFor={id}>{label}</label>
          {cloneElement(control, {
            id,
            ...(hint ? { "aria-describedby": hintId } : {}),
          })}
        </>
      ) : (
        <label>
          <span>{label}</span>
          {children}
        </label>
      )}
      {hint && <small id={hintId}>{hint}</small>}
    </div>
  );
}
export function Coverage({ items }: { items: CoverageItem[] }) {
  if (!items.length) return <p className="ph-muted">尚无来源覆盖记录</p>;
  return (
    <div className="ph-stack">
      {items.map((item) => (
        <div className="ph-coverage" key={item.source}>
          <div className="ph-row">
            <strong>{statusLabel(item.source)}</strong>
            <Badge status={item.status} />
          </div>
          <span>
            {item.records_count} 条记录{item.truncated ? " · 已达截断上限" : ""}
          </span>
          <small>
            资料截止：
            <Timestamp value={item.as_of} />
          </small>
          {item.limitations.map((text, index) => (
            <p className="ph-notice" key={index}>
              {text}
            </p>
          ))}
        </div>
      ))}
    </div>
  );
}
export function Timestamp({ value }: { value: string | null | undefined }) {
  if (!value) return <span>尚无记录</span>;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return <span>日期未知</span>;
  return (
    <time dateTime={value} title={value}>
      {new Intl.DateTimeFormat("zh-CN", {
        dateStyle: "medium",
        timeStyle: "short",
        timeZone: "Asia/Shanghai",
      }).format(date)}
    </time>
  );
}
export function DateText({ value }: { value: DateValue | null | undefined }) {
  if (!value?.value || value.precision === "unknown") return <span>未知</span>;
  return (
    <span>
      {value.value}
      {value.precision === "month"
        ? "（月精度）"
        : value.precision === "year"
          ? "（年精度）"
          : ""}
      {value.kind === "estimated"
        ? " · 预计"
        : value.kind === "actual"
          ? " · 实际"
          : ""}
    </span>
  );
}
