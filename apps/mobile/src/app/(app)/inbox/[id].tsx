import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useLocalSearchParams } from 'expo-router';
import * as WebBrowser from 'expo-web-browser';
import { useMemo, useRef, useState } from 'react';
import { KeyboardAvoidingView, Platform, Pressable, ScrollView, StyleSheet, TextInput, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { Icon } from '@/components/icon';
import { ConvAvatar, IntentBadge, SentimentBadge } from '@/components/inbox-bits';
import {
  AuthImage,
  Backdrop,
  Badge,
  Button,
  Card,
  ErrorState,
  Field,
  IconButton,
  Input,
  ListRow,
  Loading,
  Segmented,
  Sheet,
  StackHeader,
  Txt,
  toast,
} from '@/components/ui';
import { api, errorText } from '@/lib/api';
import { formatDate, formatTime, tap } from '@/lib/format';
import { useI18n } from '@/lib/i18n';
import type { Canned, Contact, InboxMeta, Message, Thread } from '@/lib/types';
import { colors, radius } from '@/theme';

type SendResult = { message: Message; thread: Thread };

export default function ThreadScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { t } = useI18n();
  const qc = useQueryClient();
  const insets = useSafeAreaInsets();
  const thread = useQuery({ queryKey: ['thread', id], queryFn: () => api.get<Thread>(`/inbox/conversations/${id}`) });
  const meta = useQuery({ queryKey: ['inbox-meta'], queryFn: () => api.get<InboxMeta>('/inbox/meta'), staleTime: 300_000 });
  const [busy, setBusy] = useState<string | null>(null);
  const [infoOpen, setInfoOpen] = useState(false);
  const [actionsOpen, setActionsOpen] = useState(false);
  const scroller = useRef<ScrollView>(null);

  const update = (next: Thread) => {
    qc.setQueryData(['thread', id], next);
    void qc.invalidateQueries({ queryKey: ['conversations'] });
    void qc.invalidateQueries({ queryKey: ['inbox-unread'] });
  };
  const run = async (key: string, action: () => Promise<Thread | void>, done?: string) => {
    setBusy(key);
    try {
      const result = await action();
      if (result) update(result);
      if (done) toast.success(done);
    } catch (err) {
      toast.error(errorText(err));
    } finally {
      setBusy(null);
    }
  };

  const th = thread.data;
  const m = meta.data;
  const groups = useMemo(() => {
    const out: { day: string; label: string; messages: Message[] }[] = [];
    for (const msg of th?.messages ?? []) {
      const date = new Date(msg.sent_at);
      const day = date.toDateString();
      let group = out[out.length - 1];
      if (!group || group.day !== day) {
        group = { day, label: formatDate(date, { weekday: 'long', day: 'numeric', month: 'long' }), messages: [] };
        out.push(group);
      }
      group.messages.push(msg);
    }
    return out;
  }, [th?.messages]);

  if (!th || !m) {
    return (
      <View style={{ flex: 1 }}>
        <Backdrop />
        <StackHeader title={t('inbox.title')} />
        {thread.isError || meta.isError ? <ErrorState error={thread.error || meta.error} onRetry={() => { void thread.refetch(); void meta.refetch(); }} /> : <Loading />}
      </View>
    );
  }

  const setState = (state: 'open' | 'done') =>
    run('state', () => api.patch<Thread>(`/inbox/conversations/${th.id}`, { state }), state === 'done' ? t('inbox.markedDone') : undefined);
  const assignMe = () => run('assign', () => api.patch<Thread>(`/inbox/conversations/${th.id}`, { assignee_id: th.assignee?.id === m.user_id ? null : m.user_id }));
  const hide = () => run('hide', () => api.post<Thread>(`/inbox/conversations/${th.id}/hide`, { hide: !th.is_hidden }));
  const like = () => run('like', async () => { await api.post(`/inbox/conversations/${th.id}/like`); }, t('inbox.liked'));
  const markUnread = () =>
    run('unread', async () => {
      await api.post(`/inbox/conversations/${th.id}/unread`);
      void qc.invalidateQueries({ queryKey: ['conversations'] });
      void qc.invalidateQueries({ queryKey: ['inbox-unread'] });
    }, t('inbox.markedUnread'));
  const togglePause = () => run('pause', () => api.patch<Thread>(`/inbox/conversations/${th.id}`, { bot_paused: !th.bot_paused }));

  return (
    <View style={{ flex: 1 }}>
      <Backdrop />
      <StackHeader
        actions={
          <>
            {m.can_reply && th.state !== 'done' ? (
              <Button size="sm" variant="primary" icon="check" loading={busy === 'state'} onPress={() => setState('done')}>{t('inbox.done')}</Button>
            ) : m.can_reply ? (
              <Button size="sm" icon="undo" loading={busy === 'state'} onPress={() => setState('open')}>{t('inbox.reopen')}</Button>
            ) : null}
            <IconButton icon="menu_book" label={t('inbox.actions')} onPress={() => setActionsOpen(true)} />
          </>
        }>
        <Pressable onPress={() => setInfoOpen(true)} style={{ flex: 1, minWidth: 0, flexDirection: 'row', alignItems: 'center', gap: 10 }} accessibilityRole="button">
          <ConvAvatar name={th.name} src={th.avatar_url} platform={th.platform} size={36} />
          <View style={{ flex: 1, minWidth: 0 }}>
            <Txt weight="700" size={15} numberOfLines={1}>{th.name}</Txt>
            <Txt muted size={12} numberOfLines={1}>{t(th.kind === 'comment' ? 'inbox.kinds.commentOne' : 'inbox.kinds.dmOne')} · {th.account_name}</Txt>
          </View>
        </Pressable>
      </StackHeader>

      <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
        <ScrollView
          ref={scroller}
          style={{ flex: 1 }}
          contentContainerStyle={{ padding: 12, paddingBottom: 16 }}
          onContentSizeChange={() => scroller.current?.scrollToEnd({ animated: false })}
          keyboardShouldPersistTaps="handled">
          {th.post && (th.post.preview || th.post.url) ? (
            <Pressable onPress={() => th.post?.url && void WebBrowser.openBrowserAsync(th.post.url)} style={styles.banner}>
              <Icon name="campaign" size={18} color={colors.text2} />
              <View style={{ flex: 1 }}>
                <Txt muted size={11}>{t('inbox.onYourPost')}</Txt>
                <Txt size={13} numberOfLines={2}>{th.post.preview || th.post.url}</Txt>
              </View>
              {th.post.url ? <Icon name="open_in_new" size={15} color={colors.muted} /> : null}
            </Pressable>
          ) : null}
          {th.state === 'pending' ? (
            <View style={[styles.banner, { backgroundColor: colors.warnBg }]}>
              <Icon name="support_agent" size={18} color={colors.warn} />
              <Txt size={13} style={{ color: colors.warn, flex: 1 }}>
                <Txt size={13} weight="700" style={{ color: colors.warn }}>{t('inbox.humanNeeded')} </Txt>
                {th.handover_reason || ''}
              </Txt>
            </View>
          ) : null}
          {th.bot_error ? (
            <View style={[styles.banner, { backgroundColor: colors.badBg }]}>
              <Icon name="error" size={18} color={colors.bad} />
              <Txt size={13} style={{ color: colors.bad, flex: 1 }}>{t('inbox.assistantError')} {th.bot_error}</Txt>
            </View>
          ) : null}
          {groups.map((group) => (
            <View key={group.day}>
              <View style={{ alignItems: 'center', marginVertical: 10 }}>
                <View style={styles.dayPill}><Txt size={11} weight="600" muted>{group.label}</Txt></View>
              </View>
              {group.messages.map((msg) => <Bubble key={msg.id} m={msg} kind={th.kind} />)}
            </View>
          ))}
        </ScrollView>

        {th.suggestion && m.can_reply ? <SuggestionCard key={th.suggestion.id} thread={th} onChanged={update} /> : null}
        {m.can_reply ? (
          <Composer key={th.id} thread={th} meta={m} onChanged={update} bottomInset={insets.bottom} />
        ) : (
          <View style={{ padding: 12, paddingBottom: insets.bottom + 12, alignItems: 'center' }}>
            <Txt muted size={12}>{t('inbox.readOnly')}</Txt>
          </View>
        )}
      </KeyboardAvoidingView>

      <Sheet visible={actionsOpen} onClose={() => setActionsOpen(false)} title={t('inbox.actions')}>
        <Card padded={false}>
          <ListRow icon="person" title={th.assignee?.id === m.user_id ? t('inbox.unassignMe') : t('inbox.assignMe')} subtitle={th.assignee ? t('inbox.assignedTo', { name: th.assignee.name }) : t('inbox.unassigned')} onPress={() => { setActionsOpen(false); void assignMe(); }} chevron={false} />
          <ListRow icon="mail" title={t('inbox.markUnread')} onPress={() => { setActionsOpen(false); void markUnread(); }} chevron={false} />
          {th.bot_mode !== 'off' ? (
            <ListRow icon="smart_toy" title={th.bot_paused ? t('inbox.resumeBot') : t('inbox.pauseBot')} subtitle={t('inbox.botMode', { mode: t(`inbox.botModes.${th.bot_mode}`) })} onPress={() => { setActionsOpen(false); void togglePause(); }} chevron={false} />
          ) : null}
          {th.can_like ? <ListRow icon="thumb_up" title={t('inbox.like')} onPress={() => { setActionsOpen(false); void like(); }} chevron={false} /> : null}
          {th.can_hide ? (
            <ListRow icon={th.is_hidden ? 'visibility' : 'visibility_off'} title={th.is_hidden ? t('inbox.unhide') : t('inbox.hide')} subtitle={t('inbox.hideHint')} onPress={() => { setActionsOpen(false); void hide(); }} chevron={false} />
          ) : null}
          <ListRow icon="person" title={t('inbox.customerDetails')} onPress={() => { setActionsOpen(false); setInfoOpen(true); }} last />
        </Card>
      </Sheet>

      <CustomerSheet visible={infoOpen} onClose={() => setInfoOpen(false)} thread={th} onChanged={update} canEdit={m.can_reply} />
    </View>
  );
}

