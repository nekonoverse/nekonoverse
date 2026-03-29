import { createSignal, createMemo, createEffect, onMount, onCleanup, Show, For } from "solid-js";
import { getCustomEmojis, type CustomEmoji } from "@nekonoverse/ui/api/emoji";
import { UNICODE_EMOJIS, type UnicodeEmojiDef } from "../../data/unicode-emojis";
import {
  getRecentEmojis,
  addRecentEmoji,
  type RecentEmoji,
} from "@nekonoverse/ui/utils/recentEmojis";
import Emoji from "../Emoji";

type SuggestItem =
  | { type: "custom"; emoji: CustomEmoji }
  | { type: "unicode"; def: UnicodeEmojiDef }
  | { type: "recent"; entry: RecentEmoji };

interface Props {
  query: string;
  onSelect: (text: string) => void;
  onClose: () => void;
  /** 親コンポーネントがキーボードハンドラをバインドするために呼び出す */
  bindKeyHandler?: (handler: (e: KeyboardEvent) => boolean) => void;
}

const MAX_RESULTS = 10;

export default function EmojiSuggest(props: Props) {
  const [customEmojis, setCustomEmojis] = createSignal<CustomEmoji[]>([]);
  const [activeIndex, setActiveIndex] = createSignal(0);

  onMount(() => {
    getCustomEmojis().then(setCustomEmojis).catch(() => {});
  });

  const items = createMemo((): SuggestItem[] => {
    const q = props.query.toLowerCase();

    if (!q) {
      // クエリが空の場合（「:」を入力しただけ）は最近使った絵文字を表示
      return getRecentEmojis()
        .slice(0, MAX_RESULTS)
        .map((e) => ({ type: "recent" as const, entry: e }));
    }

    const results: SuggestItem[] = [];

    // カスタム絵文字を優先（優先度が高い）
    for (const e of customEmojis()) {
      if (results.length >= MAX_RESULTS) break;
      if (
        e.shortcode.toLowerCase().includes(q) ||
        e.aliases?.some((a) => a.toLowerCase().includes(q)) ||
        e.category?.toLowerCase().includes(q)
      ) {
        results.push({ type: "custom", emoji: e });
      }
    }

    // Unicode絵文字
    for (const e of UNICODE_EMOJIS) {
      if (results.length >= MAX_RESULTS) break;
      if (
        e.shortcode.includes(q) ||
        e.keywords.some((k) => k.includes(q)) ||
        e.emoji === q
      ) {
        results.push({ type: "unicode", def: e });
      }
    }

    return results;
  });

  // アイテムが変わったらアクティブインデックスをリセット
  createEffect(() => {
    items();
    setActiveIndex(0);
  });

  const handleSelect = (item: SuggestItem) => {
    let text: string;
    switch (item.type) {
      case "custom":
        text = `:${item.emoji.shortcode}:`;
        addRecentEmoji({
          emoji: text,
          isCustom: true,
          url: item.emoji.url,
          shortcode: item.emoji.shortcode,
        });
        break;
      case "unicode":
        text = item.def.emoji;
        addRecentEmoji({
          emoji: text,
          isCustom: false,
          shortcode: item.def.shortcode,
        });
        break;
      case "recent":
        text = item.entry.emoji;
        addRecentEmoji(item.entry);
        break;
    }
    props.onSelect(text);
  };

  // 親コンポーネントから呼ばれるキーボードハンドラ
  const handleKeyDown = (e: KeyboardEvent): boolean => {
    const list = items();
    if (list.length === 0) return false;

    switch (e.key) {
      case "ArrowDown":
        e.preventDefault();
        setActiveIndex((i) => (i + 1) % list.length);
        return true;
      case "ArrowUp":
        e.preventDefault();
        setActiveIndex((i) => (i - 1 + list.length) % list.length);
        return true;
      case "Enter":
      case "Tab":
        e.preventDefault();
        handleSelect(list[activeIndex()]);
        return true;
      case "Escape":
        e.preventDefault();
        props.onClose();
        return true;
      default:
        return false;
    }
  };

  // ハンドラを親にバインド
  onMount(() => {
    props.bindKeyHandler?.(handleKeyDown);
  });
  onCleanup(() => {
    props.bindKeyHandler?.(() => false);
  });

  // アクティブなアイテムをスクロールして表示
  let listRef: HTMLDivElement | undefined;
  createEffect(() => {
    const idx = activeIndex();
    const el = listRef?.children[idx] as HTMLElement | undefined;
    el?.scrollIntoView({ block: "nearest" });
  });

  return (
    <Show when={items().length > 0}>
      <div class="emoji-suggest" ref={listRef}>
        <For each={items()}>
          {(item, i) => (
            <div
              class={`emoji-suggest-item${i() === activeIndex() ? " active" : ""}`}
              onMouseEnter={() => setActiveIndex(i())}
              onClick={() => handleSelect(item)}
            >
              {item.type === "custom" ? (
                <>
                  <img
                    class="custom-emoji"
                    src={item.emoji.url}
                    alt={`:${item.emoji.shortcode}:`}
                    draggable={false}
                  />
                  <span class="emoji-suggest-shortcode">
                    :{item.emoji.shortcode}:
                  </span>
                </>
              ) : item.type === "unicode" ? (
                <>
                  <Emoji emoji={item.def.emoji} />
                  <span class="emoji-suggest-shortcode">
                    :{item.def.shortcode}:
                  </span>
                </>
              ) : (
                <>
                  {item.entry.isCustom && item.entry.url ? (
                    <img
                      class="custom-emoji"
                      src={item.entry.url}
                      alt={item.entry.emoji}
                      draggable={false}
                    />
                  ) : (
                    <Emoji emoji={item.entry.emoji} />
                  )}
                  <span class="emoji-suggest-shortcode">
                    {item.entry.shortcode
                      ? `:${item.entry.shortcode}:`
                      : item.entry.emoji}
                  </span>
                </>
              )}
            </div>
          )}
        </For>
      </div>
    </Show>
  );
}
