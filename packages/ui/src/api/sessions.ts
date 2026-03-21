import { apiRequest } from "./client";

export interface SessionInfo {
  session_id: string;
  ip: string;
  user_agent: string;
  created_at: string;
  is_current: boolean;
}

export interface LoginHistoryEntry {
  id: string;
  ip_address: string;
  user_agent: string | null;
  method: string;
  success: boolean;
  created_at: string;
}

export async function getSessions(): Promise<SessionInfo[]> {
  return apiRequest<SessionInfo[]>("/api/v1/auth/sessions");
}

export async function deleteSession(sessionId: string): Promise<void> {
  await apiRequest(`/api/v1/auth/sessions/${sessionId}`, {
    method: "DELETE",
  });
}

export async function getLoginHistory(
  limit: number = 20,
  offset: number = 0,
): Promise<LoginHistoryEntry[]> {
  return apiRequest<LoginHistoryEntry[]>(
    `/api/v1/auth/login_history?limit=${limit}&offset=${offset}`,
  );
}
