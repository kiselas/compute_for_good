import { Award, CheckCircle2, LockKeyhole } from "lucide-react";
import { Link } from "react-router-dom";
import type { Reputation } from "./api";
import { t, formatNumber } from "./i18n";

function achievementCopy(id: string) {
  switch (id) {
    case "first_contribution": return {
      title: t("First merge"), quip: t("Even a Jedi starts with one PR."),
      criterion: t("One contribution accepted by a maintainer."), art: "first_contribution", tone: "mint",
    };
    case "five_contributions": return {
      title: t("The fifth element"), quip: t("Four elements. A little persistence."),
      criterion: t("Five accepted contributions."), art: "five_contributions", tone: "amber",
    };
    case "ten_contributions": return {
      title: t("Combo ×10"), quip: t("The backlog is losing hit points."),
      criterion: t("Ten accepted contributions."), art: "ten_contributions", tone: "rose",
    };
    case "cross_project": return {
      title: t("Three worlds"), quip: t("Three repositories. One explorer."),
      criterion: t("Accepted contributions in three different projects."), art: "cross_project", tone: "violet",
    };
    case "first_review": return {
      title: t("Fresh eyes"), quip: t("Elementary: check before you merge."),
      criterion: t("Review the final commit of a contribution that is accepted."), art: "first_review", tone: "teal",
    };
    case "five_reviews": return {
      title: t("Code guardian"), quip: t("Superpower: noticing the details."),
      criterion: t("Review the final commits of five accepted contributions."), art: "five_reviews", tone: "blue",
    };
    default: return { title: id, quip: "", criterion: "", art: null, tone: "blue" };
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
    <div className="recognition-heading achievement-heading"><h3><Award size={19} />{t("Achievements")}</h3><span className="achievement-collection-count">{t("{earned} of {total} earned", { earned: formatNumber(earned), total: formatNumber(reputation.achievements.length) })}</span></div>
    <div className="achievement-grid">
      {reputation.achievements.map(a => {
        const { title, quip, criterion, art, tone } = achievementCopy(a.id);
        return <article className={`achievement-card ${a.earned ? "earned" : "locked"}`} data-tone={tone} key={a.id}>
          <div className="achievement-art" aria-hidden="true">
            {art ? <img src={`/images/achievements/${art}-v2.webp`} alt="" width={96} height={96} loading="lazy" decoding="async" /> : <Award size={40} />}
          </div>
          <div className="achievement-body">
            <span className="achievement-status">{a.earned ? <CheckCircle2 size={13} aria-hidden="true" /> : <LockKeyhole size={13} aria-hidden="true" />}{a.earned ? t("Earned") : a.progress > 0 ? t("Getting there") : t("Still ahead")}</span>
            <h4>{title}</h4><p className="achievement-quip">{quip}</p>
            <div className="achievement-goal"><span>{t("Unlock condition")}</span><p>{criterion}</p></div>
            <div className="achievement-progress"><progress value={a.progress} max={a.threshold} aria-label={title} /><span>{t("{progress} / {goal}", { progress: formatNumber(a.progress), goal: formatNumber(a.threshold) })}</span></div>
          </div>
        </article>;
      })}
    </div>
    <p className="small-print">{t("Recognition comes from canonical merge records and reviews of the final accepted commit. Claims, raw PR volume and stale reviews earn no progress.")}</p>
  </section>;
}
