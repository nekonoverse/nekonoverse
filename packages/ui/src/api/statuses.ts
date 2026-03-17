import { apiRequest } from "./client";
import type { CustomEmoji } from "../types/emoji";

export type { CustomEmoji } from "../types/emoji";

export interface NoteActor {
  id: string;
  username: string;
  display_name: string | null;
  avatar_url: string | null;
  ap_id: string;
  domain: string | null;
  server_software: string | null;
  server_software_version: string | null;
  emojis: CustomEmoji[];
}

export interface ReactionSummary {
  emoji: string;
  count: number;
  me: boolean;
  emoji_url: string | null;
}

export interface MediaAttachment {
  id: string;
  type: string;
  url: string;
  preview_url: string;
  description: string | null;
  blurhash: string | null;
  meta: {
    original?: { width: number; height: number };
    focus?: { x: number; y: number };
  } | null;
}

export interface PollOption {
  title: string;
  votes_count: number;
}

export interface Poll {
  id: string;
  expires_at: string | null;
  expired: boolean;
  multiple: boolean;
  votes_count: number;
  voters_count: number;
  options: PollOption[];
  voted: boolean;
  own_votes: number[];
}

export interface TagInfo {
  name: string;
  url: string;
}

export interface PreviewCard {
  url: string;
  title: string;
  description: string;
  image: string | null;
  type: string;
  author_name: string;
  author_url: string;
  provider_name: string;
  provider_url: string;
  html: string;
  width: number;
  height: number;
  embed_url: string;
  blurhash: string | null;
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
  edited_at: string | null;
  replies_count: number;
  reactions_count: number;
  renotes_count: number;
  in_reply_to_id: string | null;
  in_reply_to_account_id: string | null;
  actor: NoteActor;
  reactions: ReactionSummary[];
  media_attachments: MediaAttachment[];
  reblog: Note | null;
  quote: Note | null;
  poll: Poll | null;
  reblogged: boolean;
  favourited: boolean;
  favourites_count: number;
  pinned: boolean;
  emojis: CustomEmoji[];
  tags: TagInfo[];
  card: PreviewCard | null;
}

export interface NoteContext {
  ancestors: Note[];
  descendants: Note[];
}

export interface NoteEditHistoryEntry {
  content: string;
  source: string | null;
  spoiler_text: string | null;
  created_at: string;
}

export async function uploadMedia(
  file: File, description?: string, focus?: string,
): Promise<MediaAttachment> {
  const formData = new FormData();
  formData.append("file", file);
  if (description) formData.append("description", description);
  if (focus) formData.append("focus", focus);
  return apiRequest<MediaAttachment>("/api/v1/media", {
    method: "POST",
    formData,
  });
}

export async function updateMedia(
  id: string, description?: string, focus?: string,
): Promise<MediaAttachment> {
  const formData = new FormData();
  if (description !== undefined) formData.append("description", description);
  if (focus) formData.append("focus", focus);
  return apiRequest<MediaAttachment>(`/api/v1/media/${id}`, {
    method: "PUT",
    formData,
  });
}

export interface PollCreate {
  options: string[];
  expires_in?: number;
  multiple?: boolean;
}

export async function createNote(
  content: string,
  visibility = "public",
  mediaIds?: string[],
  quoteId?: string,
  inReplyToId?: string,
  poll?: PollCreate,
  sensitive?: boolean,
  spoilerText?: string,
): Promise<Note> {
  const body: Record<string, unknown> = { content, visibility, media_ids: mediaIds || [] };
  if (quoteId) body.quote_id = quoteId;
  if (inReplyToId) body.in_reply_to_id = inReplyToId;
  if (poll) body.poll = poll;
  if (sensitive) body.sensitive = true;
  if (spoilerText) body.spoiler_text = spoilerText;
  return apiRequest<Note>("/api/v1/statuses", {
    method: "POST",
    body,
  });
}

export async function getContext(noteId: string): Promise<NoteContext> {
  return apiRequest<NoteContext>(`/api/v1/statuses/${noteId}/context`);
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

export interface ReactionUser {
  actor: NoteActor;
  emoji: string;
}

export async function getReactedBy(noteId: string, emoji?: string): Promise<ReactionUser[]> {
  const qs = emoji ? `?emoji=${encodeURIComponent(emoji)}` : "";
  return apiRequest<ReactionUser[]>(`/api/v1/statuses/${noteId}/reacted_by${qs}`);
}

export async function favouriteNote(noteId: string): Promise<Note> {
  return apiRequest<Note>(`/api/v1/statuses/${noteId}/favourite`, {
    method: "POST",
  });
}

export async function unfavouriteNote(noteId: string): Promise<Note> {
  return apiRequest<Note>(`/api/v1/statuses/${noteId}/unfavourite`, {
    method: "POST",
  });
}

export async function deleteNote(noteId: string): Promise<void> {
  await apiRequest(`/api/v1/statuses/${noteId}`, { method: "DELETE" });
}

export async function bookmarkNote(noteId: string): Promise<void> {
  await apiRequest(`/api/v1/statuses/${noteId}/bookmark`, { method: "POST" });
}

export async function unbookmarkNote(noteId: string): Promise<void> {
  await apiRequest(`/api/v1/statuses/${noteId}/unbookmark`, { method: "POST" });
}

export async function getBookmarks(params?: { max_id?: string; limit?: number }): Promise<Note[]> {
  const query = new URLSearchParams();
  if (params?.max_id) query.set("max_id", params.max_id);
  if (params?.limit) query.set("limit", String(params.limit));
  const qs = query.toString();
  return apiRequest<Note[]>(`/api/v1/bookmarks${qs ? `?${qs}` : ""}`);
}

export async function pinNote(noteId: string): Promise<void> {
  await apiRequest(`/api/v1/statuses/${noteId}/pin`, { method: "POST" });
}

export async function unpinNote(noteId: string): Promise<void> {
  await apiRequest(`/api/v1/statuses/${noteId}/unpin`, { method: "POST" });
}

export async function getPoll(noteId: string): Promise<Poll> {
  return apiRequest<Poll>(`/api/v1/polls/${noteId}`);
}

export async function votePoll(noteId: string, choices: number[]): Promise<Poll> {
  return apiRequest<Poll>(`/api/v1/polls/${noteId}/votes`, {
    method: "POST",
    body: { choices },
  });
}

export async function getTagTimeline(tag: string, params?: {
  max_id?: string;
  limit?: number;
}): Promise<Note[]> {
  const query = new URLSearchParams();
  if (params?.max_id) query.set("max_id", params.max_id);
  if (params?.limit) query.set("limit", String(params.limit));
  const qs = query.toString();
  return apiRequest<Note[]>(
    `/api/v1/timelines/tag/${encodeURIComponent(tag)}${qs ? `?${qs}` : ""}`,
  );
}

export interface TrendingTag {
  name: string;
  url: string;
  history: unknown[];
}

export async function getTrendingTags(limit = 10): Promise<TrendingTag[]> {
  return apiRequest<TrendingTag[]>(`/api/v1/trends/tags?limit=${limit}`);
}

export async function editNote(
  noteId: string,
  content: string,
  spoilerText?: string | null,
): Promise<Note> {
  return apiRequest<Note>(`/api/v1/statuses/${noteId}`, {
    method: "PUT",
    body: { content, spoiler_text: spoilerText ?? null },
  });
}

export async function getNoteHistory(noteId: string): Promise<NoteEditHistoryEntry[]> {
  return apiRequest<NoteEditHistoryEntry[]>(`/api/v1/statuses/${noteId}/history`);
}
