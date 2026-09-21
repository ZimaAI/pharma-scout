"use client";

import { ExternalLink, Fingerprint, Quote } from "lucide-react";

import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { safeSourceURL } from "@/core/pharma/client";
import {
  type Evidence,
  type SourceSnapshot,
  type Trial,
  type Publication,
} from "@/core/pharma/contracts";

import { useResource } from "./context";
import { Badge, ErrorPanel, Loading, Timestamp } from "./ui";

export function EvidenceDrawer({
  id,
  onClose,
  restoreFocus,
}: {
  id: string | null;
  onClose: () => void;
  restoreFocus: () => void;
}) {
  return (
    <Sheet
      open={!!id}
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
    >
      <SheetContent
        className="pharma-app ph-evidence-drawer"
        onCloseAutoFocus={(event) => {
          event.preventDefault();
          restoreFocus();
        }}
      >
        <SheetHeader>
          <SheetTitle>证据溯源</SheetTitle>
          <SheetDescription>
            核对不可变快照中的原始片段与引用位置
          </SheetDescription>
        </SheetHeader>
        {id && <EvidenceContent key={id} id={id} />}
      </SheetContent>
    </Sheet>
  );
}
function EvidenceContent({ id }: { id: string }) {
  const evidence = useResource<Evidence>(`/evidence/${id}`);
  const snapshot = useResource<SourceSnapshot>(
    evidence.data ? `/snapshots/${evidence.data.snapshot_id}` : null,
  );
  const source = useResource<Trial | Publication>(
    snapshot.data
      ? `${"pmid" in snapshot.data.normalized ? "/publications" : "/trials"}/${snapshot.data.record_id}`
      : null,
  );
  if (evidence.isPending || snapshot.isPending)
    return evidence.error ? <ErrorPanel error={evidence.error} /> : <Loading />;
  if (evidence.error || snapshot.error)
    return <ErrorPanel error={evidence.error ?? snapshot.error} />;
  const item = evidence.data;
  const data = snapshot.data;
  const record = source.data;
  const external = safeSourceURL(record?.canonical_url);
  return (
    <div className="ph-stack ph-evidence-content">
      <div className="ph-row">
        <Badge status={data.is_demo ? "demo" : "live"} />
        <span className="ph-mono">{record?.external_id ?? data.record_id}</span>
      </div>
      <dl className="ph-definition">
        <div>
          <dt>数据来源</dt>
          <dd>
            {record?.source === "ctgov"
              ? "ClinicalTrials.gov"
              : record?.source === "pubmed"
                ? "PubMed"
                : "来源快照"}
          </dd>
        </div>
        <div>
          <dt>首次观测</dt>
          <dd>
            <Timestamp value={data.first_observed_at} />
          </dd>
        </div>
        <div>
          <dt>原文语言</dt>
          <dd>{item.original_language}</dd>
        </div>
        <div>
          <dt>快照版本</dt>
          <dd className="ph-mono">{data.id}</dd>
        </div>
        <div>
          <dt>字段定位</dt>
          <dd className="ph-mono">
            {item.locator.kind === "json_pointer"
              ? item.locator.path
              : `${item.locator.section} [${item.locator.start}, ${item.locator.end})`}
          </dd>
        </div>
      </dl>
      <div className="ph-quote">
        <Quote size={20} />
        <h3>原文引用</h3>
        <blockquote>{item.quoted_text}</blockquote>
      </div>
      {item.translation_text && (
        <details>
          <summary>查看机器辅助译文</summary>
          <p className="ph-notice">{item.translation_text}</p>
        </details>
      )}
      <div className="ph-hash">
        <Fingerprint size={16} />
        <div>
          <strong>快照内容 SHA-256</strong>
          <code>{data.content_hash}</code>
          <strong>引用片段 SHA-256</strong>
          <code>{item.snippet_hash}</code>
        </div>
      </div>
      {external && (
        <a href={external} target="_blank" rel="noreferrer" className="ph-link">
          打开官方来源 <ExternalLink size={14} />
        </a>
      )}
      <details>
        <summary>查看完整来源快照</summary>
        <pre className="ph-code">
          {JSON.stringify(data.raw_payload, null, 2)}
        </pre>
      </details>
    </div>
  );
}
