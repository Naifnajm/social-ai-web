/** Minimal charts with react-native-svg: area/line trend, bars and horizontal share bars. */
import { useState } from 'react';
import { View, type LayoutChangeEvent } from 'react-native';
import Svg, { Defs, LinearGradient, Path, Rect, Stop } from 'react-native-svg';

import { colors } from '@/theme';

import { Txt } from './ui';

function useWidth(): [number, (e: LayoutChangeEvent) => void] {
  const [width, setWidth] = useState(0);
  return [width, (e) => setWidth(Math.round(e.nativeEvent.layout.width))];
}

/** Area chart; always drawn left→right (time) even in Arabic, like most finance apps. */
export function AreaChart({ values, height = 120, color = colors.ink, emptyLabel }: { values: number[]; height?: number; color?: string; emptyLabel?: string }) {
  const [width, onLayout] = useWidth();
  const max = Math.max(...values, 0);
  const empty = !values.length || max === 0;
  let line = '';
  let area = '';
  if (width && !empty) {
    const step = values.length > 1 ? width / (values.length - 1) : width;
    const pts = values.map((v, i) => [i * step, height - 6 - (v / max) * (height - 16)] as const);
    line = pts.map(([x, y], i) => `${i ? 'L' : 'M'}${x.toFixed(1)} ${y.toFixed(1)}`).join(' ');
    area = `${line} L${width} ${height} L0 ${height} Z`;
  }
  return (
    <View onLayout={onLayout} style={{ height, direction: 'ltr' }}>
      {empty ? (
        <View style={{ flex: 1, alignItems: 'center', justifyContent: 'center', borderRadius: 14, backgroundColor: colors.fill }}>
          <Txt muted size={12}>{emptyLabel}</Txt>
        </View>
      ) : width ? (
        <Svg width={width} height={height}>
          <Defs>
            <LinearGradient id="area" x1="0" y1="0" x2="0" y2="1">
              <Stop offset="0" stopColor={color} stopOpacity={0.22} />
              <Stop offset="1" stopColor={color} stopOpacity={0} />
            </LinearGradient>
          </Defs>
          <Path d={area} fill="url(#area)" />
          <Path d={line} stroke={color} strokeWidth={2} fill="none" strokeLinejoin="round" strokeLinecap="round" />
        </Svg>
      ) : null}
    </View>
  );
}

export function BarChart({ values, height = 60, color = colors.ink2 }: { values: number[]; height?: number; color?: string }) {
  const [width, onLayout] = useWidth();
  const max = Math.max(...values, 1);
  const gap = 2;
  const bar = values.length ? Math.max(1, (width - gap * (values.length - 1)) / values.length) : 0;
  return (
    <View onLayout={onLayout} style={{ height, direction: 'ltr' }}>
      {width ? (
        <Svg width={width} height={height}>
          {values.map((v, i) => {
            const h = Math.max(v ? 3 : 1, (v / max) * height);
            return <Rect key={i} x={i * (bar + gap)} y={height - h} width={bar} height={h} rx={Math.min(3, bar / 2)} fill={v ? color : colors.fill2} />;
          })}
        </Svg>
      ) : null}
    </View>
  );
}

/** Labelled horizontal bars (share of a total). */
export function ShareBars({ rows }: { rows: { label: string; value: number; hint?: string; color?: string }[] }) {
  const max = Math.max(...rows.map((r) => r.value), 1);
  return (
    <View style={{ gap: 10 }}>
      {rows.map((r) => (
        <View key={r.label} style={{ gap: 4 }}>
          <View style={{ flexDirection: 'row', justifyContent: 'space-between', gap: 8 }}>
            <Txt size={13} numberOfLines={1} style={{ flex: 1 }}>{r.label}</Txt>
            <Txt size={13} weight="700">{r.hint ?? r.value}</Txt>
          </View>
          <View style={{ height: 8, borderRadius: 4, backgroundColor: colors.fill2, overflow: 'hidden' }}>
            <View style={{ width: `${Math.round((r.value / max) * 100)}%`, height: 8, borderRadius: 4, backgroundColor: r.color ?? colors.ink }} />
          </View>
        </View>
      ))}
    </View>
  );
}
