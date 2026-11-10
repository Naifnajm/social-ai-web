import { useInfiniteQuery, useQueryClient } from '@tanstack/react-query';
import { useRouter, type Href } from 'expo-router';
import { useEffect, useState } from 'react';
import { FlatList, Pressable, RefreshControl, StyleSheet, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { Icon } from '@/components/icon';
import { ConvAvatar, IntentBadge } from '@/components/inbox-bits';
import { TAB_BAR_SPACE } from '@/components/tab-bar';
import { Backdrop, Badge, Chips, EmptyState, ErrorState, Input, Loading, PageHeader, Segmented, Txt } from '@/components/ui';
import { api } from '@/lib/api';
import { relativeTime } from '@/lib/format';
import { useI18n } from '@/lib/i18n';
import type { ConversationPage, ConversationRow } from '@/lib/types';
import { colors } from '@/theme';

type Folder = 'all' | 'mine' | 'unassigned' | 'pending' | 'done';
type Kind = '' | 'dm' | 'comment';

export default function InboxScreen() {
  const { t } = useI18n();
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const qc = useQueryClient();
  const [folder, setFolder] = useState<Folder>('all');
  const [kind, setKind] = useState<Kind>('');
  const [search, setSearch] = useState('');
  const [query, setQuery] = useState('');

  useEffect(() => {
    const id = setTimeout(() => setQuery(search.trim()), 350);
    return () => clearTimeout(id);
  }, [search]);

  const list = useInfiniteQuery({
    queryKey: ['conversations', folder, kind, query],
    queryFn: ({ pageParam }) =>
      api.get<ConversationPage>('/inbox/conversations', { folder, kind: kind || undefined, search: query || undefined, cursor: pageParam, limit: 30 }),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last) => last.next_cursor ?? undefined,
    refetchInterval: 30_000,
  });

  const items = list.data?.pages.flatMap((p) => p.items) ?? [];
  const counts = list.data?.pages[0]?.counts ?? {};
  const refresh = async () => {
    await Promise.all([list.refetch(), qc.invalidateQueries({ queryKey: ['inbox-unread'] })]);
  };

  return (
    <View style={{ flex: 1 }}>
      <Backdrop />
      <FlatList
        data={items}
        keyExtractor={(c) => String(c.id)}
        contentContainerStyle={{ paddingTop: insets.top + 8, paddingBottom: TAB_BAR_SPACE + insets.bottom }}
        refreshControl={<RefreshControl refreshing={list.isRefetching && !list.isFetchingNextPage} onRefresh={refresh} tintColor={colors.muted} />}
        onEndReached={() => list.hasNextPage && !list.isFetchingNextPage && list.fetchNextPage()}
        onEndReachedThreshold={0.4}
        keyboardShouldPersistTaps="handled"
        ListHeaderComponent={
          <View style={{ gap: 12, marginBottom: 8 }}>
            <PageHeader
              title={t('inbox.title')}
              subtitle={counts.unread ? t('inbox.unreadCount', { count: counts.unread }) : t('inbox.subtitle')}
            />
            <View style={{ paddingHorizontal: 16 }}>
              <View style={{ justifyContent: 'center' }}>
                <Input value={search} onChangeText={setSearch} placeholder={t('inbox.search')} style={{ paddingStart: 40 }} returnKeyType="search" />
                <View style={{ position: 'absolute', start: 13, pointerEvents: 'none' }}>
                  <Icon name="search" size={18} color={colors.faint} />
                </View>
              </View>
            </View>
            <Chips<Folder>
              value={folder}
              onChange={setFolder}
              options={[
                { value: 'all', label: t('inbox.folders.all'), count: counts.all },
                { value: 'mine', label: t('inbox.folders.mine'), count: counts.mine },
                { value: 'unassigned', label: t('inbox.folders.unassigned'), count: counts.unassigned },
                { value: 'pending', label: t('inbox.folders.pending'), count: counts.pending, icon: 'support_agent' },
                { value: 'done', label: t('inbox.folders.done') },
              ]}
            />
            <View style={{ paddingHorizontal: 16 }}>
              <Segmented<Kind>
                value={kind}
                onChange={setKind}
                options={[
                  { value: '', label: t('inbox.kinds.all') },
                  { value: 'dm', label: t('inbox.kinds.dm'), icon: 'chat' },
                  { value: 'comment', label: t('inbox.kinds.comment'), icon: 'mode_comment' },
                ]}
              />
            </View>
          </View>
        }
        ListEmptyComponent={
          list.isLoading ? <Loading /> : list.isError ? <ErrorState error={list.error} onRetry={() => list.refetch()} /> : (
            <EmptyState icon="inbox" title={query ? t('inbox.noResults') : t('inbox.emptyTitle')} text={query ? null : t('inbox.emptyText')} />
          )
        }
        ListFooterComponent={list.isFetchingNextPage ? <Loading style={{ paddingVertical: 20 }} /> : null}
        renderItem={({ item }) => <ConversationItem c={item} onPress={() => router.push(`/inbox/${item.id}` as Href)} />}
      />
    </View>
  );
}

function ConversationItem({ c, onPress }: { c: ConversationRow; onPress: () => void }) {
  const { t } = useI18n();
  return (
    <Pressable onPress={onPress} style={({ pressed }) => [styles.row, pressed && { backgroundColor: 'rgba(255,255,255,0.6)' }]}>
      <ConvAvatar name={c.name} src={c.avatar_url} platform={c.platform} />
      <View style={{ flex: 1, minWidth: 0, gap: 3 }}>
        <View style={styles.line}>
          <Txt weight={c.unread ? '800' : '600'} size={15} numberOfLines={1} style={{ flex: 1 }}>{c.name}</Txt>
          <Txt size={12} style={{ color: c.unread ? colors.ink : colors.faint, fontWeight: c.unread ? '700' : '400' }}>{relativeTime(c.last_message_at)}</Txt>
        </View>
        <View style={styles.line}>
          {c.kind === 'comment' ? <Icon name="mode_comment" size={14} color={colors.muted} /> : null}
          <Txt size={14} numberOfLines={1} style={{ flex: 1, color: c.unread ? colors.text : colors.muted }}>{c.snippet || '—'}</Txt>
          {c.unread ? <View style={styles.dot} /> : null}
        </View>
        <View style={[styles.line, { flexWrap: 'wrap' }]}>
          <Txt size={12} style={{ color: colors.faint }} numberOfLines={1}>{c.account_name}</Txt>
          {c.state === 'pending' ? <Badge tone="warn" icon="support_agent">{t('inbox.humanNeeded')}</Badge> : null}
          {c.has_suggestion ? <Badge tone="ink" icon="auto_awesome">{t('inbox.suggestionReady')}</Badge> : null}
          <IntentBadge intent={c.intent} />
          {c.assignee ? <Badge icon="person">{c.assignee.name}</Badge> : null}
          {c.is_hidden ? <Badge icon="visibility_off">{t('inbox.hidden')}</Badge> : null}
        </View>
      </View>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: 'row', gap: 12, paddingHorizontal: 16, paddingVertical: 12, marginHorizontal: 8, borderRadius: 18 },
  line: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  dot: { width: 9, height: 9, borderRadius: 5, backgroundColor: colors.ink },
});
