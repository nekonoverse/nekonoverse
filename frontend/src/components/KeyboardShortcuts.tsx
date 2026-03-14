import { onMount, onCleanup } from "solid-js";

interface Props {
  onCompose?: () => void;
  onQuote?: (noteId: string) => void;
  onReply?: (noteId: string) => void;
  onSearch?: () => void;
  onNavigate?: (path: string) => void;
}

/**
 * Global keyboard shortcuts handler.
 * - j/k: Focus next/previous note in timeline
 * - g: Scroll to top
 * - n: Open compose modal (new)
 * - q: Open compose modal with quote (focused note)
 * - t: Open compose modal with reply (focused note)
 * - f: Bookmark focused note
 * - r: Open reaction picker on focused note
 * - h: Navigate to home timeline
 * - p: Navigate to public timeline
 * - u: Open user search
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
      card.scrollIntoView({ block: "nearest" });
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
