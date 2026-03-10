import { apiRequest } from "./client";

export interface DriveFile {
  id: string;
  filename: string;
  mime_type: string;
  size_bytes: number;
  url: string;
  width: number | null;
  height: number | null;
  description: string | null;
  blurhash: string | null;
  focal_x: number | null;
  focal_y: number | null;
  server_file: boolean;
  created_at: string;
}

export async function getDriveFiles(limit = 20, offset = 0): Promise<DriveFile[]> {
  return apiRequest<DriveFile[]>(`/api/v1/drive/files?limit=${limit}&offset=${offset}`);
}

export async function deleteDriveFile(id: string): Promise<void> {
  await apiRequest(`/api/v1/media/${id}`, { method: "DELETE" });
}
