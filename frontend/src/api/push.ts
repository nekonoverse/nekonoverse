import { apiRequest } from "./client";

export interface PushSubscriptionResponse {
  id: string;
  endpoint: string;
  alerts: Record<string, boolean>;
  policy: string;
  server_key: string;
}

export async function createPushSubscription(
  endpoint: string,
  p256dh: string,
  auth: string,
  alerts?: Record<string, boolean>,
  policy?: string,
): Promise<PushSubscriptionResponse> {
  return apiRequest<PushSubscriptionResponse>("/api/v1/push/subscription", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      subscription: { endpoint, keys: { p256dh, auth } },
      data: { alerts, policy },
    }),
  });
}

export async function getPushSubscription(): Promise<PushSubscriptionResponse> {
  return apiRequest<PushSubscriptionResponse>("/api/v1/push/subscription");
}

export async function updatePushSubscription(
  alerts?: Record<string, boolean>,
  policy?: string,
): Promise<PushSubscriptionResponse> {
  return apiRequest<PushSubscriptionResponse>("/api/v1/push/subscription", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ data: { alerts, policy } }),
  });
}

export async function deletePushSubscription(): Promise<void> {
  await apiRequest("/api/v1/push/subscription", { method: "DELETE" });
}
