import { createSignal, createEffect, onCleanup, Show, For } from "solid-js";
import { useNavigate } from "@solidjs/router";
import { getAccount, followAccount, unfollowAccount, blockAccount, muteAccount, type Account } from "@nekonoverse/ui/api/accounts";
import { getLists, addListAccounts, type ListInfo } from "@nekonoverse/ui/api/lists";
import { isFollowing, addFollowedId, removeFollowedId } from "@nekonoverse/ui/stores/followedUsers";
import { currentUser } from "@nekonoverse/ui/stores/auth";
import { useI18n } from "@nekonoverse/ui/i18n";
import { sanitizeHtml } from "@nekonoverse/ui/utils/sanitize";
import { emojify } from "@nekonoverse/ui/utils/emojify";
import { twemojify } from "@nekonoverse/ui/utils/twemojify";
import { externalLinksNewTab } from "@nekonoverse/ui/utils/linkify";
import { defaultAvatar, instance } from "@nekonoverse/ui/stores/instance";
import { activateTouchGuard } from "../utils/touchGuard";
import { isTouchMode } from "@nekonoverse/ui/stores/theme";

interface Props {
  actorId: string;
  children: any;
}

// メモリリーク防止のため最大サイズ付きLRUキャッシュ
const MAX_CACHE_SIZE = 100;
const cache = new Map<string, Account>();
function cacheSet(key: string, value: Account) {
  if (cache.size >= MAX_CACHE_SIZE) {
    // Mapのイテレーション順は挿入順なので、最初のキーを削除
    const firstKey = cache.keys().next().value;
    if (firstKey !== undefined) cache.delete(firstKey);
  }
  cache.set(key, value);
}

