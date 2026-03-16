import { createSignal, createResource, createEffect, on, onMount, onCleanup, Show, For, Index, batch } from "solid-js";
import { A, useParams } from "@solidjs/router";
import { lookupAccount, getAccountStatuses, getRelationship, followAccount, unfollowAccount, blockAccount, unblockAccount, muteAccount, unmuteAccount, type Account } from "@nekonoverse/ui/api/accounts";
import { updateAvatar, updateHeader, updateProfile, deleteAvatar, deleteHeader, updateHeaderFocus } from "@nekonoverse/ui/api/settings";
import HeaderCropPicker from "../components/HeaderCropPicker";
import { focalPointToObjectPosition } from "@nekonoverse/ui/utils/focalPoint";
import type { Note } from "@nekonoverse/ui/api/statuses";
import { getNote } from "@nekonoverse/ui/api/statuses";
import NoteCard from "../components/notes/NoteCard";
import ComposeModal from "../components/notes/ComposeModal";
import { useI18n } from "@nekonoverse/ui/i18n";
import { currentUser, fetchCurrentUser } from "@nekonoverse/ui/stores/auth";
import { addFollowedId, removeFollowedId } from "@nekonoverse/ui/stores/followedUsers";
import { onReaction } from "@nekonoverse/ui/stores/streaming";
import { sanitizeHtml } from "@nekonoverse/ui/utils/sanitize";
import { emojify } from "@nekonoverse/ui/utils/emojify";
import { twemojify } from "@nekonoverse/ui/utils/twemojify";
import { externalLinksNewTab } from "@nekonoverse/ui/utils/linkify";
import { defaultAvatar } from "@nekonoverse/ui/stores/instance";
import { formatTimestamp, useTimeTick } from "@nekonoverse/ui/utils/formatTime";

