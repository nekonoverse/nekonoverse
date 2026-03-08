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

export default function UserHoverCard(props: Props) {
  const { t } = useI18n();
  const [visible, setVisible] = createSignal(false);
  const [account, setAccount] = createSignal<Account | null>(null);
  const [followLoading, setFollowLoading] = createSignal(false);
  const [showUnfollowModal, setShowUnfollowModal] = createSignal(false);
  let showTimer: number | undefined;
  let hideTimer: number | undefined;

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

  const handleMouseEnter = () => {
    clearTimeout(hideTimer);
    showTimer = window.setTimeout(() => {
      setVisible(true);
      if (!account()) fetchAccount();
    }, 300);
  };

  const handleMouseLeave = () => {
    clearTimeout(showTimer);
    hideTimer = window.setTimeout(() => setVisible(false), 200);
  };

  onCleanup(() => {
    clearTimeout(showTimer);
    clearTimeout(hideTimer);
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
      onMouseEnter={handleMouseEnter}
      onMouseLeave={handleMouseLeave}
    >
      {props.children}
      <Show when={visible()}>
        <div
          class="hover-card"
          onMouseEnter={() => clearTimeout(hideTimer)}
          onMouseLeave={handleMouseLeave}
        >
          <Show when={account()} fallback={<div class="hover-card-loading" />}>
            {(() => {
              const acc = account()!;
              return (
                <>
                  <div class="hover-card-header">
                    <img
                      class="hover-card-avatar"
                      src={acc.avatar || "/default-avatar.svg"}
                      alt=""
                    />
                    <div class="hover-card-names">
                      <strong class="hover-card-display-name">
                        {acc.display_name || acc.username}
                      </strong>
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
