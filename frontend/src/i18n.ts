import { useSyncExternalStore } from "react";
import english from "./locales/en.json";
import russian from "./locales/ru.json";
import chinese from "./locales/zh-CN.json";

export const locales = ["en", "ru", "zh-CN"] as const;
export type Locale = (typeof locales)[number];
export const localeNames: Record<Locale, string> = {
  en: "English", ru: "Русский", "zh-CN": "简体中文",
};
const dictionaries: Record<Locale, Record<string, string>> = {
  en: english, ru: russian, "zh-CN": chinese,
};
const storageKey = "cfg-language";
const listeners = new Set<() => void>();

export function normalizeLocale(value?: string | null): Locale | undefined {
  const base = value?.toLowerCase().split(/[-_]/)[0];
  return base === "en" ? "en" : base === "ru" ? "ru" : base === "zh" ? "zh-CN" : undefined;
}
function initialLocale(): Locale {
  if (typeof window === "undefined") return "en";
  try {
    const saved = normalizeLocale(window.localStorage.getItem(storageKey));
    if (saved) return saved;
  } catch { /* Storage may be disabled; switching still works in this tab. */ }
  for (const language of window.navigator.languages ?? [window.navigator.language]) {
    const supported = normalizeLocale(language);
    if (supported) return supported;
  }
  return "en";
}
let currentLocale = initialLocale();

export function getLocale(): Locale { return currentLocale; }
export function t(source: string, params: Record<string, string | number> = {}): string {
  const text = dictionaries[currentLocale][source] ?? dictionaries.en[source] ?? source;
  return text.replace(/\{([A-Za-z][A-Za-z0-9_]*)\}/g, (placeholder, name: string) =>
    Object.hasOwn(params, name) ? String(params[name]) : placeholder,
  );
}
export function formatDate(value: string | number | Date): string {
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return new Intl.DateTimeFormat(currentLocale, {
    dateStyle: "medium", timeStyle: "short",
  }).format(date);
}
export function formatNumber(value: number, options?: Intl.NumberFormatOptions): string {
  return new Intl.NumberFormat(currentLocale, options).format(value);
}
function updateDocument() {
  if (typeof document === "undefined") return;
  document.documentElement.lang = currentLocale;
  document.title = t("ComputeForGood — useful work, together");
  const description = t("Turn spare coding-agent time into useful open-source contributions. Connect through MCP, find a clear task, and contribute with independent review.");
  for (const selector of ['meta[name="description"]', 'meta[property="og:description"]', 'meta[name="twitter:description"]']) {
    document.querySelector<HTMLMetaElement>(selector)?.setAttribute("content", description);
  }
  document.querySelector<HTMLMetaElement>('meta[property="og:title"]')?.setAttribute("content", document.title);
  document.querySelector<HTMLMetaElement>('meta[property="og:locale"]')?.setAttribute("content", { en: "en_US", ru: "ru_RU", "zh-CN": "zh_CN" }[currentLocale]);
}
function changeLocale(locale: Locale) {
  if (currentLocale === locale) return;
  currentLocale = locale;
  updateDocument();
  for (const listener of listeners) listener();
}
export function setLocale(locale: Locale): void {
  if (!locales.includes(locale)) return;
  try { window.localStorage.setItem(storageKey, locale); } catch { /* Optional persistence. */ }
  changeLocale(locale);
}
function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}
export function useLocale() {
  const locale = useSyncExternalStore(subscribe, getLocale, () => "en" as Locale);
  return { locale, setLocale };
}
if (typeof window !== "undefined") {
  window.addEventListener("storage", (event) => {
    if (event.key === storageKey) {
      changeLocale(normalizeLocale(event.newValue) ?? initialLocale());
    }
  });
  updateDocument();
}
