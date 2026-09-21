"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Activity,
  ArrowLeft,
  ArrowRight,
  Bell,
  BookOpen,
  ChevronRight,
  CircleHelp,
  FileCheck2,
  FlaskConical,
  LayoutDashboard,
  LogOut,
  Menu,
  Microscope,
  Search,
  Settings2,
  ShieldCheck,
  Sparkles,
  Radio,
} from "lucide-react";
import dynamic from "next/dynamic";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useRef, useState, type FormEvent } from "react";

import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { pharmaFetch, PharmaAPIError } from "@/core/pharma/client";
import { type Me } from "@/core/pharma/contracts";

import { WorkspaceProvider, usePharma } from "./context";
import { Dashboard } from "./dashboard";
import { DesignPreview } from "./design-preview";
import { EvidenceDrawer } from "./evidence-drawer";
import { Badge, Empty, ErrorPanel, Field, Loading } from "./ui";

const DrugsPage = dynamic(
  () => import("./entity-pages").then((module) => module.DrugsPage),
  { loading: Loading },
);
const DrugDetail = dynamic(
  () => import("./entity-pages").then((module) => module.DrugDetail),
  { loading: Loading },
);
const TrialsPage = dynamic(
  () => import("./entity-pages").then((module) => module.TrialsPage),
  { loading: Loading },
);
const TrialDetail = dynamic(
  () => import("./entity-pages").then((module) => module.TrialDetail),
  { loading: Loading },
);
const LiteraturePage = dynamic(
  () => import("./entity-pages").then((module) => module.LiteraturePage),
  { loading: Loading },
);
const PublicationDetail = dynamic(
  () => import("./entity-pages").then((module) => module.PublicationDetail),
  { loading: Loading },
);
const EventDetail = dynamic(
  () => import("./entity-pages").then((module) => module.EventDetail),
  { loading: Loading },
);
const ResearchList = dynamic(
  () => import("./research-pages").then((module) => module.ResearchList),
  { loading: Loading },
);
const ResearchNew = dynamic(
  () => import("./research-pages").then((module) => module.ResearchNew),
  { loading: Loading },
);
const ResearchDetail = dynamic(
  () => import("./research-pages").then((module) => module.ResearchDetail),
  { loading: Loading },
);
const ReportsList = dynamic(
  () => import("./research-pages").then((module) => module.ReportsList),
  { loading: Loading },
);
const ReportDetail = dynamic(
  () => import("./research-pages").then((module) => module.ReportDetail),
  { loading: Loading },
);
const ReviewPage = dynamic(
  () => import("./research-pages").then((module) => module.ReviewPage),
  { loading: Loading },
);
const SubscriptionsPage = dynamic(
  () =>
    import("./subscriptions-page").then((module) => module.SubscriptionsPage),
  { loading: Loading },
);
const SettingsPage = dynamic(
  () => import("./settings-pages").then((module) => module.SettingsPage),
  { loading: Loading },
);
const EventsPage = dynamic(
  () => import("./settings-pages").then((module) => module.EventsPage),
  { loading: Loading },
);
const InboxPage = dynamic(
  () => import("./settings-pages").then((module) => module.InboxPage),
  { loading: Loading },
);

function Logo() {
  return (
    <div className="ph-brand">
      <svg viewBox="0 0 36 36" width="36" height="36" aria-hidden="true">
        <path
          d="M18 6 29 12.5v13L18 32 7 25.5v-13L18 6Zm0 0v13m-11 6.5 11-6.5 11 6.5"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.8"
        />
        <circle cx="18" cy="6" r="4" fill="#6E8BFF" />
        <circle cx="7" cy="25.5" r="4" fill="#8ABAFB" />
        <circle cx="29" cy="25.5" r="4" fill="#6179F3" />
        <circle cx="18" cy="19" r="3" fill="currentColor" />
      </svg>
      <div>
        <strong>
          Pharma<span>Scope</span>
        </strong>
        <small>医药研发情报</small>
      </div>
    </div>
  );
}

