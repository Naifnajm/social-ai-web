/** Post detail: content, media, per-network results; approve / request changes (approvers), publish, retry, delete. */
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useLocalSearchParams, useRouter, type Href } from 'expo-router';
import * as WebBrowser from 'expo-web-browser';
import { useState } from 'react';
import { Alert, Platform, Pressable, RefreshControl, ScrollView, StyleSheet, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { Icon, PlatformBadge } from '@/components/icon';
import { StateBadge } from '@/components/publishing';
import { AuthImage, Backdrop, Button, Card, ErrorState, Field, Input, Loading, SectionTitle, Sheet, StackHeader, Txt, toast } from '@/components/ui';
import { api, errorText } from '@/lib/api';
import { compact, formatDateTime, tap } from '@/lib/format';
import { t as translate, useI18n } from '@/lib/i18n';
import { useSession } from '@/lib/session';
import type { Post } from '@/lib/types';
import { colors, radius } from '@/theme';

function confirm(title: string, message: string, ok: string, onOk: () => void) {
  if (Platform.OS === 'web') {
    if (window.confirm(`${title}\n\n${message}`)) onOk();
    return;
  }
  Alert.alert(title, message, [
    { text: translate('common.cancel'), style: 'cancel' },
    { text: ok, style: 'destructive', onPress: onOk },
  ]);
}

export default function PostScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { t } = useI18n();
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const qc = useQueryClient();
  const { can } = useSession();
  const post = useQuery({ queryKey: ['post', id], queryFn: () => api.get<Post>(`/posts/${id}`) });
  const [busy, setBusy] = useState<string | null>(null);
  const [changesOpen, setChangesOpen] = useState(false);
  const [note, setNote] = useState('');

  const run = async (key: string, action: () => Promise<Post | void>, done: string) => {
    setBusy(key);
    try {
      const next = await action();
      if (next) qc.setQueryData(['post', id], next);
      void qc.invalidateQueries({ queryKey: ['planner'] });
      void qc.invalidateQueries({ queryKey: ['approvals'] });
      toast.success(done);
      return true;
    } catch (err) {
      toast.error(errorText(err));
      return false;
    } finally {
      setBusy(null);
    }
  };

  const p = post.data;
  if (!p) {
    return (
      <View style={{ flex: 1 }}>
        <Backdrop />
        <StackHeader title={t('post.title')} />
        {post.isError ? <ErrorState error={post.error} onRetry={() => post.refetch()} /> : <Loading />}
      </View>
    );
  }

  const toApprove = p.state === 'to_approve';
  const media = [...(p.media ?? []), ...(p.story_media ?? [])];
  const approve = () => run('approve', () => api.post<Post>(`/posts/${p.id}/approve`), t('post.approved'));
  const requestChanges = async () => {
    if (await run('changes', () => api.post<Post>(`/posts/${p.id}/request-changes`, { note: note.trim() || null }), t('post.changesRequested'))) {
      setChangesOpen(false);
      setNote('');
    }
  };
  const publishNow = () =>
    confirm(t('post.publishNowTitle'), t('post.publishNowText'), t('post.publishNow'), () =>
      void run('publish', () => api.post<Post>(`/posts/${p.id}/submit`, { action: 'publish' }), t('post.sent')),
    );
  const retry = () => run('retry', () => api.post<Post>(`/posts/${p.id}/retry`), t('post.retried'));
  const remove = () =>
    confirm(t('post.deleteTitle'), t('post.deleteText'), t('common.delete'), async () => {
      if (await run('delete', () => api.delete(`/posts/${p.id}`), t('post.deleted'))) router.back();
    });

  return (
    <View style={{ flex: 1 }}>
      <Backdrop />
      <StackHeader title={p.name || t('post.untitled')} subtitle={p.author_name ? t('post.by', { name: p.author_name }) : null} />
      <ScrollView
        contentContainerStyle={{ padding: 16, gap: 14, paddingBottom: insets.bottom + (toApprove && can('approver') ? 110 : 30) }}
        refreshControl={<RefreshControl refreshing={post.isRefetching} onRefresh={() => post.refetch()} tintColor={colors.muted} />}>
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          <StateBadge state={p.state} />
          {p.scheduled_at ? <Txt muted size={13}>{t('post.scheduledFor', { date: formatDateTime(p.scheduled_at) })}</Txt> : null}
          {p.published_at ? <Txt muted size={13}>{t('post.publishedAt', { date: formatDateTime(p.published_at) })}</Txt> : null}
        </View>

        {toApprove ? (
          <Card style={{ gap: 6, backgroundColor: 'rgba(255,159,10,0.12)' }}>
            <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
              <Icon name="verified_user" size={18} color={colors.warn} />
              <Txt weight="700" style={{ color: colors.warn }}>{t('post.waitingApproval')}</Txt>
            </View>
            {p.approval_requested_by_name ? (
              <Txt size={13} style={{ color: colors.warn }}>
                {t('post.requestedBy', { name: p.approval_requested_by_name, date: p.approval_requested_at ? formatDateTime(p.approval_requested_at) : '' })}
              </Txt>
            ) : null}
            {p.requested_action ? <Txt size={13} style={{ color: colors.warn }}>{t(`post.requested.${p.requested_action}`)}</Txt> : null}
          </Card>
        ) : null}
        {p.approval_note && !toApprove ? (
          <Card style={{ gap: 4 }}>
            <SectionTitle icon="mode_comment">{t('post.approverNote')}</SectionTitle>
            <Txt size={14}>{p.approval_note}</Txt>
          </Card>
        ) : null}

        {media.length ? (
          <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 10 }}>
            {media.map((m) => (
              <View key={m.id} style={styles.media}>
                {m.mimetype.startsWith('image/') ? <AuthImage src={m.url || `/api/media/${m.id}/file`} style={StyleSheet.absoluteFill} /> : (
                  <View style={[StyleSheet.absoluteFill, { alignItems: 'center', justifyContent: 'center' }]}><Icon name="play_circle" size={40} color={colors.text2} /></View>
                )}
              </View>
            ))}
          </ScrollView>
        ) : null}

        <Card>
          <SectionTitle icon="text_fields">{t('post.content')}</SectionTitle>
          <Txt size={15} style={{ lineHeight: 23 }} selectable>{p.content || t('post.noContent')}</Txt>
        </Card>

        <Card padded={false}>
          <View style={{ padding: 16, paddingBottom: 6 }}><SectionTitle icon="share">{t('post.networks')}</SectionTitle></View>
          {(p.targets?.length ? p.targets : (p.accounts ?? []).map((a) => ({ id: -a.id, account_id: a.id, account_name: a.name, platform: a.platform, state: p.state } as NonNullable<Post['targets']>[number]))).map((tg, i, all) => (
            <Pressable
              key={tg.id}
              disabled={!tg.external_url}
              onPress={() => tg.external_url && void WebBrowser.openBrowserAsync(tg.external_url)}
              style={[styles.target, i < all.length - 1 && styles.targetLine]}>
              <PlatformBadge platform={tg.platform} size={30} />
              <View style={{ flex: 1, minWidth: 0, gap: 2 }}>
                <Txt weight="600" numberOfLines={1}>{tg.account_name}</Txt>
                {tg.error || tg.story_error ? <Txt size={12} style={{ color: colors.bad }} numberOfLines={3}>{tg.error || tg.story_error}</Txt> : null}
                {tg.state === 'posted' && (tg.impressions || tg.engagements) ? (
                  <View style={{ flexDirection: 'row', gap: 12 }}>
                    <Metric icon="visibility" value={tg.impressions} />
                    <Metric icon="favorite" value={tg.likes} />
                    <Metric icon="mode_comment" value={tg.comments} />
                    <Metric icon="share" value={tg.shares} />
                  </View>
                ) : null}
              </View>
              <StateBadge state={tg.state} />
              {tg.external_url ? <Icon name="open_in_new" size={15} color={colors.muted} /> : null}
            </Pressable>
          ))}
        </Card>

        {can('editor') ? (
          <View style={{ gap: 10 }}>
            {p.state === 'draft' ? <Button variant="primary" icon="send" loading={busy === 'publish'} onPress={publishNow} full>{t('post.publishNow')}</Button> : null}
            {p.can_retry ? <Button icon="refresh" loading={busy === 'retry'} onPress={retry} full>{t('post.retry')}</Button> : null}
            {['draft', 'to_approve', 'scheduled', 'failed'].includes(p.state) ? (
              <Button variant="ghost" icon="delete" loading={busy === 'delete'} onPress={remove} full>{t('common.delete')}</Button>
            ) : null}
            <Button variant="ghost" icon="content_copy" onPress={async () => {
              try {
                const copy = await api.post<Post>(`/posts/${p.id}/duplicate`);
                tap('success');
                router.replace(`/post/${copy.id}` as Href);
              } catch (err) {
                toast.error(errorText(err));
              }
            }} full>{t('post.duplicate')}</Button>
          </View>
        ) : null}
      </ScrollView>

      {toApprove && can('approver') ? (
        <View style={[styles.approveBar, { paddingBottom: Math.max(insets.bottom, 12) }]}>
          <Button style={{ flex: 1 }} icon="undo" onPress={() => setChangesOpen(true)}>{t('post.requestChanges')}</Button>
          <Button style={{ flex: 1 }} variant="primary" icon="check" loading={busy === 'approve'} onPress={approve}>{t('post.approve')}</Button>
        </View>
      ) : null}

      <Sheet
        visible={changesOpen}
        onClose={() => setChangesOpen(false)}
        title={t('post.requestChanges')}
        footer={<Button variant="primary" style={{ flex: 1 }} loading={busy === 'changes'} onPress={requestChanges}>{t('post.sendRequest')}</Button>}>
        <Field label={t('post.changesNote')} hint={t('post.changesHint')}>
          <Input multiline value={note} onChangeText={setNote} autoFocus placeholder={t('post.changesPlaceholder')} />
        </Field>
      </Sheet>
    </View>
  );
}

function Metric({ icon, value }: { icon: string; value?: number }) {
  return (
    <View style={{ flexDirection: 'row', alignItems: 'center', gap: 3 }}>
      <Icon name={icon} size={13} color={colors.muted} />
      <Txt size={12} muted>{compact(value)}</Txt>
    </View>
  );
}

const styles = StyleSheet.create({
  media: { width: 220, height: 275, borderRadius: radius.lg, overflow: 'hidden', backgroundColor: colors.fill2 },
  target: { flexDirection: 'row', alignItems: 'center', gap: 10, paddingHorizontal: 16, paddingVertical: 12 },
  targetLine: { borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.line },
  approveBar: { position: 'absolute', start: 0, end: 0, bottom: 0, flexDirection: 'row', gap: 10, paddingHorizontal: 16, paddingTop: 12, backgroundColor: 'rgba(255,255,255,0.92)', borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: colors.line },
});
