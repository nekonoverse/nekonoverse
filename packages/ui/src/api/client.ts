interface RequestOptions {
  method?: string;
  body?: unknown;
  headers?: Record<string, string>;
  formData?: FormData;
}

export async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = "GET", body, headers = {}, formData } = options;

  const config: RequestInit = {
    method,
    credentials: "include",
    headers: formData ? { ...headers } : {
      "Content-Type": "application/json",
      ...headers,
    },
  };

  if (formData) {
    config.body = formData;
  } else if (body) {
    config.body = JSON.stringify(body);
  }

  const response = await fetch(path, config);

  if (!response.ok) {
    const error = await response.json().catch(() => ({ error: "Unknown error" }));
    throw new Error(error.detail || error.error || `HTTP ${response.status}`);
  }

  return response.json();
}
