/**
 * API server address. Order: the "server" field on the sign-in screen (self-hosted installs, stored on the device)
 * → EXPO_PUBLIC_API_URL → app.json `expo.extra.apiUrl` → https://api.stravica.com.
 */
import Constants from 'expo-constants';

import { KEYS, getItemSync, setItemSync, removeItem } from './storage';

const DEFAULT_API = 'https://api.stravica.com';

export function defaultServer(): string {
  const fromEnv = process.env.EXPO_PUBLIC_API_URL;
  const extra = (Constants.expoConfig?.extra ?? {}) as { apiUrl?: string };
  return normalizeServer(fromEnv || extra.apiUrl || DEFAULT_API);
}

export function normalizeServer(value: string): string {
  let url = value.trim().replace(/\/+$/, '').replace(/\/api$/, '');
  if (url && !/^https?:\/\//i.test(url)) url = `https://${url}`;
  return url;
}

let server = normalizeServer(getItemSync(KEYS.server) || '') || defaultServer();

export function getServer(): string {
  return server;
}

/** Sets a custom server (empty → back to the default). */
export function setServer(value: string): void {
  const url = normalizeServer(value);
  if (!url || url === defaultServer()) {
    server = defaultServer();
    void removeItem(KEYS.server);
    return;
  }
  server = url;
  setItemSync(KEYS.server, url);
}

export function isCustomServer(): boolean {
  return server !== defaultServer();
}
