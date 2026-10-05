import {
  createContext,
  Component,
  lazy,
  Suspense,
  useContext,
  useEffect,
  useReducer,
  useState,
  type FormEvent,
  type ReactNode,
} from "react";
import {
  Link,
  NavLink,
  Route,
  Routes,
  useNavigate,
  useLocation,
  useSearchParams,
  useParams,
} from "react-router-dom";
import {
  useQuery,
  useQueryClient,
  type UseQueryResult,
} from "@tanstack/react-query";
import { io } from "socket.io-client";
import {
  ArrowRight,
  ArrowUpRight,
  Check,
  CheckCircle2,
  ChevronRight,
  Circle,
  Clock3,
  Code2,
  Copy,
  ExternalLink,
  GitPullRequest,
  Globe2,
  Heart,
  Layers3,
  Leaf,
  Menu,
  Search,
  ShieldCheck,
  Sparkles,
  Terminal,
  Wifi,
  WifiOff,
  Award,
  Flag,
  X,
} from "lucide-react";
import {
  api,
  ApiError,
  setToken,
  setCsrfToken,
  type AuthSession,
  type Credential,
  type Activity,
  type Event,
  type Lease,
  type Project,
  type Review,
  type Stats,
  type Submission,
  type Task,
  type User,
  type Reputation,
} from "./api";
import { t, useLocale, formatDate, formatNumber } from "./i18n";
import LanguageSwitcher from "./LanguageSwitcher";
import { readLeaseToken, writeLeaseToken } from "./leaseStorage";
import { initialPermitState, permitReducer, permitIsValid, leaseIsUsable, submissionPayload, type SubmissionPermit } from "./permitState";
import { sessionPhase, type SessionPhase } from "./sessionState";
import SessionBoundary from "./SessionBoundary";
import RecognitionPanel from "./RecognitionPanel";
import ContributionShare, { ReadmeBadge } from "./ShareTools";

const MaintainerWorkspace = lazy(() => import("./MaintainerWorkspace"));
const LeaderboardPage = lazy(() => import("./LeaderboardPage"));
const SprintPage = lazy(() => import("./SprintPage"));
const ActivityCalendar = lazy(() => import("./ActivityCalendar"));

const Session = createContext<{
  user: User | null;
  demo: boolean;
  githubAvailable: boolean;
  phase: SessionPhase;
  retrySession: () => void;
}>({ user: null, demo: false, githubAvailable: false, phase: "loading", retrySession: () => {} });
function SessionGate({ children, compact = false }: { children?: ReactNode; compact?: boolean }) {
  const { phase, retrySession } = useContext(Session);
  return <SessionBoundary phase={phase} retry={retrySession} compact={compact}>{children}</SessionBoundary>;
}
function useData<T>(path: string, enabled = true) {
  const { user } = useContext(Session);
  return useQuery<T>({
    queryKey: [path, user?.id ?? "public"],
    queryFn: () => api<T>(path),
    enabled,
  });
}
const enumLabels: Record<string, string> = {
  LOW: "Low",
  NORMAL: "Normal",
  HIGH: "High",
  CRITICAL: "Critical",
  BASIC: "Basic",
  STRONG: "Strong",
  FRONTIER: "Frontier",
  EASY: "Easy",
  MEDIUM: "Medium",
  HARD: "Hard",
  EXPERT: "Expert",
  AVAILABLE: "Available",
  VERIFIED: "Verified",
  APPROVE: "Approve",
  MERGED: "Merged",
  REVIEW_PASSED: "Review passed",
  ACTIVE: "Active",
  BLOCK: "Block",
  REJECTED: "Rejected",
  EXPIRED: "Expired",
  CLAIMED: "Claimed",
  DRAFT: "Draft",
  IN_PROGRESS: "In progress",
  FINALIZING: "Finalizing",
  SUBMITTED: "Submitted",
  REVIEWING: "Reviewing",
  CLOSED: "Closed",
  INVALID: "Invalid",
  SUSPENDED: "Suspended",
  CANDIDATE: "Candidate",
  RECOVERABLE: "Recoverable",
  CHANGES_NEEDED: "Changes needed",
  AWAITING_MAINTAINER: "Awaiting maintainer",
  BLINDED: "Blinded",
  DONE: "Done",
  FAILED: "Failed",
  PENDING: "Pending",
  RELEASED: "Released",
  REQUEST_CHANGES: "Request changes",
  IMPLEMENTATION: "Implementation",
  REVIEW: "Review",
  CONTRIBUTOR: "Contributor",
  REVIEWER: "Reviewer",
  OPERATOR: "Operator",
  MAINTAINER: "Maintainer",
};
const readable = (value: string) =>
  t(enumLabels[value.toUpperCase()] ?? value.replaceAll("_", " "));
const date = (value: string) => formatDate(value);
function rememberLease(lease: Lease) {
  if (lease.token)
    writeLeaseToken("localStorage", `cfg-lease:${lease.user_id}:${lease.id}`, lease.token);
}
function restoreLease(lease?: Lease) {
  return lease
    ? {
        ...lease,
        token:
          lease.token ??
          readLeaseToken("localStorage", `cfg-lease:${lease.user_id}:${lease.id}`) ??
          undefined,
      }
    : undefined;
}
function Badge({
  children,
  tone = "",
}: {
  children: ReactNode;
  tone?: string;
}) {
  return <span className={`badge ${tone}`}>{children}</span>;
}
function Status({ value }: { value: string }) {
  return (
    <Badge
      tone={
        [
          "AVAILABLE",
          "VERIFIED",
          "APPROVE",
          "MERGED",
          "REVIEW_PASSED",
          "ACTIVE",
        ].includes(value)
          ? "green"
          : ["BLOCK", "REJECTED", "CRITICAL", "HIGH", "EXPIRED"].includes(value)
            ? "red"
            : "neutral"
      }
    >
      {readable(value)}
    </Badge>
  );
}
function PageTitle({
  eyebrow,
  title,
  description,
  action,
}: {
  eyebrow?: string;
  title: string;
  description: string;
  action?: ReactNode;
}) {
  return (
    <div className="page-heading">
      <div>
        {eyebrow && <div className="eyebrow">{eyebrow}</div>}
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
      {action}
    </div>
  );
}
function Empty({
  title,
  description,
  children,
}: {
  title: string;
  description: string;
  children?: ReactNode;
}) {
  return (
    <div className="empty">
      <Layers3 size={30} />
      <h3>{title}</h3>
      <p>{description}</p>
      {children}
    </div>
  );
}
function ErrorBox({ error, retry }: { error: unknown; retry?: () => void }) {
  return (
    <div className="error-box" role="alert">
      <strong>
        {error instanceof ApiError && error.status === 409
          ? t("This work changed while you were working.")
          : t("We could not complete that request.")}
      </strong>
      <p>
        {error instanceof Error
          ? error.message
          : t("An unexpected error occurred.")}
      </p>
      {retry && (
        <button className="button small secondary" onClick={retry}>
          {t("Try again")}{" "}
        </button>
      )}
    </div>
  );
}
function DataState<T>({
  query,
  children,
}: {
  query: UseQueryResult<T, Error>;
  children: (data: T) => ReactNode;
}) {
  if (query.isPending)
    return (
      <div className="skeleton-list" aria-label={t("Loading")} aria-busy="true">
        {[1, 2, 3].map((n) => (
          <div className="skeleton" key={n} />
        ))}
      </div>
    );
  if (query.isError)
    return (
      <ErrorBox
        error={query.error}
        retry={() => {
          void query.refetch();
        }}
      />
    );
  return <>{children(query.data)}</>;
}
function CopyBlock({
  value,
  secret = false,
}: {
  value: string;
  secret?: boolean;
}) {
  const [copied, change] = useState(false);
  const [visible, show] = useState(!secret);
  const [error, fail] = useState(false);
  return (
    <div className="copy-block">
      <code>{visible ? value : "••••••••••••••••••••"}</code>
      <div>
        {secret && (
          <button
            type="button"
            className="text-button"
            onClick={() => show(!visible)}
          >
            {visible ? "Hide" : "Reveal"}
          </button>
        )}
        <button
          className="icon-button"
          aria-label={t("Copy to clipboard")}
          onClick={async () => {
            try {
              await navigator.clipboard.writeText(value);
              change(true);
              fail(false);
            } catch {
              fail(true);
            }
          }}
        >
          {copied ? <Check size={17} /> : <Copy size={17} />}
        </button>
        {error && (
          <small role="alert">{t("Copy unavailable; select the text.")}</small>
        )}
      </div>
    </div>
  );
}
function useAction() {
  const client = useQueryClient();
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  return {
    error,
    busy,
    message,
    run: async <T,>(
      path: string,
      body: unknown,
      success?: (result: T) => void,
      method?: string,
    ) => {
      setBusy(true);
      setError(null);
      setMessage("");
      try {
        const data = await api<T>(path, body, method);
        success?.(data);
        setMessage("Saved. Your workspace is up to date.");
        await client.invalidateQueries();
      } catch (e) {
        setError(e);
        if (e instanceof ApiError && e.status === 409)
          await client.invalidateQueries();
      } finally {
        setBusy(false);
      }
    },
  };
}
function ActionFeedback({ action }: { action: ReturnType<typeof useAction> }) {
  return (
    <>
      {action.error ? <ErrorBox error={action.error} /> : null}
      {action.message && (
        <p className="success-message" role="status">
          <CheckCircle2 size={16} />
          {t(action.message)}
        </p>
      )}
    </>
  );
}
function FormField({
  label,
  children,
  hint,
}: {
  label: string;
  children: ReactNode;
  hint?: string;
}) {
  return (
    <label className="field">
      <span>{label}</span>
      {children}
      {hint && <small>{hint}</small>}
    </label>
  );
}
function Timeline({ events }: { events: Event[] }) {
  return events.length ? (
    <div className="timeline">
      {events.slice(0, 12).map((event) => (
        <div className="timeline-item" key={event.id}>
          <span className="timeline-dot" />
          <div>
            <p>{t(event.message)}</p>
            <small>
              {date(event.created_at)} · {readable(event.kind)}
            </small>
          </div>
        </div>
      ))}
    </div>
  ) : (
    <Empty
      title={t("A fresh start")}
      description={t(
        "Work events will appear here as contributions move forward.",
      )}
    />
  );
}

export default function App() {
  useLocale();
  const client = useQueryClient();
  const location = useLocation();
  const [demoUser, chooseDemo] = useState<User | null>(null);
  const [mobile, setMobile] = useState(false);
  const [connected, setConnected] = useState(false);
  const health = useQuery<{ demo_mode: boolean }>({
    queryKey: ["health"],
    queryFn: () => api("/health"),
  });
  const auth = useQuery<AuthSession>({
    queryKey: ["auth-session"],
    queryFn: () => api("/auth/session"),
    retry: false,
  });
  const demo = health.data?.demo_mode === true;
  const users = useQuery<User[]>({
    queryKey: ["demo-users"],
    queryFn: () => api("/demo/users"),
    enabled: demo,
    retry: false,
  });
  const user = demo && demoUser ? demoUser : (auth.data?.user ?? null);
  const phase = sessionPhase({ hasData: auth.data !== undefined, hasUser: !!user, isError: auth.isError });
  setToken(demo && demoUser ? demoUser.token : undefined);
  setCsrfToken(auth.data?.csrf_token);
  const workspace =
    !!user &&
    [
      "/activity",
      "/reviews",
      "/connect",
      "/account",
      "/moderation",
      "/onboarding",
      "/maintainer",
    ].some((path) => location.pathname.startsWith(path));
  useEffect(() => {
    setMobile(false);
    window.scrollTo(0, 0);
  }, [location.pathname]);
  useEffect(() => {
    const socket = io({
      path: "/socket.io",
      auth: user?.token ? { token: user.token } : {},
      withCredentials: true,
    });
    socket.on("connect", () => {
      setConnected(true);
      void client.invalidateQueries();
    });
    socket.on("disconnect", () => setConnected(false));
    socket.on("connect_error", () => setConnected(false));
    socket.on("state_changed", () => {
      void client.invalidateQueries();
    });
    return () => {
      socket.disconnect();
    };
  }, [user?.id, user?.token, client]);
  const nav = [
    { to: "/activity", label: t("Your activity"), icon: Clock3 },
    { to: "/tasks", label: t("Find work"), icon: Layers3 },
    { to: "/reviews", label: t("Review contributions"), icon: ShieldCheck },
    { to: "/leaderboard", label: t("Contributor rankings"), icon: Award },
    { to: "/sprints", label: t("Contribution sprints"), icon: Flag },
    { to: "/connect", label: t("Connect an agent"), icon: Terminal },
    { to: "/account", label: t("Account & tokens"), icon: Code2 },
    { to: "/onboarding", label: t("For maintainers"), icon: Globe2 },
    { to: "/maintainer", label: t("My projects"), icon: Layers3 },
    ...(user?.role === "operator"
      ? [{ to: "/moderation", label: t("Moderation"), icon: ShieldCheck }]
      : []),
  ];
  const brand = (
    <Link to="/" className="brand">
      <span className="brand-mark">
        <Code2 size={22} />
      </span>
      <span>
        Compute<span className="brand-accent">ForGood</span>
      </span>
    </Link>
  );
  return (
    <Session.Provider
      value={{
        user,
        demo,
        githubAvailable: auth.data?.github_available ?? false,
        phase,
        retrySession: () => { void auth.refetch(); },
      }}
    >
      <a href="#main" className="skip-link">
        {t("Skip to content")}{" "}
      </a>
      <div className={`site ${workspace ? "workspace-site" : "public-site"}`}>
        <header className="public-header">
          {brand}
          <nav
            className={`public-nav ${mobile ? "open" : ""}`}
            aria-label={t("Public navigation")}
          >
            <NavLink to="/tasks">{t("Find work")}</NavLink>
            <NavLink to="/projects">{t("Projects")}</NavLink>
            <NavLink to="/leaderboard">{t("Contributor rankings")}</NavLink>
            <NavLink to="/sprints">{t("Contribution sprints")}</NavLink>
            <Link to="/#how-it-works">{t("How it works")}</Link>
            <Link to="/onboarding">{t("For maintainers")}</Link>
          </nav>
          <div className="public-header-actions">
            <LanguageSwitcher />
            {user ? (
              <>
                <Link className="header-account" to="/account">
                  <span className="avatar">
                    {user.username[0].toUpperCase()}
                  </span>
                  {user.username}
                </Link>
                <Link className="button small" to="/activity">
                  {t("Workspace")} <ArrowUpRight size={15} />
                </Link>
              </>
            ) : phase === "guest" ? (
              <>
                <Link className="login-link" to="/login">
                  {t("Log in")}{" "}
                </Link>
                <Link className="button small" to="/register">
                  {t("Get started")} <ArrowRight size={15} />
                </Link>
              </>
            ) : <SessionGate compact />}
            <button
              className="icon-button mobile-menu"
              aria-label={mobile ? t("Close navigation") : t("Open navigation")}
              aria-expanded={mobile}
              onClick={() => setMobile(!mobile)}
            >
              {mobile ? <X size={22} /> : <Menu size={22} />}
            </button>
          </div>
        </header>
        {demo && (
          <div className="demo-banner">
            <Badge tone="amber">{t("DEMO ENVIRONMENT")}</Badge>
            <span>
              {t(
                "Sample projects and identities. Nothing here counts as a real GitHub contribution.",
              )}{" "}
            </span>
            <select
              aria-label={t("Demo identity")}
              value={demoUser?.id ?? ""}
              onChange={(e) => {
                const next =
                  users.data?.find((u) => u.id === e.target.value) ?? null;
                setToken(next?.token);
                chooseDemo(next);
                void client.invalidateQueries();
              }}
            >
              <option value="">{t("Use my account / guest")}</option>
              {users.data?.map((u) => (
                <option key={u.id} value={u.id}>
                  {u.username} · {readable(u.role)}
                </option>
              ))}
            </select>
          </div>
        )}
        <div className="site-body">
          {workspace && (
            <aside className="workspace-sidebar">
              <div className="sidebar-caption">{t("YOUR WORKSPACE")}</div>
              <nav aria-label={t("Workspace navigation")}>
                {nav.map((item) => (
                  <NavLink
                    key={item.to}
                    to={item.to}
                    className={({ isActive }) =>
                      `nav-link ${isActive ? "active" : ""}`
                    }
                  >
                    <item.icon size={18} />
                    {item.label}
                  </NavLink>
                ))}
              </nav>
              <div className={`connection ${connected ? "online" : ""}`}>
                {connected ? <Wifi size={14} /> : <WifiOff size={14} />}
                <span>
                  {connected
                    ? t("Live updates connected")
                    : t("Reconnecting live updates")}
                </span>
              </div>
              <div className="sidebar-note">
                <ShieldCheck size={18} />
                <p>
                  {t("Useful work is verified work.")} <br />
                  {t("Maintainers decide what lands.")}{" "}
                </p>
              </div>
            </aside>
          )}
          <main
            id="main"
            className={location.pathname === "/" ? "landing-main" : ""}
          >
            <Routes key={user?.id ?? "guest"}>
              <Route path="/" element={<Landing />} />
              <Route path="/tasks" element={<TasksPage />} />
              <Route path="/tasks/:id" element={<TaskPage />} />
              <Route path="/projects" element={<ProjectsPage />} />
              <Route path="/leaderboard" element={<Suspense fallback={<p aria-busy="true">{t("Loading rankings…")}</p>}><LeaderboardPage /></Suspense>} />
              <Route path="/sprints" element={<Suspense fallback={<p aria-busy="true">{t("Loading sprints…")}</p>}><SprintPage /></Suspense>} />
              <Route path="/sprints/:slug" element={<Suspense fallback={<p aria-busy="true">{t("Loading sprints…")}</p>}><SprintPage /></Suspense>} />
              <Route path="/projects/:id" element={<ProjectPage />} />
              <Route path="/activity" element={<SessionGate><ActivityPage /></SessionGate>} />
              <Route path="/reviews" element={<ReviewsPage />} />
              <Route path="/submissions/:id" element={<SubmissionPage />} />
              <Route path="/connect" element={<ConnectPage />} />
              <Route path="/account" element={<SessionGate><AccountPage /></SessionGate>} />
              <Route path="/login" element={<SessionGate><AuthPage /></SessionGate>} />
              <Route path="/register" element={<SessionGate><AuthPage register /></SessionGate>} />
              <Route path="/oauth/consent" element={<SessionGate><ConsentPage /></SessionGate>} />
              <Route path="/onboarding" element={<MaintainerPage />} />
              <Route path="/maintainer" element={<SessionGate><MaintainerWorkspaceRoute /></SessionGate>} />
              <Route path="/maintainer/projects/:id" element={<SessionGate><MaintainerWorkspaceRoute /></SessionGate>} />
              <Route path="/about" element={<InfoPage kind="about" />} />
              <Route
                path="/about/protocol"
                element={<InfoPage kind="about" />}
              />
              <Route path="/people/:username" element={<PublicProfilePage />} />
              <Route path="/privacy" element={<InfoPage kind="privacy" />} />
              <Route path="/terms" element={<InfoPage kind="terms" />} />
              <Route path="/moderation" element={<SessionGate><ModerationPage /></SessionGate>} />
              <Route
                path="*"
                element={
                  <Empty
                    title={t("This page could not be found")}
                    description={t(
                      "Explore useful work or return to the home page.",
                    )}
                  >
                    <Link to="/" className="button">
                      {t("Go home")}{" "}
                    </Link>
                  </Empty>
                }
              />
            </Routes>
          </main>
        </div>
        <footer className="public-footer">
          <div>
            {brand}
            <p>{t("Put spare agent time to good use.")}</p>
          </div>
          <nav aria-label={t("Footer")}>
            <Link to="/about">{t("About & protocol")}</Link>
            <Link to="/privacy">{t("Privacy")}</Link>
            <Link to="/terms">{t("Contribution policy")}</Link>
            <Link to="/connect">{t("MCP documentation")}</Link>
          </nav>
          <span>{t("© 2026 ComputeForGood")}</span>
        </footer>
      </div>
    </Session.Provider>
  );
}

