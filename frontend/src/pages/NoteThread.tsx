import { createSignal, createResource, Show, For } from "solid-js";
import { useParams, useNavigate } from "@solidjs/router";
import { getNote, getContext, type Note, type NoteContext } from "@nekonoverse/ui/api/statuses";
import { currentUser, authLoading } from "@nekonoverse/ui/stores/auth";
import { useI18n } from "@nekonoverse/ui/i18n";
import NoteCard from "../components/notes/NoteCard";
import NoteComposer from "../components/notes/NoteComposer";

/** in_reply_to_idチェーンに基づいて子孫ノートの深さマップを構築する。 */
function buildDepthMap(targetId: string, descendants: Note[]): Map<string, number> {
  const depthMap = new Map<string, number>();
  depthMap.set(targetId, 0);
  for (const note of descendants) {
    const parentDepth = depthMap.get(note.in_reply_to_id || "") ?? 0;
    depthMap.set(note.id, parentDepth + 1);
  }
  return depthMap;
}

/** 「返信先」表示用に、ノートID → アクター情報のルックアップを構築する */
function buildActorMap(
  target: Note,
  ancestors: Note[],
  descendants: Note[],
): Map<string, { username: string; domain: string | null }> {
  const map = new Map<string, { username: string; domain: string | null }>();
  map.set(target.id, { username: target.actor.username, domain: target.actor.domain });
  for (const n of ancestors) {
    map.set(n.id, { username: n.actor.username, domain: n.actor.domain });
  }
  for (const n of descendants) {
    map.set(n.id, { username: n.actor.username, domain: n.actor.domain });
  }
  return map;
}

