import { useQuery } from "@tanstack/react-query";
import { ArrowRight, Award, GitPullRequest, Globe2, ShieldCheck } from "lucide-react";
import { Link, useSearchParams } from "react-router-dom";
import { api, type Leaderboard } from "./api";
import { t, useLocale, formatDate, formatNumber } from "./i18n";

export default function LeaderboardPage() {
  useLocale();
  const [params, setParams] = useSearchParams();
  const metric = ["contributions", "reviews", "projects"].includes(params.get("metric") ?? "") ? params.get("metric")! : "contributions";
  const period = params.get("period") === "30d" ? "30d" : "all";
  const demo = params.get("demo") === "true";
  const requestedOffset = Number(params.get("offset") ?? 0);
  const offset = Number.isInteger(requestedOffset) && requestedOffset >= 0 && requestedOffset <= 10000 ? requestedOffset : 0;
  const path = `/leaderboard?metric=${metric}&period=${period}&limit=25&offset=${offset}&demo=${demo}`;
  const query = useQuery<Leaderboard>({ queryKey: [path], queryFn: () => api(path) });
  function change(key: string, value: string) {
    const next = new URLSearchParams(params);
    next.set(key, value);
    if (key !== "offset") next.delete("offset");
    setParams(next);
  }
  const options = [
    { id: "contributions", label: t("Accepted contributions"), icon: GitPullRequest },
    { id: "reviews", label: t("Reviews on accepted work"), icon: ShieldCheck },
    { id: "projects", label: t("Projects helped"), icon: Globe2 },
  ];
  return <>
    <div className="page-heading recognition-title"><div><div className="eyebrow">{t("THE PEOPLE BEHIND THE WORK")}</div><h1>{t("Useful work. Visible credit.")}</h1><p>{t("Meet the contributors helping open source move forward. Every place in these tables comes from an accepted outcome.")}</p></div><Award size={44} aria-hidden="true" /></div>
    {demo && <div className="info-strip">{t("Demo recognition is separate from real contribution rankings.")} <Link to="/leaderboard">{t("View real rankings")}</Link></div>}
    <section className="panel leaderboard-panel">
      <div className="leaderboard-controls">
        <div className="ranking-switch" role="group" aria-label={t("Rank by")}>
          {options.map(({ id, label, icon: Icon }) => <button type="button" key={id} aria-pressed={metric === id} onClick={() => change("metric", id)}><Icon size={17} />{label}</button>)}
        </div>
        <label className="ranking-period">{t("Period")}<select value={period} onChange={event => change("period", event.target.value)}><option value="all">{t("All time")}</option><option value="30d">{t("Last 30 days")}</option></select></label>
      </div>
      {query.isPending ? <div className="empty" aria-busy="true">{t("Loading rankings…")}</div> : query.isError ? <div className="error-box" role="alert"><p>{t("Rankings are temporarily unavailable.")}</p><button type="button" className="button secondary" onClick={() => void query.refetch()}>{t("Try again")}</button></div> : query.data && <>
        {query.data.entries.length ? <div className="ranking-table-scroll" tabIndex={0} role="region" aria-label={t("Contributor rankings")}><table className="ranking-table">
          <caption>{options.find(o => o.id === metric)?.label} · {period === "30d" ? t("Last 30 days") : t("All time")}</caption>
          <thead><tr><th scope="col">{t("Rank")}</th><th scope="col">{t("Contributor")}</th><th scope="col">{t("Accepted contributions")}</th><th scope="col">{t("Reviews on accepted work")}</th><th scope="col">{t("Projects helped")}</th></tr></thead>
          <tbody>{query.data.entries.map(entry => <tr key={entry.username}><td><span className={`ranking-place ${entry.rank <= 3 ? "leading" : ""}`}>{formatNumber(entry.rank)}</span></td><th scope="row"><Link to={`/people/${encodeURIComponent(entry.username)}`}>@{entry.username}</Link></th><td>{formatNumber(entry.metrics.accepted_contributions)}</td><td>{formatNumber(entry.metrics.accepted_reviews)}</td><td>{formatNumber(entry.metrics.projects_helped)}</td></tr>)}</tbody>
        </table></div> : <div className="empty"><Award size={30} /><h3>{offset > 0 ? t("No more contributors on this page") : t("The first places are waiting for useful work.")}</h3><p>{t("Only contributors with an accepted outcome in the selected category and period appear here.")}</p><Link className="button secondary" to="/tasks">{t("Find work")}<ArrowRight size={16} /></Link></div>}
        <div className="ranking-footer"><span>{t("{count} contributors", { count: formatNumber(query.data.total) })}</span><div className="button-row"><button type="button" className="button small secondary" disabled={offset === 0} onClick={() => change("offset", String(Math.max(0, offset - 25)))}>{t("Previous")}</button><button type="button" className="button small secondary" disabled={offset + 25 >= query.data.total || offset + 25 > 10000} onClick={() => change("offset", String(offset + 25))}>{t("Next")}</button></div></div>
        <p className="small-print">{t("Updated {date}", { date: formatDate(query.data.as_of) })}</p>
      </>}
    </section>
    <section className="panel recognition-explanation"><h2>{t("What counts, and why")}</h2><p>{t("An accepted contribution is a canonical PR with a recorded maintainer merge. Review credit requires a review of that PR's final accepted commit, by someone other than its author, before acceptance.")}</p><p>{t("The 30-day table uses the date acceptance was recorded. Equal totals share a rank. These counts describe participation, not vulnerability severity, code quality or social impact.")}</p><p>{t("Recognition comes from canonical merge records and reviews of the final accepted commit. Claims, raw PR volume and stale reviews earn no progress.")}</p><div className="button-row"><Link className="button" to="/tasks">{t("Find work")}<ArrowRight size={16} /></Link><Link className="button secondary" to="/onboarding">{t("Bring your project")}</Link></div></section>
  </>;
}
