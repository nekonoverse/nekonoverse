import { createResource, createSignal, For, Show } from "solid-js";
import {
  deletePasskey,
  listPasskeys,
  registerPasskey,
  type PasskeyCredentialInfo,
} from "@nekonoverse/ui/api/passkey";
import { useI18n } from "../i18n";

export default function PasskeyManager() {
  const { t } = useI18n();
  const [newKeyName, setNewKeyName] = createSignal("");
  const [adding, setAdding] = createSignal(false);
  const [error, setError] = createSignal("");

  const [passkeys, { refetch }] = createResource(listPasskeys);

  const handleAdd = async () => {
    setError("");
    setAdding(true);
    try {
      await registerPasskey(newKeyName() || undefined);
      setNewKeyName("");
      refetch();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("passkey.addFailed"));
    } finally {
      setAdding(false);
    }
  };

  const handleDelete = async (id: string) => {
    if (!confirm(t("passkey.confirmDelete"))) return;
    try {
      await deletePasskey(id);
      refetch();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("passkey.deleteFailed"));
    }
  };

  return (
    <div class="passkey-manager">
      <h3>{t("passkey.title")}</h3>
      {error() && <div class="error">{error()}</div>}
      <Show when={!passkeys.loading} fallback={<p>{t("common.loading")}</p>}>
        <Show
          when={(passkeys() ?? []).length > 0}
          fallback={<p class="passkey-empty">{t("passkey.noPasskeys")}</p>}
        >
          <ul class="passkey-list">
            <For each={passkeys()}>
              {(pk: PasskeyCredentialInfo) => (
                <li class="passkey-item">
                  <div class="passkey-info">
                    <span class="passkey-name">{pk.name ?? t("passkey.unnamed")}</span>
                    <span class="passkey-date">
                      {t("passkey.added")}: {new Date(pk.created_at).toLocaleDateString()}
                    </span>
                    <Show when={pk.last_used_at}>
                      <span class="passkey-last-used">
                        {t("passkey.lastUsed")}: {new Date(pk.last_used_at!).toLocaleDateString()}
                      </span>
                    </Show>
                  </div>
                  <button class="btn-danger" onClick={() => handleDelete(pk.id)}>
                    {t("passkey.delete")}
                  </button>
                </li>
              )}
            </For>
          </ul>
        </Show>
      </Show>
      <div class="passkey-add">
        <input
          type="text"
          placeholder={t("passkey.namePlaceholder")}
          value={newKeyName()}
          onInput={(e) => setNewKeyName(e.currentTarget.value)}
        />
        <button onClick={handleAdd} disabled={adding()}>
          {adding() ? t("passkey.adding") : t("passkey.addButton")}
        </button>
      </div>
    </div>
  );
}