// ---------------------------------------------------------------- bubbles

function Bubble({ m, kind }: { m: Message; kind: string }) {
  const { t } = useI18n();
  const out = m.direction === 'out';
  const showAuthor = out || kind === 'comment';
  return (
    <View style={{ marginBottom: 10, alignItems: out ? 'flex-end' : 'flex-start' }}>
      {showAuthor ? (
        <View style={styles.meta}>
          {m.is_bot ? (
            <View style={styles.metaItem}><Icon name="smart_toy" size={12} color={colors.text2} /><Txt size={11} weight="700" style={{ color: colors.text2 }}>{t('inbox.assistant')}</Txt></View>
          ) : (
            <Txt size={11} weight="700" style={{ color: colors.text2 }}>{out ? m.user?.name || m.author : m.author}</Txt>
          )}
          {m.channel === 'private' ? <View style={styles.metaItem}><Icon name="lock" size={11} color={colors.muted} /><Txt size={11} muted>{t('inbox.privateReply')}</Txt></View> : null}
          {m.channel === 'public' && out ? <View style={styles.metaItem}><Icon name="reply" size={11} color={colors.muted} /><Txt size={11} muted>{t('inbox.publicReply')}</Txt></View> : null}
          {m.hidden ? <View style={styles.metaItem}><Icon name="visibility_off" size={11} color={colors.muted} /><Txt size={11} muted>{t('inbox.hidden')}</Txt></View> : null}
        </View>
      ) : null}
      <View
        style={[
          styles.bubble,
          out ? [styles.bubbleOut, m.is_bot && { backgroundColor: colors.ink2 }] : styles.bubbleIn,
          m.state === 'failed' && { opacity: 0.7, borderWidth: 2, borderColor: 'rgba(180,35,24,0.5)' },
          m.hidden && { opacity: 0.5 },
        ]}>
        {m.attachments?.length ? (
          <View style={{ gap: 4, padding: 4 }}>
            {m.attachments.map((a) =>
              a.mimetype.startsWith('image/') ? (
                <AuthImage key={a.id} src={a.url} style={{ width: 220, height: 220, borderRadius: 16 }} />
              ) : (
                <View key={a.id} style={styles.file}>
                  <Icon name={a.mimetype.startsWith('audio/') ? 'mic' : a.mimetype.startsWith('video/') ? 'movie' : 'description'} size={15} color={out ? '#fff' : colors.text2} />
                  <Txt size={12} numberOfLines={1} style={{ color: out ? '#fff' : colors.text2 }}>{a.filename}</Txt>
                </View>
              ),
            )}
          </View>
        ) : null}
        {m.body ? <Txt size={15} style={{ color: out ? '#fff' : colors.text, lineHeight: 21, paddingHorizontal: 13, paddingVertical: 8 }} selectable>{m.body}</Txt> : null}
      </View>
      <View style={[styles.meta, { marginTop: 2 }]}>
        <Txt size={11} style={{ color: colors.faint }}>{formatTime(m.sent_at)}</Txt>
        {m.state === 'failed' ? <View style={styles.metaItem}><Icon name="error" size={11} color={colors.bad} /><Txt size={11} style={{ color: colors.bad }}>{t('inbox.notSent')}</Txt></View> : null}
      </View>
      {m.state === 'failed' && m.error ? <Txt size={11} style={{ color: colors.bad, maxWidth: '85%' }}>{m.error}</Txt> : null}
    </View>
  );
}

