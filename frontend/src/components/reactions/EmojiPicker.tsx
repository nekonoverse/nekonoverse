import {
  createSignal,
  createMemo,
  onMount,
  onCleanup,
  Show,
  For,
  type JSX,
} from "solid-js";
import { getCustomEmojis, type CustomEmoji } from "../../api/emoji";
import {
  UNICODE_EMOJIS,
  EMOJI_CATEGORIES,
  UNICODE_BY_CATEGORY,
  type UnicodeEmojiDef,
} from "../../data/unicode-emojis";
import {
  getRecentEmojis,
  addRecentEmoji,
  type RecentEmoji,
} from "../../utils/recentEmojis";
import Emoji from "../Emoji";
import { useI18n } from "../../i18n";

// スクロールで近づいた時だけ中身をレンダリングするコンポーネント
function LazyCategory(props: {
  estimatedHeight: number;
  children: JSX.Element;
}) {
  const [visible, setVisible] = createSignal(false);
  let sentinel!: HTMLDivElement;

  onMount(() => {
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setVisible(true);
          observer.disconnect();
        }
      },
      { rootMargin: "200px" },
    );
    observer.observe(sentinel);
    onCleanup(() => observer.disconnect());
  });

  return (
    <div ref={sentinel}>
      <Show
        when={visible()}
        fallback={<div style={{ height: `${props.estimatedHeight}px` }} />}
      >
        {props.children}
      </Show>
    </div>
  );
}

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
  const [recentEmojis, setRecentEmojis] =
    createSignal<RecentEmoji[]>(getRecentEmojis());

  // iOSのゴーストタップ防止: タッチデバイスでのみ300ms間クリックをブロック
  const isTouchDevice =
    typeof window !== "undefined" &&
    ("ontouchstart" in window || navigator.maxTouchPoints > 0);
  const [ready, setReady] = createSignal(!isTouchDevice);
  const readyTimer = isTouchDevice
    ? setTimeout(() => setReady(true), 300)
    : undefined;
  onCleanup(() => {
    if (readyTimer !== undefined) clearTimeout(readyTimer);
  });

  const isUsed = (emoji: string) => props.usedEmojis?.includes(emoji) ?? false;

  onMount(() => {
    const handleClick = (e: MouseEvent | TouchEvent) => {
      const target = e.target as Node;
      if (ref && !ref.contains(target)) {
        props.onClose();
      }
    };
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") props.onClose();
    };
    document.addEventListener("mousedown", handleClick);
    document.addEventListener("touchstart", handleClick, { passive: true });
    document.addEventListener("keydown", handleKeyDown);
    onCleanup(() => {
      document.removeEventListener("mousedown", handleClick);
      document.removeEventListener("touchstart", handleClick);
      document.removeEventListener("keydown", handleKeyDown);
    });

    getCustomEmojis()
      .then((emojis) => setCustomEmojis(emojis))
      .catch(() => {});

    const isTouch = "ontouchstart" in window || navigator.maxTouchPoints > 0;
    if (!isTouch) {
      setTimeout(() => searchRef?.focus(), 0);
    }
  });

  // --- Searching ---

  const isSearching = () => query().trim().length > 0;

  const filteredUnicode = createMemo(() => {
    const q = query().toLowerCase().trim();
    if (!q) return [];
    return UNICODE_EMOJIS.filter(
      (e) =>
        e.shortcode.includes(q) ||
        e.keywords.some((k) => k.includes(q)) ||
        e.emoji === q,
    );
  });

  const filteredCustom = createMemo(() => {
    const q = query().toLowerCase().trim();
    if (!q) return [];
    return customEmojis().filter(
      (e) =>
        e.shortcode.toLowerCase().includes(q) ||
        e.aliases?.some((a) => a.toLowerCase().includes(q)) ||
        e.category?.toLowerCase().includes(q),
    );
  });

  // Group custom emojis by category (for browse mode)
  const groupedCustom = createMemo(() => {
    const emojis = customEmojis();
    const groups = new Map<string, CustomEmoji[]>();
    for (const e of emojis) {
      const cat = e.category || t("reactions.custom");
      if (!groups.has(cat)) groups.set(cat, []);
      groups.get(cat)!.push(e);
    }
    return groups;
  });

  // --- Selection handlers ---

  const selectUnicode = (def: UnicodeEmojiDef) => {
    if (!ready()) return;
    addRecentEmoji({
      emoji: def.emoji,
      isCustom: false,
      shortcode: def.shortcode,
    });
    setRecentEmojis(getRecentEmojis());
    props.onSelect(def.emoji);
    props.onClose();
  };

  const selectCustom = (emoji: CustomEmoji) => {
    if (!ready()) return;
    const emojiStr = `:${emoji.shortcode}:`;
    addRecentEmoji({
      emoji: emojiStr,
      isCustom: true,
      url: emoji.url,
      shortcode: emoji.shortcode,
    });
    setRecentEmojis(getRecentEmojis());
    props.onSelect(emojiStr);
    props.onClose();
  };

  const selectRecent = (recent: RecentEmoji) => {
    if (!ready()) return;
    addRecentEmoji(recent);
    setRecentEmojis(getRecentEmojis());
    props.onSelect(recent.emoji);
    props.onClose();
  };

  // --- Render helpers ---

  const renderUnicodeBtn = (def: UnicodeEmojiDef) => (
    <button
      class={`emoji-btn${isUsed(def.emoji) ? " emoji-used" : ""}`}
      disabled={isUsed(def.emoji)}
      onClick={() => selectUnicode(def)}
      title={`:${def.shortcode}:`}
    >
      <Emoji emoji={def.emoji} />
    </button>
  );

  const renderCustomBtn = (emoji: CustomEmoji) => (
    <button
      class={`emoji-btn${isUsed(`:${emoji.shortcode}:`) ? " emoji-used" : ""}`}
      disabled={isUsed(`:${emoji.shortcode}:`)}
      onClick={() => selectCustom(emoji)}
      title={`:${emoji.shortcode}:`}
    >
      <img
        class="custom-emoji"
        src={emoji.url}
        alt={`:${emoji.shortcode}:`}
        draggable={false}
      />
    </button>
  );

  const renderRecentBtn = (recent: RecentEmoji) => (
    <button
      class={`emoji-btn${isUsed(recent.emoji) ? " emoji-used" : ""}`}
      disabled={isUsed(recent.emoji)}
      onClick={() => selectRecent(recent)}
      title={recent.shortcode ? `:${recent.shortcode}:` : recent.emoji}
    >
      {recent.isCustom && recent.url ? (
        <img
          class="custom-emoji"
          src={recent.url}
          alt={recent.emoji}
          draggable={false}
        />
      ) : (
        <Emoji emoji={recent.emoji} />
      )}
    </button>
  );

  return (
    <div class="emoji-picker" ref={ref}>
      {/* Search bar — always visible */}
      <input
        ref={searchRef}
        class="emoji-search"
        type="text"
        placeholder={t("reactions.searchEmoji")}
        value={query()}
        onInput={(e) => setQuery(e.currentTarget.value)}
      />

      <div class="emoji-scroll-area">
        {/* --- Search results mode --- */}
        <Show when={isSearching()}>
          <Show
            when={filteredUnicode().length > 0 || filteredCustom().length > 0}
            fallback={
              <div class="emoji-custom-empty">{t("reactions.noResults")}</div>
            }
          >
            <div class="emoji-grid">
              <For each={filteredCustom()}>{(e) => renderCustomBtn(e)}</For>
              <For each={filteredUnicode()}>{(e) => renderUnicodeBtn(e)}</For>
            </div>
          </Show>
        </Show>

        {/* --- Browse mode --- */}
        <Show when={!isSearching()}>
          {/* Recently used */}
          <Show when={recentEmojis().length > 0}>
            <div class="emoji-category-label">
              {t("reactions.recentlyUsed")}
            </div>
            <div class="emoji-grid">
              <For each={recentEmojis()}>
                {(recent) => renderRecentBtn(recent)}
              </For>
            </div>
          </Show>

          {/* Custom emojis by category */}
          <Show when={customEmojis().length > 0}>
            <For each={[...groupedCustom().entries()]}>
              {([category, emojis]) => (
                <>
                  <div class="emoji-category-label">{category}</div>
                  <div class="emoji-grid">
                    <For each={emojis}>{(emoji) => renderCustomBtn(emoji)}</For>
                  </div>
                </>
              )}
            </For>
          </Show>

          {/* Unicode emoji categories (lazy-rendered per category) */}
          <For each={EMOJI_CATEGORIES}>
            {(cat) => {
              const emojis = UNICODE_BY_CATEGORY.get(cat.id) ?? [];
              // 各ボタン36px + gap 4px、8列グリッド + カテゴリラベル24px
              const rows = Math.ceil(emojis.length / 8);
              const estimatedHeight = rows * 40 + 24;
              return (
                <Show when={emojis.length > 0}>
                  <LazyCategory estimatedHeight={estimatedHeight}>
                    <div class="emoji-category-label">{cat.label}</div>
                    <div class="emoji-grid">
                      <For each={emojis}>{(def) => renderUnicodeBtn(def)}</For>
                    </div>
                  </LazyCategory>
                </Show>
              );
            }}
          </For>
        </Show>
      </div>
    </div>
  );
}