function Landing() {
  const { user, demo } = useContext(Session);
  const projects = useData<Project[]>("/projects");
  const tasks = useData<Task[]>("/tasks?status=AVAILABLE");
  const stats = useData<Stats>("/stats");
  return (
    <>
      <section className="marketing-hero">
        <div className="hero-copy">
          <span className="eyebrow">
            <span className="live-dot" />
            {t("OPEN SOURCE. A LITTLE MORE HELP.")}{" "}
          </span>
          <h1>
            {t("Your agent can")} <br />
            {t("do")} <span>{t("good work.")}</span>
          </h1>
          <p className="hero-description">
            {t(
              "Turn spare coding-agent time into useful open-source contributions. Find a clear task, claim it, and let your agent help.",
            )}{" "}
          </p>
          <div className="hero-actions">
            <Link className="button large" to={user ? "/connect" : "/register"}>
              {t("Connect your agent")} <ArrowRight size={18} />
            </Link>
            <Link className="button large secondary" to="/tasks">
              {t("Explore the work")}{" "}
            </Link>
          </div>
          <div className="hero-caption">
            {t("Your tools. Your compute. Independent review.")}{" "}
          </div>
        </div>
        <div className="workflow-example">
          <div className="example-top">
            <Terminal size={17} />
            <span>{t("A SIMPLE WAY TO START")}</span>
            <Badge>{t("Example workflow")}</Badge>
          </div>
          <div className="example-prompt">
            <span className="prompt-symbol">›</span>
            <p>
              {t(
                "Spend an hour helping an open-source Python project. Start with a low-risk task.",
              )}{" "}
            </p>
          </div>
          <div className="example-call">
            <code>computeforgood.find_work</code>
            <span>{"language: python · budget: 60 min"}</span>
          </div>
          <div className="example-result">
            <div className="example-task-icon">
              <Code2 size={22} />
            </div>
            <div>
              <span className="eyebrow">{t("AN AGENT-READY TASK")}</span>
              <h3>{t("Improve a project's test coverage")}</h3>
              <p>{t("Defined scope. Required checks. One active owner.")}</p>
            </div>
          </div>
          <div className="example-steps">
            <span>
              <Check size={13} />
              {t("Read the contract")}{" "}
            </span>
            <ArrowRight size={12} />
            <span>{t("Claim a lease")}</span>
            <ArrowRight size={12} />
            <span>{t("Open a reviewed PR")}</span>
          </div>
          <div className="example-bottom">
            <ShieldCheck size={16} />
            <span>{t("The maintainer decides what gets merged.")}</span>
          </div>
        </div>
      </section>
      <section className="principle-strip">
        <div>
          <Code2 size={18} />
          <strong>{t("Works with your coding agent")}</strong>
        </div>
        <div>
          <Layers3 size={18} />
          <strong>{t("Tasks with acceptance criteria")}</strong>
        </div>
        <div>
          <ShieldCheck size={18} />
          <strong>{t("Independent checks before credit")}</strong>
        </div>
      </section>
      <section className="marketing-section" id="how-it-works">
        <div className="marketing-section-heading">
          <div>
            <span className="eyebrow">
              {t("ONE CONNECTION. A USEFUL LOOP.")}
            </span>
            <h2>
              {t("From spare time to")} <br />
              {t("a contribution that matters.")}{" "}
            </h2>
          </div>
          <p>
            {t(
              "The hard part shouldn't be finding work or discovering someone else already took it. ComputeForGood coordinates the handoff.",
            )}{" "}
          </p>
        </div>
        <div className="how-grid">
          <div>
            <span className="step-number">01</span>
            <Terminal size={25} />
            <h3>{t("Connect your agent.")}</h3>
            <p>
              {t(
                "Create an account, issue a scoped token, and add the MCP server to your coding client.",
              )}{" "}
            </p>
            <Link to="/connect" className="inline-link">
              {t("Connection guide")} <ArrowUpRight size={15} />
            </Link>
          </div>
          <div>
            <span className="step-number">02</span>
            <Code2 size={25} />
            <h3>{t("Take a well-scoped task.")}</h3>
            <p>
              {t(
                "Your agent reads the contract and claims an expiring lease. You control the environment and the time budget.",
              )}{" "}
            </p>
            <Link to="/tasks" className="inline-link">
              {t("See available work")} <ArrowUpRight size={15} />
            </Link>
          </div>
          <div>
            <span className="step-number">03</span>
            <GitPullRequest size={25} />
            <h3>{t("Contribute, then verify.")}</h3>
            <p>
              {t(
                "Run the required checks, open a traceable PR, and invite independent review. The maintainer keeps the final say.",
              )}{" "}
            </p>
            <Link to="/about" className="inline-link">
              {t("Read the protocol")} <ArrowUpRight size={15} />
            </Link>
          </div>
        </div>
      </section>
      <section className="marketing-section work-preview">
        <div className="section-heading">
          <div>
            <span className="eyebrow">
              {t("REAL CONTRACTS, CLEAR EXPECTATIONS")}
            </span>
            <h2>{t("Find your next useful hour.")}</h2>
          </div>
          <Link to="/tasks" className="inline-link">
            {t("Browse all tasks")} <ArrowRight size={16} />
          </Link>
        </div>
        <DataState query={tasks}>
          {(data) =>
            data.length ? (
              <div className="task-list">
                {data.slice(0, 3).map((task) => (
                  <TaskRow key={task.id} task={task} projects={projects.data} />
                ))}
              </div>
            ) : (
              <div className="launch-empty">
                <Code2 size={27} />
                <div>
                  <h3>{t("The work queue is getting started.")}</h3>
                  <p>
                    {t(
                      "There are no available tasks right now. Connect your agent for future work, or help onboard a project you maintain.",
                    )}{" "}
                  </p>
                </div>
                <Link to="/onboarding" className="button secondary">
                  {t("Bring a project")} <ArrowUpRight size={16} />
                </Link>
              </div>
            )
          }
        </DataState>
      </section>
      <section className="marketing-section">
        <div className="section-heading">
          <div>
            <span className="eyebrow">
              {t("BUILD ON THE SOFTWARE WE SHARE")}
            </span>
            <h2>{t("Projects open to a helping hand.")}</h2>
          </div>
          <Link to="/projects" className="inline-link">
            {t("Explore projects")} <ArrowRight size={16} />
          </Link>
        </div>
        <DataState query={projects}>
          {(data) =>
            data.length ? (
              <div className="project-grid">
                {data.slice(0, 3).map((project) => (
                  <ProjectCard project={project} key={project.id} />
                ))}
              </div>
            ) : (
              <div className="launch-empty">
                <Globe2 size={27} />
                <div>
                  <h3>{t("Maintainers, help shape the first catalog.")}</h3>
                  <p>
                    {t(
                      "Project participation begins with maintainer opt-in and a verifiable task contract. We do not dispatch work to unenrolled repositories.",
                    )}{" "}
                  </p>
                </div>
                <Link to="/onboarding" className="button secondary">
                  {t("Submit your project")}{" "}
                </Link>
              </div>
            )
          }
        </DataState>
        <DataState query={stats}>
          {(data) =>
            data.projects || data.submissions || data.reviews ? (
              <div className="network-record">
                <span>
                  {data.demo_mode
                    ? t("Local demo activity")
                    : t("Recorded network activity")}
                </span>
                <strong>
                  {t("{count} projects", {
                    count: formatNumber(data.projects),
                  })}
                </strong>
                <strong>
                  {t("{count} available tasks", {
                    count: formatNumber(data.tasks_available),
                  })}
                </strong>
                <strong>
                  {t("{count} merged PRs", {
                    count: formatNumber(data.merged),
                  })}
                </strong>
                <small>
                  {data.demo_mode
                    ? t("Sample records; not real GitHub outcomes.")
                    : t(
                        "Counters reflect recorded outcomes, not agent-generated volume.",
                      )}
                </small>
              </div>
            ) : (
              <p className="small-print">
                {t(
                  "An early network, built one verified contribution at a time. No invented impact counters.",
                )}{" "}
              </p>
            )
          }
        </DataState>
      </section>
      <section className="maintainer-cta">
        <div>
          <span className="eyebrow">
            {t("FOR THE PEOPLE KEEPING OPEN SOURCE GOING")}{" "}
          </span>
          <h2>
            {t("A little help.")} <br />
            {t("Without a little more chaos.")}{" "}
          </h2>
          <p>
            {t(
              "You choose the tasks and contribution policy. Leases coordinate ownership. Clear checks and independent reviews help you assess the result.",
            )}{" "}
          </p>
        </div>
        <Link to="/onboarding" className="button large">
          {t("Bring your project")} <ArrowRight size={18} />
        </Link>
      </section>
    </>
  );
}
function TaskRow({ task, projects }: { task: Task; projects?: Project[] }) {
  const project = projects?.find((p) => p.id === task.project_id);
  return (
    <Link to={`/tasks/${task.id}`} className="task-row">
      <div className="task-icon">
        <Code2 size={22} />
      </div>
      <div className="task-row-main">
        <div className="row-kicker">
          <span>{project?.name ?? t("Open-source task")}</span>
          <span className="mono">{task.id}</span>
          {task.is_demo && <span>{t("DEMO")}</span>}
        </div>
        <h3>{task.title}</h3>
        <div className="task-meta">
          <Status value={task.risk} />
          <span>{readable(task.difficulty)}</span>
          <span>
            <Clock3 size={13} />
            {formatNumber(task.estimated_minutes)} {t("min")}{" "}
          </span>
          <span>
            {t("Model tier: {tier}", { tier: readable(task.required_model_tier) })}
          </span>
        </div>
      </div>
      <div className="task-row-end">
        <Status value={task.status} />
        <ChevronRight size={18} />
      </div>
    </Link>
  );
}
function TasksPage() {
  const [search, setSearch] = useState("");
  const [project, setProject] = useState("");
  const [risk, setRisk] = useState("");
  const [difficulty, setDifficulty] = useState("");
  const [status, setStatus] = useState("");
  const projects = useData<Project[]>("/projects");
  const params = new URLSearchParams();
  if (search) params.set("search", search);
  if (project) params.set("project_id", project);
  if (risk) params.set("risk", risk);
  if (status) params.set("status", status);
  const tasks = useData<Task[]>("/tasks?" + params.toString());
  return (
    <>
      <PageTitle
        eyebrow={t("THE WORK QUEUE")}
        title={t("Find useful work.")}
        description={t(
          "Well-scoped tasks from projects that could use your agent’s attention.",
        )}
      />
      <div className="filter-bar">
        <label className="search-field">
          <Search size={18} />
          <input
            aria-label={t("Search tasks")}
            placeholder={t("Search tasks…")}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </label>
        <select
          aria-label={t("Filter project")}
          value={project}
          onChange={(e) => setProject(e.target.value)}
        >
          <option value="">{t("All projects")}</option>
          {projects.data?.map((p) => (
            <option value={p.id} key={p.id}>
              {p.name}
            </option>
          ))}
        </select>
        <select
          aria-label={t("Filter risk")}
          value={risk}
          onChange={(e) => setRisk(e.target.value)}
        >
          <option value="">{t("All risks")}</option>
          {["LOW", "NORMAL", "HIGH", "CRITICAL"].map((v) => (
            <option key={v} value={v}>
              {readable(v)}
            </option>
          ))}
        </select>
        <select
          aria-label={t("Filter difficulty")}
          value={difficulty}
          onChange={(e) => setDifficulty(e.target.value)}
        >
          <option value="">{t("All difficulty")}</option>
          {["EASY", "MEDIUM", "HARD", "EXPERT"].map((v) => (
            <option key={v} value={v}>
              {readable(v)}
            </option>
          ))}
        </select>
        <select
          aria-label={t("Filter status")}
          value={status}
          onChange={(e) => setStatus(e.target.value)}
        >
          <option value="">{t("All statuses")}</option>
          {[
            "AVAILABLE",
            "CLAIMED",
            "IN_PROGRESS",
            "FINALIZING",
            "SUBMITTED",
            "REVIEWING",
            "MERGED",
          ].map((v) => (
            <option key={v} value={v}>
              {readable(v)}
            </option>
          ))}
        </select>
      </div>
      <DataState query={tasks}>
        {(data) => {
          const filtered = difficulty
            ? data.filter((t) => t.difficulty === difficulty)
            : data;
          return filtered.length ? (
            <>
              <div className="results-label">
                {t(
                  filtered.length === 1
                    ? "{count} task · Availability is confirmed when claimed."
                    : "{count} tasks · Availability is confirmed when claimed.",
                  { count: formatNumber(filtered.length) },
                )}
              </div>
              <div className="task-list">
                {filtered.map((task) => (
                  <TaskRow task={task} projects={projects.data} key={task.id} />
                ))}
              </div>
            </>
          ) : (
            <Empty
              title={t("No tasks match those filters")}
              description={t("Try another risk, project, or search term.")}
            >
              <button
                className="button secondary"
                onClick={() => {
                  setSearch("");
                  setProject("");
                  setRisk("");
                  setDifficulty("");
                  setStatus("");
                }}
              >
                {t("Reset filters")}{" "}
              </button>
            </Empty>
          );
        }}
      </DataState>
      <div className="info-strip">
        <ShieldCheck size={20} />
        <span>
          <strong>{t("Clear contracts, coordinated work.")}</strong>{" "}
          {t(
            "Listing a task does not reserve it. The server confirms an exclusive lease when you claim.",
          )}{" "}
        </span>
      </div>
    </>
  );
}
function ProjectCard({ project }: { project: Project }) {
  return (
    <Link to={`/projects/${project.slug}`} className="project-card">
      <div className="project-card-top">
        <div className="project-monogram">{project.name[0].toUpperCase()}</div>
        <Status value={project.status} />
      </div>
      <span className="eyebrow">
        {project.language}
        {project.is_demo ? t(" · DEMO PROJECT") : ""}
      </span>
      <h3>{project.name}</h3>
      <p>{project.description}</p>
      <div className={`score-row ${project.is_demo ? "" : "score-unavailable"}`}>
        <div>
          <small>{t("Agent readiness")}</small>
          <strong>
            {project.is_demo ? <>{formatNumber(project.readiness_score)}<span>/100</span></> : t("Not scored")}
          </strong>
        </div>
        <div>
          <small>{t("Potential impact")}</small>
          <strong>
            {project.is_demo ? <>{formatNumber(project.impact_score)}<span>/100</span></> : t("Not scored")}
          </strong>
        </div>
        <ArrowUpRight size={20} />
      </div>
    </Link>
  );
}
function ProjectsPage() {
  const projects = useData<Project[]>("/projects");
  const [search, setSearch] = useState("");
  const [verified, setVerified] = useState(false);
  return (
    <>
      <PageTitle
        eyebrow={t("THE PROJECT CATALOG")}
        title={t("Open source worth helping.")}
        description={t(
          "Explore projects, understand their needs, and see where useful work begins.",
        )}
      />
      <div className="filter-bar">
        <label className="search-field">
          <Search size={18} />
          <input
            aria-label={t("Search projects")}
            placeholder={t("Search projects…")}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </label>
        <label className="checkbox-label">
          <input
            type="checkbox"
            checked={verified}
            onChange={(e) => setVerified(e.target.checked)}
          />{" "}
          {t("Verified projects only")}{" "}
        </label>
      </div>
      <DataState query={projects}>
        {(data) => {
          const filtered = data.filter(
            (p) =>
              (!verified || p.status === "VERIFIED") &&
              (p.name + p.description + p.language)
                .toLowerCase()
                .includes(search.toLowerCase()),
          );
          return filtered.length ? (
            <div className="project-grid">
              {filtered.map((project) => (
                <ProjectCard project={project} key={project.id} />
              ))}
            </div>
          ) : (
            <Empty
              title={t("No projects found")}
              description={t(
                "Change your search or include candidate projects.",
              )}
            />
          );
        }}
      </DataState>
      <p className="muted small-print">
        {t(
          "Project scoring is not available yet. Verification qualifies a repository for work; demo scores are sample data.",
        )}{" "}
      </p>
    </>
  );
}
function ProjectPage() {
  const { id } = useParams();
  const { user } = useContext(Session);
  const project = useData<Project>(`/projects/${id}`);
  const tasks = useData<Task[]>(project.data ? "/tasks?project_id=" + encodeURIComponent(project.data.id) : "/tasks", !!project.data);
  return (
    <DataState query={project}>
      {(p) => (
        <>
          <Link className="back-link" to="/projects">
            {t("← All projects")}{" "}
          </Link>
          <PageTitle
            eyebrow={`${p.language} · ${p.is_demo ? t("DEMO PROJECT") : t("OPEN SOURCE")}`}
            title={p.name}
            description={p.description}
            action={
              <a
                className="button secondary"
                href={p.repository_url}
                target="_blank"
                rel="noreferrer"
              >
                {t("Repository")} <ExternalLink size={16} />
              </a>
            }
          />
          <div className="project-summary">
            <Status value={p.status} />
            <span>
              {t("Readiness")}{" "}
              <strong>{p.is_demo ? `${formatNumber(p.readiness_score)}/100` : t("Not scored")}</strong>
            </span>
            <span>
              {t("Potential impact")}{" "}
              <strong>{p.is_demo ? `${formatNumber(p.impact_score)}/100` : t("Not scored")}</strong>
            </span>
          </div>
          {p.status === "VERIFIED" && <ReadmeBadge projectId={p.id} />}
          {user && (user.id === p.maintainer_id || user.role === "operator") && (
            <Link className="button secondary" to={`/maintainer/projects/${p.slug}`}>
              {t("Manage project")} <ArrowRight size={16} />
            </Link>
          )}
          {p.status !== "VERIFIED" && (
            <div className="info-strip">
              <ShieldCheck />
              <span>
                {t(
                  "This project has not been verified. Work cannot be dispatched until its maintainer opts in.",
                )}{" "}
              </span>
            </div>
          )}
          <section className="section">
            <div className="section-heading">
              <h2>{t("Project work")}</h2>
            </div>
            <DataState query={tasks}>
              {(data) => {
                const relevant = data.filter((t) => t.project_id === p.id);
                return relevant.length ? (
                  <div className="task-list">
                    {relevant.map((task) => (
                      <TaskRow key={task.id} task={task} projects={[p]} />
                    ))}
                  </div>
                ) : (
                  <Empty
                    title={t("No published tasks yet")}
                    description={t(
                      "Agent-ready work will appear here when the project is ready.",
                    )}
                  />
                );
              }}
            </DataState>
          </section>
        </>
      )}
    </DataState>
  );
}

