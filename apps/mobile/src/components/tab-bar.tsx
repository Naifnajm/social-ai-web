/** Floating glass tab bar with Solar icons (duo when active) and an unread badge on the inbox. */
import type { BottomTabBarProps } from 'expo-router/js-tabs';
import { Pressable, StyleSheet, View } from 'react-native';

import { tap } from '@/lib/format';
import { useI18n } from '@/lib/i18n';
import { colors, shadowFloat } from '@/theme';

import { Glass } from './glass';
import { Icon } from './icon';
import { CountBadge, Txt } from './ui';

const ICONS: Record<string, string> = {
  inbox: 'inbox',
  create: 'add_photo',
  planner: 'calendar_today',
  performance: 'bar_chart',
  more: 'apps',
};

export function GlassTabBar({ state, emitter, navigateToTab, insets, badges }: BottomTabBarProps & { badges: Record<string, number> }) {
  const { t } = useI18n();
  return (
    <View style={[styles.wrap, { paddingBottom: Math.max(insets.bottom, 10), pointerEvents: 'box-none' }]}>
      <Glass strong style={styles.bar}>
        <View style={styles.row} role="tablist">
          {state.routes.map((route, index) => {
            const focused = index === state.index;
            const isCreate = route.name === 'create';
            const onPress = () => {
              tap();
              const event = emitter.emit({ type: 'tabPress', target: route.key, canPreventDefault: true });
              if (!focused && !event.defaultPrevented) navigateToTab(route.key);
            };
            return (
              <Pressable
                key={route.key}
                role="tab"
                accessibilityState={{ selected: focused }}
                accessibilityLabel={t(`tabs.${route.name}`)}
                onPress={onPress}
                style={styles.item}>
                {isCreate ? (
                  <View style={[styles.create, focused && { transform: [{ scale: 1.05 }] }]}>
                    <Icon name="add" size={24} color="#fff" />
                  </View>
                ) : (
                  <View style={[styles.pill, focused && styles.pillActive]}>
                    <Icon name={ICONS[route.name] ?? 'apps'} size={22} duo={focused} color={focused ? colors.ink : colors.muted} />
                    {badges[route.name] ? <CountBadge count={badges[route.name]} style={styles.badge} /> : null}
                  </View>
                )}
                <Txt size={10} weight={focused ? '700' : '500'} numberOfLines={1} style={{ color: focused ? colors.ink : colors.muted }}>
                  {t(`tabs.${route.name}`)}
                </Txt>
              </Pressable>
            );
          })}
        </View>
      </Glass>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { position: 'absolute', start: 0, end: 0, bottom: 0, paddingHorizontal: 12 },
  bar: { borderRadius: 30, borderWidth: 1, borderColor: colors.glassEdge, ...shadowFloat },
  row: { flexDirection: 'row', alignItems: 'center', paddingHorizontal: 6, paddingVertical: 6 },
  item: { flex: 1, alignItems: 'center', gap: 2, paddingVertical: 2 },
  pill: { width: 52, height: 32, borderRadius: 16, alignItems: 'center', justifyContent: 'center' },
  pillActive: { backgroundColor: 'rgba(0,0,0,0.07)' },
  create: { width: 46, height: 32, borderRadius: 16, backgroundColor: colors.ink, alignItems: 'center', justifyContent: 'center' },
  badge: { position: 'absolute', top: -4, end: 4 },
});

/** Space to leave at the bottom of tab screens so content can scroll above the floating bar. */
export const TAB_BAR_SPACE = 96;
