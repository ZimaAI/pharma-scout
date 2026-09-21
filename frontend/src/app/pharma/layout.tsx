import { type Metadata } from "next";

import { PharmaQueryProvider } from "@/components/pharma/context";

import "@/styles/pharma.css";

export const metadata: Metadata = {
  title: {
    default: "PharmaScount · 医药研发情报",
    template: "%s · PharmaScount",
  },
  description: "临床试验进展、科学文献与可追溯证据的研发情报研究工作台。",
  robots: { index: false, follow: false },
  icons: {
    icon: [
      { url: "/pharma/brand/logo.svg", type: "image/svg+xml" },
      { url: "/pharma/brand/icon-32.png", type: "image/png", sizes: "32x32" },
    ],
    shortcut: "/pharma/brand/icon-32.png",
    apple: "/pharma/brand/apple-touch-icon.png",
  },
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
