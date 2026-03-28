import {
  createSignal,
  createResource,
  createEffect,
  on,
  onMount,
  onCleanup,
  Show,
  For,
  untrack,
} from "solid-js";
import { useSearchParams, useNavigate } from "@solidjs/router";
import { currentUser, authLoading } from "@nekonoverse/ui/stores/auth";
import EntrancePage from "../components/entrance/EntrancePage";
import {
  getPublicTimeline,
  getHomeTimeline,
  getNote,
  type Note,
} from "@nekonoverse/ui/api/statuses";
import { onUpdate, onReaction } from "@nekonoverse/ui/stores/streaming";
import { followedIds } from "@nekonoverse/ui/stores/followedUsers";
import { hideNonFollowedReplies } from "@nekonoverse/ui/stores/theme";
import { useI18n } from "@nekonoverse/ui/i18n";
import { pickerOpenCount } from "../components/reactions/ReactionBar";
import NoteComposer from "../components/notes/NoteComposer";
import ComposeModal from "../components/notes/ComposeModal";
import NoteCard from "../components/notes/NoteCard";
import NoteThreadModal from "../components/notes/NoteThreadModal";

export default function Home() {
  const { t } = useI18n();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [notes, setNotes] = createSignal<Note[]>([]);
  const [quoteTarget, setQuoteTarget] = createSignal<Note | null>(null);
  const [replyTarget, setReplyTarget] = createSignal<Note | null>(null);
  const [threadNoteId, setThreadNoteId] = createSignal<string | null>(null);
  const [newNoteIds, setNewNoteIds] = createSignal<Set<string>>(new Set());

  // 無限スクロール状態
  const [loadingMore, setLoadingMore] = createSignal(false);
  const [hasMore, setHasMore] = createSignal(true);
  // フィルタリングで全アイテムが除外された場合に備え、生のページネーションカーソルを別途追跡
  let rawPaginationCursor: string | null = null;

  // 新規投稿バッファリング状態
  const [bufferedNotes, setBufferedNotes] = createSignal<Note[]>([]);
  const [isAtTop, setIsAtTop] = createSignal(true);

  // トップへスクロールボタンの状態
  const [showScrollTop, setShowScrollTop] = createSignal(false);

  // 絵文字ピッカーなどのポップオーバーが開いている間は自動スクロール/バナーを抑制
  const isPopoverOpen = () => pickerOpenCount() > 0 || !!document.querySelector(".thread-modal");

  let sentinelRef: HTMLDivElement | undefined;
  let observer: IntersectionObserver | undefined;

  // コールバックref: センチネルがDOMに現れたら即座に監視を開始
  const setSentinelRef = (el: HTMLDivElement) => {
    sentinelRef = el;
    if (observer && el) {
      observer.observe(el);
    }
  };

  const isHomeTL = () => {
    const tl = searchParams.tl ?? localStorage.getItem("nekonoverse:tl");
    return tl === "home" && !!currentUser();
  };

  const filterHomeTLReplies = (data: Note[]): Note[] => {
    if (!hideNonFollowedReplies()) return data;
    const user = currentUser();
    const followed = followedIds();
    return data.filter((n) => {
      // 実際のノート（またはリブログされたノート）を確認
      const target = n.reblog || n;
      if (!target.in_reply_to_id) return true;
      // セルフリプライ（スレッド）
      if (target.in_reply_to_account_id === target.actor.id) return true;
      // 自分への返信
      if (user && target.in_reply_to_account_id === user.id) return true;
      // フォロー中のユーザーへの返信
      if (target.in_reply_to_account_id && followed.has(target.in_reply_to_account_id))
        return true;
      return false;
    });
  };

  const loadTimeline = async () => {
    try {
      const isHome = untrack(isHomeTL);
      const data = isHome
        ? await getHomeTimeline()
        : await getPublicTimeline();
      setNotes(isHome ? filterHomeTLReplies(data) : data);
      setHasMore(data.length >= 20);
      setBufferedNotes([]);
      rawPaginationCursor = null;
      return data;
    } catch {
      return [];
    }
  };

  // 過去の投稿を読み込む（無限スクロール）
  const loadOlderNotes = async () => {
    if (loadingMore() || !hasMore()) return;
    const current = notes();
    if (current.length === 0) return;
    // フィルタリングで前ページの全アイテムが除外された場合は生カーソルを使用
    const lastId = rawPaginationCursor || current[current.length - 1].id;
    rawPaginationCursor = null;
    setLoadingMore(true);
    try {
      const isHome = untrack(isHomeTL);
      const raw = isHome
        ? await getHomeTimeline({ max_id: lastId })
        : await getPublicTimeline({ max_id: lastId });
      const data = isHome ? filterHomeTLReplies(raw) : raw;
      if (raw.length === 0) {
        setHasMore(false);
      } else {
        setNotes((prev) => {
          const existingIds = new Set(prev.map((n) => n.id));
          const unique = data.filter((n) => !existingIds.has(n.id));
          return [...prev, ...unique];
        });
        if (raw.length < 20) {
          setHasMore(false);
        } else if (data.length === 0) {
          // 全アイテムがフィルタ除外された場合 — 最後の生アイテムでカーソルを進める
          rawPaginationCursor = raw[raw.length - 1].id;
        }
      }
    } catch {
      // 無視
    } finally {
      setLoadingMore(false);
      // センチネルを再監視: IntersectionObserverは状態の*変化*時のみ発火するため、
      // ノート追加後にセンチネルがまだ表示内にある場合は
      // 監視をリセットして次のページ読み込みをトリガーする必要がある
      if (observer && sentinelRef && hasMore()) {
        observer.unobserve(sentinelRef);
        observer.observe(sentinelRef);
      }
    }
  };

  // 新規投稿バッファリングとトップへスクロールボタンのためのスクロール位置追跡
  const handleScroll = () => {
    const y = window.scrollY;
    setIsAtTop(y < 100);
    setShowScrollTop(y > 500);
  };

  const scrollToTop = () => {
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  // バッファされたノートをタイムラインに反映
  const flushBuffer = () => {
    const buffered = bufferedNotes();
    if (buffered.length === 0) return;
    setNotes((prev) => {
      const existingIds = new Set(prev.map((n) => n.id));
      const unique = buffered.filter((n) => !existingIds.has(n.id));
      return [...unique, ...prev];
    });
    // 反映されたノートにスライドインアニメーションを適用
    for (const n of buffered) {
      setNewNoteIds((s) => new Set(s).add(n.id));
      setTimeout(
        () =>
          setNewNoteIds((s) => {
            const next = new Set(s);
            next.delete(n.id);
            return next;
          }),
        600,
      );
    }
    setBufferedNotes([]);
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  // ユーザーがトップに戻ったらバッファを自動反映（ポップオーバーが開いている場合を除く）
  createEffect(() => {
    if (isAtTop() && bufferedNotes().length > 0 && !isPopoverOpen()) {
      flushBuffer();
    }
  });

  // 初回読み込み: 認証の確定を待つ（App.tsxのLayoutがfetchCurrentUserを担当）
  const [initialData] = createResource(
    () => (!authLoading() ? true : false),
    () => loadTimeline(),
  );
  // TL切り替えエフェクト用に初回読み込み完了を追跡
  const loaded = () => initialData.state === "ready";

  // グローバルストリームからのリアルタイムタイムライン更新を購読
  const unsub = onUpdate(async (data) => {
    const { id } = data as { id: string };
    if (!id) return;
    try {
      const note = await getNote(id);
      // 公開タイムラインでは公開ノートのみ表示（REST APIのフィルタリングと一致させる）
      if (!isHomeTL() && note.visibility !== "public") {
        return;
      }
      // ホームTLでは、フォローしていないユーザーへの返信をフィルタリング
      if (isHomeTL() && filterHomeTLReplies([note]).length === 0) {
        return;
      }
      // このノートが既に存在する場合（直接、リブログとして、または引用として）、
      // その場で更新する（フォーカルポイントの更新、編集などに対応）
      const inTimeline = notes().some(
        (n) => n.id === id || n.reblog?.id === id || n.quote?.id === id,
      );
      if (inTimeline) {
        setNotes((prev) =>
          prev.map((n) => {
            if (n.id === id) return note;
            if (n.reblog?.id === id) return { ...n, reblog: note };
            if (n.quote?.id === id) return { ...n, quote: note };
            return n;
          }),
        );
        return;
      }
      if (
        bufferedNotes().some(
          (n) => n.id === id || n.reblog?.id === id || n.quote?.id === id,
        )
      )
        return;

      if (isAtTop() && !isPopoverOpen()) {
        // ユーザーがトップにいてポップオーバーなし: アニメーション付きで直接挿入
        setNotes((prev) => {
          if (prev.some((n) => n.id === id)) return prev;
          return [note, ...prev];
        });
        setNewNoteIds((s) => new Set(s).add(id));
        setTimeout(
          () =>
            setNewNoteIds((s) => {
              const next = new Set(s);
              next.delete(id);
              return next;
            }),
          600,
        );
      } else {
        // ユーザーがスクロール中: ノートをバッファに格納
        setBufferedNotes((prev) => {
          if (prev.some((n) => n.id === id)) return prev;
          return [note, ...prev];
        });
      }
    } catch {
      /* 無視 */
    }
  });

  // リアクション更新のデバウンス (同一Noteへの連続更新を集約)
  const pendingReactionRefresh = new Map<
    string,
    ReturnType<typeof setTimeout>
  >();
  const unsubReaction = onReaction(async (data) => {
    const { id } = data as { id: string };
    if (!id) return;
    const inNotes = notes().some((n) => n.id === id || n.reblog?.id === id);
    const inBuffer = bufferedNotes().some(
      (n) => n.id === id || n.reblog?.id === id,
    );
    if (inNotes || inBuffer) {
      const existing = pendingReactionRefresh.get(id);
      if (existing) clearTimeout(existing);
      pendingReactionRefresh.set(
        id,
        setTimeout(async () => {
          pendingReactionRefresh.delete(id);
          await refreshNote(id);
        }, 500),
      );
    }
  });

  onMount(() => {
    window.addEventListener("scroll", handleScroll, { passive: true });

    // 無限スクロール用のIntersectionObserver
    observer = new IntersectionObserver(
      (entries) => {
        if (entries[0]?.isIntersecting) {
          loadOlderNotes();
        }
      },
      { rootMargin: "200px" },
    );
    // センチネルが既にレンダリング済みの場合（例: 高速ロード）、今すぐ監視を開始
    if (sentinelRef) {
      observer.observe(sentinelRef);
    }
  });

  onCleanup(() => {
    unsub();
    unsubReaction();
    pendingReactionRefresh.forEach((timer) => clearTimeout(timer));
    pendingReactionRefresh.clear();
    window.removeEventListener("scroll", handleScroll);
    if (observer) {
      observer.disconnect();
    }
  });

  // tlの検索パラメータが変更された時のみ再読み込み（明示的な依存関係）
  createEffect(
    on(
      () => searchParams.tl,
      () => {
        if (loaded()) {
          setHasMore(true);
          setBufferedNotes([]);
          loadTimeline();
        }
      },
      { defer: true },
    ),
  );

  const handleNewNote = (note: Note) => {
    if (!isHomeTL() && note.visibility !== "public") {
      // 公開TL表示中にunlisted等を投稿した場合はホームTLに遷移
      navigate("/?tl=home");
      return;
    }
    setNotes((prev) => [note, ...prev]);
  };

  const refreshNote = async (noteId: string) => {
    try {
      const updated = await getNote(noteId);
      const mapper = (n: Note) => {
        if (n.id === noteId) return updated;
        if (n.reblog?.id === noteId) return { ...n, reblog: updated };
        return n;
      };
      setNotes((prev) => prev.map(mapper));
      setBufferedNotes((prev) => prev.map(mapper));
    } catch {
      // 無視
    }
  };

  return (
    <div class="page-container">
      <Show when={!authLoading()} fallback={<p>{t("common.loading")}</p>}>
        <Show when={currentUser()} fallback={<EntrancePage />}>
          <NoteComposer
            onPost={handleNewNote}
            quoteNote={quoteTarget()}
            onClearQuote={() => setQuoteTarget(null)}
          />

          <div class="timeline">
            <h2>{isHomeTL() ? t("timeline.home") : t("timeline.public")}</h2>

            {/* 新着投稿バナー（レイアウトシフト防止のため絵文字ピッカーが開いている間は非表示） */}
            <Show when={bufferedNotes().length > 0 && !isPopoverOpen()}>
              <button class="new-posts-banner" onClick={flushBuffer}>
                {t("timeline.newPosts").replace(
                  "{count}",
                  String(bufferedNotes().length),
                )}
              </button>
            </Show>

            <Show
              when={loaded()}
              fallback={<p>{t("timeline.loading")}</p>}
            >
              <Show
                when={notes().length > 0}
                fallback={<p class="empty">{t("timeline.empty")}</p>}
              >
                <For each={notes().slice(0, 200)}>
                  {(note) => (
                    <div
                      class={newNoteIds().has(note.id) ? "note-slide-in" : ""}
                    >
                      <NoteCard
                        note={note}
                        onReactionUpdate={() => refreshNote(note.id)}
                        onQuote={(n) => setQuoteTarget(n)}
                        onReply={(n) => setReplyTarget(n)}
                        onDelete={(id) =>
                          setNotes((prev) => prev.filter((n) => n.id !== id))
                        }
                        onThreadOpen={(id) => setThreadNoteId(id)}
                      />
                    </div>
                  )}
                </For>
              </Show>

              {/* 無限スクロール用のセンチネル要素 */}
              <div ref={setSentinelRef} class="timeline-sentinel" />

              {/* 読み込みインジケーター */}
              <Show when={loadingMore()}>
                <p class="timeline-loading">{t("timeline.loadingMore")}</p>
              </Show>

              {/* タイムラインの末尾 */}
              <Show when={!hasMore() && notes().length > 0}>
                <p class="timeline-end">{t("timeline.noMore")}</p>
              </Show>
            </Show>
          </div>

          {/* トップへスクロールフローティングボタン */}
          <Show when={showScrollTop()}>
            <button
              class="scroll-to-top"
              onClick={scrollToTop}
              aria-label={t("timeline.scrollToTop")}
              title={t("timeline.scrollToTop")}
            >
              <svg
                width="20"
                height="20"
                viewBox="0 0 20 20"
                fill="none"
                xmlns="http://www.w3.org/2000/svg"
                aria-hidden="true"
              >
                <path d="M10 3L3 10h4v7h6v-7h4L10 3z" fill="currentColor" />
              </svg>
            </button>
          </Show>

          {/* スレッドモーダル */}
          <Show when={threadNoteId()}>
            <NoteThreadModal
              noteId={threadNoteId()!}
              onClose={() => setThreadNoteId(null)}
              onReply={(n) => {
                setThreadNoteId(null);
                setReplyTarget(n);
              }}
              onQuote={(n) => {
                setThreadNoteId(null);
                setQuoteTarget(n);
              }}
            />
          </Show>

          {/* 投稿モーダル（返信/引用） */}
          <ComposeModal
            open={!!replyTarget() || !!quoteTarget()}
            onClose={() => { setReplyTarget(null); setQuoteTarget(null); }}
            onPost={(n) => { setReplyTarget(null); setQuoteTarget(null); handleNewNote(n); }}
            replyTo={replyTarget()}
            quoteNote={quoteTarget()}
          />
        </Show>
      </Show>
    </div>
  );
}
