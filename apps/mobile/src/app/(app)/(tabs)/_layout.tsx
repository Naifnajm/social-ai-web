import { useQuery } from '@tanstack/react-query';
import { Tabs } from 'expo-router/js-tabs';

import { GlassTabBar } from '@/components/tab-bar';
import { api } from '@/lib/api';
import { useI18n } from '@/lib/i18n';
import { colors } from '@/theme';

export default function TabsLayout() {
  const { t } = useI18n();
  const unread = useQuery({
    queryKey: ['inbox-unread'],
    queryFn: () => api.get<{ unread: number; pending: number }>('/inbox/unread'),
    refetchInterval: 30_000,
  });
  const badges = { inbox: unread.data?.unread ?? 0 };
  return (
    <Tabs
      tabBar={(props) => <GlassTabBar {...props} badges={badges} />}
      screenOptions={{ headerShown: false, sceneStyle: { backgroundColor: colors.bg } }}>
      <Tabs.Screen name="inbox" options={{ title: t('tabs.inbox') }} />
      <Tabs.Screen name="planner" options={{ title: t('tabs.planner') }} />
      <Tabs.Screen name="create" options={{ title: t('tabs.create') }} />
      <Tabs.Screen name="performance" options={{ title: t('tabs.performance') }} />
      <Tabs.Screen name="more" options={{ title: t('tabs.more') }} />
    </Tabs>
  );
}