export function PharmaApp({ path }: { path: string[] }) {
  const me = useQuery({
    queryKey: ["pharma-session"],
    queryFn: ({ signal }) => pharmaFetch<Me>("/auth/me", { signal }),
    retry: false,
    staleTime: 60_000,
  });
  if (
    path[0] === "login" ||
    (me.error instanceof PharmaAPIError && me.error.status === 401)
  )
    return <LoginPage />;
  if (me.isPending)
    return (
      <div className="ph-auth-loading">
        <Logo />
        <Loading />
      </div>
    );
  if (me.error)
    return (
      <div className="ph-auth-loading">
        <Logo />
        <ErrorPanel error={me.error} onRetry={() => void me.refetch()} />
      </div>
    );
  if (!me.data.memberships.length)
    return (
      <div className="ph-auth-loading">
        <Empty
          title="尚未加入工作区"
          description="请联系管理员添加工作区成员权限。"
        />
      </div>
    );
  return <WorkspaceApp key={me.data.user.id} me={me.data} path={path} />;
}

function LoginPage() {
  const client = useQueryClient();
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  async function login(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const me = await pharmaFetch<Me>("/auth/login", {
        method: "POST",
        body: { email, password },
      });
      client.clear();
      client.setQueryData(["pharma-session"], me);
      setPassword("");
      router.replace("/pharma/dashboard");
    } catch (error) {
      setError(error);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="ph-login">
      <section className="ph-login-story">
        <Logo />
        <div>
          <span className="ph-eyebrow">CLARITY THROUGH EVIDENCE</span>
          <h1>
            从研发动态，
            <br />
            到有依据的洞察。
          </h1>
          <p>
            让临床试验、科学文献与研究判断相互连接。
            <br />
            在每一次来源变化中，保留可追溯的证据。
          </p>
          <div className="ph-login-pillars">
            <span>
              <FlaskConical size={20} />
              追踪试验进展
            </span>
            <span>
              <BookOpen size={20} />
              连接原始证据
            </span>
            <span>
              <ShieldCheck size={20} />
              独立审核发布
            </span>
          </div>
        </div>
        <small>PHARMASCOPE · POWERED BY DEERFLOW</small>
      </section>
      <section className="ph-login-form-area">
        <form className="ph-login-form" onSubmit={login}>
          <span className="ph-eyebrow">WELCOME BACK</span>
          <h2>登录研究工作台</h2>
          <p>使用工作区账户，继续您的研发情报研究。</p>
          <Field label="邮箱">
            <input
              autoComplete="username"
              type="email"
              className="ph-input"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              required
              placeholder="name@organization.com"
            />
          </Field>
          <Field label="密码">
            <input
              autoComplete="current-password"
              type="password"
              className="ph-input"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              required
              placeholder="输入账户密码"
            />
          </Field>
          {error != null && <ErrorPanel error={error} />}
          <button
            className="ph-button ph-login-submit"
            type="submit"
            disabled={busy}
          >
            {busy ? "正在登录…" : "登录工作台"}
            <ArrowRight size={17} />
          </button>
          <p className="ph-login-help">
            <CircleHelp size={15} />
            账户由管理员创建；如需访问或重置密码，请联系管理员。
          </p>
          <Link className="ph-link" href="/workspace">
            <ArrowLeft size={14} />
            进入原有通用助手
          </Link>
        </form>
        <p className="ph-login-disclaimer">
          仅用于研发信息研究，不构成医疗建议或临床决策依据。
        </p>
      </section>
    </div>
  );
}

function WorkspaceApp({ me, path }: { me: Me; path: string[] }) {
  const client = useQueryClient();
  const router = useRouter();
  const [workspaceId, setWorkspaceId] = useState(() => {
    if (typeof window !== "undefined") {
      try {
        return (
          localStorage.getItem(`pharma-workspace:${me.user.id}`) ??
          me.memberships[0]!.workspace_id
        );
      } catch {
        /* Storage may be restricted. */
      }
    }
    return me.memberships[0]!.workspace_id;
  });
  const [evidence, setEvidence] = useState<string | null>(null);
  const evidenceTrigger = useRef<HTMLElement | null>(null);
  const workspace =
    me.memberships.find((member) => member.workspace_id === workspaceId) ??
    me.memberships[0]!;
  function selectWorkspace(id: string) {
    client.removeQueries({ queryKey: ["pharma"] });
    setEvidence(null);
    setWorkspaceId(id);
    try {
      localStorage.setItem(`pharma-workspace:${me.user.id}`, id);
    } catch {
      /* In-memory switching remains available. */
    }
    router.push("/pharma/dashboard");
  }
  return (
    <WorkspaceProvider
      key={workspace.workspace_id}
      me={me}
      workspace={workspace}
      openEvidence={(id) => {
        evidenceTrigger.current =
          document.activeElement instanceof HTMLElement
            ? document.activeElement
            : null;
        setEvidence(id);
      }}
    >
      <PharmaShell path={path} onWorkspace={selectWorkspace} />
      <EvidenceDrawer
        id={evidence}
        onClose={() => setEvidence(null)}
        restoreFocus={() => evidenceTrigger.current?.focus()}
      />
    </WorkspaceProvider>
  );
}

