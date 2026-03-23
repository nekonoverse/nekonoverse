import { Show } from "solid-js";
import { useI18n } from "@nekonoverse/ui/i18n";

export interface EmojiEditFields {
  shortcode: string;
  category: string;
  author: string;
  license: string;
  description: string;
  isSensitive: boolean;
  aliases: string;
}

interface Props {
  fields: EmojiEditFields;
  onChange: (fields: EmojiEditFields) => void;
  /** Show copy_permission & local_only (admin-only fields) */
  showAdminFields?: boolean;
  copyPermission?: string;
  onCopyPermissionChange?: (v: string) => void;
  localOnly?: boolean;
  onLocalOnlyChange?: (v: boolean) => void;
  /** Disable shortcode editing (e.g. when editing existing emoji) */
  shortcodeReadonly?: boolean;
  /** Optional preview image */
  previewUrl?: string | null;
  previewDomain?: string | null;
}

export default function EmojiEditForm(props: Props) {
  const { t } = useI18n();

  const update = (partial: Partial<EmojiEditFields>) => {
    props.onChange({ ...props.fields, ...partial });
  };

  return (
    <div class="emoji-edit-form">
      <Show when={props.previewUrl}>
        <div class="emoji-import-preview">
          <img
            src={props.previewUrl!}
            alt={`:${props.fields.shortcode}:`}
            style="height: 48px"
          />
          <Show when={props.previewDomain}>
            <span class="emoji-import-domain">{props.previewDomain}</span>
          </Show>
        </div>
      </Show>

      <label class="emoji-import-field">
        <span>{t("reactions.emojiShortcode")}</span>
        <input
          type="text"
          value={props.fields.shortcode}
          onInput={(e) => update({ shortcode: e.currentTarget.value })}
          pattern="[a-zA-Z0-9_]+"
          readonly={props.shortcodeReadonly}
        />
      </label>

      <div class="emoji-edit-form-row">
        <label class="emoji-import-field">
          <span>{t("reactions.emojiCategory")}</span>
          <input
            type="text"
            value={props.fields.category}
            onInput={(e) => update({ category: e.currentTarget.value })}
          />
        </label>
        <label class="emoji-import-field">
          <span>{t("reactions.emojiAliases")}</span>
          <input
            type="text"
            value={props.fields.aliases}
            onInput={(e) => update({ aliases: e.currentTarget.value })}
            placeholder="alias1, alias2"
          />
        </label>
      </div>

      <div class="emoji-edit-form-row">
        <label class="emoji-import-field">
          <span>{t("reactions.emojiAuthor")}</span>
          <input
            type="text"
            value={props.fields.author}
            onInput={(e) => update({ author: e.currentTarget.value })}
          />
        </label>
        <label class="emoji-import-field">
          <span>{t("reactions.emojiLicense")}</span>
          <input
            type="text"
            value={props.fields.license}
            onInput={(e) => update({ license: e.currentTarget.value })}
          />
        </label>
      </div>

      <label class="emoji-import-field">
        <span>{t("reactions.emojiDescription")}</span>
        <input
          type="text"
          value={props.fields.description}
          onInput={(e) => update({ description: e.currentTarget.value })}
        />
      </label>

      <div class="emoji-edit-form-row">
        <label class="emoji-import-checkbox">
          <input
            type="checkbox"
            checked={props.fields.isSensitive}
            onChange={(e) => update({ isSensitive: e.currentTarget.checked })}
          />
          {t("reactions.emojiSensitive")}
        </label>

        <Show when={props.showAdminFields}>
          <label class="emoji-import-checkbox">
            <input
              type="checkbox"
              checked={props.localOnly ?? false}
              onChange={(e) =>
                props.onLocalOnlyChange?.(e.currentTarget.checked)
              }
            />
            {t("admin.emojiLocalOnly")}
          </label>
        </Show>
      </div>

      <Show when={props.showAdminFields}>
        <label class="emoji-import-field">
          <span>{t("admin.emojiCopyPermission")}</span>
          <select
            value={props.copyPermission ?? ""}
            onChange={(e) =>
              props.onCopyPermissionChange?.(e.currentTarget.value)
            }
          >
            <option value="">--</option>
            <option value="allow">allow</option>
            <option value="deny">deny</option>
            <option value="conditional">conditional</option>
          </select>
        </label>
      </Show>
    </div>
  );
}