// ---------------------------------------------------------------- AI suggestion

function SuggestionCard({ thread, onChanged }: { thread: Thread; onChanged: (t: Thread) => void }) {
  const { t } = useI18n();
  const suggestion = thread.suggestion!;
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(suggestion.body);
  const [busy, setBusy] = useState<string | null>(null);
  const windowClosed = thread.window.limited && !thread.window.open && !thread.window.human_agent;

  const send = async () => {
    setBusy('send');
    try {
      const result = await api.post<SendResult>(`/inbox/suggestions/${suggestion.id}/send`, { body: editing ? text : null });
      if (result.message.state === 'failed') toast.error(result.message.error || t('inbox.notSent'));
      else toast.success(t('inbox.sent'));
      onChanged(result.thread);
    } catch (err) {
      toast.error(errorText(err));
    } finally {
      setBusy(null);
    }
  };
  const discard = async () => {
    setBusy('discard');
    try {
      onChanged(await api.delete<Thread>(`/inbox/suggestions/${suggestion.id}`));
    } catch (err) {
      toast.error(errorText(err));
    } finally {
      setBusy(null);
    }
  };

  return (
    <View style={styles.suggestion}>
      <View style={[styles.metaItem, { marginBottom: 6 }]}>
        <Icon name="auto_awesome" size={16} color={colors.ink} duo />
        <Txt size={13} weight="700" style={{ flex: 1 }}>{t('inbox.suggestion')}</Txt>
        {suggestion.confidence ? <Badge tone={suggestion.confidence >= 75 ? 'ok' : 'warn'}>{t('inbox.confidence', { n: suggestion.confidence })}</Badge> : null}
      </View>
      {editing ? (
        <Input multiline value={text} onChangeText={setText} autoFocus style={{ minHeight: 80 }} />
      ) : (
        <Txt size={14} style={{ lineHeight: 20 }}>{suggestion.body}</Txt>
      )}
      {suggestion.note ? (
        <View style={[styles.metaItem, { marginTop: 4 }]}>
          <Icon name="info" size={13} color={colors.muted} />
          <Txt size={12} muted style={{ flex: 1 }}>{suggestion.note}</Txt>
        </View>
      ) : null}
      <View style={{ flexDirection: 'row', gap: 8, marginTop: 10 }}>
        <Button size="sm" variant="primary" icon="send" loading={busy === 'send'} disabled={windowClosed || !text.trim()} onPress={send}>{t('inbox.send')}</Button>
        {!editing ? <Button size="sm" icon="edit_square" onPress={() => setEditing(true)}>{t('common.edit')}</Button> : null}
        <Button size="sm" variant="ghost" loading={busy === 'discard'} onPress={discard}>{t('inbox.discard')}</Button>
      </View>
    </View>
  );
}

