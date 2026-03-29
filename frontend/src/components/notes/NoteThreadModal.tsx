import { createSignal, createEffect, Show, For, onCleanup } from "solid-js";
import { getNote, getContext, type Note, type NoteContext } from "@nekonoverse/ui/api/statuses";
import { currentUser } from "@nekonoverse/ui/stores/auth";
import { useI18n } from "@nekonoverse/ui/i18n";
import NoteCard from "./NoteCard";
import NoteComposer from "./NoteComposer";

/** in_reply_to_id チェーンに基づいて子孫ノートの深さマップを構築する。 */
function buildDepthMap(targetId: string, descendants: Note[]): Map<string, number> {
  const depthMap = new Map<string, number>();
  depthMap.set(targetId, 0);
  for (const note of descendants) {
    const parentDepth = depthMap.get(note.in_reply_to_id || "") ?? 0;
    depthMap.set(note.id, parentDepth + 1);
  }
  return depthMap;
}

/** ノートID → アクター情報のルックアップを構築する（「返信先」表示用） */
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

interface Props {
  noteId: string;
  onClose: () => void;
  onReply?: (note: Note) => void;
  onQuote?: (note: Note) => void;
}

export default function NoteThreadModal(props: Props) {
  const { t } = useI18n();
  const [targetNote, setTargetNote] = createSignal<Note | null>(null);
  const [context, setContext] = createSignal<NoteContext | null>(null);
  const [loading, setLoading] = createSignal(true);

  const loadThread = async (noteId: string) => {
    setLoading(true);
    try {
      const [note, ctx] = await Promise.all([getNote(noteId), getContext(noteId)]);
      setTargetNote(note);
      setContext(ctx);
    } catch {
      // 無視
    }
    setLoading(false);
  };

  createEffect(() => {
    loadThread(props.noteId);
  });

  // Escapeキーで閉じる
  const handleKey = (e: KeyboardEvent) => {
    if (e.key === "Escape") props.onClose();
  };
  document.addEventListener("keydown", handleKey);
  onCleanup(() => document.removeEventListener("keydown", handleKey));

  const handleReply = async () => {
    await loadThread(props.noteId);
  };

  const handleDelete = (noteId: string) => {
    if (noteId === props.noteId) {
      props.onClose();
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
      const ctx = context();
      if (!ctx) return;
      const mapNote = (n: Note) => (n.id === noteId ? updated : n);
      setContext({
        ancestors: ctx.ancestors.map(mapNote),
        descendants: ctx.descendants.map(mapNote),
      });
    } catch {}
  };

  // モーダル内で別のスレッドに遷移
  const openThread = (noteId: string) => {
    loadThread(noteId);
  };

  return (
    <div class="modal-overlay" onClick={props.onClose}>
      <div class="modal-content thread-modal" onClick={(e) => e.stopPropagation()}>
        <div class="modal-header">
          <h3>{t("thread.title")}</h3>
          <button class="modal-close" onClick={props.onClose}>✕</button>
        </div>
        <div class="thread-modal-body">
          <Show when={!loading()} fallback={
            <div style="padding: 24px; text-align: center; color: var(--text-secondary)">
              {t("common.loading")}
            </div>
          }>
            <Show when={targetNote()} fallback={
              <div style="padding: 24px; text-align: center; color: var(--text-secondary)">
                {t("thread.notFound")}
              </div>
            }>
              <div class="thread-view">
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
                              onReply={props.onReply}
                              onQuote={props.onQuote}
                              onThreadOpen={openThread}
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
                          onReply={props.onReply}
                          onQuote={props.onQuote}
                          onThreadOpen={openThread}
                          inReplyToActor={parentActor()}
                        />
                      </div>
                    );
                  }}
                </Show>

                {/* 返信コンポーザ */}
                <Show when={currentUser() && targetNote()}>
                  <div class="thread-reply-composer">
                    <NoteComposer
                      replyTo={targetNote()}
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
                              onReply={props.onReply}
                              onQuote={props.onQuote}
                              onThreadOpen={openThread}
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
      </div>
    </div>
  );
}
