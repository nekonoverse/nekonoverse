import { createSignal, createResource, For, Show } from "solid-js";
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
  const [showCreate, setShowCreate] = createSignal(false);
  const [draft, setDraft] = createSignal<DiscordWebhookInput>(defaultInput());
  const [error, setError] = createSignal<string | null>(null);
  const [testResult, setTestResult] = createSignal<{ id: string; ok: boolean; message: string } | null>(null);

  function openCreate() {
    setDraft(defaultInput());
    setEditing(null);
    setError(null);
    setShowCreate(true);
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
    setError(null);
    setShowCreate(true);
  }

  function closeModal() {
    setShowCreate(false);
    setEditing(null);
    setError(null);
  }

  async function handleSubmit(e: Event) {
    e.preventDefault();
    setError(null);
    const current = editing();
    const payload = draft();
    try {
      if (current) {
        // 編集モード: webhook_url が空欄なら URL は変更しない
        const updates: Partial<DiscordWebhookInput> = { ...payload };
        if (!payload.webhook_url) {
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
      <p class="settings-description">{t("settings.discordWebhooks.description" as any)}</p>

      <button class="btn" onClick={openCreate}>
        {t("settings.discordWebhooks.add" as any)}
      </button>

      <Show when={error()}>
        <p class="error-message">{error()}</p>
      </Show>

      <Show
        when={webhooks() && webhooks()!.length > 0}
        fallback={
          <Show when={!webhooks.loading}>
            <p class="settings-empty">{t("settings.discordWebhooks.empty" as any)}</p>
          </Show>
        }
      >
        <ul class="discord-webhook-list">
          <For each={webhooks()!}>
            {(webhook) => (
              <li class="discord-webhook-row">
                <div class="discord-webhook-row-main">
                  <div class="discord-webhook-row-name">
                    {webhook.name}
                    <Show when={!webhook.enabled}>
                      {" "}
                      <span class="badge badge-warn">
                        {t("settings.discordWebhooks.disabled" as any)}
                      </span>
                    </Show>
                  </div>
                  <div class="discord-webhook-row-url">{webhook.webhook_url_masked}</div>
                  <Show when={webhook.last_error}>
                    <div class="discord-webhook-row-error">
                      {t("settings.discordWebhooks.lastError" as any)}: {webhook.last_error}
                    </div>
                  </Show>
                  <Show when={testResult() && testResult()!.id === webhook.id}>
                    <div
                      class={
                        testResult()!.ok
                          ? "discord-webhook-row-success"
                          : "discord-webhook-row-error"
                      }
                    >
                      {testResult()!.message}
                    </div>
                  </Show>
                </div>
                <div class="discord-webhook-row-actions">
                  <button class="btn btn-small" onClick={() => handleTest(webhook)}>
                    {t("settings.discordWebhooks.test" as any)}
                  </button>
                  <button class="btn btn-small" onClick={() => openEdit(webhook)}>
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

      <Show when={showCreate()}>
        <div class="modal-overlay" onClick={closeModal}>
          <div class="modal-content" onClick={(e) => e.stopPropagation()}>
            <h4>
              {editing()
                ? t("settings.discordWebhooks.editTitle" as any)
                : t("settings.discordWebhooks.addTitle" as any)}
            </h4>
            <form onSubmit={handleSubmit}>
              <label>
                {t("settings.discordWebhooks.name" as any)}
                <input
                  type="text"
                  value={draft().name}
                  onInput={(e) =>
                    setDraft({ ...draft(), name: e.currentTarget.value })
                  }
                  required
                  maxLength={100}
                />
              </label>
              <label>
                {t("settings.discordWebhooks.url" as any)}
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
                  <small>{t("settings.discordWebhooks.urlEditHint" as any)}</small>
                </Show>
              </label>

              <fieldset>
                <legend>{t("settings.discordWebhooks.notifyTitle" as any)}</legend>
                <For each={NOTIFY_KEYS}>
                  {(key) => (
                    <label class="checkbox-label">
                      <input
                        type="checkbox"
                        checked={draft()[key] ?? true}
                        onChange={(e) =>
                          setDraft({ ...draft(), [key]: e.currentTarget.checked })
                        }
                      />
                      {t(NOTIFY_LABEL_KEY[key] as any)}
                    </label>
                  )}
                </For>
              </fieldset>

              <label class="checkbox-label">
                <input
                  type="checkbox"
                  checked={draft().enabled ?? true}
                  onChange={(e) =>
                    setDraft({ ...draft(), enabled: e.currentTarget.checked })
                  }
                />
                {t("settings.discordWebhooks.enabled" as any)}
              </label>

              <Show when={error()}>
                <p class="error-message">{error()}</p>
              </Show>

              <div class="modal-actions">
                <button type="button" class="btn" onClick={closeModal}>
                  {t("common.cancel" as any)}
                </button>
                <button type="submit" class="btn btn-primary">
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
