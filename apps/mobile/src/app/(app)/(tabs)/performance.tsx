/** Performance: KPIs vs the previous period, trends, networks, best times, top posts, tips and inbox stats. */
import { useQuery } from '@tanstack/react-query';
import * as WebBrowser from 'expo-web-browser';
import { useState } from 'react';
import { Pressable, RefreshControl, ScrollView, StyleSheet, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { AreaChart, BarChart, ShareBars } from '@/components/charts';
import { Icon, PlatformBadge } from '@/components/icon';
import { TAB_BAR_SPACE } from '@/components/tab-bar';
import { Backdrop, Card, ErrorState, Loading, PageHeader, SectionTitle, Segmented, Txt } from '@/components/ui';
import { api } from '@/lib/api';
import { compact, formatDate, formatNumber } from '@/lib/format';
import { useI18n } from '@/lib/i18n';
import { useSession } from '@/lib/session';
import type { Dashboard, InboxStats, Tip } from '@/lib/types';
import { colors, radius, PLATFORM_LABELS } from '@/theme';

type Days = 7 | 30 | 90;
const DAY_KEYS = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'];

export default function PerformanceScreen() {
  const { t } = useI18n();
  const insets = useSafeAreaInsets();
  const { can } = useSession();
  const [days, setDays] = useState<Days>(30);
  const dash = useQuery({ queryKey: ['dashboard', days], queryFn: () => api.get<Dashboard>('/analytics/dashboard', { days }) });
  const inbox = useQuery({ queryKey: ['inbox-stats', days], queryFn: () => api.get<InboxStats>('/inbox/stats', { days }), enabled: can('viewer') });
  const d = dash.data;

  const kpis = d
    ? [
        { key: 'posts', icon: 'send', value: formatNumber(d.kpis.posts ?? 0), delta: d.deltas.posts },
        { key: 'impressions', icon: 'visibility', value: compact(d.kpis.impressions), delta: d.deltas.impressions },
        { key: 'engagements', icon: 'favorite', value: compact(d.kpis.engagements), delta: d.deltas.engagements },
        { key: 'engagement_rate', icon: 'percent', value: `${formatNumber(d.kpis.engagement_rate ?? 0)}%`, delta: d.deltas.engagement_rate },
        { key: 'followers', icon: 'group', value: compact(d.kpis.followers), sub: d.kpis.followers_growth ? `${d.kpis.followers_growth > 0 ? '+' : ''}${formatNumber(d.kpis.followers_growth)}` : undefined },
        { key: 'video_views', icon: 'play_circle', value: compact(d.kpis.video_views), delta: d.deltas.video_views },
      ]
    : [];

  return (
    <View style={{ flex: 1 }}>
      <Backdrop />
      <ScrollView
        contentContainerStyle={{ paddingTop: insets.top + 8, paddingBottom: TAB_BAR_SPACE + insets.bottom + 10 }}
        refreshControl={<RefreshControl refreshing={dash.isRefetching} onRefresh={() => { void dash.refetch(); void inbox.refetch(); }} tintColor={colors.muted} />}>
        <PageHeader title={t('performance.title')} subtitle={d?.last_sync ? t('performance.lastSync', { date: formatDate(d.last_sync, { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }) }) : t('performance.subtitle')} />
        <View style={{ paddingHorizontal: 16, gap: 14 }}>
          <Segmented<Days>
            value={days}
            onChange={setDays}
            options={[7, 30, 90].map((n) => ({ value: n as Days, label: t('performance.lastDays', { n }) }))}
          />
          {dash.isLoading ? <Loading /> : dash.isError || !d ? <ErrorState error={dash.error} onRetry={() => dash.refetch()} /> : (
            <>
              <View style={styles.grid}>
                {kpis.map((k) => (
                  <Card key={k.key} style={styles.kpi}>
                    <View style={{ flexDirection: 'row', alignItems: 'center', gap: 5 }}>
                      <Icon name={k.icon} size={15} color={colors.muted} />
                      <Txt muted size={12} numberOfLines={1} style={{ flex: 1 }}>{t(`performance.kpi.${k.key}`)}</Txt>
                    </View>
                    <Txt style={{ fontSize: 24, fontWeight: '800', letterSpacing: -0.5, marginTop: 4 }}>{k.value}</Txt>
                    {'sub' in k && k.sub ? <Txt muted size={12}>{k.sub}</Txt> : <Delta value={'delta' in k ? k.delta : null} />}
                  </Card>
                ))}
              </View>

              <Card style={{ gap: 14 }}>
                <SectionTitle icon="show_chart">{t('performance.trend')}</SectionTitle>
                <View style={{ gap: 4 }}>
                  <Txt muted size={12}>{t('performance.kpi.impressions')}</Txt>
                  <AreaChart values={d.series.map((s) => s.impressions)} emptyLabel={t('performance.noData')} />
                </View>
                <View style={{ gap: 4 }}>
                  <Txt muted size={12}>{t('performance.kpi.engagements')}</Txt>
                  <AreaChart height={90} values={d.series.map((s) => s.engagements)} emptyLabel={t('performance.noData')} color={colors.ink2} />
                </View>
                <View style={{ gap: 4 }}>
                  <Txt muted size={12}>{t('performance.postsPerDay')}</Txt>
                  <BarChart values={d.series.map((s) => s.posts)} />
                  {d.series.length ? (
                    <View style={{ flexDirection: 'row', justifyContent: 'space-between', direction: 'ltr' }}>
                      <Txt size={11} style={{ color: colors.faint }}>{formatDate(`${d.series[0].date}T12:00:00`)}</Txt>
                      <Txt size={11} style={{ color: colors.faint }}>{formatDate(`${d.series[d.series.length - 1].date}T12:00:00`)}</Txt>
                    </View>
                  ) : null}
                </View>
              </Card>

              {d.tips.length ? (
                <Card style={{ gap: 10 }}>
                  <SectionTitle icon="lightbulb">{t('performance.tips')}</SectionTitle>
                  {d.tips.map((tip, i) => <TipRow key={i} tip={tip} />)}
                </Card>
              ) : null}

              {d.breakdown.length ? (
                <Card style={{ gap: 4 }}>
                  <SectionTitle icon="table">{t('performance.byNetwork')}</SectionTitle>
                  {d.breakdown.map((r, i) => (
                    <View key={r.platform} style={[styles.netRow, i < d.breakdown.length - 1 && styles.line]}>
                      <PlatformBadge platform={r.platform} size={28} />
                      <View style={{ flex: 1 }}>
                        <Txt weight="600">{r.label || PLATFORM_LABELS[r.platform]}</Txt>
                        <Txt muted size={12}>{t('performance.netLine', { posts: r.posts, followers: compact(r.followers) })}</Txt>
                      </View>
                      <View style={{ alignItems: 'flex-end' }}>
                        <Txt weight="700">{compact(r.impressions)}</Txt>
                        <Txt muted size={11}>{`${formatNumber(r.engagement_rate)}%`}</Txt>
                      </View>
                    </View>
                  ))}
                </Card>
              ) : null}

              {d.best_slots.length ? (
                <Card style={{ gap: 10 }}>
                  <SectionTitle icon="schedule" actions={<Txt muted size={11}>{d.best_source === 'own' ? t('performance.fromResults') : t('performance.benchmark')}</Txt>}>
                    {t('performance.bestTimes')}
                  </SectionTitle>
                  <View style={{ flexDirection: 'row', gap: 8 }}>
                    {d.best_slots.slice(0, 3).map((s, i) => (
                      <View key={i} style={[styles.slot, i === 0 && { backgroundColor: colors.ink }]}>
                        <Txt size={12} weight="600" style={{ color: i === 0 ? 'rgba(255,255,255,0.7)' : colors.muted }}>{t(`performance.days.${DAY_KEYS[s.weekday] ?? 'mon'}`)}</Txt>
                        <Txt size={18} weight="800" style={{ color: i === 0 ? '#fff' : colors.text }}>{`${String(s.hour).padStart(2, '0')}:00`}</Txt>
                      </View>
                    ))}
                  </View>
                </Card>
              ) : null}

              {d.top_posts.length ? (
                <Card style={{ gap: 4 }}>
                  <SectionTitle icon="trophy">{t('performance.topPosts')}</SectionTitle>
                  {d.top_posts.slice(0, 5).map((p, i) => (
                    <Pressable key={`${p.id}-${i}`} disabled={!p.url} onPress={() => void WebBrowser.openBrowserAsync(p.url)} style={[styles.netRow, i < Math.min(d.top_posts.length, 5) - 1 && styles.line]}>
                      <Txt weight="800" size={15} style={{ width: 18, color: colors.faint }}>{i + 1}</Txt>
                      <PlatformBadge platform={p.platform} size={24} />
                      <View style={{ flex: 1, minWidth: 0 }}>
                        <Txt size={14} numberOfLines={1}>{p.name}</Txt>
                        <Txt muted size={12}>{t('performance.topLine', { impressions: compact(p.impressions), engagements: compact(p.engagements) })}</Txt>
                      </View>
                      <Txt weight="700" size={13}>{`${formatNumber(p.engagement_rate)}%`}</Txt>
                    </Pressable>
                  ))}
                </Card>
              ) : null}
            </>
          )}

          {inbox.data ? <InboxStatsCard s={inbox.data} /> : null}
        </View>
      </ScrollView>
    </View>
  );
}

function Delta({ value }: { value?: number | null }) {
  const { t } = useI18n();
  if (value === null || value === undefined) return <Txt size={12} style={{ color: colors.faint }}>{t('performance.noCompare')}</Txt>;
  const up = value >= 0;
  return (
    <View style={{ flexDirection: 'row', alignItems: 'center', gap: 2 }}>
      <Icon name={up ? 'arrow_upward' : 'arrow_downward'} size={13} color={up ? colors.ok : colors.bad} />
      <Txt size={12} weight="700" style={{ color: up ? colors.ok : colors.bad }}>{`${formatNumber(Math.abs(value))}%`}</Txt>
    </View>
  );
}

function TipRow({ tip }: { tip: Tip }) {
  const bg = tip.level === 'danger' ? colors.badBg : tip.level === 'warning' ? colors.warnBg : tip.level === 'success' ? colors.okBg : colors.fill;
  const fg = tip.level === 'danger' ? colors.bad : tip.level === 'warning' ? colors.warn : tip.level === 'success' ? colors.ok : colors.text2;
  return (
    <View style={{ flexDirection: 'row', gap: 10, padding: 12, borderRadius: 14, backgroundColor: bg }}>
      <Icon name={tip.icon || 'lightbulb'} size={18} color={fg} />
      <View style={{ flex: 1, gap: 2 }}>
        <Txt weight="700" size={14} style={{ color: fg }}>{tip.title}</Txt>
        <Txt size={13} style={{ color: colors.text2 }}>{tip.text}</Txt>
      </View>
    </View>
  );
}

function InboxStatsCard({ s }: { s: InboxStats }) {
  const { t } = useI18n();
  const sentiments = ['positive', 'neutral', 'negative'] as const;
  const total = sentiments.reduce((n, k) => n + (s.sentiment[k] ?? 0), 0);
  return (
    <Card style={{ gap: 12 }}>
      <SectionTitle icon="inbox">{t('performance.inbox.title')}</SectionTitle>
      <View style={styles.grid}>
        {[
          { key: 'conversations', value: formatNumber(s.conversations) },
          { key: 'replies', value: formatNumber(s.replies) },
          { key: 'botShare', value: `${formatNumber(Math.round(s.bot_share))}%` },
          { key: 'firstResponse', value: s.avg_first_response_minutes ? t('performance.inbox.minutes', { n: Math.round(s.avg_first_response_minutes) }) : '—' },
        ].map((k) => (
          <View key={k.key} style={styles.mini}>
            <Txt muted size={12}>{t(`performance.inbox.${k.key}`)}</Txt>
            <Txt size={20} weight="800">{k.value}</Txt>
          </View>
        ))}
      </View>
      {total ? (
        <ShareBars
          rows={sentiments.map((k) => ({
            label: t(`inbox.sentiment.${k}`),
            value: s.sentiment[k] ?? 0,
            hint: `${Math.round(((s.sentiment[k] ?? 0) / total) * 100)}%`,
            color: k === 'positive' ? colors.ok : k === 'negative' ? colors.badSolid : colors.faint,
          }))}
        />
      ) : null}
      {s.by_platform.length ? (
        <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 8 }}>
          {s.by_platform.map((p) => (
            <View key={p.platform} style={styles.platformChip}>
              <PlatformBadge platform={p.platform} size={18} />
              <Txt size={12} weight="600">{formatNumber(p.conversations)}</Txt>
            </View>
          ))}
        </View>
      ) : null}
    </Card>
  );
}

const styles = StyleSheet.create({
  grid: { flexDirection: 'row', flexWrap: 'wrap', gap: 10 },
  kpi: { width: '48.2%', flexGrow: 1, padding: 14, gap: 2 },
  netRow: { flexDirection: 'row', alignItems: 'center', gap: 10, paddingVertical: 10 },
  line: { borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.line },
  slot: { flex: 1, padding: 12, borderRadius: radius.md, backgroundColor: colors.fill, gap: 2 },
  mini: { width: '47%', flexGrow: 1, padding: 12, borderRadius: radius.md, backgroundColor: colors.fill, gap: 2 },
  platformChip: { flexDirection: 'row', alignItems: 'center', gap: 6, paddingStart: 4, paddingEnd: 10, height: 28, borderRadius: 14, backgroundColor: colors.fill },
});
