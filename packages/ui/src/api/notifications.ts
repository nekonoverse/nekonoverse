import { apiRequest } from "./client";
import type { NoteActor } from "./statuses";
import type { Note } from "./statuses";

export interface Notification {
  id: string;
  type: string;
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
}): Promise<Notification[]> {
  const query = new URLSearchParams();
  if (params?.max_id) query.set("max_id", params.max_id);
  if (params?.limit) query.set("limit", String(params.limit));
  const qs = query.toString();
  return apiRequest<Notification[]>(`/api/v1/notifications${qs ? `?${qs}` : ""}`);
}

export async function dismissNotification(id: string): Promise<void> {
  await apiRequest(`/api/v1/notifications/${id}/dismiss`, { method: "POST" });
}

export async function clearNotifications(): Promise<void> {
  await apiRequest("/api/v1/notifications/clear", { method: "POST" });
}