export default function NoteThread() {
  const params = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { t } = useI18n();
  const [targetNote, setTargetNote] = createSignal<Note | null>(null);
  const [context, setContext] = createSignal<NoteContext | null>(null);
  const [notFound, setNotFound] = createSignal(false);
  const [replyTarget, setReplyTarget] = createSignal<Note | null>(null);

  // 実効的な返信先: replyTargetが設定されていればそれ、なければ対象ノート
  const effectiveReplyTarget = () => replyTarget() || targetNote();

  const [initialData] = createResource(
    () => (!authLoading() && params.id ? params.id : false),
    async (id) => {
      setNotFound(false);
      try {
        const [note, ctx] = await Promise.all([getNote(id), getContext(id)]);
        setTargetNote(note);
        setContext(ctx);
        return { note, ctx };
      } catch {
        setNotFound(true);
        return null;
      }
    },
  );

  const loadThread = async () => {
    setNotFound(false);
    try {
      const [note, ctx] = await Promise.all([
        getNote(params.id),
        getContext(params.id),
      ]);
      setTargetNote(note);
      setContext(ctx);
    } catch {
      setNotFound(true);
    }
  };

  const handleReply = async (newNote: Note) => {
    setReplyTarget(null);
    // 新しい返信を表示するためにスレッドを再読み込み
    await loadThread();
  };

  const handleDelete = (noteId: string) => {
    // 表示中のノートを削除した場合は前のページに戻る
    if (noteId === params.id) {
      const ctx = context();
      const ancestors = ctx?.ancestors;
      if (ancestors && ancestors.length > 0) {
        // 親ノートのスレッドに遷移
        navigate(`/notes/${ancestors[ancestors.length - 1].id}`, { replace: true });
      } else {
        history.length > 1 ? history.back() : navigate("/", { replace: true });
      }
      return;
    }
    const ctx = context();
    if (!ctx) return;
    setContext({
      ancestors: ctx.ancestors.filter((n) => n.id !== noteId),
      descendants: ctx.descendants.filter((n) => n.id !== noteId),
    });
  };

  const refreshNote = async (noteId: string) => {
    try {
      const updated = await getNote(noteId);
      const target = targetNote();
      if (target && target.id === noteId) {
        setTargetNote(updated);
        return;
      }
      if (target && target.reblog?.id === noteId) {
        setTargetNote({ ...target, reblog: updated });
        return;
      }
      const ctx = context();
      if (!ctx) return;
      const mapNote = (n: Note) => {
        if (n.id === noteId) return updated;
        if (n.reblog?.id === noteId) return { ...n, reblog: updated };
        return n;
      };
      setContext({
        ancestors: ctx.ancestors.map(mapNote),
        descendants: ctx.descendants.map(mapNote),
      });
    } catch {}
  };

  return (
    <div class="page-container">
      <Show when={initialData.state === "ready"} fallback={<p>{t("thread.loading")}</p>}>
        <Show when={!notFound()} fallback={<p class="empty">{t("thread.notFound")}</p>}>
          <div class="thread-view">
            <h2>{t("thread.title")}</h2>

            {/* 祖先ノート */}
            <Show when={context()?.ancestors && context()!.ancestors.length > 0}>
              <div class="thread-ancestors">
                <For each={context()!.ancestors}>
                  {(note) => {
                    const actorMap = () => buildActorMap(targetNote()!, context()!.ancestors, context()!.descendants);
                    const parentActor = () => note.in_reply_to_id ? actorMap().get(note.in_reply_to_id) || null : null;
                    return (
                      <div class="thread-ancestor-note">
                        <div class="thread-connector" />
                        <NoteCard
                          note={note}
                          onReactionUpdate={() => refreshNote(note.id)}
                          onDelete={handleDelete}
                          onReply={(n) => setReplyTarget(n)}
                          inReplyToActor={parentActor()}
                        />
                      </div>
                    );
                  }}
                </For>
              </div>
            </Show>

            {/* 対象ノート（ハイライト表示） */}
            <Show when={targetNote()}>
              {(note) => {
                const actorMap = () => buildActorMap(note(), context()?.ancestors || [], context()?.descendants || []);
                const parentActor = () => note().in_reply_to_id ? actorMap().get(note().in_reply_to_id!) || null : null;
                return (
                  <div class="thread-target-note">
                    <NoteCard
                      note={note()}
                      onReactionUpdate={() => refreshNote(note().id)}
                      onDelete={handleDelete}
                      inReplyToActor={parentActor()}
                    />
                  </div>
                );
              }}
            </Show>

            {/* 返信コンポーザー */}
            <Show when={currentUser() && targetNote()}>
              <div class="thread-reply-composer">
                <Show when={replyTarget() && replyTarget()!.id !== targetNote()?.id}>
                  <div class="thread-reply-indicator">
                    <span>
                      @{replyTarget()!.actor.username}{" "}
                      {t("thread.replyingTo")}
                    </span>
                    <button
                      class="thread-reply-indicator-cancel"
                      onClick={() => setReplyTarget(null)}
                      title={t("common.cancel")}
                    >
                      {"\u2715"}
                    </button>
                  </div>
                </Show>
                <NoteComposer
                  replyTo={effectiveReplyTarget()}
                  onPost={handleReply}
                />
              </div>
            </Show>

            {/* 子孫ノート */}
            <Show when={context()?.descendants && context()!.descendants.length > 0}>
              <div class="thread-descendants">
                <For each={context()!.descendants}>
                  {(note) => {
                    const depthMap = () => buildDepthMap(targetNote()!.id, context()!.descendants);
                    const depth = () => Math.min(depthMap().get(note.id) ?? 1, 4);
                    const actorMap = () => buildActorMap(targetNote()!, context()!.ancestors, context()!.descendants);
                    const parentActor = () => note.in_reply_to_id ? actorMap().get(note.in_reply_to_id) || null : null;
                    return (
                      <div
                        class="thread-descendant-note"
                        style={{ "margin-left": `${(depth() - 1) * 24}px` }}
                      >
                        <div class="thread-connector" />
                        <NoteCard
                          note={note}
                          onReactionUpdate={() => refreshNote(note.id)}
                          onDelete={handleDelete}
                          onReply={(n) => setReplyTarget(n)}
                          inReplyToActor={parentActor()}
                        />
                      </div>
                    );
                  }}
                </For>
              </div>
            </Show>
          </div>
        </Show>
      </Show>
    </div>
  );
}
