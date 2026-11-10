/**
 * API client for the browser. Same-origin `/api/...` (Next rewrites to the API server), httpOnly cookies,
 * automatic refresh on 401, and the active workspace sent as `X-Workspace`.
 *
 *   const posts = await api.get<Post[]>("/posts", { state: "draft" });
 *   await api.post("/posts", { content: "Hi" });
 *   await api.upload("/media", file);
 *
 * With React Query: useQuery({ queryKey: ["posts"], queryFn: () => api.get("/posts") }).
 */

export class ApiError extends Error {
  status: number;
  code: string;
  data: unknown;

  constructor(status: number, message: string, code = "error", data: unknown = null) {
    super(message);
    this.status = status;
    this.code = code;
    this.data = data;
  }
}

let workspaceId: number | null = null;
let locale = "ar";
let onUnauthenticated: (() => void) | null = null;

export function setApiWorkspace(id: number | null) {
  workspaceId = id;
}
export function setApiLocale(value: string) {
  locale = value;
}
export function setOnUnauthenticated(handler: () => void) {
  onUnauthenticated = handler;
}

type Query = Record<string, string | number | boolean | null | undefined | (string | number)[]>;

function buildUrl(path: string, query?: Query) {
  const url = new URL(`/api${path.startsWith("/") ? path : `/${path}`}`, window.location.origin);
  for (const [key, value] of Object.entries(query || {})) {
    if (value === undefined || value === null || value === "") continue;
    if (Array.isArray(value)) value.forEach((v) => url.searchParams.append(key, String(v)));
    else url.searchParams.set(key, String(value));
  }
  return url.toString();
}

let refreshing: Promise<boolean> | null = null;

async function refresh(): Promise<boolean> {
  refreshing ||= fetch("/api/auth/refresh", { method: "POST", credentials: "include" })
    .then((r) => r.ok)
    .catch(() => false)
    .finally(() => setTimeout(() => (refreshing = null), 0));
  return refreshing;
}

async function request<T>(method: string, path: string, body?: unknown, query?: Query, retry = true): Promise<T> {
  const headers: Record<string, string> = { "Accept-Language": locale, "X-Requested-With": "fetch" };
  if (workspaceId) headers["X-Workspace"] = String(workspaceId);
  let payload: BodyInit | undefined;
  if (body instanceof FormData) payload = body;
  else if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }
  const response = await fetch(buildUrl(path, query), { method, headers, body: payload, credentials: "include" });
  if (response.status === 401 && retry && !path.startsWith("/auth/")) {
    if (await refresh()) return request<T>(method, path, body, query, false);
    onUnauthenticated?.();
  }
  if (!response.ok) {
    let data: { detail?: unknown; code?: string } = {};
    try {
      data = await response.json();
    } catch {
      /* not JSON */
    }
    const detail = Array.isArray(data.detail)
      ? data.detail.map((d: { msg?: string }) => d.msg).join(" · ")
      : String(data.detail || response.statusText);
    // plan limits: the billing overlay (components/billing) opens an upgrade dialog
    if (data.code === "limit_reached") window.dispatchEvent(new CustomEvent("sai:limit-reached", { detail: { ...data, detail } }));
    throw new ApiError(response.status, detail, data.code || "error", data);
  }
  if (response.status === 204) return undefined as T;
  const type = response.headers.get("content-type") || "";
  return (type.includes("application/json") ? response.json() : response.blob()) as Promise<T>;
}

export const api = {
  get: <T>(path: string, query?: Query) => request<T>("GET", path, undefined, query),
  post: <T>(path: string, body?: unknown, query?: Query) => request<T>("POST", path, body ?? {}, query),
  put: <T>(path: string, body?: unknown) => request<T>("PUT", path, body ?? {}),
  patch: <T>(path: string, body?: unknown) => request<T>("PATCH", path, body ?? {}),
  delete: <T>(path: string) => request<T>("DELETE", path),
  upload: <T>(path: string, file: File | Blob, field = "file", extra?: Record<string, string>) => {
    const form = new FormData();
    form.append(field, file);
    for (const [k, v] of Object.entries(extra || {})) form.append(k, v);
    return request<T>("POST", path, form);
  },
};

/** URL of a workspace file for <img>/<video> (served by the API with the session cookie). */
export const mediaUrl = (id: number | null | undefined) => (id ? `/api/media/${id}/file` : "");
