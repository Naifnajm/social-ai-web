/** Planner: agenda of the posts by day (`/api/planner`), drafts without a date, and the approvals shortcut. */
import { useQuery } from '@tanstack/react-query';
import { useRouter, type Href } from 'expo-router';
import { useMemo, useState } from 'react';
import { Pressable, RefreshControl, SectionList, StyleSheet, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { Icon, PlatformBadge } from '@/components/icon';
import { StateBadge } from '@/components/publishing';
import { TAB_BAR_SPACE } from '@/components/tab-bar';
import { AuthImage, Backdrop, Button, CountBadge, ErrorState, IconButton, Loading, PageHeader, Segmented, Txt } from '@/components/ui';
import { api } from '@/lib/api';
import { formatDate, isoDay } from '@/lib/format';
import { useI18n } from '@/lib/i18n';
import { useSession } from '@/lib/session';
import type { PlannerOut, PlannerPost, Post } from '@/lib/types';
import { colors, radius, shadow } from '@/theme';

type Range = 7 | 14 | 30;

export default function PlannerScreen() {
  const { t, rtl } = useI18n();
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const { can } = useSession();
  const [range, setRange] = useState<Range>(14);
  const [offset, setOffset] = useState(0);

  const start = useMemo(() => {
    const d = new Date();
    d.setHours(0, 0, 0, 0);
    d.setDate(d.getDate() + offset * range);
    return d;
  }, [offset, range]);
  const end = useMemo(() => {
    const d = new Date(start);
    d.setDate(d.getDate() + range);
    return d;
  }, [start, range]);

  const planner = useQuery({
    queryKey: ['planner', isoDay(start), range],
    queryFn: () => api.get<PlannerOut>('/planner', { start: isoDay(start), end: isoDay(end) }),
  });
  const approvals = useQuery({
    queryKey: ['approvals'],
    queryFn: () => api.get<Post[]>('/approvals'),
    enabled: can('approver'),
  });

  const sections = useMemo(() => {
    const data = planner.data;
    if (!data) return [];
    const byDay = new Map<string, PlannerPost[]>();
    for (const p of data.posts) {
      const day = p.day || (p.scheduled_at || p.published_at || '').slice(0, 10);
      if (!day) continue;
      byDay.set(day, [...(byDay.get(day) ?? []), p]);
    }
    const out: { key: string; title: string; today: boolean; data: PlannerPost[] }[] = [...byDay.entries()]
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([day, posts]) => ({
        key: day,
        title: formatDate(`${day}T12:00:00`, { weekday: 'long', day: 'numeric', month: 'long' }),
        today: day === data.today,
        data: posts.sort((a, b) => (a.time || '').localeCompare(b.time || '')),
      }));
    if (data.unplanned.length && offset === 0) out.push({ key: 'unplanned', title: t('planner.unplanned'), today: false, data: data.unplanned });
    return out;
  }, [planner.data, offset, t]);

  const pendingApprovals = approvals.data?.length ?? 0;
  const period = `${formatDate(start)} – ${formatDate(new Date(end.getTime() - 86400000))}`;

  return (
    <View style={{ flex: 1 }}>
      <Backdrop />
      <SectionList
        sections={sections}
        keyExtractor={(p, i) => `${p.id}-${i}`}
        stickySectionHeadersEnabled={false}
        contentContainerStyle={{ paddingTop: insets.top + 8, paddingBottom: TAB_BAR_SPACE + insets.bottom + 10 }}
        refreshControl={<RefreshControl refreshing={planner.isRefetching} onRefresh={() => { void planner.refetch(); void approvals.refetch(); }} tintColor={colors.muted} />}
        ListHeaderComponent={
          <View style={{ gap: 12, marginBottom: 6 }}>
            <PageHeader
              title={t('planner.title')}
              subtitle={planner.data ? t('planner.subtitle', { count: planner.data.posts.length }) : null}
              actions={can('editor') ? <IconButton icon="add" label={t('planner.newPost')} filled onPress={() => router.push('/compose')} /> : null}
            />
            {can('approver') && pendingApprovals ? (
              <Pressable onPress={() => router.push('/approvals')} style={styles.approvals}>
                <View style={styles.approvalIcon}><Icon name="verified_user" size={20} color="#fff" /></View>
                <View style={{ flex: 1 }}>
                  <Txt weight="700">{t('planner.toApprove', { count: pendingApprovals })}</Txt>
                  <Txt muted size={12}>{t('planner.toApproveHint')}</Txt>
                </View>
                <CountBadge count={pendingApprovals} />
              </Pressable>
            ) : null}
            <View style={{ paddingHorizontal: 16, gap: 10 }}>
              <Segmented<Range>
                value={range}
                onChange={(r) => { setRange(r); setOffset(0); }}
                options={[
                  { value: 7, label: t('planner.week') },
                  { value: 14, label: t('planner.twoWeeks') },
                  { value: 30, label: t('planner.month') },
                ]}
              />
              <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
                <IconButton icon="arrow_back" label={t('planner.previous')} onPress={() => setOffset((o) => o - 1)} flip={rtl} filled size={34} />
                <Txt weight="600" size={14} style={{ flex: 1, textAlign: 'center' }}>{period}</Txt>
                <View style={{ transform: [{ scaleX: -1 }] }}>
                  <IconButton icon="arrow_back" label={t('planner.next')} onPress={() => setOffset((o) => o + 1)} flip={rtl} filled size={34} />
                </View>
              </View>
              {offset !== 0 ? <Button size="sm" icon="calendar_today" onPress={() => setOffset(0)} style={{ alignSelf: 'center' }}>{t('planner.today')}</Button> : null}
            </View>
          </View>
        }
        renderSectionHeader={({ section }) => (
          <View style={styles.dayHeader}>
            {section.today ? <View style={styles.todayDot} /> : null}
            <Txt weight="800" size={14} style={{ color: section.today ? colors.ink : colors.text2 }}>
              {section.today ? `${t('planner.todayLabel')} · ` : ''}{section.title}
            </Txt>
          </View>
        )}
        renderItem={({ item }) => <PostRow p={item} onPress={() => router.push(`/post/${item.id}` as Href)} />}
        ListEmptyComponent={
          planner.isLoading ? <Loading /> : planner.isError ? <ErrorState error={planner.error} onRetry={() => planner.refetch()} /> : (
            <View style={{ alignItems: 'center', gap: 10, paddingVertical: 48, paddingHorizontal: 30 }}>
              <View style={styles.emptyIcon}><Icon name="calendar_today" size={26} color="#fff" duo /></View>
              <Txt weight="700" size={16}>{t('planner.emptyTitle')}</Txt>
              <Txt muted style={{ textAlign: 'center' }}>{t('planner.emptyText')}</Txt>
              {can('editor') ? <Button variant="primary" icon="add" onPress={() => router.push('/create')}>{t('planner.createPost')}</Button> : null}
            </View>
          )
        }
      />
    </View>
  );
}