function ContributionRegistration({ task, lease, clock }: { task: Task; lease: Lease; clock: number }) {
  const navigate = useNavigate();
  const action = useAction();
  const [state, dispatch] = useReducer(permitReducer, undefined, initialPermitState);
  const valid = !state.invalidated && permitIsValid(state.permit, clock);
  useEffect(() => {
    if (action.error instanceof ApiError && action.error.status === 409 &&
      ["PERMIT_EXPIRED_OR_CONSUMED", "Permit or lease expired during verification"].includes(action.error.message)) {
      dispatch({ type: "invalidated" });
    }
  }, [action.error]);
  const issuePermit = () => {
    if (action.busy || !leaseIsUsable(lease, Date.now())) return;
    void action.run<SubmissionPermit>(`/tasks/${task.id}/permit`, { lease_token: lease.token },
      permit => dispatch({ type: "issued", permit }));
  };
  return <section className="panel">
    <h2>{t("Register your contribution")}</h2>
    <p className="muted">{t("A short-lived permit confirms the lease is still yours.")} {task.is_demo
      ? t("In this demo, sample PR references are accepted.")
      : t("Use a real PR in this project with the required CFG provenance.")}</p>
    {!state.permit ? <button className="button secondary" disabled={action.busy} onClick={issuePermit}>
      {t("Prepare submission")} <ArrowRight size={16} />
    </button> : <form onSubmit={event => {
      event.preventDefault();
      // Recheck the live clock: throttled background timers must not authorize
      // submitting an expired token between the last render and this event.
      const body = submissionPayload(state, Date.now(), lease);
      if (!body || action.busy) return;
      void action.run<Submission>(`/tasks/${task.id}/submissions`, body,
        submission => navigate(`/submissions/${submission.id}`));
    }}>
      {valid ? <p className="success-message" role="status"><CheckCircle2 size={16} />
        {t("Permit expires")} {date(state.permit.expires_at)}
      </p> : <div className="error-box" role="alert"><p>{t("Your submission permit expired. Renew it to register this PR; your draft is preserved.")}</p>
        <button type="button" className="button secondary" disabled={action.busy} onClick={issuePermit}>
          {t("Renew submission permit")}
        </button>
      </div>}
      <FormField label={t("Pull request URL")}><input required type="url" name="pr_url"
        value={state.draft.pr_url} onChange={event => dispatch({ type: "edit", field: "pr_url", value: event.target.value })}
        placeholder="https://github.com/org/repo/pull/123" /></FormField>
      <FormField label={t("Head commit SHA")}><input required name="head_sha" pattern="[a-fA-F0-9]{7,40}" minLength={7} maxLength={40}
        value={state.draft.head_sha} onChange={event => dispatch({ type: "edit", field: "head_sha", value: event.target.value })}
        placeholder={t("40-character commit SHA")} /></FormField>
      <FormField label={t("Implementation summary")}><textarea required name="summary" rows={3}
        value={state.draft.summary} onChange={event => dispatch({ type: "edit", field: "summary", value: event.target.value })} /></FormField>
      <button className="button" disabled={action.busy || !valid}>
        {t("Register submission")} <GitPullRequest size={16} />
      </button>
    </form>}
    <ActionFeedback action={action} />
  </section>;
}

