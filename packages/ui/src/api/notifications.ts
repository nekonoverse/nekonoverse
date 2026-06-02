import { apiRequest } from "./client";
import type { NoteActor } from "./statuses";
import type { Note } from "./statuses";

export interface Notification {
  id: string;
  type: string;
  // サーバ内部の生 type。type は Mastodon 互換のためマッピング後 (quote→reblog,
  // reaction→favourite 等) が入るが、こちらは Notification 行に格納された生値
  // (quote / reaction / reply 等を区別したい自家 UI 向け nekonoverse 拡張)。
  nekonoverse_type?: string;
  created_at: string;
  read: boolean;
  account?: NoteActor;
  status?: Note;
  emoji?: string;
  emoji_url?: string | null;
}

export async function getNotifications(params?: {
  max_id?: string;
  limit?: number;
  types?: string[];
}): Promise<Notification[]> {
  const query = new URLSearchParams();
  if (params?.max_id) query.set("max_id", params.max_id);
  if (params?.limit) query.set("limit", String(params.limit));
  if (params?.types) {
    for (const t of params.types) query.append("types[]", t);
  }
  const qs = query.toString();
  return apiRequest<Notification[]>(`/api/v1/notifications${qs ? `?${qs}` : ""}`);
}

export async function dismissNotification(id: string): Promise<void> {
  await apiRequest(`/api/v1/notifications/${id}/dismiss`, { method: "POST" });
}

export async function markAllNotificationsAsRead(): Promise<void> {
  await apiRequest("/api/v1/notifications/mark_all_as_read", { method: "POST" });
}

export async function clearNotifications(): Promise<void> {
  await apiRequest("/api/v1/notifications/clear", { method: "POST" });
}
