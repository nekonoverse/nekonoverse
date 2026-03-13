import { createSignal, onMount, Show, For } from "solid-js";
import { apiRequest } from "../api/client";
import type { Account } from "../api/accounts";
import { currentUser, authLoading } from "../stores/auth";
import { useI18n } from "../i18n";
import { defaultAvatar } from "../stores/instance";

export default function FollowRequests() {
  const { t } = useI18n();
  const [requests, setRequests] = createSignal<Account[]>([]);
  const [loading, setLoading] = createSignal(true);

  onMount(async () => {
    try {
      const data = await apiRequest<Account[]>("/api/v1/follow_requests");
      setRequests(data);
    } catch {}
    setLoading(false);
  });

  const authorize = async (id: string) => {
    try {
      await apiRequest(`/api/v1/follow_requests/${id}/authorize`, { method: "POST" });
      setRequests((prev) => prev.filter((r) => r.id !== id));
    } catch {}
  };

  const reject = async (id: string) => {
    try {
      await apiRequest(`/api/v1/follow_requests/${id}/reject`, { method: "POST" });
      setRequests((prev) => prev.filter((r) => r.id !== id));
    } catch {}
  };

  return (
    <div class="page-container">
      <h1>{t("followRequest.title")}</h1>
      <Show when={!authLoading()} fallback={<p>{t("common.loading")}</p>}>
        <Show when={currentUser()} fallback={<p>{t("followRequest.loginRequired")}</p>}>
          <Show when={!loading()} fallback={<p>{t("common.loading")}</p>}>
            <Show when={requests().length > 0} fallback={<p class="empty">{t("followRequest.empty")}</p>}>
              <div class="follow-requests-list">
                <For each={requests()}>
                  {(account) => (
                    <div class="follow-request-item">
                      <a href={account.url?.startsWith("http") ? `/@${account.acct}` : account.url} class="follow-request-user">
                        <img
                          src={account.avatar || defaultAvatar()}
                          alt={account.username}
                          class="follow-request-avatar"
                        />
                        <div class="follow-request-info">
                          <strong class="follow-request-name">{account.display_name || account.username}</strong>
                          <span class="follow-request-acct">@{account.acct}</span>
                        </div>
                      </a>
                      <div class="follow-request-actions">
                        <button class="btn follow-request-accept" onClick={() => authorize(account.id)}>
                          {t("followRequest.accept")}
                        </button>
                        <button class="btn follow-request-reject" onClick={() => reject(account.id)}>
                          {t("followRequest.reject")}
                        </button>
                      </div>
                    </div>
                  )}
                </For>
              </div>
            </Show>
          </Show>
        </Show>
      </Show>
    </div>
  );
}
