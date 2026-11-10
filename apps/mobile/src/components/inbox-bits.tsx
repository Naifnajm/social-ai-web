import { View } from 'react-native';

import { useI18n } from '@/lib/i18n';
import type { Intent, Sentiment } from '@/lib/types';

import { PlatformBadge } from './icon';
import { Avatar, Badge, type Tone } from './ui';

/** Customer avatar with the network badge in the corner. */
export function ConvAvatar({ name, src, platform, size = 46 }: { name: string; src?: string | null; platform: string; size?: number }) {
  return (
    <View style={{ width: size, height: size }}>
      <Avatar name={name} src={src} size={size} />
      <View style={{ position: 'absolute', bottom: -2, end: -2, borderRadius: 8, borderWidth: 2, borderColor: '#fff' }}>
        <PlatformBadge platform={platform} size={Math.round(size * 0.4)} />
      </View>
    </View>
  );
}

const INTENT_TONE: Record<Intent, Tone> = {
  question: 'neutral',
  order: 'ok',
  lead: 'ok',
  complaint: 'bad',
  praise: 'ok',
  spam: 'warn',
  other: 'neutral',
};

export function IntentBadge({ intent }: { intent?: Intent | null }) {
  const { t } = useI18n();
  if (!intent || intent === 'other') return null;
  return <Badge tone={INTENT_TONE[intent]}>{t(`inbox.intent.${intent}`)}</Badge>;
}

export function SentimentBadge({ sentiment }: { sentiment?: Sentiment | null }) {
  const { t } = useI18n();
  if (!sentiment) return null;
  const tone: Tone = sentiment === 'positive' ? 'ok' : sentiment === 'negative' ? 'bad' : 'neutral';
  return <Badge tone={tone} icon={sentiment === 'negative' ? 'mood_bad' : 'mood'}>{t(`inbox.sentiment.${sentiment}`)}</Badge>;
}
