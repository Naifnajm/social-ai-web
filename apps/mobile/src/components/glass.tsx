/**
 * Glass surface: Liquid Glass on iOS 26+ (expo-glass-effect), a blur material on older iOS and the web
 * (expo-blur → backdrop-filter), and a solid translucent white on Android (no blur target needed).
 */
import { BlurView } from 'expo-blur';
import { GlassView, isLiquidGlassAvailable } from 'expo-glass-effect';
import type { ReactNode } from 'react';
import { Platform, StyleSheet, View, type StyleProp, type ViewStyle } from 'react-native';

import { colors } from '@/theme';

const liquid = Platform.OS === 'ios' && (() => {
  try {
    return isLiquidGlassAvailable();
  } catch {
    return false;
  }
})();

export function Glass({
  children,
  style,
  strong = false,
  intensity = 40,
}: {
  children?: ReactNode;
  style?: StyleProp<ViewStyle>;
  strong?: boolean;
  intensity?: number;
}) {
  const flat = StyleSheet.flatten(style) || {};
  const radius = flat.borderRadius;
  if (liquid) {
    return (
      <GlassView glassEffectStyle="regular" colorScheme="light" style={[{ overflow: 'hidden' }, style]}>
        {children}
      </GlassView>
    );
  }
  if (Platform.OS === 'android') {
    return <View style={[{ backgroundColor: strong ? 'rgba(255,255,255,0.96)' : 'rgba(255,255,255,0.9)' }, style]}>{children}</View>;
  }
  return (
    <View style={[{ overflow: 'hidden' }, style]}>
      <BlurView
        intensity={intensity}
        tint={Platform.OS === 'ios' ? 'systemChromeMaterialLight' : 'light'}
        style={[StyleSheet.absoluteFill, radius ? { borderRadius: radius } : null]}
      />
      <View
        style={[StyleSheet.absoluteFill, { pointerEvents: 'none', backgroundColor: strong ? colors.glassStrong : colors.glass }, radius ? { borderRadius: radius } : null]}
      />
      {children}
    </View>
  );
}
