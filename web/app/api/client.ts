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

export function resolveApiUrl(path: string): string {
  if (/^https?:\/\//.test(path)) return path;
  return `${apiRoot}${path}`;
}

export function getAuthHeaders(): Record<string, string> {
  if (typeof window === "undefined") return {};
  const token = window.localStorage.getItem("auth_token");
  return token ? { Authorization: `Bearer ${token}` } : {};
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