// ---------------------------------------------------------------- composer

function Composer({ thread, meta, onChanged, bottomInset }: { thread: Thread; meta: InboxMeta; onChanged: (t: Thread) => void; bottomInset: number }) {
  const { t, rtl } = useI18n();
  const [draft, setDraft] = useState('');
  const [channel, setChannel] = useState<'dm' | 'public' | 'private'>(thread.kind === 'comment' ? 'public' : 'dm');
  const [cannedOpen, setCannedOpen] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const input = useRef<TextInput>(null);

  const w = thread.window;
  const windowClosed = w.limited && !w.open && !w.human_agent;
  const windowNote = !w.limited ? '' : w.open ? (w.hours_left < 4 ? t('inbox.windowHoursLeft', { hours: Math.max(1, Math.round(w.hours_left)) }) : '') : w.human_agent ? t('inbox.windowHumanAgent') : t('inbox.windowClosed');

  const slash = draft.startsWith('/') && !draft.includes(' ') ? draft.slice(1).toLowerCase() : null;
  const matches = meta.canned.filter((c) => slash === null || (c.shortcut || '').toLowerCase().startsWith(slash) || c.name.toLowerCase().includes(slash));
  const firstName = (thread.name || '').split(' ')[0];

  const insert = (c: Canned) => {
    const body = c.body.split('{name}').join(firstName).replace(/ {2,}/g, ' ').trim();
    setDraft((d) => (slash !== null ? body : d ? `${d} ${body}` : body));
    setCannedOpen(false);
    tap();
    setTimeout(() => input.current?.focus(), 50);
  };

  const send = async () => {
    if (!draft.trim()) return;
    setBusy('send');
    try {
      const result = await api.post<SendResult>(`/inbox/conversations/${thread.id}/messages`, { body: draft, channel });
      if (result.message.state === 'failed') toast.error(result.message.error || t('inbox.notSent'));
      else {
        setDraft('');
        tap('success');
      }
      onChanged(result.thread);
    } catch (err) {
      toast.error(errorText(err));
    } finally {
      setBusy(null);
    }
  };

  const suggest = async () => {
    setBusy('ai');
    try {
      onChanged(await api.post<Thread>(`/inbox/conversations/${thread.id}/suggest`));
    } catch (err) {
      toast.error(errorText(err));
    } finally {
      setBusy(null);
    }
  };

  return (
    <View style={[styles.composerWrap, { paddingBottom: Math.max(bottomInset, 10) }]}>
      {windowNote ? (
        <View style={[styles.windowNote, { backgroundColor: windowClosed ? colors.badBg : colors.warnBg }]}>
          <Icon name="schedule" size={14} color={windowClosed ? colors.bad : colors.warn} />
          <Txt size={12} style={{ color: windowClosed ? colors.bad : colors.warn, flex: 1 }}>{windowNote}</Txt>
        </View>
      ) : null}
      {thread.kind === 'comment' && thread.can_private ? (
        <Segmented
          style={{ marginBottom: 8 }}
          value={channel}
          onChange={setChannel}
          options={[
            { value: 'public', label: t('inbox.replyPublicly'), icon: 'reply' },
            { value: 'private', label: t('inbox.replyPrivately'), icon: 'lock' },
          ]}
        />
      ) : null}
      {slash !== null && matches.length ? (
        <View style={styles.slashList}>
          {matches.slice(0, 4).map((c) => (
            <Pressable key={c.id} onPress={() => insert(c)} style={styles.slashItem}>
              <Txt size={13} weight="700" numberOfLines={1}>{c.name}{c.shortcut ? <Txt size={12} muted>{`  /${c.shortcut}`}</Txt> : null}</Txt>
              <Txt size={12} muted numberOfLines={1}>{c.body}</Txt>
            </Pressable>
          ))}
        </View>
      ) : null}
      <View style={styles.composer}>
        <TextInput
          ref={input}
          value={draft}
          onChangeText={setDraft}
          multiline
          editable={!windowClosed}
          placeholderTextColor={colors.faint}
          placeholder={windowClosed ? t('inbox.windowClosedShort') : thread.kind === 'comment' ? (channel === 'private' ? t('inbox.placeholderPrivate') : t('inbox.placeholderPublic')) : t('inbox.placeholder')}
          style={[styles.composerInput, { textAlign: rtl ? 'right' : 'left' }, Platform.OS === 'web' && ({ outlineStyle: 'none' } as object)]}
        />
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: 2, paddingHorizontal: 6, paddingBottom: 6 }}>
          <IconButton icon="bolt" label={t('inbox.cannedReplies')} onPress={() => setCannedOpen(true)} size={36} />
          {meta.has_provider ? (
            <Button size="sm" variant="ghost" icon="wand_stars" loading={busy === 'ai'} onPress={suggest}>{t('inbox.writeWithAi')}</Button>
          ) : null}
          <View style={{ flex: 1 }} />
          <Pressable
            accessibilityRole="button"
            accessibilityLabel={t('inbox.send')}
            disabled={!draft.trim() || windowClosed || busy === 'send'}
            onPress={send}
            style={[styles.sendBtn, (!draft.trim() || windowClosed) && { opacity: 0.35 }]}>
            <Icon name="send" size={18} color="#fff" flip={rtl} />
          </Pressable>
        </View>
      </View>

      <Sheet visible={cannedOpen} onClose={() => setCannedOpen(false)} title={t('inbox.cannedReplies')}>
        {meta.canned.length ? (
          <Card padded={false}>
            {meta.canned.map((c, i) => (
              <ListRow key={c.id} title={c.name} subtitle={c.body} onPress={() => insert(c)} chevron={false} last={i === meta.canned.length - 1}
                trailing={c.shortcut ? <Badge>{`/${c.shortcut}`}</Badge> : null} />
            ))}
          </Card>
        ) : (
          <Txt muted size={14} style={{ textAlign: 'center', paddingVertical: 20 }}>{t('inbox.noCanned')}</Txt>
        )}
      </Sheet>
    </View>
  );
}

