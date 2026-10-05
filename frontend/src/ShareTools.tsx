import { useState } from "react";
import { Copy, Download, Share2 } from "lucide-react";
import { t, useLocale } from "./i18n";

export function publicOrigin() {
  return typeof window === "undefined" ? "https://compute-for-good.tech" : window.location.origin;
}

export function CopyField({ value, label }: { value: string; label: string }) {
  const [notice, setNotice] = useState("");
  async function copy() {
    try { await navigator.clipboard.writeText(value); setNotice(t("Copied")); }
    catch { setNotice(t("Copy the text from the field below.")); }
  }
  return <div className="copy-field"><label><span>{label}</span><textarea readOnly value={value} rows={2} onFocus={e => e.target.select()} /></label><button type="button" className="button secondary small" onClick={() => void copy()}><Copy size={15} />{t("Copy")}</button><span role="status" className="small-print">{notice}</span></div>;
}

export function ReadmeBadge({ username, projectId }: { username?: string; projectId?: string }) {
  const { locale } = useLocale();
  const id = encodeURIComponent(username ?? projectId ?? "");
  const image = `${publicOrigin()}/api/badges/${username ? "people" : "projects"}/${id}.svg?lang=${locale}`;
  const destination = username ? `${publicOrigin()}/people/${id}` : `${publicOrigin()}/tasks?project_id=${id}`;
  const alt = username ? t("Accepted contributions") : t("Available tasks");
  return <details className="panel readme-badge"><summary>{t("Your README badge")}</summary><p>{t("Link your public record from GitHub or your website. Counts update when the badge is requested.")}</p><img src={image} alt={alt} width={420} height={32} /><CopyField label={t("Markdown for README")} value={`[![ComputeForGood: ${alt}](${image})](${destination})`} /><p className="small-print">{t("Image hosts may cache badges. Open the linked page for the latest evidence.")}</p></details>;
}

export default function ContributionShare({ id, title }: { id: string; title?: string }) {
  const { locale } = useLocale();
  const url = `${publicOrigin()}/share/${encodeURIComponent(id)}?lang=${locale}`;
  const png = `/api/shares/contributions/${encodeURIComponent(id)}/card.png?lang=${locale}`;
  const text = t("My contribution was accepted: {title}. See the result and find your own task: {url}", { title: title ?? t("Accepted contribution"), url });
  return <details className="contribution-share"><summary><Share2 size={16} />{t("Share this outcome")}</summary><div className="share-preview"><img src={png} alt={t("Accepted contribution card")} loading="lazy" width={1200} height={630} /></div><div className="share-actions"><a className="button secondary small" href={`${png}&download=true`}><Download size={16} />{t("Download PNG")}</a><a className="button secondary small" href={`${png}&shape=portrait&download=true`}>{t("Portrait card")}</a><a className="inline-link" href={url}>{t("Open public evidence")}</a></div><CopyField label={t("Share link")} value={url} /><CopyField label={t("Suggested post")} value={text} /></details>;
}
