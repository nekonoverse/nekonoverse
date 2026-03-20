import { createSignal, onMount, onCleanup, Show, For } from "solid-js";
import { getNotifications, type Notification } from "@nekonoverse/ui/api/notifications";
import NoteCard from "../components/notes/NoteCard";
import NoteThreadModal from "../components/notes/NoteThreadModal";
import { emojify } from "@nekonoverse/ui/utils/emojify";
import { twemojify } from "@nekonoverse/ui/utils/twemojify";
import { formatTimestamp, useTimeTick } from "@nekonoverse/ui/utils/formatTime";
import { getNote } from "@nekonoverse/ui/api/statuses";
import { onNotification } from "@nekonoverse/ui/stores/streaming";
import { useI18n } from "@nekonoverse/ui/i18n";
import { currentUser } from "@nekonoverse/ui/stores/auth";
import { defaultAvatar } from "@nekonoverse/ui/stores/instance";

function profileUrl(account: Notification["account"]): string {
  if (!account) return "#";
  return account.domain
    ? `/@${account.username}@${account.domain}`
    : `/@${account.username}`;
}

export default function Mentions() {
  const { t } = useI18n();
  const [mentions, setMentions] = createSignal<Notification[]>([]);
  const [loading, setLoading] = createSignal(true);
  const [loadingMore, setLoadingMore] = createSignal(false);
  const [hasMore, setHasMore] = createSignal(true);
  const [threadNoteId, setThreadNoteId] = createSignal<string | null>(null);

  const load = async () => {
    try {
      const data = await getNotifications({ limit: 20, types: ["mention"] });
      setMentions(data);
      setHasMore(data.length >= 20);
    } catch {
    } finally {
      setLoading(false);
    }
  };

  onMount(() => load());

  const unsub = onNotification(async () => {
    try {
      const fresh = await getNotifications({ limit: 1, types: ["mention"] });
      if (fresh.length > 0) {
        setMentions((prev) => {
          if (prev.some((n) => n.id === fresh[0].id)) return prev;
          return [fresh[0], ...prev];
        });
      }
    } catch {}
  });

  onCleanup(() => unsub());

  const loadMore = async () => {
    const current = mentions();
    if (current.length === 0 || loadingMore()) return;
    setLoadingMore(true);
    try {
      const older = await getNotifications({
        max_id: current[current.length - 1].id,
        limit: 20,
        types: ["mention"],
      });
      setMentions([...current, ...older]);
      setHasMore(older.length >= 20);
    } catch {
    } finally {
      setLoadingMore(false);
    }
  };

  const refreshNote = async (noteId: string) => {
    try {
      const updated = await getNote(noteId);
      setMentions((prev) =>
        prev.map((n) => {
          if (n.status?.id === noteId) return { ...n, status: updated };
          return n;
        })
      );
    } catch {}
  };

  return (
    <div class="page-container">
      <h2>{t("mentions.title")}</h2>

      <Show when={!loading()} fallback={<p>{t("common.loading")}</p>}>
        <Show when={currentUser()} fallback={<p>{t("notifications.loginRequired")}</p>}>
          <Show
            when={mentions().length > 0}
            fallback={<p class="empty">{t("mentions.empty")}</p>}
          >
            <div class="notifications-list">
              <For each={mentions()}>
                {(notif) => (
                  <div class="notification-item">
                    <div class="notification-icon">💬</div>
                    <div class="notification-body">
                      <div class="notification-meta">
                        <Show when={notif.account}>
                          <a href={profileUrl(notif.account)} class="notification-actor">
                            <img
                              class="notification-avatar"
                              src={notif.account!.avatar_url || defaultAvatar()}
                              alt=""
                            />
                            <strong ref={(el) => {
                              el.textContent = notif.account!.display_name || notif.account!.username;
                              emojify(el, notif.account!.emojis || []);
                              twemojify(el);
                            }} />
                          </a>
                        </Show>
                      </div>
                      <span class="notification-time">
                        {(() => { useTimeTick(); return formatTimestamp(notif.created_at, t); })()}
                      </span>
                      <Show when={notif.status}>
                        <div class="notification-note">
                          <NoteCard
                            note={notif.status!}
                            onReactionUpdate={() => refreshNote(notif.status!.id)}
                            onThreadOpen={(id) => setThreadNoteId(id)}
                          />
                        </div>
                      </Show>
                    </div>
                  </div>
                )}
              </For>
            </div>
            <Show when={hasMore()}>
              <div class="load-more">
                <button
                  class="btn btn-small"
                  onClick={loadMore}
                  disabled={loadingMore()}
                >
                  {loadingMore() ? t("common.loading") : t("notifications.loadMore")}
                </button>
              </div>
            </Show>
          </Show>
        </Show>
      </Show>

      {/* Thread modal */}
      <Show when={threadNoteId()}>
        <NoteThreadModal
          noteId={threadNoteId()!}
          onClose={() => setThreadNoteId(null)}
        />
      </Show>
    </div>
  );
}
