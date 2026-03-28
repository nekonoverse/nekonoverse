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
  terms_of_service: string | null;
  privacy_policy: string | null;
  registration_open: boolean;
  registration_mode: string;
  invite_create_role: string;
  server_icon_url: string | null;
  server_theme_color: string | null;
  push_enabled: boolean;
  vapid_public_key: string | null;
  timeline_default_limit: number;
  timeline_max_limit: number;
  katex_enabled: boolean;
}

export interface AdminUser {
  id: string;
  username: string;
  email: string;
  display_name: string | null;
  role: string;
  is_active: boolean;
  is_system: boolean;
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

// Moderator note deletion
export async function adminDeleteNote(noteId: string): Promise<void> {
  await apiRequest(`/api/v1/admin/notes/${noteId}`, { method: "DELETE" });
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

export interface ImportByShortcodeBody {
  shortcode: string;
  domain: string;
  shortcode_override?: string;
  category?: string;
  author?: string;
  license?: string;
  description?: string;
  is_sensitive?: boolean;
  aliases?: string[];
}

export async function importRemoteEmojiByShortcode(body: ImportByShortcodeBody): Promise<AdminEmoji> {
  return apiRequest<AdminEmoji>("/api/v1/admin/emoji/import-by-shortcode", {
    method: "POST",
    body,
  });
}

export interface AdminEmojiUpdate {
  shortcode?: string;
  category?: string;
  visible_in_picker?: boolean;
  aliases?: string[];
  license?: string;
  is_sensitive?: boolean;
  local_only?: boolean;
  author?: string;
  description?: string;
  copy_permission?: string;
  usage_info?: string;
  is_based_on?: string;
}

export async function updateEmoji(emojiId: string, body: AdminEmojiUpdate): Promise<AdminEmoji> {
  return apiRequest<AdminEmoji>(`/api/v1/admin/emoji/${emojiId}`, {
    method: "PATCH",
    body,
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

// Invitation Codes
export interface InviteCode {
  code: string;
  created_by: string;
  used_by: string | null;
  used_at: string | null;
  max_uses: number | null;
  use_count: number;
  expires_at: string | null;
  created_at: string;
}

export interface InviteCodeCreateParams {
  max_uses?: number | null;
  expires_in_days?: number | null;
}

export async function getInviteCodes(): Promise<InviteCode[]> {
  return apiRequest<InviteCode[]>("/api/v1/invites");
}

export async function createInviteCode(
  params?: InviteCodeCreateParams,
): Promise<InviteCode> {
  return apiRequest<InviteCode>("/api/v1/invites", {
    method: "POST",
    body: params ?? {},
  });
}

export async function revokeInviteCode(code: string): Promise<void> {
  await apiRequest(`/api/v1/invites/${code}`, { method: "DELETE" });
}

// Pending Registrations
export interface PendingRegistration {
  id: string;
  username: string;
  email: string;
  reason: string | null;
  created_at: string;
}

export async function getPendingRegistrations(): Promise<PendingRegistration[]> {
  return apiRequest<PendingRegistration[]>("/api/v1/admin/registrations");
}

export async function approveRegistration(userId: string): Promise<void> {
  await apiRequest(`/api/v1/admin/registrations/${userId}/approve`, { method: "POST" });
}

export async function rejectRegistration(userId: string): Promise<void> {
  await apiRequest(`/api/v1/admin/registrations/${userId}/reject`, { method: "POST" });
}

// Federation
export interface DeliveryStats {
  success: number;
  failure: number;
  pending: number;
  dead: number;
}

export interface FederatedServer {
  domain: string;
  user_count: number;
  note_count: number;
  last_activity_at: string | null;
  first_seen_at: string | null;
  status: string;
  block_severity: string | null;
  delivery_stats: DeliveryStats;
}

export interface FederatedServerList {
  servers: FederatedServer[];
  total: number;
}

export interface ActorSummary {
  username: string;
  display_name: string | null;
  ap_id: string;
  last_fetched_at: string | null;
}

export interface FederatedServerDetail extends FederatedServer {
  block_reason: string | null;
  recent_actors: ActorSummary[];
}

export async function getFederatedServers(params: {
  limit?: number;
  offset?: number;
  sort?: string;
  order?: string;
  search?: string;
  status?: string;
} = {}): Promise<FederatedServerList> {
  const qs = new URLSearchParams();
  if (params.limit) qs.set("limit", String(params.limit));
  if (params.offset) qs.set("offset", String(params.offset));
  if (params.sort) qs.set("sort", params.sort);
  if (params.order) qs.set("order", params.order);
  if (params.search) qs.set("search", params.search);
  if (params.status) qs.set("status", params.status);
  return apiRequest<FederatedServerList>(`/api/v1/admin/federation?${qs}`);
}

export async function getFederatedServerDetail(domain: string): Promise<FederatedServerDetail> {
  return apiRequest<FederatedServerDetail>(
    `/api/v1/admin/federation/${encodeURIComponent(domain)}`
  );
}

// Queue Management
export interface QueueStats {
  pending: number;
  processing: number;
  delivered: number;
  dead: number;
  total: number;
  recent_delivered: number;
  recent_dead: number;
}

export interface QueueJob {
  id: string;
  target_inbox_url: string;
  status: string;
  attempts: number;
  max_attempts: number;
  error_message: string | null;
  created_at: string;
  last_attempted_at: string | null;
  next_retry_at: string | null;
}

export interface QueueJobList {
  jobs: QueueJob[];
  total: number;
}

export async function getQueueStats(): Promise<QueueStats> {
  return apiRequest<QueueStats>("/api/v1/admin/queue/stats");
}

export async function getQueueJobs(params: {
  status?: string;
  domain?: string;
  limit?: number;
  offset?: number;
} = {}): Promise<QueueJobList> {
  const qs = new URLSearchParams();
  if (params.status) qs.set("status", params.status);
  if (params.domain) qs.set("domain", params.domain);
  if (params.limit) qs.set("limit", String(params.limit));
  if (params.offset) qs.set("offset", String(params.offset));
  return apiRequest<QueueJobList>(`/api/v1/admin/queue/jobs?${qs}`);
}

export async function retryQueueJob(jobId: string): Promise<void> {
  await apiRequest(`/api/v1/admin/queue/retry/${jobId}`, { method: "POST" });
}

export async function retryAllDeadJobs(domain?: string): Promise<{ retried: number }> {
  const qs = domain ? `?domain=${encodeURIComponent(domain)}` : "";
  return apiRequest(`/api/v1/admin/queue/retry-all${qs}`, { method: "POST" });
}

export async function purgeDeliveredJobs(
  olderThanHours: number = 24
): Promise<{ purged: number }> {
  return apiRequest(`/api/v1/admin/queue/purge?older_than_hours=${olderThanHours}`, {
    method: "DELETE",
  });
}

// System Stats
export interface SystemStats {
  db_pool_size: number;
  db_pool_checked_in: number;
  db_pool_checked_out: number;
  db_pool_overflow: number;
  valkey_connected_clients: number;
  valkey_used_memory_human: string;
  valkey_total_keys: number;
  load_avg_1m: number;
  load_avg_5m: number;
  load_avg_15m: number;
  memory_total_mb: number;
  memory_available_mb: number;
  memory_percent: number;
  uptime_seconds: number;
  worker_alive: boolean;
  worker_last_heartbeat: string | null;
}

export async function getSystemStats(): Promise<SystemStats> {
  return apiRequest<SystemStats>("/api/v1/admin/system/stats");
}

// Push / VAPID Key Management
export async function generateVapidKey(): Promise<{ vapid_public_key: string }> {
  return apiRequest<{ vapid_public_key: string }>("/api/v1/admin/push/generate-vapid-key", {
    method: "POST",
  });
}

// Moderator Permissions
export async function getModeratorPermissions(): Promise<Record<string, boolean>> {
  return apiRequest<Record<string, boolean>>("/api/v1/admin/permissions");
}

export async function updateModeratorPermissions(
  permissions: Record<string, boolean>,
): Promise<Record<string, boolean>> {
  return apiRequest<Record<string, boolean>>("/api/v1/admin/permissions", {
    method: "PATCH",
    body: permissions,
  });
}

// Roles
export interface AdminRole {
  name: string;
  display_name: string;
  permissions: Record<string, boolean>;
  is_admin: boolean;
  quota_bytes: number;
  priority: number;
  is_system: boolean;
  created_at: string;
}

export async function getRoles(): Promise<AdminRole[]> {
  return apiRequest<AdminRole[]>("/api/v1/admin/roles");
}

export async function getRole(name: string): Promise<AdminRole> {
  return apiRequest<AdminRole>(`/api/v1/admin/roles/${name}`);
}

export async function createRole(params: {
  name: string;
  display_name: string;
  copy_from?: string;
}): Promise<AdminRole> {
  return apiRequest<AdminRole>("/api/v1/admin/roles", {
    method: "POST",
    body: params,
  });
}

export async function updateRole(
  name: string,
  params: {
    display_name?: string;
    permissions?: Record<string, boolean>;
    quota_bytes?: number;
    priority?: number;
  },
): Promise<AdminRole> {
  return apiRequest<AdminRole>(`/api/v1/admin/roles/${name}`, {
    method: "PATCH",
    body: params,
  });
}

export async function deleteRole(name: string): Promise<void> {
  await apiRequest(`/api/v1/admin/roles/${name}`, { method: "DELETE" });
}

// Storage
export interface StorageInfo {
  usage_bytes: number;
  quota_bytes: number;
  usage_percent: number;
}

export async function getAccountStorage(): Promise<StorageInfo> {
  return apiRequest<StorageInfo>("/api/v1/accounts/storage");
}

// Announcements
export interface Announcement {
  id: string;
  title: string;
  content: string;
  content_html: string;
  published: boolean;
  all_day: boolean;
  starts_at: string | null;
  ends_at: string | null;
  created_at: string;
  updated_at: string;
}

export async function getAnnouncements(): Promise<Announcement[]> {
  return apiRequest<Announcement[]>("/api/v1/admin/announcements");
}

export async function createAnnouncement(data: {
  title: string;
  content: string;
  published?: boolean;
  all_day?: boolean;
  starts_at?: string | null;
  ends_at?: string | null;
}): Promise<Announcement> {
  return apiRequest<Announcement>("/api/v1/admin/announcements", {
    method: "POST",
    body: data,
  });
}

export async function updateAnnouncement(
  id: string,
  data: Partial<Pick<Announcement, "title" | "content" | "published" | "all_day" | "starts_at" | "ends_at">>,
): Promise<Announcement> {
  return apiRequest<Announcement>(`/api/v1/admin/announcements/${id}`, {
    method: "PATCH",
    body: data,
  });
}

export async function deleteAnnouncement(id: string): Promise<void> {
  await apiRequest(`/api/v1/admin/announcements/${id}`, { method: "DELETE" });
}
