import { Redirect } from 'expo-router';
import { ActivityIndicator, View } from 'react-native';

import { Logo } from '@/components/logo';
import { useSession } from '@/lib/session';
import { colors } from '@/theme';

/** Start: wait for the stored session, then go to the inbox or the sign-in screen. */
export default function Index() {
  const { status } = useSession();
  if (status === 'signedIn') return <Redirect href="/inbox" />;
  if (status === 'signedOut') return <Redirect href="/sign-in" />;
  return (
    <View style={{ flex: 1, alignItems: 'center', justifyContent: 'center', gap: 20, backgroundColor: colors.bg }}>
      <Logo size={64} />
      <ActivityIndicator color={colors.muted} />
    </View>
  );
}
