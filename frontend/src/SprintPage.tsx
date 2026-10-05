import { useQuery } from "@tanstack/react-query";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { Flag, ArrowRight } from "lucide-react";
import { api } from "./api";
import { t, useLocale, formatDate, formatNumber } from "./i18n";
import { CopyField, publicOrigin } from "./ShareTools";

export interface Sprint {
  id: string; slug: string; title: Record<string, string>; description: Record<string, string>;
  starts_at: string; ends_at: string; response_hours: number; status: string;
  state: string; version: number; is_demo: boolean; owner: string | null;
  project: { id: string; slug: string; name: string };
  goal: number; accepted: number; participants: number; accepted_reviews: number; available: number;
  tasks: { id: string; title: string; status: string; risk: string; estimated_minutes: number; available: boolean }[];
  results: { submission_id: string; title: string; username: string }[];
}
const states: Record<string, string> = { draft: "Draft", upcoming: "Upcoming", active: "Active", ended: "Ended", paused: "Paused" };

export function SprintCard({ value }: { value: Sprint }) {
  const { locale } = useLocale();
  return <article className="panel sprint-card"><div className="eyebrow">{value.project.name} · {t(states[value.state] ?? value.state)}</div><h2><Link to={`/sprints/${encodeURIComponent(value.slug)}`}>{value.title[locale] ?? value.title.en}</Link></h2><p>{value.description[locale] ?? value.description.en}</p><progress value={value.accepted} max={Math.max(1, value.goal)} aria-label={t("Sprint progress")} /><p>{t("{accepted} of {goal} tasks accepted", { accepted: formatNumber(value.accepted), goal: formatNumber(value.goal) })} · {t("{count} available tasks", { count: formatNumber(value.available) })}</p><Link className="inline-link" to={`/sprints/${encodeURIComponent(value.slug)}`}>{t("Explore sprint")} <ArrowRight size={16} /></Link></article>;
}

function Catalog() {
  useLocale();
  const [params] = useSearchParams();
  const demo = params.get("demo") === "true";
  const path = `/sprints?demo=${demo}`;
  const query = useQuery<Sprint[]>({ queryKey: [path], queryFn: () => api(path) });
  return <><div className="page-heading"><div><div className="eyebrow">{t("CONTRIBUTE TOGETHER")}</div><h1>{t("Contribution sprints")}</h1><p>{t("A clear shared goal, scoped tasks and a maintainer who can accept the result.")}</p></div><Flag size={40} /></div>{demo && <p className="info-strip">{t("Demo recognition is separate from real contribution rankings.")}</p>}{query.isPending ? <p aria-busy="true">{t("Loading sprints…")}</p> : query.isError ? <div className="error-box" role="alert"><p>{t("Sprints are temporarily unavailable.")}</p><button type="button" className="button secondary" onClick={() => void query.refetch()}>{t("Try again")}</button></div> : query.data?.length ? <div className="sprint-grid">{query.data.map(value => <SprintCard key={value.id} value={value} />)}</div> : <section className="panel"><h2>{t("The next sprint is being prepared")}</h2><p>{t("Published sprints appear here once the maintainer has prepared available tasks.")}</p><Link className="button secondary" to="/tasks">{t("Find tasks")}</Link></section>}</>;
}

function Detail({ slug }: { slug: string }) {
  const { locale } = useLocale();
  const path = `/sprints/${encodeURIComponent(slug)}`;
  const query = useQuery<Sprint>({ queryKey: [path], queryFn: () => api(path) });
  if (query.isPending) return <p aria-busy="true">{t("Loading sprints…")}</p>;
  if (query.isError || !query.data) return <div className="error-box" role="alert"><p>{t("This sprint is unavailable.")}</p><Link to="/sprints">{t("Contribution sprints")}</Link></div>;
  const sprint = query.data;
  const invitation = t("Join me in {sprint}: scoped open-source tasks and real accepted outcomes. {url}", { sprint: sprint.title[locale] ?? sprint.title.en, url: `${publicOrigin()}/sprints/${encodeURIComponent(sprint.slug)}` });
  return <><Link className="back-link" to="/sprints">{t("Contribution sprints")}</Link><div className="page-heading"><div><div className="eyebrow">{sprint.project.name} · {t(states[sprint.state] ?? sprint.state)}</div><h1>{sprint.title[locale] ?? sprint.title.en}</h1><p>{sprint.description[locale] ?? sprint.description.en}</p></div><Flag size={40} /></div>
    {sprint.is_demo && <p className="info-strip">{t("Demo recognition is separate from real contribution rankings.")}</p>}
    <section className="panel sprint-progress"><div className="recognition-metrics"><div><strong>{formatNumber(sprint.accepted)} / {formatNumber(sprint.goal)}</strong><span>{t("Accepted tasks")}</span></div><div><strong>{formatNumber(sprint.participants)}</strong><span>{t("Contributors and reviewers")}</span></div><div><strong>{formatNumber(sprint.accepted_reviews)}</strong><span>{t("Reviews on accepted work")}</span></div><div><strong>{formatNumber(sprint.available)}</strong><span>{t("Available tasks")}</span></div></div><progress value={sprint.accepted} max={Math.max(1, sprint.goal)} aria-label={t("Sprint progress")} /><p>{formatDate(sprint.starts_at)} — {formatDate(sprint.ends_at)}</p><p className="small-print">{t("Only outcomes accepted during the sprint count toward its goal. The date uses the acceptance record, not PR creation.")}</p><p>{t("Maintainer response target: {hours} hours", { hours: formatNumber(sprint.response_hours) })} · {sprint.owner && <Link to={`/people/${encodeURIComponent(sprint.owner)}`}>@{sprint.owner}</Link>}</p></section>
    <section className="panel"><h2>{t("Choose your contribution")}</h2><p>{t("Open the task contract, connect your agent, and reserve the work. Each task still requires CI, independent review and maintainer acceptance.")}</p><div className="sprint-tasks">{sprint.tasks.map(task => <article key={task.id}><div><Link className="inline-link" to={`/tasks/${encodeURIComponent(task.id)}`}>{task.title}</Link><p className="small-print">{task.risk} · {t("{minutes} min estimate", { minutes: formatNumber(task.estimated_minutes) })} · {task.available ? t("Available") : t("Not currently available")}</p></div><Link className="button secondary small" to={`/tasks/${encodeURIComponent(task.id)}`}>{t("View contract")}</Link></article>)}</div>{!sprint.available && <p className="info-strip">{t("No tasks are available in this sprint right now. Browse the catalog or return for the next sprint.")}</p>}</section>
    <section className="panel"><h2>{t("Sprint outcomes")}</h2>{sprint.results.length ? <ul className="sprint-results">{sprint.results.map(result => <li key={result.submission_id}><a href={`/share/${encodeURIComponent(result.submission_id)}?lang=${locale}`}>{result.title}</a> · <Link to={`/people/${encodeURIComponent(result.username)}`}>@{result.username}</Link></li>)}</ul> : <p>{t("The first accepted outcome will appear here.")}</p>}</section>
    <section className="panel"><h2>{t("Invite someone to contribute")}</h2><CopyField label={t("Sprint invitation")} value={invitation} /><Link className="inline-link" to="/connect">{t("Connect an agent")}</Link></section>
  </>;
}

export default function SprintPage() {
  const { slug } = useParams();
  return slug ? <Detail slug={slug} /> : <Catalog />;
}
