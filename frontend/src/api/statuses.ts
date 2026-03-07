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

export interface MediaAttachment {
  id: string;
  type: string;
  url: string;
  preview_url: string;
  description: string | null;
  blurhash: string | null;
  meta: { original?: { width: number; height: number } } | null;
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
  media_attachments: MediaAttachment[];
  reblog: Note | null;
  quote: Note | null;
}

export async function uploadMedia(file: File, description?: string): Promise<MediaAttachment> {
  const formData = new FormData();
  formData.append("file", file);
  if (description) formData.append("description", description);
  return apiRequest<MediaAttachment>("/api/v1/media", {
    method: "POST",
    formData,
  });
}

export async function createNote(content: string, visibility = "public", mediaIds?: string[], quoteId?: string): Promise<Note> {
  const body: Record<string, unknown> = { content, visibility, media_ids: mediaIds || [] };
  if (quoteId) body.quote_id = quoteId;
  return apiRequest<Note>("/api/v1/statuses", {
    method: "POST",
    body,
  });
}

export async function reblogNote(noteId: string): Promise<Note> {
  return apiRequest<Note>(`/api/v1/statuses/${noteId}/reblog`, {
    method: "POST",
  });
}

export async function unreblogNote(noteId: string): Promise<{ ok: boolean }> {
  return apiRequest<{ ok: boolean }>(`/api/v1/statuses/${noteId}/unreblog`, {
    method: "POST",
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
