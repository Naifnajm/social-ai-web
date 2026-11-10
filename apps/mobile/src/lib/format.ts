/** Date and number formatting in the UI language. */
import * as Haptics from 'expo-haptics';
import { Platform } from 'react-native';

import { formatNumber, intlLocale, t } from './i18n';

function fmt(date: Date, options: Intl.DateTimeFormatOptions): string {
  try {
    return new Intl.DateTimeFormat(intlLocale(), options).format(date);
  } catch {
    return date.toISOString().slice(0, 16).replace('T', ' ');
  }
}

export const formatDate = (iso: string | Date, options: Intl.DateTimeFormatOptions = { day: 'numeric', month: 'short' }) =>
  fmt(typeof iso === 'string' ? new Date(iso) : iso, options);

export const formatDateTime = (iso: string | Date) =>
  formatDate(iso, { weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });

export const formatTime = (iso: string | Date) => formatDate(iso, { hour: '2-digit', minute: '2-digit' });

/** "now", "5 min", "3 h", "yesterday", "12 Mar". */
export function relativeTime(iso?: string | null): string {
  if (!iso) return '';
  const date = new Date(iso);
  const diff = (Date.now() - date.getTime()) / 1000;
  if (diff < 60) return t('time.now');
  if (diff < 3600) return t('time.minutes', { n: Math.floor(diff / 60) });
  if (diff < 86400) return t('time.hours', { n: Math.floor(diff / 3600) });
  if (diff < 172800) return t('time.yesterday');
  if (diff < 7 * 86400) return formatDate(date, { weekday: 'long' });
  return formatDate(date);
}

export function compact(n?: number | null): string {
  return formatNumber(n ?? 0, { notation: 'compact', maximumFractionDigits: 1 });
}

export { formatNumber };

/** Light haptic tap on key actions (no-op on the web). */
export function tap(kind: 'light' | 'success' | 'warning' = 'light') {
  if (Platform.OS === 'web') return;
  try {
    if (kind === 'light') void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    else void Haptics.notificationAsync(kind === 'success' ? Haptics.NotificationFeedbackType.Success : Haptics.NotificationFeedbackType.Warning);
  } catch {
    /* haptics unavailable */
  }
}

/** Local "YYYY-MM-DD". */
export function isoDay(date: Date): string {
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}