const navigation = [
  { path: "dashboard", label: "工作台", icon: LayoutDashboard, group: "总览" },
  { path: "drugs", label: "药物档案", icon: FlaskConical, group: "情报资料" },
  { path: "trials", label: "临床试验", icon: Activity, group: "情报资料" },
  { path: "literature", label: "文献情报", icon: BookOpen, group: "情报资料" },
  { path: "events", label: "研发事件", icon: Radio, group: "情报资料" },
  { path: "research", label: "专题研究", icon: Microscope, group: "研究协作" },
  { path: "reports", label: "研究报告", icon: FileCheck2, group: "研究协作" },
  { path: "review", label: "审核中心", icon: ShieldCheck, group: "研究协作" },
  { path: "subscriptions", label: "情报订阅", icon: Bell, group: "研究协作" },
];
function PharmaShell({
  path,
  onWorkspace,
}: {
  path: string[];
  onWorkspace: (id: string) => void;
}) {
  const { me, workspace, config } = usePharma();
  const client = useQueryClient();
  const router = useRouter();
  const [menu, setMenu] = useState(false);
  const menuTrigger = useRef<HTMLButtonElement>(null);
  const [search, setSearch] = useState("");
  const [logoutError, setLogoutError] = useState<unknown>(null);
  const route = path[0] ?? "dashboard";
  const reviewer = ["admin", "reviewer"].includes(workspace.role);
  const mode = config?.data_mode ?? workspace.data_mode;
  const nav = navigation.filter((item) => item.path !== "review" || reviewer);
  const label =
    nav.find((item) => item.path === route)?.label ??
    (route === "settings"
      ? "工作区设置"
      : route === "inbox"
        ? "通知中心"
        : "组件预览");
  async function logout() {
    try {
      await pharmaFetch("/auth/logout", { method: "POST" }, me.csrf_token);
      client.clear();
      router.replace("/pharma/login");
    } catch (error) {
      setLogoutError(error);
    }
  }
  const links = (
    <>
      <div className="ph-sidebar-brand">
        <Logo />
      </div>
      <nav aria-label="主要导航">
        {nav.map((item, index) => (
          <div key={item.path}>
            {index === 0 || nav[index - 1]?.group !== item.group ? (
              <span className="ph-nav-group">{item.group}</span>
            ) : null}
            <Link
              href={`/pharma/${item.path}`}
              aria-current={route === item.path ? "page" : undefined}
              title={item.label}
              onClick={() => setMenu(false)}
            >
              <item.icon size={19} />
              <span>{item.label}</span>
              {route === item.path && (
                <ChevronRight size={14} className="ph-nav-arrow" />
              )}
            </Link>
          </div>
        ))}
      </nav>
      <div className="ph-sidebar-bottom">
        <div className="ph-sidebar-tip">
          <Sparkles size={18} />
          <strong>以证据连接研发洞察</strong>
          <p>官方来源 · 版本追溯 · 人工审核</p>
        </div>
        <Link
          href="/pharma/settings"
          title="工作区设置"
          aria-current={route === "settings" ? "page" : undefined}
          onClick={() => setMenu(false)}
        >
          <Settings2 size={19} />
          <span>工作区设置</span>
        </Link>
        <Link href="/workspace" title="通用研究助手">
          <Microscope size={19} />
          <span>通用研究助手</span>
          <ArrowRight size={14} />
        </Link>
        <small>PharmaScope · 基于 DeerFlow</small>
      </div>
    </>
  );
  return (
    <div className="ph-shell">
      <a className="ph-skip" href="#ph-main">
        跳转到主要内容
      </a>
      <aside className="ph-sidebar">{links}</aside>
      <Sheet open={menu} onOpenChange={setMenu}>
        <SheetContent
          side="left"
          className="pharma-app ph-mobile-sidebar"
          onCloseAutoFocus={(event) => {
            event.preventDefault();
            menuTrigger.current?.focus();
          }}
        >
          <SheetHeader className="ph-sr-only">
            <SheetTitle>工作台导航</SheetTitle>
            <SheetDescription>选择资料或研究模块</SheetDescription>
          </SheetHeader>
          {links}
        </SheetContent>
      </Sheet>
      <div className="ph-main-shell">
        <header className="ph-topbar">
          <div className="ph-topbar-left">
            <button
              className="ph-icon-button ph-menu-button"
              ref={menuTrigger}
              aria-label="打开导航"
              onClick={() => setMenu(true)}
            >
              <Menu size={20} />
            </button>
            <span className="ph-breadcrumb">
              研发情报 <ChevronRight size={13} />
              <strong>{label}</strong>
            </span>
          </div>
          <form
            className="ph-top-search"
            onSubmit={(event) => {
              event.preventDefault();
              router.push(`/pharma/drugs?query=${encodeURIComponent(search)}`);
            }}
          >
            <Search size={16} />
            <input
              aria-label="搜索药物"
              placeholder="搜索药物名称、研发代号…"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
            />
            <kbd>↵</kbd>
          </form>
          <div className="ph-topbar-actions">
            <Link
              href="/pharma/inbox"
              className="ph-icon-button"
              aria-label="通知中心"
            >
              <Bell size={19} />
            </Link>
            <span className="ph-topbar-divider" />
            <div className="ph-account" data-testid="pharma-account">
              <span className="ph-avatar">
                {me.user.display_name.slice(0, 1)}
              </span>
              <div>
                <strong>{me.user.display_name}</strong>
                <small>
                  {workspace.role === "admin"
                    ? "管理员"
                    : workspace.role === "reviewer"
                      ? "审核员"
                      : workspace.role === "analyst"
                        ? "研究员"
                        : "只读成员"}
                </small>
              </div>
            </div>
            <button
              className="ph-icon-button"
              aria-label="退出登录"
              onClick={() => void logout()}
            >
              <LogOut size={17} />
            </button>
          </div>
        </header>
        <div className="ph-workspace-bar">
          <label>
            <span>当前工作区</span>
            <select
              aria-label="工作区"
              value={workspace.workspace_id}
              onChange={(event) => onWorkspace(event.target.value)}
            >
              {me.memberships.map((member) => (
                <option key={member.workspace_id} value={member.workspace_id}>
                  {member.workspace_name}
                </option>
              ))}
            </select>
          </label>
          <div className="ph-mode-banner">
            <Badge status={mode ?? "unknown"} />
            <span>
              {mode === "demo"
                ? "虚构资料 · 仅用于流程演示"
                : "官方资料 · 结论须经人工核验"}
            </span>
          </div>
        </div>
        <main id="ph-main" className="ph-main" tabIndex={-1}>
          {logoutError != null && <ErrorPanel error={logoutError} />}
          <RouteContent path={path} />
        </main>
        <footer className="ph-footer">
          <span>
            <ShieldCheck size={14} />
            仅用于研发信息研究，不构成医疗建议或临床决策依据。
          </span>
          <span>证据可追溯 · 结论需核验</span>
        </footer>
      </div>
    </div>
  );
}
function RouteContent({ path }: { path: string[] }) {
  const route = path[0] ?? "dashboard";
  const id = path[1];
  const { workspace } = usePharma();
  if (route === "dashboard") return <Dashboard />;
  if (route === "drugs") return id ? <DrugDetail id={id} /> : <DrugsPage />;
  if (route === "trials") return id ? <TrialDetail id={id} /> : <TrialsPage />;
  if (route === "literature" || route === "publications")
    return id ? <PublicationDetail id={id} /> : <LiteraturePage />;
  if (route === "events") return id ? <EventDetail id={id} /> : <EventsPage />;
  if (route === "research")
    return id === "new" ? (
      <ResearchNew />
    ) : id ? (
      <ResearchDetail id={id} />
    ) : (
      <ResearchList />
    );
  if (route === "reports")
    return id ? <ReportDetail id={id} /> : <ReportsList />;
  if (route === "review")
    return ["reviewer", "admin"].includes(workspace.role) ? (
      <ReviewPage />
    ) : (
      <Empty title="此页面需要审核权限" description="请联系工作区管理员。" />
    );
  if (route === "subscriptions") return <SubscriptionsPage />;
  if (route === "settings") return <SettingsPage />;
  if (route === "inbox") return <InboxPage />;
  if (route === "design-preview") return <DesignPreview />;
  return (
    <Empty
      title="页面不存在"
      action={
        <Link href="/pharma/dashboard" className="ph-button">
          返回工作台
        </Link>
      }
    />
  );
}
