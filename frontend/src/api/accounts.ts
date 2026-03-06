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
