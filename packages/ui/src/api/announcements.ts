import { apiRequest } from "./client";

export interface MastodonAnnouncement {
  id: string;
  title: string;
  content: string;
  starts_at: string | null;
  ends_at: string | null;
  all_day: boolean;
  published_at: string;
  updated_at: string;
  read: boolean;
}

export async function getUserAnnouncements(): Promise<MastodonAnnouncement[]> {
  return apiRequest<MastodonAnnouncement[]>("/api/v1/announcements");
}

export async function dismissAnnouncement(id: string): Promise<void> {
  await apiRequest(`/api/v1/announcements/${id}/dismiss`, { method: "POST" });
}

export async function getAnnouncementsUnreadCount(): Promise<{ count: number }> {
  return apiRequest<{ count: number }>("/api/v1/announcements/unread_count");
}
