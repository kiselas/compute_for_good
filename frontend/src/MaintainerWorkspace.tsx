import { useState, type FormEvent, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, CheckCircle2, Flag, Layers3, Plus, ShieldCheck } from "lucide-react";
import { api, ApiError, type Project, type Task, type Submission } from "./api";
import { t, useLocale, formatNumber } from "./i18n";
import SprintBuilder from "./SprintBuilder";

interface Goal {
  id: string; title: string; description: string; priority: number;
  status: string; version: number;
}
interface Improvement {
  id: string; goal_id: string | null; title: string; problem: string; outcome: string;
  acceptance_criteria: string[]; in_scope: string; out_of_scope: string;
  kind: string; priority: number; status: string; version: number;
}
interface PlannedTask extends Task { version: number; improvement_id: string | null; contract_locked?: boolean }
interface Plan { project: Project; goals: Goal[]; improvements: Improvement[]; tasks: PlannedTask[]; submissions: Submission[] }
type Tab = "goals" | "improvements" | "tasks" | "results";
type RunAction = (path: string, body: unknown, method?: string, onSuccess?: (result: unknown) => void) => Promise<void>;
const labels: Record<string, string> = {
  ACTIVE: "Active", PAUSED: "Paused", COMPLETED: "Completed", PROPOSED: "Proposed",
  APPROVED: "Approved", IN_PROGRESS: "In progress", ACCEPTANCE: "Acceptance", DONE: "Done",
  REJECTED: "Rejected", FEATURE: "Feature", BUG: "Bug fix", DOCS: "Documentation", TESTS: "Tests",
  PERFORMANCE: "Performance", DRAFT: "Draft", AVAILABLE: "Available", CLAIMED: "Claimed",
  SUBMITTED: "Submitted", REVIEWING: "Reviewing", REVIEW_PASSED: "Review passed", MERGED: "Merged",
  INVALID: "Invalid", CLOSED: "Closed", CANDIDATE: "Candidate", VERIFIED: "Verified", SUSPENDED: "Suspended",
  LOW: "Low", NORMAL: "Normal", HIGH: "High", CRITICAL: "Critical", BASIC: "Basic", STRONG: "Strong",
  FRONTIER: "Frontier", EASY: "Easy", MEDIUM: "Medium", HARD: "Hard", EXPERT: "Expert",
};
const readable = (value: string) => t(labels[value] ?? value.replaceAll("_", " "));
const lines = (value: FormDataEntryValue | null) => String(value ?? "").split(/\r?\n/).map(line => line.trim()).filter(Boolean);
const text = (data: FormData, key: string) => String(data.get(key) ?? "").trim();
function Field({ label, name, value, multiline = false, required = true, hint, min = 3, max = 5000 }: {
  label: string; name: string; value?: string; multiline?: boolean; required?: boolean;
  hint?: string; min?: number; max?: number;
}) {
  return <label className="maintainer-field"><span>{t(label)}</span>
    {multiline ? <textarea name={name} defaultValue={value} required={required} minLength={required ? min : undefined} maxLength={max} rows={4} />
      : <input name={name} defaultValue={value} required={required} minLength={required ? min : undefined} maxLength={max} />}
    {hint && <small>{t(hint)}</small>}
  </label>;
}
function Priority({ value = 3 }: { value?: number }) {
  return <label className="maintainer-field"><span>{t("Priority")}</span><select name="priority" defaultValue={value}>
    <option value="1">{t("1 — Essential")}</option><option value="2">{t("2 — Important")}</option>
    <option value="3">{t("3 — Normal priority")}</option><option value="4">{t("4 — Later")}</option>
    <option value="5">{t("5 — Optional")}</option>
  </select></label>;
}
function Collapsible({ title, children, icon = true }: { title: string; children: ReactNode; icon?: boolean }) {
  return <details className="maintainer-editor"><summary>{icon && <Plus size={16} />}{t(title)}</summary>{children}</details>;
}
function Save({ busy, label = "Save draft" }: { busy: boolean; label?: string }) {
  return <button className="button" disabled={busy} type="submit">{t(busy ? "Saving…" : label)}</button>;
}
function VersionConflict({ stale, reload }: { stale: boolean; reload: () => void }) {
  return stale ? <div className="maintainer-conflict" role="alert"><p>{t("This item changed while you were editing. Your draft is preserved. Load the latest version before saving; this replaces your draft.")}</p><button type="button" className="button small secondary" onClick={reload}>{t("Load latest version")}</button></div> : null;
}
function ErrorNotice({ error, retry }: { error: unknown; retry?: () => void }) {
  return <div className="error-box" role="alert"><p>{t(error instanceof Error ? error.message : "Unable to load project plan", { status: error instanceof ApiError ? error.status : 500 })}</p>
    {retry && <button className="button small secondary" onClick={retry}>{t("Try again")}</button>}
  </div>;
}

