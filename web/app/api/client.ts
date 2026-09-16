export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly payload?: unknown,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

const apiRoot = import.meta.env.VITE_API_ROOT ?? "";
const authTokenStorageKey = "auth_token";

export const authRequiredEvent = "agentrig:auth-required";

export function resolveApiUrl(path: string): string {
  if (/^https?:\/\//.test(path)) return path;
  return `${apiRoot}${path}`;
}

export function getAuthHeaders(): Record<string, string> {
  if (typeof window === "undefined") return {};
  const token = window.localStorage.getItem(authTokenStorageKey);
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export function hasStoredAuthToken(): boolean {
  return (
    typeof window !== "undefined" &&
    Boolean(window.localStorage.getItem(authTokenStorageKey))
  );
}

export function storeAuthToken(token: string): void {
  window.localStorage.setItem(authTokenStorageKey, token);
}

export function clearAuthToken(): void {
  window.localStorage.removeItem(authTokenStorageKey);
}

export async function apiRequest<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const response = await fetch(resolveApiUrl(path), {
    ...init,
    credentials: init.credentials ?? "same-origin",
    headers: {
      Accept: "application/json",
      ...(init.body ? { "Content-Type": "application/json" } : {}),
      ...getAuthHeaders(),
      ...init.headers,
    },
  });
  if (response.status === 401 && typeof window !== "undefined") {
    window.dispatchEvent(new Event(authRequiredEvent));
  }
  const text = await response.text();
  let payload: unknown;
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      payload = text;
    }
  }
  if (!response.ok) {
    throw new ApiError(
      typeof payload === "object" && payload && "message" in payload
        ? String((payload as { message: unknown }).message)
        : typeof payload === "object" && payload && "detail" in payload
          ? String((payload as { detail: unknown }).detail)
          : `请求失败 (${response.status})`,
      response.status,
      payload,
    );
  }
  return payload as T;
}

export function jsonBody(value: unknown): Pick<RequestInit, "body"> {
  return { body: JSON.stringify(value) };
}

export interface ApiFile {
  blob: Blob;
  filename: string | null;
}

export async function apiDownload(path: string): Promise<ApiFile> {
  const response = await fetch(resolveApiUrl(path), {
    credentials: "same-origin",
    headers: getAuthHeaders(),
  });
  if (response.status === 401 && typeof window !== "undefined") {
    window.dispatchEvent(new Event(authRequiredEvent));
  }
  if (!response.ok) {
    const text = await response.text();
    let payload: unknown = text;
    if (text) {
      try {
        payload = JSON.parse(text);
      } catch {
        // Keep the response text as the structured error fallback.
      }
    }
    throw new ApiError(
      typeof payload === "object" && payload && "message" in payload
        ? String((payload as { message: unknown }).message)
        : `请求失败 (${response.status})`,
      response.status,
      payload,
    );
  }
  const disposition = response.headers.get("Content-Disposition") ?? "";
  const filename = disposition.match(/filename="([^"]+)"/)?.[1] ?? null;
  return { blob: await response.blob(), filename };
}
