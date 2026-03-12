import { createSignal, createEffect, Show, For } from "solid-js";
import { instance } from "../../stores/instance";
import { registrationMode } from "../../stores/instance";
import { getPublicTimeline, type Note } from "../../api/statuses";
import { useI18n } from "../../i18n";
import NoteCard from "../notes/NoteCard";

export default function EntrancePage() {
  const { t } = useI18n();
  const [previewNotes, setPreviewNotes] = createSignal<Note[]>([]);
  const [loadingPreview, setLoadingPreview] = createSignal(true);

  createEffect(() => {
    loadPreview();
  });

  const loadPreview = async () => {
    try {
      const notes = await getPublicTimeline({ limit: 5, local: true });
      setPreviewNotes(notes);
    } catch {
      // ignore
    } finally {
      setLoadingPreview(false);
    }
  };

  const formatNumber = (n: number): string => {
    if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
    if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
    return String(n);
  };

  const mode = () => registrationMode();
  const stats = () => instance()?.stats;
  const serverIcon = () => instance()?.thumbnail?.url;
  const serverTitle = () => instance()?.title || "Nekonoverse";

  return (
    <div class="entrance">
      {/* Hero Section */}
      <section class="entrance-hero">
        <Show when={serverIcon()}>
          <img
            src={serverIcon()!}
            alt={serverTitle()}
            class="entrance-hero-icon"
          />
        </Show>
        <h1 class="entrance-hero-title">{serverTitle()}</h1>
        <p class="entrance-hero-tagline">{t("app.tagline")}</p>
        <div class="entrance-hero-actions">
          <a href="/login" class="btn">
            {t("common.login")}
          </a>
          <Show when={mode() !== "closed"}>
            <a href="/register" class="btn btn-accent">
              {t("entrance.cta.join")}
            </a>
          </Show>
        </div>
        <Show when={mode() === "closed"}>
          <p class="entrance-hero-notice">{t("entrance.footer.closed")}</p>
        </Show>
        <Show when={mode() === "invite"}>
          <p class="entrance-hero-notice">
            {t("entrance.footer.inviteRequired")}
          </p>
        </Show>
        <Show when={mode() === "approval"}>
          <p class="entrance-hero-notice">
            {t("entrance.footer.approvalRequired")}
          </p>
        </Show>
      </section>

      {/* Stats Section */}
      <Show when={stats()}>
        <section class="entrance-stats">
          <div class="entrance-stat-card">
            <span class="entrance-stat-number">
              {formatNumber(stats()!.user_count)}
            </span>
            <span class="entrance-stat-label">{t("entrance.stats.users")}</span>
          </div>
          <div class="entrance-stat-card">
            <span class="entrance-stat-number">
              {formatNumber(stats()!.status_count)}
            </span>
            <span class="entrance-stat-label">{t("entrance.stats.posts")}</span>
          </div>
          <div class="entrance-stat-card">
            <span class="entrance-stat-number">
              {formatNumber(stats()!.domain_count)}
            </span>
            <span class="entrance-stat-label">
              {t("entrance.stats.servers")}
            </span>
          </div>
        </section>
      </Show>

      {/* Public Timeline Preview */}
      <section class="entrance-preview">
        <h2 class="entrance-preview-title">{t("entrance.preview.title")}</h2>
        <Show
          when={!loadingPreview()}
          fallback={<p>{t("timeline.loading")}</p>}
        >
          <Show
            when={previewNotes().length > 0}
            fallback={<p class="empty">{t("timeline.empty")}</p>}
          >
            <div class="entrance-preview-list">
              <For each={previewNotes()}>
                {(note) => <NoteCard note={note} />}
              </For>
            </div>
          </Show>
        </Show>
      </section>

    </div>
  );
}
