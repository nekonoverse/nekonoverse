import { apiRequest } from "./client";

export interface AdminStats {
  user_count: number;
  note_count: number;
  domain_count: number;
}

export interface ServerSettings {
  server_name: string | null;
  server_description: string | null;
  tos_url: string | null;
  registration_open: boolean;
  server_icon_url: string | null;
}

export interface AdminUser {
  id: string;
  username: string;
  email: string;
  display_name: string | null;
  role: string;
  is_active: boolean;
  suspended: boolean;
  silenced: boolean;
  created_at: string;
}

export interface DomainBlock {
  id: string;
  domain: string;
  severity: string;
  reason: string | null;
  created_at: string;
}

export interface Report {
  id: string;
  reporter: string;
  target: string;
  target_note_id: string | null;
  comment: string | null;
  status: string;
  created_at: string;
  resolved_at: string | null;
}

export interface ModerationLogEntry {
  id: string;
  moderator: string;
  action: string;
  target_type: string;
  target_id: string;
  reason: string | null;
  created_at: string;
}

// Stats
export async function getAdminStats(): Promise<AdminStats> {
  return apiRequest<AdminStats>("/api/v1/admin/stats");
}

// Server Settings
export async function getServerSettings(): Promise<ServerSettings> {
  return apiRequest<ServerSettings>("/api/v1/admin/settings");
}

export async function updateServerSettings(data: Partial<ServerSettings>): Promise<ServerSettings> {
  return apiRequest<ServerSettings>("/api/v1/admin/settings", {
    method: "PATCH",
    body: data,
  });
}

// Users
export async function getAdminUsers(limit = 50, offset = 0): Promise<AdminUser[]> {
  return apiRequest<AdminUser[]>(`/api/v1/admin/users?limit=${limit}&offset=${offset}`);
}

export async function changeUserRole(userId: string, role: string): Promise<void> {
  await apiRequest(`/api/v1/admin/users/${userId}/role`, {
    method: "PATCH",
    body: { role },
  });
}

export async function suspendUser(userId: string, reason?: string): Promise<void> {
  await apiRequest(`/api/v1/admin/users/${userId}/suspend`, {
    method: "POST",
    body: { reason: reason || null },
  });
}

export async function unsuspendUser(userId: string): Promise<void> {
  await apiRequest(`/api/v1/admin/users/${userId}/unsuspend`, { method: "POST" });
}

export async function silenceUser(userId: string, reason?: string): Promise<void> {
  await apiRequest(`/api/v1/admin/users/${userId}/silence`, {
    method: "POST",
    body: { reason: reason || null },
  });
}

export async function unsilenceUser(userId: string): Promise<void> {
  await apiRequest(`/api/v1/admin/users/${userId}/unsilence`, { method: "POST" });
}

// Domain Blocks
export async function getDomainBlocks(): Promise<DomainBlock[]> {
  return apiRequest<DomainBlock[]>("/api/v1/admin/domain_blocks");
}

export async function createDomainBlock(domain: string, severity: string, reason?: string): Promise<DomainBlock> {
  return apiRequest<DomainBlock>("/api/v1/admin/domain_blocks", {
    method: "POST",
    body: { domain, severity, reason: reason || null },
  });
}

export async function removeDomainBlock(domain: string): Promise<void> {
  await apiRequest(`/api/v1/admin/domain_blocks/${encodeURIComponent(domain)}`, {
    method: "DELETE",
  });
}

// Reports
export async function getReports(status?: string): Promise<Report[]> {
  const qs = status ? `?status=${status}` : "";
  return apiRequest<Report[]>(`/api/v1/admin/reports${qs}`);
}

export async function resolveReport(reportId: string): Promise<void> {
  await apiRequest(`/api/v1/admin/reports/${reportId}/resolve`, { method: "POST" });
}

export async function rejectReport(reportId: string): Promise<void> {
  await apiRequest(`/api/v1/admin/reports/${reportId}/reject`, { method: "POST" });
}

// Moderation Log
export async function getModerationLog(limit = 50): Promise<ModerationLogEntry[]> {
  return apiRequest<ModerationLogEntry[]>(`/api/v1/admin/log?limit=${limit}`);
}

