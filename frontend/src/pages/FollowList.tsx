import { createSignal, onMount, Show, For } from "solid-js";
import { A, useParams, useLocation } from "@solidjs/router";
import {
  lookupAccount,
  getFollowers,
  getFollowing,
  followAccount,
  unfollowAccount,
  type Account,
} from "../api/accounts";
import { useI18n } from "../i18n";
import { currentUser } from "../stores/auth";
import { isFollowing as isFollowingUser, addFollowedId, removeFollowedId } from "../stores/followedUsers";
import { sanitizeHtml } from "@nekonoverse/ui/utils/sanitize";
import { emojify } from "@nekonoverse/ui/utils/emojify";
import { twemojify } from "@nekonoverse/ui/utils/twemojify";
import { defaultAvatar } from "../stores/instance";

export default function FollowList() {
  const { t } = useI18n();
  const params = useParams<{ acct: string }>();
  const location = useLocation();

  const [account, setAccount] = createSignal<Account | null>(null);
  const [accounts, setAccounts] = createSignal<Account[]>([]);
  const [loading, setLoading] = createSignal(true);
  const [error, setError] = createSignal("");
  const [followLoadingId, setFollowLoadingId] = createSignal<string | null>(null);

  const tab = () => location.pathname.endsWith("/following") ? "following" : "followers";

  const loadData = async () => {
    setLoading(true);
    setError("");
    try {
      const acct = params.acct.replace(/^@/, "");
      const acc = await lookupAccount(acct);
      setAccount(acc);

      const list = tab() === "followers"
        ? await getFollowers(acc.id)
        : await getFollowing(acc.id);
      setAccounts(list);
    } catch (e: any) {
      setError(e.message || "Not found");
    } finally {
      setLoading(false);
    }
  };

  onMount(loadData);

  const handleFollow = async (targetId: string) => {
    setFollowLoadingId(targetId);
    try {
      if (isFollowingUser(targetId)) {
        await unfollowAccount(targetId);
        removeFollowedId(targetId);
      } else {
        await followAccount(targetId);
        addFollowedId(targetId);
      }
    } catch {}
    setFollowLoadingId(null);
  };

  const acctPath = () => `/@${params.acct.replace(/^@/, "")}`;

  return (
    <div class="page-container">
      <Show when={!loading()} fallback={<p>{t("common.loading")}</p>}>
        <Show when={!error()} fallback={<p class="error">{error()}</p>}>
          <div class="follow-list-header">
            <A href={acctPath()} class="follow-list-back">
              {t("profile.backToProfile")}
            </A>
            <h2 class="follow-list-username">
              {account()?.display_name || account()?.username}
            </h2>
          </div>

          <div class="follow-list-tabs">
            <A
              href={`${acctPath()}/followers`}
              class={`follow-list-tab${tab() === "followers" ? " active" : ""}`}
            >
              {t("profile.followers")}
              <Show when={account()?.followers_count != null}>
                <span class="follow-list-tab-count">{account()!.followers_count}</span>
              </Show>
            </A>
            <A
              href={`${acctPath()}/following`}
              class={`follow-list-tab${tab() === "following" ? " active" : ""}`}
            >
              {t("profile.followingList")}
              <Show when={account()?.following_count != null}>
                <span class="follow-list-tab-count">{account()!.following_count}</span>
              </Show>
            </A>
          </div>

          <div class="follow-list-content">
            <Show
              when={accounts().length > 0}
              fallback={
                <p class="empty">
                  {tab() === "followers" ? t("profile.noFollowers") : t("profile.noFollowing")}
                </p>
              }
            >
              <For each={accounts()}>
                {(acc) => {
                  const isOwn = () =>
                    currentUser()?.username === acc.username &&
                    !acc.acct.includes("@");

                  return (
                    <div class="follow-list-item">
                      <A href={`/@${acc.acct}`} class="follow-list-item-link">
                        <img
                          class="follow-list-avatar"
                          src={acc.avatar || defaultAvatar()}
                          alt=""
                        />
                        <div class="follow-list-item-info">
                          <span class="follow-list-display-name" ref={(el) => {
                            el.textContent = acc.display_name || acc.username;
                            if (acc.emojis) emojify(el, acc.emojis);
                            twemojify(el);
                          }} />
                          <span class="follow-list-handle">@{acc.acct}</span>
                          <Show when={acc.note}>
                            <p class="follow-list-bio" ref={(el) => {
                              el.innerHTML = sanitizeHtml(acc.note);
                              if (acc.emojis) emojify(el, acc.emojis);
                              twemojify(el);
                            }} />
                          </Show>
                        </div>
                      </A>
                      <Show when={currentUser() && !isOwn()}>
                        <button
                          class={`btn btn-small${isFollowingUser(acc.id) ? " btn-following" : ""}`}
                          disabled={followLoadingId() === acc.id}
                          onClick={() => handleFollow(acc.id)}
                        >
                          {isFollowingUser(acc.id) ? t("profile.following") : t("profile.follow")}
                        </button>
                      </Show>
                    </div>
                  );
                }}
              </For>
            </Show>
          </div>
        </Show>
      </Show>
    </div>
  );
}
