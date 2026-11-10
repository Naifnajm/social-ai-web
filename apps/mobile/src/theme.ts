/**
 * Design tokens — the same neutral "liquid glass" palette as the web app (apps/web/src/app/globals.css):
 * near-black ink, zinc greys, white glass surfaces on a soft grey background.
 */
import { Platform, type ViewStyle } from 'react-native';

export const colors = {
  ink: '#0a0a0a',
  ink2: '#27272a',
  text: '#18181b',
  text2: '#3f3f46',
  muted: '#63636b',
  faint: '#a1a1aa',
  line: 'rgba(0,0,0,0.08)',
  lineStrong: 'rgba(0,0,0,0.14)',
  fill: 'rgba(0,0,0,0.035)',
  fill2: 'rgba(0,0,0,0.06)',
  track: 'rgba(118,118,128,0.14)',
  bg: '#f4f4f5',
  white: '#ffffff',
  glass: 'rgba(255,255,255,0.62)',
  glassStrong: 'rgba(255,255,255,0.82)',
  glassEdge: 'rgba(255,255,255,0.6)',
  ok: '#1f7a3d',
  okBg: 'rgba(52,199,89,0.13)',
  warn: '#8a5300',
  warnBg: 'rgba(255,159,10,0.16)',
  bad: '#b42318',
  badBg: 'rgba(255,59,48,0.1)',
  badSolid: '#d92d20',
} as const;

export const platformColors: Record<string, string> = {
  facebook: '#1877f2',
  instagram: '#e1306c',
  linkedin: '#0a66c2',
  x: '#000000',
  tiktok: '#010101',
  threads: '#000000',
  telegram: '#229ed9',
  whatsapp: '#25d366',
};

export const PLATFORM_LABELS: Record<string, string> = {
  facebook: 'Facebook',
  instagram: 'Instagram',
  linkedin: 'LinkedIn',
  x: 'X',
  tiktok: 'TikTok',
  threads: 'Threads',
  telegram: 'Telegram',
  whatsapp: 'WhatsApp',
};

export const radius = { sm: 10, md: 14, lg: 20, xl: 24, pill: 999 } as const;
export const space = { xs: 4, sm: 8, md: 12, lg: 16, xl: 20, xxl: 28 } as const;

/** Soft layered shadow of glass cards (web `--shadow`). */
export const shadow: ViewStyle = Platform.select<ViewStyle>({
  web: { boxShadow: '0 0 0 1px rgba(0,0,0,0.06), 0 1px 2px rgba(0,0,0,0.04), 0 8px 24px -6px rgba(0,0,0,0.08)' },
  default: {
    shadowColor: '#000',
    shadowOpacity: 0.07,
    shadowRadius: 14,
    shadowOffset: { width: 0, height: 6 },
    elevation: 2,
  },
})!;

export const shadowFloat: ViewStyle = Platform.select<ViewStyle>({
  web: { boxShadow: '0 0 0 1px rgba(0,0,0,0.06), 0 4px 10px rgba(0,0,0,0.05), 0 24px 56px -12px rgba(0,0,0,0.22)' },
  default: {
    shadowColor: '#000',
    shadowOpacity: 0.16,
    shadowRadius: 24,
    shadowOffset: { width: 0, height: 10 },
    elevation: 8,
  },
})!;

export const font = {
  title: { fontSize: 28, fontWeight: '800', letterSpacing: -0.4, color: colors.text },
  h2: { fontSize: 17, fontWeight: '700', letterSpacing: -0.2, color: colors.text },
  body: { fontSize: 15, color: colors.text },
  small: { fontSize: 13, color: colors.muted },
  tiny: { fontSize: 11, color: colors.muted },
} as const;
