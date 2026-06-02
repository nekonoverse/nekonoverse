import { createResource, createSignal, For, Show } from "solid-js";
import { useI18n } from "@nekonoverse/ui/i18n";
import {
  createDiscordWebhook,
  deleteDiscordWebhook,
  listDiscordWebhooks,
  testDiscordWebhook,
  updateDiscordWebhook,
  type DiscordWebhook,
  type DiscordWebhookInput,
} from "@nekonoverse/ui/api/discordWebhooks";

type NotifyKey =
  | "notify_mention"
  | "notify_direct"
  | "notify_quote"
  | "notify_reaction"
  | "notify_renote"
  | "notify_follow"
  | "notify_follow_request";

const NOTIFY_KEYS: NotifyKey[] = [
  "notify_mention",
  "notify_direct",
  "notify_quote",
  "notify_reaction",
  "notify_renote",
  "notify_follow",
  "notify_follow_request",
];

const NOTIFY_LABEL_KEY: Record<NotifyKey, string> = {
  notify_mention: "settings.discordWebhooks.notify.mention",
  notify_direct: "settings.discordWebhooks.notify.direct",
  notify_quote: "settings.discordWebhooks.notify.quote",
  notify_reaction: "settings.discordWebhooks.notify.reaction",
  notify_renote: "settings.discordWebhooks.notify.renote",
  notify_follow: "settings.discordWebhooks.notify.follow",
  notify_follow_request: "settings.discordWebhooks.notify.followRequest",
};

function defaultInput(): DiscordWebhookInput {
  return {
    name: "",
    webhook_url: "",
    notify_mention: true,
    notify_direct: true,
    notify_quote: true,
    notify_reaction: true,
    notify_renote: true,
    notify_follow: true,
    notify_follow_request: true,
    enabled: true,
  };
}

