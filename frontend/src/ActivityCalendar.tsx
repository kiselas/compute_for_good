import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { CalendarDays } from "lucide-react";
import { api } from "./api";
import { t, useLocale, formatNumber } from "./i18n";

export interface ActivityYear {
  username: string; is_demo: boolean; year: number; as_of: string; timezone: string;
  days: { date: string; contributions: number; reviews: number }[];
  active_days: number; totals: { contributions: number; reviews: number }; available_years: number[];
}
type Kind = "all" | "contributions" | "reviews";
export function calendarCells(data: ActivityYear) {
  const first = new Date(Date.UTC(data.year, 0, 1));
  const pad = (first.getUTCDay() + 6) % 7;
  return [...Array.from({ length: pad }, () => null), ...data.days];
}

export default function ActivityCalendar({ username }: { username: string }) {
  const { locale } = useLocale();
  const [year, setYear] = useState<number | null>(null);
  const [kind, setKind] = useState<Kind>("all");
  const [selected, setSelected] = useState<string | null>(null);
  const path = `/people/${encodeURIComponent(username)}/activity${year ? `?year=${year}` : ""}`;
  const query = useQuery<ActivityYear>({ queryKey: [path], queryFn: () => api(path) });
  const dayPath = `/people/${encodeURIComponent(username)}/activity/day?day=${selected ?? ""}`;
  const detail = useQuery<{ items: { submission_id: string; kind: string; title: string; project: string }[]; limit: number }>({ queryKey: [dayPath], queryFn: () => api(dayPath), enabled: !!selected });
  const evidence = detail.data?.items.filter(item => kind === "all" || item.kind === (kind === "reviews" ? "review" : "contribution")) ?? [];
  const cells = useMemo(() => query.data ? calendarCells(query.data) : [], [query.data]);
  const count = (day: NonNullable<typeof cells[number]>) => kind === "all" ? day.contributions + day.reviews : day[kind];
  const activeDays = cells.filter(day => day && count(day) > 0).length;
  const total = cells.reduce((sum, day) => sum + (day ? count(day) : 0), 0);
  const best = cells.reduce((winner, day) => day && count(day) > (winner ? count(winner) : 0) ? day : winner, null as typeof cells[number]);
  const dateLabel = (iso: string) => new Intl.DateTimeFormat(locale, { dateStyle: "long", timeZone: "UTC" }).format(new Date(iso + "T00:00:00Z"));
  return <section className="panel activity-calendar">
    <div className="recognition-heading"><h2><CalendarDays size={21} />{t("A year of useful work")}</h2>{query.data && <label>{t("Year")} <select aria-label={t("Year")} value={query.data.year} onChange={e => { setYear(Number(e.target.value)); setSelected(null); }}>{query.data.available_years.map(y => <option value={y} key={y}>{y}</option>)}</select></label>}</div>
    <p className="small-print">{t("Cells count accepted contributions and reviews of their final commit, on the acceptance recording date in UTC. Claims and pending PRs do not count.")}</p>
    <div className="ranking-switch" role="group" aria-label={t("Activity type")}>{([ ["all", "All outcomes"], ["contributions", "Accepted contributions"], ["reviews", "Reviews on accepted work"] ] as const).map(([value, label]) => <button type="button" aria-pressed={kind === value} key={value} onClick={() => setKind(value)}>{t(label)}</button>)}</div>
    {query.isPending ? <p aria-busy="true">{t("Loading activity…")}</p> : query.isError ? <div className="error-box" role="alert"><p>{t("Activity is temporarily unavailable.")}</p><button type="button" className="button secondary small" onClick={() => void query.refetch()}>{t("Try again")}</button></div> : query.data && <>
      {query.data.is_demo && <p className="info-strip">{t("Demo recognition is separate from real contribution rankings.")}</p>}
      <div className="activity-summary"><strong>{t("{count} outcomes", { count: formatNumber(total) })}</strong><span>{t("{count} active days", { count: formatNumber(activeDays) })}</span>{best && count(best) > 0 && <span>{t("Most active day: {date}", { date: dateLabel(best.date) })}</span>}</div>
      <div className="calendar-scroll" tabIndex={0} role="region" aria-label={t("Contribution calendar")}><div className="calendar-months">{cells.map((day, index) => day && day.date.endsWith("-01") ? <span key={day.date} style={{ gridColumn: Math.floor(index / 7) + 1 }}>{new Intl.DateTimeFormat(locale, { month: "short", timeZone: "UTC" }).format(new Date(day.date + "T00:00:00Z"))}</span> : null)}</div><div className={`calendar-grid ${kind === "reviews" ? "review-calendar" : ""}`}>
        {cells.map((day, index) => day ? <button type="button" key={day.date} data-level={Math.min(4, count(day))} aria-pressed={selected === day.date} tabIndex={selected === day.date || !selected && day.date === query.data?.days.at(-1)?.date ? 0 : -1} title={`${dateLabel(day.date)} · ${count(day)}`} aria-label={t("{date}: {count} outcomes", { date: dateLabel(day.date), count: formatNumber(count(day)) })} onClick={() => setSelected(day.date)} onKeyDown={e => { const delta: Record<string, number> = { ArrowRight: 7, ArrowLeft: -7, ArrowDown: 1, ArrowUp: -1 }; if (!(e.key in delta)) return; e.preventDefault(); const target = cells[index + delta[e.key]]; if (target) { setSelected(target.date); e.currentTarget.parentElement?.querySelector<HTMLButtonElement>(`button[data-date="${target.date}"]`)?.focus(); } }} data-date={day.date} /> : <span key={`pad-${index}`} />)}
      </div></div>
      <div className={`calendar-legend ${kind === "reviews" ? "review-calendar" : ""}`}><span>{t("Less")}</span>{[0, 1, 2, 3, 4].map(level => <span className="calendar-sample" data-level={level} key={level} />)}<span>{t("More")}</span><small>{t("Select a day to see its evidence.")}</small></div>
      {!activeDays && <p>{t("Your first accepted outcome will light up the calendar.")}</p>}
      {selected && <div className="calendar-evidence" aria-live="polite"><h3>{dateLabel(selected)}</h3>{detail.isPending ? <p>{t("Loading activity…")}</p> : detail.isError ? <p role="alert">{t("Activity is temporarily unavailable.")}</p> : evidence.length ? <><ul>{evidence.map(item => <li key={`${item.kind}-${item.submission_id}`}><a href={`/share/${encodeURIComponent(item.submission_id)}?lang=${locale}`}>{item.title}</a> · {item.project} · {t(item.kind === "review" ? "Reviews on accepted work" : "Accepted contribution")}</li>)}</ul>{detail.data?.items.length === detail.data?.limit && <p className="small-print">{t("Showing the first 100 outcomes for this day.")}</p>}</> : <p>{t("No accepted outcomes on this day.")}</p>}</div>}
      <Link className="inline-link" to="/sprints">{t("Join a contribution sprint")}</Link>
    </>}
  </section>;
}