// Server Icon
export async function uploadServerIcon(file: File): Promise<{ ok: boolean; url: string }> {
  const formData = new FormData();
  formData.append("file", file);
  return apiRequest<{ ok: boolean; url: string }>("/api/v1/admin/server-icon", {
    method: "POST",
    formData,
  });
}

// Sensitive marking
export async function markNoteSensitive(noteId: string): Promise<void> {
  await apiRequest(`/api/v1/admin/notes/${noteId}/sensitive`, { method: "POST" });
}

// Custom Emoji
export interface AdminEmoji {
  id: string;
  shortcode: string;
  url: string;
  static_url: string | null;
  visible_in_picker: boolean;
  category: string | null;
  aliases: string[] | null;
  license: string | null;
  is_sensitive: boolean;
  local_only: boolean;
  author: string | null;
  description: string | null;
  copy_permission: string | null;
  usage_info: string | null;
  is_based_on: string | null;
  import_from: string | null;
  created_at: string;
}

export async function getAdminEmojis(): Promise<AdminEmoji[]> {
  return apiRequest<AdminEmoji[]>("/api/v1/admin/emoji/list");
}

export async function addEmoji(formData: FormData): Promise<AdminEmoji> {
  return apiRequest<AdminEmoji>("/api/v1/admin/emoji/add", {
    method: "POST",
    formData,
  });
}

export async function deleteEmoji(emojiId: string): Promise<void> {
  await apiRequest(`/api/v1/admin/emoji/${emojiId}`, { method: "DELETE" });
}

export async function importEmojis(file: File): Promise<{ imported: number; skipped: number; errors: string[] }> {
  const formData = new FormData();
  formData.append("file", file);
  return apiRequest("/api/v1/admin/emoji/import", {
    method: "POST",
    formData,
  });
}

export function getEmojiExportUrl(): string {
  return "/api/v1/admin/emoji/export";
}

// Remote Emoji
export interface RemoteEmoji {
  id: string;
  shortcode: string;
  domain: string | null;
  url: string;
  static_url: string | null;
  category: string | null;
  aliases: string[] | null;
  license: string | null;
  is_sensitive: boolean;
  author: string | null;
  description: string | null;
  copy_permission: string | null;
  created_at: string;
}

export async function getRemoteEmojis(domain?: string, search?: string): Promise<RemoteEmoji[]> {
  const params = new URLSearchParams();
  if (domain) params.set("domain", domain);
  if (search) params.set("search", search);
  params.set("limit", "200");
  return apiRequest<RemoteEmoji[]>(`/api/v1/admin/emoji/remote?${params}`);
}

export async function getRemoteEmojiDomains(): Promise<string[]> {
  return apiRequest<string[]>("/api/v1/admin/emoji/remote/domains");
}

export async function importRemoteEmoji(emojiId: string): Promise<AdminEmoji> {
  return apiRequest<AdminEmoji>(`/api/v1/admin/emoji/import-remote/${emojiId}`, { method: "POST" });
}

export async function importRemoteEmojiByShortcode(shortcode: string, domain: string): Promise<AdminEmoji> {
  return apiRequest<AdminEmoji>("/api/v1/admin/emoji/import-by-shortcode", {
    method: "POST",
    body: { shortcode, domain },
  });
}

// Server Files
export interface ServerFile {
  id: string;
  filename: string;
  mime_type: string;
  size_bytes: number;
  url: string;
  created_at: string;
}

export async function getServerFiles(): Promise<ServerFile[]> {
  return apiRequest<ServerFile[]>("/api/v1/admin/server-files");
}

export async function uploadServerFile(file: File): Promise<ServerFile> {
  const formData = new FormData();
  formData.append("file", file);
  return apiRequest<ServerFile>("/api/v1/admin/server-files", {
    method: "POST",
    formData,
  });
}

export async function deleteServerFile(fileId: string): Promise<void> {
  await apiRequest(`/api/v1/admin/server-files/${fileId}`, { method: "DELETE" });
}
