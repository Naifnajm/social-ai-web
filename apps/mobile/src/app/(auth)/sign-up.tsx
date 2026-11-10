import { Link } from 'expo-router';
import { useState } from 'react';
import { Pressable, View } from 'react-native';

import { AuthShell } from '@/components/auth-shell';
import { Icon } from '@/components/icon';
import { Button, Field, Input, Txt } from '@/components/ui';
import { errorText } from '@/lib/api';
import { useI18n } from '@/lib/i18n';
import { signUp } from '@/lib/session';
import { colors } from '@/theme';

/** Sign up: creates the user and their company workspace. */
export default function SignUp() {
  const { t } = useI18n();
  const [name, setName] = useState('');
  const [company, setCompany] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    if (!name.trim() || !company.trim() || !email.trim() || !password) {
      setError(t('auth.fillAll'));
      return;
    }
    if (password.length < 8) {
      setError(t('auth.passwordShort'));
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await signUp({ name: name.trim(), email, password, workspace_name: company.trim() });
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <AuthShell
      title={t('auth.signUpTitle')}
      subtitle={t('auth.signUpSubtitle')}
      footer={
        <View style={{ flexDirection: 'row', gap: 6, justifyContent: 'center' }}>
          <Txt muted>{t('auth.haveAccount')}</Txt>
          <Link href="/sign-in" asChild>
            <Pressable><Txt weight="700">{t('auth.signIn')}</Txt></Pressable>
          </Link>
        </View>
      }>
      <Field label={t('auth.name')}>
        <Input value={name} onChangeText={setName} autoComplete="name" textContentType="name" />
      </Field>
      <Field label={t('auth.company')} hint={t('auth.companyHint')}>
        <Input value={company} onChangeText={setCompany} textContentType="organizationName" />
      </Field>
      <Field label={t('auth.email')}>
        <Input ltr value={email} onChangeText={setEmail} autoCapitalize="none" autoComplete="email" keyboardType="email-address" placeholder="name@company.com" />
      </Field>
      <Field label={t('auth.password')} hint={t('auth.passwordHint')}>
        <Input ltr value={password} onChangeText={setPassword} secureTextEntry autoComplete="new-password" textContentType="newPassword" onSubmitEditing={submit} />
      </Field>
      {error ? (
        <View style={{ flexDirection: 'row', gap: 6, alignItems: 'center', backgroundColor: colors.badBg, padding: 10, borderRadius: 12 }}>
          <Icon name="error" size={16} color={colors.bad} />
          <Txt size={13} style={{ color: colors.bad, flex: 1 }}>{error}</Txt>
        </View>
      ) : null}
      <Button variant="primary" size="lg" loading={busy} onPress={submit} full>{t('auth.createAccount')}</Button>
      <Txt muted size={12} style={{ textAlign: 'center' }}>{t('auth.terms')}</Txt>
    </AuthShell>
  );
}
