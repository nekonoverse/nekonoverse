import { createSignal } from "solid-js";
import { apiRequest } from "../api/client";
import { authenticateWithPasskey as _authenticateWithPasskey } from "../api/passkey";
import { fetchFollowedIds } from "./followedUsers";
import type { CurrentUser, LoginResponse } from "../api/types/auth";
import { getRoleName } from "../api/types/auth";

export type { CurrentUser, ProfileField, FocalPoint, LoginResponse } from "../api/types/auth";

const CACHED_USER_KEY = "nekonoverse_cached_user";

// localStorageから同期的にキャッシュを復元
function restoreCachedUser(): CurrentUser | null {
  try {
    const raw = localStorage.getItem(CACHED_USER_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

function cacheUser(user: CurrentUser | null) {
  try {
    if (user) {
      localStorage.setItem(CACHED_USER_KEY, JSON.stringify(user));
    } else {
      localStorage.removeItem(CACHED_USER_KEY);
    }
  } catch {
    // localStorage使用不可時は無視
  }
}

// キャッシュがあれば即座にauthLoading=falseで開始
const cachedUser = restoreCachedUser();
const [currentUser, setCurrentUser] = createSignal<CurrentUser | null>(cachedUser);
const [authLoading, setAuthLoading] = createSignal(!cachedUser);

export { currentUser, authLoading };

export async function fetchCurrentUser() {
  // キャッシュ済みならloadingフラグを立てない(UIをブロックしない)
  if (!currentUser()) setAuthLoading(true);
  try {
    const user = await apiRequest<CurrentUser>(
      "/api/v1/accounts/verify_credentials",
    );
    setCurrentUser(user);
    cacheUser(user);
    fetchFollowedIds();
    // Sync theme from server (non-blocking)
    import("./theme").then((m) => m.syncThemeFromServer()).catch(() => {});
  } catch {
    setCurrentUser(null);
    cacheUser(null);
  } finally {
    setAuthLoading(false);
  }
}

export async function login(
  username: string,
  password: string,
): Promise<LoginResponse> {
  const resp = await apiRequest<LoginResponse>("/api/v1/auth/login", {
    method: "POST",
    body: { username, password },
  });
  if (resp.requires_totp) {
    return resp;
  }
  await fetchCurrentUser();
  return resp;
}

export async function completeTotpLogin(
  code: string,
  totpToken: string,
): Promise<void> {
  await apiRequest("/api/v1/auth/totp/verify", {
    method: "POST",
    body: { code, totp_token: totpToken },
  });
  await fetchCurrentUser();
}

export async function logout() {
  await apiRequest("/api/v1/auth/logout", { method: "POST" });
  setCurrentUser(null);
  cacheUser(null);
}

export async function loginWithPasskey() {
  await _authenticateWithPasskey();
  await fetchCurrentUser();
}

/** Check if current user has emoji management permission. */
export function canManageEmoji(): boolean {
  const u = currentUser();
  if (!u) return false;
  const r = getRoleName(u.role);
  if (r === "admin") return true;
  return u.nekonoverse_permissions?.includes("emoji") ?? false;
}

/** Check if current user has content moderation permission. */
export function canModerateContent(): boolean {
  const u = currentUser();
  if (!u) return false;
  const r = getRoleName(u.role);
  if (r === "admin") return true;
  return u.nekonoverse_permissions?.includes("content") ?? false;
}

export async function register(
  username: string,
  email: string,
  password: string,
  inviteCode?: string,
  reason?: string,
  captchaToken?: string,
): Promise<{ pending?: boolean }> {
  const body: Record<string, string> = { username, email, password };
  if (inviteCode) body.invite_code = inviteCode;
  if (reason) body.reason = reason;
  if (captchaToken) body.captcha_token = captchaToken;
  await apiRequest("/api/v1/accounts", {
    method: "POST",
    body,
  });
  // 承認制モードではログインせず、pendingフラグを返す
  try {
    await login(username, password);
    return {};
  } catch {
    // ログイン失敗 = 承認待ち
    return { pending: true };
  }
}
