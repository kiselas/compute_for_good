import { Globe2 } from "lucide-react";
import { localeNames, locales, t, useLocale, type Locale } from "./i18n";

export default function LanguageSwitcher() {
  const { locale, setLocale } = useLocale();
  return (
    <label className="language-picker">
      <Globe2 size={16} aria-hidden="true" />
      <span className="sr-only">{t("Language")}</span>
      <select aria-label={t("Language")} value={locale}
        onChange={(event) => setLocale(event.target.value as Locale)}>
        {locales.map((language) => <option key={language} value={language} lang={language}>
          {localeNames[language]}
        </option>)}
      </select>
    </label>
  );
}
