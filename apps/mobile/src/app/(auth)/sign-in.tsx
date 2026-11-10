import { Link } from 'expo-router';
import { useState } from 'react';
import { Pressable, View } from 'react-native';

import { AuthShell } from '@/components/auth-shell';
import { Icon } from '@/components/icon';
import { Button, Field, Input, Txt } from '@/components/ui';
import { errorText } from '@/lib/api';
import { defaultServer, getServer, isCustomServer, setServer } from '@/lib/config';
import { useI18n } from '@/lib/i18n';
import { signIn } from '@/lib/session';
import { colors } from '@/theme';

export default function SignIn() {
  const { t } = useI18n();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showServer, setShowServer] = useState(isCustomServer());
  const [server, setServerValue] = useState(isCustomServer() ? getServer() : '');

  const submit = async () => {
    if (!email.trim() || !password) {
      setError(t('auth.fillAll'));
      return;
    }
    setBusy(true);
    setError(null);
    try {
      setServer(server);
      await signIn(email, password);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <AuthShell
      title={t('auth.welcome')}
      subtitle={t('auth.signInSubtitle')}
      footer={
        <View style={{ alignItems: 'center', gap: 14 }}>
          <View style={{ flexDirection: 'row', gap: 6 }}>
            <Txt muted>{t('auth.noAccount')}</Txt>
            <Link href="/sign-up" asChild>
              <Pressable><Txt weight="700">{t('auth.createAccount')}</Txt></Pressable>
            </Link>
          </View>
          <Pressable onPress={() => setShowServer((v) => !v)} style={{ flexDirection: 'row', alignItems: 'center', gap: 4 }} accessibilityRole="button">
            <Icon name="settings" size={14} color={colors.faint} />
            <Txt size={12} style={{ color: colors.faint }}>{t('auth.server')}</Txt>
          </Pressable>
        </View>
      }>
      <Field label={t('auth.email')}>
        <Input
          ltr
          value={email}
          onChangeText={setEmail}
          autoCapitalize="none"
          autoComplete="email"
          keyboardType="email-address"
          textContentType="emailAddress"
          placeholder="name@company.com"
          returnKeyType="next"
        />
      </Field>
      <Field label={t('auth.password')}>
        <Input ltr value={password} onChangeText={setPassword} secureTextEntry autoComplete="current-password" textContentType="password" onSubmitEditing={submit} returnKeyType="go" />
      </Field>
      {showServer ? (
        <Field label={t('auth.serverLabel')} hint={t('auth.serverHint', { url: defaultServer() })}>
          <Input ltr value={server} onChangeText={setServerValue} autoCapitalize="none" autoCorrect={false} keyboardType="url" placeholder={defaultServer()} />
        </Field>
      ) : null}
      {error ? (
        <View style={{ flexDirection: 'row', gap: 6, alignItems: 'center', backgroundColor: colors.badBg, padding: 10, borderRadius: 12 }}>
          <Icon name="error" size={16} color={colors.bad} />
          <Txt size={13} style={{ color: colors.bad, flex: 1 }}>{error}</Txt>
        </View>
      ) : null}
      <Button variant="primary" size="lg" loading={busy} onPress={submit} full>{t('auth.signIn')}</Button>
      <Link href="/forgot" asChild>
        <Pressable style={{ alignSelf: 'center' }}>
          <Txt size={14} weight="600" style={{ color: colors.text2 }}>{t('auth.forgot')}</Txt>
        </Pressable>
      </Link>
    </AuthShell>
  );
}
