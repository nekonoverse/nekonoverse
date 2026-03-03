import { useI18n, locales, type Locale } from "../../i18n";

export default function LanguageSwitcher() {
  const { locale, setLocale } = useI18n();

  const nextLocale = () => {
    const idx = locales.findIndex((l) => l.code === locale());
    return locales[(idx + 1) % locales.length];
  };

  return (
    <button
      class="lang-switcher"
      onClick={() => setLocale(nextLocale().code as Locale)}
      title={nextLocale().name}
    >
      {nextLocale().code.toUpperCase()}
    </button>
  );
}
