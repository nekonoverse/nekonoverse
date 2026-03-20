import { apiRequest } from "./client";

export interface AuthorizedApp {
  id: string;
  name: string;
  website: string | null;
  scopes: string[];
  created_at: string;
}

export async function getAuthorizedApps(): Promise<AuthorizedApp[]> {
  return apiRequest<AuthorizedApp[]>("/api/v1/authorized_apps");
}

export async function revokeAuthorizedApp(appId: string): Promise<void> {
  await apiRequest(`/api/v1/authorized_apps/${appId}`, { method: "DELETE" });
}
