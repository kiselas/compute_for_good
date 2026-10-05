import { Award, CheckCircle2, LockKeyhole } from "lucide-react";
import { Link } from "react-router-dom";
import type { Reputation } from "./api";
import { t, formatNumber } from "./i18n";

function achievementCopy(id: string): [string, string] {
  switch (id) {
    case "first_contribution": return [t("First accepted contribution"), t("One contribution accepted by a maintainer.")];
    case "five_contributions": return [t("Steady contributor"), t("Five accepted contributions.")];
    case "ten_contributions": return [t("Ten useful changes"), t("Ten accepted contributions.")];
    case "cross_project": return [t("Across projects"), t("Accepted contributions in three different projects.")];
    case "first_review": return [t("First accepted review"), t("Review the final commit of a contribution that is accepted.")];
    case "five_reviews": return [t("Review partner"), t("Review the final commits of five accepted contributions.")];
    default: return [id, ""];
  }
}

export default function RecognitionPanel({ reputation }: { reputation: Reputation }) {
  const earned = reputation.achievements.filter(a => a.earned).length;
  return <section className="panel recognition-panel">
    <div className="recognition-heading">
      <div><div className="eyebrow">{t("VERIFIED OUTCOMES")}</div><h2>{t("Contribution record")}</h2></div>
      <Link className="inline-link" to={reputation.is_demo ? "/leaderboard?demo=true" : "/leaderboard"}>{t("Contributor rankings")}</Link>
    </div>
    {reputation.is_demo && <p className="info-strip">{t("Demo recognition is separate from real contribution rankings.")}</p>}
    <div className="recognition-metrics">
      <div><strong>{formatNumber(reputation.metrics.accepted_contributions)}</strong><span>{t("Accepted contributions")}</span></div>
      <div><strong>{formatNumber(reputation.metrics.accepted_reviews)}</strong><span>{t("Reviews on accepted work")}</span></div>
      <div><strong>{formatNumber(reputation.metrics.projects_helped)}</strong><span>{t("Projects helped")}</span></div>
      <div><strong>{reputation.acceptance.rate === null ? "—" : t("{rate}%", { rate: formatNumber(reputation.acceptance.rate) })}</strong><span>{t("PR acceptance rate")}</span><small>{t("{count} decided submissions", { count: formatNumber(reputation.acceptance.decided) })}</small></div>
    </div>
    <p className="small-print">{t("Acceptance rate uses accepted, closed and invalid canonical submissions. Pending work is excluded; a small sample is not a quality guarantee.")}</p>
    <div className="recognition-heading"><h3><Award size={19} />{t("Achievements")}</h3><span className="muted">{t("{earned} of {total} earned", { earned: formatNumber(earned), total: formatNumber(reputation.achievements.length) })}</span></div>
    <div className="achievement-grid">
      {reputation.achievements.map(a => {
        const [title, description] = achievementCopy(a.id);
        return <article className={`achievement-card ${a.earned ? "earned" : "locked"}`} key={a.id}>
          <div className="achievement-icon" aria-hidden="true">{a.earned ? <CheckCircle2 size={22} /> : <LockKeyhole size={22} />}</div>
          <div><h4>{title}</h4><p>{description}</p><div className="achievement-progress"><progress value={a.progress} max={a.threshold} aria-label={title} /><span>{a.earned ? t("Earned") : t("{progress} / {goal}", { progress: formatNumber(a.progress), goal: formatNumber(a.threshold) })}</span></div></div>
        </article>;
      })}
    </div>
    <p className="small-print">{t("Recognition comes from canonical merge records and reviews of the final accepted commit. Claims, raw PR volume and stale reviews earn no progress.")}</p>
  </section>;
}
