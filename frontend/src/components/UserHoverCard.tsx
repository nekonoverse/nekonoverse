import { createSignal, onCleanup, Show } from "solid-js";
import { getAccount, followAccount, unfollowAccount, type Account } from "../api/accounts";
import { isFollowing, addFollowedId, removeFollowedId } from "../stores/followedUsers";
import { currentUser } from "../stores/auth";
import { useI18n } from "../i18n";

interface Props {
  actorId: string;
  children: any;
}

// Simple in-memory cache
const cache = new Map<string, Account>();

// Detect touch-primary device (no hover capability)
const isTouchDevice = () =>
  typeof window !== "undefined" &&
  (("ontouchstart" in window) || window.matchMedia("(hover: none)").matches);

export default function UserHoverCard(props: Props) {
  const { t } = useI18n();
  const [visible, setVisible] = createSignal(false);
  const [account, setAccount] = createSignal<Account | null>(null);
  const [followLoading, setFollowLoading] = createSignal(false);
  const [showUnfollowModal, setShowUnfollowModal] = createSignal(false);
  let showTimer: number | undefined;
  let hideTimer: number | undefined;
  let longPressTimer: number | undefined;
  let longPressTriggered = false;
  let wrapperEl: HTMLSpanElement | undefined;
  let cardEl: HTMLDivElement | undefined;

  const fetchAccount = async () => {
    const cached = cache.get(props.actorId);
    if (cached) {
      setAccount(cached);
      return;
    }
    try {
      const acc = await getAccount(props.actorId);
      cache.set(props.actorId, acc);
      setAccount(acc);
    } catch {}
  };

  // --- Click handler: desktop only (タッチデバイスはtouchイベントで処理) ---
  const handleClick = (e: MouseEvent) => {
    if (isTouchDevice()) {
      e.preventDefault();
      return;
    }
    e.preventDefault();
    e.stopPropagation();
    if (visible()) {
      setVisible(false);
    } else {
      setVisible(true);
      if (!account()) fetchAccount();
    }
  };

  // --- Desktop: mouse hover handlers ---
  const handleMouseEnter = () => {
    if (isTouchDevice()) return;
    clearTimeout(hideTimer);
    showTimer = window.setTimeout(() => {
      setVisible(true);
      if (!account()) fetchAccount();
    }, 300);
  };

  const handleMouseLeave = () => {
    if (isTouchDevice()) return;
    clearTimeout(showTimer);
    hideTimer = window.setTimeout(() => setVisible(false), 200);
  };

  // --- Touch: long-press handlers ---
  const handleTouchStart = (e: TouchEvent) => {
    if (!isTouchDevice()) return;
    longPressTriggered = false;
    longPressTimer = window.setTimeout(() => {
      longPressTriggered = true;
      // Prevent subsequent click from navigating
      e.preventDefault();
      setVisible(true);
      if (!account()) fetchAccount();
    }, 500);
  };

  const handleTouchEnd = (e: TouchEvent) => {
    if (!isTouchDevice()) return;
    clearTimeout(longPressTimer);
    if (longPressTriggered) {
      // Prevent the tap from navigating to the profile after long-press
      e.preventDefault();
      longPressTriggered = false;
    } else if (!visible()) {
      // 短いタップでカードを表示
      e.preventDefault();
      setVisible(true);
      if (!account()) fetchAccount();
    }
  };

  const handleTouchMove = () => {
    // Cancel long-press if finger moves (user is scrolling)
    clearTimeout(longPressTimer);
    longPressTriggered = false;
  };

  // タッチデバイスでのカード外タップはbackdropのonClickで処理するため、
  // documentレベルのtouchstartリスナーは不要

  // --- Positioning for mobile: adjust card so it doesn't overflow viewport ---
  const adjustCardPosition = (el: HTMLDivElement) => {
    cardEl = el;
    if (typeof window === "undefined") return;
    // Use requestAnimationFrame to ensure the element is rendered
    requestAnimationFrame(() => {
      const rect = el.getBoundingClientRect();
      const vw = window.innerWidth;

      // Reset any previous inline positioning
      el.style.left = "";
      el.style.right = "";

      if (rect.right > vw - 8) {
        // Card overflows right edge
        el.style.left = "auto";
        el.style.right = "0";
        // Re-check after moving
        const newRect = el.getBoundingClientRect();
        if (newRect.left < 8) {
          el.style.right = "auto";
          el.style.left = `-${rect.left - 8}px`;
        }
      } else if (rect.left < 8) {
        // Card overflows left edge
        el.style.left = `-${rect.left - 8}px`;
      }
    });
  };

  onCleanup(() => {
    clearTimeout(showTimer);
    clearTimeout(hideTimer);
    clearTimeout(longPressTimer);
  });

  const isOwnAccount = () => {
    const user = currentUser();
    const acc = account();
    if (!user || !acc) return true; // hide button until loaded
    return user.username === acc.username && !acc.acct.includes("@");
  };

  const followed = () => isFollowing(props.actorId);

  const handleFollow = async () => {
    setFollowLoading(true);
    try {
      await followAccount(props.actorId);
      addFollowedId(props.actorId);
    } catch {}
    setFollowLoading(false);
  };

  const handleUnfollow = async () => {
    setFollowLoading(true);
    try {
      await unfollowAccount(props.actorId);
      removeFollowedId(props.actorId);
    } catch {}
    setFollowLoading(false);
    setShowUnfollowModal(false);
  };

  return (
    <span
      class="hover-card-wrapper"
      ref={(el) => { wrapperEl = el; }}
      onClick={handleClick}
      onMouseEnter={handleMouseEnter}
      onMouseLeave={handleMouseLeave}
      onTouchStart={handleTouchStart}
      onTouchEnd={handleTouchEnd}
      onTouchMove={handleTouchMove}
    >
      {props.children}
      {/* Mobile backdrop overlay for tap-outside-to-close (rendered outside wrapper via portal-like fixed positioning) */}
      <Show when={visible() && isTouchDevice()}>
        <div
          class="hover-card-backdrop"
          onTouchStart={(e) => { e.stopPropagation(); }}
          onTouchEnd={(e) => { e.preventDefault(); e.stopPropagation(); setVisible(false); }}
          onClick={(e) => { e.stopPropagation(); setVisible(false); }}
        />
      </Show>
      <Show when={visible()}>
        <div
          class={`hover-card${isTouchDevice() ? " hover-card-touch" : ""}`}
          ref={adjustCardPosition}
          onMouseEnter={() => clearTimeout(hideTimer)}
          onMouseLeave={handleMouseLeave}
        >
          <Show when={account()} fallback={<div class="hover-card-loading" />}>
            {(() => {
              const acc = account()!;
              return (
                <>
                  <div class="hover-card-header">
                    <a href={`/@${acc.acct}`} class="hover-card-avatar-link">
                      <img
                        class="hover-card-avatar"
                        src={acc.avatar || "/default-avatar.svg"}
                        alt=""
                      />
                    </a>
                    <div class="hover-card-names">
                      <a href={`/@${acc.acct}`} class="hover-card-name-link">
                        <strong class="hover-card-display-name">
                          {acc.display_name || acc.username}
                        </strong>
                      </a>
                      <span class="hover-card-handle">@{acc.acct}</span>
                    </div>
                  </div>
                  <Show when={acc.note}>
                    <p class="hover-card-bio" innerHTML={acc.note} />
                  </Show>
                  <Show when={currentUser() && !isOwnAccount()}>
                    <div class="hover-card-actions">
                      <Show
                        when={followed()}
                        fallback={
                          <button
                            class="hover-card-follow-btn"
                            onClick={handleFollow}
                            disabled={followLoading()}
                          >
                            {t("profile.follow")}
                          </button>
                        }
                      >
                        <button
                          class="hover-card-follow-btn following"
                          onClick={() => setShowUnfollowModal(true)}
                        >
                          {t("profile.following")}
                        </button>
                      </Show>
                    </div>
                  </Show>
                </>
              );
            })()}
          </Show>
        </div>
      </Show>

      {/* Unfollow confirmation modal */}
      <Show when={showUnfollowModal()}>
        <div class="modal-overlay" onClick={() => setShowUnfollowModal(false)}>
          <div class="modal-content" style="max-width: 360px" onClick={(e) => e.stopPropagation()}>
            <div class="modal-header">
              <h3>{t("profile.confirmUnfollow")}</h3>
              <button class="modal-close" onClick={() => setShowUnfollowModal(false)}>✕</button>
            </div>
            <div style="padding: 16px; display: flex; gap: 8px; justify-content: flex-end">
              <button class="btn btn-small" onClick={() => setShowUnfollowModal(false)}>
                {t("common.cancel")}
              </button>
              <button
                class="btn btn-small btn-danger"
                disabled={followLoading()}
                onClick={handleUnfollow}
              >
                {t("profile.unfollow")}
              </button>
            </div>
          </div>
        </div>
      </Show>
    </span>
  );
}
