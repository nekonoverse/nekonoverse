import { createSignal, onMount, Show, For } from "solid-js";
import { useParams } from "@solidjs/router";
import { lookupAccount, getAccountStatuses, type Account } from "../api/accounts";
import { updateDisplayName, updateAvatar, updateHeader } from "../api/settings";
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

  // Inline edit state
  const [editing, setEditing] = createSignal(false);
  const [editName, setEditName] = createSignal("");
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
    setEditName(acc.display_name || "");
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

  const handleSave = async () => {
    setSaving(true);
    try {
      await updateDisplayName(editName() || null);
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
                  </div>
                  <span class="profile-handle">@{acc.acct}</span>
                  <Show when={acc.note}>
                    <p class="profile-bio" innerHTML={acc.note} />
                  </Show>
                  <Show when={acc.created_at}>
                    <span class="profile-joined">
                      {t("profile.joined")} {formatDate(acc.created_at)}
                    </span>
                  </Show>
                </div>

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
