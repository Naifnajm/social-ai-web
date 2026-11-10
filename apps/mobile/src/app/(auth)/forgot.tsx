import { Link } from 'expo-router';
import { useState } from 'react';
import { Pressable, View } from 'react-native';

import { AuthShell } from '@/components/auth-shell';
import { Icon } from '@/components/icon';
import { Button, Field, Input, Txt } from '@/components/ui';
import { api, errorText } from '@/lib/api';
import { useI18n } from '@/lib/i18n';
import { colors } from '@/theme';

/** Forgot password: the API e-mails a reset link (opened in the browser). */
export default function Forgot() {
  const { t } = useI18n();
  const [email, setEmail] = useState('');
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    if (!email.trim()) {
      setError(t('auth.fillAll'));
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await api.post('/auth/password/forgot', { email: email.trim() });
      setSent(true);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <AuthShell
      title={t('auth.forgotTitle')}
      subtitle={t('auth.forgotSubtitle')}
      footer={
        <Link href="/sign-in" asChild>
          <Pressable style={{ alignSelf: 'center' }}><Txt weight="700">{t('auth.backToSignIn')}</Txt></Pressable>
        </Link>
      }>
      {sent ? (
        <View style={{ alignItems: 'center', gap: 10, paddingVertical: 8 }}>
          <View style={{ width: 52, height: 52, borderRadius: 18, backgroundColor: colors.okBg, alignItems: 'center', justifyContent: 'center' }}>
            <Icon name="mail" size={26} color={colors.ok} />
          </View>
          <Txt weight="700" size={16}>{t('auth.sentTitle')}</Txt>
          <Txt muted style={{ textAlign: 'center' }}>{t('auth.sentText', { email: email.trim() })}</Txt>
        </View>
      ) : (
        <>
          <Field label={t('auth.email')}>
            <Input ltr value={email} onChangeText={setEmail} autoCapitalize="none" autoComplete="email" keyboardType="email-address" placeholder="name@company.com" onSubmitEditing={submit} />
          </Field>
          {error ? <Txt size={13} style={{ color: colors.bad }}>{error}</Txt> : null}
          <Button variant="primary" size="lg" loading={busy} onPress={submit} full>{t('auth.sendLink')}</Button>
        </>
      )}
    </AuthShell>
  );
}
