import { apiRequest } from "./client";
import type { Note } from "./statuses";
import type { Account } from "./accounts";

export interface ListInfo {
  id: string;
  title: string;
  replies_policy: string;
  exclusive: boolean;
}

export async function getLists(): Promise<ListInfo[]> {
  return apiRequest<ListInfo[]>("/api/v1/lists");
}

export async function getAccountLists(accountId: string): Promise<ListInfo[]> {
  return apiRequest<ListInfo[]>(`/api/v1/accounts/${accountId}/lists`);
}

export async function getList(id: string): Promise<ListInfo> {
  return apiRequest<ListInfo>(`/api/v1/lists/${id}`);
}

export async function createList(
  title: string,
  repliesPolicy = "list",
  exclusive = false,
): Promise<ListInfo> {
  return apiRequest<ListInfo>("/api/v1/lists", {
    method: "POST",
    body: { title, replies_policy: repliesPolicy, exclusive },
  });
}

export async function updateList(
  id: string,
  params: { title?: string; replies_policy?: string; exclusive?: boolean },
): Promise<ListInfo> {
  return apiRequest<ListInfo>(`/api/v1/lists/${id}`, {
    method: "PUT",
    body: params,
  });
}

export async function deleteList(id: string): Promise<void> {
  return apiRequest<void>(`/api/v1/lists/${id}`, { method: "DELETE" });
}

export async function getListAccounts(id: string): Promise<Account[]> {
  return apiRequest<Account[]>(`/api/v1/lists/${id}/accounts`);
}

export async function addListAccounts(id: string, accountIds: string[]): Promise<void> {
  return apiRequest<void>(`/api/v1/lists/${id}/accounts`, {
    method: "POST",
    body: { account_ids: accountIds },
  });
}

export async function removeListAccounts(id: string, accountIds: string[]): Promise<void> {
  return apiRequest<void>(`/api/v1/lists/${id}/accounts`, {
    method: "DELETE",
    body: { account_ids: accountIds },
  });
}

export async function getListTimeline(
  id: string,
  params?: { max_id?: string; limit?: number },
): Promise<Note[]> {
  const query = new URLSearchParams();
  if (params?.max_id) query.set("max_id", params.max_id);
  if (params?.limit) query.set("limit", String(params.limit));
  const qs = query.toString();
  return apiRequest<Note[]>(`/api/v1/timelines/list/${id}${qs ? `?${qs}` : ""}`);
}
