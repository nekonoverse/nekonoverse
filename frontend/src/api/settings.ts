import { apiRequest } from "./client";
import type { CurrentUser } from "../stores/auth";

export async function updateDisplayName(displayName: string | null): Promise<CurrentUser> {
  return apiRequest<CurrentUser>("/api/v1/accounts/update_credentials", {
    method: "PATCH",
    body: { display_name: displayName },
  });
}

export async function changePassword(currentPassword: string, newPassword: string): Promise<void> {
  await apiRequest("/api/v1/auth/change_password", {
    method: "POST",
    body: { current_password: currentPassword, new_password: newPassword },
  });
}
