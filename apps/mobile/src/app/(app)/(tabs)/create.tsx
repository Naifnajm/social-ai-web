/** Quick publish: camera / gallery → brand template set → live framed preview → caption (+AI) → accounts → publish. */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useRouter } from 'expo-router';
import { type ReactNode, useEffect, useMemo, useRef, useState } from 'react';
import { ActivityIndicator, KeyboardAvoidingView, Platform, Pressable, RefreshControl, ScrollView, StyleSheet, View, useWindowDimensions } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { Image } from 'expo-image';

import { Icon } from '@/components/icon';
import { AccountPicker, AiWriteButton, MediaStrip, ResultsSheet, type Thumb } from '@/components/publishing';
import { TAB_BAR_SPACE } from '@/components/tab-bar';
import { AuthImage, Backdrop, Badge, Button, Card, EmptyState, ErrorState, Field, Input, Loading, PageHeader, SectionTitle, Segmented, Txt, toast } from '@/components/ui';
import { api, errorText } from '@/lib/api';
import { formatDateTime, tap } from '@/lib/format';
import { useI18n } from '@/lib/i18n';
import { pickMedia, uploadAsset } from '@/lib/media';
import type { Choice, PostResult, QuickData, QuickPreview } from '@/lib/types';
import { colors, radius } from '@/theme';

type PublishAs = 'feed' | 'story' | 'feed_story';
type When = 'now' | 'best_time';

