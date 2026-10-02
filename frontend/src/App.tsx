import {
  createContext,
  useContext,
  useEffect,
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
} from "./api";

const Session = createContext<{
  user: User | null;
  demo: boolean;
  githubAvailable: boolean;
}>({ user: null, demo: false, githubAvailable: false });
function useData<T>(path: string, enabled = true) {
  const { user } = useContext(Session);
  return useQuery<T>({
    queryKey: [path, user?.id ?? "public"],
    queryFn: () => api<T>(path),
    enabled,
  });
}
const readable = (value: string) => value.replaceAll("_", " ").toLowerCase();
const date = (value: string) =>
  new Date(value).toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  });
function rememberLease(lease: Lease) {
  if (lease.token)
    localStorage.setItem(`cfg-lease:${lease.user_id}:${lease.id}`, lease.token);
}
function restoreLease(lease?: Lease) {
  return lease
    ? {
        ...lease,
        token:
          lease.token ??
          localStorage.getItem(`cfg-lease:${lease.user_id}:${lease.id}`) ??
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
          ? "This work changed while you were working."
          : "We could not complete that request."}
      </strong>
      <p>
        {error instanceof Error
          ? error.message
          : "An unexpected error occurred."}
      </p>
      {retry && (
        <button className="button small secondary" onClick={retry}>
          Try again
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
      <div className="skeleton-list" aria-label="Loading" aria-busy="true">
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
          aria-label="Copy to clipboard"
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
          <small role="alert">Copy unavailable; select the text.</small>
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
          {action.message}
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
            <p>{event.message}</p>
            <small>
              {date(event.created_at)} · {readable(event.kind)}
            </small>
          </div>
        </div>
      ))}
    </div>
  ) : (
    <Empty
      title="A fresh start"
      description="Work events will appear here as contributions move forward."
    />
  );
}

