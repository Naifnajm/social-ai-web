import type { ReactNode } from 'react';
import { KeyboardAvoidingView, Platform, Pressable, ScrollView, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { setLanguage, useI18n } from '@/lib/i18n';
import { colors } from '@/theme';

import { Logo } from './logo';
import { Backdrop, Card, Txt } from './ui';

/** Layout of the sign-in / sign-up / forgot screens: logo, title, glass card, language toggle. */
export function AuthShell({ title, subtitle, children, footer }: { title: string; subtitle?: string; children: ReactNode; footer?: ReactNode }) {
  const insets = useSafeAreaInsets();
  const { locale } = useI18n();
  return (
    <View style={{ flex: 1 }}>
      <Backdrop />
      <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
        <ScrollView
          keyboardShouldPersistTaps="handled"
          contentContainerStyle={{ flexGrow: 1, justifyContent: 'center', padding: 20, paddingTop: insets.top + 24, paddingBottom: insets.bottom + 24 }}>
          <View style={{ position: 'absolute', top: insets.top + 8, end: 16, flexDirection: 'row', gap: 4 }}>
            {(['ar', 'en'] as const).map((lang) => (
              <Pressable
                key={lang}
                onPress={() => void setLanguage(lang)}
                accessibilityRole="button"
                style={{ paddingHorizontal: 12, height: 32, borderRadius: 16, justifyContent: 'center', backgroundColor: locale === lang ? colors.ink : 'rgba(255,255,255,0.7)' }}>
                <Txt size={13} weight="600" style={{ color: locale === lang ? '#fff' : colors.text2 }}>{lang === 'ar' ? 'العربية' : 'English'}</Txt>
              </Pressable>
            ))}
          </View>
          <View style={{ width: '100%', maxWidth: 420, alignSelf: 'center', gap: 22 }}>
            <View style={{ alignItems: 'center', gap: 12 }}>
              <Logo size={60} />
              <Txt style={{ fontSize: 26, fontWeight: '800', letterSpacing: -0.5, textAlign: 'center' }}>{title}</Txt>
              {subtitle ? <Txt muted style={{ textAlign: 'center' }}>{subtitle}</Txt> : null}
            </View>
            <Card style={{ gap: 14, padding: 20 }}>{children}</Card>
            {footer}
          </View>
        </ScrollView>
      </KeyboardAvoidingView>
    </View>
  );
}
