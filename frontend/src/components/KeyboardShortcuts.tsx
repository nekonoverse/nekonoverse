import { onMount, onCleanup } from "solid-js";

interface Props {
  onCompose?: () => void;
}

/**
 * Global keyboard shortcuts handler.
 * - j/k: Focus next/previous note in timeline
 * - n: Open compose modal
 * - Esc: Close modal (handled by ComposeModal itself)
 * - f: Bookmark focused note
 * - r: Open reaction picker on focused note
 * - q: Quote focused note
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
    // Remove previous focus
    document.querySelectorAll(".note-card.keyboard-focused").forEach((el) => {
      el.classList.remove("keyboard-focused");
    });

    if (index >= 0 && index < cards.length) {
      const card = cards[index];
      card.classList.add("keyboard-focused");
      // Account for sticky navbar height when scrolling
      const navbar = document.querySelector(".navbar");
      const navbarHeight = navbar ? navbar.getBoundingClientRect().height : 0;
      const cardRect = card.getBoundingClientRect();
      if (cardRect.top < navbarHeight) {
        window.scrollBy({ top: cardRect.top - navbarHeight - 8, behavior: "smooth" });
      } else if (cardRect.bottom > window.innerHeight) {
        card.scrollIntoView({ block: "end", behavior: "smooth" });
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

  const handleKeyDown = (e: KeyboardEvent) => {
    if (isInputFocused()) return;

    // Don't intercept when modifier keys are held (except Shift for some)
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
      case "n": {
        e.preventDefault();
        props.onCompose?.();
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
      case "q": {
        if (currentIndex >= 0) {
          e.preventDefault();
          clickButton(cards[currentIndex], ".note-quote-btn");
        }
        break;
      }
      case "g": {
        e.preventDefault();
        window.scrollTo({ top: 0, behavior: "smooth" });
        // Clear focus when going to top
        document.querySelectorAll(".note-card.keyboard-focused").forEach((el) => {
          el.classList.remove("keyboard-focused");
        });
        break;
      }
    }
  };

  onMount(() => {
    document.addEventListener("keydown", handleKeyDown);
  });

  onCleanup(() => {
    document.removeEventListener("keydown", handleKeyDown);
    // Clean up focus markers
    document.querySelectorAll(".note-card.keyboard-focused").forEach((el) => {
      el.classList.remove("keyboard-focused");
    });
  });

  return null;
}
