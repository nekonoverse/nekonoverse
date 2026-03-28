import { onMount, onCleanup } from "solid-js";

interface Props {
  onCompose?: () => void;
  onQuote?: (noteId: string) => void;
  onReply?: (noteId: string) => void;
  onSearch?: () => void;
  onNavigate?: (path: string) => void;
  /** すべてのショートカットを無効化する（例: モーダルが開いている時） */
  disabled?: boolean;
}

/**
 * グローバルキーボードショートカットハンドラー
 * - j/k: タイムラインの次/前のノートにフォーカス
 * - g: トップにスクロール
 * - n: 投稿モーダルを開く（新規）
 * - q: 引用付き投稿モーダルを開く（フォーカス中のノート）
 * - t: 返信付き投稿モーダルを開く（フォーカス中のノート）
 * - f: フォーカス中のノートをブックマーク
 * - r: フォーカス中のノートでリアクションピッカーを開く
 * - h: ホームタイムラインに移動
 * - p: 公開タイムラインに移動
 * - u: ユーザー検索を開く
 */
export default function KeyboardShortcuts(props: Props) {
  const isInputFocused = () => {
    const el = document.activeElement;
    if (!el) return false;
    const tag = el.tagName.toLowerCase();
    if (tag === "input" || tag === "textarea" || tag === "select") return true;
    if ((el as HTMLElement).isContentEditable) return true;
    return false;
  };

  const getNoteCards = (): HTMLElement[] => {
    return Array.from(document.querySelectorAll<HTMLElement>(".note-card"));
  };

  const getFocusedIndex = (cards: HTMLElement[]): number => {
    const focused = document.querySelector(".note-card.keyboard-focused");
    if (!focused) return -1;
    return cards.indexOf(focused as HTMLElement);
  };

  const setFocus = (cards: HTMLElement[], index: number) => {
    document.querySelectorAll(".note-card.keyboard-focused").forEach((el) => {
      el.classList.remove("keyboard-focused");
    });

    if (index >= 0 && index < cards.length) {
      const card = cards[index];
      card.classList.add("keyboard-focused");

      // scrollIntoView({ block: "nearest" }) は要素が部分的に表示されている場合、
      // 固定ナビバーを考慮しない。手動スクロールでカードがナビバーの下に
      // 完全に表示されるようにする。
      const navbar = document.querySelector<HTMLElement>(".navbar");
      const navH = navbar ? navbar.getBoundingClientRect().height : 0;
      const rect = card.getBoundingClientRect();
      if (rect.top < navH) {
        // カードがナビバーの裏に隠れている — マージン付きでスクロール表示
        window.scrollBy({ top: rect.top - navH - 4 });
      } else if (rect.bottom > window.innerHeight) {
        // カードがビューポートの下にある — 最小限のスクロールで表示
        card.scrollIntoView({ block: "nearest" });
      }
    }
  };

  const clickButton = (card: HTMLElement, selector: string): boolean => {
    const btn = card.querySelector<HTMLElement>(selector);
    if (btn) {
      btn.click();
      return true;
    }
    return false;
  };

  const getFocusedNoteId = (cards: HTMLElement[], index: number): string | null => {
    if (index < 0 || index >= cards.length) return null;
    return cards[index].getAttribute("data-note-id");
  };

  const handleKeyDown = (e: KeyboardEvent) => {
    if (props.disabled) return;
    if (isInputFocused()) return;
    if (e.ctrlKey || e.altKey || e.metaKey) return;

    const cards = getNoteCards();
    const currentIndex = getFocusedIndex(cards);

    switch (e.key) {
      case "j": {
        e.preventDefault();
        const next = currentIndex + 1;
        if (next < cards.length) {
          setFocus(cards, next);
        } else if (cards.length > 0 && currentIndex === -1) {
          setFocus(cards, 0);
        }
        break;
      }
      case "k": {
        e.preventDefault();
        if (currentIndex > 0) {
          setFocus(cards, currentIndex - 1);
        }
        break;
      }
      case "g": {
        e.preventDefault();
        window.scrollTo({ top: 0 });
        document.querySelectorAll(".note-card.keyboard-focused").forEach((el) => {
          el.classList.remove("keyboard-focused");
        });
        break;
      }
      case "n": {
        e.preventDefault();
        props.onCompose?.();
        break;
      }
      case "q": {
        if (currentIndex >= 0) {
          e.preventDefault();
          const noteId = getFocusedNoteId(cards, currentIndex);
          if (noteId) props.onQuote?.(noteId);
        }
        break;
      }
      case "t": {
        if (currentIndex >= 0) {
          e.preventDefault();
          const noteId = getFocusedNoteId(cards, currentIndex);
          if (noteId) props.onReply?.(noteId);
        }
        break;
      }
      case "f": {
        if (currentIndex >= 0) {
          e.preventDefault();
          clickButton(cards[currentIndex], ".note-bookmark-btn");
        }
        break;
      }
      case "r": {
        if (currentIndex >= 0) {
          e.preventDefault();
          clickButton(cards[currentIndex], ".reaction-add-btn");
        }
        break;
      }
      case "h": {
        e.preventDefault();
        props.onNavigate?.("/?tl=home");
        break;
      }
      case "p": {
        e.preventDefault();
        props.onNavigate?.("/");
        break;
      }
      case "u": {
        e.preventDefault();
        props.onSearch?.();
        break;
      }
    }
  };

  onMount(() => {
    document.addEventListener("keydown", handleKeyDown);
  });

  onCleanup(() => {
    document.removeEventListener("keydown", handleKeyDown);
    document.querySelectorAll(".note-card.keyboard-focused").forEach((el) => {
      el.classList.remove("keyboard-focused");
    });
  });

  return null;
}