export default function CreateScreen() {
  const { t } = useI18n();
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const qc = useQueryClient();
  const { width } = useWindowDimensions();
  const data = useQuery({ queryKey: ['quick-data'], queryFn: () => api.get<QuickData>('/templates/quick') });

  const [files, setFiles] = useState<Thumb[]>([]);
  const [uploading, setUploading] = useState(false);
  const [choiceKey, setChoiceKey] = useState<string | null>(null);
  const [text, setText] = useState('');
  const [content, setContent] = useState('');
  const [accountIds, setAccountIds] = useState<number[] | null>(null);
  const [publishAs, setPublishAs] = useState<PublishAs>('feed_story');
  const [when, setWhen] = useState<When>('now');
  const [result, setResult] = useState<{ mode: string; posts: PostResult[] } | null>(null);

  const d = data.data;
  const choices = useMemo(() => d?.choices ?? [], [d]);
  const current: Choice | undefined = choices.find((c) => c.key === choiceKey) ?? choices[0];
  const accounts = useMemo(() => (d?.accounts ?? []).filter((a) => a.platform !== 'whatsapp'), [d]);
  const selected = accountIds ?? accounts.filter((a) => a.state === 'connected').map((a) => a.id);
  const roles = new Set(current?.templates.map((x) => x.role));
  const textTemplate = current?.templates.find((x) => x.text_enabled);

  const chooseSet = (c: Choice) => {
    tap();
    setChoiceKey(c.key);
    const r = new Set(c.templates.map((x) => x.role));
    if (r.size === 1) setPublishAs(r.has('story') ? 'story' : 'feed');
    else setPublishAs('feed_story');
  };

  // ------------------------------------------------------------ media
  const add = async (source: 'camera' | 'library') => {
    const assets = await pickMedia(source);
    if (!assets.length) return;
    setUploading(true);
    try {
      for (const asset of assets) {
        try {
          const media = await uploadAsset(asset);
          setFiles((f) => [...f, { id: media.id, mimetype: media.mimetype, url: media.thumb_url || media.url, local: asset.uri }]);
        } catch (err) {
          toast.error(errorText(err));
        }
      }
    } finally {
      setUploading(false);
    }
  };

  // ------------------------------------------------------------ live preview (debounced)
  const [previews, setPreviews] = useState<QuickPreview[]>([]);
  const [previewBusy, setPreviewBusy] = useState(false);
  const seq = useRef(0);
  const previewKey = current && files.length ? JSON.stringify([current.key, files.map((f) => f.id), text]) : '';
  useEffect(() => {
    if (!previewKey) return;
    const mine = ++seq.current;
    const [choice, mediaIds, value] = JSON.parse(previewKey) as [string, number[], string];
    const timer = setTimeout(async () => {
      setPreviewBusy(true);
      try {
        const res = await api.post<QuickPreview[]>('/templates/quick/preview', { choice, media_ids: mediaIds, text: value || null });
        if (mine === seq.current) setPreviews(res);
      } catch (err) {
        if (mine === seq.current) toast.error(errorText(err));
      } finally {
        if (mine === seq.current) setPreviewBusy(false);
      }
    }, value ? 500 : 150);
    return () => clearTimeout(timer);
  }, [previewKey]);
  const shown = previewKey ? previews.filter((p) => files.some((f) => f.id === p.media_id)) : [];
  const previewItems = shown.flatMap((p) =>
    p.items.filter((it) => publishAs === 'feed_story' || (publishAs === 'feed' ? it.role === 'post' : it.role === 'story')).map((it) => ({ ...it, media: p.media_id, error: p.error })),
  );

  // ------------------------------------------------------------ publish
  const publish = useMutation({
    mutationFn: (mode: 'draft' | When) =>
      api.post<{ mode: string; posts: PostResult[] }>('/templates/quick/publish', {
        choice: current!.key,
        media_ids: files.map((f) => f.id),
        text: text || null,
        content,
        account_ids: selected,
        publish_as: publishAs,
        grouping: 'single',
        mode,
      }),
    onSuccess: (res) => {
      tap('success');
      setResult(res);
      void qc.invalidateQueries({ queryKey: ['planner'] });
      void qc.invalidateQueries({ queryKey: ['posts'] });
    },
    onError: (err) => toast.error(errorText(err)),
  });
  const reset = () => {
    setResult(null);
    setFiles([]);
    setPreviews([]);
    setContent('');
    setText('');
    void qc.invalidateQueries({ queryKey: ['quick-data'] });
  };

  const header = <PageHeader title={t('quick.title')} subtitle={t('quick.subtitle')} />;
  const scrollProps = {
    contentContainerStyle: { paddingTop: insets.top + 8, paddingBottom: TAB_BAR_SPACE + insets.bottom + 20 },
    refreshControl: <RefreshControl refreshing={data.isRefetching} onRefresh={() => void data.refetch()} tintColor={colors.muted} />,
  };

  if (!d) {
    return (
      <View style={{ flex: 1 }}>
        <Backdrop />
        <ScrollView {...scrollProps}>{header}{data.isError ? <ErrorState error={data.error} onRetry={() => data.refetch()} /> : <Loading />}</ScrollView>
      </View>
    );
  }

  const noStory = publishAs !== 'feed' ? accounts.filter((a) => selected.includes(a.id) && !a.can_story) : [];
  const canSubmit = !!files.length && !!current && !publish.isPending && !uploading;
  const canPublish = canSubmit && selected.length > 0;
  const bestSlot = d.best_slots[0];
  const previewWidth = Math.min(width - 72, 300);

  return (
    <View style={{ flex: 1 }}>
      <Backdrop />
      <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
        <ScrollView {...scrollProps} keyboardShouldPersistTaps="handled">
          {header}
          {!choices.length ? (
            <Card style={{ marginHorizontal: 16 }}>
              <EmptyState
                icon="photo_frame"
                title={t('quick.noTemplatesTitle')}
                text={t('quick.noTemplatesText')}
                action={<Button icon="edit_square" onPress={() => router.push('/compose')}>{t('quick.useStudio')}</Button>}
              />
            </Card>
          ) : (
            <View style={{ gap: 14, paddingHorizontal: 16 }}>
              {/* 1 · photos */}
              <Card style={{ gap: 12 }}>
                <Step n={1} title={t('quick.photos')} aside={files.length ? t('quick.selected', { count: files.length }) : undefined} />
                <MediaStrip
                  items={files}
                  busy={uploading}
                  onRemove={(id) => setFiles((all) => all.filter((x) => x.id !== id))}
                  onAdd={{ camera: () => void add('camera'), library: () => void add('library') }}
                />
                {d.recent.length ? (
                  <View style={{ gap: 6 }}>
                    <Txt size={12} muted>{t('quick.recent')}</Txt>
                    <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 6 }}>
                      {d.recent.filter((m) => m.mimetype.startsWith('image/')).slice(0, 20).map((m) => {
                        const on = files.some((f) => f.id === m.id);
                        return (
                          <Pressable
                            key={m.id}
                            onPress={() => setFiles((f) => (on ? f.filter((x) => x.id !== m.id) : [...f, { id: m.id, mimetype: m.mimetype, url: m.thumb_url || m.url }]))}
                            style={[styles.recent, on && { borderColor: colors.ink, borderWidth: 2 }]}>
                            <AuthImage src={m.thumb_url || m.url} style={StyleSheet.absoluteFill} />
                            {on ? <View style={styles.recentCheck}><Icon name="check" size={12} color="#fff" /></View> : null}
                          </Pressable>
                        );
                      })}
                    </ScrollView>
                  </View>
                ) : null}
              </Card>

              {/* 2 · template set */}
              <Card style={{ gap: 12 }}>
                <Step n={2} title={t('quick.design')} />
                <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 10 }}>
                  {choices.map((c) => {
                    const on = current?.key === c.key;
                    const first = c.templates[0];
                    return (
                      <Pressable key={c.key} onPress={() => chooseSet(c)} style={[styles.choice, on && styles.choiceOn]}>
                        <View style={styles.choiceImg}>
                          {first ? <AuthImage src={first.preview_url} style={StyleSheet.absoluteFill} contentFit="contain" /> : null}
                        </View>
                        <Txt size={13} weight="700" numberOfLines={1}>{c.name}</Txt>
                        <View style={{ flexDirection: 'row', gap: 4 }}>
                          {Array.from(new Set(c.templates.map((x) => x.role))).map((r) => <Badge key={r}>{t(`quick.role.${r}`)}</Badge>)}
                        </View>
                      </Pressable>
                    );
                  })}
                </ScrollView>
                {textTemplate ? (
                  <Field label={t('quick.textOnDesign')} hint={t('quick.textOnDesignHint')}>
                    <Input value={text} onChangeText={setText} placeholder={textTemplate.text_default || t('quick.textPlaceholder')} />
                  </Field>
                ) : null}
              </Card>

              {/* live preview */}
              {files.length ? (
                <Card style={{ gap: 10 }}>
                  <SectionTitle icon="visibility" actions={previewBusy ? <ActivityIndicator size="small" color={colors.muted} /> : null}>{t('quick.preview')}</SectionTitle>
                  {previewItems.length ? (
                    <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 12 }}>
                      {previewItems.map((it, i) => {
                        const [w, h] = it.aspect.split(':').map(Number);
                        const ratio = w && h ? w / h : 4 / 5;
                        const pw = it.role === 'story' ? previewWidth * 0.62 : previewWidth;
                        return (
                          <View key={`${it.media}-${it.template_id}-${i}`} style={{ gap: 6 }}>
                            <Image source={{ uri: it.src }} style={{ width: pw, height: pw / ratio, borderRadius: 14, backgroundColor: colors.fill2 }} contentFit="cover" />
                            <Badge icon={it.role === 'story' ? 'smartphone' : 'image'}>{t(`quick.role.${it.role}`)}</Badge>
                          </View>
                        );
                      })}
                    </ScrollView>
                  ) : previewBusy ? (
                    <Loading style={{ paddingVertical: 30 }} />
                  ) : (
                    <Txt muted size={13}>{shown.find((p) => p.error)?.error || t('quick.previewEmpty')}</Txt>
                  )}
                  {shown.some((p) => p.video) ? <Txt muted size={12}>{t('quick.videoNote')}</Txt> : null}
                </Card>
              ) : null}

              {/* 3 · caption */}
              <Card style={{ gap: 10 }}>
                <Step n={3} title={t('quick.caption')} aside={d.has_ai ? <AiWriteButton brief={content || text || current?.name || ''} accountIds={selected} onText={setContent} /> : undefined} />
                <Input multiline value={content} onChangeText={setContent} placeholder={t('quick.captionPlaceholder')} style={{ minHeight: 110 }} />
                <Txt size={11} style={{ color: colors.faint, alignSelf: 'flex-end' }}>{content.length}</Txt>
              </Card>

              {/* 4 · accounts + format */}
              <Card style={{ gap: 12 }}>
                <Step n={4} title={t('quick.where')} />
                <AccountPicker accounts={accounts} selected={selected} onChange={setAccountIds} />
                {roles.size > 1 ? (
                  <Segmented<PublishAs>
                    value={publishAs}
                    onChange={setPublishAs}
                    options={[
                      { value: 'feed', label: t('quick.as.feed') },
                      { value: 'story', label: t('quick.as.story') },
                      { value: 'feed_story', label: t('quick.as.both') },
                    ]}
                  />
                ) : null}
                {noStory.length ? (
                  <View style={styles.note}>
                    <Icon name="info" size={15} color={colors.warn} />
                    <Txt size={12} style={{ color: colors.warn, flex: 1 }}>{t('quick.noStory', { names: noStory.map((a) => a.name).join('، ') })}</Txt>
                  </View>
                ) : null}
              </Card>

              {/* 5 · when */}
              <Card style={{ gap: 12 }}>
                <Step n={5} title={t('quick.when')} />
                <Segmented<When>
                  value={when}
                  onChange={setWhen}
                  options={[
                    { value: 'now', label: t('quick.now'), icon: 'send' },
                    { value: 'best_time', label: t('quick.bestTime'), icon: 'schedule' },
                  ]}
                />
                {when === 'best_time' && bestSlot ? <Txt muted size={13}>{t('quick.bestSlot', { date: bestSlot.label || formatDateTime(bestSlot.at) })}</Txt> : null}
                <View style={{ flexDirection: 'row', gap: 10 }}>
                  <Button style={{ flex: 1 }} icon="save" disabled={!canSubmit} loading={publish.isPending && publish.variables === 'draft'} onPress={() => publish.mutate('draft')}>
                    {t('quick.saveDraft')}
                  </Button>
                  <Button style={{ flex: 1.4 }} variant="primary" icon={when === 'now' ? 'send' : 'schedule'} disabled={!canPublish} loading={publish.isPending && publish.variables !== 'draft'} onPress={() => publish.mutate(when)}>
                    {when === 'now' ? t('quick.publishNow') : t('quick.scheduleBest')}
                  </Button>
                </View>
                {!files.length ? <Txt muted size={12} style={{ textAlign: 'center' }}>{t('quick.needPhoto')}</Txt> : null}
              </Card>
            </View>
          )}
        </ScrollView>
      </KeyboardAvoidingView>
      <ResultsSheet result={result} onClose={reset} />
    </View>
  );
}

