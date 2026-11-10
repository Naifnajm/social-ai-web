/**
 * Small key/value store: expo-secure-store (Keychain / Keystore) on phones, localStorage on the web build.
 * Used for the session tokens, the API server, the language and the active workspace.
 */
import * as SecureStore from 'expo-secure-store';
import { Platform } from 'react-native';

const web = Platform.OS === 'web';

function webStore(): Storage | null {
  try {
    return typeof window !== 'undefined' ? window.localStorage : null;
  } catch {
    return null;
  }
}

export async function getItem(key: string): Promise<string | null> {
  if (web) return webStore()?.getItem(key) ?? null;
  try {
    return await SecureStore.getItemAsync(key);
  } catch {
    return null;
  }
}

export async function setItem(key: string, value: string | null): Promise<void> {
  if (value === null) return removeItem(key);
  if (web) {
    webStore()?.setItem(key, value);
    return;
  }
  await SecureStore.setItemAsync(key, value);
}

export async function removeItem(key: string): Promise<void> {
  if (web) {
    webStore()?.removeItem(key);
    return;
  }
  try {
    await SecureStore.deleteItemAsync(key);
  } catch {
    /* nothing stored */
  }
}

/** Synchronous read (language at start-up, before the first render). */
export function getItemSync(key: string): string | null {
  if (web) return webStore()?.getItem(key) ?? null;
  try {
    return SecureStore.getItem(key);
  } catch {
    return null;
  }
}

export function setItemSync(key: string, value: string): void {
  if (web) {
    webStore()?.setItem(key, value);
    return;
  }
  try {
    SecureStore.setItem(key, value);
  } catch {
    /* best effort */
  }
}

export const KEYS = {
  access: 'sai.access',
  refresh: 'sai.refresh',
  server: 'sai.server',
  workspace: 'sai.workspace',
  locale: 'sai.locale',
  pushToken: 'sai.push',
} as const;
