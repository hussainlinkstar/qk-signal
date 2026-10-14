import { parseErrorDetail } from "@/services/http";

export type LogoUploadScope = "workspace" | "user";

export type LogoUploadResponse = {
  url: string;
  object_uri: string;
  filename: string;
  content_type: string;
  size_bytes: number;
  storage: "gcs" | "local";
};

export async function uploadLogoAsset(
  file: File,
  scope: LogoUploadScope,
  headers: HeadersInit = {}
): Promise<LogoUploadResponse> {
  const formData = new FormData();
  formData.append("file", file);

  const response = await fetch(`/api/uploads/logo?scope=${scope}`, {
    method: "POST",
    headers,
    body: formData,
  });

  if (!response.ok) {
    throw new Error(await parseErrorDetail(response, "Unable to upload logo."));
  }

  return (await response.json()) as LogoUploadResponse;
}
