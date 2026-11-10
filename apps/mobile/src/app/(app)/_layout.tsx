import * as Notifications from 'expo-notifications';
import { Stack, useRouter, type Href } from 'expo-router';
import { useEffect } from 'react';
import { Platform } from 'react-native';

import { registerPush, routeForLink, unregisterPush } from '@/lib/push';
import { onSigningOut } from '@/lib/session';
import { colors } from '@/theme';

onSigningOut(unregisterPush);

/** Signed-in area: the tabs plus the detail screens pushed over them. Registers push and opens tapped notifications. */
export default function AppLayout() {
  const router = useRouter();

  useEffect(() => {
    void registerPush();
  }, []);

  useEffect(() => {
    if (Platform.OS === 'web') return;
    const open = (response: Notifications.NotificationResponse | null) => {
      const link = response?.notification.request.content.data?.link;
      if (response) router.push(routeForLink(typeof link === 'string' ? link : null) as Href);
    };
    let handled = false;
    void Notifications.getLastNotificationResponseAsync().then((r) => {
      if (r && !handled) {
        handled = true;
        open(r);
        void Notifications.clearLastNotificationResponseAsync();
      }
    }).catch(() => undefined);
    const sub = Notifications.addNotificationResponseReceivedListener((r) => {
      handled = true;
      open(r);
    });
    return () => sub.remove();
  }, [router]);

  return (
    <Stack screenOptions={{ headerShown: false, contentStyle: { backgroundColor: colors.bg } }}>
      <Stack.Screen name="(tabs)" />
      <Stack.Screen name="inbox/[id]" />
      <Stack.Screen name="post/[id]" />
      <Stack.Screen name="approvals" />
      <Stack.Screen name="notifications" />
      <Stack.Screen name="compose" options={{ presentation: 'modal' }} />
      <Stack.Screen name="accounts" />
      <Stack.Screen name="settings" />
      <Stack.Screen name="workspaces" />
    </Stack>
  );
}