export default function MaintainerWorkspace({ projectId, user }: { projectId?: string; user?: { id: string; role: string } | null }) {
  useLocale();
  const cache = useQueryClient();
  const [tab, setTab] = useState<Tab>("goals");
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<unknown>(null);
  const [notice, setNotice] = useState(false);
  const list = useQuery({ queryKey: ["maintainer", "projects", user?.id], queryFn: () => api<Project[]>("/maintainer/projects"), enabled: !!user && !projectId });
  const plan = useQuery({ queryKey: ["maintainer", projectId, user?.id], queryFn: () => api<Plan>(`/maintainer/projects/${projectId}/plan`), enabled: !!user && !!projectId });
  const run: RunAction = async (path, body, method, onSuccess) => {
    setBusy(true); setActionError(null); setNotice(false);
    try {
      const result = await api(path, body, method);
      await cache.invalidateQueries();
      onSuccess?.(result); setNotice(true);
    } catch (error) {
      setActionError(error);
      if (error instanceof ApiError && error.status === 409) await cache.invalidateQueries({ queryKey: ["maintainer"] });
    } finally { setBusy(false); }
  };
  if (!user) return <section className="panel maintainer-welcome"><Flag size={28} /><h1>{t("Plan your project's next chapter")}</h1>
    <p>{t("Set the direction, approve improvements, and publish clear tasks for contributors.")}</p>
    <Link className="button" to="/login?returnTo=/maintainer">{t("Sign in to manage projects")}</Link>
  </section>;
  if (!projectId) return <div className="maintainer-workspace"><div className="page-heading"><div><p className="eyebrow">{t("Maintainer workspace")}</p>
    <h1>{t("Your projects")}</h1><p>{t("Turn your priorities into reviewed open-source contributions.")}</p></div>
    <Link className="button" to="/onboarding">{t("Submit a repository")}</Link></div>
    {list.isPending && <p role="status">{t("Loading your projects…")}</p>}
    {list.isError && <ErrorNotice error={list.error} retry={() => void list.refetch()} />}
    {list.data?.length === 0 && <section className="panel maintainer-empty"><Layers3 size={26} /><h2>{t("Start with a repository")}</h2>
      <p>{t("Submit a repository you maintain. You can prepare its roadmap while the operator checks ownership and readiness.")}</p>
      <Link className="button" to="/onboarding">{t("Submit a repository")}</Link></section>}
    <div className="maintainer-projects">{list.data?.map(project => <Link className="panel maintainer-project" key={project.id} to={`/maintainer/projects/${project.id}`}>
      <div className="maintainer-card-heading"><h2>{project.name}</h2><span className="badge">{readable(project.status)}</span></div><p>{project.description}</p>
      <div className="maintainer-card-footer"><span>{project.is_demo ? t("Readiness: {score}/100", { score: formatNumber(project.readiness_score) }) : t("Project scoring is not available yet")}</span><span>{t("Open roadmap")} <ArrowRight size={16} /></span></div>
    </Link>)}</div></div>;
  if (plan.isPending) return <p role="status">{t("Loading project plan…")}</p>;
  if (plan.isError) return <ErrorNotice error={plan.error} retry={() => void plan.refetch()} />;
  if (!plan.data) return null;
  const data = plan.data;
  const contributionPath = (task: Task) => {
    const submission = data.submissions.find(item => item.task_id === task.id);
    return submission ? `/submissions/${submission.id}` : `/tasks/${task.id}`;
  };
  const base = `/maintainer/projects/${data.project.id}`;
  const ready = data.project.status === "VERIFIED";
  return <div className="maintainer-workspace">
    <Link className="back-link" to="/maintainer">{t("All your projects")}</Link>
    <div className="page-heading"><div><p className="eyebrow">{t("Maintainer workspace")}</p><h1>{data.project.name}</h1>
      <p>{t("You decide the direction. Contributors work against the approved task contract.")}</p></div>
      <a className="button secondary" href={data.project.repository_url} target="_blank" rel="noreferrer">{t("View repository")}</a></div>
    <section className={`maintainer-readiness ${ready ? "ready" : "pending"}`}><ShieldCheck size={22} /><div>
      <strong>{t(ready ? "Repository verified" : "Prepare the roadmap before publication")}</strong>
      <p>{t(ready ? "Publication still checks the project's readiness, task scope, and approved improvement." : "Your plan and drafts are private working material. An operator must verify repository ownership and readiness before tasks can be published.")}</p>
    </div><span className="badge">{readable(data.project.status)}</span></section>
    <SprintBuilder projectId={data.project.id} tasks={data.tasks} />
    <div className="maintainer-tabs" role="tablist" aria-label={t("Project planning views")}>
      {([ ["goals", "Goals", data.goals.length], ["improvements", "Improvements", data.improvements.length], ["tasks", "Tasks", data.tasks.length], ["results", "Results", data.tasks.filter(task => task.status === "MERGED").length] ] as const).map(([id, title, count]) =>
        <button key={id} type="button" role="tab" id={`maintainer-tab-${id}`} aria-selected={tab === id} aria-controls={`maintainer-panel-${id}`} tabIndex={tab === id ? 0 : -1} className={tab === id ? "active" : ""} onClick={() => setTab(id)} onKeyDown={event => {
          const order: Tab[] = ["goals", "improvements", "tasks", "results"];
          if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
          event.preventDefault();
          const next = event.key === "Home" ? 0 : event.key === "End" ? 3 : (order.indexOf(tab) + (event.key === "ArrowRight" ? 1 : 3)) % 4;
          setTab(order[next]);
          event.currentTarget.parentElement?.querySelector<HTMLButtonElement>(`#maintainer-tab-${order[next]}`)?.focus();
        }}>{t(title)} <span>{formatNumber(count)}</span></button>)}
    </div>
    {actionError != null && <ErrorNotice error={actionError} />}
    {notice && <p className="maintainer-success" role="status"><CheckCircle2 size={16} />{t("Project plan saved")}</p>}
    <section role="tabpanel" id={`maintainer-panel-${tab}`} aria-labelledby={`maintainer-tab-${tab}`}>
      {tab === "goals" && <><div className="maintainer-section-intro"><h2>{t("What matters next")}</h2><p>{t("Describe the outcomes you want. Keep the first roadmap focused on a few achievable goals.")}</p></div>
        <GoalForm base={base} busy={busy} run={run} />
        <div className="maintainer-cards">{data.goals.map(goal => <section className="panel maintainer-card" key={goal.id}><div className="maintainer-card-heading"><h3>{goal.title}</h3><span className="badge">{readable(goal.status)}</span></div><p className="maintainer-user-content">{goal.description}</p>
          <span className="maintainer-meta">{t("Priority {priority}", { priority: formatNumber(goal.priority) })}</span>
          <div className="button-row">{goal.status !== "COMPLETED" && <button className="button small secondary" disabled={busy} onClick={() => void run(`${base}/goals/${goal.id}`, { version: goal.version, status: goal.status === "ACTIVE" ? "PAUSED" : "ACTIVE" }, "PATCH")}>{t(goal.status === "ACTIVE" ? "Pause goal" : "Resume goal")}</button>}
            {goal.status !== "COMPLETED" && <button className="button small secondary" disabled={busy} onClick={() => void run(`${base}/goals/${goal.id}`, { version: goal.version, status: "COMPLETED" }, "PATCH")}>{t("Complete goal")}</button>}</div>
          {goal.status !== "COMPLETED" && <GoalForm base={base} busy={busy} run={run} goal={goal} priorityOnly={data.tasks.some(task => task.contract_locked && data.improvements.find(item => item.id === task.improvement_id)?.goal_id === goal.id)} />}
        </section>)}</div>{!data.goals.length && <p className="maintainer-empty-copy">{t("No goals yet. Start with the most important outcome for this repository.")}</p>}
        <p className="maintainer-help">{t("Pausing a goal stops new work from being dispatched. Active work keeps its original contract.")}</p>
      </>}
      {tab === "improvements" && <><div className="maintainer-section-intro"><h2>{t("From goals to improvements")}</h2><p>{t("Describe the problem, expected result, and acceptance criteria. Approve the proposal before publishing its tasks.")}</p></div>
        <ImprovementForm base={base} goals={data.goals} busy={busy} run={run} />
        <div className="maintainer-cards">{data.improvements.map(item => <section className="panel maintainer-card" key={item.id}>
          <div className="maintainer-card-heading"><h3>{item.title}</h3><span className="badge">{readable(item.status)}</span></div>
          <div className="maintainer-meta">{readable(item.kind)} · {t("Priority {priority}", { priority: formatNumber(item.priority) })}{item.goal_id && <> · {data.goals.find(goal => goal.id === item.goal_id)?.title}</>}</div>
          <h4>{t("Problem to solve")}</h4><p className="maintainer-user-content">{item.problem}</p><h4>{t("Expected outcome")}</h4><p className="maintainer-user-content">{item.outcome}</p>
          <h4>{t("Acceptance criteria")}</h4><ul>{item.acceptance_criteria.map((criterion, index) => <li key={index}>{criterion}</li>)}</ul>
          <div className="maintainer-scope"><div><h4>{t("In scope")}</h4><p className="maintainer-user-content">{item.in_scope || t("Not specified")}</p></div><div><h4>{t("Out of scope")}</h4><p className="maintainer-user-content">{item.out_of_scope || t("Not specified")}</p></div></div>
          <div className="button-row">
            {item.status === "PROPOSED" && <button className="button small" disabled={busy} onClick={() => void run(`${base}/improvements/${item.id}`, { version: item.version, status: "APPROVED" }, "PATCH")}>{t("Approve improvement")}</button>}
            {item.status === "APPROVED" && <button className="button small secondary" disabled={busy} onClick={() => void run(`${base}/improvements/${item.id}`, { version: item.version, status: "PROPOSED" }, "PATCH")}>{t("Return to proposal")}</button>}
            {item.status === "IN_PROGRESS" && <button className="button small secondary" disabled={busy} onClick={() => void run(`${base}/improvements/${item.id}`, { version: item.version, status: "ACCEPTANCE" }, "PATCH")}>{t("Move to acceptance")}</button>}
            {item.status === "ACCEPTANCE" && <button className="button small secondary" disabled={busy} onClick={() => void run(`${base}/improvements/${item.id}`, { version: item.version, status: "IN_PROGRESS" }, "PATCH")}>{t("Continue implementation")}</button>}
            {item.status === "ACCEPTANCE" && <button className="button small" disabled={busy} onClick={() => void run(`${base}/improvements/${item.id}`, { version: item.version, status: "DONE" }, "PATCH")}>{t("Accept completed improvement")}</button>}
            {!["DONE", "REJECTED"].includes(item.status) && <button className="button small secondary" disabled={busy} onClick={() => void run(`${base}/improvements/${item.id}`, { version: item.version, status: "REJECTED" }, "PATCH")}>{t("Reject and stop new work")}</button>}
          </div>
          {!["DONE", "REJECTED"].includes(item.status) && <ImprovementForm base={base} goals={data.goals} busy={busy} run={run} improvement={item} priorityOnly={data.tasks.some(task => task.improvement_id === item.id && task.contract_locked)} />}
          {data.tasks.some(task => task.improvement_id === item.id && task.contract_locked) && <p className="maintainer-help">{t("Improvement requirements are fixed because related work has started. You can still change its status.")}</p>}
          {["PROPOSED", "APPROVED", "IN_PROGRESS"].includes(item.status) && <TaskForm base={base} improvementId={item.id} busy={busy} run={run} />}
        </section>)}</div>{!data.improvements.length && <p className="maintainer-empty-copy">{t("No improvements yet. Create a proposal or ask your connected agent to prepare one for your review.")}</p>}
        <p className="maintainer-help">{t("Agents can prepare proposals and task drafts through MCP. Approval and publication remain your decisions.")} <Link to="/connect">{t("Connect an agent")}</Link></p>
      </>}
      {tab === "tasks" && <><div className="maintainer-section-intro"><h2>{t("Clear tasks, explicit publication")}</h2><p>{t("Task drafts stay unavailable to contributors until you publish them. Once work has started, the task contract cannot be edited.")}</p></div>
        <div className="maintainer-cards">{data.tasks.map(task => {
          const improvement = data.improvements.find(item => item.id === task.improvement_id);
          const goal = data.goals.find(item => item.id === improvement?.goal_id);
          const publishable = ready && !!improvement && ["APPROVED", "IN_PROGRESS"].includes(improvement.status) && (!goal || goal.status === "ACTIVE");
          return <section className="panel maintainer-card" key={task.id}><div className="maintainer-card-heading"><h3>{task.title}</h3><span className="badge">{readable(task.status)}</span></div>
            <p className="maintainer-meta">{improvement?.title ?? t("Unlinked task")} · {readable(task.risk)} · {t("Model tier: {tier}", { tier: readable(task.required_model_tier) })} · {t("{minutes} minutes", { minutes: formatNumber(task.estimated_minutes) })}</p>
            <p className="maintainer-user-content">{task.description}</p><h4>{t("Acceptance criteria")}</h4><ul>{task.acceptance_criteria.map((criterion, index) => <li key={index}>{criterion}</li>)}</ul>
            <details className="maintainer-contract"><summary>{t("Task scope and verification")}</summary><h4>{t("Allowed paths")}</h4><pre>{task.allowed_paths.join("\n")}</pre><h4>{t("Forbidden paths")}</h4><pre>{task.forbidden_paths.join("\n") || "—"}</pre><h4>{t("Verification commands")}</h4><pre>{task.verification_commands.join("\n")}</pre></details>
            {task.status === "DRAFT" && <><div className="button-row"><button className="button" disabled={busy || !publishable} onClick={() => void run(`${base}/tasks/${task.id}/publish`, { version: task.version })}>{t("Publish task")}</button></div>
              {!publishable && <p className="maintainer-help">{t("Publication requires a verified repository, an approved improvement, and an active goal.")}</p>}</>}
            {task.improvement_id && !task.contract_locked && ["DRAFT", "AVAILABLE"].includes(task.status) && <TaskForm base={base} improvementId={task.improvement_id} busy={busy} run={run} task={task} />}
            {task.contract_locked && <p className="maintainer-help">{t("Contract locked because work has started. Create a new task for changed requirements.")}</p>}
            {task.status !== "DRAFT" && <Link className="maintainer-text-link" to={contributionPath(task)}>{t("View contribution progress")} <ArrowRight size={15} /></Link>}
          </section>;
        })}</div>{!data.tasks.length && <p className="maintainer-empty-copy">{t("No tasks yet. Open an improvement to prepare its first task draft.")}</p>}
      </>}
      {tab === "results" && <><div className="maintainer-section-intro"><h2>{t("Delivered results")}</h2><p>{t("Merged contributions are evidence for acceptance. An improvement is complete only when its acceptance criteria have been met.")}</p></div>
        <div className="maintainer-cards">{data.tasks.filter(task => task.status === "MERGED").map(task => <section className="panel maintainer-card" key={task.id}><CheckCircle2 size={22} /><h3>{task.title}</h3><p>{data.improvements.find(item => item.id === task.improvement_id)?.title ?? t("Unlinked task")}</p><Link className="button small secondary" to={contributionPath(task)}>{t("View contribution progress")}</Link></section>)}</div>
        {!data.tasks.some(task => task.status === "MERGED") && <p className="maintainer-empty-copy">{t("Completed contributions will appear here after their pull requests are merged.")}</p>}
      </>}
    </section>
  </div>;
}

