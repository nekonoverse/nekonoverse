import { apiRequest } from "./client";

export interface DiscordWebhook {
  id: string;
  name: string;
  webhook_url_masked: string;
  notify_mention: boolean;
  notify_direct: boolean;
  notify_quote: boolean;
  notify_reaction: boolean;
  notify_renote: boolean;
  notify_follow: boolean;
  notify_follow_request: boolean;
  enabled: boolean;
  consecutive_failures: number;
  last_error: string | null;
  last_delivered_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface DiscordWebhookInput {
  name: string;
  webhook_url: string;
  notify_mention?: boolean;
  notify_direct?: boolean;
  notify_quote?: boolean;
  notify_reaction?: boolean;
  notify_renote?: boolean;
  notify_follow?: boolean;
  notify_follow_request?: boolean;
  enabled?: boolean;
}

export type DiscordWebhookUpdate = Partial<DiscordWebhookInput>;

export interface DiscordWebhookTestResult {
  success: boolean;
  status_code: number | null;
  error: string | null;
}

export async function listDiscordWebhooks(): Promise<DiscordWebhook[]> {
  return apiRequest<DiscordWebhook[]>("/api/v1/discord-webhooks");
}

export async function createDiscordWebhook(
  input: DiscordWebhookInput,
): Promise<DiscordWebhook> {
  return apiRequest<DiscordWebhook>("/api/v1/discord-webhooks", {
    method: "POST",
    body: input,
  });
}

export async function updateDiscordWebhook(
  id: string,
  input: DiscordWebhookUpdate,
): Promise<DiscordWebhook> {
  return apiRequest<DiscordWebhook>(`/api/v1/discord-webhooks/${id}`, {
    method: "PATCH",
    body: input,
  });
}

export async function deleteDiscordWebhook(id: string): Promise<void> {
  await apiRequest(`/api/v1/discord-webhooks/${id}`, { method: "DELETE" });
}

export async function testDiscordWebhook(
  id: string,
): Promise<DiscordWebhookTestResult> {
  return apiRequest<DiscordWebhookTestResult>(
    `/api/v1/discord-webhooks/${id}/test`,
    { method: "POST" },
  );
}
