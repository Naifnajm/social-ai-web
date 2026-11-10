/**
 * Push notifications (Expo push service): ask permission, register the Expo push token with `POST /api/devices`
 * after sign-in, unregister it on sign-out, and turn a notification `link` (web path) into an app route.
 */
import Constants from 'expo-constants';
import * as Device from 'expo-device';
import * as Notifications from 'expo-notifications';
import { Platform } from 'react-native';

import { api } from './api';
import { KEYS, getItem, removeItem, setItem } from './storage';

export type PushStatus = 'registered' | 'denied' | 'unavailable';

const supported = Platform.OS !== 'web';

if (supported) {
  Notifications.setNotificationHandler({
    handleNotification: async () => ({
      shouldShowBanner: true,
      shouldShowList: true,
      shouldPlaySound: true,
      shouldSetBadge: true,
    }),
  });
}

function projectId(): string | undefined {
  const extra = Constants.expoConfig?.extra as { eas?: { projectId?: string } } | undefined;
  return extra?.eas?.projectId ?? Constants.easConfig?.projectId ?? undefined;
}

export async function registerPush({ ask = true }: { ask?: boolean } = {}): Promise<PushStatus> {
  if (!supported || !Device.isDevice) return 'unavailable';
  try {
    if (Platform.OS === 'android') {
      await Notifications.setNotificationChannelAsync('default', {
        name: 'Stravica Social',
        importance: Notifications.AndroidImportance.HIGH,
        vibrationPattern: [0, 180, 120, 180],
        lightColor: '#0a0a0a',
      });
    }
    let { status } = await Notifications.getPermissionsAsync();
    if (status !== 'granted' && ask) status = (await Notifications.requestPermissionsAsync()).status;
    if (status !== 'granted') return 'denied';
    const id = projectId();
    const token = (await Notifications.getExpoPushTokenAsync(id ? { projectId: id } : undefined)).data;
    await api.post('/devices', { push_token: token, platform: Platform.OS });
    await setItem(KEYS.pushToken, token);
    return 'registered';
  } catch {
    // no projectId (not built with EAS), Expo Go without push support, offline…: the app works without push
    return 'unavailable';
  }
}

export async function unregisterPush(): Promise<void> {
  const token = await getItem(KEYS.pushToken);
  if (!token) return;
  try {
    await api.delete(`/devices/${encodeURIComponent(token)}`);
  } finally {
    await removeItem(KEYS.pushToken);
  }
}

export async function pushPermission(): Promise<'granted' | 'denied' | 'undetermined' | 'unavailable'> {
  if (!supported) return 'unavailable';
  try {
    return (await Notifications.getPermissionsAsync()).status as 'granted' | 'denied' | 'undetermined';
  } catch {
    return 'unavailable';
  }
}

/**
 * Notification links are web paths (`/inbox/12`, `/posts?post=5`, `/approvals?post=5`, `/planner?post=5`…).
 * Returns the matching app route.
 */
export function routeForLink(link?: string | null): string {
  if (!link) return '/notifications';
  const [path, search = ''] = link.replace(/^\/(ar|en)(?=\/)/, '').split('?');
  const params = new URLSearchParams(search);
  const post = params.get('post');
  const inbox = path.match(/^\/inbox\/(\d+)/);
  if (inbox) return `/inbox/${inbox[1]}`;
  if (path.startsWith('/inbox')) return '/inbox';
  if (path.startsWith('/approvals')) return post ? `/post/${post}` : '/approvals';
  if (/^\/(posts|planner|studio)/.test(path)) return post ? `/post/${post}` : path.startsWith('/planner') ? '/planner' : '/notifications';
  if (path.startsWith('/performance')) return '/performance';
  return '/notifications';
}