function Step({ n, title, aside }: { n: number; title: string; aside?: ReactNode }) {
  return (
    <View style={{ flexDirection: 'row', alignItems: 'center', gap: 10 }}>
      <View style={styles.step}><Txt size={12} weight="800" style={{ color: '#fff' }}>{n}</Txt></View>
      <Txt weight="700" size={16} style={{ flex: 1 }}>{title}</Txt>
      {typeof aside === 'string' ? <Txt muted size={12}>{aside}</Txt> : aside}
    </View>
  );
}

const styles = StyleSheet.create({
  step: { width: 24, height: 24, borderRadius: 12, backgroundColor: colors.ink, alignItems: 'center', justifyContent: 'center' },
  recent: { width: 56, height: 56, borderRadius: 12, overflow: 'hidden', backgroundColor: colors.fill2, borderWidth: 1, borderColor: colors.line },
  recentCheck: { position: 'absolute', top: 3, end: 3, width: 18, height: 18, borderRadius: 9, backgroundColor: colors.ink, alignItems: 'center', justifyContent: 'center' },
  choice: { width: 128, gap: 6, padding: 8, borderRadius: radius.md, backgroundColor: 'rgba(255,255,255,0.7)', borderWidth: 1.5, borderColor: colors.line },
  choiceOn: { borderColor: colors.ink, backgroundColor: '#fff' },
  choiceImg: { width: '100%', height: 120, borderRadius: 10, overflow: 'hidden', backgroundColor: colors.fill2 },
  note: { flexDirection: 'row', gap: 6, alignItems: 'center', backgroundColor: colors.warnBg, borderRadius: 12, padding: 10 },
});
