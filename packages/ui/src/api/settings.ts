import { apiRequest } from "./client";
import type { CurrentUser } from "./types/auth";

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

export interface UpdateProfileParams {
  display_name?: string;
  summary?: string;
  fields_attributes?: string;
  birthday?: string;
  is_cat?: boolean;
  is_bot?: boolean;
  locked?: boolean;
}

export async function updateProfile(params: UpdateProfileParams): Promise<CurrentUser> {
  const formData = new FormData();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined) {
      formData.append(key, String(value));
    }
  }
  return apiRequest<CurrentUser>("/api/v1/accounts/update_credentials", {
    method: "PATCH",
    formData,
  });
}

export async function deleteAvatar(): Promise<CurrentUser> {
  const formData = new FormData();
  formData.append("avatar_delete", "1");
  return apiRequest<CurrentUser>("/api/v1/accounts/update_credentials", {
    method: "PATCH",
    formData,
  });
}

export async function deleteHeader(): Promise<CurrentUser> {
  const formData = new FormData();
  formData.append("header_delete", "1");
  return apiRequest<CurrentUser>("/api/v1/accounts/update_credentials", {
    method: "PATCH",
    formData,
  });
}

export async function updateAvatarFocus(x: number, y: number): Promise<CurrentUser> {
  const formData = new FormData();
  formData.append("avatar_focus", `${x},${y}`);
  return apiRequest<CurrentUser>("/api/v1/accounts/update_credentials", {
    method: "PATCH",
    formData,
  });
}

export async function updateHeaderFocus(x: number, y: number): Promise<CurrentUser> {
  const formData = new FormData();
  formData.append("header_focus", `${x},${y}`);
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
