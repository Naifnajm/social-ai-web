/**
 * API client: `Authorization: Bearer`, `X-Workspace` and `Accept-Language` headers, automatic token refresh on 401.
 *
 *   const page = await api.get<ConversationPage>('/inbox/conversations', { folder: 'mine' });
 *   await api.post('/posts', { content: 'Hi' });
 *   await api.upload<MediaItem>('/media', { uri, name: 'photo.jpg', type: 'image/jpeg' });
 */
import { Platform } from 'react-native';

import { getServer } from './config';
import { getLocale, t } from './i18n';
import { KEYS, getItem, setItem, removeItem } from './storage';
import type { SessionOut } from './types';

export class ApiError extends Error {
  status: number;
  code: string;
  data: unknown;

  constructor(status: number, message: string, code = 'error', data: unknown = null) {
    super(message);
    this.status = status;
    this.code = code;
    this.data = data;
  }
}

let accessToken: string | null = null;
let refreshToken: string | null = null;
let workspaceId: number | null = null;
let onUnauthenticated: (() => void) | null = null;

export async function loadTokens(): Promise<boolean> {
  [accessToken, refreshToken] = await Promise.all([getItem(KEYS.access), getItem(KEYS.refresh)]);
  return !!(accessToken || refreshToken);
}

export async function saveTokens(session: Pick<SessionOut, 'access_token' | 'refresh_token'>): Promise<void> {
  accessToken = session.access_token;
  refreshToken = session.refresh_token;
  await Promise.all([setItem(KEYS.access, accessToken), setItem(KEYS.refresh, refreshToken)]);
}

export async function clearTokens(): Promise<void> {
  accessToken = null;
  refreshToken = null;
  await Promise.all([removeItem(KEYS.access), removeItem(KEYS.refresh)]);
}

export function setApiWorkspace(id: number | null) {
  workspaceId = id;
}
export function getApiWorkspace() {
  return workspaceId;
}
export function setOnUnauthenticated(handler: (() => void) | null) {
  onUnauthenticated = handler;
}

type Query = Record<string, string | number | boolean | null | undefined | (string | number)[]>;

export function apiUrl(path: string, query?: Query): string {
  const parts: string[] = [];
  for (const [key, value] of Object.entries(query || {})) {
    if (value === undefined || value === null || value === '') continue;
    const values = Array.isArray(value) ? value : [value];
    values.forEach((v) => parts.push(`${encodeURIComponent(key)}=${encodeURIComponent(String(v))}`));
  }
  const clean = path.startsWith('/api/') ? path : `/api${path.startsWith('/') ? path : `/${path}`}`;
  return `${getServer()}${clean}${parts.length ? `?${parts.join('&')}` : ''}`;
}

/** Headers for authenticated media (images served by the API). */
export function authHeaders(): Record<string, string> {
  const headers: Record<string, string> = {};
  if (accessToken) headers.Authorization = `Bearer ${accessToken}`;
  if (workspaceId) headers['X-Workspace'] = String(workspaceId);
  return headers;
}

let refreshing: Promise<boolean> | null = null;

export function refreshSession(): Promise<boolean> {
  if (!refreshToken) return Promise.resolve(false);
  refreshing ||= fetch(apiUrl('/auth/refresh'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'Accept-Language': getLocale() },
    body: JSON.stringify({ refresh_token: refreshToken }),
    credentials: 'omit',
  })
    .then(async (r) => {
      if (!r.ok) return false;
      await saveTokens((await r.json()) as SessionOut);
      return true;
    })
    .catch(() => false)
    .finally(() => setTimeout(() => (refreshing = null), 0));
  return refreshing;
}

async function request<T>(method: string, path: string, body?: unknown, query?: Query, retry = true): Promise<T> {
  const headers: Record<string, string> = { 'Accept-Language': getLocale(), Accept: 'application/json', ...authHeaders() };
  let payload: BodyInit | undefined;
  if (body instanceof FormData) payload = body;
  else if (body !== undefined) {
    headers['Content-Type'] = 'application/json';
    payload = JSON.stringify(body);
  }
  let response: Response;
  try {
    response = await fetch(apiUrl(path, query), { method, headers, body: payload, credentials: 'omit' });
  } catch {
    throw new ApiError(0, t('errors.network'), 'network');
  }
  const isAuthCall = /^\/auth\/(login|signup|refresh|password)/.test(path);
  if (response.status === 401 && retry && !isAuthCall) {
    if (await refreshSession()) return request<T>(method, path, body, query, false);
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
      ? data.detail.map((d: { msg?: string }) => d.msg).join(' · ')
      : String(data.detail || (response.status >= 500 ? t('errors.server') : response.statusText || t('errors.generic')));
    throw new ApiError(response.status, detail, data.code || 'error', data);
  }
  if (response.status === 204) return undefined as T;
  const type = response.headers.get('content-type') || '';
  return (type.includes('application/json') ? response.json() : response.text()) as Promise<T>;
}

export type UploadFile = { uri: string; name: string; type: string };

export const api = {
  get: <T>(path: string, query?: Query) => request<T>('GET', path, undefined, query),
  post: <T>(path: string, body?: unknown, query?: Query) => request<T>('POST', path, body ?? {}, query),
  put: <T>(path: string, body?: unknown) => request<T>('PUT', path, body ?? {}),
  patch: <T>(path: string, body?: unknown) => request<T>('PATCH', path, body ?? {}),
  delete: <T>(path: string) => request<T>('DELETE', path),
  async upload<T>(path: string, file: UploadFile, field = 'file'): Promise<T> {
    const form = new FormData();
    if (Platform.OS === 'web') {
      const blob = await (await fetch(file.uri)).blob();
      form.append(field, blob, file.name);
    } else {
      // React Native's FormData takes a { uri, name, type } descriptor for files
      form.append(field, file as unknown as Blob);
    }
    return request<T>('POST', path, form);
  },
};

export function errorText(err: unknown): string {
  if (err instanceof ApiError) return err.message;
  if (err instanceof Error) return err.message;
  return t('errors.generic');
}
