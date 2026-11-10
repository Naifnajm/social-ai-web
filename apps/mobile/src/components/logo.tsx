import { View } from 'react-native';
import Svg, { Path } from 'react-native-svg';

import { colors } from '@/theme';

/** App mark: a black rounded tile with a white "send" spark (same as the app icon). */
export function Logo({ size = 48 }: { size?: number }) {
  return (
    <View
      style={{
        width: size,
        height: size,
        borderRadius: size * 0.28,
        backgroundColor: colors.ink,
        alignItems: 'center',
        justifyContent: 'center',
      }}>
      <Svg viewBox="0 0 24 24" width={size * 0.56} height={size * 0.56}>
        <Path
          d="M12 2.5c.5 4.6 2.9 7 7.5 7.5-4.6.5-7 2.9-7.5 7.5-.5-4.6-2.9-7-7.5-7.5 4.6-.5 7-2.9 7.5-7.5Z"
          fill="#fff"
        />
        <Path d="M18.5 15.5c.2 1.8 1.2 2.8 3 3-1.8.2-2.8 1.2-3 3-.2-1.8-1.2-2.8-3-3 1.8-.2 2.8-1.2 3-3Z" fill="#fff" opacity={0.6} />
      </Svg>
    </View>
  );
}
