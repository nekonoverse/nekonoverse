import { createSignal, createEffect, on, onCleanup, Show, For, Index } from "solid-js";
import { A, useParams } from "@solidjs/router";
import { lookupAccount, getAccountStatuses, getRelationship, followAccount, unfollowAccount, blockAccount, unblockAccount, muteAccount, unmuteAccount, type Account } from "../api/accounts";
import { updateAvatar, updateHeader, updateProfile } from "../api/settings";
import type { Note } from "../api/statuses";
import { getNote } from "../api/statuses";
import NoteCard from "../components/notes/NoteCard";
import { useI18n } from "../i18n";
import { currentUser, fetchCurrentUser } from "../stores/auth";
import { addFollowedId, removeFollowedId } from "../stores/followedUsers";
import { onReaction } from "../stores/streaming";
import { sanitizeHtml } from "../utils/sanitize";
import { emojify } from "../utils/emojify";
import { twemojify } from "../utils/twemojify";
import { defaultAvatar } from "../stores/instance";

export default function Profile() {
  const { t } = useI18n();
  const params = useParams<{ acct: string }>();
  const [account, setAccount] = createSignal<Account | null>(null);
  const [notes, setNotes] = createSignal<Note[]>([]);
  const [loading, setLoading] = createSignal(true);
  const [error, setError] = createSignal("");

  // Follow state
  const [isFollowing, setIsFollowing] = createSignal(false);
  const [isRequested, setIsRequested] = createSignal(false);
  const [followLoading, setFollowLoading] = createSignal(false);

  // Block/mute state
  const [isBlocking, setIsBlocking] = createSignal(false);
  const [isMuting, setIsMuting] = createSignal(false);
  const [blockMuteLoading, setBlockMuteLoading] = createSignal(false);
  const [moreOpen, setMoreOpen] = createSignal(false);
  const [showUnfollowModal, setShowUnfollowModal] = createSignal(false);

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

  let avatarInput!: HTMLInputElement;
  let headerInput!: HTMLInputElement;

  const loadProfile = async () => {
    try {
      const acct = params.acct.replace(/^@/, "");
      const acc = await lookupAccount(acct);
      setAccount(acc);
      const statuses = await getAccountStatuses(acc.id);
      setNotes(statuses);
      // Load relationship if logged in and not own profile
      const own = currentUser()?.username === acc.username && !acc.acct.includes("@");
      if (currentUser() && !own) {
        try {
          const rel = await getRelationship(acc.id);
          setIsFollowing(rel.following);
          setIsRequested(rel.requested);
          setIsBlocking(rel.blocking);
          setIsMuting(rel.muting);
          if (rel.following) addFollowedId(acc.id);
          else removeFollowedId(acc.id);
        } catch {}
      }
    } catch (e: any) {
      setError(e.message || "Not found");
    } finally {
      setLoading(false);
    }
  };

  createEffect(on(() => params.acct, () => {
    setAccount(null);
    setNotes([]);
    setLoading(true);
    setError("");
    setIsFollowing(false);
    setIsRequested(false);
    setIsBlocking(false);
    setIsMuting(false);
    setEditing(false);
    setMoreOpen(false);
    setShowUnfollowModal(false);
    loadProfile();
  }));

  const isOwn = () => {
    const acc = account();
    return acc && currentUser()?.username === acc.username && !acc.acct.includes("@");
  };

  const startEditing = () => {
    const acc = account()!;
    const user = currentUser();
    setEditName(acc.display_name || "");
    setEditBio(user?.summary || "");
    setEditBirthday(user?.birthday || "");
    setEditFields(user?.fields?.length ? [...user.fields] : []);
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

  const handleSave = async () => {
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
      setNotes((prev) => prev.map((n) => (n.id === noteId ? updated : n)));
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

  const formatDate = (iso?: string) => {
    if (!iso) return "";
    return new Date(iso).toLocaleDateString();
  };

  return (
    <div class="page-container">
      <Show when={!loading()} fallback={<p>{t("common.loading")}</p>}>
        <Show when={!error()} fallback={<p class="error">{error()}</p>}>
          {(() => {
            const acc = account()!;
            return (
              <>
                <div class="profile-header">
                  <Show when={editing()}>
                    <div
                      class="profile-header-editable"
                      onClick={() => headerInput.click()}
                    >
                      <Show when={acc.header}>
                        <img class="profile-header-img" src={acc.header} alt="" />
                      </Show>
                      <Show when={!acc.header}>
                        <div class="profile-header-placeholder" />
                      </Show>
                      <div class="profile-overlay">
                        {uploadingHeader() ? "..." : "\u{1F4F7}"}
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
                      <img class="profile-header-img" src={acc.header} alt="" />
                    </Show>
                    <Show when={!acc.header}>
                      <div class="profile-header-placeholder" />
                    </Show>
                  </Show>

                  <Show when={editing()}>
                    <div
                      class="profile-avatar-editable"
                      onClick={() => avatarInput.click()}
                    >
                      <img
                        class="profile-avatar"
                        src={acc.avatar || {defaultAvatar()}}
                        alt=""
                      />
                      <div class="profile-avatar-overlay">
                        {uploadingAvatar() ? "..." : "\u{1F4F7}"}
                      </div>
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
                      src={acc.avatar || {defaultAvatar()}}
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

                  <Show when={acc.followers_count != null || acc.following_count != null}>
                    <div class="profile-follow-counts">
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
                              }} />
                            </>
                          )}
                        </For>
                      </dl>
                    </Show>
                  </Show>
                  <Show when={acc.created_at}>
                    <span class="profile-joined">
                      {t("profile.joined")} {formatDate(acc.created_at)}
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
                        />
                      )}
                    </For>
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
    </div>
  );
}
