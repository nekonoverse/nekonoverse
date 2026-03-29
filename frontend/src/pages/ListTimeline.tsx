import { createSignal, createEffect, onCleanup, Show, For } from "solid-js";
import { useParams, useNavigate } from "@solidjs/router";
import {
  getList,
  getListTimeline,
  getListAccounts,
  addListAccounts,
  removeListAccounts,
  type ListInfo,
} from "@nekonoverse/ui/api/lists";
import { searchAccounts, type Account } from "@nekonoverse/ui/api/accounts";
import { getNote, type Note } from "@nekonoverse/ui/api/statuses";
import { currentUser, authLoading } from "@nekonoverse/ui/stores/auth";
import { onReaction, onUpdate } from "@nekonoverse/ui/stores/streaming";
import { defaultAvatar } from "@nekonoverse/ui/stores/instance";
import NoteCard from "../components/notes/NoteCard";
import NoteThreadModal from "../components/notes/NoteThreadModal";
import { useI18n } from "@nekonoverse/ui/i18n";

export default function ListTimeline() {
  const { t } = useI18n();
  const params = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [list, setList] = createSignal<ListInfo | null>(null);
  const [notes, setNotes] = createSignal<Note[]>([]);
  const [hasMore, setHasMore] = createSignal(false);
  const [loading, setLoading] = createSignal(true);
  const [notFound, setNotFound] = createSignal(false);
  const [threadNoteId, setThreadNoteId] = createSignal<string | null>(null);

  // メンバーパネル
  const [showMembers, setShowMembers] = createSignal(false);
  const [members, setMembers] = createSignal<Account[]>([]);
  const [searchQuery, setSearchQuery] = createSignal("");
  const [searchResults, setSearchResults] = createSignal<Account[]>([]);

  const LIMIT = 20;

  const loadNotes = async (maxId?: string) => {
    const data = await getListTimeline(params.id, { limit: LIMIT + 1, max_id: maxId });
    setHasMore(data.length > LIMIT);
    const items = data.slice(0, LIMIT);
    if (maxId) {
      setNotes((prev) => [...prev, ...items]);
    } else {
      setNotes(items);
    }
  };

  const loadMembers = async () => {
    const data = await getListAccounts(params.id);
    setMembers(data);
  };

  // 認証準備完了時の初回読み込み
  createEffect(async () => {
    if (authLoading() || !currentUser()) return;
    try {
      const info = await getList(params.id);
      setList(info);
      await loadNotes();
      setLoading(false);
    } catch {
      setNotFound(true);
      setLoading(false);
    }
  });

  const loadMore = () => {
    const last = notes().at(-1);
    if (last) loadNotes(last.id);
  };

  const refreshNote = async (noteId: string) => {
    try {
      const updated = await getNote(noteId);
      setNotes((prev) =>
        prev.map((n) => {
          if (n.id === noteId) return updated;
          if (n.reblog?.id === noteId) return { ...n, reblog: updated };
          return n;
        }),
      );
    } catch {}
  };

  // SSE: リアクション
  const unsubReaction = onReaction(async (data) => {
    const { id } = data as { id: string };
    if (!id) return;
    if (notes().some((n) => n.id === id || n.reblog?.id === id)) {
      await refreshNote(id);
    }
  });
  onCleanup(() => unsubReaction());

  // SSE: リスト内の新しいノート
  const unsubUpdate = onUpdate((data) => {
    const note = data as Note;
    if (note?.id && !notes().some((n) => n.id === note.id)) {
      setNotes((prev) => [note, ...prev]);
    }
  });
  onCleanup(() => unsubUpdate());

  // メンバー追加用のアカウント検索
  let searchTimer: ReturnType<typeof setTimeout> | undefined;
  const handleSearch = (q: string) => {
    setSearchQuery(q);
    clearTimeout(searchTimer);
    if (!q.trim()) {
      setSearchResults([]);
      return;
    }
    searchTimer = setTimeout(async () => {
      const results = await searchAccounts(q, true);
      // 既存メンバーを除外
      const memberIds = new Set(members().map((m) => m.id));
      setSearchResults(results.filter((a) => !memberIds.has(a.id)));
    }, 300);
  };
  onCleanup(() => clearTimeout(searchTimer));

  const handleAddMember = async (account: Account) => {
    await addListAccounts(params.id, [account.id]);
    setMembers((prev) => [...prev, account]);
    setSearchResults((prev) => prev.filter((a) => a.id !== account.id));
  };

  const handleRemoveMember = async (accountId: string) => {
    await removeListAccounts(params.id, [accountId]);
    setMembers((prev) => prev.filter((m) => m.id !== accountId));
  };

  const toggleMembers = async () => {
    if (!showMembers()) {
      await loadMembers();
    }
    setShowMembers(!showMembers());
  };

  return (
    <div class="page-container">
      <Show when={!loading()} fallback={<p>{t("common.loading")}</p>}>
        <Show when={!notFound()} fallback={<p>{t("list.notFound")}</p>}>
          <Show when={list()}>
            {(info) => (
              <>
                <div class="list-tl-header">
                  <button class="btn btn-small" onClick={() => navigate("/lists")}>
                    &larr; {t("list.title")}
                  </button>
                  <h1>{info().title}</h1>
                  <div class="list-tl-meta">
                    <span class="list-card-badge">{info().replies_policy}</span>
                    <Show when={info().exclusive}>
                      <span class="list-card-badge list-card-badge-exclusive">{t("list.exclusive")}</span>
                    </Show>
                    <button class="btn btn-small" onClick={toggleMembers}>
                      {showMembers() ? t("list.hideMembers") : t("list.showMembers")}
                    </button>
                  </div>
                </div>

                {/* メンバーパネル */}
                <Show when={showMembers()}>
                  <div class="list-members-panel">
                    <div class="list-members-search">
                      <input
                        type="text"
                        class="input"
                        placeholder={t("list.searchAccounts")}
                        value={searchQuery()}
                        onInput={(e) => handleSearch(e.currentTarget.value)}
                      />
                    </div>
                    <Show when={searchResults().length > 0}>
                      <div class="list-members-results">
                        <For each={searchResults()}>
                          {(account) => (
                            <div class="list-member-row">
                              <img
                                src={account.avatar || defaultAvatar()}
                                alt={account.acct}
                                class="list-member-avatar"
                              />
                              <span class="list-member-name">
                                {account.display_name || account.username}
                                <small>@{account.acct}</small>
                              </span>
                              <button class="btn btn-small btn-primary" onClick={() => handleAddMember(account)}>
                                {t("list.addMember")}
                              </button>
                            </div>
                          )}
                        </For>
                      </div>
                    </Show>
                    <div class="list-members-list">
                      <h3>{t("list.members")}</h3>
                      <Show when={members().length > 0} fallback={<p class="empty">{t("list.noMembers")}</p>}>
                        <For each={members()}>
                          {(member) => (
                            <div class="list-member-row">
                              <img
                                src={member.avatar || defaultAvatar()}
                                alt={member.acct}
                                class="list-member-avatar"
                              />
                              <span class="list-member-name">
                                {member.display_name || member.username}
                                <small>@{member.acct}</small>
                              </span>
                              <button
                                class="btn btn-small btn-danger"
                                onClick={() => handleRemoveMember(member.id)}
                              >
                                {t("list.removeMember")}
                              </button>
                            </div>
                          )}
                        </For>
                      </Show>
                    </div>
                  </div>
                </Show>

                {/* タイムライン */}
                <Show when={notes().length > 0} fallback={<p class="empty">{t("list.timelineEmpty")}</p>}>
                  <For each={notes()}>
                    {(note) => (
                      <NoteCard
                        note={note}
                        onReactionUpdate={() => refreshNote(note.id)}
                        onDelete={(id) => setNotes((prev) => prev.filter((n) => n.id !== id))}
                        onThreadOpen={(id) => setThreadNoteId(id)}
                      />
                    )}
                  </For>
                  <Show when={hasMore()}>
                    <button class="btn load-more-btn" onClick={loadMore}>
                      {t("notifications.loadMore")}
                    </button>
                  </Show>
                </Show>
              </>
            )}
          </Show>
        </Show>
      </Show>

      <Show when={threadNoteId()}>
        <NoteThreadModal noteId={threadNoteId()!} onClose={() => setThreadNoteId(null)} />
      </Show>
    </div>
  );
}
