import { apiRequest } from "./client";

export interface LegalPage {
  content_html: string | null;
  content_raw: string | null;
}

export async function getTerms(): Promise<LegalPage> {
  return apiRequest<LegalPage>("/api/v1/instance/terms");
}

export async function getPrivacyPolicy(): Promise<LegalPage> {
  return apiRequest<LegalPage>("/api/v1/instance/privacy");
}