export default function UserHoverCard(props: Props) {
  const { t } = useI18n();
  const navigate = useNavigate();
  const [visible, setVisible] = createSignal(false);
  const [account, setAccount] = createSignal<Account | null>(null);
  const [followLoading, setFollowLoading] = createSignal(false);
  const [showUnfollowModal, setShowUnfollowModal] = createSignal(false);
  const [moreOpen, setMoreOpen] = createSignal(false);
  const [showAddToList, setShowAddToList] = createSignal(false);
  const [lists, setLists] = createSignal<ListInfo[]>([]);
  const [selectedListId, setSelectedListId] = createSignal("");
  const [addToListLoading, setAddToListLoading] = createSignal(false);
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
      cacheSet(props.actorId, acc);
      setAccount(acc);
    } catch {}
  };

  // --- Click handler: desktop only (タッチデバイスはtouchイベントで処理) ---
  const handleClick = (e: MouseEvent) => {
    if (isTouchMode()) {
      e.preventDefault();
      return;
    }
    e.preventDefault();
    e.stopPropagation();
    if (visible()) {
      // カードが表示中ならプロフィールページに遷移
      const acc = account();
      if (acc) {
        setVisible(false);
        navigate(`/@${acc.acct}`);
      } else {
        setVisible(false);
      }
    } else {
      setVisible(true);
      if (!account()) fetchAccount();
    }
  };

  // --- デスクトップ: マウスホバーハンドラ ---
  const handleMouseEnter = () => {
    if (isTouchMode()) return;
    clearTimeout(hideTimer);
    showTimer = window.setTimeout(() => {
      setVisible(true);
      if (!account()) fetchAccount();
    }, 300);
  };

  const handleMouseLeave = () => {
    if (isTouchMode()) return;
    clearTimeout(showTimer);
    hideTimer = window.setTimeout(() => setVisible(false), 200);
  };

  // --- タッチ: ロングプレスハンドラ ---
  const handleTouchStart = (e: TouchEvent) => {
    if (!isTouchMode()) return;
    longPressTriggered = false;
    longPressTimer = window.setTimeout(() => {
      longPressTriggered = true;
      activateTouchGuard();
      // 後続のクリックによるナビゲーションを防止
      e.preventDefault();
      setVisible(true);
      if (!account()) fetchAccount();
    }, 500);
  };

  const handleTouchEnd = (e: TouchEvent) => {
    if (!isTouchMode()) return;
    clearTimeout(longPressTimer);
    if (longPressTriggered) {
      // ロングプレス後のタップによるプロフィール遷移を防止
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
    // 指が動いたらロングプレスをキャンセル（ユーザーがスクロール中）
    clearTimeout(longPressTimer);
    longPressTriggered = false;
  };

  // タッチデバイスでのカード外タップはbackdropのonClickで処理するため、
  // documentレベルのtouchstartリスナーは不要

  // --- モバイル用の位置調整: カードがビューポートからはみ出さないように調整 ---
  const adjustCardPosition = (el: HTMLDivElement) => {
    cardEl = el;
    if (typeof window === "undefined") return;
    // requestAnimationFrameで要素がレンダリング済みであることを保証
    requestAnimationFrame(() => {
      const rect = el.getBoundingClientRect();
      const vw = window.innerWidth;

      // 以前のインラインポジショニングをリセット
      el.style.left = "";
      el.style.right = "";

      if (rect.right > vw - 8) {
        // カードが右端からはみ出す
        el.style.left = "auto";
        el.style.right = "0";
        // 移動後に再チェック
        const newRect = el.getBoundingClientRect();
        if (newRect.left < 8) {
          el.style.right = "auto";
          el.style.left = `-${rect.left - 8}px`;
        }
      } else if (rect.left < 8) {
        // カードが左端からはみ出す
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

  const handleBlock = async () => {
    setMoreOpen(false);
    if (!confirm(t("block.confirmBlock"))) return;
    try { await blockAccount(props.actorId); } catch {}
  };

  const handleMute = async () => {
    setMoreOpen(false);
    if (!confirm(t("block.confirmMute"))) return;
    try { await muteAccount(props.actorId); } catch {}
  };

  const handleAddToList = async () => {
    setMoreOpen(false);
    setShowAddToList(true);
    try { const data = await getLists(); setLists(data); } catch {}
  };

  const handleAddToListConfirm = async () => {
    const listId = selectedListId();
    if (!listId) return;
    setAddToListLoading(true);
    try {
      await addListAccounts(listId, [props.actorId]);
      setShowAddToList(false);
      setSelectedListId("");
    } catch {}
    setAddToListLoading(false);
  };

  // 外部クリックでその他メニューを閉じる
  const handleDocClick = (e: MouseEvent) => {
    const target = e.target as HTMLElement;
    if (!target.closest(".hover-card-more-menu")) {
      setMoreOpen(false);
    }
  };
  createEffect(() => {
    if (moreOpen()) {
      document.addEventListener("click", handleDocClick);
    } else {
      document.removeEventListener("click", handleDocClick);
    }
  });
  onCleanup(() => document.removeEventListener("click", handleDocClick));

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
      {/* モバイル用背景オーバーレイ: 外部タップで閉じる（ポータル風の固定配置でwrapper外にレンダリング） */}
      <Show when={visible() && isTouchMode()}>
        <div
          class="hover-card-backdrop"
          onTouchStart={(e) => { e.stopPropagation(); }}
          onTouchEnd={(e) => { e.preventDefault(); e.stopPropagation(); setVisible(false); }}
          onClick={(e) => { e.stopPropagation(); setVisible(false); }}
        />
      </Show>
      <Show when={visible()}>
        <div
          class={`hover-card${isTouchMode() ? " hover-card-touch" : ""}`}
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
                    <a href={`/@${acc.acct}`} class="hover-card-avatar-link" onClick={(e) => {
                      e.preventDefault();
                      e.stopPropagation();
                      setVisible(false);
                      navigate(`/@${acc.acct}`);
                    }}>
                      <img
                        class="hover-card-avatar"
                        src={acc.avatar || defaultAvatar()}
                        alt=""
                      />
                    </a>
                    <div class="hover-card-names">
                      <a href={`/@${acc.acct}`} class="hover-card-name-link" onClick={(e) => {
                        e.preventDefault();
                        e.stopPropagation();
                        setVisible(false);
                        navigate(`/@${acc.acct}`);
                      }}>
                        <strong class="hover-card-display-name" ref={(el) => {
                          el.textContent = acc.display_name || acc.username;
                          if (acc.emojis) emojify(el, acc.emojis);
                          twemojify(el);
                        }} />
                      </a>
                      <span class="hover-card-handle">@{acc.acct.includes("@") ? acc.acct : `${acc.acct}@${instance()?.uri || ""}`}</span>
                    </div>
                  </div>
                  <Show when={acc.note}>
                    <p class="hover-card-bio" ref={(el) => {
                      el.innerHTML = sanitizeHtml(acc.note);
                      if (acc.emojis) emojify(el, acc.emojis);
                      twemojify(el);
                      externalLinksNewTab(el);
                    }} />
                  </Show>
                  <Show when={currentUser() && !isOwnAccount()}>
                    <div class="hover-card-actions">
                      <Show
                        when={followed()}
                        fallback={
                          <button
                            class="hover-card-follow-btn"
                            onClick={(e) => { e.stopPropagation(); handleFollow(); }}
                            disabled={followLoading()}
                          >
                            {t("profile.follow")}
                          </button>
                        }
                      >
                        <button
                          class="hover-card-follow-btn following"
                          onClick={(e) => { e.stopPropagation(); setShowUnfollowModal(true); }}
                        >
                          {t("profile.following")}
                        </button>
                      </Show>
                      <div class="hover-card-more-menu">
                        <button class="hover-card-more-btn" onClick={(e) => { e.stopPropagation(); setMoreOpen(!moreOpen()); }}>···</button>
                        <Show when={moreOpen()}>
                          <div class="hover-card-more-dropdown">
                            <button class="hover-card-more-item" onClick={(e) => { e.stopPropagation(); handleMute(); }}>{t("block.mute")}</button>
                            <button class="hover-card-more-item hover-card-more-danger" onClick={(e) => { e.stopPropagation(); handleBlock(); }}>{t("block.block")}</button>
                            <button class="hover-card-more-item" onClick={(e) => { e.stopPropagation(); handleAddToList(); }}>{t("list.addToList" as any)}</button>
                          </div>
                        </Show>
                      </div>
                    </div>
                  </Show>
                </>
              );
            })()}
          </Show>
        </div>
      </Show>

      {/* フォロー解除確認モーダル */}
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

      {/* リストに追加モーダル */}
      <Show when={showAddToList()}>
        <div class="modal-overlay" onClick={() => setShowAddToList(false)}>
          <div class="modal-content" style="max-width: 360px" onClick={(e) => e.stopPropagation()}>
            <div class="modal-header">
              <h3>{t("list.addToList" as any)}</h3>
              <button class="modal-close" onClick={() => setShowAddToList(false)}>✕</button>
            </div>
            <div style="padding: 16px">
              <Show when={lists().length > 0} fallback={<p>{t("list.noLists" as any)}</p>}>
                <select class="modal-select" value={selectedListId()} onChange={(e) => setSelectedListId(e.target.value)}>
                  <option value="">{t("list.selectList" as any)}</option>
                  <For each={lists()}>{(l) => <option value={l.id}>{l.title}</option>}</For>
                </select>
                <div style="margin-top: 12px; display: flex; gap: 8px; justify-content: flex-end">
                  <button class="btn btn-small" onClick={() => setShowAddToList(false)}>{t("common.cancel")}</button>
                  <button class="btn btn-small btn-primary" disabled={!selectedListId() || addToListLoading()} onClick={handleAddToListConfirm}>
                    {t("common.add" as any)}
                  </button>
                </div>
              </Show>
            </div>
          </div>
        </div>
      </Show>
    </span>
  );
}
