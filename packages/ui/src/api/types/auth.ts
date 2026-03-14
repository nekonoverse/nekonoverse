export interface ProfileField {
  name: string;
  value: string;
}

export interface FocalPoint {
  x: number;
  y: number;
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
  discoverable: boolean;
  role: string;
}

export interface LoginResponse {
  ok?: boolean;
  requires_totp?: boolean;
  totp_token?: string;
}
