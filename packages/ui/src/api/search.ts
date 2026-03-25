import { apiRequest } from "./client";
import type { Account } from "./accounts";
import type { Note } from "./statuses";

export interface SearchResult {
  accounts: Account[];
  statuses: Note[];
  hashtags: { name: string; url: string; history: unknown[] }[];
}

export async function searchV2(
  q: string,
  resolve = false,
): Promise<SearchResult> {
  const params = new URLSearchParams({ q, resolve: String(resolve) });
  return apiRequest<SearchResult>(`/api/v2/search?${params}`);
}

export interface SuggestResult {
  suggestions: { token: string; df: number }[];
  prefix: string;
}

export async function searchSuggest(
  q: string,
  limit = 10,
): Promise<SuggestResult> {
  const params = new URLSearchParams({ q, limit: String(limit) });
  return apiRequest<SuggestResult>(`/api/v2/search/suggest?${params}`);
}