function GoalForm({ base, busy, run, goal, priorityOnly = false }: { base: string; busy: boolean; run: RunAction; goal?: Goal; priorityOnly?: boolean }) {
  const [baseline, setBaseline] = useState(goal);
  const stale = !!goal && goal.version !== baseline?.version;
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); const form = event.currentTarget; const data = new FormData(form);
    void run(goal ? `${base}/goals/${goal.id}` : `${base}/goals`, {
      ...(baseline ? { version: baseline.version } : {}), ...(!priorityOnly ? { title: text(data, "title"), description: text(data, "description") } : {}), priority: Number(data.get("priority")),
    }, goal ? "PATCH" : "POST", result => { if (!goal) form.reset(); else setBaseline(result as Goal); });
  };
  return <Collapsible title={goal ? "Edit goal" : "Add a goal"}><VersionConflict stale={stale} reload={() => setBaseline(goal)} /><form key={baseline?.version ?? "new"} className="maintainer-form" onSubmit={submit}>
    {!priorityOnly && <><Field label="Goal title" name="title" value={baseline?.title} max={200} /><Field label="Desired outcome and context" name="description" value={baseline?.description} multiline min={10} /></>}
    <Priority value={baseline?.priority} /><Save busy={busy || stale} label={goal ? "Save changes" : "Create goal"} />
  </form></Collapsible>;
}
function ImprovementForm({ base, goals, busy, run, improvement, priorityOnly = false }: { base: string; goals: Goal[]; busy: boolean; run: RunAction; improvement?: Improvement; priorityOnly?: boolean }) {
  const [baseline, setBaseline] = useState(improvement);
  const stale = !!improvement && improvement.version !== baseline?.version;
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); const form = event.currentTarget; const data = new FormData(form);
    void run(improvement ? `${base}/improvements/${improvement.id}` : `${base}/improvements`, {
      ...(baseline ? { version: baseline.version } : {}), ...(!priorityOnly ? { goal_id: text(data, "goal_id") || null,
      title: text(data, "title"), problem: text(data, "problem"), outcome: text(data, "outcome"),
      acceptance_criteria: lines(data.get("acceptance_criteria")), in_scope: text(data, "in_scope"), out_of_scope: text(data, "out_of_scope"),
      kind: text(data, "kind") } : {}), priority: Number(data.get("priority")),
    }, improvement ? "PATCH" : "POST", result => { if (!improvement) form.reset(); else setBaseline(result as Improvement); });
  };
  return <Collapsible title={improvement ? "Edit improvement" : "Propose an improvement"}><VersionConflict stale={stale} reload={() => setBaseline(improvement)} /><form key={baseline?.version ?? "new"} className="maintainer-form" onSubmit={submit}>
    {!priorityOnly && <><Field label="Improvement title" name="title" value={baseline?.title} max={200} />
    <label className="maintainer-field"><span>{t("Related goal")}</span><select name="goal_id" defaultValue={baseline?.goal_id ?? ""}><option value="">{t("Independent improvement")}</option>{goals.map(goal => <option key={goal.id} value={goal.id}>{goal.title}</option>)}</select></label>
    <label className="maintainer-field"><span>{t("Work type")}</span><select name="kind" defaultValue={baseline?.kind ?? "FEATURE"}>{["FEATURE", "BUG", "DOCS", "TESTS", "PERFORMANCE"].map(kind => <option key={kind} value={kind}>{readable(kind)}</option>)}</select></label>
    <Field label="Problem to solve" name="problem" value={baseline?.problem} multiline min={10} /><Field label="Expected outcome" name="outcome" value={baseline?.outcome} multiline min={10} />
    <Field label="Acceptance criteria" name="acceptance_criteria" value={baseline?.acceptance_criteria.join("\n")} multiline hint="One criterion per line. Describe observable results." />
    <Field label="In scope" name="in_scope" value={baseline?.in_scope} multiline required={false} /><Field label="Out of scope" name="out_of_scope" value={baseline?.out_of_scope} multiline required={false} /></>}
    <Priority value={baseline?.priority} /><Save busy={busy || stale} label={improvement ? "Save changes" : "Create proposal"} />
  </form></Collapsible>;
}
function TaskForm({ base, improvementId, busy, run, task }: { base: string; improvementId: string; busy: boolean; run: RunAction; task?: PlannedTask }) {
  const [baseline, setBaseline] = useState(task);
  const stale = !!task && task.version !== baseline?.version;
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); const form = event.currentTarget; const data = new FormData(form);
    void run(task ? `${base}/tasks/${task.id}` : `${base}/improvements/${improvementId}/tasks`, {
      ...(baseline ? { version: baseline.version } : {}), title: text(data, "title"), description: text(data, "description"),
      difficulty: text(data, "difficulty"), risk: text(data, "risk"), required_model_tier: text(data, "required_model_tier"), estimated_minutes: Number(data.get("estimated_minutes")),
      acceptance_criteria: lines(data.get("acceptance_criteria")), allowed_paths: lines(data.get("allowed_paths")), forbidden_paths: lines(data.get("forbidden_paths")), verification_commands: lines(data.get("verification_commands")),
    }, task ? "PATCH" : "POST", result => { if (!task) form.reset(); else setBaseline(result as PlannedTask); });
  };
  return <Collapsible title={task ? "Edit task contract" : "Prepare a task draft"}><VersionConflict stale={stale} reload={() => setBaseline(task)} /><form key={baseline?.version ?? "new"} className="maintainer-form" onSubmit={submit}>
    <p className="maintainer-help">{t("Start with one small, independently verifiable contribution. Saving a draft does not publish it.")}</p>
    <Field label="Task title" name="title" value={baseline?.title} max={200} /><Field label="Task instructions" name="description" value={baseline?.description} multiline min={10} />
    <div className="maintainer-form-grid"><label className="maintainer-field"><span>{t("Risk")}</span><select name="risk" defaultValue={baseline?.risk ?? "LOW"}>{["LOW", "NORMAL", "HIGH", "CRITICAL"].map(risk => <option key={risk} value={risk}>{readable(risk)}</option>)}</select></label>
      <label className="maintainer-field"><span>{t("Model capability")}</span><select name="required_model_tier" defaultValue={baseline?.required_model_tier ?? "BASIC"}>{["BASIC", "STRONG", "FRONTIER"].map(tier => <option key={tier} value={tier}>{readable(tier)}</option>)}</select></label>
      <label className="maintainer-field"><span>{t("Difficulty")}</span><select name="difficulty" defaultValue={baseline?.difficulty ?? "EASY"}>{["EASY", "MEDIUM", "HARD", "EXPERT"].map(level => <option key={level} value={level}>{readable(level)}</option>)}</select></label>
      <label className="maintainer-field"><span>{t("Estimated minutes")}</span><input name="estimated_minutes" type="number" min={1} max={1440} defaultValue={baseline?.estimated_minutes ?? 30} required /></label></div>
    <Field label="Acceptance criteria" name="acceptance_criteria" value={baseline?.acceptance_criteria.join("\n")} multiline hint="One criterion per line. Describe observable results." />
    <Field label="Allowed paths" name="allowed_paths" value={baseline?.allowed_paths.join("\n")} multiline hint="One repository path or pattern per line. Keep the scope narrow." />
    <Field label="Forbidden paths" name="forbidden_paths" value={baseline?.forbidden_paths.join("\n")} multiline required={false} hint="One repository path or pattern per line." />
    <Field label="Verification commands" name="verification_commands" value={baseline?.verification_commands.join("\n")} multiline hint="One command per line. Contributors run these in their own environment." />
    <Save busy={busy || stale} label={task ? "Save task contract" : "Save draft"} />
  </form></Collapsible>;
}
