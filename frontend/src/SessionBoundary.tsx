import type { ReactNode } from "react";
import { t } from "./i18n";
import type { SessionPhase } from "./sessionState";

export default function SessionBoundary({ phase, retry, compact = false, children }: {
  phase: SessionPhase; retry: () => void; compact?: boolean; children?: ReactNode;
}) {
  if (phase === "authenticated" || phase === "guest") return children;
  if (phase === "loading") return compact
    ? <span role="status" aria-live="polite">{t("Checking your session…")}</span>
    : <section className="panel" role="status" aria-live="polite"><p>{t("Checking your session…")}</p></section>;
  if (compact) return <div role="alert"><button className="text-button" type="button" onClick={retry}
    aria-label={t("Unable to check your session. Please try again.")}>{t("Retry session check")}</button></div>;
  return <section className="panel error-box" role="alert"><p>{t("Unable to check your session. Please try again.")}</p>
    <button className="button secondary" type="button" onClick={retry}>{t("Retry session check")}</button></section>;
}
