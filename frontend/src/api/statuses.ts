import { apiRequest } from "./client";

export interface NoteActor {
  id: string;
  username: string;
  display_name: string | null;
  avatar_url: string | null;
  ap_id: string;
  domain: string | null;
}

export interface ReactionSummary {
  emoji: string;
  count: number;
  me: boolean;
}

export interface Note {
  id: string;
  ap_id: string;
  content: string;
  source: string | null;
  visibility: string;
  sensitive: boolean;
  spoiler_text: string | null;
  published: string;
  replies_count: number;
  reactions_count: number;
  renotes_count: number;
  actor: NoteActor;
  reactions: ReactionSummary[];
}

export async function createNote(content: string, visibility = "public"): Promise<Note> {
  return apiRequest<Note>("/api/v1/statuses", {
    method: "POST",
    body: { content, visibility },
  });
}

export async function getPublicTimeline(params?: {
  local?: boolean;
  max_id?: string;
  limit?: number;
}): Promise<Note[]> {
  const query = new URLSearchParams();
  if (params?.local) query.set("local", "true");
  if (params?.max_id) query.set("max_id", params.max_id);
  if (params?.limit) query.set("limit", String(params.limit));
  const qs = query.toString();
  return apiRequest<Note[]>(`/api/v1/timelines/public${qs ? `?${qs}` : ""}`);
}

export async function getHomeTimeline(params?: {
  max_id?: string;
  limit?: number;
}): Promise<Note[]> {
  const query = new URLSearchParams();
  if (params?.max_id) query.set("max_id", params.max_id);
  if (params?.limit) query.set("limit", String(params.limit));
  const qs = query.toString();
  return apiRequest<Note[]>(`/api/v1/timelines/home${qs ? `?${qs}` : ""}`);
}

export async function getNote(noteId: string): Promise<Note> {
  return apiRequest<Note>(`/api/v1/statuses/${noteId}`);
}

export async function reactToNote(noteId: string, emoji: string): Promise<void> {
  await apiRequest(`/api/v1/statuses/${noteId}/react/${encodeURIComponent(emoji)}`, {
    method: "POST",
  });
}

export async function unreactToNote(noteId: string, emoji: string): Promise<void> {
  await apiRequest(`/api/v1/statuses/${noteId}/unreact/${encodeURIComponent(emoji)}`, {
    method: "POST",
  });
}