// ---------------------------------------------------------------- customer info

function CustomerSheet({ visible, onClose, thread, onChanged, canEdit }: { visible: boolean; onClose: () => void; thread: Thread; onChanged: (t: Thread) => void; canEdit: boolean }) {
  const { t } = useI18n();
  const contact = thread.contact;
  const [form, setForm] = useState<Partial<Contact>>({});
  const [note, setNote] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const value = (k: keyof Contact) => (form[k] ?? contact?.[k] ?? '') as string;

  const save = async () => {
    setBusy(true);
    try {
      if (contact && Object.keys(form).length) await api.patch<Contact>(`/inbox/contacts/${contact.id}`, form);
      const next = await api.patch<Thread>(`/inbox/conversations/${thread.id}`, note !== null ? { note } : {});
      onChanged(next);
      setForm({});
      setNote(null);
      toast.success(t('common.saved'));
      onClose();
    } catch (err) {
      toast.error(errorText(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Sheet
      visible={visible}
      onClose={onClose}
      title={t('inbox.customerDetails')}
      footer={canEdit ? <Button variant="primary" full style={{ flex: 1 }} loading={busy} onPress={save}>{t('common.save')}</Button> : null}>
      <View style={{ alignItems: 'center', gap: 6, paddingVertical: 4 }}>
        <ConvAvatar name={thread.name} src={thread.avatar_url} platform={thread.platform} size={64} />
        <Txt weight="700" size={17}>{thread.name}</Txt>
        {thread.handle ? <Txt muted size={13}>{thread.handle}</Txt> : null}
        <View style={{ flexDirection: 'row', gap: 6, flexWrap: 'wrap', justifyContent: 'center' }}>
          <IntentBadge intent={thread.intent} />
          <SentimentBadge sentiment={thread.sentiment} />
          {(thread.tags ?? []).map((tag) => <Badge key={tag.id} icon="tag">{tag.name}</Badge>)}
          {contact?.conversations && contact.conversations > 1 ? <Badge icon="forum">{t('inbox.conversationsCount', { count: contact.conversations })}</Badge> : null}
        </View>
      </View>
      {contact ? (
        <>
          <Field label={t('inbox.contact.name')}>
            <Input value={value('name')} editable={canEdit} onChangeText={(v) => setForm((f) => ({ ...f, name: v }))} />
          </Field>
          <Field label={t('inbox.contact.phone')}>
            <Input ltr value={value('phone')} editable={canEdit} keyboardType="phone-pad" onChangeText={(v) => setForm((f) => ({ ...f, phone: v }))} />
          </Field>
          <Field label={t('inbox.contact.email')}>
            <Input ltr value={value('email')} editable={canEdit} keyboardType="email-address" autoCapitalize="none" onChangeText={(v) => setForm((f) => ({ ...f, email: v }))} />
          </Field>
          <Field label={t('inbox.contact.note')}>
            <Input multiline value={value('note')} editable={canEdit} onChangeText={(v) => setForm((f) => ({ ...f, note: v }))} />
          </Field>
        </>
      ) : null}
      <Field label={t('inbox.conversationNote')} hint={t('inbox.conversationNoteHint')}>
        <Input multiline value={note ?? thread.note ?? ''} editable={canEdit} onChangeText={setNote} />
      </Field>
    </Sheet>
  );
}

const styles = StyleSheet.create({
  banner: { flexDirection: 'row', alignItems: 'center', gap: 10, backgroundColor: 'rgba(255,255,255,0.7)', borderRadius: radius.md, padding: 12, marginBottom: 8, borderWidth: 1, borderColor: colors.line },
  dayPill: { backgroundColor: colors.fill2, borderRadius: 999, paddingHorizontal: 12, paddingVertical: 3 },
  meta: { flexDirection: 'row', alignItems: 'center', gap: 8, paddingHorizontal: 4, marginBottom: 3, flexWrap: 'wrap' },
  metaItem: { flexDirection: 'row', alignItems: 'center', gap: 3 },
  bubble: { maxWidth: '85%', borderRadius: 20, overflow: 'hidden' },
  bubbleOut: { backgroundColor: colors.ink, borderBottomEndRadius: 6 },
  bubbleIn: { backgroundColor: 'rgba(255,255,255,0.95)', borderBottomStartRadius: 6, borderWidth: 1, borderColor: colors.line },
  file: { flexDirection: 'row', alignItems: 'center', gap: 6, paddingHorizontal: 10, paddingVertical: 8, borderRadius: 12, backgroundColor: 'rgba(0,0,0,0.06)' },
  suggestion: { marginHorizontal: 10, marginBottom: 8, padding: 14, borderRadius: radius.lg, backgroundColor: 'rgba(255,255,255,0.92)', borderWidth: 1.5, borderColor: colors.ink },
  composerWrap: { paddingHorizontal: 10, paddingTop: 8, borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: colors.line, backgroundColor: 'rgba(255,255,255,0.7)' },
  windowNote: { flexDirection: 'row', alignItems: 'center', gap: 6, borderRadius: 12, paddingHorizontal: 10, paddingVertical: 6, marginBottom: 8 },
  composer: { borderRadius: 22, borderWidth: 1, borderColor: colors.line, backgroundColor: '#fff' },
  composerInput: { minHeight: 44, maxHeight: 140, paddingHorizontal: 14, paddingTop: 12, paddingBottom: 4, fontSize: 15, color: colors.text },
  sendBtn: { width: 38, height: 38, borderRadius: 19, backgroundColor: colors.ink, alignItems: 'center', justifyContent: 'center' },
  slashList: { backgroundColor: '#fff', borderRadius: 16, borderWidth: 1, borderColor: colors.line, marginBottom: 8, overflow: 'hidden' },
  slashItem: { paddingHorizontal: 12, paddingVertical: 8, borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.line },
});
