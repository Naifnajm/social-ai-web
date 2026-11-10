/** Pieces shared by Quick publish and the Studio composer: account picker, media strip, AI writer, results sheet. */
import { useMutation } from '@tanstack/react-query';
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, View } from 'react-native';
import * as WebBrowser from 'expo-web-browser';

import { api, errorText } from '@/lib/api';
import { formatDateTime } from '@/lib/format';
import { useI18n } from '@/lib/i18n';
import type { PostResult } from '@/lib/types';
import { colors, radius } from '@/theme';

import { Icon, PlatformBadge } from './icon';
import { AuthImage, Badge, Button, Card, Sheet, Txt, toast } from './ui';

export type PickAccount = { id: number; name: string; platform: string; state?: string; can_story?: boolean };

export function AccountPicker({ accounts, selected, onChange }: { accounts: PickAccount[]; selected: number[]; onChange: (ids: number[]) => void }) {
  const { t } = useI18n();
  if (!accounts.length) return <Txt muted size={13}>{t('publish.noAccounts')}</Txt>;
  return (
    <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 8 }}>
      {accounts.map((a) => {
        const on = selected.includes(a.id);
        const broken = a.state && a.state !== 'connected';
        return (
          <Pressable
            key={a.id}
            accessibilityRole="checkbox"
            accessibilityState={{ checked: on }}
            onPress={() => onChange(on ? selected.filter((x) => x !== a.id) : [...selected, a.id])}
            style={[styles.account, on && styles.accountOn, broken ? { opacity: 0.55 } : null]}>
            <PlatformBadge platform={a.platform} size={22} />
            <Txt size={13} weight="600" numberOfLines={1} style={{ maxWidth: 130, color: on ? '#fff' : colors.text }}>{a.name}</Txt>
            {on ? <Icon name="check" size={15} color="#fff" /> : null}
          </Pressable>
        );
      })}
    </View>
  );
}

export type Thumb = { id: number; mimetype: string; url?: string; local?: string };

export function MediaStrip({ items, onRemove, onAdd, busy, addLabel }: { items: Thumb[]; onRemove: (id: number) => void; onAdd?: { camera: () => void; library: () => void }; busy?: boolean; addLabel?: string }) {
  const { t } = useI18n();
  return (
    <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 8 }}>
      {onAdd ? (
        <>
          <Pressable onPress={onAdd.camera} style={styles.addTile} accessibilityRole="button" accessibilityLabel={t('media.camera')}>
            <Icon name="add_photo" size={24} color={colors.text2} />
            <Txt size={11} weight="600" style={{ color: colors.text2 }}>{t('media.camera')}</Txt>
          </Pressable>
          <Pressable onPress={onAdd.library} style={styles.addTile} accessibilityRole="button" accessibilityLabel={addLabel ?? t('media.gallery')}>
            {busy ? <ActivityIndicator color={colors.muted} /> : <Icon name="photo_library" size={24} color={colors.text2} />}
            <Txt size={11} weight="600" style={{ color: colors.text2 }}>{addLabel ?? t('media.gallery')}</Txt>
          </Pressable>
        </>
      ) : null}
      {items.map((m) => (
        <View key={m.id} style={styles.thumb}>
          {m.mimetype.startsWith('video/') ? (
            <View style={[StyleSheet.absoluteFill, { alignItems: 'center', justifyContent: 'center', backgroundColor: colors.fill2 }]}>
              <Icon name="movie" size={26} color={colors.text2} />
            </View>
          ) : (
            <AuthImage src={m.local || m.url || `/api/media/${m.id}/file`} style={StyleSheet.absoluteFill} />
          )}
          <Pressable onPress={() => onRemove(m.id)} style={styles.remove} accessibilityLabel={t('common.remove')} hitSlop={6}>
            <Icon name="close" size={13} color="#fff" />
          </Pressable>
        </View>
      ))}
    </ScrollView>
  );
}

