"use client";

import {
  Badge,
  Empty,
  ErrorPanel,
  Field,
  Loading,
  PageHeader,
  Panel,
} from "./ui";

export function DesignPreview() {
  return (
    <div className="ph-stack">
      <PageHeader
        eyebrow="DESIGN SYSTEM / V1.0"
        title="清晰呈现，有据可循"
        description="PharmaScope 组件与状态预览 · 全部示例仅用于界面检查"
        actions={<button className="ph-button">发起研究</button>}
      />
      <div className="ph-grid">
        <Panel title="状态语义">
          <div className="ph-actions">
            {[
              "draft",
              "in_review",
              "published",
              "partial",
              "failed",
              "unverified",
              "demo",
              "live",
            ].map((status) => (
              <Badge key={status} status={status} />
            ))}
          </div>
        </Panel>
        <Panel title="表单与反馈">
          <Field label="药物名称" hint="仅用于组件预览">
            <input className="ph-input" placeholder="输入名称或研发代号" />
          </Field>
          <div className="ph-actions">
            <button className="ph-button">主要操作</button>
            <button className="ph-button ph-button-secondary">次要操作</button>
            <button className="ph-button" disabled>
              不可用
            </button>
          </div>
        </Panel>
      </div>
      <Panel title="数据状态">
        <Empty
          title="尚未同步来源"
          description="完成药物建档和别名确认后，获取第一批官方资料。"
        />
        <Loading />
        <ErrorPanel
          error={new Error("来源暂时不可用，已保留上次成功抓取的资料。")}
        />
        <div className="ph-notice">
          部分完成：PubMed 已返回，试验来源需要稍后重试。
        </div>
        <div className="ph-notice">暂无此操作权限，请联系工作区管理员。</div>
      </Panel>
    </div>
  );
}
