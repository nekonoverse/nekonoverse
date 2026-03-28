import type { Visibility } from "@nekonoverse/ui/stores/composer";
import { useI18n } from "@nekonoverse/ui/i18n";

const OPTIONS: { key: Visibility; emoji: string; i18nKey: string }[] = [
  { key: "public", emoji: "\u{1F310}", i18nKey: "visibility.public" },
  { key: "unlisted", emoji: "\u{1F513}", i18nKey: "visibility.unlisted" },
  { key: "followers", emoji: "\u{1F512}", i18nKey: "visibility.followers" },
  { key: "direct", emoji: "\u2709\uFE0F", i18nKey: "visibility.direct" },
];

interface Props {
  value: Visibility;
  onChange: (v: Visibility) => void;
  /** セレクタから除外する公開範囲キー */
  exclude?: Visibility[];
}

export default function VisibilitySelector(props: Props) {
  const { t } = useI18n();
  const filtered = () => {
    const ex = props.exclude;
    return ex ? OPTIONS.filter((o) => !ex.includes(o.key)) : OPTIONS;
  };

  return (
    <select
      class="visibility-select"
      value={props.value}
      onChange={(e) => props.onChange(e.currentTarget.value as Visibility)}
    >
      {filtered().map((opt) => (
        <option value={opt.key}>
          {opt.emoji} {t(opt.i18nKey as any)}
        </option>
      ))}
    </select>
  );
}