function PostRow({ p, onPress }: { p: PlannerPost; onPress: () => void }) {
  const accent = p.campaign?.color || p.pillar?.color;
  return (
    <Pressable onPress={onPress} style={({ pressed }) => [styles.post, pressed && { opacity: 0.8 }]}>
      {accent ? <View style={[styles.accent, { backgroundColor: accent }]} /> : null}
      <View style={styles.thumb}>
        {p.media && p.media.kind === 'image' ? <AuthImage src={p.media.url} style={StyleSheet.absoluteFill} /> : (
          <Icon name={p.media ? 'movie' : 'text_fields'} size={22} color={colors.muted} />
        )}
        {p.media_count && p.media_count > 1 ? <View style={styles.count}><Txt size={10} weight="700" style={{ color: '#fff' }}>{p.media_count}</Txt></View> : null}
      </View>
      <View style={{ flex: 1, minWidth: 0, gap: 4 }}>
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
          {p.time ? <Txt weight="800" size={13}>{p.time}</Txt> : null}
          <Txt weight="600" size={14} numberOfLines={1} style={{ flex: 1 }}>{p.name}</Txt>
        </View>
        {p.preview ? <Txt muted size={13} numberOfLines={2}>{p.preview}</Txt> : null}
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: 4, flexWrap: 'wrap' }}>
          {p.platforms.map((pl) => <PlatformBadge key={pl} platform={pl} size={18} />)}
          <View style={{ flex: 1 }} />
          <StateBadge state={p.state} />
        </View>
      </View>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  approvals: { flexDirection: 'row', alignItems: 'center', gap: 12, marginHorizontal: 16, padding: 14, borderRadius: radius.lg, backgroundColor: 'rgba(255,255,255,0.85)', borderWidth: 1, borderColor: colors.line, ...shadow },
  approvalIcon: { width: 38, height: 38, borderRadius: 12, backgroundColor: colors.ink, alignItems: 'center', justifyContent: 'center' },
  dayHeader: { flexDirection: 'row', alignItems: 'center', gap: 6, paddingHorizontal: 20, paddingTop: 16, paddingBottom: 8 },
  todayDot: { width: 8, height: 8, borderRadius: 4, backgroundColor: colors.badSolid },
  post: { flexDirection: 'row', gap: 12, marginHorizontal: 16, marginBottom: 8, padding: 10, borderRadius: radius.lg, backgroundColor: 'rgba(255,255,255,0.8)', borderWidth: 1, borderColor: colors.glassEdge, overflow: 'hidden', ...shadow },
  accent: { position: 'absolute', start: 0, top: 0, bottom: 0, width: 4 },
  thumb: { width: 64, height: 64, borderRadius: 12, overflow: 'hidden', backgroundColor: colors.fill2, alignItems: 'center', justifyContent: 'center' },
  count: { position: 'absolute', bottom: 3, end: 3, backgroundColor: 'rgba(0,0,0,0.6)', borderRadius: 8, paddingHorizontal: 5 },
  emptyIcon: { width: 56, height: 56, borderRadius: 18, backgroundColor: colors.ink, alignItems: 'center', justifyContent: 'center' },
});
