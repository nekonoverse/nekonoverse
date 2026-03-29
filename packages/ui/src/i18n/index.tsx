import {
  createContext,
  createSignal,
  createMemo,
  useContext,
  type ParentComponent,
} from "solid-js";
import { flatten, translator } from "@solid-primitives/i18n";
import { ja, type Dictionary } from "./dictionaries/ja";
import { en } from "./dictionaries/en";
import { neko } from "./dictionaries/neko";

export type Locale = "ja" | "en" | "neko";

const dictionaries: Record<Locale, Dictionary> = { ja, en, neko };

export const locales: { code: Locale; name: string }[] = [
  { code: "ja", name: "日本語" },
  { code: "en", name: "English" },
  { code: "neko", name: "ねこ語" },
];

function detectLocale(): Locale {
  const saved = localStorage.getItem("locale");
  if (saved && saved in dictionaries) return saved as Locale;
  const nav = navigator.language.split("-")[0];
  if (nav in dictionaries) return nav as Locale;
  return "ja";
}

type TranslatorFn = (key: keyof Dictionary) => string;

interface I18nContextValue {
  t: TranslatorFn;
  locale: () => Locale;
  setLocale: (l: Locale) => void;
}

const I18nContext = createContext<I18nContextValue>();

export const I18nProvider: ParentComponent = (props) => {
  const [locale, setLocaleSignal] = createSignal<Locale>(detectLocale());

  const flatDict = createMemo(() => flatten(dictionaries[locale()]));
  const t = translator(flatDict) as TranslatorFn;

  const setLocale = (l: Locale) => {
    setLocaleSignal(l);
    localStorage.setItem("locale", l);
    document.documentElement.lang = l;
  };

  // 初期 lang 属性を設定
  document.documentElement.lang = locale();

  return (
    <I18nContext.Provider value={{ t, locale, setLocale }}>
      {props.children}
    </I18nContext.Provider>
  );
};

export function useI18n(): I18nContextValue {
  const ctx = useContext(I18nContext);
  if (!ctx) throw new Error("useI18n must be used within I18nProvider");
  return ctx;
}