/** "Write with AI" — `POST /api/ai/text` with the brief (or the current text) and the chosen accounts. */
export function AiWriteButton({ brief, accountIds, onText, disabled }: { brief: string; accountIds: number[]; onText: (text: string) => void; disabled?: boolean }) {
  const { t, locale } = useI18n();
  const write = useMutation({
    mutationFn: () =>
      api.post<{ text: string }>('/ai/text', {
        brief: brief || t('publish.aiDefaultBrief'),
        preset: 'post',
        length: 'short',
        account_ids: accountIds,
        hashtags: true,
        emojis: true,
        language: locale,
      }),
    onSuccess: (res) => {
      onText(res.text);
      toast.success(t('publish.aiDone'));
    },
    onError: (err) => toast.error(errorText(err)),
  });
  return (
    <Button size="sm" icon="wand_stars" loading={write.isPending} disabled={disabled} onPress={() => write.mutate()}>
      {t('publish.writeWithAi')}
    </Button>
  );
}

/** Outcome of a publish: per account state with links to the live posts. */
export function ResultsSheet({ result, onClose }: { result: { mode: string; posts: PostResult[] } | null; onClose: () => void }) {
  const { t } = useI18n();
  if (!result) return null;
  const failed = result.posts.some((p) => p.results.some((r) => r.state === 'failed' || r.story_state === 'failed'));
  const title = failed ? t('publish.result.partial') : result.mode === 'draft' ? t('publish.result.draft') : result.mode === 'now' ? t('publish.result.published') : t('publish.result.scheduled');
  return (
    <Sheet visible onClose={onClose} title={title} footer={<Button variant="primary" full style={{ flex: 1 }} onPress={onClose}>{t('common.done')}</Button>}>
      {result.posts.map((p) => (
        <Card key={p.id} style={{ gap: 8 }}>
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
            <Txt weight="700" style={{ flex: 1 }} numberOfLines={1}>{p.name}</Txt>
            <StateBadge state={p.state} />
          </View>
          {p.scheduled_at ? <Txt muted size={13}>{t('publish.scheduledFor', { date: formatDateTime(p.scheduled_at) })}</Txt> : null}
          {p.results.map((r) => (
            <Pressable key={`${p.id}-${r.account_id}`} disabled={!r.url} onPress={() => void WebBrowser.openBrowserAsync(r.url)} style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
              <PlatformBadge platform={r.platform} size={22} />
              <View style={{ flex: 1 }}>
                <Txt size={14} numberOfLines={1}>{r.account}</Txt>
                {r.error || r.story_error ? <Txt size={12} style={{ color: colors.bad }}>{r.error || r.story_error}</Txt> : null}
              </View>
              <StateBadge state={r.state} />
              {r.url ? <Icon name="open_in_new" size={15} color={colors.muted} /> : null}
            </Pressable>
          ))}
        </Card>
      ))}
    </Sheet>
  );
}

export function StateBadge({ state }: { state: string }) {
  const { t } = useI18n();
  const tone = ['posted', 'published', 'approved'].includes(state) ? 'ok' : ['failed', 'error', 'rejected'].includes(state) ? 'bad' : ['to_approve', 'partial', 'scheduled', 'publishing', 'pending'].includes(state) ? 'warn' : 'neutral';
  return <Badge tone={tone}>{t(`states.${state}`)}</Badge>;
}

const styles = StyleSheet.create({
  account: { flexDirection: 'row', alignItems: 'center', gap: 7, paddingStart: 6, paddingEnd: 12, height: 36, borderRadius: radius.pill, backgroundColor: 'rgba(255,255,255,0.85)', borderWidth: 1, borderColor: colors.line },
  accountOn: { backgroundColor: colors.ink, borderColor: colors.ink },
  addTile: { width: 84, height: 84, borderRadius: 16, backgroundColor: 'rgba(255,255,255,0.8)', borderWidth: 1, borderStyle: 'dashed', borderColor: colors.lineStrong, alignItems: 'center', justifyContent: 'center', gap: 4 },
  thumb: { width: 84, height: 84, borderRadius: 16, overflow: 'hidden', backgroundColor: colors.fill2 },
  remove: { position: 'absolute', top: 5, end: 5, width: 22, height: 22, borderRadius: 11, backgroundColor: 'rgba(0,0,0,0.6)', alignItems: 'center', justifyContent: 'center' },
});