export default function DiscordWebhooksManager() {
  const { t } = useI18n();
  const [webhooks, { refetch }] = createResource<DiscordWebhook[]>(listDiscordWebhooks);
  const [editing, setEditing] = createSignal<DiscordWebhook | null>(null);
  const [showModal, setShowModal] = createSignal(false);
  const [draft, setDraft] = createSignal<DiscordWebhookInput>(defaultInput());
  const [error, setError] = createSignal("");
  const [submitting, setSubmitting] = createSignal(false);
  const [testResult, setTestResult] = createSignal<{
    id: string;
    ok: boolean;
    message: string;
  } | null>(null);

  function openCreate() {
    setDraft(defaultInput());
    setEditing(null);
    setError("");
    setShowModal(true);
  }

  function openEdit(webhook: DiscordWebhook) {
    setDraft({
      name: webhook.name,
      webhook_url: "",
      notify_mention: webhook.notify_mention,
      notify_direct: webhook.notify_direct,
      notify_quote: webhook.notify_quote,
      notify_reaction: webhook.notify_reaction,
      notify_renote: webhook.notify_renote,
      notify_follow: webhook.notify_follow,
      notify_follow_request: webhook.notify_follow_request,
      enabled: webhook.enabled,
    });
    setEditing(webhook);
    setError("");
    setShowModal(true);
  }

  function closeModal() {
    setShowModal(false);
    setEditing(null);
    setError("");
  }

  async function handleSubmit(e: Event) {
    e.preventDefault();
    setError("");
    setSubmitting(true);
    try {
      const current = editing();
      const payload = draft();
      if (current) {
        const updates: Partial<DiscordWebhookInput> = { ...payload };
        if (!payload.webhook_url) {
          // 編集モードで URL を空欄のまま送らない
          delete updates.webhook_url;
        }
        await updateDiscordWebhook(current.id, updates);
      } else {
        await createDiscordWebhook(payload);
      }
      await refetch();
      closeModal();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  }

  async function handleDelete(webhook: DiscordWebhook) {
    if (!confirm(t("settings.discordWebhooks.deleteConfirm" as any))) return;
    try {
      await deleteDiscordWebhook(webhook.id);
      await refetch();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function handleTest(webhook: DiscordWebhook) {
    setTestResult(null);
    try {
      const result = await testDiscordWebhook(webhook.id);
      setTestResult({
        id: webhook.id,
        ok: result.success,
        message: result.success
          ? t("settings.discordWebhooks.testSuccess" as any)
          : (result.error || t("settings.discordWebhooks.testFailure" as any)),
      });
      await refetch();
    } catch (err) {
      setTestResult({
        id: webhook.id,
        ok: false,
        message: err instanceof Error ? err.message : String(err),
      });
    }
  }

  return (
    <div class="settings-section">
      <h3>{t("settings.discordWebhooks.title" as any)}</h3>
      <p class="settings-label">{t("settings.discordWebhooks.description" as any)}</p>

      <Show when={error()}>
        <p class="error">{error()}</p>
      </Show>

      <Show when={!webhooks.loading} fallback={<p>{t("common.loading")}</p>}>
        <Show
          when={(webhooks() ?? []).length > 0}
          fallback={
            <p class="webhook-empty">{t("settings.discordWebhooks.empty" as any)}</p>
          }
        >
          <ul class="webhook-list">
            <For each={webhooks()}>
              {(webhook) => (
                <li class="webhook-item">
                  <div class="webhook-info">
                    <div class="webhook-name">
                      <span>{webhook.name}</span>
                      <Show when={!webhook.enabled}>
                        <span class="webhook-badge webhook-badge-warn">
                          {t("settings.discordWebhooks.disabled" as any)}
                        </span>
                      </Show>
                    </div>
                    <div class="webhook-url">{webhook.webhook_url_masked}</div>
                    <Show when={webhook.last_error}>
                      <div class="webhook-error-message">
                        {t("settings.discordWebhooks.lastError" as any)}:{" "}
                        {webhook.last_error}
                      </div>
                    </Show>
                    <Show when={testResult() && testResult()!.id === webhook.id}>
                      <div
                        class={
                          testResult()!.ok
                            ? "webhook-test-success"
                            : "webhook-test-failure"
                        }
                      >
                        {testResult()!.message}
                      </div>
                    </Show>
                  </div>
                  <div class="webhook-actions">
                    <button
                      class="btn btn-small btn-secondary"
                      onClick={() => handleTest(webhook)}
                    >
                      {t("settings.discordWebhooks.test" as any)}
                    </button>
                    <button
                      class="btn btn-small btn-secondary"
                      onClick={() => openEdit(webhook)}
                    >
                      {t("settings.discordWebhooks.edit" as any)}
                    </button>
                    <button
                      class="btn btn-small btn-danger"
                      onClick={() => handleDelete(webhook)}
                    >
                      {t("settings.discordWebhooks.delete" as any)}
                    </button>
                  </div>
                </li>
              )}
            </For>
          </ul>
        </Show>
      </Show>

      <button class="btn" onClick={openCreate}>
        {t("settings.discordWebhooks.add" as any)}
      </button>

      <Show when={showModal()}>
        <div class="modal-overlay" onClick={closeModal}>
          <div
            class="modal-content"
            style={{ "max-width": "520px" }}
            onClick={(e) => e.stopPropagation()}
          >
            <div class="modal-header">
              <h3>
                {editing()
                  ? t("settings.discordWebhooks.editTitle" as any)
                  : t("settings.discordWebhooks.addTitle" as any)}
              </h3>
              <button class="modal-close" onClick={closeModal} aria-label="close">
                ✕
              </button>
            </div>

            <form onSubmit={handleSubmit} class="webhook-form">
              <div class="webhook-form-body">
                <div class="settings-form-group">
                  <label>{t("settings.discordWebhooks.name" as any)}</label>
                  <input
                    type="text"
                    value={draft().name}
                    onInput={(e) =>
                      setDraft({ ...draft(), name: e.currentTarget.value })
                    }
                    required
                    maxLength={100}
                  />
                </div>

                <div class="settings-form-group">
                  <label>{t("settings.discordWebhooks.url" as any)}</label>
                  <input
                    type="url"
                    value={draft().webhook_url}
                    onInput={(e) =>
                      setDraft({ ...draft(), webhook_url: e.currentTarget.value })
                    }
                    placeholder={t("settings.discordWebhooks.urlPlaceholder" as any)}
                    required={!editing()}
                  />
                  <Show when={editing()}>
                    <small class="settings-label">
                      {t("settings.discordWebhooks.urlEditHint" as any)}
                    </small>
                  </Show>
                </div>

                <div class="settings-form-group">
                  <label>{t("settings.discordWebhooks.notifyTitle" as any)}</label>
                  <div class="webhook-notify-grid">
                    <For each={NOTIFY_KEYS}>
                      {(key) => (
                        <label class="toggle-label">
                          <input
                            type="checkbox"
                            checked={draft()[key] ?? true}
                            onChange={(e) =>
                              setDraft({
                                ...draft(),
                                [key]: e.currentTarget.checked,
                              })
                            }
                          />
                          <span>{t(NOTIFY_LABEL_KEY[key] as any)}</span>
                        </label>
                      )}
                    </For>
                  </div>
                </div>

                <label class="toggle-label">
                  <input
                    type="checkbox"
                    checked={draft().enabled ?? true}
                    onChange={(e) =>
                      setDraft({ ...draft(), enabled: e.currentTarget.checked })
                    }
                  />
                  <span>{t("settings.discordWebhooks.enabled" as any)}</span>
                </label>

                <Show when={error()}>
                  <p class="error">{error()}</p>
                </Show>
              </div>

              <div class="modal-footer">
                <button
                  type="button"
                  class="btn btn-small btn-secondary"
                  onClick={closeModal}
                >
                  {t("common.cancel" as any)}
                </button>
                <button
                  type="submit"
                  class="btn btn-small"
                  disabled={submitting()}
                >
                  {t("common.save" as any)}
                </button>
              </div>
            </form>
          </div>
        </div>
      </Show>
    </div>
  );
}
