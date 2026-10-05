import { useState, type FormEvent } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api, type Task } from "./api";
import { t, useLocale } from "./i18n";
import type { Sprint } from "./SprintPage";

export default function SprintBuilder({ projectId, tasks }: { projectId: string; tasks: Task[] }) {
  const { locale } = useLocale();
  const client = useQueryClient();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const path = `/maintainer/projects/${encodeURIComponent(projectId)}/sprints`;
  const query = useQuery<Sprint[]>({ queryKey: [path], queryFn: () => api(path) });
  async function run(url: string, body: unknown) {
    setBusy(true); setError("");
    try { await api(url, { method: "POST", body: JSON.stringify(body) }); await client.invalidateQueries({ queryKey: [path] }); await client.invalidateQueries({ queryKey: ["/sprints?demo=false"] }); return true; }
    catch (e) { setError(e instanceof Error ? e.message : t("Unable to save sprint")); return false; }
    finally { setBusy(false); }
  }
  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const form = event.currentTarget; const data = new FormData(form);
    const localized = (key: string) => Object.fromEntries(["en", "ru", "zh-CN"].map(language => [language, String(data.get(`${key}-${language}`) ?? "").trim()]));
    if (await run(path, { slug: data.get("slug"), title: localized("title"), description: localized("description"), starts_at: new Date(String(data.get("starts_at"))).toISOString(), ends_at: new Date(String(data.get("ends_at"))).toISOString(), response_hours: Number(data.get("response_hours")), task_ids: data.getAll("task_ids") })) form.reset();
  }
  const eligible = tasks.filter(task => task.status === "AVAILABLE" && ["LOW", "NORMAL"].includes(task.risk));
  return <section className="panel sprint-builder"><h2>{t("Contribution sprints")}</h2><p>{t("Prepare a shared goal using existing published tasks. Publication rechecks their contracts and availability.")}</p>{error && <p className="error-box" role="alert">{t(error)}</p>}{query.isError && <p role="alert">{t("Sprints are temporarily unavailable.")}</p>}
    {query.data?.map(sprint => <div className="sprint-owner-row" key={sprint.id}><strong>{sprint.title[locale] ?? sprint.title.en}</strong><span>{t(sprint.status === "DRAFT" ? "Draft" : sprint.status === "PAUSED" ? "Paused" : "Published")}</span>{sprint.status === "DRAFT" ? <button type="button" className="button small" disabled={busy} onClick={() => void run(`${path}/${sprint.id}/publish`, { version: sprint.version })}>{t("Publish sprint")}</button> : <><Link to={`/sprints/${encodeURIComponent(sprint.slug)}`}>{t("Explore sprint")}</Link>{sprint.status === "PUBLISHED" && <button type="button" className="button secondary small" disabled={busy} onClick={() => void run(`${path}/${sprint.id}/pause`, { version: sprint.version })}>{t("Pause sprint")}</button>}</>}</div>)}
    <details className="maintainer-editor"><summary>{t("Prepare a sprint")}</summary><form onSubmit={e => void create(e)}><label className="maintainer-field">{t("Sprint URL name")}<input name="slug" required pattern="[a-z0-9][a-z0-9-]{2,79}" maxLength={80} placeholder="first-contribution" /></label>
      {[ ["en", "English"], ["ru", "Русский"], ["zh-CN", "简体中文"] ].map(([language, name]) => <fieldset key={language}><legend>{name}</legend><label className="maintainer-field">{t("Sprint title")}<input name={`title-${language}`} required maxLength={200} /></label><label className="maintainer-field">{t("Sprint description")}<textarea name={`description-${language}`} required maxLength={5000} rows={3} /></label></fieldset>)}
      <label className="maintainer-field">{t("Starts at")}<input name="starts_at" type="datetime-local" required /></label><label className="maintainer-field">{t("Ends at")}<input name="ends_at" type="datetime-local" required /></label><label className="maintainer-field">{t("Response target in hours")}<input name="response_hours" type="number" min={1} max={168} defaultValue={72} required /></label>
      <fieldset><legend>{t("Published LOW/NORMAL tasks")}</legend>{eligible.length ? eligible.map(task => <label className="sprint-task-check" key={task.id}><input type="checkbox" name="task_ids" value={task.id} />{task.title}</label>) : <p>{t("Publish task contracts before preparing a sprint.")}</p>}</fieldset><button className="button" type="submit" disabled={busy || !eligible.length}>{t(busy ? "Saving…" : "Save draft")}</button>
    </form></details>
  </section>;
}
