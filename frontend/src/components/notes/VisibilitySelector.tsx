import type { Visibility } from "../../stores/composer";
import { useI18n } from "../../i18n";

const OPTIONS: { key: Visibility; emoji: string; i18nKey: string }[] = [
  { key: "public", emoji: "\u{1F310}", i18nKey: "visibility.public" },
  { key: "unlisted", emoji: "\u{1F513}", i18nKey: "visibility.unlisted" },
  { key: "followers", emoji: "\u{1F512}", i18nKey: "visibility.followers" },
  { key: "direct", emoji: "\u2709\uFE0F", i18nKey: "visibility.direct" },
];

interface Props {
  value: Visibility;
  onChange: (v: Visibility) => void;
}

export default function VisibilitySelector(props: Props) {
  const { t } = useI18n();

  return (
    <select
      class="visibility-select"
      value={props.value}
      onChange={(e) => props.onChange(e.currentTarget.value as Visibility)}
    >
      {OPTIONS.map((opt) => (
        <option value={opt.key}>
          {opt.emoji} {t(opt.i18nKey as any)}
        </option>
      ))}
    </select>
  );
}
