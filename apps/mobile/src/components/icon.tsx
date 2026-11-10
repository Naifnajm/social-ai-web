/**
 * Solar icons (480 Design, CC BY 4.0) by semantic key — the same set as the web app (packages/icons):
 *   <Icon name="inbox" />  <Icon name="send" duo size={22} color="#fff" />
 * Brand logos: <PlatformIcon platform="instagram" />, <PlatformBadge platform="x" size={24} />.
 */
import { memo } from 'react';
import { type StyleProp, type ViewStyle } from 'react-native';
import Svg, { Defs, G, LinearGradient, Path, Rect, Stop, SvgXml } from 'react-native-svg';

import brands from '@/assets/brands.json';
import icons from '@/assets/icons.json';
import { colors, platformColors } from '@/theme';

type IconSet = Record<string, { linear: string; duo?: string }>;
const ICONS = icons as IconSet;
const BRANDS = brands as Record<string, string>;

export type IconName = keyof typeof icons;

const cache = new Map<string, string>();
function xmlFor(name: string, duo: boolean): string | null {
  const key = `${name}:${duo ? 1 : 0}`;
  const hit = cache.get(key);
  if (hit) return hit;
  const entry = ICONS[name];
  if (!entry) return null;
  const xml = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">${(duo && entry.duo) || entry.linear}</svg>`;
  cache.set(key, xml);
  return xml;
}

/** Icons that point "forward/back" and must mirror in right-to-left layouts. */
const DIRECTIONAL = new Set(['arrow_back', 'east', 'send', 'reply', 'undo', 'redo', 'fast_forward', 'open_in_new']);

export const Icon = memo(function Icon({
  name,
  size = 20,
  color = colors.text2,
  duo = false,
  flip = false,
  style,
}: {
  name: IconName | string;
  size?: number;
  color?: string;
  duo?: boolean;
  /** mirror horizontally (pass `rtl` for directional icons) */
  flip?: boolean;
  style?: StyleProp<ViewStyle>;
}) {
  const xml = xmlFor(name, duo);
  if (!xml) return null;
  const mirror = flip && DIRECTIONAL.has(name);
  return (
    <SvgXml
      xml={xml}
      width={size}
      height={size}
      color={color}
      style={[mirror ? { transform: [{ scaleX: -1 }] } : null, style]}
    />
  );
});

export function PlatformIcon({ platform, size = 14, color = '#fff' }: { platform: string; size?: number; color?: string }) {
  const d = BRANDS[platform];
  if (!d) return null;
  return (
    <Svg viewBox="0 0 24 24" width={size} height={size}>
      <Path d={d} fill={color} />
    </Svg>
  );
}

/** Rounded brand-colour badge with the network logo. */
export function PlatformBadge({ platform, size = 26 }: { platform: string; size?: number }) {
  const d = BRANDS[platform];
  const scale = 0.55;
  const offset = (24 * (1 - scale)) / 2;
  return (
    <Svg viewBox="0 0 24 24" width={size} height={size}>
      {platform === 'instagram' && (
        <Defs>
          <LinearGradient id="ig" x1="0" y1="1" x2="1" y2="0">
            <Stop offset="0" stopColor="#f9a825" />
            <Stop offset="0.45" stopColor="#e1306c" />
            <Stop offset="1" stopColor="#833ab4" />
          </LinearGradient>
        </Defs>
      )}
      <Rect x={0} y={0} width={24} height={24} rx={8} fill={platform === 'instagram' ? 'url(#ig)' : platformColors[platform] || colors.ink} />
      {d ? (
        <G transform={`translate(${offset} ${offset}) scale(${scale})`}>
          <Path d={d} fill="#fff" />
        </G>
      ) : null}
    </Svg>
  );
}
