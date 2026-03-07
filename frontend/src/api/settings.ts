import { apiRequest } from "./client";
import type { CurrentUser } from "../stores/auth";

export async function updateDisplayName(displayName: string | null): Promise<CurrentUser> {
  const formData = new FormData();
  if (displayName !== null) {
    formData.append("display_name", displayName);
  }
  return apiRequest<CurrentUser>("/api/v1/accounts/update_credentials", {
    method: "PATCH",
    formData,
  });
}

export async function updateAvatar(file: File): Promise<CurrentUser> {
  const formData = new FormData();
  formData.append("avatar", file);
  return apiRequest<CurrentUser>("/api/v1/accounts/update_credentials", {
    method: "PATCH",
    formData,
  });
}

export async function updateHeader(file: File): Promise<CurrentUser> {
  const formData = new FormData();
  formData.append("header", file);
  return apiRequest<CurrentUser>("/api/v1/accounts/update_credentials", {
    method: "PATCH",
    formData,
  });
}

export async function changePassword(currentPassword: string, newPassword: string): Promise<void> {
  await apiRequest("/api/v1/auth/change_password", {
    method: "POST",
    body: { current_password: currentPassword, new_password: newPassword },
  });
}
