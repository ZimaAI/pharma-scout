import { type Metadata } from "next";

import { PharmaQueryProvider } from "@/components/pharma/context";

import "@/styles/pharma.css";

export const metadata: Metadata = {
  title: {
    default: "PharmaScope · 医药研发情报",
    template: "%s · PharmaScope",
  },
  description: "临床试验进展、科学文献与可追溯证据的研发情报研究工作台。",
  robots: { index: false, follow: false },
};

export default function PharmaLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="pharma-app" lang="zh-CN">
      <PharmaQueryProvider>{children}</PharmaQueryProvider>
    </div>
  );
}