export default function Profile() {
  const { t } = useI18n();
  const params = useParams<{ acct: string }>();
  const [account, setAccount] = createSignal<Account | null>(null);
  const [notes, setNotes] = createSignal<Note[]>([]);
  const [error, setError] = createSignal("");

  // Infinite scroll state
  const [loadingMore, setLoadingMore] = createSignal(false);
  const [hasMore, setHasMore] = createSignal(true);
  let sentinelRef: HTMLDivElement | undefined;
  let observer: IntersectionObserver | undefined;

  const setSentinelRef = (el: HTMLDivElement) => {
    sentinelRef = el;
    if (observer && el) {
      observer.observe(el);
    }
  };

  // Follow state
  const [isFollowing, setIsFollowing] = createSignal(false);
  const [isRequested, setIsRequested] = createSignal(false);
  const [followLoading, setFollowLoading] = createSignal(false);

  // Block/mute state
  const [isBlocking, setIsBlocking] = createSignal(false);
  const [isMuting, setIsMuting] = createSignal(false);
  const [isFollowedBy, setIsFollowedBy] = createSignal(false);
  const [blockMuteLoading, setBlockMuteLoading] = createSignal(false);
  const [moreOpen, setMoreOpen] = createSignal(false);
  const [showUnfollowModal, setShowUnfollowModal] = createSignal(false);
  const [showUnlockModal, setShowUnlockModal] = createSignal(false);

  // Compose modal state
  const [replyTarget, setReplyTarget] = createSignal<Note | null>(null);
  const [quoteTarget, setQuoteTarget] = createSignal<Note | null>(null);

  // Inline edit state
  const [editing, setEditing] = createSignal(false);
  const [editName, setEditName] = createSignal("");
  const [editBio, setEditBio] = createSignal("");
  const [editBirthday, setEditBirthday] = createSignal("");
  const [editFields, setEditFields] = createSignal<{ name: string; value: string }[]>([]);
  const [editIsCat, setEditIsCat] = createSignal(false);
  const [editIsBot, setEditIsBot] = createSignal(false);
  const [editLocked, setEditLocked] = createSignal(false);
  const [editDiscoverable, setEditDiscoverable] = createSignal(true);
  const [saving, setSaving] = createSignal(false);
  const [uploadingAvatar, setUploadingAvatar] = createSignal(false);
  const [uploadingHeader, setUploadingHeader] = createSignal(false);
  const [showHeaderFocal, setShowHeaderFocal] = createSignal(false);

  let avatarInput!: HTMLInputElement;
  let headerInput!: HTMLInputElement;

  const loadProfile = async () => {
    try {
      const acct = params.acct.replace(/^@/, "");
      const acc = await lookupAccount(acct);
      setAccount(acc);

      // statuses取得とrelationship取得を並列実行
      const own = currentUser()?.username === acc.username && !acc.acct.includes("@");
      const promises: Promise<void>[] = [
        getAccountStatuses(acc.id).then((statuses) => setNotes(statuses)),
      ];
      if (currentUser() && !own) {
        promises.push(
          getRelationship(acc.id).then((rel) => {
            setIsFollowing(rel.following);
            setIsRequested(rel.requested);
            setIsBlocking(rel.blocking);
            setIsMuting(rel.muting);
            setIsFollowedBy(rel.followed_by);
            if (rel.following) addFollowedId(acc.id);
            else removeFollowedId(acc.id);
          }).catch(() => {}),
        );
      }
      await Promise.all(promises);
    } catch (e: any) {
      setError(e.message || "Not found");
    }
  };

  const loadMoreNotes = async () => {
    if (loadingMore() || !hasMore()) return;
    const current = notes();
    const acc = account();
    if (current.length === 0 || !acc) return;
    const lastId = current[current.length - 1].id;
    setLoadingMore(true);
    try {
      const data = await getAccountStatuses(acc.id, { max_id: lastId });
      if (data.length === 0) {
        setHasMore(false);
      } else {
        setNotes((prev) => [...prev, ...data]);
      }
    } catch {
    } finally {
      setLoadingMore(false);
      if (observer && sentinelRef && hasMore()) {
        observer.unobserve(sentinelRef);
        observer.observe(sentinelRef);
      }
    }
  };

  onMount(() => {
    observer = new IntersectionObserver(
      (entries) => {
        if (entries[0]?.isIntersecting) {
          loadMoreNotes();
        }
      },
      { rootMargin: "200px" },
    );
    if (sentinelRef) {
      observer.observe(sentinelRef);
    }
  });

  onCleanup(() => {
    observer?.disconnect();
  });

  const [profileData] = createResource(
    () => params.acct,
    async (acct) => {
      batch(() => {
        setAccount(null);
        setNotes([]);
        setError("");
        setHasMore(true);
        setIsFollowing(false);
        setIsRequested(false);
        setIsBlocking(false);
        setIsMuting(false);
        setIsFollowedBy(false);
        setEditing(false);
        setMoreOpen(false);
        setShowUnfollowModal(false);
        setShowUnlockModal(false);
      });
      await loadProfile();
      return account();
    },
  );

  const isOwn = () => {
    const acc = account();
    return acc && currentUser()?.username === acc.username && !acc.acct.includes("@");
  };

  // M-9: テキストノードベースのデコードに切り替え (innerHTMLへの未サニタイズ代入を回避)
  const htmlToPlainText = (html: string): string => {
    const parser = new DOMParser();
    const doc = parser.parseFromString(
      html.replace(/<br\s*\/?>/gi, "\n"),
      "text/html",
    );
    return doc.body.textContent?.trim() || "";
  };

  const decodeHtmlEntities = (text: string): string => {
    const textarea = document.createElement("textarea");
    textarea.innerHTML = text;
    return textarea.value || "";
  };

  const startEditing = () => {
    const acc = account()!;
    const user = currentUser();
    setEditName(acc.display_name || "");
    setEditBio(htmlToPlainText(user?.summary || ""));
    setEditBirthday(user?.birthday || "");
    setEditFields(
      user?.fields?.length
        ? user.fields.map((f) => ({
            name: decodeHtmlEntities(f.name),
            value: decodeHtmlEntities(f.value),
          }))
        : [],
    );
    setEditIsCat(user?.is_cat || false);
    setEditIsBot(user?.is_bot || false);
    setEditLocked(user?.locked || false);
    setEditDiscoverable(user?.discoverable ?? true);
    setEditing(true);
  };

  const cancelEditing = () => {
    setEditing(false);
  };

  const refreshAccount = async () => {
    await fetchCurrentUser();
    const acct = params.acct.replace(/^@/, "");
    const acc = await lookupAccount(acct);
    setAccount(acc);
  };

  const addField = () => {
    if (editFields().length < 4) {
      setEditFields([...editFields(), { name: "", value: "" }]);
    }
  };

  const removeField = (index: number) => {
    setEditFields(editFields().filter((_, i) => i !== index));
  };

  const updateFieldValue = (index: number, key: "name" | "value", val: string) => {
    setEditFields(editFields().map((f, i) => (i === index ? { ...f, [key]: val } : f)));
  };

  const doSave = async () => {
    setSaving(true);
    try {
      await updateProfile({
        display_name: editName(),
        summary: editBio(),
        fields_attributes: JSON.stringify(editFields()),
        birthday: editBirthday(),
        is_cat: editIsCat(),
        is_bot: editIsBot(),
        locked: editLocked(),
        discoverable: editDiscoverable(),
      });
      await refreshAccount();
      setEditing(false);
    } catch {
    } finally {
      setSaving(false);
    }
  };

  const handleSave = async () => {
    const acc = account();
    if (acc && acc.locked && !editLocked()) {
      setShowUnlockModal(true);
      return;
    }
    await doSave();
  };

  const handleAvatarChange = async (e: Event) => {
    const input = e.currentTarget as HTMLInputElement;
    const file = input.files?.[0];
    if (!file) return;
    setUploadingAvatar(true);
    try {
      await updateAvatar(file);
      await refreshAccount();
    } catch {
    } finally {
      setUploadingAvatar(false);
      input.value = "";
    }
  };

  const handleHeaderChange = async (e: Event) => {
    const input = e.currentTarget as HTMLInputElement;
    const file = input.files?.[0];
    if (!file) return;
    setUploadingHeader(true);
    try {
      await updateHeader(file);
      await refreshAccount();
    } catch {
    } finally {
      setUploadingHeader(false);
      input.value = "";
    }
  };

  const handleDeleteAvatar = async (e: MouseEvent) => {
    e.stopPropagation();
    setUploadingAvatar(true);
    try {
      await deleteAvatar();
      await refreshAccount();
    } catch {
    } finally {
      setUploadingAvatar(false);
    }
  };

  const handleDeleteHeader = async (e: MouseEvent) => {
    e.stopPropagation();
    setUploadingHeader(true);
    try {
      await deleteHeader();
      await refreshAccount();
    } catch {
    } finally {
      setUploadingHeader(false);
    }
  };

  const handleHeaderFocalSave = async (x: number, y: number) => {
    try {
      await updateHeaderFocus(x, y);
      await refreshAccount();
    } catch {}
    setShowHeaderFocal(false);
  };

  const handleBlock = async () => {
    const acc = account()!;
    if (isBlocking()) {
      setBlockMuteLoading(true);
      try { await unblockAccount(acc.id); setIsBlocking(false); } catch {}
      setBlockMuteLoading(false);
    } else {
      if (!confirm(t("block.confirmBlock"))) return;
      setBlockMuteLoading(true);
      try { await blockAccount(acc.id); setIsBlocking(true); } catch {}
      setBlockMuteLoading(false);
    }
  };

  const handleMute = async () => {
    const acc = account()!;
    if (isMuting()) {
      setBlockMuteLoading(true);
      try { await unmuteAccount(acc.id); setIsMuting(false); } catch {}
      setBlockMuteLoading(false);
    } else {
      if (!confirm(t("block.confirmMute"))) return;
      setBlockMuteLoading(true);
      try { await muteAccount(acc.id); setIsMuting(true); } catch {}
      setBlockMuteLoading(false);
    }
  };

  // Close dropdown on outside click
  const handleDocClick = (e: MouseEvent) => {
    const target = e.target as HTMLElement;
    if (!target.closest(".profile-more-menu")) {
      setMoreOpen(false);
    }
  };
  if (typeof document !== "undefined") {
    document.addEventListener("click", handleDocClick);
    onCleanup(() => document.removeEventListener("click", handleDocClick));
  }

  const refreshNote = async (noteId: string) => {
    try {
      const updated = await getNote(noteId);
      setNotes((prev) => prev.map((n) => {
        if (n.id === noteId) return updated;
        if (n.reblog?.id === noteId) return { ...n, reblog: updated };
        return n;
      }));
    } catch {}
  };

  const unsubReaction = onReaction(async (data) => {
    const { id } = data as { id: string };
    if (!id) return;
    if (notes().some((n) => n.id === id || n.reblog?.id === id)) {
      await refreshNote(id);
    }
  });
  onCleanup(() => unsubReaction());

  return (
    <div class="page-container">
      <Show when={profileData.state === "ready"} fallback={<p>{t("common.loading")}</p>}>
        <Show when={!error()} fallback={<p class="error">{error()}</p>}>
          {(() => {
            const acc = account()!;
            return (
              <>
                <div class="profile-header">
                  <Show when={editing()}>
                    <div class="profile-header-editable">
                      <div onClick={() => headerInput.click()}>
                        <Show when={acc.header}>
                          <img
                            class="profile-header-img"
                            src={acc.header}
                            alt=""
                            style={{ "object-position": focalPointToObjectPosition(currentUser()?.header_focal) }}
                          />
                        </Show>
                        <Show when={!acc.header}>
                          <div class="profile-header-placeholder" />
                        </Show>
                        <div class="profile-overlay">
                          {uploadingHeader() ? "..." : "\u{1F4F7}"}
                        </div>
                      </div>
                      <div class="profile-image-actions">
                        <Show when={acc.header}>
                          <button
                            class="profile-image-action-btn"
                            title={t("profile.cropHeader")}
                            onClick={(e) => { e.stopPropagation(); setShowHeaderFocal(true); }}
                          >
                            +
                          </button>
                          <button
                            class="profile-image-action-btn profile-image-delete-btn"
                            title={t("profile.deleteHeader")}
                            onClick={handleDeleteHeader}
                          >
                            ✕
                          </button>
                        </Show>
                      </div>
                    </div>
                    <input
                      ref={headerInput}
                      type="file"
                      accept="image/jpeg,image/png,image/gif,image/webp"
                      onChange={handleHeaderChange}
                      style="display: none"
                    />
                  </Show>
                  <Show when={!editing()}>
                    <Show when={acc.header}>
                      <img
                        class="profile-header-img"
                        src={acc.header}
                        alt=""
                        style={{ "object-position": focalPointToObjectPosition(currentUser()?.header_focal) }}
                      />
                    </Show>
                    <Show when={!acc.header}>
                      <div class="profile-header-placeholder" />
                    </Show>
                  </Show>

                  <Show when={editing()}>
                    <div class="profile-avatar-edit-wrapper">
                      <div
                        class="profile-avatar-editable"
                        onClick={() => avatarInput.click()}
                      >
                        <img
                          class="profile-avatar"
                          src={acc.avatar || defaultAvatar()}
                          alt=""
                        />
                        <div class="profile-avatar-overlay">
                          {uploadingAvatar() ? "..." : "\u{1F4F7}"}
                        </div>
                      </div>
                      <Show when={acc.avatar}>
                        <button
                          class="profile-avatar-delete-btn"
                          title={t("profile.deleteAvatar")}
                          onClick={handleDeleteAvatar}
                        >
                          ✕
                        </button>
                      </Show>
                    </div>
                    <input
                      ref={avatarInput}
                      type="file"
                      accept="image/jpeg,image/png,image/gif,image/webp"
                      onChange={handleAvatarChange}
                      style="display: none"
                    />
                  </Show>
                  <Show when={!editing()}>
                    <img
                      class="profile-avatar"
                      src={acc.avatar || defaultAvatar()}
                      alt=""
                    />
                  </Show>
                </div>

                <div class="profile-info">
                  <div class="profile-info-header">
                    <Show when={editing()}>
                      <input
                        class="profile-edit-input"
                        type="text"
                        value={editName()}
                        onInput={(e) => setEditName(e.currentTarget.value)}
                        placeholder={acc.username}
                      />
                    </Show>
                    <Show when={!editing()}>
                      <h2 class="profile-display-name" ref={(el) => {
                        el.textContent = acc.display_name || acc.username;
                        if (acc.emojis) emojify(el, acc.emojis);
                        twemojify(el);
                      }} />
                    </Show>

                    <Show when={isOwn()}>
                      <Show when={editing()}>
                        <div class="profile-edit-actions">
                          <button
                            class="btn btn-small"
                            onClick={handleSave}
                            disabled={saving()}
                          >
                            {saving() ? t("profile.saving") : t("profile.save")}
                          </button>
                          <button
                            class="profile-edit-btn"
                            onClick={cancelEditing}
                            disabled={saving()}
                          >
                            {t("profile.cancel")}
                          </button>
                        </div>
                      </Show>
                      <Show when={!editing()}>
                        <button class="profile-edit-btn" onClick={startEditing}>
                          {t("profile.edit")}
                        </button>
                      </Show>
                    </Show>
                    <Show when={!isOwn() && currentUser()}>
                      <div class="profile-actions-right">
                      <button
                        class={`btn btn-small${isFollowing() ? " btn-following" : ""}${isRequested() ? " btn-requested" : ""}`}
                        disabled={followLoading()}
                        onClick={async () => {
                          if (isFollowing()) {
                            setShowUnfollowModal(true);
                            return;
                          }
                          if (isRequested()) {
                            // フォロー申請を取り消す
                            setFollowLoading(true);
                            try {
                              await unfollowAccount(acc.id);
                              setIsRequested(false);
                              removeFollowedId(acc.id);
                            } catch {}
                            setFollowLoading(false);
                            return;
                          }
                          setFollowLoading(true);
                          try {
                            await followAccount(acc.id);
                            setIsFollowing(true);
                            addFollowedId(acc.id);
                          } catch {
                            // フォロー失敗時にrelationshipを再取得して正しい状態に同期
                            try {
                              const rel = await getRelationship(acc.id);
                              setIsFollowing(rel.following);
                              setIsRequested(rel.requested);
                            } catch {}
                          }
                          setFollowLoading(false);
                        }}
                      >
                        {isFollowing() ? t("profile.following") : isRequested() ? t("profile.requested") : t("profile.follow")}
                      </button>
                      <div class="profile-more-menu">
                        <button
                          class="profile-more-btn"
                          onClick={(e) => { e.stopPropagation(); setMoreOpen(!moreOpen()); }}
                        >
                          ···
                        </button>
                        <Show when={moreOpen()}>
                          <div class="profile-more-dropdown">
                            <button
                              class={`profile-more-item${isMuting() ? " active" : ""}`}
                              disabled={blockMuteLoading()}
                              onClick={() => { setMoreOpen(false); handleMute(); }}
                            >
                              {isMuting() ? t("block.unmute") : t("block.mute")}
                            </button>
                            <button
                              class={`profile-more-item profile-more-danger${isBlocking() ? " active" : ""}`}
                              disabled={blockMuteLoading()}
                              onClick={() => { setMoreOpen(false); handleBlock(); }}
                            >
                              {isBlocking() ? t("block.unblock") : t("block.block")}
                            </button>
                          </div>
                        </Show>
                      </div>
                      </div>
                    </Show>
                  </div>
                  <span class="profile-handle">@{acc.acct}</span>
                  <Show when={!isOwn() && currentUser() && isFollowedBy()}>
                    <span class="follows-you-badge">{t("profile.followsYou")}</span>
                  </Show>
                  <Show when={acc.acct.includes("@") && acc.url && /^https?:\/\//.test(acc.url)}>
                    <a
                      class="remote-view-link"
                      href={acc.url}
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                        <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
                        <polyline points="15 3 21 3 21 9" />
                        <line x1="10" y1="14" x2="21" y2="3" />
                      </svg>
                      {t("remote.viewOnRemote")}
                    </a>
                  </Show>

                  <Show when={acc.followers_count != null || acc.following_count != null}>
                    <div class="profile-follow-counts">
                      <Show when={acc.statuses_count != null}>
                        <span class="profile-follow-count-link">
                          <span class="profile-follow-count-num">{acc.statuses_count ?? 0}</span>
                          {" "}{t("profile.postsCount")}
                        </span>
                      </Show>
                      <A href={`/@${acc.acct}/following`} class="profile-follow-count-link">
                        <span class="profile-follow-count-num">{acc.following_count ?? 0}</span>
                        {" "}{t("profile.followingList")}
                      </A>
                      <A href={`/@${acc.acct}/followers`} class="profile-follow-count-link">
                        <span class="profile-follow-count-num">{acc.followers_count ?? 0}</span>
                        {" "}{t("profile.followers")}
                      </A>
                    </div>
                  </Show>

                  <Show when={editing()}>
                    <div class="profile-edit-section">
                      <label class="profile-edit-label">{t("settings.bio")}</label>
                      <textarea
                        class="profile-edit-textarea"
                        rows={3}
                        value={editBio()}
                        onInput={(e) => setEditBio(e.currentTarget.value)}
                        placeholder={t("settings.bioPlaceholder")}
                      />

                      <label class="profile-edit-label">{t("settings.birthday")}</label>
                      <input
                        class="profile-edit-input"
                        type="date"
                        value={editBirthday()}
                        onInput={(e) => setEditBirthday(e.currentTarget.value)}
                      />

                      <label class="profile-edit-label">{t("settings.fields")}</label>
                      <Index each={editFields()}>
                        {(field, i) => (
                          <div class="profile-edit-field-row">
                            <input
                              class="profile-edit-field-input"
                              type="text"
                              value={field().name}
                              onInput={(e) => updateFieldValue(i, "name", e.currentTarget.value)}
                              placeholder={t("settings.fieldLabel")}
                            />
                            <input
                              class="profile-edit-field-input"
                              type="text"
                              value={field().value}
                              onInput={(e) => updateFieldValue(i, "value", e.currentTarget.value)}
                              placeholder={t("settings.fieldContent")}
                            />
                            <button class="btn btn-small btn-danger" onClick={() => removeField(i)}>
                              {t("settings.removeField")}
                            </button>
                          </div>
                        )}
                      </Index>
                      <Show when={editFields().length < 4}>
                        <button class="btn btn-small" onClick={addField}>
                          {t("settings.addField")}
                        </button>
                      </Show>

                      <div class="profile-edit-checkboxes">
                        <label class="profile-edit-checkbox">
                          <input type="checkbox" checked={editIsCat()} onChange={(e) => setEditIsCat(e.currentTarget.checked)} />
                          {t("settings.isCat")}
                        </label>
                        <label class="profile-edit-checkbox">
                          <input type="checkbox" checked={editIsBot()} onChange={(e) => setEditIsBot(e.currentTarget.checked)} />
                          {t("settings.isBot")}
                        </label>
                        <label class="profile-edit-checkbox">
                          <input type="checkbox" checked={editLocked()} onChange={(e) => setEditLocked(e.currentTarget.checked)} />
                          {t("settings.locked")}
                        </label>
                        <label class="profile-edit-checkbox">
                          <input type="checkbox" checked={editDiscoverable()} onChange={(e) => setEditDiscoverable(e.currentTarget.checked)} />
                          {t("settings.discoverable")}
                        </label>
                      </div>
                    </div>
                  </Show>
                  <Show when={!editing()}>
                    <Show when={acc.note}>
                      <p class="profile-bio" ref={(el) => {
                        el.innerHTML = sanitizeHtml(acc.note);
                        if (acc.emojis) emojify(el, acc.emojis);
                        twemojify(el);
                        externalLinksNewTab(el);
                      }} />
                    </Show>
                    <Show when={acc.fields && acc.fields.length > 0}>
                      <dl class="profile-fields">
                        <For each={acc.fields!}>
                          {(field) => (
                            <>
                              <dt class="profile-field-label">{field.name}</dt>
                              <dd class="profile-field-value" ref={(el) => {
                                el.innerHTML = sanitizeHtml(field.value);
                                if (acc.emojis) emojify(el, acc.emojis);
                                twemojify(el);
                                externalLinksNewTab(el);
                              }} />
                            </>
                          )}
                        </For>
                      </dl>
                    </Show>
                  </Show>
                  <Show when={acc.created_at}>
                    <span class="profile-joined">
                      {acc.domain ? t("profile.firstSeen") : t("profile.joined")} {(() => { useTimeTick(); return formatTimestamp(acc.created_at!, t, true); })()}
                    </span>
                  </Show>
                </div>

                <Show when={notes().filter((n) => n.pinned).length > 0}>
                  <div class="profile-posts">
                    <h3>{t("note.pinnedPosts")}</h3>
                    <For each={notes().filter((n) => n.pinned)}>
                      {(note) => (
                        <NoteCard
                          note={note}
                          onReactionUpdate={() => refreshNote(note.id)}
                          onDelete={(id) => setNotes((prev) => prev.filter((n) => n.id !== id))}
                          onReply={(n) => setReplyTarget(n)}
                          onQuote={(n) => setQuoteTarget(n)}
                        />
                      )}
                    </For>
                  </div>
                </Show>
                <div class="profile-posts">
                  <h3>{t("profile.posts")}</h3>
                  <Show
                    when={notes().length > 0}
                    fallback={<p class="empty">{t("profile.noPostsYet")}</p>}
                  >
                    <For each={notes()}>
                      {(note) => (
                        <NoteCard
                          note={note}
                          onReactionUpdate={() => refreshNote(note.id)}
                          onDelete={(id) => setNotes((prev) => prev.filter((n) => n.id !== id))}
                          onReply={(n) => setReplyTarget(n)}
                          onQuote={(n) => setQuoteTarget(n)}
                        />
                      )}
                    </For>
                    <div ref={setSentinelRef} class="timeline-sentinel" />
                    <Show when={loadingMore()}>
                      <p class="timeline-loading">{t("timeline.loadingMore")}</p>
                    </Show>
                    <Show when={!hasMore() && notes().length > 0}>
                      <p class="timeline-end">{t("timeline.noMore")}</p>
                    </Show>
                  </Show>
                </div>
              </>
            );
          })()}
        </Show>
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
                onClick={async () => {
                  setFollowLoading(true);
                  try {
                    const accId = account()!.id;
                    await unfollowAccount(accId);
                    setIsFollowing(false);
                    removeFollowedId(accId);
                  } catch {}
                  setFollowLoading(false);
                  setShowUnfollowModal(false);
                }}
              >
                {t("profile.unfollow")}
              </button>
            </div>
          </div>
        </div>
      </Show>

      {/* Compose modal (reply / quote) */}
      <ComposeModal
        open={!!replyTarget() || !!quoteTarget()}
        onClose={() => { setReplyTarget(null); setQuoteTarget(null); }}
        replyTo={replyTarget()}
        quoteNote={quoteTarget()}
      />

      {/* Unlock confirmation modal */}
      <Show when={showUnlockModal()}>
        <div class="modal-overlay" onClick={() => setShowUnlockModal(false)}>
          <div class="modal-content" style="max-width: 400px" onClick={(e) => e.stopPropagation()}>
            <div class="modal-header">
              <h3>{t("followRequest.confirmUnlockTitle")}</h3>
              <button class="modal-close" onClick={() => setShowUnlockModal(false)}>✕</button>
            </div>
            <div style="padding: 16px">
              <p style="margin: 0 0 16px 0">{t("followRequest.confirmUnlock")}</p>
              <div style="display: flex; gap: 8px; justify-content: flex-end">
                <button class="btn btn-small" onClick={() => setShowUnlockModal(false)}>
                  {t("common.cancel")}
                </button>
                <button
                  class="btn btn-small btn-danger"
                  disabled={saving()}
                  onClick={async () => {
                    setShowUnlockModal(false);
                    await doSave();
                  }}
                >
                  {t("common.confirm")}
                </button>
              </div>
            </div>
          </div>
        </div>
      </Show>

      {/* Header crop picker */}
      <Show when={showHeaderFocal() && account()?.header}>
        <HeaderCropPicker
          imageUrl={account()!.header!}
          initialX={currentUser()?.header_focal?.x}
          initialY={currentUser()?.header_focal?.y}
          onSave={handleHeaderFocalSave}
          onClose={() => setShowHeaderFocal(false)}
        />
      </Show>
    </div>
  );
}