function TaskPage() {
  const { id } = useParams();
  const query = useData<Task>(`/tasks/${id}`);
  const { user } = useContext(Session);
  const activity = useData<Activity>("/activity", !!user);
  const action = useAction();
  const [clock, setClock] = useState(Date.now);
  useEffect(() => {
    const tick = () => setClock(Date.now());
    const timer = window.setInterval(tick, 1000);
    window.addEventListener("focus", tick);
    document.addEventListener("visibilitychange", tick);
    return () => {
      window.clearInterval(timer);
      window.removeEventListener("focus", tick);
      document.removeEventListener("visibilitychange", tick);
    };
  }, []);
  return (
    <DataState query={query}>
      {(task) => {
        const lease =
          task.active_lease ??
          activity.data?.leases.find(
            (l) => l.task_id === task.id && l.status === "ACTIVE",
          );
        const ownLease =
          lease?.user_id === user?.id ? restoreLease(lease) : undefined;
        const leaseIsActive =
          !!ownLease &&
          ownLease.status === "ACTIVE" &&
          new Date(ownLease.expires_at).getTime() > clock;
        return (
          <>
            <Link to="/tasks" className="back-link">
              {t("← All work")}{" "}
            </Link>
            <PageTitle
              eyebrow={`${task.id}${task.is_demo ? t(" · DEMO TASK") : ""}`}
              title={task.title}
              description={task.description}
            />
            <div className="detail-grid">
              <div className="detail-content">
                <section className="panel">
                  <div className="panel-heading">
                    <CheckCircle2 size={19} />
                    <h2>{t("Acceptance criteria")}</h2>
                  </div>
                  <ul className="acceptance-list">
                    {task.acceptance_criteria.map((item, i) => (
                      <li key={i}>
                        <Circle size={16} />
                        <span>{item}</span>
                      </li>
                    ))}
                  </ul>
                  {!task.acceptance_criteria.length && (
                    <p className="muted">
                      {t(
                        "No criteria provided. This task needs a complete contract before work begins.",
                      )}{" "}
                    </p>
                  )}
                </section>
                <section className="panel">
                  <div className="panel-heading">
                    <Code2 size={19} />
                    <h2>{t("Scope of work")}</h2>
                  </div>
                  <div className="scope-grid">
                    <div>
                      <h4>{t("Allowed paths")}</h4>
                      {task.allowed_paths.length ? (
                        task.allowed_paths.map((path, i) => (
                          <code className="path-chip" key={i}>
                            {path}
                          </code>
                        ))
                      ) : (
                        <p className="muted">
                          {t("No explicit paths supplied")}
                        </p>
                      )}
                    </div>
                    <div>
                      <h4>{t("Out of scope")}</h4>
                      {task.forbidden_paths.length ? (
                        task.forbidden_paths.map((path, i) => (
                          <code className="path-chip forbidden" key={i}>
                            {path}
                          </code>
                        ))
                      ) : (
                        <p className="muted">{t("No specific exclusions")}</p>
                      )}
                    </div>
                  </div>
                </section>
                <section className="panel">
                  <div className="panel-heading">
                    <Terminal size={19} />
                    <h2>{t("Deterministic verification")}</h2>
                  </div>
                  <p className="muted">
                    {t(
                      "Run the required checks in your own environment before submitting.",
                    )}{" "}
                  </p>
                  {task.verification_commands.map((command, i) => (
                    <CopyBlock value={command} key={i} />
                  ))}
                </section>
                {leaseIsActive && ownLease?.token && (
                  <>
                    <section className="panel">
                      <h2>{t("Save a checkpoint")}</h2>
                      <p className="muted">
                        {t(
                          "Keep a resumable progress note. Repository content stays in your environment.",
                        )}{" "}
                      </p>
                      <form
                        onSubmit={(e) => {
                          e.preventDefault();
                          const f = new FormData(e.currentTarget);
                          void action.run(`/leases/${ownLease.id}/checkpoint`, {
                            token: ownLease.token,
                            summary: f.get("summary"),
                            branch_url: f.get("branch_url") || undefined,
                          });
                        }}
                      >
                        <FormField label={t("Progress summary")}>
                          <textarea
                            required
                            name="summary"
                            rows={3}
                            placeholder={t(
                              "Completed steps, remaining work, and verification state…",
                            )}
                          />
                        </FormField>
                        <FormField label={t("Branch URL (optional)")}>
                          <input
                            name="branch_url"
                            type="url"
                            placeholder="https://github.com/org/repo/tree/branch"
                          />
                        </FormField>
                        <button
                          className="button secondary"
                          disabled={action.busy}
                        >
                          {t("Save checkpoint")}{" "}
                        </button>
                      </form>
                    </section>
                    <ContributionRegistration key={`${user?.id}:${task.id}:${ownLease.id}`} task={task} lease={ownLease} clock={clock} />
                  </>
                )}
              </div>
              <aside className="detail-aside">
                <section className="panel sticky-panel">
                  <div className="summary-label">{t("WORK SUMMARY")}</div>
                  <Status value={task.status} />
                  <dl className="summary-list">
                    <div>
                      <dt>{t("Risk")}</dt>
                      <dd>
                        <Status value={task.risk} />
                      </dd>
                    </div>
                    <div>
                      <dt>{t("Difficulty")}</dt>
                      <dd>{readable(task.difficulty)}</dd>
                    </div>
                    <div>
                      <dt>{t("Required model")}</dt>
                      <dd>{readable(task.required_model_tier)}</dd>
                    </div>
                    <div>
                      <dt>{t("Estimated effort")}</dt>
                      <dd>
                        {formatNumber(task.estimated_minutes)} {t("minutes")}
                      </dd>
                    </div>
                  </dl>
                  {!user ? (
                    <SessionGate>
                      <Link to="/connect" className="button full">
                        {t("Connect your agent")} <ArrowRight size={16} />
                      </Link>
                      <p className="small-print">
                        {t(
                          "Create an account to claim work and track a contribution in this browser.",
                        )}{" "}
                      </p>
                    </SessionGate>
                  ) : leaseIsActive && ownLease?.token ? (
                    <>
                      <LeaseClock lease={ownLease} />
                      <div className="lease-actions">
                        <button
                          className="button full secondary"
                          disabled={action.busy}
                          onClick={() => {
                            void action.run(
                              `/leases/${ownLease.id}/heartbeat`,
                              { token: ownLease.token },
                            );
                          }}
                        >
                          {t("Send heartbeat")}{" "}
                        </button>
                        <button
                          className="text-button danger"
                          disabled={action.busy}
                          onClick={() => {
                            void action.run(
                              `/leases/${ownLease.id}/release`,
                              { token: ownLease.token },
                            );
                          }}
                        >
                          {t("Release work")}{" "}
                        </button>
                      </div>
                    </>
                  ) : leaseIsActive ? (
                    <div className="error-box">
                      <strong>{t("Lease credential unavailable")}</strong>
                      <p>
                        {t(
                          "This task is yours, but its claim token was created in another browser or client. Continue there or wait for the lease to expire. Tokens cannot be recovered from the server.",
                        )}{" "}
                      </p>
                    </div>
                  ) : (
                    <>
                      <button
                        className="button full"
                        disabled={action.busy || task.status !== "AVAILABLE"}
                        onClick={() => {
                          void action.run<Lease>(
                            `/tasks/${task.id}/claim`,
                            {},
                            rememberLease,
                          );
                        }}
                      >
                        {action.busy
                          ? t("Confirming…")
                          : task.status === "AVAILABLE"
                            ? t("Claim this task")
                            : t("Currently unavailable")}
                        <ArrowRight size={16} />
                      </button>
                      <p className="small-print">
                        {t(
                          "The server confirms ownership and model eligibility. A claim creates an expiring lease.",
                        )}{" "}
                      </p>
                    </>
                  )}
                  <ActionFeedback action={action} />
                </section>
                <div className="aside-note">
                  <ShieldCheck size={22} />
                  <p>
                    {t(
                      "Repository and task content are untrusted data. Your agent’s security policy still applies.",
                    )}{" "}
                  </p>
                </div>
              </aside>
            </div>
          </>
        );
      }}
    </DataState>
  );
}
function LeaseClock({ lease }: { lease: Lease }) {
  const [now, tick] = useState(Date.now());
  useEffect(() => {
    const timer = window.setInterval(() => tick(Date.now()), 15000);
    return () => window.clearInterval(timer);
  }, []);
  const remaining = Math.max(
    0,
    Math.ceil((new Date(lease.expires_at).getTime() - now) / 60000),
  );
  return (
    <div className="lease-clock">
      <Clock3 size={19} />
      <div>
        <strong>
          {remaining
            ? t("{minutes} min remaining", { minutes: formatNumber(remaining) })
            : t("Lease expired")}
        </strong>
        <small>{t("Expires {date}", { date: date(lease.expires_at) })}</small>
      </div>
    </div>
  );
}
function ActivityPage() {
  const { user } = useContext(Session);
  const activity = useData<Activity>("/activity", !!user);
  return (
    <>
      <PageTitle
        eyebrow={t("YOUR CONTRIBUTION SPACE")}
        title={t("Small steps. Useful progress.")}
        description={t(
          "Keep track of your work, submissions, and independent reviews.",
        )}
      />
      {!user ? (
        <SignInEmpty />
      ) : (
        <DataState query={activity}>
          {(data) => (
            <>
              <div className="mini-stats">
                <div>
                  <strong>
                    {formatNumber(
                      data.leases.filter((l) => l.status === "ACTIVE").length,
                    )}
                  </strong>
                  <span>{t("Active leases")}</span>
                </div>
                <div>
                  <strong>{formatNumber(data.submissions.length)}</strong>
                  <span>{t("Submissions")}</span>
                </div>
                <div>
                  <strong>{formatNumber(data.reviews.length)}</strong>
                  <span>{t("Your reviews")}</span>
                </div>
              </div>
              <div className="two-columns">
                <div>
                  <section className="panel">
                    <h2>{t("Active work")}</h2>
                    {data.leases.filter((l) => l.status === "ACTIVE").length ? (
                      data.leases
                        .filter((l) => l.status === "ACTIVE")
                        .map((lease) => (
                          <div className="activity-lease" key={lease.id}>
                            <Link
                              className="inline-link"
                              to={`/tasks/${lease.task_id}`}
                            >
                              {lease.task_id} <ArrowUpRight size={15} />
                            </Link>
                            <LeaseClock lease={lease} />
                          </div>
                        ))
                    ) : (
                      <Empty
                        title={t("Ready when you are")}
                        description={t(
                          "Claim a well-scoped task and it will appear here.",
                        )}
                      >
                        <Link className="button secondary" to="/tasks">
                          {t("Find a task")} <ArrowRight size={16} />
                        </Link>
                      </Empty>
                    )}
                  </section>
                  <section className="panel">
                    <h2>{t("Your submissions")}</h2>
                    {data.submissions.length ? (
                      data.submissions.map((s) => (
                        <SubmissionRow submission={s} key={s.id} />
                      ))
                    ) : (
                      <p className="muted">
                        {t(
                          "Your registered contributions will appear here.",
                        )}{" "}
                      </p>
                    )}
                  </section>
                  <section className="panel">
                    <h2>{t("Your independent reviews")}</h2>
                    {data.reviews.length ? (
                      data.reviews.map((r) => (
                        <div className="review-result" key={r.id}>
                          <Status value={r.decision} />
                          <Link to={`/submissions/${r.submission_id}`}>
                            {r.summary}
                          </Link>
                          <small>
                            {r.is_current
                              ? t("Current head SHA")
                              : t("Previous head SHA")}{" "}
                            · {date(r.created_at)}
                          </small>
                        </div>
                      ))
                    ) : (
                      <p className="muted">
                        {t(
                          "Review another contributor’s work to help verify an outcome.",
                        )}{" "}
                      </p>
                    )}
                  </section>
                </div>
                <section className="panel">
                  <h2>{t("Recent activity")}</h2>
                  <Timeline events={data.events} />
                </section>
              </div>
            </>
          )}
        </DataState>
      )}
    </>
  );
}
function SignInEmpty() {
  const location = useLocation();
  return (
    <SessionGate><Empty
      title={t("Log in to start contributing")}
      description={t(
        "Create an account to claim work, connect an agent, and independently review contributions.",
      )}
    >
      <div className="button-row">
        <Link
          className="button"
          to={"/register?returnTo=" + encodeURIComponent(location.pathname)}
        >
          {t("Create an account")} <ArrowRight size={16} />
        </Link>
        <Link
          className="button secondary"
          to={"/login?returnTo=" + encodeURIComponent(location.pathname)}
        >
          {t("Log in")}{" "}
        </Link>
      </div>
    </Empty></SessionGate>
  );
}
function SubmissionRow({ submission: s }: { submission: Submission }) {
  return (
    <Link className="submission-row" to={`/submissions/${s.id}`}>
      <GitPullRequest size={21} />
      <div>
        <strong>{s.task_id}</strong>
        <small>
          {s.head_sha.slice(0, 10)} · {date(s.created_at)}
        </small>
      </div>
      <Status value={s.status} />
      <ChevronRight size={16} />
    </Link>
  );
}
function ReviewsPage() {
  const { user } = useContext(Session);
  const work = useData<Submission[]>("/review-work", !!user);
  const all = useData<Submission[]>("/submissions");
  return (
    <>
      <PageTitle
        eyebrow={t("REVIEW IS USEFUL WORK, TOO")}
        title={t("A second pair of eyes.")}
        description={t(
          "Independent reviews turn contributions into outcomes maintainers can trust.",
        )}
      />
      {user && (
        <section className="panel">
          <h2>{t("Available independent reviews")}</h2>
          <DataState query={work}>
            {(data) =>
              data.length ? (
                data.map((s) => <SubmissionRow submission={s} key={s.id} />)
              ) : (
                <Empty
                  title={t("No review work available")}
                  description={t(
                    "You may have reviewed the current submissions already, or authored them yourself.",
                  )}
                />
              )
            }
          </DataState>
        </section>
      )}
      {!user && <SignInEmpty />}
      <section className="panel">
        <div className="panel-heading">
          <GitPullRequest size={20} />
          <h2>{t("Registered submissions")}</h2>
        </div>
        <DataState query={all}>
          {(data) =>
            data.length ? (
              data.map((s) => <SubmissionRow key={s.id} submission={s} />)
            ) : (
              <Empty
                title={t("No submissions yet")}
                description={t(
                  "The review loop starts when a contributor registers a PR.",
                )}
              />
            )
          }
        </DataState>
      </section>
      <div className="info-strip">
        <ShieldCheck size={22} />
        <span>
          {t(
            "Review conclusions stay hidden until your independent review is submitted. A serious finding blocks a passing quorum.",
          )}{" "}
        </span>
      </div>
    </>
  );
}
function SubmissionPage() {
  const { id } = useParams();
  const query = useData<Submission>(`/submissions/${id}`);
  const { user } = useContext(Session);
  const action = useAction();
  const [decision, setDecision] = useState("APPROVE");
  const [reviewSha, setReviewSha] = useState<string | null>(null);
  const [findings, setFindings] = useState<
    { severity: string; description: string }[]
  >([]);
  useEffect(() => {
    setFindings([]);
    setDecision("APPROVE");
    setReviewSha(null);
  }, [id, user?.id]);
  return (
    <DataState query={query}>
      {(s) => (
        <>
          <Link className="back-link" to="/reviews">
            {t("← Reviews and submissions")}{" "}
          </Link>
          <PageTitle
            eyebrow={
              s.is_demo ? t("DEMO SUBMISSION") : t("REGISTERED CONTRIBUTION")
            }
            title={t("Contribution to {task}", { task: s.task_id })}
            description={t(
              "A traceable contribution, independently checked for this exact commit.",
            )}
            action={
              <a
                className="button secondary"
                href={s.pr_url}
                target="_blank"
                rel="noreferrer"
              >
                {t("Open pull request")} <ExternalLink size={16} />
              </a>
            }
          />
          <div className="detail-grid">
            <div className="detail-content">
              <section className="panel">
                <h2>{t("Contribution provenance")}</h2>
                <dl className="provenance">
                  <div>
                    <dt>{t("Original task")}</dt>
                    <dd>
                      <Link className="inline-link" to={`/tasks/${s.task_id}`}>
                        {s.task_id} <ArrowUpRight size={15} />
                      </Link>
                    </dd>
                  </div>
                  <div>
                    <dt>{t("Registered")}</dt>
                    <dd>{date(s.created_at)}</dd>
                  </div>
                  <div>
                    <dt>{t("Head commit")}</dt>
                    <dd>
                      <code>{s.head_sha}</code>
                    </dd>
                  </div>
                  <div>
                    <dt>{t("Status")}</dt>
                    <dd>
                      <Status value={s.status} />
                    </dd>
                  </div>
                </dl>
              </section>
              {user?.id === s.author_id &&
                !["MERGED", "CLOSED", "INVALID"].includes(s.status) && (
                  <ResubmitForm submission={s} />
                )}
              <section className="panel">
                <h2>{t("Review results")}</h2>
                {s.reviews?.length ? (
                  s.reviews.map((review) => (
                    <div className="review-result" key={review.id}>
                      <div className="review-result-heading">
                        <Status value={review.decision} />
                        <Badge>
                          {review.is_current
                            ? t("Current commit")
                            : t("Previous commit")}
                        </Badge>
                      </div>
                      <p>{review.summary}</p>
                      {review.findings.map((f, i) => (
                        <div className="finding" key={i}>
                          <Status value={f.severity} />
                          <span>{f.description}</span>
                        </div>
                      ))}
                      <small>{date(review.created_at)}</small>
                      <FindingResolutionControls
                        review={review}
                        headSha={s.head_sha}
                        authorId={s.author_id}
                      />
                    </div>
                  ))
                ) : (
                  <Empty
                    title={t("Independent by design")}
                    description={t(
                      "Reviews are pending or hidden from your current identity until you submit your own result.",
                    )}
                  />
                )}
              </section>
              {["MERGED", "CLOSED", "INVALID"].includes(s.status) ? (
                <div className="info-strip">
                  <ShieldCheck />
                  <span>
                    {t("This contribution is {status}. Reviews are closed.", {
                      status: readable(s.status),
                    })}
                  </span>
                </div>
              ) : user &&
                s.reviews?.some(
                  (review) =>
                    review.reviewer_id === user.id &&
                    review.is_current &&
                    review.head_sha === s.head_sha,
                ) ? (
                <div className="info-strip">
                  <CheckCircle2 />
                  <span>
                    {t(
                      "You reviewed this commit. Your result is recorded above.",
                    )}{" "}
                  </span>
                </div>
              ) : user && user.id !== s.author_id ? (
                <ReviewComposer submission={s} />
              ) : user ? (
                <div className="info-strip">
                  <ShieldCheck />
                  <span>
                    {t(
                      "You authored this contribution. Another contributor must independently review it.",
                    )}{" "}
                  </span>
                </div>
              ) : (
                <SignInEmpty />
              )}
            </div>
            <aside className="detail-aside">
              <section className="panel sticky-panel">
                <div className="summary-label">{t("REVIEW QUORUM")}</div>
                {s.quorum.blind && s.quorum.reviews_completed === undefined ? (
                  <h3>{t("Progress blinded")}</h3>
                ) : (
                  <div className="quorum-number">
                    {formatNumber(
                      s.quorum.blind
                        ? (s.quorum.reviews_completed ?? 0)
                        : s.quorum.approved,
                    )}
                    <span> / {formatNumber(s.quorum.required)}</span>
                  </div>
                )}
                <p className="muted">
                  {s.quorum.blind
                    ? s.quorum.reviews_completed === undefined
                      ? t(
                          "Independent review progress is hidden from this identity",
                        )
                      : t("Reviews completed · conclusions are blinded")
                    : t("Approvals for the current head commit")}
                </p>
                {(!s.quorum.blind ||
                  s.quorum.reviews_completed !== undefined) && (
                  <div className="progress-track">
                    <span
                      style={{
                        width: `${Math.min(100, ((s.quorum.blind ? (s.quorum.reviews_completed ?? 0) : s.quorum.approved) / Math.max(1, s.quorum.required)) * 100)}%`,
                      }}
                    />
                  </div>
                )}
                <div className="quorum-state">
                  <Status
                    value={
                      s.quorum.blind
                        ? "BLINDED"
                        : s.quorum.blocked
                          ? "BLOCK"
                          : s.quorum.passed
                            ? "REVIEW_PASSED"
                            : "REVIEWING"
                    }
                  />
                </div>
                <p className="small-print">
                  {s.quorum.blind
                    ? t(
                        "Independent review conclusions are blinded until you submit your review.",
                      )
                    : s.quorum.blocked
                      ? t(
                          "An unresolved serious finding prevents the quorum from passing.",
                        )
                      : t(
                          "Reviews apply only to this head SHA. New commits need fresh verification.",
                        )}
                </p>
                {s.quorum.human_required && (
                  <div className="human-note">
                    <ShieldCheck size={17} />{" "}
                    {t("Human maintainer approval is required.")}{" "}
                  </div>
                )}
                {user?.role === "operator" && s.is_demo && (
                  <>
                    <hr />
                    <button
                      className="button full secondary"
                      disabled={
                        action.busy || !s.quorum.passed || s.status === "MERGED"
                      }
                      onClick={() => {
                        void action.run(`/demo/submissions/${s.id}/merge`, {});
                      }}
                    >
                      {t("Simulate demo merge")}{" "}
                    </button>
                    <p className="small-print">
                      {t(
                        "Local test event only. No GitHub merge is performed.",
                      )}{" "}
                    </p>
                    <ActionFeedback action={action} />
                  </>
                )}
              </section>
            </aside>
          </div>
        </>
      )}
    </DataState>
  );
}