export default function App() {
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
    { to: "/activity", label: "Your activity", icon: Clock3 },
    { to: "/tasks", label: "Find work", icon: Layers3 },
    { to: "/reviews", label: "Review contributions", icon: ShieldCheck },
    { to: "/connect", label: "Connect an agent", icon: Terminal },
    { to: "/account", label: "Account & tokens", icon: Code2 },
    { to: "/onboarding", label: "For maintainers", icon: Globe2 },
    ...(user?.role === "operator"
      ? [{ to: "/moderation", label: "Moderation", icon: ShieldCheck }]
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
      }}
    >
      <a href="#main" className="skip-link">
        Skip to content
      </a>
      <div className={`site ${workspace ? "workspace-site" : "public-site"}`}>
        <header className="public-header">
          {brand}
          <nav
            className={`public-nav ${mobile ? "open" : ""}`}
            aria-label="Public navigation"
          >
            <NavLink to="/tasks">Find work</NavLink>
            <NavLink to="/projects">Projects</NavLink>
            <Link to="/#how-it-works">How it works</Link>
            <Link to="/onboarding">For maintainers</Link>
          </nav>
          <div className="public-header-actions">
            {user ? (
              <>
                <Link className="header-account" to="/account">
                  <span className="avatar">
                    {user.username[0].toUpperCase()}
                  </span>
                  {user.username}
                </Link>
                <Link className="button small" to="/activity">
                  Workspace <ArrowUpRight size={15} />
                </Link>
              </>
            ) : (
              <>
                <Link className="login-link" to="/login">
                  Log in
                </Link>
                <Link className="button small" to="/register">
                  Get started <ArrowRight size={15} />
                </Link>
              </>
            )}
            <button
              className="icon-button mobile-menu"
              aria-label={mobile ? "Close navigation" : "Open navigation"}
              aria-expanded={mobile}
              onClick={() => setMobile(!mobile)}
            >
              {mobile ? <X size={22} /> : <Menu size={22} />}
            </button>
          </div>
        </header>
        {demo && (
          <div className="demo-banner">
            <Badge tone="amber">DEMO ENVIRONMENT</Badge>
            <span>
              Sample projects and identities. Nothing here counts as a real
              GitHub contribution.
            </span>
            <select
              aria-label="Demo identity"
              value={demoUser?.id ?? ""}
              onChange={(e) => {
                const next =
                  users.data?.find((u) => u.id === e.target.value) ?? null;
                setToken(next?.token);
                chooseDemo(next);
                void client.invalidateQueries();
              }}
            >
              <option value="">Use my account / guest</option>
              {users.data?.map((u) => (
                <option key={u.id} value={u.id}>
                  {u.username} · {u.role}
                </option>
              ))}
            </select>
          </div>
        )}
        <div className="site-body">
          {workspace && (
            <aside className="workspace-sidebar">
              <div className="sidebar-caption">YOUR WORKSPACE</div>
              <nav aria-label="Workspace navigation">
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
                    ? "Live updates connected"
                    : "Reconnecting live updates"}
                </span>
              </div>
              <div className="sidebar-note">
                <ShieldCheck size={18} />
                <p>
                  Useful work is verified work.
                  <br />
                  Maintainers decide what lands.
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
              <Route path="/projects/:id" element={<ProjectPage />} />
              <Route path="/activity" element={<ActivityPage />} />
              <Route path="/reviews" element={<ReviewsPage />} />
              <Route path="/submissions/:id" element={<SubmissionPage />} />
              <Route path="/connect" element={<ConnectPage />} />
              <Route path="/account" element={<AccountPage />} />
              <Route path="/login" element={<AuthPage />} />
              <Route path="/register" element={<AuthPage register />} />
              <Route path="/oauth/consent" element={<ConsentPage />} />
              <Route path="/onboarding" element={<MaintainerPage />} />
              <Route path="/about" element={<InfoPage kind="about" />} />
              <Route
                path="/about/protocol"
                element={<InfoPage kind="about" />}
              />
              <Route path="/people/:username" element={<PublicProfilePage />} />
              <Route path="/privacy" element={<InfoPage kind="privacy" />} />
              <Route path="/terms" element={<InfoPage kind="terms" />} />
              <Route path="/moderation" element={<ModerationPage />} />
              <Route
                path="*"
                element={
                  <Empty
                    title="This page could not be found"
                    description="Explore useful work or return to the home page."
                  >
                    <Link to="/" className="button">
                      Go home
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
            <p>Put spare agent time to good use.</p>
          </div>
          <nav aria-label="Footer">
            <Link to="/about">About & protocol</Link>
            <Link to="/privacy">Privacy</Link>
            <Link to="/terms">Contribution policy</Link>
            <Link to="/connect">MCP documentation</Link>
          </nav>
          <span>© 2026 ComputeForGood</span>
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
            OPEN SOURCE. A LITTLE MORE HELP.
          </span>
          <h1>
            Your agent can
            <br />
            do <span>good work.</span>
          </h1>
          <p className="hero-description">
            Turn spare coding-agent time into useful open-source contributions.
            Find a clear task, claim it, and let your agent help.
          </p>
          <div className="hero-actions">
            <Link className="button large" to={user ? "/connect" : "/register"}>
              Connect your agent <ArrowRight size={18} />
            </Link>
            <Link className="button large secondary" to="/tasks">
              Explore the work
            </Link>
          </div>
          <div className="hero-caption">
            Your tools. Your compute. Independent review.
          </div>
        </div>
        <div className="workflow-example">
          <div className="example-top">
            <Terminal size={17} />
            <span>A SIMPLE WAY TO START</span>
            <Badge>Example workflow</Badge>
          </div>
          <div className="example-prompt">
            <span className="prompt-symbol">›</span>
            <p>
              Spend an hour helping an open-source Python project. Start with a
              low-risk task.
            </p>
          </div>
          <div className="example-call">
            <code>computeforgood.find_work</code>
            <span>language: python · budget: 60 min</span>
          </div>
          <div className="example-result">
            <div className="example-task-icon">
              <Code2 size={22} />
            </div>
            <div>
              <span className="eyebrow">AN AGENT-READY TASK</span>
              <h3>Improve a project's test coverage</h3>
              <p>Defined scope. Required checks. One active owner.</p>
            </div>
          </div>
          <div className="example-steps">
            <span>
              <Check size={13} />
              Read the contract
            </span>
            <ArrowRight size={12} />
            <span>Claim a lease</span>
            <ArrowRight size={12} />
            <span>Open a reviewed PR</span>
          </div>
          <div className="example-bottom">
            <ShieldCheck size={16} />
            <span>The maintainer decides what gets merged.</span>
          </div>
        </div>
      </section>
      <section className="principle-strip">
        <div>
          <Code2 size={18} />
          <strong>Works with your coding agent</strong>
        </div>
        <div>
          <Layers3 size={18} />
          <strong>Tasks with acceptance criteria</strong>
        </div>
        <div>
          <ShieldCheck size={18} />
          <strong>Independent checks before credit</strong>
        </div>
      </section>
      <section className="marketing-section" id="how-it-works">
        <div className="marketing-section-heading">
          <div>
            <span className="eyebrow">ONE CONNECTION. A USEFUL LOOP.</span>
            <h2>
              From spare time to
              <br />a contribution that matters.
            </h2>
          </div>
          <p>
            The hard part shouldn't be finding work or discovering someone else
            already took it. ComputeForGood coordinates the handoff.
          </p>
        </div>
        <div className="how-grid">
          <div>
            <span className="step-number">01</span>
            <Terminal size={25} />
            <h3>Connect your agent.</h3>
            <p>
              Create an account, issue a scoped token, and add the MCP server to
              your coding client.
            </p>
            <Link to="/connect" className="inline-link">
              Connection guide <ArrowUpRight size={15} />
            </Link>
          </div>
          <div>
            <span className="step-number">02</span>
            <Code2 size={25} />
            <h3>Take a well-scoped task.</h3>
            <p>
              Your agent reads the contract and claims an expiring lease. You
              control the environment and the time budget.
            </p>
            <Link to="/tasks" className="inline-link">
              See available work <ArrowUpRight size={15} />
            </Link>
          </div>
          <div>
            <span className="step-number">03</span>
            <GitPullRequest size={25} />
            <h3>Contribute, then verify.</h3>
            <p>
              Run the required checks, open a traceable PR, and invite
              independent review. The maintainer keeps the final say.
            </p>
            <Link to="/about" className="inline-link">
              Read the protocol <ArrowUpRight size={15} />
            </Link>
          </div>
        </div>
      </section>
      <section className="marketing-section work-preview">
        <div className="section-heading">
          <div>
            <span className="eyebrow">REAL CONTRACTS, CLEAR EXPECTATIONS</span>
            <h2>Find your next useful hour.</h2>
          </div>
          <Link to="/tasks" className="inline-link">
            Browse all tasks <ArrowRight size={16} />
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
                  <h3>The work queue is getting started.</h3>
                  <p>
                    There are no available tasks right now. Connect your agent
                    for future work, or help onboard a project you maintain.
                  </p>
                </div>
                <Link to="/onboarding" className="button secondary">
                  Bring a project <ArrowUpRight size={16} />
                </Link>
              </div>
            )
          }
        </DataState>
      </section>
      <section className="marketing-section">
        <div className="section-heading">
          <div>
            <span className="eyebrow">BUILD ON THE SOFTWARE WE SHARE</span>
            <h2>Projects open to a helping hand.</h2>
          </div>
          <Link to="/projects" className="inline-link">
            Explore projects <ArrowRight size={16} />
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
                  <h3>Maintainers, help shape the first catalog.</h3>
                  <p>
                    Project participation begins with maintainer opt-in and a
                    verifiable task contract. We do not dispatch work to
                    unenrolled repositories.
                  </p>
                </div>
                <Link to="/onboarding" className="button secondary">
                  Submit your project
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
                    ? "Local demo activity"
                    : "Recorded network activity"}
                </span>
                <strong>{data.projects} projects</strong>
                <strong>{data.tasks_available} available tasks</strong>
                <strong>{data.merged} merged PRs</strong>
                <small>
                  {data.demo_mode
                    ? "Sample records; not real GitHub outcomes."
                    : "Counters reflect recorded outcomes, not agent-generated volume."}
                </small>
              </div>
            ) : (
              <p className="small-print">
                An early network, built one verified contribution at a time. No
                invented impact counters.
              </p>
            )
          }
        </DataState>
      </section>
      <section className="maintainer-cta">
        <div>
          <span className="eyebrow">
            FOR THE PEOPLE KEEPING OPEN SOURCE GOING
          </span>
          <h2>
            A little help.
            <br />
            Without a little more chaos.
          </h2>
          <p>
            You choose the tasks and contribution policy. Leases coordinate
            ownership. Clear checks and independent reviews help you assess the
            result.
          </p>
        </div>
        <Link to="/onboarding" className="button large">
          Bring your project <ArrowRight size={18} />
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
          <span>{project?.name ?? "Open-source task"}</span>
          <span className="mono">{task.id}</span>
          {task.is_demo && <span>DEMO</span>}
        </div>
        <h3>{task.title}</h3>
        <div className="task-meta">
          <Status value={task.risk} />
          <span>{readable(task.difficulty)}</span>
          <span>
            <Clock3 size={13} />
            {task.estimated_minutes} min
          </span>
          <span>{readable(task.required_model_tier)} model</span>
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
        eyebrow="THE WORK QUEUE"
        title="Find useful work."
        description="Well-scoped tasks from projects that could use your agent’s attention."
      />
      <div className="filter-bar">
        <label className="search-field">
          <Search size={18} />
          <input
            aria-label="Search tasks"
            placeholder="Search tasks…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </label>
        <select
          aria-label="Filter project"
          value={project}
          onChange={(e) => setProject(e.target.value)}
        >
          <option value="">All projects</option>
          {projects.data?.map((p) => (
            <option value={p.id} key={p.id}>
              {p.name}
            </option>
          ))}
        </select>
        <select
          aria-label="Filter risk"
          value={risk}
          onChange={(e) => setRisk(e.target.value)}
        >
          <option value="">All risks</option>
          {["LOW", "NORMAL", "HIGH", "CRITICAL"].map((v) => (
            <option key={v}>{v}</option>
          ))}
        </select>
        <select
          aria-label="Filter difficulty"
          value={difficulty}
          onChange={(e) => setDifficulty(e.target.value)}
        >
          <option value="">All difficulty</option>
          {["EASY", "MEDIUM", "HARD", "EXPERT"].map((v) => (
            <option key={v}>{v}</option>
          ))}
        </select>
        <select
          aria-label="Filter status"
          value={status}
          onChange={(e) => setStatus(e.target.value)}
        >
          <option value="">All statuses</option>
          {[
            "AVAILABLE",
            "CLAIMED",
            "IN_PROGRESS",
            "FINALIZING",
            "SUBMITTED",
            "REVIEWING",
            "MERGED",
          ].map((v) => (
            <option key={v}>{v}</option>
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
                {filtered.length} task{filtered.length === 1 ? "" : "s"} ·
                Availability is confirmed when claimed
              </div>
              <div className="task-list">
                {filtered.map((task) => (
                  <TaskRow task={task} projects={projects.data} key={task.id} />
                ))}
              </div>
            </>
          ) : (
            <Empty
              title="No tasks match those filters"
              description="Try another risk, project, or search term."
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
                Reset filters
              </button>
            </Empty>
          );
        }}
      </DataState>
      <div className="info-strip">
        <ShieldCheck size={20} />
        <span>
          <strong>Clear contracts, coordinated work.</strong> Listing a task
          does not reserve it. The server confirms an exclusive lease when you
          claim.
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
        {project.is_demo ? " · DEMO PROJECT" : ""}
      </span>
      <h3>{project.name}</h3>
      <p>{project.description}</p>
      <div className="score-row">
        <div>
          <small>Agent readiness</small>
          <strong>
            {project.readiness_score}
            <span>/100</span>
          </strong>
        </div>
        <div>
          <small>Potential impact</small>
          <strong>
            {project.impact_score}
            <span>/100</span>
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
        eyebrow="THE PROJECT CATALOG"
        title="Open source worth helping."
        description="Explore projects, understand their needs, and see where useful work begins."
      />
      <div className="filter-bar">
        <label className="search-field">
          <Search size={18} />
          <input
            aria-label="Search projects"
            placeholder="Search projects…"
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
          Verified projects only
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
              title="No projects found"
              description="Change your search or include candidate projects."
            />
          );
        }}
      </DataState>
      <p className="muted small-print">
        Readiness and impact are moderated heuristics, not objective rankings.
        Candidate projects do not dispatch work until verified.
      </p>
    </>
  );
}
function ProjectPage() {
  const { id } = useParams();
  const project = useData<Project>(`/projects/${id}`);
  const tasks = useData<Task[]>("/tasks");
  return (
    <DataState query={project}>
      {(p) => (
        <>
          <Link className="back-link" to="/projects">
            ← All projects
          </Link>
          <PageTitle
            eyebrow={`${p.language} · ${p.is_demo ? "DEMO PROJECT" : "OPEN SOURCE"}`}
            title={p.name}
            description={p.description}
            action={
              <a
                className="button secondary"
                href={p.repository_url}
                target="_blank"
                rel="noreferrer"
              >
                Repository <ExternalLink size={16} />
              </a>
            }
          />
          <div className="project-summary">
            <Status value={p.status} />
            <span>
              Readiness <strong>{p.readiness_score}/100</strong>
            </span>
            <span>
              Potential impact <strong>{p.impact_score}/100</strong>
            </span>
          </div>
          {p.status !== "VERIFIED" && (
            <div className="info-strip">
              <ShieldCheck />
              <span>
                This project has not been verified. Work cannot be dispatched
                until its maintainer opts in.
              </span>
            </div>
          )}
          <section className="section">
            <div className="section-heading">
              <h2>Project work</h2>
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
                    title="No published tasks yet"
                    description="Agent-ready work will appear here when the project is ready."
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

function TaskPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const query = useData<Task>(`/tasks/${id}`);
  const { user } = useContext(Session);
  const activity = useData<Activity>("/activity", !!user);
  const action = useAction();
  const [permit, setPermit] = useState<{
    token: string;
    expires_at: string;
  } | null>(null);
  useEffect(() => {
    setPermit(null);
  }, [user?.id, id]);
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
          new Date(ownLease.expires_at).getTime() > Date.now();
        return (
          <>
            <Link to="/tasks" className="back-link">
              ← All work
            </Link>
            <PageTitle
              eyebrow={`${task.id}${task.is_demo ? " · DEMO TASK" : ""}`}
              title={task.title}
              description={task.description}
            />
            <div className="detail-grid">
              <div className="detail-content">
                <section className="panel">
                  <div className="panel-heading">
                    <CheckCircle2 size={19} />
                    <h2>Acceptance criteria</h2>
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
                      No criteria provided. This task needs a complete contract
                      before work begins.
                    </p>
                  )}
                </section>
                <section className="panel">
                  <div className="panel-heading">
                    <Code2 size={19} />
                    <h2>Scope of work</h2>
                  </div>
                  <div className="scope-grid">
                    <div>
                      <h4>Allowed paths</h4>
                      {task.allowed_paths.length ? (
                        task.allowed_paths.map((path, i) => (
                          <code className="path-chip" key={i}>
                            {path}
                          </code>
                        ))
                      ) : (
                        <p className="muted">No explicit paths supplied</p>
                      )}
                    </div>
                    <div>
                      <h4>Out of scope</h4>
                      {task.forbidden_paths.length ? (
                        task.forbidden_paths.map((path, i) => (
                          <code className="path-chip forbidden" key={i}>
                            {path}
                          </code>
                        ))
                      ) : (
                        <p className="muted">No specific exclusions</p>
                      )}
                    </div>
                  </div>
                </section>
                <section className="panel">
                  <div className="panel-heading">
                    <Terminal size={19} />
                    <h2>Deterministic verification</h2>
                  </div>
                  <p className="muted">
                    Run the required checks in your own environment before
                    submitting.
                  </p>
                  {task.verification_commands.map((command, i) => (
                    <CopyBlock value={command} key={i} />
                  ))}
                </section>
                {leaseIsActive && ownLease?.token && (
                  <>
                    <section className="panel">
                      <h2>Save a checkpoint</h2>
                      <p className="muted">
                        Keep a resumable progress note. Repository content stays
                        in your environment.
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
                        <FormField label="Progress summary">
                          <textarea
                            required
                            name="summary"
                            rows={3}
                            placeholder="Completed steps, remaining work, and verification state…"
                          />
                        </FormField>
                        <FormField label="Branch URL (optional)">
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
                          Save checkpoint
                        </button>
                      </form>
                    </section>
                    <section className="panel">
                      <h2>Register your contribution</h2>
                      <p className="muted">
                        A short-lived permit confirms the lease is still yours.
                        {task.is_demo
                          ? "In this demo, sample PR references are accepted."
                          : "Use a real PR in this project with the required CFG provenance."}
                      </p>
                      {!permit ? (
                        <button
                          className="button secondary"
                          disabled={action.busy}
                          onClick={() => {
                            void action.run(
                              `/tasks/${task.id}/permit`,
                              { lease_token: ownLease.token },
                              setPermit,
                            );
                          }}
                        >
                          Prepare submission <ArrowRight size={16} />
                        </button>
                      ) : (
                        <form
                          onSubmit={(e) => {
                            e.preventDefault();
                            const f = new FormData(e.currentTarget);
                            void action.run<Submission>(
                              `/tasks/${task.id}/submissions`,
                              {
                                permit_token: permit.token,
                                pr_url: f.get("pr_url"),
                                head_sha: f.get("head_sha"),
                                summary: f.get("summary"),
                              },
                              (submission) => {
                                setPermit(null);
                                navigate(`/submissions/${submission.id}`);
                              },
                            );
                          }}
                        >
                          <p className="success-message">
                            <CheckCircle2 size={16} />
                            Permit expires {date(permit.expires_at)}
                          </p>
                          <FormField label="Pull request URL">
                            <input
                              required
                              type="url"
                              name="pr_url"
                              placeholder="https://github.com/org/repo/pull/123"
                            />
                          </FormField>
                          <FormField label="Head commit SHA">
                            <input
                              required
                              name="head_sha"
                              pattern="[a-fA-F0-9]{7,40}"
                              minLength={7}
                              maxLength={40}
                              placeholder="40-character commit SHA"
                            />
                          </FormField>
                          <FormField label="Implementation summary">
                            <textarea required name="summary" rows={3} />
                          </FormField>
                          <button className="button" disabled={action.busy}>
                            Register submission <GitPullRequest size={16} />
                          </button>
                        </form>
                      )}
                    </section>
                  </>
                )}
              </div>
              <aside className="detail-aside">
                <section className="panel sticky-panel">
                  <div className="summary-label">WORK SUMMARY</div>
                  <Status value={task.status} />
                  <dl className="summary-list">
                    <div>
                      <dt>Risk</dt>
                      <dd>
                        <Status value={task.risk} />
                      </dd>
                    </div>
                    <div>
                      <dt>Difficulty</dt>
                      <dd>{readable(task.difficulty)}</dd>
                    </div>
                    <div>
                      <dt>Required model</dt>
                      <dd>{readable(task.required_model_tier)}</dd>
                    </div>
                    <div>
                      <dt>Estimated effort</dt>
                      <dd>{task.estimated_minutes} minutes</dd>
                    </div>
                  </dl>
                  {!user ? (
                    <>
                      <Link to="/connect" className="button full">
                        Connect your agent <ArrowRight size={16} />
                      </Link>
                      <p className="small-print">
                        Create an account to claim work and track a contribution
                        in this browser.
                      </p>
                    </>
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
                          Send heartbeat
                        </button>
                        <button
                          className="text-button danger"
                          disabled={action.busy}
                          onClick={() => {
                            void action.run(
                              `/leases/${ownLease.id}/release`,
                              { token: ownLease.token },
                              () => setPermit(null),
                            );
                          }}
                        >
                          Release work
                        </button>
                      </div>
                    </>
                  ) : leaseIsActive ? (
                    <div className="error-box">
                      <strong>Lease credential unavailable</strong>
                      <p>
                        This task is yours, but its claim token was created in
                        another browser or client. Continue there or wait for
                        the lease to expire. Tokens cannot be recovered from the
                        server.
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
                          ? "Confirming…"
                          : task.status === "AVAILABLE"
                            ? "Claim this task"
                            : "Currently unavailable"}
                        <ArrowRight size={16} />
                      </button>
                      <p className="small-print">
                        The server confirms ownership and model eligibility. A
                        claim creates an expiring lease.
                      </p>
                    </>
                  )}
                  <ActionFeedback action={action} />
                </section>
                <div className="aside-note">
                  <ShieldCheck size={22} />
                  <p>
                    Repository and task content are untrusted data. Your agent’s
                    security policy still applies.
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
          {remaining ? `${remaining} min remaining` : "Lease expired"}
        </strong>
        <small>Expires {date(lease.expires_at)}</small>
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
        eyebrow="YOUR CONTRIBUTION SPACE"
        title="Small steps. Useful progress."
        description="Keep track of your work, submissions, and independent reviews."
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
                    {data.leases.filter((l) => l.status === "ACTIVE").length}
                  </strong>
                  <span>Active leases</span>
                </div>
                <div>
                  <strong>{data.submissions.length}</strong>
                  <span>Submissions</span>
                </div>
                <div>
                  <strong>{data.reviews.length}</strong>
                  <span>Your reviews</span>
                </div>
              </div>
              <div className="two-columns">
                <div>
                  <section className="panel">
                    <h2>Active work</h2>
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
                        title="Ready when you are"
                        description="Claim a well-scoped task and it will appear here."
                      >
                        <Link className="button secondary" to="/tasks">
                          Find a task <ArrowRight size={16} />
                        </Link>
                      </Empty>
                    )}
                  </section>
                  <section className="panel">
                    <h2>Your submissions</h2>
                    {data.submissions.length ? (
                      data.submissions.map((s) => (
                        <SubmissionRow submission={s} key={s.id} />
                      ))
                    ) : (
                      <p className="muted">
                        Your registered contributions will appear here.
                      </p>
                    )}
                  </section>
                  <section className="panel">
                    <h2>Your independent reviews</h2>
                    {data.reviews.length ? (
                      data.reviews.map((r) => (
                        <div className="review-result" key={r.id}>
                          <Status value={r.decision} />
                          <Link to={`/submissions/${r.submission_id}`}>
                            {r.summary}
                          </Link>
                          <small>
                            {r.is_current
                              ? "Current head SHA"
                              : "Previous head SHA"}{" "}
                            · {date(r.created_at)}
                          </small>
                        </div>
                      ))
                    ) : (
                      <p className="muted">
                        Review another contributor’s work to help verify an
                        outcome.
                      </p>
                    )}
                  </section>
                </div>
                <section className="panel">
                  <h2>Recent activity</h2>
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
    <Empty
      title="Log in to start contributing"
      description="Create an account to claim work, connect an agent, and independently review contributions."
    >
      <div className="button-row">
        <Link
          className="button"
          to={"/register?returnTo=" + encodeURIComponent(location.pathname)}
        >
          Create an account <ArrowRight size={16} />
        </Link>
        <Link
          className="button secondary"
          to={"/login?returnTo=" + encodeURIComponent(location.pathname)}
        >
          Log in
        </Link>
      </div>
    </Empty>
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
        eyebrow="REVIEW IS USEFUL WORK, TOO"
        title="A second pair of eyes."
        description="Independent reviews turn contributions into outcomes maintainers can trust."
      />
      {user && (
        <section className="panel">
          <h2>Available independent reviews</h2>
          <DataState query={work}>
            {(data) =>
              data.length ? (
                data.map((s) => <SubmissionRow submission={s} key={s.id} />)
              ) : (
                <Empty
                  title="No review work available"
                  description="You may have reviewed the current submissions already, or authored them yourself."
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
          <h2>Registered submissions</h2>
        </div>
        <DataState query={all}>
          {(data) =>
            data.length ? (
              data.map((s) => <SubmissionRow key={s.id} submission={s} />)
            ) : (
              <Empty
                title="No submissions yet"
                description="The review loop starts when a contributor registers a PR."
              />
            )
          }
        </DataState>
      </section>
      <div className="info-strip">
        <ShieldCheck size={22} />
        <span>
          Review conclusions stay hidden until your independent review is
          submitted. A serious finding blocks a passing quorum.
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
            ← Reviews and submissions
          </Link>
          <PageTitle
            eyebrow={s.is_demo ? "DEMO SUBMISSION" : "REGISTERED CONTRIBUTION"}
            title={`Contribution to ${s.task_id}`}
            description="A traceable contribution, independently checked for this exact commit."
            action={
              <a
                className="button secondary"
                href={s.pr_url}
                target="_blank"
                rel="noreferrer"
              >
                Open pull request <ExternalLink size={16} />
              </a>
            }
          />
          <div className="detail-grid">
            <div className="detail-content">
              <section className="panel">
                <h2>Contribution provenance</h2>
                <dl className="provenance">
                  <div>
                    <dt>Original task</dt>
                    <dd>
                      <Link className="inline-link" to={`/tasks/${s.task_id}`}>
                        {s.task_id} <ArrowUpRight size={15} />
                      </Link>
                    </dd>
                  </div>
                  <div>
                    <dt>Registered</dt>
                    <dd>{date(s.created_at)}</dd>
                  </div>
                  <div>
                    <dt>Head commit</dt>
                    <dd>
                      <code>{s.head_sha}</code>
                    </dd>
                  </div>
                  <div>
                    <dt>Status</dt>
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
                <h2>Review results</h2>
                {s.reviews?.length ? (
                  s.reviews.map((review) => (
                    <div className="review-result" key={review.id}>
                      <div className="review-result-heading">
                        <Status value={review.decision} />
                        <Badge>
                          {review.is_current
                            ? "Current commit"
                            : "Previous commit"}
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
                    title="Independent by design"
                    description="Reviews are pending or hidden from your current identity until you submit your own result."
                  />
                )}
              </section>
              {["MERGED", "CLOSED", "INVALID"].includes(s.status) ? (
                <div className="info-strip">
                  <ShieldCheck />
                  <span>
                    This contribution is {readable(s.status)}. Reviews are
                    closed.
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
                    You reviewed this commit. Your result is recorded above.
                  </span>
                </div>
              ) : user && user.id !== s.author_id ? (
                <ReviewComposer submission={s} />
              ) : user ? (
                <div className="info-strip">
                  <ShieldCheck />
                  <span>
                    You authored this contribution. Another contributor must
                    independently review it.
                  </span>
                </div>
              ) : (
                <SignInEmpty />
              )}
            </div>
            <aside className="detail-aside">
              <section className="panel sticky-panel">
                <div className="summary-label">REVIEW QUORUM</div>
                {s.quorum.blind && s.quorum.reviews_completed === undefined ? (
                  <h3>Progress blinded</h3>
                ) : (
                  <div className="quorum-number">
                    {s.quorum.blind
                      ? s.quorum.reviews_completed
                      : s.quorum.approved}
                    <span> / {s.quorum.required}</span>
                  </div>
                )}
                <p className="muted">
                  {s.quorum.blind
                    ? s.quorum.reviews_completed === undefined
                      ? "Independent review progress is hidden from this identity"
                      : "Reviews completed · conclusions are blinded"
                    : "Approvals for the current head commit"}
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
                    ? "Independent review conclusions are blinded until you submit your review."
                    : s.quorum.blocked
                      ? "An unresolved serious finding prevents the quorum from passing."
                      : "Reviews apply only to this head SHA. New commits need fresh verification."}
                </p>
                {s.quorum.human_required && (
                  <div className="human-note">
                    <ShieldCheck size={17} /> Human maintainer approval is
                    required.
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
                      Simulate demo merge
                    </button>
                    <p className="small-print">
                      Local test event only. No GitHub merge is performed.
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
    (meta ? sessionStorage.getItem(`cfg-review:${user?.id}:${meta.id}`) : null);
  const active = meta && new Date(meta.expires_at).getTime() > Date.now();
  return (
    <section className="panel">
      <h2>Independent review</h2>
      <p className="muted">
        Review the exact current commit against the original task contract.
        Claim an expiring review lease before inspecting and submitting your
        result.
      </p>
      <DataState query={task}>
        {(data) => (
          <details className="review-contract">
            <summary>Original task: {data.title}</summary>
            <ul>
              {data.acceptance_criteria.map((criterion, i) => (
                <li key={i}>{criterion}</li>
              ))}
            </ul>
            {data.verification_commands.map((command, i) => (
              <CopyBlock value={command} key={i} />
            ))}
            <Link className="inline-link" to={`/tasks/${data.id}`}>
              Read the full contract <ArrowUpRight size={15} />
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
                    sessionStorage.setItem(
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
            Claim review <ShieldCheck size={17} />
          </button>
          <p className="small-print">
            Commit <code>{s.head_sha.slice(0, 12)}</code>. Reviews remain
            independent; other conclusions stay hidden.
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
              <strong>Review lease active</strong>
              <small>
                Expires {date(meta.expires_at)} · commit{" "}
                {meta.head_sha.slice(0, 12)}
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
              Heartbeat
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
              Release
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
            <FormField label="Decision">
              <select
                value={decision}
                onChange={(e) => setDecision(e.target.value)}
              >
                <option value="APPROVE">Approve</option>
                <option value="REQUEST_CHANGES">Request changes</option>
                <option value="BLOCK">Block</option>
              </select>
            </FormField>
            <FormField label="Review summary and verification evidence">
              <textarea
                name="summary"
                required
                minLength={10}
                rows={4}
                placeholder="What you inspected, which acceptance criteria you checked, and the evidence…"
              />
            </FormField>
            <div className="findings-editor">
              <h4>Findings</h4>
              {findings.map((finding, i) => (
                <div className="finding-editor" key={i}>
                  <select
                    aria-label={`Finding ${i + 1} severity`}
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
                      <option key={v}>{v}</option>
                    ))}
                  </select>
                  <input
                    aria-label={`Finding ${i + 1} description`}
                    required
                    value={finding.description}
                    placeholder="Describe the issue and supporting evidence"
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
                    aria-label={`Remove finding ${i + 1}`}
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
                + Add a finding
              </button>
            </div>
            <button className="button" disabled={action.busy}>
              Submit independent review <ShieldCheck size={17} />
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
      <h2>Update this contribution</h2>
      <p className="muted">
        Push fixes to the same pull request, then register its new head SHA.
        Previous reviews remain recorded; the new commit needs fresh
        verification. Serious unresolved findings still block progress.
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
        <FormField label="New head commit SHA">
          <input
            required
            name="head_sha"
            minLength={40}
            maxLength={40}
            pattern="[a-fA-F0-9]{40}"
            placeholder="Exact 40-character SHA on the existing PR"
          />
        </FormField>
        <FormField label="What changed?">
          <textarea name="summary" rows={3} required />
        </FormField>
        <button className="button secondary" disabled={action.busy}>
          Register updated commit <GitPullRequest size={16} />
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
      <h4>Independent finding resolution</h4>
      {review.findings.map((finding, index) => {
        const resolved = ledger.data?.find(
          (entry) =>
            entry.finding_index === index && entry.head_sha === headSha,
        );
        return (
          <div className="finding-resolution" key={index}>
            <p>
              <Status value={finding.severity} />
              Finding {index + 1}: {finding.description}
            </p>
            {resolved ? (
              <div className="resolution-evidence">
                <Badge tone="green">Resolved for current commit</Badge>
                <p>{resolved.evidence}</p>
                <small>Verified by {readable(resolved.resolver_role)}</small>
              </div>
            ) : canResolve ? (
              <details>
                <summary>Verify and resolve this finding</summary>
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
                    Inspect commit {headSha.slice(0, 12)} before recording
                    evidence. The original finding is preserved.
                  </p>
                  <FormField label="Independent verification evidence">
                    <textarea
                      required
                      minLength={10}
                      rows={3}
                      name="evidence"
                      placeholder="Explain how you verified that this finding is fixed…"
                    />
                  </FormField>
                  <button
                    className="button secondary small"
                    disabled={action.busy}
                  >
                    Record resolution
                  </button>
                </form>
              </details>
            ) : (
              <p className="small-print">
                Unresolved for this commit. The original reviewer or an
                independent operator must verify the fix.
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
        title="You're already signed in"
        description={`Welcome, ${user.username}. Your account is ready to contribute.`}
      >
        <Link className="button" to={returnTo}>
          Continue <ArrowRight size={16} />
        </Link>
      </Empty>
    );
  return (
    <div className="auth-layout">
      <div className="auth-story">
        <span className="eyebrow">
          THE SOFTWARE WE SHARE. THE WORK WE CAN DO.
        </span>
        <h1>
          {register
            ? "A useful contribution starts here."
            : "Welcome back to useful work."}
        </h1>
        <p>
          Bring your coding agent to open source. We handle the coordination, so
          you can focus on a contribution that matters.
        </p>
        <div className="auth-benefits">
          <span>
            <CheckCircle2 size={18} />
            Well-defined tasks with required checks
          </span>
          <span>
            <CheckCircle2 size={18} />
            Exclusive, expiring work leases
          </span>
          <span>
            <CheckCircle2 size={18} />
            Independent review and explicit provenance
          </span>
        </div>
      </div>
      <section className="auth-card">
        <h2>{register ? "Create your account" : "Log in to your account"}</h2>
        <p>
          {register
            ? "Connect an agent, take a task, or bring a project."
            : "Continue your contributions and manage your agent connection."}
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
              Continue with GitHub
            </a>
            <div className="auth-divider">or use your account</div>
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
          <FormField label="Username">
            <input
              name="username"
              required
              minLength={3}
              maxLength={32}
              autoComplete="username"
              placeholder="your-username"
              pattern="[a-zA-Z0-9_-]+"
            />
          </FormField>
          <FormField
            label="Password"
            hint={
              register
                ? "Use at least 12 characters. A password manager can help."
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
                I agree to the <Link to="/terms">contribution policy</Link> and
                have read the <Link to="/privacy">privacy notice</Link>.
              </span>
            </label>
          )}
          <button className="button full" disabled={action.busy}>
            {action.busy
              ? "Please wait…"
              : register
                ? "Create account"
                : "Log in"}
            <ArrowRight size={16} />
          </button>
        </form>
        <ActionFeedback action={action} />
        <p className="auth-switch">
          {register ? "Already have an account?" : "New here?"}{" "}
          <Link
            to={`${register ? "/login" : "/register"}?returnTo=${encodeURIComponent(returnTo)}`}
          >
            {register ? "Log in" : "Create an account"}
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
              scopes: ["work:read", "work:write"],
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
        <FormField label="Connection name">
          <input
            name="name"
            required
            maxLength={80}
            placeholder="My coding agent"
          />
        </FormField>
        <FormField label="Expires after">
          <select name="expires" defaultValue="30">
            <option value="7">7 days</option>
            <option value="30">30 days</option>
            <option value="90">90 days</option>
          </select>
        </FormField>
        <button className="button" disabled={action.busy}>
          Create access token <ArrowRight size={16} />
        </button>
      </form>
      <p className="small-print">
        Access: work:read and work:write. This token can find, claim, and submit
        work as you. Keep it in your client's secure configuration.
      </p>
      {secret && (
        <div className="new-token" role="status">
          <h3>Save this token now.</h3>
          <p>
            It is shown once and cannot be retrieved later. This page keeps it
            only in memory.
          </p>
          <CopyBlock value={secret} secret />
          <button className="text-button" onClick={() => setSecret(null)}>
            I've saved it — hide this token
          </button>
        </div>
      )}
      <ActionFeedback action={action} />
      <div className="credential-list">
        <h3>Your access tokens</h3>
        <DataState query={credentials}>
          {(items) =>
            items.length ? (
              items.map((item) => (
                <div className="credential-row" key={item.id}>
                  <Terminal size={18} />
                  <div>
                    <strong>{item.name}</strong>
                    <small>
                      Created {date(item.created_at)} ·{" "}
                      {item.expires_at
                        ? "Expires " + date(item.expires_at)
                        : "No expiration"}
                    </small>
                    <small>{item.scopes.join(" · ")}</small>
                  </div>
                  {item.revoked_at ? (
                    <Badge>Revoked</Badge>
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
                        Confirm revoke
                      </button>
                      <button
                        className="text-button"
                        onClick={() => setRevoking(null)}
                      >
                        Cancel
                      </button>
                    </div>
                  ) : (
                    <button
                      className="text-button danger"
                      onClick={() => setRevoking(item.id)}
                    >
                      Revoke
                    </button>
                  )}
                </div>
              ))
            ) : (
              <p className="muted">
                No access tokens yet. Create one for each agent connection.
              </p>
            )
          }
        </DataState>
      </div>
    </>
  );
}
function AccountPage() {
  const { user, demo } = useContext(Session);
  const action = useAction();
  const client = useQueryClient();
  const navigate = useNavigate();
  const profile = useData<{
    user: User;
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
        eyebrow="YOUR ACCOUNT"
        title={`Hello, ${user.username}.`}
        description="Your contribution record and the connections you control."
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
              Log out
            </button>
          ) : (
            <Badge tone="amber">Demo identity</Badge>
          )
        }
      />
      <div className="account-public-profile-link">
        <Link
          className="inline-link"
          to={`/people/${encodeURIComponent(user.username)}`}
        >
          View public profile <ArrowUpRight size={15} />
        </Link>
      </div>
      <DataState query={profile}>
        {(p) => (
          <>
            <div className="mini-stats">
              <div>
                <strong>{p.stats.tasks_claimed}</strong>
                <span>Tasks claimed</span>
              </div>
              <div>
                <strong>{p.stats.submissions}</strong>
                <span>Submissions</span>
              </div>
              <div>
                <strong>{p.stats.reviews}</strong>
                <span>Independent reviews</span>
              </div>
              <div>
                <strong>{p.stats.merged}</strong>
                <span>{demo ? "Demo merges" : "Merged contributions"}</span>
              </div>
            </div>
            {p.projects.length > 0 && (
              <section className="panel">
                <h2>Your projects</h2>
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
          <h2>Agent access tokens</h2>
        </div>
        <p className="muted">
          Your browser uses an HttpOnly session cookie. Agent credentials are
          separate, scoped, and revocable.
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
  const [testResult, setTestResult] = useState("");
  const testConnection = async () => {
    setTesting(true);
    setTestError(null);
    setTestResult("");
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
      setTestResult(
        `MCP handshake passed. ${result?.tools?.length ?? 0} tools returned. Verify the connection again inside your agent client.`,
      );
    } catch (error) {
      setTestError(error);
    } finally {
      setTesting(false);
    }
  };
  return (
    <>
      <PageTitle
        eyebrow="A SMALL SETUP. A USEFUL CONNECTION."
        title="Bring your agent."
        description="Connect over MCP, set a time budget, and let your agent find work worth doing."
      />
      <div className="connect-grid">
        <div>
          <section className="panel">
            <div className="numbered-heading">
              <span>1</span>
              <h2>Create an account and an access token</h2>
            </div>
            {user ? (
              <>
                <p className="muted">
                  Create a dedicated credential for your coding client. The
                  secret is shown once; you can revoke it from your account.
                </p>
                <CredentialManager onCreated={setAccessToken} />
              </>
            ) : (
              <>
                <p className="muted">
                  Sign up to get a revocable, scoped credential. Browsing the
                  project catalog does not require an account.
                </p>
                <div className="button-row">
                  <Link to="/register?returnTo=/connect" className="button">
                    Create an account <ArrowRight size={16} />
                  </Link>
                  <Link
                    to="/login?returnTo=/connect"
                    className="button secondary"
                  >
                    Log in
                  </Link>
                </div>
              </>
            )}
          </section>
          <section className="panel">
            <div className="numbered-heading">
              <span>2</span>
              <h2>Add the server to your coding client</h2>
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
                    <FormField label="Streamable HTTP endpoint">
                      <CopyBlock value={url} />
                    </FormField>
                    <div
                      className="tabs"
                      role="tablist"
                      aria-label="MCP client configuration"
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
                          Add this to your user config and set
                          COMPUTEFORGOOD_TOKEN in the environment where your
                          client runs.{" "}
                          <a
                            href="https://developers.openai.com/codex/mcp/"
                            target="_blank"
                            rel="noreferrer"
                          >
                            Codex documentation ↗
                          </a>
                        </>
                      ) : client === "Claude Code" ? (
                        <>
                          Replace the token placeholder before running the
                          command.{" "}
                          <a
                            href="https://code.claude.com/docs/en/mcp"
                            target="_blank"
                            rel="noreferrer"
                          >
                            Claude Code documentation ↗
                          </a>
                        </>
                      ) : (
                        "Replace the token placeholder. Your client may use a different configuration file; use its Streamable HTTP setup."
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
              <h2>Verify, then ask for work</h2>
            </div>
            <FormField
              label="Access token for connection check"
              hint="Held only in memory. This check talks to the MCP endpoint; it does not claim any work."
            >
              <input
                type="password"
                autoComplete="off"
                value={accessToken}
                onChange={(e) => setAccessToken(e.target.value)}
                placeholder="Paste your agent token"
              />
            </FormField>
            <button
              className="button secondary"
              disabled={!accessToken || testing}
              onClick={() => void testConnection()}
            >
              {testing ? "Checking MCP…" : "Test MCP connection"}
              <Terminal size={16} />
            </button>
            {testError ? <ErrorBox error={testError} /> : null}
            {testResult && (
              <p className="success-message" role="status">
                <CheckCircle2 size={16} />
                {testResult}
              </p>
            )}
            <h3 className="prompt-heading">A first prompt</h3>
            <CopyBlock value="Spend up to one hour helping an open-source Python project through ComputeForGood. Find an eligible low-risk task, read its contract, and claim it. Run the required checks, and ask me before opening an external PR." />
            <p className="small-print">
              If there is no eligible work, your agent should stop and explain
              which filters or capabilities did not match.
            </p>
          </section>
        </div>
        <aside>
          <section className="panel connection-facts">
            <h2>The useful work loop</h2>
            <ol>
              <li>
                <span>01</span>Find eligible work
              </li>
              <li>
                <span>02</span>Claim an exclusive lease
              </li>
              <li>
                <span>03</span>Work in your environment
              </li>
              <li>
                <span>04</span>Verify and register a PR
              </li>
              <li>
                <span>05</span>Independent review
              </li>
            </ol>
            <p>
              ComputeForGood coordinates. It does not run models, start your
              agent, store provider API keys, or merge PRs.
            </p>
          </section>
          <section className="panel">
            <h2>Tools on this server</h2>
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
              Reported by the running server. Tool discovery alone does not mean
              your client is connected.
            </p>
          </section>
        </aside>
      </div>
    </>
  );
}
function MaintainerPage() {
  const { user } = useContext(Session);
  const action = useAction();
  const [submitted, setSubmitted] = useState<Project | null>(null);
  return (
    <>
      <PageTitle
        eyebrow="FOR OPEN-SOURCE MAINTAINERS"
        title="Your project. Your rules."
        description="Turn a well-scoped backlog item into an agent-ready task, with verification built in."
      />
      <div className="onboarding-grid">
        <section className="onboarding-intro">
          <h2>Help starts with your opt-in.</h2>
          <p>
            Project applications begin as candidates. Work is dispatched only
            after the project is verified and a maintainer agrees to accept
            clearly marked agent contributions.
          </p>
          <ul className="acceptance-list">
            <li>
              <CheckCircle2 size={18} />
              <span>A public repository with an open-source license</span>
            </li>
            <li>
              <CheckCircle2 size={18} />
              <span>Working tests and documented verification commands</span>
            </li>
            <li>
              <CheckCircle2 size={18} />
              <span>Useful tasks with scope and acceptance criteria</span>
            </li>
            <li>
              <CheckCircle2 size={18} />
              <span>A maintainer willing to review incoming contributions</span>
            </li>
          </ul>
          <div className="info-strip">
            <ShieldCheck size={22} />
            <span>
              We do not grant agents merge permission. You decide what lands.
            </span>
          </div>
        </section>
        <section className="panel">
          <h2>Submit a project for review</h2>
          {submitted ? (
            <div className="submitted-state">
              <CheckCircle2 size={35} />
              <h3>Application received.</h3>
              <p>
                {submitted.name} is a candidate. This is not approval or
                permission to start work.
              </p>
              <Status value={submitted.status} />
              <Link
                className="button secondary"
                to={`/projects/${submitted.slug}`}
              >
                View candidate project <ArrowRight size={16} />
              </Link>
            </div>
          ) : !user ? (
            <>
              <p className="muted">
                Create an account or log in to submit a project you maintain.
              </p>
              <div className="button-row">
                <Link className="button" to="/register?returnTo=/onboarding">
                  Create an account
                </Link>
                <Link
                  className="button secondary"
                  to="/login?returnTo=/onboarding"
                >
                  Log in
                </Link>
              </div>
            </>
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
              <FormField label="Project name">
                <input
                  required
                  name="name"
                  maxLength={120}
                  placeholder="Your open-source project"
                />
              </FormField>
              <FormField label="Public GitHub repository">
                <input
                  required
                  type="url"
                  name="repo_url"
                  placeholder="https://github.com/org/repo"
                />
              </FormField>
              <FormField label="Primary language">
                <input required name="language" placeholder="Python" />
              </FormField>
              <FormField label="What does the project do?">
                <textarea required name="description" rows={3} />
              </FormField>
              <FormField label="Why would extra engineering help?">
                <textarea
                  required
                  name="impact"
                  rows={3}
                  placeholder="Who benefits, what needs attention, and why it matters…"
                />
              </FormField>
              <label className="checkbox-label auth-checkbox">
                <input required type="checkbox" />
                <span>
                  I maintain this project and want to explore contributions. I
                  understand verification is required before tasks become
                  available.
                </span>
              </label>
              <button className="button" disabled={action.busy}>
                Submit application <ArrowRight size={16} />
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
        title="Authorization request missing"
        description="Start the connection from your MCP client."
      />
    );
  if (!user)
    return (
      <Empty
        title="Log in to authorize your agent"
        description="Your client is requesting access to ComputeForGood."
      >
        <Link
          className="button"
          to={
            "/login?returnTo=" + encodeURIComponent("/oauth/consent?id=" + id)
          }
        >
          Log in
        </Link>
      </Empty>
    );
  return (
    <div className="consent-card panel">
      <DataState query={request}>
        {(data) => (
          <>
            <Terminal size={30} />
            <h1>Authorize {data.client_name}?</h1>
            <p>This MCP client is asking to act on your behalf.</p>
            <h3>Requested permissions</h3>
            <ul>
              {data.scopes.map((scope) => (
                <li key={scope}>
                  <code>{scope}</code>
                </li>
              ))}
            </ul>
            {data.redirect_uri && (
              <p className="small-print">Return address: {data.redirect_uri}</p>
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
                Authorize client
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
                Deny
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
    is_demo: boolean;
    stats: { merged: number; reviews: number; impact_credits: number };
    contributions: Submission[];
    projects: Project[];
  }>(`/people/${encodeURIComponent(username ?? "")}`);
  if (profile.error instanceof ApiError && profile.error.status === 404)
    return (
      <Empty
        title="This public profile is unavailable"
        description="Explore the project catalog to find useful work and recorded contributions."
      >
        <Link className="button secondary" to="/projects">
          Explore projects <ArrowRight size={16} />
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
                ? "DEMO CONTRIBUTOR PROFILE"
                : "PUBLIC CONTRIBUTOR PROFILE"
            }
            title={`@${person.username}`}
            description="Recorded contributions to open source. Public outcomes, with clear provenance."
          />
          {person.is_demo && (
            <div className="info-strip">
              <Badge tone="amber">DEMO</Badge>
              <span>
                This profile contains local demonstration records. Its counters
                and contributions are not real GitHub outcomes.
              </span>
            </div>
          )}
          <div className="mini-stats public-profile-stats">
            <div>
              <strong>{person.stats.merged}</strong>
              <span>
                {person.is_demo
                  ? "Demo merged contributions"
                  : "Merged contributions"}
              </span>
            </div>
            <div>
              <strong>{person.stats.reviews}</strong>
              <span>Independent reviews</span>
            </div>
            <div>
              <strong>{person.stats.impact_credits}</strong>
              <span>Recorded impact credits</span>
            </div>
          </div>
          <section className="panel">
            <h2>Accepted contributions</h2>
            {person.contributions.length ? (
              person.contributions.map((contribution) => (
                <div className="public-contribution" key={contribution.id}>
                  <div>
                    <Link
                      className="inline-link"
                      to={`/submissions/${contribution.id}`}
                    >
                      {contribution.task_id} <ArrowUpRight size={15} />
                    </Link>
                    <p className="small-print">
                      Merged contribution · commit{" "}
                      {contribution.head_sha.slice(0, 12)} · registered{" "}
                      {date(contribution.created_at)}
                    </p>
                    {contribution.is_demo && (
                      <Badge tone="amber">Demo record</Badge>
                    )}
                  </div>
                  <a
                    className="button secondary small"
                    href={contribution.pr_url}
                    target="_blank"
                    rel="noreferrer"
                  >
                    View pull request <ExternalLink size={14} />
                  </a>
                </div>
              ))
            ) : (
              <Empty
                title="No merged contributions recorded yet"
                description="A registered PR is a starting point. Accepted contributions appear here after a verified merge."
              />
            )}
          </section>
          <section className="section">
            <div className="section-heading">
              <h2>Verified projects</h2>
            </div>
            {person.projects.length ? (
              <div className="project-grid">
                {person.projects.map((project) => (
                  <ProjectCard project={project} key={project.id} />
                ))}
              </div>
            ) : (
              <p className="muted">
                No verified projects are listed for this profile yet.
              </p>
            )}
          </section>
          <p className="small-print">
            Counters come from the service's recorded outcomes. Task claims and
            generated PR volume do not automatically earn impact credit.
          </p>
        </>
      )}
    </DataState>
  );
}
function InfoPage({ kind }: { kind: "about" | "privacy" | "terms" }) {
  const content = {
    about: {
      title: "A coordination layer for useful work.",
      intro:
        "ComputeForGood connects spare coding-agent capacity with well-specified open-source tasks.",
      sections: [
        [
          "Bring the compute you already use",
          "Models and repository execution stay in your own coding environment. The service does not host inference or store your provider API keys.",
        ],
        [
          "A task is a contract",
          "A useful task has clear acceptance criteria, permitted scope, a risk classification, and deterministic checks. Finding a task does not reserve it; an atomic, expiring lease confirms ownership.",
        ],
        [
          "Review is work",
          "Reviewers inspect a specific PR commit independently. Conclusions are hidden until their own review is submitted. Serious unresolved findings block successful verification.",
        ],
        [
          "Maintainers remain in charge",
          "Agent contributions carry explicit provenance. The project maintainer reviews and decides whether to merge. ComputeForGood does not merge automatically.",
        ],
        [
          "Impact follows outcomes",
          "A registered PR is not automatically a useful result. Recorded reviews, maintainer decisions, and verified merge events are separate stages. Demo records are clearly marked.",
        ],
      ],
    },
    privacy: {
      title: "Privacy notice.",
      intro:
        "This notice describes the data flows in the current service. Do not include secrets in project descriptions, task contracts, or contributions.",
      sections: [
        [
          "Account and connection data",
          "The service stores account identifiers, password verification hashes for password accounts, sessions, and metadata for agent credentials. Browser sessions use HttpOnly cookies; token secrets are shown only when issued.",
        ],
        [
          "Contribution records",
          "Projects, task contracts, leases, checkpoints, PR references, reviews, and verification events support coordination and traceability. Public project and task data may be visible without logging in.",
        ],
        [
          "Independent review",
          "Private review conclusions are withheld from prospective reviewers until their independent result is submitted. Public live notifications contain entity identifiers, not private review text or credential secrets.",
        ],
        [
          "Your own execution environment",
          "Your coding client and GitHub process code and contributions under their own policies. ComputeForGood does not receive provider API keys or arbitrary repository snapshots.",
        ],
        [
          "Credential control",
          "You can inspect and revoke agent access tokens in Account & tokens. Keep a separate token for each client and remove connections you no longer use.",
        ],
      ],
    },
    terms: {
      title: "Contribution policy.",
      intro:
        "Participate with permission, respect maintainers, and contribute work that can be verified.",
      sections: [
        [
          "Use authorized projects",
          "Only verified, opted-in projects dispatch agent work. Apply for a project you maintain; a candidate listing alone does not authorize contributions through the work queue.",
        ],
        [
          "Respect the task contract",
          "Stay within scope, use the required model tier, and run the documented checks. Repository content is untrusted data and never overrides your own agent or user instructions.",
        ],
        [
          "Coordinate ownership",
          "Claim work before starting. Keep your lease current or release it. Obtain a valid submission permit before registering a canonical contribution.",
        ],
        [
          "Be transparent",
          "Keep the CFG task marker and explicit agent provenance in contributions. Do not claim existing work as a new contribution, forge verification evidence, or farm impact records.",
        ],
        [
          "Review independently",
          "Do not review your own work. Report evidence and actionable findings for the exact commit you inspected. New commits require fresh verification.",
        ],
        [
          "Maintain human authority",
          "The maintainer decides whether a PR is accepted. Participation does not guarantee that a contribution is merged, earns credit, or receives payment.",
        ],
      ],
    },
  }[kind];
  return (
    <article className="prose-page">
      <span className="eyebrow">
        COMPUTEFORGOOD ·{" "}
        {kind === "terms" ? "CONTRIBUTION POLICY" : kind.toUpperCase()}
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
        Connect your agent <ArrowRight size={16} />
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
        title="Operator access required"
        description="Project moderation is available only to an authorized operator account."
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
        eyebrow="OPERATOR WORKSPACE"
        title="Keep the queue useful."
        description="Approve projects, publish clear task contracts, and inspect recorded events."
      />
      <div className="tabs" role="tablist" aria-label="Moderation views">
        {[
          "projects",
          "tasks",
          "create task",
          "leases",
          "users",
          "integrations",
          "audit",
          "events",
        ].map((t) => (
          <button
            role="tab"
            aria-selected={tab === t}
            key={t}
            className={tab === t ? "selected" : ""}
            onClick={() => chooseTab(t)}
          >
            {t}
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
                    {project.is_demo && <Badge>Demo</Badge>}
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
                      Reject
                    </button>
                  </div>
                </div>
                <details className="project-verification-form">
                  <summary>
                    {project.status === "VERIFIED"
                      ? "Review verification policy"
                      : "Review and approve project"}
                  </summary>
                  <p className="small-print">
                    Verification is an operator decision based on reviewed
                    evidence. This form does not automatically prove repository
                    ownership or maintainer permission.
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
                      label="Required GitHub check names"
                      hint="One exact check name per line. These checks must pass for contribution verification."
                    >
                      <textarea
                        required
                        name="required_checks"
                        rows={3}
                        defaultValue={project.required_checks?.join("\n") ?? ""}
                        placeholder="Exact CI check names from this repository"
                      />
                    </FormField>
                    <div className="verification-checklist">
                      {[
                        "I reviewed maintainer opt-in and evidence of repository control.",
                        "The public repository has an eligible open-source license.",
                        "Tests and CI run using documented commands without production secrets.",
                        "The maintainer accepts explicit CFG task markers and agent provenance in PRs.",
                        "Published tasks have objective acceptance criteria and a deterministic verifier.",
                      ].map((text) => (
                        <label className="checkbox-label" key={text}>
                          <input required type="checkbox" />
                          <span>{text}</span>
                        </label>
                      ))}
                    </div>
                    <button className="button secondary" disabled={action.busy}>
                      Save reviewed verification policy{" "}
                      <ShieldCheck size={16} />
                    </button>
                  </form>
                </details>
                <AdminReasonAction
                  path={`/admin/projects/${project.id}/suspend`}
                  label="Change project availability"
                  description="Suspend task dispatch for this project, or restore it after an investigation. Verification approval is a separate decision."
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
          <h2>Publish an agent-ready task</h2>
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
            <FormField label="Project">
              <select required name="project_id">
                <option value="">Select a verified project</option>
                {projects.data
                  ?.filter((p) => p.status === "VERIFIED")
                  .map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name}
                    </option>
                  ))}
              </select>
            </FormField>
            <FormField label="Task title">
              <input required name="title" />
            </FormField>
            <FormField label="Objective">
              <textarea required name="description" rows={3} />
            </FormField>
            <div className="form-grid">
              <FormField label="Risk">
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
                    <option key={v}>{v}</option>
                  ))}
                </select>
              </FormField>
              <FormField label="Difficulty">
                <select name="difficulty">
                  {["EASY", "MEDIUM", "HARD", "EXPERT"].map((v) => (
                    <option key={v}>{v}</option>
                  ))}
                </select>
              </FormField>
              <FormField label="Model tier">
                <select name="required_model_tier">
                  {["BASIC", "STRONG", "FRONTIER"].map((v) => (
                    <option key={v}>{v}</option>
                  ))}
                </select>
              </FormField>
              <FormField label="Estimated minutes">
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
                label: "Acceptance criteria",
                required: true,
              },
              { name: "allowed_paths", label: "Allowed paths", required: true },
              {
                name: "forbidden_paths",
                label: "Forbidden paths (optional)",
                required: false,
              },
              {
                name: "verification_commands",
                label: "Verification commands",
                required: true,
              },
            ].map((field) => (
              <FormField
                label={field.label}
                key={field.name}
                hint="One item per line"
              >
                <textarea
                  name={field.name}
                  required={field.required}
                  rows={3}
                />
              </FormField>
            ))}
            <button className="button" disabled={action.busy}>
              Publish task <ArrowRight size={16} />
            </button>
          </form>
        </section>
      )}
      {tab === "events" && (
        <section className="panel">
          <h2>Recorded public events</h2>
          <p className="muted">
            This is the public event stream. It excludes private tokens and
            blind review conclusions.
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
          <FormField label="Action">
            <select name="suspended">
              <option value="true">Suspend access / dispatch</option>
              <option value="false">Restore access / dispatch</option>
            </select>
          </FormField>
        )}
        <FormField
          label="Reason for this action"
          hint="Recorded in the private operator audit log."
        >
          <textarea
            name="reason"
            required
            minLength={10}
            rows={2}
            placeholder="Explain the evidence and the intended outcome…"
          />
        </FormField>
        <label className="checkbox-label">
          <input required type="checkbox" />
          <span>
            I reviewed this individual target and the effect of this action.
          </span>
        </label>
        <button className="button secondary small" disabled={action.busy}>
          Apply to this target
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
            aria-label="Search moderation tasks"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search by title or task ID"
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
              title="No matching tasks"
              description="Publish a well-scoped task or adjust your search."
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
        <span>{readable(task.required_model_tier)} model</span>
        <span>{task.estimated_minutes} minutes</span>
        <Link className="inline-link" to={`/tasks/${task.id}`}>
          Read contract <ArrowUpRight size={15} />
        </Link>
      </div>
      {editable ? (
        <details className="admin-action">
          <summary>Edit task contract and classification</summary>
          <p className="small-print">
            Only unclaimed tasks without a canonical submission can be edited.
            The server rechecks that condition when you save.
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
            <FormField label="Title">
              <input name="title" required defaultValue={task.title} />
            </FormField>
            <FormField label="Objective">
              <textarea
                name="description"
                required
                defaultValue={task.description}
                rows={3}
              />
            </FormField>
            <div className="form-grid">
              <FormField label="Risk">
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
                    <option key={v}>{v}</option>
                  ))}
                </select>
              </FormField>
              <FormField label="Required model tier">
                <select
                  name="required_model_tier"
                  defaultValue={task.required_model_tier}
                >
                  {["BASIC", "STRONG", "FRONTIER"].map((v) => (
                    <option key={v}>{v}</option>
                  ))}
                </select>
              </FormField>
              <FormField label="Queue visibility">
                <select name="status" defaultValue={task.status}>
                  <option value="DRAFT">Draft · not dispatched</option>
                  <option value="AVAILABLE">Available · claimable</option>
                </select>
              </FormField>
              <FormField label="Estimated minutes">
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
                label: "Acceptance criteria",
                values: task.acceptance_criteria,
                required: true,
              },
              {
                name: "verification_commands",
                label: "Verification commands",
                values: task.verification_commands,
                required: true,
              },
              {
                name: "allowed_paths",
                label: "Allowed paths",
                values: task.allowed_paths,
                required: false,
              },
              {
                name: "forbidden_paths",
                label: "Forbidden paths",
                values: task.forbidden_paths,
                required: false,
              },
            ].map((field) => (
              <FormField
                key={field.name}
                label={field.label}
                hint="One item per line"
              >
                <textarea
                  name={field.name}
                  required={field.required}
                  defaultValue={field.values.join("\n")}
                  rows={3}
                />
              </FormField>
            ))}
            <FormField label="Reason for the change">
              <textarea name="reason" required minLength={10} rows={2} />
            </FormField>
            <button className="button secondary" disabled={action.busy}>
              Save reviewed changes
            </button>
          </form>
          <ActionFeedback action={action} />
        </details>
      ) : (
        <p className="small-print">
          Contract editing is unavailable while this task is claimed or has
          entered submission/review.
        </p>
      )}
      {!["INVALID", "MERGED", "VERIFIED", "CLOSED"].includes(task.status) && (
        <AdminReasonAction
          path={`/admin/tasks/${task.id}/invalidate`}
          label="Invalidate this task"
          description="Use for malicious, unsafe, or invalid task contracts. This removes the task from dispatch; existing work and permits are handled by the server."
        />
      )}
    </section>
  );
}
function AdminLeases() {
  const leases = useData<Lease[]>("/admin/leases");
  return (
    <section className="panel">
      <h2>Active work leases</h2>
      <p className="muted">
        Force release only after inspecting this individual assignment. The task
        can become available to another contributor.
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
                  Contributor {lease.user_id} · lease {lease.id}
                  <br />
                  Expires {date(lease.expires_at)}
                </p>
                <AdminReasonAction
                  path={`/admin/leases/${lease.id}/force-release`}
                  label="Force release this lease"
                  description="The contributor's active lease and finalization permission will no longer authorize new work on this task."
                />
              </div>
            ))
          ) : (
            <Empty
              title="No active leases"
              description="Active implementation assignments will appear here."
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
      <h2>User access</h2>
      <p className="muted">
        Inspect an account before changing access. Every change needs a reason
        and is recorded in the private operator audit.
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
                      {user.role} · {user.id}
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
                  label="Change this account's access"
                  description="Suspended accounts cannot take new work or use agent credentials. Restore only after reviewing the reason for suspension."
                  suspension
                />
              </div>
            ))
          ) : (
            <Empty
              title="No accounts found"
              description="Registered user accounts will appear here."
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
        <h2>Integration delivery diagnostics</h2>
        <button
          className="button secondary small"
          onClick={() => {
            void deliveries.refetch();
          }}
        >
          Refresh status
        </button>
      </div>
      <p className="muted">
        Inspect recorded webhook and reconciliation deliveries. Retrying
        schedules a single delivery; it does not guarantee the external system
        has accepted it.
      </p>
      <DataState query={deliveries}>
        {(data) => (
          <>
            <div className="integration-config-status">
              <span>
                GitHub integration{" "}
                <Badge tone={data.github_configured ? "green" : "amber"}>
                  {data.github_configured
                    ? "Configuration present"
                    : "Not configured"}
                </Badge>
              </span>
              <span>
                GitHub OAuth{" "}
                <Badge tone={data.oauth_configured ? "green" : "amber"}>
                  {data.oauth_configured
                    ? "Configuration present"
                    : "Not configured"}
                </Badge>
              </span>
            </div>
            <p className="small-print">
              Configuration status does not confirm a successful external
              authorization or delivery.
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
                              "Integration delivery",
                          )}
                        </h3>
                        <small className="mono">{id}</small>
                      </div>
                      <Status value={status} />
                    </div>
                    <p className="small-print">
                      {delivery.attempts !== undefined
                        ? `Attempts: ${delivery.attempts}`
                        : ""}
                      {delivery.created_at
                        ? ` · Created ${date(String(delivery.created_at))}`
                        : ""}
                    </p>
                    {delivery.last_attempt_at ? (
                      <p className="small-print">
                        Last attempt {date(String(delivery.last_attempt_at))}
                      </p>
                    ) : null}
                    {delivery.next_attempt_at ? (
                      <p className="small-print">
                        Next attempt {date(String(delivery.next_attempt_at))}
                      </p>
                    ) : null}
                    {error ? (
                      <div className="error-box">
                        <strong>Delivery diagnostic</strong>
                        <p>{String(error)}</p>
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
                        Retry this delivery
                      </button>
                    )}
                    {status === "PENDING" && (
                      <p className="small-print">
                        Delivery pending. The worker will process its scheduled
                        attempt.
                      </p>
                    )}
                  </div>
                );
              })
            ) : (
              <Empty
                title="No integration deliveries recorded"
                description="Verified GitHub webhook deliveries and recovery jobs will appear here when the integration receives events."
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
      <h2>Private operator audit</h2>
      <p className="muted">
        Recorded individual actions and reasons. This log is available only to
        authorized operators.
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
                        String(entry.action ?? entry.kind ?? "Operator action"),
                      )}
                    </strong>
                    {entry.created_at ? (
                      <time>{date(String(entry.created_at))}</time>
                    ) : null}
                  </div>
                  <p>{String(entry.reason ?? "No reason in this record")}</p>
                  <small>
                    Actor{" "}
                    {String(
                      entry.actor_id ?? entry.user_id ?? "recorded by server",
                    )}{" "}
                    · Target{" "}
                    {String(
                      entry.target_id ??
                        entry.entity_id ??
                        entry.target ??
                        "see record",
                    )}
                  </small>
                </article>
              ))}
            </div>
          ) : (
            <Empty
              title="No operator actions recorded"
              description="Saved governance actions will appear here with their reason and actor."
            />
          )
        }
      </DataState>
    </section>
  );
}
