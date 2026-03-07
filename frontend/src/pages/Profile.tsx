import { createSignal, onMount, Show, For } from "solid-js";
import { useParams } from "@solidjs/router";
import { lookupAccount, getAccountStatuses, getRelationship, followAccount, unfollowAccount, blockAccount, unblockAccount, muteAccount, unmuteAccount, type Account } from "../api/accounts";
import { updateAvatar, updateHeader, updateProfile } from "../api/settings";
import type { Note } from "../api/statuses";
import { getNote } from "../api/statuses";
import NoteCard from "../components/notes/NoteCard";
import { useI18n } from "../i18n";
import { currentUser, fetchCurrentUser } from "../stores/auth";

export default function Profile() {
  const { t } = useI18n();
  const params = useParams<{ acct: string }>();
  const [account, setAccount] = createSignal<Account | null>(null);
  const [notes, setNotes] = createSignal<Note[]>([]);
  const [loading, setLoading] = createSignal(true);
  const [error, setError] = createSignal("");

  // Follow state
  const [isFollowing, setIsFollowing] = createSignal(false);
  const [followLoading, setFollowLoading] = createSignal(false);

  // Block/mute state
  const [isBlocking, setIsBlocking] = createSignal(false);
  const [isMuting, setIsMuting] = createSignal(false);
  const [blockMuteLoading, setBlockMuteLoading] = createSignal(false);

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
      if (currentUser() && currentUser()!.username !== acc.username) {
        try {
          const rel = await getRelationship(acc.id);
          setIsFollowing(rel.following);
          setIsBlocking(rel.blocking);
          setIsMuting(rel.muting);
        } catch {}
      }
    } catch (e: any) {
      setError(e.message || "Not found");
    } finally {
      setLoading(false);
    }
  };

  onMount(loadProfile);

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

  const refreshNote = async (noteId: string) => {
    try {
      const updated = await getNote(noteId);
      setNotes((prev) => prev.map((n) => (n.id === noteId ? updated : n)));
    } catch {}
  };

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
                        src={acc.avatar || "/default-avatar.svg"}
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
                      src={acc.avatar || "/default-avatar.svg"}
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
                      <h2 class="profile-display-name">
                        {acc.display_name || acc.username}
                      </h2>
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
                      <button
                        class={`btn btn-small${isFollowing() ? " btn-following" : ""}`}
                        disabled={followLoading()}
                        onClick={async () => {
                          setFollowLoading(true);
                          try {
                            if (isFollowing()) {
                              await unfollowAccount(acc.id);
                              setIsFollowing(false);
                            } else {
                              await followAccount(acc.id);
                              setIsFollowing(true);
                            }
                          } catch {}
                          setFollowLoading(false);
                        }}
                      >
                        {isFollowing() ? t("profile.following") : t("profile.follow")}
                      </button>
                      <button
                        class={`btn btn-small${isMuting() ? " btn-muted" : ""}`}
                        disabled={blockMuteLoading()}
                        onClick={handleMute}
                      >
                        {isMuting() ? t("block.unmute") : t("block.mute")}
                      </button>
                      <button
                        class={`btn btn-small btn-danger${isBlocking() ? " btn-blocked" : ""}`}
                        disabled={blockMuteLoading()}
                        onClick={handleBlock}
                      >
                        {isBlocking() ? t("block.unblock") : t("block.block")}
                      </button>
                    </Show>
                  </div>
                  <span class="profile-handle">@{acc.acct}</span>

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
                      <For each={editFields()}>
                        {(field, i) => (
                          <div class="profile-edit-field-row">
                            <input
                              class="profile-edit-field-input"
                              type="text"
                              value={field.name}
                              onInput={(e) => updateFieldValue(i(), "name", e.currentTarget.value)}
                              placeholder={t("settings.fieldLabel")}
                            />
                            <input
                              class="profile-edit-field-input"
                              type="text"
                              value={field.value}
                              onInput={(e) => updateFieldValue(i(), "value", e.currentTarget.value)}
                              placeholder={t("settings.fieldContent")}
                            />
                            <button class="btn btn-small btn-danger" onClick={() => removeField(i())}>
                              {t("settings.removeField")}
                            </button>
                          </div>
                        )}
                      </For>
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
                      <p class="profile-bio" innerHTML={acc.note} />
                    </Show>
                    <Show when={acc.fields && acc.fields.length > 0}>
                      <dl class="profile-fields">
                        <For each={acc.fields!}>
                          {(field) => (
                            <>
                              <dt class="profile-field-label">{field.name}</dt>
                              <dd class="profile-field-value" innerHTML={field.value} />
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
    </div>
  );
}