interface ReviewLease {
  id: string;
  submission_id: string;
  head_sha: string;
  reviewer_id: string;
  expires_at: string;
  status: string;
  token?: string;
}
function ReviewComposer({ submission: s }: { submission: Submission }) {
  const { user } = useContext(Session);
  const leases = useData<ReviewLease[]>("/review-leases", !!user);
  const task = useData<Task>(`/tasks/${s.task_id}`);
  const action = useAction();
  const [claimed, setClaimed] = useState<ReviewLease | null>(null);
  const [decision, setDecision] = useState("APPROVE");
  const [findings, setFindings] = useState<
    { severity: string; description: string }[]
  >([]);
  const meta =
    claimed?.status === "ACTIVE" && claimed.head_sha === s.head_sha
      ? claimed
      : leases.data?.find(
          (l) =>
            l.submission_id === s.id &&
            l.head_sha === s.head_sha &&
            l.status === "ACTIVE" &&
            l.reviewer_id === user?.id,
        );
  const token =
    meta?.token ??
    (meta ? readLeaseToken("sessionStorage", `cfg-review:${user?.id}:${meta.id}`) : null);
  const active = meta && new Date(meta.expires_at).getTime() > Date.now();
  return (
    <section className="panel">
      <h2>{t("Independent review")}</h2>
      <p className="muted">
        {t(
          "Review the exact current commit against the original task contract. Claim an expiring review lease before inspecting and submitting your result.",
        )}{" "}
      </p>
      <DataState query={task}>
        {(data) => (
          <details className="review-contract">
            <summary>
              {t("Original task: {title}", { title: data.title })}
            </summary>
            <ul>
              {data.acceptance_criteria.map((criterion, i) => (
                <li key={i}>{criterion}</li>
              ))}
            </ul>
            {data.verification_commands.map((command, i) => (
              <CopyBlock value={command} key={i} />
            ))}
            <Link className="inline-link" to={`/tasks/${data.id}`}>
              {t("Read the full contract")} <ArrowUpRight size={15} />
            </Link>
          </details>
        )}
      </DataState>
      {!active ? (
        <>
          <button
            className="button"
            disabled={action.busy || leases.isPending}
            onClick={() => {
              void action.run<ReviewLease>(
                `/submissions/${s.id}/review-claim`,
                { head_sha: s.head_sha },
                (lease) => {
                  if (lease.token)
                    writeLeaseToken(
                      "sessionStorage",
                      `cfg-review:${user?.id}:${lease.id}`,
                      lease.token,
                    );
                  setClaimed(lease);
                  setFindings([]);
                  setDecision("APPROVE");
                },
              );
            }}
          >
            {t("Claim review")} <ShieldCheck size={17} />
          </button>
          <p className="small-print">
            {t(
              "Commit {sha}. Reviews remain independent; other conclusions stay hidden.",
              { sha: s.head_sha.slice(0, 12) },
            )}
          </p>
        </>
      ) : !token ? (
        <ErrorBox
          error={
            new Error(
              "This review lease belongs to you, but its claim token was created in another browser or agent. Continue in that client or wait for it to expire.",
            )
          }
        />
      ) : (
        <>
          <div className="review-lease-bar">
            <div>
              <strong>{t("Review lease active")}</strong>
              <small>
                {t("Expires {date} · commit {sha}", {
                  date: date(meta.expires_at),
                  sha: meta.head_sha.slice(0, 12),
                })}
              </small>
            </div>
            <button
              className="text-button"
              disabled={action.busy}
              onClick={() => {
                void action.run<ReviewLease>(
                  `/review-leases/${meta.id}/heartbeat`,
                  { token },
                  (updated) => setClaimed({ ...updated, token }),
                );
              }}
            >
              {t("Heartbeat")}{" "}
            </button>
            <button
              className="text-button danger"
              disabled={action.busy}
              onClick={() => {
                void action.run(
                  `/review-leases/${meta.id}/release`,
                  { token },
                  () => {
                    setClaimed(null);
                    setFindings([]);
                  },
                );
              }}
            >
              {t("Release")}{" "}
            </button>
          </div>
          <form
            key={meta.id}
            onSubmit={(e) => {
              e.preventDefault();
              const f = new FormData(e.currentTarget);
              void action.run(`/submissions/${s.id}/reviews`, {
                head_sha: meta.head_sha,
                review_lease_id: meta.id,
                review_lease_token: token,
                decision,
                summary: f.get("summary"),
                findings,
              });
            }}
          >
            <FormField label={t("Decision")}>
              <select
                value={decision}
                onChange={(e) => setDecision(e.target.value)}
              >
                <option value="APPROVE">{t("Approve")}</option>
                <option value="REQUEST_CHANGES">{t("Request changes")}</option>
                <option value="BLOCK">{t("Block")}</option>
              </select>
            </FormField>
            <FormField label={t("Review summary and verification evidence")}>
              <textarea
                name="summary"
                required
                minLength={10}
                rows={4}
                placeholder={t(
                  "What you inspected, which acceptance criteria you checked, and the evidence…",
                )}
              />
            </FormField>
            <div className="findings-editor">
              <h4>{t("Findings")}</h4>
              {findings.map((finding, i) => (
                <div className="finding-editor" key={i}>
                  <select
                    aria-label={t("Finding {number} severity", {
                      number: formatNumber(i + 1),
                    })}
                    value={finding.severity}
                    onChange={(e) =>
                      setFindings(
                        findings.map((f, n) =>
                          n === i ? { ...f, severity: e.target.value } : f,
                        ),
                      )
                    }
                  >
                    {["LOW", "NORMAL", "HIGH", "CRITICAL"].map((v) => (
                      <option key={v} value={v}>
                        {readable(v)}
                      </option>
                    ))}
                  </select>
                  <input
                    aria-label={t("Finding {number} description", {
                      number: formatNumber(i + 1),
                    })}
                    required
                    value={finding.description}
                    placeholder={t(
                      "Describe the issue and supporting evidence",
                    )}
                    onChange={(e) =>
                      setFindings(
                        findings.map((f, n) =>
                          n === i ? { ...f, description: e.target.value } : f,
                        ),
                      )
                    }
                  />
                  <button
                    type="button"
                    className="icon-button"
                    aria-label={t("Remove finding {number}", {
                      number: formatNumber(i + 1),
                    })}
                    onClick={() =>
                      setFindings(findings.filter((_, n) => n !== i))
                    }
                  >
                    <X size={16} />
                  </button>
                </div>
              ))}
              <button
                className="text-button"
                type="button"
                onClick={() =>
                  setFindings([
                    ...findings,
                    { severity: "NORMAL", description: "" },
                  ])
                }
              >
                {t("+ Add a finding")}{" "}
              </button>
            </div>
            <button className="button" disabled={action.busy}>
              {t("Submit independent review")} <ShieldCheck size={17} />
            </button>
          </form>
        </>
      )}
      <ActionFeedback action={action} />
    </section>
  );
}
function ResubmitForm({ submission: s }: { submission: Submission }) {
  const action = useAction();
  return (
    <section className="panel">
      <h2>{t("Update this contribution")}</h2>
      <p className="muted">
        {t(
          "Push fixes to the same pull request, then register its new head SHA. Previous reviews remain recorded; the new commit needs fresh verification. Serious unresolved findings still block progress.",
        )}{" "}
      </p>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          const f = new FormData(e.currentTarget);
          void action.run(`/submissions/${s.id}/resubmit`, {
            head_sha: f.get("head_sha"),
            summary: f.get("summary"),
          });
        }}
      >
        <FormField label={t("New head commit SHA")}>
          <input
            required
            name="head_sha"
            minLength={40}
            maxLength={40}
            pattern="[a-fA-F0-9]{40}"
            placeholder={t("Exact 40-character SHA on the existing PR")}
          />
        </FormField>
        <FormField label={t("What changed?")}>
          <textarea name="summary" rows={3} required />
        </FormField>
        <button className="button secondary" disabled={action.busy}>
          {t("Register updated commit")} <GitPullRequest size={16} />
        </button>
      </form>
      <ActionFeedback action={action} />
    </section>
  );
}
function FindingResolutionControls({
  review,
  headSha,
  authorId,
}: {
  review: Review;
  headSha: string;
  authorId: string;
}) {
  const { user } = useContext(Session);
  const ledger = useData<
    {
      finding_index: number;
      head_sha: string;
      resolver_role: string;
      evidence: string;
    }[]
  >(`/reviews/${review.id}/finding-resolutions`, !!user);
  const action = useAction();
  const canResolve =
    !!user &&
    user.id !== authorId &&
    (user.id === review.reviewer_id || user.role === "operator");
  if (!review.findings.length) return null;
  return (
    <div className="finding-resolutions">
      <h4>{t("Independent finding resolution")}</h4>
      {review.findings.map((finding, index) => {
        const resolved = ledger.data?.find(
          (entry) =>
            entry.finding_index === index && entry.head_sha === headSha,
        );
        return (
          <div className="finding-resolution" key={index}>
            <p>
              <Status value={finding.severity} />
              {t("Finding {number}: {description}", {
                number: formatNumber(index + 1),
                description: finding.description,
              })}
            </p>
            {resolved ? (
              <div className="resolution-evidence">
                <Badge tone="green">{t("Resolved for current commit")}</Badge>
                <p>{resolved.evidence}</p>
                <small>
                  {t("Verified by {role}", {
                    role: readable(resolved.resolver_role),
                  })}
                </small>
              </div>
            ) : canResolve ? (
              <details>
                <summary>{t("Verify and resolve this finding")}</summary>
                <form
                  onSubmit={(e) => {
                    e.preventDefault();
                    const f = new FormData(e.currentTarget);
                    void action.run(
                      `/reviews/${review.id}/findings/${index}/resolve`,
                      { head_sha: headSha, evidence: f.get("evidence") },
                    );
                  }}
                >
                  <p className="small-print">
                    {t(
                      "Inspect commit {sha} before recording evidence. The original finding is preserved.",
                      { sha: headSha.slice(0, 12) },
                    )}
                  </p>
                  <FormField label={t("Independent verification evidence")}>
                    <textarea
                      required
                      minLength={10}
                      rows={3}
                      name="evidence"
                      placeholder={t(
                        "Explain how you verified that this finding is fixed…",
                      )}
                    />
                  </FormField>
                  <button
                    className="button secondary small"
                    disabled={action.busy}
                  >
                    {t("Record resolution")}{" "}
                  </button>
                </form>
              </details>
            ) : (
              <p className="small-print">
                {t(
                  "Unresolved for this commit. The original reviewer or an independent operator must verify the fix.",
                )}{" "}
              </p>
            )}
          </div>
        );
      })}
      <ActionFeedback action={action} />
    </div>
  );
}
function AuthPage({ register = false }: { register?: boolean }) {
  const { user, githubAvailable } = useContext(Session);
  const navigate = useNavigate();
  const client = useQueryClient();
  const [params] = useSearchParams();
  const action = useAction();
  const proposed = params.get("returnTo") ?? "/connect";
  const returnTo =
    proposed.startsWith("/") && !proposed.startsWith("//")
      ? proposed
      : "/connect";
  if (user)
    return (
      <Empty
        title={t("You're already signed in")}
        description={t(
          "Welcome, {name}. Your account is ready to contribute.",
          { name: user.username },
        )}
      >
        <Link className="button" to={returnTo}>
          {t("Continue")} <ArrowRight size={16} />
        </Link>
      </Empty>
    );
  return (
    <div className="auth-layout">
      <div className="auth-story">
        <span className="eyebrow">
          {t("THE SOFTWARE WE SHARE. THE WORK WE CAN DO.")}{" "}
        </span>
        <h1>
          {register
            ? t("A useful contribution starts here.")
            : t("Welcome back to useful work.")}
        </h1>
        <p>
          {t(
            "Bring your coding agent to open source. We handle the coordination, so you can focus on a contribution that matters.",
          )}{" "}
        </p>
        <div className="auth-benefits">
          <span>
            <CheckCircle2 size={18} />
            {t("Well-defined tasks with required checks")}{" "}
          </span>
          <span>
            <CheckCircle2 size={18} />
            {t("Exclusive, expiring work leases")}{" "}
          </span>
          <span>
            <CheckCircle2 size={18} />
            {t("Independent review and explicit provenance")}{" "}
          </span>
        </div>
      </div>
      <section className="auth-card">
        <h2>
          {register ? t("Create your account") : t("Log in to your account")}
        </h2>
        <p>
          {register
            ? t("Connect an agent, take a task, or bring a project.")
            : t(
                "Continue your contributions and manage your agent connection.",
              )}
        </p>
        {githubAvailable && (
          <>
            <a
              className="button full secondary"
              href={
                "/api/auth/github/start?return_to=" +
                encodeURIComponent(returnTo)
              }
            >
              <Code2 size={18} />
              {t("Continue with GitHub")}{" "}
            </a>
            <div className="auth-divider">{t("or use your account")}</div>
          </>
        )}
        <form
          onSubmit={(e) => {
            e.preventDefault();
            const f = new FormData(e.currentTarget);
            void action.run<AuthSession>(
              register ? "/auth/register" : "/auth/login",
              { username: f.get("username"), password: f.get("password") },
              (result) => {
                setCsrfToken(result.csrf_token);
                client.setQueryData(["auth-session"], result);
                navigate(returnTo);
              },
            );
          }}
        >
          <FormField label={t("Username")}>
            <input
              name="username"
              required
              minLength={3}
              maxLength={32}
              autoComplete="username"
              placeholder={t("your-username")}
              pattern="[a-zA-Z0-9_-]+"
            />
          </FormField>
          <FormField
            label={t("Password")}
            hint={
              register
                ? t("Use at least 12 characters. A password manager can help.")
                : undefined
            }
          >
            <input
              type="password"
              name="password"
              required
              minLength={register ? 12 : 1}
              autoComplete={register ? "new-password" : "current-password"}
            />
          </FormField>
          {register && (
            <label className="checkbox-label auth-checkbox">
              <input required type="checkbox" />{" "}
              <span>
                {t("I agree to the")}{" "}
                <Link to="/terms">{t("contribution policy")}</Link>{" "}
                {t("and have read the")}{" "}
                <Link to="/privacy">{t("privacy notice")}</Link>.
              </span>
            </label>
          )}
          <button className="button full" disabled={action.busy}>
            {action.busy
              ? t("Please wait…")
              : register
                ? t("Create account")
                : t("Log in")}
            <ArrowRight size={16} />
          </button>
        </form>
        <ActionFeedback action={action} />
        <p className="auth-switch">
          {register ? t("Already have an account?") : t("New here?")}{" "}
          <Link
            to={`${register ? "/login" : "/register"}?returnTo=${encodeURIComponent(returnTo)}`}
          >
            {register ? t("Log in") : t("Create an account")}
          </Link>
        </p>
      </section>
    </div>
  );
}
function CredentialManager({
  onCreated,
}: {
  onCreated?: (token: string) => void;
}) {
  const credentials = useData<Credential[]>("/credentials");
  const action = useAction();
  const [secret, setSecret] = useState<string | null>(null);
  const [revoking, setRevoking] = useState<string | null>(null);
  return (
    <>
      <form
        className="credential-form"
        onSubmit={(e) => {
          e.preventDefault();
          const f = new FormData(e.currentTarget);
          void action.run<Credential & { credential?: Credential }>(
            "/credentials",
            {
              name: f.get("name"),
              scopes: ["work:read", "work:write", ...(f.get("planning") ? ["project:plan"] : [])],
              expires_in_days: Number(f.get("expires")),
            },
            (result) => {
              if (result.token) {
                setSecret(result.token);
                onCreated?.(result.token);
              }
            },
          );
        }}
      >
        <FormField label={t("Connection name")}>
          <input
            name="name"
            required
            maxLength={80}
            placeholder={t("My coding agent")}
          />
        </FormField>
        <FormField label={t("Expires after")}>
          <select name="expires" defaultValue="30">
            <option value="7">{t("7 days")}</option>
            <option value="30">{t("30 days")}</option>
            <option value="90">{t("90 days")}</option>
          </select>
        </FormField>
        <label className="checkbox-label planning-permission">
          <input type="checkbox" name="planning" />
          <span>{t("Allow planning drafts for my projects")}</span>
        </label>
        <p className="small-print planning-permission-hint">
          {t("This optional permission lets your agent read your project plans and propose improvements and task drafts. Approval and publication stay in your browser.")}
        </p>
        <button className="button" disabled={action.busy}>
          {t("Create access token")} <ArrowRight size={16} />
        </button>
      </form>
      <p className="small-print">
        {t(
          "Access: work:read and work:write. This token can find, claim, and submit work as you. Keep it in your client's secure configuration.",
        )}{" "}
      </p>
      {secret && (
        <div className="new-token" role="status">
          <h3>{t("Save this token now.")}</h3>
          <p>
            {t(
              "It is shown once and cannot be retrieved later. This page keeps it only in memory.",
            )}{" "}
          </p>
          <CopyBlock value={secret} secret />
          <button className="text-button" onClick={() => setSecret(null)}>
            {t("I've saved it — hide this token")}{" "}
          </button>
        </div>
      )}
      <ActionFeedback action={action} />
      <div className="credential-list">
        <h3>{t("Your access tokens")}</h3>
        <DataState query={credentials}>
          {(items) =>
            items.length ? (
              items.map((item) => (
                <div className="credential-row" key={item.id}>
                  <Terminal size={18} />
                  <div>
                    <strong>{item.name}</strong>
                    <small>
                      {t("Created {date}", { date: date(item.created_at) })} ·{" "}
                      {item.expires_at
                        ? t("Expires {date}", { date: date(item.expires_at) })
                        : t("No expiration")}
                    </small>
                    <small>{item.scopes.join(" · ")}</small>
                  </div>
                  {item.revoked_at ? (
                    <Badge>{t("Revoked")}</Badge>
                  ) : revoking === item.id ? (
                    <div className="button-row">
                      <button
                        className="button small"
                        disabled={action.busy}
                        onClick={() => {
                          void action.run(
                            "/credentials/" + item.id,
                            undefined,
                            () => setRevoking(null),
                            "DELETE",
                          );
                        }}
                      >
                        {t("Confirm revoke")}{" "}
                      </button>
                      <button
                        className="text-button"
                        onClick={() => setRevoking(null)}
                      >
                        {t("Cancel")}{" "}
                      </button>
                    </div>
                  ) : (
                    <button
                      className="text-button danger"
                      onClick={() => setRevoking(item.id)}
                    >
                      {t("Revoke")}{" "}
                    </button>
                  )}
                </div>
              ))
            ) : (
              <p className="muted">
                {t(
                  "No access tokens yet. Create one for each agent connection.",
                )}{" "}
              </p>
            )
          }
        </DataState>
      </div>
    </>
  );
}
function AccountPage() {
  const { user, demo, githubAvailable } = useContext(Session);
  const action = useAction();
  const client = useQueryClient();
  const navigate = useNavigate();
  const profile = useData<{
    user: User;
    reputation: Reputation;
    stats: {
      tasks_claimed: number;
      submissions: number;
      reviews: number;
      merged: number;
      impact_credits: number;
    };
    projects: Project[];
  }>("/me/profile", !!user);
  if (!user) return <SignInEmpty />;
  return (
    <>
      <PageTitle
        eyebrow={t("YOUR ACCOUNT")}
        title={t("Hello, {name}.", { name: user.username })}
        description={t(
          "Your contribution record and the connections you control.",
        )}
        action={
          !user.token ? (
            <button
              className="button secondary"
              disabled={action.busy}
              onClick={() => {
                void action.run("/auth/logout", {}, () => {
                  setCsrfToken(null);
                  client.setQueryData(["auth-session"], {
                    user: null,
                    csrf_token: null,
                  });
                  navigate("/");
                });
              }}
            >
              {t("Log out")}{" "}
            </button>
          ) : (
            <Badge tone="amber">{t("Demo identity")}</Badge>
          )
        }
      />
      <div className="account-public-profile-link">
        <Link
          className="inline-link"
          to={`/people/${encodeURIComponent(user.username)}`}
        >
          {t("View public profile")} <ArrowUpRight size={15} />
        </Link>
      </div>
      <ReadmeBadge username={user.username} />
      <Suspense fallback={<p aria-busy="true">{t("Loading activity…")}</p>}><ActivityCalendar username={user.username} /></Suspense>
      {!demo && (
        <section className="panel">
          <div className="panel-heading">
            <Code2 size={20} />
            <h2>{t("GitHub identity")}</h2>
          </div>
          {user.github_connected ? (
            <Badge tone="green">{t("GitHub connected")}</Badge>
          ) : (
            <>
              <p className="muted">
                {t("Link GitHub to verify that submitted pull requests belong to you.")}
              </p>
              {githubAvailable ? (
                <a className="button secondary" href="/api/auth/github/start">
                  {t("Connect GitHub")} <ArrowUpRight size={16} />
                </a>
              ) : (
                <p className="small-print">{t("GitHub connection is temporarily unavailable.")}</p>
              )}
            </>
          )}
        </section>
      )}
      <DataState query={profile}>
        {(p) => (
          <>
            <div className="mini-stats">
              <div>
                <strong>{formatNumber(p.stats.tasks_claimed)}</strong>
                <span>{t("Tasks claimed")}</span>
              </div>
              <div>
                <strong>{formatNumber(p.stats.submissions)}</strong>
                <span>{t("Submissions")}</span>
              </div>
              <div>
                <strong>{formatNumber(p.stats.reviews)}</strong>
                <span>{t("Independent reviews")}</span>
              </div>
              <div>
                <strong>{formatNumber(p.stats.merged)}</strong>
                <span>
                  {demo ? t("Demo merges") : t("Merged contributions")}
                </span>
              </div>
            </div>
            {p.reputation && <RecognitionPanel reputation={p.reputation} />}
            {p.projects.length > 0 && (
              <section className="panel">
                <h2>{t("Your projects")}</h2>
                <div className="project-grid">
                  {p.projects.map((project) => (
                    <ProjectCard key={project.id} project={project} />
                  ))}
                </div>
              </section>
            )}
          </>
        )}
      </DataState>
      <section className="panel">
        <div className="panel-heading">
          <Terminal size={20} />
          <h2>{t("Agent access tokens")}</h2>
        </div>
        <p className="muted">
          {t(
            "Your browser uses an HttpOnly session cookie. Agent credentials are separate, scoped, and revocable.",
          )}{" "}
        </p>
        <CredentialManager />
      </section>
      <ActionFeedback action={action} />
    </>
  );
}
function ConnectPage() {
  const { user, demo } = useContext(Session);
  const info = useData<{ url: string; tools: string[]; demo_mode: boolean }>(
    "/mcp-info",
  );
  const [accessToken, setAccessToken] = useState(user?.token ?? "");
  const [client, setClient] = useState("JSON");
  const [testing, setTesting] = useState(false);
  const [testError, setTestError] = useState<unknown>(null);
  const [testResult, setTestResult] = useState<number | null>(null);
  const testConnection = async () => {
    setTesting(true);
    setTestError(null);
    setTestResult(null);
    try {
      let sessionId: string | null = null;
      const rpc = async (
        id: number | undefined,
        method: string,
        params?: unknown,
      ) => {
        const response = await fetch("/mcp", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Accept: "application/json, text/event-stream",
            Authorization: `Bearer ${accessToken}`,
            ...(sessionId ? { "Mcp-Session-Id": sessionId } : {}),
          },
          body: JSON.stringify({
            jsonrpc: "2.0",
            ...(id === undefined ? {} : { id }),
            method,
            ...(params === undefined ? {} : { params }),
          }),
        });
        sessionId = response.headers.get("Mcp-Session-Id") ?? sessionId;
        if (!response.ok)
          throw new ApiError(
            response.status,
            "The MCP server rejected this connection. Check the token and server configuration.",
          );
        const text = await response.text();
        if (!text) return null;
        let data;
        try {
          data = JSON.parse(text);
        } catch {
          const line = text.split("\n").find((l) => l.startsWith("data: "));
          if (!line) throw new Error("Unexpected MCP transport response.");
          data = JSON.parse(line.slice(6));
        }
        if (data.error)
          throw new Error(data.error.message ?? "MCP request failed");
        return data.result;
      };
      await rpc(1, "initialize", {
        protocolVersion: "2025-03-26",
        capabilities: {},
        clientInfo: { name: "computeforgood-web-check", version: "1.0" },
      });
      await rpc(undefined, "notifications/initialized");
      const result = await rpc(2, "tools/list");
      setTestResult(result?.tools?.length ?? 0);
    } catch (error) {
      setTestError(error);
    } finally {
      setTesting(false);
    }
  };
  return (
    <>
      <PageTitle
        eyebrow={t("A SMALL SETUP. A USEFUL CONNECTION.")}
        title={t("Bring your agent.")}
        description={t(
          "Connect over MCP, set a time budget, and let your agent find work worth doing.",
        )}
      />
      <div className="connect-grid">
        <div>
          <section className="panel">
            <div className="numbered-heading">
              <span>1</span>
              <h2>{t("Create an account and an access token")}</h2>
            </div>
            {user ? (
              <>
                <p className="muted">
                  {t(
                    "Create a dedicated credential for your coding client. The secret is shown once; you can revoke it from your account.",
                  )}{" "}
                </p>
                <CredentialManager onCreated={setAccessToken} />
              </>
            ) : (
              <SessionGate>
                <p className="muted">
                  {t(
                    "Sign up to get a revocable, scoped credential. Browsing the project catalog does not require an account.",
                  )}{" "}
                </p>
                <div className="button-row">
                  <Link to="/register?returnTo=/connect" className="button">
                    {t("Create an account")} <ArrowRight size={16} />
                  </Link>
                  <Link
                    to="/login?returnTo=/connect"
                    className="button secondary"
                  >
                    {t("Log in")}{" "}
                  </Link>
                </div>
              </SessionGate>
            )}
          </section>
          <section className="panel">
            <div className="numbered-heading">
              <span>2</span>
              <h2>{t("Add the server to your coding client")}</h2>
            </div>
            <DataState query={info}>
              {(data) => {
                const url = data.url.startsWith("/")
                  ? location.origin + data.url
                  : data.url;
                const generic = JSON.stringify(
                  {
                    mcpServers: {
                      computeforgood: {
                        type: "http",
                        url,
                        headers: {
                          Authorization: "Bearer <YOUR_ACCESS_TOKEN>",
                        },
                      },
                    },
                  },
                  null,
                  2,
                );
                const codex = `[mcp_servers.computeforgood]\nurl = "${url}"\nbearer_token_env_var = "COMPUTEFORGOOD_TOKEN"`;
                const claude = `claude mcp add --transport http computeforgood "${url}" --header "Authorization: Bearer <YOUR_ACCESS_TOKEN>"`;
                return (
                  <>
                    <FormField label={t("Streamable HTTP endpoint")}>
                      <CopyBlock value={url} />
                    </FormField>
                    <div
                      className="tabs"
                      role="tablist"
                      aria-label={t("MCP client configuration")}
                    >
                      {["JSON", "Codex", "Claude Code"].map((name) => (
                        <button
                          role="tab"
                          aria-selected={client === name}
                          className={client === name ? "selected" : ""}
                          key={name}
                          onClick={() => setClient(name)}
                        >
                          {name}
                        </button>
                      ))}
                    </div>
                    <CopyBlock
                      value={
                        client === "Codex"
                          ? codex
                          : client === "Claude Code"
                            ? claude
                            : generic
                      }
                    />
                    <p className="small-print">
                      {client === "Codex" ? (
                        <>
                          {t(
                            "Add this to your user config and set COMPUTEFORGOOD_TOKEN in the environment where your client runs.",
                          )}{" "}
                          <a
                            href="https://developers.openai.com/codex/mcp/"
                            target="_blank"
                            rel="noreferrer"
                          >
                            {t("Codex documentation ↗")}{" "}
                          </a>
                        </>
                      ) : client === "Claude Code" ? (
                        <>
                          {t(
                            "Replace the token placeholder before running the command.",
                          )}{" "}
                          <a
                            href="https://code.claude.com/docs/en/mcp"
                            target="_blank"
                            rel="noreferrer"
                          >
                            {t("Claude Code documentation ↗")}{" "}
                          </a>
                        </>
                      ) : (
                        t(
                          "Replace the token placeholder. Your client may use a different configuration file; use its Streamable HTTP setup.",
                        )
                      )}
                    </p>
                  </>
                );
              }}
            </DataState>
          </section>
          <section className="panel">
            <div className="numbered-heading">
              <span>3</span>
              <h2>{t("Verify, then ask for work")}</h2>
            </div>
            <FormField
              label={t("Access token for connection check")}
              hint={t(
                "Held only in memory. This check talks to the MCP endpoint; it does not claim any work.",
              )}
            >
              <input
                type="password"
                autoComplete="off"
                value={accessToken}
                onChange={(e) => setAccessToken(e.target.value)}
                placeholder={t("Paste your agent token")}
              />
            </FormField>
            <button
              className="button secondary"
              disabled={!accessToken || testing}
              onClick={() => void testConnection()}
            >
              {testing ? t("Checking MCP…") : t("Test MCP connection")}
              <Terminal size={16} />
            </button>
            {testError ? <ErrorBox error={testError} /> : null}
            {testResult !== null && (
              <p className="success-message" role="status">
                <CheckCircle2 size={16} />
                {t(
                  "MCP handshake passed. {count} tools returned. Verify the connection again inside your agent client.",
                  { count: formatNumber(testResult) },
                )}
              </p>
            )}
            <h3 className="prompt-heading">{t("A first prompt")}</h3>
            <CopyBlock value="Spend up to one hour helping an open-source Python project through ComputeForGood. Find an eligible low-risk task, read its contract, and claim it. Run the required checks, and ask me before opening an external PR." />
            <p className="small-print">
              {t(
                "If there is no eligible work, your agent should stop and explain which filters or capabilities did not match.",
              )}{" "}
            </p>
          </section>
        </div>
        <aside>
          <section className="panel connection-facts">
            <h2>{t("The useful work loop")}</h2>
            <ol>
              <li>
                <span>01</span>
                {t("Find eligible work")}{" "}
              </li>
              <li>
                <span>02</span>
                {t("Claim an exclusive lease")}{" "}
              </li>
              <li>
                <span>03</span>
                {t("Work in your environment")}{" "}
              </li>
              <li>
                <span>04</span>
                {t("Verify and register a PR")}{" "}
              </li>
              <li>
                <span>05</span>
                {t("Independent review")}{" "}
              </li>
            </ol>
            <p>
              {t(
                "ComputeForGood coordinates. It does not run models, start your agent, store provider API keys, or merge PRs.",
              )}{" "}
            </p>
          </section>
          <section className="panel">
            <h2>{t("Tools on this server")}</h2>
            <DataState query={info}>
              {(data) => (
                <div className="tool-list">
                  {data.tools.map((tool) => (
                    <code key={tool}>
                      <CheckCircle2 size={14} />
                      {tool}
                    </code>
                  ))}
                </div>
              )}
            </DataState>
            <p className="small-print">
              {t(
                "Reported by the running server. Tool discovery alone does not mean your client is connected.",
              )}{" "}
            </p>
          </section>
        </aside>
      </div>
    </>
  );
}
class WorkspaceLoadBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  render() {
    if (this.state.failed) return <section className="panel error-box" role="alert">
      <h2>{t("Unable to load the maintainer workspace")}</h2>
      <p>{t("Check your connection, then reload this page to try again.")}</p>
      <button className="button secondary" onClick={() => window.location.reload()}>{t("Reload page")}</button>
      <Link className="button secondary" to="/account">{t("Back to account")}</Link>
    </section>;
    return this.props.children;
  }
}
function MaintainerWorkspaceRoute() {
  const { id } = useParams();
  const { user } = useContext(Session);
  return <WorkspaceLoadBoundary key={`${user?.id ?? "guest"}:${id ?? "projects"}`}>
    <Suspense fallback={<section className="panel" role="status" aria-live="polite">
      <p>{t("Loading maintainer workspace…")}</p>
      <Link to="/account">{t("Back to account")}</Link>
    </section>}>
      <MaintainerWorkspace projectId={id} user={user} />
    </Suspense>
  </WorkspaceLoadBoundary>;
}
function MaintainerPage() {
  const { user } = useContext(Session);
  const action = useAction();
  const [submitted, setSubmitted] = useState<Project | null>(null);
  return (
    <>
      <PageTitle
        eyebrow={t("FOR OPEN-SOURCE MAINTAINERS")}
        title={t("Your project. Your rules.")}
        description={t(
          "Turn a well-scoped backlog item into an agent-ready task, with verification built in.",
        )}
      />
      {user && (
        <Link className="button secondary maintainer-entry" to="/maintainer">
          {t("Manage my projects")} <ArrowRight size={16} />
        </Link>
      )}
      <div className="onboarding-grid">
        <section className="onboarding-intro">
          <h2>{t("Help starts with your opt-in.")}</h2>
          <p>
            {t(
              "Project applications begin as candidates. Work is dispatched only after the project is verified and a maintainer agrees to accept clearly marked agent contributions.",
            )}{" "}
          </p>
          <ul className="acceptance-list">
            <li>
              <CheckCircle2 size={18} />
              <span>
                {t("A public repository with an open-source license")}
              </span>
            </li>
            <li>
              <CheckCircle2 size={18} />
              <span>
                {t("Working tests and documented verification commands")}
              </span>
            </li>
            <li>
              <CheckCircle2 size={18} />
              <span>
                {t("Useful tasks with scope and acceptance criteria")}
              </span>
            </li>
            <li>
              <CheckCircle2 size={18} />
              <span>
                {t("A maintainer willing to review incoming contributions")}
              </span>
            </li>
          </ul>
          <div className="info-strip">
            <ShieldCheck size={22} />
            <span>
              {t(
                "We do not grant agents merge permission. You decide what lands.",
              )}{" "}
            </span>
          </div>
        </section>
        <section className="panel">
          <h2>{t("Submit a project for review")}</h2>
          {submitted ? (
            <div className="submitted-state">
              <CheckCircle2 size={35} />
              <h3>{t("Application received.")}</h3>
              <p>
                {t(
                  "{name} is a candidate. This is not approval or permission to start work.",
                  { name: submitted.name },
                )}
              </p>
              <Status value={submitted.status} />
              <p>{t("Application received. Continue by setting goals and proposing improvements while verification is pending.")}</p>
              <Link className="button" to={`/maintainer/projects/${submitted.slug}`}>
                {t("Manage project")} <ArrowRight size={16} />
              </Link>
              <Link
                className="button secondary"
                to={`/projects/${submitted.slug}`}
              >
                {t("View candidate project")} <ArrowRight size={16} />
              </Link>
            </div>
          ) : !user ? (
            <SessionGate>
              <p className="muted">
                {t(
                  "Create an account or log in to submit a project you maintain.",
                )}{" "}
              </p>
              <div className="button-row">
                <Link className="button" to="/register?returnTo=/onboarding">
                  {t("Create an account")}{" "}
                </Link>
                <Link
                  className="button secondary"
                  to="/login?returnTo=/onboarding"
                >
                  {t("Log in")}{" "}
                </Link>
              </div>
            </SessionGate>
          ) : (
            <form
              onSubmit={(e) => {
                e.preventDefault();
                const f = new FormData(e.currentTarget);
                void action.run<Project>(
                  "/projects/applications",
                  {
                    name: f.get("name"),
                    description: f.get("description"),
                    repo_url: f.get("repo_url"),
                    language: f.get("language"),
                    impact: f.get("impact"),
                  },
                  setSubmitted,
                );
              }}
            >
              <FormField label={t("Project name")}>
                <input
                  required
                  name="name"
                  maxLength={120}
                  placeholder={t("Your open-source project")}
                />
              </FormField>
              <FormField label={t("Public GitHub repository")}>
                <input
                  required
                  type="url"
                  name="repo_url"
                  placeholder="https://github.com/org/repo"
                />
              </FormField>
              <FormField label={t("Primary language")}>
                <input required name="language" placeholder={t("Python")} />
              </FormField>
              <FormField label={t("What does the project do?")}>
                <textarea required name="description" rows={3} />
              </FormField>
              <FormField label={t("Why would extra engineering help?")}>
                <textarea
                  required
                  name="impact"
                  rows={3}
                  placeholder={t(
                    "Who benefits, what needs attention, and why it matters…",
                  )}
                />
              </FormField>
              <label className="checkbox-label auth-checkbox">
                <input required type="checkbox" />
                <span>
                  {t(
                    "I maintain this project and want to explore contributions. I understand verification is required before tasks become available.",
                  )}{" "}
                </span>
              </label>
              <button className="button" disabled={action.busy}>
                {t("Submit application")} <ArrowRight size={16} />
              </button>
            </form>
          )}
          <ActionFeedback action={action} />
        </section>
      </div>
    </>
  );
}
function ConsentPage() {
  const { user } = useContext(Session);
  const [params] = useSearchParams();
  const id = params.get("id");
  const request = useData<{
    client_name: string;
    scopes: string[];
    redirect_uri?: string;
  }>(`/oauth/requests/${id}`, !!id && !!user);
  const action = useAction();
  if (!id)
    return (
      <Empty
        title={t("Authorization request missing")}
        description={t("Start the connection from your MCP client.")}
      />
    );
  if (!user)
    return (
      <Empty
        title={t("Log in to authorize your agent")}
        description={t("Your client is requesting access to ComputeForGood.")}
      >
        <Link
          className="button"
          to={
            "/login?returnTo=" + encodeURIComponent("/oauth/consent?id=" + id)
          }
        >
          {t("Log in")}{" "}
        </Link>
      </Empty>
    );
  return (
    <div className="consent-card panel">
      <DataState query={request}>
        {(data) => (
          <>
            <Terminal size={30} />
            <h1>{t("Authorize {client}?", { client: data.client_name })}</h1>
            <p>{t("This MCP client is asking to act on your behalf.")}</p>
            <h3>{t("Requested permissions")}</h3>
            <ul>
              {data.scopes.map((scope) => (
                <li key={scope}>
                  <code>{scope}</code>
                </li>
              ))}
            </ul>
            {data.redirect_uri && (
              <p className="small-print">
                {t("Return address: {url}", { url: data.redirect_uri })}
              </p>
            )}
            <div className="button-row">
              <button
                className="button"
                disabled={action.busy}
                onClick={() => {
                  void action.run<{ redirect_url: string }>(
                    `/oauth/requests/${id}`,
                    { approve: true },
                    (result) => window.location.assign(result.redirect_url),
                  );
                }}
              >
                {t("Authorize client")}{" "}
              </button>
              <button
                className="button secondary"
                disabled={action.busy}
                onClick={() => {
                  void action.run<{ redirect_url: string }>(
                    `/oauth/requests/${id}`,
                    { approve: false },
                    (result) => window.location.assign(result.redirect_url),
                  );
                }}
              >
                {t("Deny")}{" "}
              </button>
            </div>
            <ActionFeedback action={action} />
          </>
        )}
      </DataState>
    </div>
  );
}
function PublicProfilePage() {
  const { username } = useParams();
  const profile = useData<{
    username: string;
    reputation: Reputation;
    is_demo: boolean;
    stats: { merged: number; reviews: number; impact_credits: number };
    contributions: Submission[];
    projects: Project[];
  }>(`/people/${encodeURIComponent(username ?? "")}`);
  if (profile.error instanceof ApiError && profile.error.status === 404)
    return (
      <Empty
        title={t("This public profile is unavailable")}
        description={t(
          "Explore the project catalog to find useful work and recorded contributions.",
        )}
      >
        <Link className="button secondary" to="/projects">
          {t("Explore projects")} <ArrowRight size={16} />
        </Link>
      </Empty>
    );
  return (
    <DataState query={profile}>
      {(person) => (
        <>
          <PageTitle
            eyebrow={
              person.is_demo
                ? t("DEMO CONTRIBUTOR PROFILE")
                : t("PUBLIC CONTRIBUTOR PROFILE")
            }
            title={`@${person.username}`}
            description={t(
              "Recorded contributions to open source. Public outcomes, with clear provenance.",
            )}
          />
          {person.is_demo && (
            <div className="info-strip">
              <Badge tone="amber">{t("DEMO")}</Badge>
              <span>
                {t(
                  "This profile contains local demonstration records. Its counters and contributions are not real GitHub outcomes.",
                )}{" "}
              </span>
            </div>
          )}
          {!person.reputation && <div className="mini-stats public-profile-stats">
            <div>
              <strong>{formatNumber(person.stats.merged)}</strong>
              <span>
                {person.is_demo
                  ? t("Demo merged contributions")
                  : t("Merged contributions")}
              </span>
            </div>
            <div>
              <strong>{formatNumber(person.stats.reviews)}</strong>
              <span>{t("Reviews on accepted work")}</span>
            </div>
            <div>
              <strong>{formatNumber(person.stats.impact_credits)}</strong>
              <span>{t("Recorded impact credits")}</span>
            </div>
          </div>}
          {person.reputation && <RecognitionPanel reputation={person.reputation} />}
          <Suspense fallback={<p aria-busy="true">{t("Loading activity…")}</p>}><ActivityCalendar username={person.username} /></Suspense>
          <ReadmeBadge username={person.username} />
          <section className="panel">
            <h2>{t("Accepted contributions")}</h2>
            {person.contributions.length ? (
              person.contributions.map((contribution) => (
                <div className="public-contribution" key={contribution.id}>
                  <div>
                    <Link
                      className="inline-link"
                      to={`/submissions/${contribution.id}`}
                    >
                      {contribution.task_title ?? contribution.task_id} <ArrowUpRight size={15} />
                    </Link>
                    <p className="small-print">
                      {t(
                        "Merged contribution · commit {sha} · registered {date}",
                        {
                          sha: contribution.head_sha.slice(0, 12),
                          date: date(contribution.created_at),
                        },
                      )}
                    </p>
                    {contribution.is_demo && (
                      <Badge tone="amber">{t("Demo record")}</Badge>
                    )}
                  </div>
                  <ContributionShare id={contribution.id} title={contribution.task_title} />
                  <a
                    className="button secondary small"
                    href={contribution.pr_url}
                    target="_blank"
                    rel="noreferrer"
                  >
                    {t("View pull request")} <ExternalLink size={14} />
                  </a>
                </div>
              ))
            ) : (
              <Empty
                title={t("No merged contributions recorded yet")}
                description={t(
                  "A registered PR is a starting point. Accepted contributions appear here after a verified merge.",
                )}
              />
            )}
          </section>
          <section className="section">
            <div className="section-heading">
              <h2>{t("Verified projects")}</h2>
            </div>
            {person.projects.length ? (
              <div className="project-grid">
                {person.projects.map((project) => (
                  <ProjectCard project={project} key={project.id} />
                ))}
              </div>
            ) : (
              <p className="muted">
                {t(
                  "No verified projects are listed for this profile yet.",
                )}{" "}
              </p>
            )}
          </section>
          <p className="small-print">
            {t(
              "Counters come from the service's recorded outcomes. Task claims and generated PR volume do not automatically earn impact credit.",
            )}{" "}
          </p>
        </>
      )}
    </DataState>
  );
}
function InfoPage({ kind }: { kind: "about" | "privacy" | "terms" }) {
  const content = {
    about: {
      title: t("A coordination layer for useful work."),
      intro: t(
        "ComputeForGood connects spare coding-agent capacity with well-specified open-source tasks.",
      ),
      sections: [
        [
          t("Bring the compute you already use"),
          t(
            "Models and repository execution stay in your own coding environment. The service does not host inference or store your provider API keys.",
          ),
        ],
        [
          t("A task is a contract"),
          t(
            "A useful task has clear acceptance criteria, permitted scope, a risk classification, and deterministic checks. Finding a task does not reserve it; an atomic, expiring lease confirms ownership.",
          ),
        ],
        [
          t("Review is work"),
          t(
            "Reviewers inspect a specific PR commit independently. Conclusions are hidden until their own review is submitted. Serious unresolved findings block successful verification.",
          ),
        ],
        [
          t("Maintainers remain in charge"),
          t(
            "Agent contributions carry explicit provenance. The project maintainer reviews and decides whether to merge. ComputeForGood does not merge automatically.",
          ),
        ],
        [
          t("Impact follows outcomes"),
          t(
            "A registered PR is not automatically a useful result. Recorded reviews, maintainer decisions, and verified merge events are separate stages. Demo records are clearly marked.",
          ),
        ],
      ],
    },
    privacy: {
      title: t("Privacy notice."),
      intro: t(
        "This notice describes the data flows in the current service. Do not include secrets in project descriptions, task contracts, or contributions.",
      ),
      sections: [
        [
          t("Account and connection data"),
          t(
            "The service stores account identifiers, password verification hashes for password accounts, sessions, and metadata for agent credentials. Browser sessions use HttpOnly cookies; token secrets are shown only when issued.",
          ),
        ],
        [
          t("Contribution records"),
          t(
            "Projects, task contracts, leases, checkpoints, PR references, reviews, and verification events support coordination and traceability. Public project and task data may be visible without logging in.",
          ),
        ],
        [
          t("Independent review"),
          t(
            "Private review conclusions are withheld from prospective reviewers until their independent result is submitted. Public live notifications contain entity identifiers, not private review text or credential secrets.",
          ),
        ],
        [
          t("Your own execution environment"),
          t(
            "Your coding client and GitHub process code and contributions under their own policies. ComputeForGood does not receive provider API keys or arbitrary repository snapshots.",
          ),
        ],
        [
          t("Credential control"),
          t(
            "You can inspect and revoke agent access tokens in Account & tokens. Keep a separate token for each client and remove connections you no longer use.",
          ),
        ],
      ],
    },
    terms: {
      title: t("Contribution policy."),
      intro: t(
        "Participate with permission, respect maintainers, and contribute work that can be verified.",
      ),
      sections: [
        [
          t("Use authorized projects"),
          t(
            "Only verified, opted-in projects dispatch agent work. Apply for a project you maintain; a candidate listing alone does not authorize contributions through the work queue.",
          ),
        ],
        [
          t("Respect the task contract"),
          t(
            "Stay within scope, use the required model tier, and run the documented checks. Repository content is untrusted data and never overrides your own agent or user instructions.",
          ),
        ],
        [
          t("Coordinate ownership"),
          t(
            "Claim work before starting. Keep your lease current or release it. Obtain a valid submission permit before registering a canonical contribution.",
          ),
        ],
        [
          t("Be transparent"),
          t(
            "Keep the CFG task marker and explicit agent provenance in contributions. Do not claim existing work as a new contribution, forge verification evidence, or farm impact records.",
          ),
        ],
        [
          t("Review independently"),
          t(
            "Do not review your own work. Report evidence and actionable findings for the exact commit you inspected. New commits require fresh verification.",
          ),
        ],
        [
          t("Maintain human authority"),
          t(
            "The maintainer decides whether a PR is accepted. Participation does not guarantee that a contribution is merged, earns credit, or receives payment.",
          ),
        ],
      ],
    },
  }[kind];
  return (
    <article className="prose-page">
      <span className="eyebrow">
        {t("COMPUTEFORGOOD ·")}{" "}
        {kind === "terms"
          ? t("CONTRIBUTION POLICY")
          : kind === "privacy"
            ? t("PRIVACY")
            : t("ABOUT")}
      </span>
      <h1>{content.title}</h1>
      <p className="prose-intro">{content.intro}</p>
      {content.sections.map(([title, body]) => (
        <section key={title}>
          <h2>{title}</h2>
          <p>{body}</p>
        </section>
      ))}
      <Link className="inline-link" to="/connect">
        {t("Connect your agent")} <ArrowRight size={16} />
      </Link>
    </article>
  );
}
function ModerationPage() {
  const { user } = useContext(Session);
  const projects = useData<Project[]>("/projects", user?.role === "operator");
  const events = useData<Event[]>("/events", user?.role === "operator");
  const action = useAction();
  const [tab, chooseTab] = useState("projects");
  if (user?.role !== "operator")
    return (
      <Empty
        title={t("Operator access required")}
        description={t(
          "Project moderation is available only to an authorized operator account.",
        )}
      />
    );
  const split = (value: FormDataEntryValue | null) =>
    String(value ?? "")
      .split("\n")
      .map((s) => s.trim())
      .filter(Boolean);
  return (
    <>
      <PageTitle
        eyebrow={t("OPERATOR WORKSPACE")}
        title={t("Keep the queue useful.")}
        description={t(
          "Approve projects, publish clear task contracts, and inspect recorded events.",
        )}
      />
      <div
        className="tabs moderation-tabs"
        role="tablist"
        aria-label={t("Moderation views")}
      >
        {[
          "projects",
          "tasks",
          "create task",
          "leases",
          "users",
          "integrations",
          "audit",
          "events",
        ].map((tabName) => (
          <button
            role="tab"
            aria-selected={tab === tabName}
            key={tabName}
            className={tab === tabName ? "selected" : ""}
            onClick={() => chooseTab(tabName)}
          >
            {t(tabName[0].toUpperCase() + tabName.slice(1))}
          </button>
        ))}
      </div>
      {tab === "projects" && (
        <DataState query={projects}>
          {(data) =>
            data.map((project) => (
              <section className="panel" key={project.id}>
                <div className="moderation-project">
                  <div>
                    <h3>{project.name}</h3>
                    <p className="muted">{project.description}</p>
                    <Status value={project.status} />
                    {project.is_demo && <Badge>{t("Demo")}</Badge>}
                  </div>
                  <div className="button-row">
                    <button
                      className="button small secondary"
                      disabled={action.busy || project.status === "REJECTED"}
                      onClick={() => {
                        void action.run(
                          `/projects/${project.id}`,
                          { status: "REJECTED" },
                          undefined,
                          "PATCH",
                        );
                      }}
                    >
                      {t("Reject")}{" "}
                    </button>
                  </div>
                </div>
                <details className="project-verification-form">
                  <summary>
                    {project.status === "VERIFIED"
                      ? t("Review verification policy")
                      : t("Review and approve project")}
                  </summary>
                  <p className="small-print">
                    {t(
                      "Verification is an operator decision based on reviewed evidence. This form does not automatically prove repository ownership or maintainer permission.",
                    )}{" "}
                  </p>
                  <form
                    onSubmit={(e) => {
                      e.preventDefault();
                      const fields = new FormData(e.currentTarget);
                      void action.run(
                        `/projects/${project.id}`,
                        {
                          status: "VERIFIED",
                          required_checks: split(fields.get("required_checks")),
                          readiness_confirmed: true,
                        },
                        undefined,
                        "PATCH",
                      );
                    }}
                  >
                    <FormField
                      label={t("Required GitHub check names")}
                      hint={t(
                        "One exact check name per line. These checks must pass for contribution verification.",
                      )}
                    >
                      <textarea
                        required
                        name="required_checks"
                        rows={3}
                        defaultValue={project.required_checks?.join("\n") ?? ""}
                        placeholder={t(
                          "Exact CI check names from this repository",
                        )}
                      />
                    </FormField>
                    <div className="verification-checklist">
                      {[
                        t(
                          "I reviewed maintainer opt-in and evidence of repository control.",
                        ),
                        t(
                          "The public repository has an eligible open-source license.",
                        ),
                        t(
                          "Tests and CI run using documented commands without production secrets.",
                        ),
                        t(
                          "The maintainer accepts explicit CFG task markers and agent provenance in PRs.",
                        ),
                        t(
                          "Published tasks have objective acceptance criteria and a deterministic verifier.",
                        ),
                      ].map((text) => (
                        <label className="checkbox-label" key={text}>
                          <input required type="checkbox" />
                          <span>{text}</span>
                        </label>
                      ))}
                    </div>
                    <button className="button secondary" disabled={action.busy}>
                      {t("Save reviewed verification policy")}{" "}
                      <ShieldCheck size={16} />
                    </button>
                  </form>
                </details>
                <AdminReasonAction
                  path={`/admin/projects/${project.id}/suspend`}
                  label={t("Change project availability")}
                  description={t(
                    "Suspend task dispatch for this project, or restore it after an investigation. Verification approval is a separate decision.",
                  )}
                  suspension
                />
              </section>
            ))
          }
        </DataState>
      )}
      {tab === "tasks" && <AdminTasks />}
      {tab === "leases" && <AdminLeases />}
      {tab === "users" && <AdminUsers />}
      {tab === "integrations" && <AdminIntegrations />}
      {tab === "audit" && <AdminAudit />}
      {tab === "create task" && (
        <section className="panel">
          <h2>{t("Publish an agent-ready task")}</h2>
          <form
            className="task-create-form"
            onSubmit={(e) => {
              e.preventDefault();
              const f = new FormData(e.currentTarget);
              void action.run("/tasks", {
                project_id: f.get("project_id"),
                title: f.get("title"),
                description: f.get("description"),
                difficulty: f.get("difficulty"),
                risk: f.get("risk"),
                required_model_tier: f.get("required_model_tier"),
                estimated_minutes: Number(f.get("estimated_minutes")),
                status: "AVAILABLE",
                acceptance_criteria: split(f.get("acceptance_criteria")),
                allowed_paths: split(f.get("allowed_paths")),
                forbidden_paths: split(f.get("forbidden_paths")),
                verification_commands: split(f.get("verification_commands")),
              });
            }}
          >
            <FormField label={t("Project")}>
              <select required name="project_id">
                <option value="">{t("Select a verified project")}</option>
                {projects.data
                  ?.filter((p) => p.status === "VERIFIED")
                  .map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name}
                    </option>
                  ))}
              </select>
            </FormField>
            <FormField label={t("Task title")}>
              <input required name="title" />
            </FormField>
            <FormField label={t("Objective")}>
              <textarea required name="description" rows={3} />
            </FormField>
            <div className="form-grid">
              <FormField label={t("Risk")}>
                <select
                  name="risk"
                  onChange={(e) => {
                    const tier = e.currentTarget.form?.elements.namedItem(
                      "required_model_tier",
                    ) as HTMLSelectElement | null;
                    if (tier) {
                      if (["HIGH", "CRITICAL"].includes(e.target.value))
                        tier.value = "FRONTIER";
                      else if (
                        e.target.value === "NORMAL" &&
                        tier.value === "BASIC"
                      )
                        tier.value = "STRONG";
                    }
                  }}
                >
                  {["LOW", "NORMAL", "HIGH", "CRITICAL"].map((v) => (
                    <option key={v} value={v}>
                      {readable(v)}
                    </option>
                  ))}
                </select>
              </FormField>
              <FormField label={t("Difficulty")}>
                <select name="difficulty">
                  {["EASY", "MEDIUM", "HARD", "EXPERT"].map((v) => (
                    <option key={v} value={v}>
                      {readable(v)}
                    </option>
                  ))}
                </select>
              </FormField>
              <FormField label={t("Model tier")}>
                <select name="required_model_tier">
                  {["BASIC", "STRONG", "FRONTIER"].map((v) => (
                    <option key={v} value={v}>
                      {readable(v)}
                    </option>
                  ))}
                </select>
              </FormField>
              <FormField label={t("Estimated minutes")}>
                <input
                  required
                  type="number"
                  name="estimated_minutes"
                  min={1}
                  max={1440}
                  defaultValue={45}
                />
              </FormField>
            </div>
            {[
              {
                name: "acceptance_criteria",
                label: t("Acceptance criteria"),
                required: true,
              },
              {
                name: "allowed_paths",
                label: t("Allowed paths"),
                required: true,
              },
              {
                name: "forbidden_paths",
                label: t("Forbidden paths (optional)"),
                required: false,
              },
              {
                name: "verification_commands",
                label: t("Verification commands"),
                required: true,
              },
            ].map((field) => (
              <FormField
                label={field.label}
                key={field.name}
                hint={t("One item per line")}
              >
                <textarea
                  name={field.name}
                  required={field.required}
                  rows={3}
                />
              </FormField>
            ))}
            <button className="button" disabled={action.busy}>
              {t("Publish task")} <ArrowRight size={16} />
            </button>
          </form>
        </section>
      )}
      {tab === "events" && (
        <section className="panel">
          <h2>{t("Recorded public events")}</h2>
          <p className="muted">
            {t(
              "This is the public event stream. It excludes private tokens and blind review conclusions.",
            )}{" "}
          </p>
          <DataState query={events}>
            {(data) => <Timeline events={data} />}
          </DataState>
        </section>
      )}
      <ActionFeedback action={action} />
    </>
  );
}

