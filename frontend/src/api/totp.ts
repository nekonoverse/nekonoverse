import { apiRequest } from "./client";

export interface TotpSetupResponse {
  secret: string;
  provisioning_uri: string;
}

export interface TotpEnableResponse {
  recovery_codes: string[];
}

export interface TotpStatusResponse {
  totp_enabled: boolean;
}

export async function setupTotp(password: string): Promise<TotpSetupResponse> {
  return apiRequest<TotpSetupResponse>("/api/v1/auth/totp/setup", {
    method: "POST",
    body: { password },
  });
}

export async function enableTotp(code: string): Promise<TotpEnableResponse> {
  return apiRequest<TotpEnableResponse>("/api/v1/auth/totp/enable", {
    method: "POST",
    body: { code },
  });
}

export async function disableTotp(password: string): Promise<void> {
  await apiRequest("/api/v1/auth/totp/disable", {
    method: "POST",
    body: { password },
  });
}

export async function verifyTotp(
  code: string,
  totpToken: string
): Promise<{ ok: boolean }> {
  return apiRequest<{ ok: boolean }>("/api/v1/auth/totp/verify", {
    method: "POST",
    body: { code, totp_token: totpToken },
  });
}

export async function getTotpStatus(): Promise<TotpStatusResponse> {
  return apiRequest<TotpStatusResponse>("/api/v1/auth/totp/status");
}
