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

// Server-side preferences

export type SourceMediaType = "auto" | "mfm" | "plain";

export interface ServerPreferences {
  "posting:default:visibility": string;
  "posting:default:sensitive": boolean;
  "posting:default:language": string | null;
  "reading:expand:media": string;
  "reading:expand:spoilers": boolean;
  "posting:source_media_type": SourceMediaType;
  "theme_customization": import("../stores/theme").ThemeCustomization | null;
}

export async function getPreferences(): Promise<ServerPreferences> {
  return apiRequest<ServerPreferences>("/api/v1/preferences", { method: "GET" });
}

export async function updateSourceMediaType(value: SourceMediaType): Promise<ServerPreferences> {
  return apiRequest<ServerPreferences>("/api/v1/preferences", {
    method: "PATCH",
    body: { "posting:source_media_type": value },
  });
}

export async function updateThemeCustomization(
  customization: import("../stores/theme").ThemeCustomization | null,
): Promise<ServerPreferences> {
  return apiRequest<ServerPreferences>("/api/v1/preferences", {
    method: "PATCH",
    body: { theme_customization: customization || false },
  });
}

export async function changePassword(currentPassword: string, newPassword: string): Promise<void> {
  await apiRequest("/api/v1/auth/change_password", {
    method: "POST",
    body: { current_password: currentPassword, new_password: newPassword },
  });
}

// Data export

export interface DataExportStatus {
  id: string;
  status: "pending" | "processing" | "completed" | "failed" | "expired";
  size_bytes?: number | null;
  error?: string | null;
  expires_at?: string | null;
  created_at: string;
}

export async function startExport(): Promise<{ id: string; status: string }> {
  return apiRequest("/api/v1/export", { method: "POST" });
}

export async function getExportStatus(): Promise<DataExportStatus | null> {
  return apiRequest("/api/v1/export", { method: "GET" });
}
