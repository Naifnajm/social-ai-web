import { useQuery } from '@tanstack/react-query';
import { useRouter } from 'expo-router';
import { Alert, Platform, ScrollView, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { TAB_BAR_SPACE } from '@/components/tab-bar';
import { Avatar, Backdrop, Badge, Card, CountBadge, ListRow, PageHeader, Segmented, Txt } from '@/components/ui';
import { api } from '@/lib/api';
import { setLanguage, useI18n, type Lang } from '@/lib/i18n';
import { signOut, useSession } from '@/lib/session';
import type { Post } from '@/lib/types';

export default function MoreScreen() {
  const { t, locale } = useI18n();
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const { me, workspace, role, can } = useSession();
  const notes = useQuery({ queryKey: ['notifications-count'], queryFn: () => api.get<{ unread: number }>('/notifications/count'), refetchInterval: 60_000 });
  const approvals = useQuery({ queryKey: ['approvals'], queryFn: () => api.get<Post[]>('/approvals'), enabled: can('approver') });

  const changeLanguage = (lang: Lang) => {
    if (lang === locale) return;
    if (Platform.OS === 'web') {
      void setLanguage(lang);
      void api.patch('/auth/me', { locale: lang }).catch(() => undefined);
      return;
    }
    Alert.alert(t('settings.languageTitle'), t('settings.languageReload'), [
      { text: t('common.cancel'), style: 'cancel' },
      {
        text: t('settings.switch'),
        onPress: () => {
          void api.patch('/auth/me', { locale: lang }).catch(() => undefined).finally(() => void setLanguage(lang));
        },
      },
    ]);
  };

  const confirmSignOut = () => {
    if (Platform.OS === 'web') {
      if (window.confirm(t('more.signOutConfirm'))) void signOut();
      return;
    }
    Alert.alert(t('more.signOut'), t('more.signOutConfirm'), [
      { text: t('common.cancel'), style: 'cancel' },
      { text: t('more.signOut'), style: 'destructive', onPress: () => void signOut() },
    ]);
  };

  return (
    <View style={{ flex: 1 }}>
      <Backdrop />
      <ScrollView contentContainerStyle={{ paddingTop: insets.top + 8, paddingBottom: TAB_BAR_SPACE + insets.bottom + 10 }}>
        <PageHeader title={t('more.title')} />
        <View style={{ paddingHorizontal: 16, gap: 16 }}>
          <Card padded={false}>
            <ListRow
              leading={<Avatar name={me?.user.name} src={me?.user.avatar_url} size={48} />}
              title={<Txt weight="700" size={17} numberOfLines={1}>{me?.user.name}</Txt>}
              subtitle={me?.user.email}
              onPress={() => router.push('/settings')}
            />
            <ListRow
              icon="storefront"
              title={workspace?.name ?? '—'}
              subtitle={t('more.workspaceRole', { role: t(`roles.${role}`) })}
              trailing={(me?.workspaces.length ?? 0) > 1 ? <Badge>{String(me?.workspaces.length)}</Badge> : null}
              onPress={() => router.push('/workspaces')}
              last
            />
          </Card>

          <Card padded={false}>
            <ListRow icon="info" title={t('more.notifications')} trailing={<CountBadge count={notes.data?.unread ?? 0} />} onPress={() => router.push('/notifications')} />
            {can('approver') ? (
              <ListRow icon="verified_user" title={t('more.approvals')} trailing={<CountBadge count={approvals.data?.length ?? 0} />} onPress={() => router.push('/approvals')} />
            ) : null}
            {can('editor') ? <ListRow icon="edit_square" title={t('more.studio')} subtitle={t('more.studioHint')} onPress={() => router.push('/compose')} /> : null}
            <ListRow icon="link" title={t('more.accounts')} onPress={() => router.push('/accounts')} last />
          </Card>

          <Card style={{ gap: 10 }}>
            <Txt weight="700">{t('settings.language')}</Txt>
            <Segmented<Lang>
              value={locale}
              onChange={changeLanguage}
              options={[
                { value: 'ar', label: 'العربية' },
                { value: 'en', label: 'English' },
              ]}
            />
          </Card>

          <Card padded={false}>
            <ListRow icon="settings" title={t('more.settings')} onPress={() => router.push('/settings')} />
            <ListRow icon="lock" title={t('more.signOut')} danger chevron={false} onPress={confirmSignOut} last />
          </Card>
          <Txt muted size={11} style={{ textAlign: 'center' }}>Stravica Social · v1.0.0</Txt>
        </View>
      </ScrollView>
    </View>
  );
}
