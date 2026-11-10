import { QueryClient, QueryClientProvider, focusManager } from '@tanstack/react-query';
import { Stack } from 'expo-router';
import * as SplashScreen from 'expo-splash-screen';
import { StatusBar } from 'expo-status-bar';
import { useEffect } from 'react';
import { AppState, Platform } from 'react-native';
import { GestureHandlerRootView } from 'react-native-gesture-handler';

import { ToastHost } from '@/components/ui';
import { reloadApp, syncDirection } from '@/lib/i18n';
import { bootstrap, getSession, useSession } from '@/lib/session';
import { colors } from '@/theme';

void SplashScreen.preventAutoHideAsync().catch(() => undefined);

// the native layout direction follows the language; a change only applies after a reload
if (syncDirection()) void reloadApp();

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: 1, staleTime: 20_000, refetchOnWindowFocus: true },
    mutations: { retry: 0 },
  },
});

// refetch active queries when the app comes back to the foreground
if (Platform.OS !== 'web') {
  AppState.addEventListener('change', (s) => focusManager.setFocused(s === 'active'));
}

let lastWorkspace: number | null | undefined;

export default function RootLayout() {
  const { status, workspace } = useSession();

  useEffect(() => {
    void bootstrap();
  }, []);

  useEffect(() => {
    if (status !== 'loading') void SplashScreen.hideAsync().catch(() => undefined);
  }, [status]);

  // a different workspace (or signing out) must never show cached data of the previous one
  useEffect(() => {
    const id = workspace?.id ?? null;
    if (lastWorkspace !== undefined && lastWorkspace !== id) queryClient.clear();
    lastWorkspace = getSession().status === 'loading' ? undefined : id;
  }, [workspace?.id, status]);

  return (
    <GestureHandlerRootView style={{ flex: 1, backgroundColor: colors.bg }}>
      <QueryClientProvider client={queryClient}>
        <StatusBar style="dark" />
        <Stack screenOptions={{ headerShown: false, contentStyle: { backgroundColor: colors.bg } }}>
          <Stack.Screen name="index" />
          <Stack.Protected guard={status === 'signedIn'}>
            <Stack.Screen name="(app)" />
          </Stack.Protected>
          <Stack.Protected guard={status === 'signedOut'}>
            <Stack.Screen name="(auth)" />
          </Stack.Protected>
        </Stack>
        <ToastHost />
      </QueryClientProvider>
    </GestureHandlerRootView>
  );
}
