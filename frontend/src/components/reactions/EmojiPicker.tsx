import { createSignal, onMount, onCleanup, Show, For } from "solid-js";
import { getCustomEmojis, type CustomEmoji } from "../../api/emoji";
import Emoji from "../Emoji";
import { useI18n } from "../../i18n";

const EMOJI_LIST = [
  "\u{1F44D}", "\u2764\uFE0F", "\u{1F602}", "\u{1F60D}", "\u{1F62E}",
  "\u{1F622}", "\u{1F621}", "\u{1F44F}", "\u{1F525}", "\u{1F389}",
  "\u{1F914}", "\u{1F60E}", "\u{1F631}", "\u{1F4AF}", "\u{1F440}",
  "\u{1F64F}", "\u{1F680}", "\u{1F31F}", "\u{1F43E}", "\u{1F431}",
];

interface Props {
  onSelect: (emoji: string) => void;
  onClose: () => void;
  usedEmojis?: string[];
}

export default function EmojiPicker(props: Props) {
  const { t } = useI18n();
  let ref: HTMLDivElement | undefined;
  let searchRef: HTMLInputElement | undefined;
  const [query, setQuery] = createSignal("");
  const [customEmojis, setCustomEmojis] = createSignal<CustomEmoji[]>([]);
  const [tab, setTab] = createSignal<"unicode" | "custom">("unicode");

  const isUsed = (emoji: string) => props.usedEmojis?.includes(emoji) ?? false;

  onMount(() => {
    const handleClick = (e: MouseEvent) => {
      if (ref && !ref.contains(e.target as Node)) {
        props.onClose();
      }
    };
    document.addEventListener("mousedown", handleClick);
    onCleanup(() => document.removeEventListener("mousedown", handleClick));

    getCustomEmojis().then((emojis) => setCustomEmojis(emojis)).catch(() => {});

    // Auto-focus search when switching to custom tab
    searchRef?.focus();
  });

  const filteredCustom = () => {
    const q = query().toLowerCase();
    if (!q) return customEmojis();
    return customEmojis().filter((e) =>
      e.shortcode.toLowerCase().includes(q) ||
      e.aliases?.some((a) => a.toLowerCase().includes(q)) ||
      e.category?.toLowerCase().includes(q)
    );
  };

  // Group filtered custom emojis by category
  const groupedCustom = () => {
    const emojis = filteredCustom();
    const groups = new Map<string, CustomEmoji[]>();
    for (const e of emojis) {
      const cat = e.category || "";
      if (!groups.has(cat)) groups.set(cat, []);
      groups.get(cat)!.push(e);
    }
    return groups;
  };

  const selectCustom = (emoji: CustomEmoji) => {
    props.onSelect(`:${emoji.shortcode}:`);
    props.onClose();
  };

  return (
    <div class="emoji-picker" ref={ref}>
      <div class="emoji-picker-tabs">
        <button
          class={`emoji-picker-tab${tab() === "unicode" ? " active" : ""}`}
          onClick={() => setTab("unicode")}
        >
          {t("reactions.unicode")}
        </button>
        <button
          class={`emoji-picker-tab${tab() === "custom" ? " active" : ""}`}
          onClick={() => { setTab("custom"); setTimeout(() => searchRef?.focus(), 0); }}
        >
          {t("reactions.custom")}
        </button>
      </div>

      <Show when={tab() === "unicode"}>
        <div class="emoji-grid">
          {EMOJI_LIST.map((emoji) => (
            <button
              class={`emoji-btn${isUsed(emoji) ? " emoji-used" : ""}`}
              disabled={isUsed(emoji)}
              onClick={() => {
                props.onSelect(emoji);
                props.onClose();
              }}
            >
              <Emoji emoji={emoji} />
            </button>
          ))}
        </div>
      </Show>

      <Show when={tab() === "custom"}>
        <input
          ref={searchRef}
          class="emoji-search"
          type="text"
          placeholder={t("reactions.searchEmoji")}
          value={query()}
          onInput={(e) => setQuery(e.currentTarget.value)}
        />
        <div class="emoji-custom-list">
          <Show
            when={filteredCustom().length > 0}
            fallback={
              <div class="emoji-custom-empty">
                {customEmojis().length === 0
                  ? t("reactions.noCustomEmoji")
                  : t("reactions.noResults")}
              </div>
            }
          >
            <For each={[...groupedCustom().entries()]}>
              {([category, emojis]) => (
                <>
                  <Show when={category}>
                    <div class="emoji-category-label">{category}</div>
                  </Show>
                  <div class="emoji-grid">
                    <For each={emojis}>
                      {(emoji) => (
                        <button
                          class={`emoji-btn${isUsed(`:${emoji.shortcode}:`) ? " emoji-used" : ""}`}
                          disabled={isUsed(`:${emoji.shortcode}:`)}
                          onClick={() => selectCustom(emoji)}
                          title={`:${emoji.shortcode}:`}
                        >
                          <img class="custom-emoji" src={emoji.url} alt={`:${emoji.shortcode}:`} draggable={false} />
                        </button>
                      )}
                    </For>
                  </div>
                </>
              )}
            </For>
          </Show>
        </div>
      </Show>
    </div>
  );
}
