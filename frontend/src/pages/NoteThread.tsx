import { createSignal, createEffect, Show, For } from "solid-js";
import { useParams } from "@solidjs/router";
import { getNote, getContext, type Note, type NoteContext } from "@nekonoverse/ui/api/statuses";
import { currentUser, authLoading } from "@nekonoverse/ui/stores/auth";
import { useI18n } from "@nekonoverse/ui/i18n";
import NoteCard from "../components/notes/NoteCard";
import NoteComposer from "../components/notes/NoteComposer";

/** Build a depth map for descendants based on in_reply_to_id chains. */
function buildDepthMap(targetId: string, descendants: Note[]): Map<string, number> {
  const depthMap = new Map<string, number>();
  depthMap.set(targetId, 0);
  for (const note of descendants) {
    const parentDepth = depthMap.get(note.in_reply_to_id || "") ?? 0;
    depthMap.set(note.id, parentDepth + 1);
  }
  return depthMap;
}

/** Build a lookup from note id -> actor info, for showing "Replying to" */
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
  const { t } = useI18n();
  const [targetNote, setTargetNote] = createSignal<Note | null>(null);
  const [context, setContext] = createSignal<NoteContext | null>(null);
  const [loading, setLoading] = createSignal(true);
  const [notFound, setNotFound] = createSignal(false);

  const loadThread = async () => {
    setLoading(true);
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
    } finally {
      setLoading(false);
    }
  };

  // Load when params change or auth settles
  let loaded = false;
  createEffect(() => {
    const id = params.id;
    if (!authLoading() && id) {
      loaded = true;
      loadThread();
    }
  });

  const handleReply = async (newNote: Note) => {
    // Reload thread to show the new reply
    await loadThread();
  };

  const handleDelete = (noteId: string) => {
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
      <Show when={!loading()} fallback={<p>{t("thread.loading")}</p>}>
        <Show when={!notFound()} fallback={<p class="empty">{t("thread.notFound")}</p>}>
          <div class="thread-view">
            <h2>{t("thread.title")}</h2>

            {/* Ancestors */}
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
                          inReplyToActor={parentActor()}
                        />
                      </div>
                    );
                  }}
                </For>
              </div>
            </Show>

            {/* Target note (highlighted) */}
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

            {/* Reply composer */}
            <Show when={currentUser() && targetNote()}>
              <div class="thread-reply-composer">
                <NoteComposer
                  replyTo={targetNote()}
                  onPost={handleReply}
                />
              </div>
            </Show>

            {/* Descendants */}
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
                          onReply={() => {/* Navigate to child thread */}}
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
