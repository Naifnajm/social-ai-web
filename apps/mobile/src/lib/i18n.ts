/**
 * Translations (src/i18n/{ar,en}.json) and layout direction.
 *
 *   const { t, locale, rtl } = useI18n();
 *   t('inbox.title');  t('quick.selected', { count: 3 });
 *
 * Arabic is the default (device language when it is Arabic or English, else Arabic). Switching language on a phone
 * flips the native layout direction (I18nManager.forceRTL), which needs an app reload.
 */
import { getLocales } from 'expo-localization';
import { useSyncExternalStore } from 'react';
import { Alert, DevSettings, I18nManager, Platform } from 'react-native';

import ar from '@/i18n/ar.json';
import en from '@/i18n/en.json';

import { KEYS, getItemSync, setItemSync } from './storage';

export type Lang = 'ar' | 'en';
type Dict = { [key: string]: string | Dict };
const DICTS: Record<Lang, Dict> = { ar: ar as Dict, en: en as Dict };

function deviceLang(): Lang | null {
  try {
    const code = getLocales()[0]?.languageCode;
    return code === 'ar' || code === 'en' ? code : null;
  } catch {
    return null;
  }
}

function initialLang(): Lang {
  const stored = getItemSync(KEYS.locale);
  if (stored === 'ar' || stored === 'en') return stored;
  return deviceLang() ?? 'ar';
}

let locale: Lang = initialLang();
const listeners = new Set<() => void>();

function lookup(dict: Dict, key: string): string | undefined {
  let node: string | Dict | undefined = dict;
  for (const part of key.split('.')) {
    if (!node || typeof node === 'string') return undefined;
    node = node[part];
  }
  return typeof node === 'string' ? node : undefined;
}

export type Params = Record<string, string | number | null | undefined>;

export function t(key: string, params?: Params): string {
  let text = lookup(DICTS[locale], key) ?? lookup(DICTS.en, key) ?? key;
  if (params) {
    // "{count}" plurals: key_one / key_two (Arabic dual) / key_other when present
    if (typeof params.count === 'number') {
      const n = params.count;
      const form = n === 1 ? 'one' : n === 2 && locale === 'ar' ? 'two' : n >= 3 && n <= 10 && locale === 'ar' ? 'few' : 'other';
      text = lookup(DICTS[locale], `${key}_${form}`) ?? lookup(DICTS[locale], `${key}_other`) ?? text;
    }
    text = text.replace(/\{(\w+)\}/g, (match, name: string) => {
      const value = params[name];
      return value === undefined || value === null ? match : typeof value === 'number' ? formatNumber(value) : value;
    });
  }
  return text;
}

export function getLocale(): Lang {
  return locale;
}

export function isRTL(): boolean {
  return locale === 'ar';
}

/** Intl locale: Arabic with Latin digits (clearer for business numbers, matches what Gulf users type). */
export function intlLocale(): string {
  return locale === 'ar' ? 'ar-u-nu-latn' : 'en-GB';
}

export function formatNumber(n: number, options?: Intl.NumberFormatOptions): string {
  try {
    return new Intl.NumberFormat(intlLocale(), options).format(n);
  } catch {
    return String(n);
  }
}

function applyWebDirection() {
  if (Platform.OS !== 'web' || typeof document === 'undefined') return;
  document.documentElement.dir = locale === 'ar' ? 'rtl' : 'ltr';
  document.documentElement.lang = locale;
}

/**
 * Called once at start-up: make the native layout direction match the language. Returns true when the app has to
 * reload first (the direction only changes after a reload).
 */
export function syncDirection(): boolean {
  if (Platform.OS === 'web') {
    applyWebDirection();
    return false;
  }
  const wantRTL = locale === 'ar';
  I18nManager.allowRTL(true);
  if (I18nManager.isRTL === wantRTL) return false;
  I18nManager.forceRTL(wantRTL);
  // avoid a reload loop when the platform ignores forceRTL (e.g. RTL disabled in the build)
  const attempt = `${locale}:${Math.floor(Date.now() / 60000)}`;
  if (getItemSync('sai.rtl-attempt') === attempt) return false;
  setItemSync('sai.rtl-attempt', attempt);
  return true;
}

export async function reloadApp(): Promise<void> {
  if (Platform.OS === 'web') {
    window.location.reload();
    return;
  }
  try {
    const Updates = await import('expo-updates');
    await Updates.reloadAsync();
    return;
  } catch {
    /* expo-updates unavailable (e.g. Expo Go in some setups) */
  }
  try {
    if (__DEV__) {
      DevSettings.reload();
      return;
    }
  } catch {
    /* fall through */
  }
  Alert.alert(t('settings.restartTitle'), t('settings.restartText'));
}

/** Changes the UI language. On phones the direction flips, so the app reloads (or asks to be restarted). */
export async function setLanguage(next: Lang): Promise<void> {
  if (next === locale) return;
  locale = next;
  setItemSync(KEYS.locale, next);
  if (Platform.OS === 'web') {
    applyWebDirection();
    listeners.forEach((l) => l());
    return;
  }
  I18nManager.allowRTL(true);
  I18nManager.forceRTL(next === 'ar');
  listeners.forEach((l) => l());
  await reloadApp();
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function useI18n() {
  const current = useSyncExternalStore(subscribe, getLocale, getLocale);
  return { t, locale: current, rtl: current === 'ar' };
}
