import { createSignal } from "solid-js";
import { apiRequest } from "../api/client";
import { authenticateWithPasskey as _authenticateWithPasskey } from "../api/passkey";

export interface ProfileField {
  name: string;
  value: string;
}

export interface CurrentUser {
  id: string;
  username: string;
  display_name: string | null;
  avatar_url: string | null;
  header_url: string | null;
  summary: string | null;
  fields: ProfileField[];
  birthday: string | null;
  is_cat: boolean;
  is_bot: boolean;
  locked: boolean;
  discoverable: boolean;
  role: string;
}

const [currentUser, setCurrentUser] = createSignal<CurrentUser | null>(null);
const [authLoading, setAuthLoading] = createSignal(true);

export { currentUser, authLoading };

export async function fetchCurrentUser() {
  setAuthLoading(true);
  try {
    const user = await apiRequest<CurrentUser>("/api/v1/accounts/verify_credentials");
    setCurrentUser(user);
  } catch {
    setCurrentUser(null);
  } finally {
    setAuthLoading(false);
  }
}

export async function login(username: string, password: string) {
  await apiRequest("/api/v1/auth/login", {
    method: "POST",
    body: { username, password },
  });
  await fetchCurrentUser();
}

export async function logout() {
  await apiRequest("/api/v1/auth/logout", { method: "POST" });
  setCurrentUser(null);
}

export async function loginWithPasskey() {
  await _authenticateWithPasskey();
  await fetchCurrentUser();
}

export async function register(username: string, email: string, password: string) {
  await apiRequest("/api/v1/accounts", {
    method: "POST",
    body: { username, email, password },
  });
  await login(username, password);
}