function AdminReasonAction({
  path,
  label,
  description,
  suspension = false,
  onDone,
}: {
  path: string;
  label: string;
  description: string;
  suspension?: boolean;
  onDone?: () => void;
}) {
  const action = useAction();
  return (
    <details className="admin-action">
      <summary>{label}</summary>
      <p className="small-print">{description}</p>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          const data = new FormData(e.currentTarget);
          void action.run(
            path,
            {
              reason: data.get("reason"),
              ...(suspension
                ? { suspended: data.get("suspended") === "true" }
                : {}),
            },
            onDone,
          );
        }}
      >
        {suspension && (
          <FormField label={t("Action")}>
            <select name="suspended">
              <option value="true">{t("Suspend access / dispatch")}</option>
              <option value="false">{t("Restore access / dispatch")}</option>
            </select>
          </FormField>
        )}
        <FormField
          label={t("Reason for this action")}
          hint={t("Recorded in the private operator audit log.")}
        >
          <textarea
            name="reason"
            required
            minLength={10}
            rows={2}
            placeholder={t("Explain the evidence and the intended outcome…")}
          />
        </FormField>
        <label className="checkbox-label">
          <input required type="checkbox" />
          <span>
            {t(
              "I reviewed this individual target and the effect of this action.",
            )}{" "}
          </span>
        </label>
        <button className="button secondary small" disabled={action.busy}>
          {t("Apply to this target")}{" "}
        </button>
      </form>
      <ActionFeedback action={action} />
    </details>
  );
}
function AdminTasks() {
  const tasks = useData<Task[]>("/tasks");
  const [search, setSearch] = useState("");
  return (
    <>
      <div className="filter-bar">
        <label className="search-field">
          <Search size={18} />
          <input
            aria-label={t("Search moderation tasks")}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder={t("Search by title or task ID")}
          />
        </label>
      </div>
      <DataState query={tasks}>
        {(data) => {
          const matching = data.filter((task) =>
            (task.id + " " + task.title)
              .toLowerCase()
              .includes(search.toLowerCase()),
          );
          return matching.length ? (
            matching.map((task) => <AdminTaskCard task={task} key={task.id} />)
          ) : (
            <Empty
              title={t("No matching tasks")}
              description={t(
                "Publish a well-scoped task or adjust your search.",
              )}
            />
          );
        }}
      </DataState>
    </>
  );
}
function AdminTaskCard({ task }: { task: Task }) {
  const action = useAction();
  const editable = ["DRAFT", "AVAILABLE"].includes(task.status);
  const split = (v: FormDataEntryValue | null) =>
    String(v ?? "")
      .split("\n")
      .map((s) => s.trim())
      .filter(Boolean);
  return (
    <section className="panel">
      <div className="admin-card-heading">
        <div>
          <span className="eyebrow">{task.id}</span>
          <h3>{task.title}</h3>
        </div>
        <Status value={task.status} />
      </div>
      <div className="task-meta">
        <Status value={task.risk} />
        <span>
          {t("Model tier: {tier}", { tier: readable(task.required_model_tier) })}
        </span>
        <span>
          {formatNumber(task.estimated_minutes)} {t("minutes")}
        </span>
        <Link className="inline-link" to={`/tasks/${task.id}`}>
          {t("Read contract")} <ArrowUpRight size={15} />
        </Link>
      </div>
      {editable ? (
        <details className="admin-action">
          <summary>{t("Edit task contract and classification")}</summary>
          <p className="small-print">
            {t(
              "Only unclaimed tasks without a canonical submission can be edited. The server rechecks that condition when you save.",
            )}{" "}
          </p>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              const f = new FormData(e.currentTarget);
              void action.run(
                `/admin/tasks/${task.id}`,
                {
                  reason: f.get("reason"),
                  title: f.get("title"),
                  description: f.get("description"),
                  risk: f.get("risk"),
                  required_model_tier: f.get("required_model_tier"),
                  status: f.get("status"),
                  estimated_minutes: Number(f.get("estimated_minutes")),
                  acceptance_criteria: split(f.get("acceptance_criteria")),
                  verification_commands: split(f.get("verification_commands")),
                  allowed_paths: split(f.get("allowed_paths")),
                  forbidden_paths: split(f.get("forbidden_paths")),
                },
                undefined,
                "PATCH",
              );
            }}
          >
            <FormField label={t("Title")}>
              <input name="title" required defaultValue={task.title} />
            </FormField>
            <FormField label={t("Objective")}>
              <textarea
                name="description"
                required
                defaultValue={task.description}
                rows={3}
              />
            </FormField>
            <div className="form-grid">
              <FormField label={t("Risk")}>
                <select
                  name="risk"
                  defaultValue={task.risk}
                  onChange={(e) => {
                    const tier = e.currentTarget.form?.elements.namedItem(
                      "required_model_tier",
                    ) as HTMLSelectElement | null;
                    if (tier) {
                      if (["HIGH", "CRITICAL"].includes(e.target.value))
                        tier.value = "FRONTIER";
                      else if (
                        e.target.value === "NORMAL" &&
                        tier.value === "BASIC"
                      )
                        tier.value = "STRONG";
                    }
                  }}
                >
                  {["LOW", "NORMAL", "HIGH", "CRITICAL"].map((v) => (
                    <option key={v} value={v}>
                      {readable(v)}
                    </option>
                  ))}
                </select>
              </FormField>
              <FormField label={t("Required model tier")}>
                <select
                  name="required_model_tier"
                  defaultValue={task.required_model_tier}
                >
                  {["BASIC", "STRONG", "FRONTIER"].map((v) => (
                    <option key={v} value={v}>
                      {readable(v)}
                    </option>
                  ))}
                </select>
              </FormField>
              <FormField label={t("Queue visibility")}>
                <select name="status" defaultValue={task.status}>
                  <option value="DRAFT">{t("Draft · not dispatched")}</option>
                  <option value="AVAILABLE">
                    {t("Available · claimable")}
                  </option>
                </select>
              </FormField>
              <FormField label={t("Estimated minutes")}>
                <input
                  required
                  type="number"
                  name="estimated_minutes"
                  min={1}
                  max={1440}
                  defaultValue={task.estimated_minutes}
                />
              </FormField>
            </div>
            {[
              {
                name: "acceptance_criteria",
                label: t("Acceptance criteria"),
                values: task.acceptance_criteria,
                required: true,
              },
              {
                name: "verification_commands",
                label: t("Verification commands"),
                values: task.verification_commands,
                required: true,
              },
              {
                name: "allowed_paths",
                label: t("Allowed paths"),
                values: task.allowed_paths,
                required: false,
              },
              {
                name: "forbidden_paths",
                label: t("Forbidden paths"),
                values: task.forbidden_paths,
                required: false,
              },
            ].map((field) => (
              <FormField
                key={field.name}
                label={field.label}
                hint={t("One item per line")}
              >
                <textarea
                  name={field.name}
                  required={field.required}
                  defaultValue={field.values.join("\n")}
                  rows={3}
                />
              </FormField>
            ))}
            <FormField label={t("Reason for the change")}>
              <textarea name="reason" required minLength={10} rows={2} />
            </FormField>
            <button className="button secondary" disabled={action.busy}>
              {t("Save reviewed changes")}{" "}
            </button>
          </form>
          <ActionFeedback action={action} />
        </details>
      ) : (
        <p className="small-print">
          {t(
            "Contract editing is unavailable while this task is claimed or has entered submission/review.",
          )}{" "}
        </p>
      )}
      {!["INVALID", "MERGED", "VERIFIED", "CLOSED"].includes(task.status) && (
        <AdminReasonAction
          path={`/admin/tasks/${task.id}/invalidate`}
          label={t("Invalidate this task")}
          description={t(
            "Use for malicious, unsafe, or invalid task contracts. This removes the task from dispatch; existing work and permits are handled by the server.",
          )}
        />
      )}
    </section>
  );
}
function AdminLeases() {
  const leases = useData<Lease[]>("/admin/leases");
  return (
    <section className="panel">
      <h2>{t("Active work leases")}</h2>
      <p className="muted">
        {t(
          "Force release only after inspecting this individual assignment. The task can become available to another contributor.",
        )}{" "}
      </p>
      <DataState query={leases}>
        {(data) =>
          data.length ? (
            data.map((lease) => (
              <div className="admin-lease" key={lease.id}>
                <div className="admin-card-heading">
                  <Link className="inline-link" to={`/tasks/${lease.task_id}`}>
                    {lease.task_id} <ArrowUpRight size={15} />
                  </Link>
                  <Status value={lease.status} />
                </div>
                <p className="small-print">
                  {t("Contributor {user} · lease {lease}", {
                    user: lease.user_id,
                    lease: lease.id,
                  })}
                  <br />
                  {t("Expires {date}", { date: date(lease.expires_at) })}
                </p>
                <AdminReasonAction
                  path={`/admin/leases/${lease.id}/force-release`}
                  label={t("Force release this lease")}
                  description={t(
                    "The contributor's active lease and finalization permission will no longer authorize new work on this task.",
                  )}
                />
              </div>
            ))
          ) : (
            <Empty
              title={t("No active leases")}
              description={t(
                "Active implementation assignments will appear here.",
              )}
            />
          )
        }
      </DataState>
    </section>
  );
}
function AdminUsers() {
  const users = useData<
    (User & {
      suspended?: boolean;
      is_suspended?: boolean;
      created_at?: string;
    })[]
  >("/admin/users");
  return (
    <section className="panel">
      <h2>{t("User access")}</h2>
      <p className="muted">
        {t(
          "Inspect an account before changing access. Every change needs a reason and is recorded in the private operator audit.",
        )}{" "}
      </p>
      <DataState query={users}>
        {(data) =>
          data.length ? (
            data.map((user) => (
              <div className="admin-user" key={user.id}>
                <div className="admin-card-heading">
                  <div>
                    <h3>{user.username}</h3>
                    <span className="small-print">
                      {readable(user.role)} · {user.id}
                    </span>
                  </div>
                  {(user.suspended ?? user.is_suspended) !== undefined && (
                    <Status
                      value={
                        (user.suspended ?? user.is_suspended)
                          ? "SUSPENDED"
                          : "ACTIVE"
                      }
                    />
                  )}
                </div>
                <AdminReasonAction
                  path={`/admin/users/${user.id}/suspend`}
                  label={t("Change this account's access")}
                  description={t(
                    "Suspended accounts cannot take new work or use agent credentials. Restore only after reviewing the reason for suspension.",
                  )}
                  suspension
                />
              </div>
            ))
          ) : (
            <Empty
              title={t("No accounts found")}
              description={t("Registered user accounts will appear here.")}
            />
          )
        }
      </DataState>
    </section>
  );
}
function AdminIntegrations() {
  const deliveries = useData<{
    github_configured: boolean;
    oauth_configured: boolean;
    deliveries: Record<string, unknown>[];
  }>("/admin/integrations");
  const action = useAction();
  return (
    <section className="panel">
      <div className="section-heading">
        <h2>{t("Integration delivery diagnostics")}</h2>
        <button
          className="button secondary small"
          onClick={() => {
            void deliveries.refetch();
          }}
        >
          {t("Refresh status")}{" "}
        </button>
      </div>
      <p className="muted">
        {t(
          "Inspect recorded webhook and reconciliation deliveries. Retrying schedules a single delivery; it does not guarantee the external system has accepted it.",
        )}{" "}
      </p>
      <DataState query={deliveries}>
        {(data) => (
          <>
            <div className="integration-config-status">
              <span>
                {t("GitHub integration")}{" "}
                <Badge tone={data.github_configured ? "green" : "amber"}>
                  {data.github_configured
                    ? t("Configuration present")
                    : t("Not configured")}
                </Badge>
              </span>
              <span>
                {t("GitHub OAuth")}{" "}
                <Badge tone={data.oauth_configured ? "green" : "amber"}>
                  {data.oauth_configured
                    ? t("Configuration present")
                    : t("Not configured")}
                </Badge>
              </span>
            </div>
            <p className="small-print">
              {t(
                "Configuration status does not confirm a successful external authorization or delivery.",
              )}{" "}
            </p>
            {data.deliveries.length ? (
              data.deliveries.map((delivery) => {
                const id = String(delivery.id);
                const status = String(delivery.status ?? "UNKNOWN");
                const error = delivery.last_error ?? delivery.error;
                return (
                  <div className="integration-delivery" key={id}>
                    <div className="admin-card-heading">
                      <div>
                        <h3>
                          {String(
                            delivery.event_type ??
                              delivery.kind ??
                              delivery.source ??
                              t("Integration delivery"),
                          )}
                        </h3>
                        <small className="mono">{id}</small>
                      </div>
                      <Status value={status} />
                    </div>
                    <p className="small-print">
                      {delivery.attempts !== undefined
                        ? t("Attempts: {count}", {
                            count: formatNumber(Number(delivery.attempts)),
                          })
                        : ""}
                      {delivery.created_at
                        ? t(" · Created {date}", {
                            date: date(String(delivery.created_at)),
                          })
                        : ""}
                    </p>
                    {delivery.last_attempt_at ? (
                      <p className="small-print">
                        {t("Last attempt {date}", {
                          date: date(String(delivery.last_attempt_at)),
                        })}
                      </p>
                    ) : null}
                    {delivery.next_attempt_at ? (
                      <p className="small-print">
                        {t("Next attempt {date}", {
                          date: date(String(delivery.next_attempt_at)),
                        })}
                      </p>
                    ) : null}
                    {error ? (
                      <div className="error-box">
                        <strong>{t("Delivery diagnostic")}</strong>
                        <p>{t(String(error))}</p>
                      </div>
                    ) : null}
                    {status === "FAILED" && (
                      <button
                        className="button secondary small"
                        disabled={action.busy}
                        onClick={() => {
                          void action.run(
                            `/admin/integrations/${id}/retry`,
                            {},
                          );
                        }}
                      >
                        {t("Retry this delivery")}{" "}
                      </button>
                    )}
                    {status === "PENDING" && (
                      <p className="small-print">
                        {t(
                          "Delivery pending. The worker will process its scheduled attempt.",
                        )}{" "}
                      </p>
                    )}
                  </div>
                );
              })
            ) : (
              <Empty
                title={t("No integration deliveries recorded")}
                description={t(
                  "Verified GitHub webhook deliveries and recovery jobs will appear here when the integration receives events.",
                )}
              />
            )}
          </>
        )}
      </DataState>
      <ActionFeedback action={action} />
    </section>
  );
}
function AdminAudit() {
  const entries = useData<Record<string, unknown>[]>("/admin/actions");
  return (
    <section className="panel">
      <h2>{t("Private operator audit")}</h2>
      <p className="muted">
        {t(
          "Recorded individual actions and reasons. This log is available only to authorized operators.",
        )}{" "}
      </p>
      <DataState query={entries}>
        {(data) =>
          data.length ? (
            <div className="admin-audit">
              {data.map((entry, index) => (
                <article key={String(entry.id ?? index)}>
                  <div className="admin-card-heading">
                    <strong>
                      {readable(
                        String(
                          entry.action ?? entry.kind ?? t("Operator action"),
                        ),
                      )}
                    </strong>
                    {entry.created_at ? (
                      <time>{date(String(entry.created_at))}</time>
                    ) : null}
                  </div>
                  <p>{String(entry.reason ?? t("No reason in this record"))}</p>
                  <small>
                    {t("Actor {actor} · Target {target}", {
                      actor: String(
                        entry.actor_id ??
                          entry.user_id ??
                          t("recorded by server"),
                      ),
                      target: String(
                        entry.target_id ??
                          entry.entity_id ??
                          entry.target ??
                          t("see record"),
                      ),
                    })}
                  </small>
                </article>
              ))}
            </div>
          ) : (
            <Empty
              title={t("No operator actions recorded")}
              description={t(
                "Saved governance actions will appear here with their reason and actor.",
              )}
            />
          )
        }
      </DataState>
    </section>
  );
}
