import { apiRequest } from "./client";
import type { Note } from "./statuses";

export interface Account {
  id: string;
  username: string;
  acct: string;
  display_name: string | null;
  note: string;
  avatar: string;
  header: string;
  url: string;
  created_at?: string;
}

export async function getAccount(id: string): Promise<Account> {
  return apiRequest<Account>(`/api/v1/accounts/${id}`);
}

export async function lookupAccount(acct: string): Promise<Account> {
  return apiRequest<Account>(`/api/v1/accounts/lookup?acct=${encodeURIComponent(acct)}`);
}

export async function getAccountStatuses(id: string, limit = 20): Promise<Note[]> {
  return apiRequest<Note[]>(`/api/v1/accounts/${id}/statuses?limit=${limit}`);
}

export interface Relationship {
  id: string;
  following: boolean;
  followed_by: boolean;
  blocking: boolean;
  muting: boolean;
}

export async function getRelationship(id: string): Promise<Relationship> {
  return apiRequest<Relationship>(`/api/v1/accounts/${id}/relationship`);
}

export async function followAccount(id: string): Promise<void> {
  await apiRequest(`/api/v1/accounts/${id}/follow`, { method: "POST" });
}

export async function unfollowAccount(id: string): Promise<void> {
  await apiRequest(`/api/v1/accounts/${id}/unfollow`, { method: "POST" });
}

export async function blockAccount(id: string): Promise<void> {
  await apiRequest(`/api/v1/accounts/${id}/block`, { method: "POST" });
}

export async function unblockAccount(id: string): Promise<void> {
  await apiRequest(`/api/v1/accounts/${id}/unblock`, { method: "POST" });
}

export async function muteAccount(id: string): Promise<void> {
  await apiRequest(`/api/v1/accounts/${id}/mute`, { method: "POST" });
}

export async function unmuteAccount(id: string): Promise<void> {
  await apiRequest(`/api/v1/accounts/${id}/unmute`, { method: "POST" });
}

export async function getBlockedAccounts(): Promise<Account[]> {
  return apiRequest<Account[]>("/api/v1/blocks");
}

export async function getMutedAccounts(): Promise<Account[]> {
  return apiRequest<Account[]>("/api/v1/mutes");
}

export async function searchAccounts(q: string, resolve = false): Promise<Account[]> {
  const query = new URLSearchParams({ q });
  if (resolve) query.set("resolve", "true");
  return apiRequest<Account[]>(`/api/v1/accounts/search?${query.toString()}`);
}

export async function moveAccount(targetApId: string): Promise<void> {
  await apiRequest("/api/v1/accounts/move", {
    method: "POST",
    body: { target_ap_id: targetApId },
  });
}
