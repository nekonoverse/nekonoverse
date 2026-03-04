import { apiRequest } from "./client";

// ── Base64URL utilities ────────────────────────────────────────────────────

function bufferToBase64url(buffer: ArrayBuffer): string {
  const bytes = new Uint8Array(buffer);
  let str = "";
  for (const byte of bytes) {
    str += String.fromCharCode(byte);
  }
  return btoa(str).replace(/\+/g, "-").replace(/\//g, "_").replace(/=/g, "");
}

function base64urlToBuffer(base64url: string): ArrayBuffer {
  const base64 = base64url.replace(/-/g, "+").replace(/_/g, "/");
  const padded = base64.padEnd(base64.length + ((4 - (base64.length % 4)) % 4), "=");
  const binary = atob(padded);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) {
    bytes[i] = binary.charCodeAt(i);
  }
  return bytes.buffer;
}

// ── Options conversion ─────────────────────────────────────────────────────

function parseCreationOptions(
  options: Record<string, unknown>,
): PublicKeyCredentialCreationOptions {
  const o = options as {
    challenge: string;
    user: { id: string; name: string; displayName: string };
    excludeCredentials?: { id: string; type: string; transports?: AuthenticatorTransport[] }[];
    rp: PublicKeyCredentialRpEntity;
    pubKeyCredParams: PublicKeyCredentialParameters[];
    timeout?: number;
    attestation?: AttestationConveyancePreference;
    authenticatorSelection?: AuthenticatorSelectionCriteria;
  };
  return {
    ...o,
    challenge: base64urlToBuffer(o.challenge),
    user: {
      ...o.user,
      id: base64urlToBuffer(o.user.id),
    },
    excludeCredentials: o.excludeCredentials?.map((c) => ({
      ...c,
      id: base64urlToBuffer(c.id),
    })),
  };
}

function parseRequestOptions(
  options: Record<string, unknown>,
): PublicKeyCredentialRequestOptions {
  const o = options as {
    challenge: string;
    allowCredentials?: { id: string; type: string; transports?: AuthenticatorTransport[] }[];
    rpId?: string;
    timeout?: number;
    userVerification?: UserVerificationRequirement;
  };
  return {
    ...o,
    challenge: base64urlToBuffer(o.challenge),
    allowCredentials: o.allowCredentials?.map((c) => ({
      ...c,
      id: base64urlToBuffer(c.id),
    })),
  };
}

function serializeCredential(
  credential: PublicKeyCredential,
  name?: string,
): Record<string, unknown> {
  const response = credential.response as AuthenticatorAttestationResponse;
  return {
    id: credential.id,
    rawId: bufferToBase64url(credential.rawId),
    type: credential.type,
    response: {
      attestationObject: bufferToBase64url(response.attestationObject),
      clientDataJSON: bufferToBase64url(response.clientDataJSON),
    },
    authenticatorAttachment: credential.authenticatorAttachment ?? null,
    clientExtensionResults: credential.getClientExtensionResults(),
    name: name ?? null,
  };
}

function serializeAuthCredential(
  credential: PublicKeyCredential,
  challengeId: string,
): Record<string, unknown> {
  const response = credential.response as AuthenticatorAssertionResponse;
  return {
    challengeId,
    id: credential.id,
    rawId: bufferToBase64url(credential.rawId),
    type: credential.type,
    response: {
      authenticatorData: bufferToBase64url(response.authenticatorData),
      clientDataJSON: bufferToBase64url(response.clientDataJSON),
      signature: bufferToBase64url(response.signature),
      userHandle: response.userHandle ? bufferToBase64url(response.userHandle) : null,
    },
    authenticatorAttachment: credential.authenticatorAttachment ?? null,
    clientExtensionResults: credential.getClientExtensionResults(),
  };
}

// ── Public API ─────────────────────────────────────────────────────────────

export interface PasskeyCredentialInfo {
  id: string;
  credential_id: string;
  name: string | null;
  aaguid: string | null;
  sign_count: number;
  created_at: string;
  last_used_at: string | null;
}

export async function registerPasskey(name?: string): Promise<PasskeyCredentialInfo> {
  const optionsJSON = await apiRequest<Record<string, unknown>>(
    "/api/v1/passkey/register/options",
    { method: "POST" },
  );

  const creationOptions = parseCreationOptions(optionsJSON);
  const credential = (await navigator.credentials.create({
    publicKey: creationOptions,
  })) as PublicKeyCredential | null;

  if (!credential) {
    throw new Error("Passkey creation was cancelled");
  }

  const serialized = serializeCredential(credential, name);
  return apiRequest<PasskeyCredentialInfo>("/api/v1/passkey/register/verify", {
    method: "POST",
    body: serialized,
  });
}

export async function authenticateWithPasskey(): Promise<void> {
  const optionsJSON = await apiRequest<Record<string, unknown>>(
    "/api/v1/passkey/authenticate/options",
    { method: "POST" },
  );

  const { challengeId, ...rest } = optionsJSON as { challengeId: string } & Record<
    string,
    unknown
  >;

  const requestOptions = parseRequestOptions(rest);
  const credential = (await navigator.credentials.get({
    publicKey: requestOptions,
  })) as PublicKeyCredential | null;

  if (!credential) {
    throw new Error("Passkey authentication was cancelled");
  }

  const serialized = serializeAuthCredential(credential, challengeId);
  await apiRequest("/api/v1/passkey/authenticate/verify", {
    method: "POST",
    body: serialized,
  });
}

export async function listPasskeys(): Promise<PasskeyCredentialInfo[]> {
  return apiRequest<PasskeyCredentialInfo[]>("/api/v1/passkey/credentials");
}

export async function deletePasskey(passkeyId: string): Promise<void> {
  await apiRequest(`/api/v1/passkey/credentials/${passkeyId}`, {
    method: "DELETE",
  });
}
