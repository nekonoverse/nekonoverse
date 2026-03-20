export interface ProfileField {
  name: string;
  value: string;
}

export interface FocalPoint {
  x: number;
  y: number;
}

export interface RoleObject {
  id: string;
  name: string;
  permissions: string;
  color: string;
  highlighted: boolean;
}

export interface CurrentUser {
  id: string;
  username: string;
  display_name: string | null;
  avatar_url: string | null;
  header_url: string | null;
  avatar_focal: FocalPoint | null;
  header_focal: FocalPoint | null;
  summary: string | null;
  fields: ProfileField[];
  birthday: string | null;
  is_cat: boolean;
  is_bot: boolean;
  locked: boolean;
  role: string | RoleObject;
  nekonoverse_permissions?: string[];
}

/** Extract role name string from either string or Mastodon-compatible object. */
export function getRoleName(role: string | RoleObject | undefined): string {
  if (!role) return "";
  if (typeof role === "string") return role;
  return role.name.toLowerCase();
}

export interface LoginResponse {
  ok?: boolean;
  requires_totp?: boolean;
  totp_token?: string;
}
