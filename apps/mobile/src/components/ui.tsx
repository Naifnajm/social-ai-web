/**
 * UI kit — the phone version of the web kit (apps/web/src/components/ui): black pill buttons, white glass cards,
 * grey track segmented controls, soft badges. All layout uses start/end so Arabic (RTL) mirrors correctly.
 */
import { Image } from 'expo-image';
import { useRouter } from 'expo-router';
import { type ReactNode, useEffect, useState, useSyncExternalStore } from 'react';
import {
  ActivityIndicator,
  Modal,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
  type StyleProp,
  type TextInputProps,
  type TextProps,
  type TextStyle,
  type ViewStyle,
  KeyboardAvoidingView,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { authHeaders, apiUrl } from '@/lib/api';
import { tap } from '@/lib/format';
import { useI18n } from '@/lib/i18n';
import { colors, radius, shadow, shadowFloat } from '@/theme';

import { Glass } from './glass';
import { Icon } from './icon';

// ---------------------------------------------------------------- text

export function Txt({ style, muted, weight, size, ...rest }: TextProps & { muted?: boolean; weight?: TextStyle['fontWeight']; size?: number }) {
  return (
    <Text
      {...rest}
      style={[{ color: muted ? colors.muted : colors.text, fontSize: size ?? 15, fontWeight: weight }, styles.text, style]}
    />
  );
}

// ---------------------------------------------------------------- screen background

/** Soft grey background with faint light blobs (the web's radial gradients). */
export function Backdrop() {
  return (
    <View style={[StyleSheet.absoluteFill, { backgroundColor: colors.bg, overflow: 'hidden', pointerEvents: 'none' }]}>
      <View style={[styles.blob, { top: -160, start: -120, backgroundColor: 'rgba(148,163,184,0.22)' }]} />
      <View style={[styles.blob, { top: 60, end: -180, backgroundColor: 'rgba(214,211,209,0.35)' }]} />
      <View style={[styles.blob, { bottom: -200, start: 40, backgroundColor: 'rgba(203,213,225,0.3)' }]} />
    </View>
  );
}

/** Large-title page header used at the top of tab screens. */
export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: string | null; actions?: ReactNode }) {
  return (
    <View style={styles.pageHeader}>
      <View style={{ flex: 1, minWidth: 0 }}>
        <Txt style={styles.pageTitle} numberOfLines={1}>{title}</Txt>
        {subtitle ? <Txt muted size={13} numberOfLines={2} style={{ marginTop: 2 }}>{subtitle}</Txt> : null}
      </View>
      {actions ? <View style={styles.rowGap8}>{actions}</View> : null}
    </View>
  );
}

/** Compact glass header with a back button (stack screens). */
export function StackHeader({ title, subtitle, actions, onBack, children }: { title?: string; subtitle?: string | null; actions?: ReactNode; onBack?: () => void; children?: ReactNode }) {
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const { t, rtl } = useI18n();
  const back = onBack ?? (() => (router.canGoBack() ? router.back() : router.replace('/inbox')));
  return (
    <Glass strong style={[styles.stackHeader, { paddingTop: insets.top + 6 }]}>
      <View style={styles.stackHeaderRow}>
        <IconButton icon="arrow_back" label={t('common.back')} onPress={back} flip={rtl} />
        {children ?? (
          <View style={{ flex: 1, minWidth: 0 }}>
            {title ? <Txt weight="700" size={16} numberOfLines={1}>{title}</Txt> : null}
            {subtitle ? <Txt muted size={12} numberOfLines={1}>{subtitle}</Txt> : null}
          </View>
        )}
        {actions ? <View style={styles.rowGap4}>{actions}</View> : null}
      </View>
    </Glass>
  );
}

// ---------------------------------------------------------------- surfaces

export function Card({ children, style, padded = true }: { children?: ReactNode; style?: StyleProp<ViewStyle>; padded?: boolean }) {
  return <View style={[styles.card, padded && { padding: 16 }, style]}>{children}</View>;
}

export function SectionTitle({ icon, children, actions }: { icon?: string; children: ReactNode; actions?: ReactNode }) {
  return (
    <View style={[styles.rowGap8, { marginBottom: 10 }]}>
      {icon ? <Icon name={icon} size={18} color={colors.text2} /> : null}
      <Txt weight="700" size={15} style={{ flex: 1 }}>{children}</Txt>
      {actions}
    </View>
  );
}

// ---------------------------------------------------------------- buttons

type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger';

export function Button({
  children,
  onPress,
  variant = 'secondary',
  size = 'md',
  icon,
  loading,
  disabled,
  style,
  full,
  haptic = true,
}: {
  children?: ReactNode;
  onPress?: () => void;
  variant?: ButtonVariant;
  size?: 'sm' | 'md' | 'lg';
  icon?: string;
  loading?: boolean;
  disabled?: boolean;
  style?: StyleProp<ViewStyle>;
  full?: boolean;
  haptic?: boolean;
}) {
  const { rtl } = useI18n();
  const fg = variant === 'primary' || variant === 'danger' ? '#fff' : colors.text;
  const height = size === 'sm' ? 34 : size === 'lg' ? 52 : 44;
  return (
    <Pressable
      accessibilityRole="button"
      disabled={disabled || loading}
      onPress={() => {
        if (haptic) tap();
        onPress?.();
      }}
      style={({ pressed }) => [
        styles.button,
        { height, paddingHorizontal: size === 'sm' ? 12 : 18 },
        variant === 'primary' && styles.buttonPrimary,
        variant === 'secondary' && styles.buttonSecondary,
        variant === 'danger' && { backgroundColor: colors.badSolid },
        full && { alignSelf: 'stretch' },
        (disabled || loading) && { opacity: 0.45 },
        pressed && { opacity: 0.75, transform: [{ scale: 0.98 }] },
        style,
      ]}>
      {loading ? <ActivityIndicator size="small" color={fg} /> : icon ? <Icon name={icon} size={size === 'sm' ? 16 : 18} color={fg} flip={rtl} /> : null}
      {children ? (
        <Txt weight="600" size={size === 'sm' ? 13 : 15} style={{ color: fg }} numberOfLines={1}>
          {children}
        </Txt>
      ) : null}
    </Pressable>
  );
}

export function IconButton({
  icon,
  label,
  onPress,
  size = 38,
  color = colors.text2,
  filled,
  disabled,
  flip,
  badge,
}: {
  icon: string;
  label: string;
  onPress?: () => void;
  size?: number;
  color?: string;
  filled?: boolean;
  disabled?: boolean;
  flip?: boolean;
  badge?: number;
}) {
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={label}
      disabled={disabled}
      hitSlop={6}
      onPress={() => {
        tap();
        onPress?.();
      }}
      style={({ pressed }) => [
        { width: size, height: size, borderRadius: size / 2, alignItems: 'center', justifyContent: 'center' },
        filled && { backgroundColor: 'rgba(255,255,255,0.8)', ...shadow },
        pressed && { backgroundColor: colors.fill2 },
        disabled && { opacity: 0.4 },
      ]}>
      <Icon name={icon} size={Math.round(size * 0.53)} color={color} flip={flip} />
      {badge ? <CountBadge count={badge} style={{ position: 'absolute', top: 0, end: 0 }} /> : null}
    </Pressable>
  );
}

export function CountBadge({ count, style }: { count: number; style?: StyleProp<ViewStyle> }) {
  if (!count) return null;
  return (
    <View style={[styles.countBadge, style]}>
      <Txt size={10} weight="700" style={{ color: '#fff' }}>{count > 99 ? '99+' : count}</Txt>
    </View>
  );
}

// ---------------------------------------------------------------- inputs

export function Field({ label, hint, error, children, style }: { label?: string; hint?: string | null; error?: string | null; children: ReactNode; style?: StyleProp<ViewStyle> }) {
  return (
    <View style={[{ gap: 6 }, style]}>
      {label ? <Txt size={13} weight="600" style={{ color: colors.text2 }}>{label}</Txt> : null}
      {children}
      {error ? <Txt size={12} style={{ color: colors.bad }}>{error}</Txt> : hint ? <Txt size={12} muted>{hint}</Txt> : null}
    </View>
  );
}

export function Input({ style, ltr, multiline, ...rest }: TextInputProps & { ltr?: boolean }) {
  const { rtl } = useI18n();
  const [focused, setFocused] = useState(false);
  return (
    <TextInput
      placeholderTextColor={colors.faint}
      {...rest}
      multiline={multiline}
      onFocus={(e) => {
        setFocused(true);
        rest.onFocus?.(e);
      }}
      onBlur={(e) => {
        setFocused(false);
        rest.onBlur?.(e);
      }}
      style={[
        styles.input,
        multiline && { minHeight: 96, paddingTop: 12, paddingBottom: 12, textAlignVertical: 'top' },
        focused && { borderColor: 'rgba(0,0,0,0.3)', backgroundColor: '#fff' },
        { textAlign: ltr ? 'left' : rtl ? 'right' : 'left', writingDirection: ltr ? 'ltr' : rtl ? 'rtl' : 'ltr' },
        Platform.OS === 'web' && ({ outlineStyle: 'none' } as unknown as TextStyle),
        style,
      ]}
    />
  );
}

export function Switch({ value, onChange, label, disabled }: { value: boolean; onChange: (v: boolean) => void; label?: string; disabled?: boolean }) {
  return (
    <Pressable
      accessibilityRole="switch"
      accessibilityState={{ checked: value, disabled }}
      disabled={disabled}
      onPress={() => {
        tap();
        onChange(!value);
      }}
      style={[styles.rowGap8, disabled && { opacity: 0.5 }]}>
      <View style={[styles.switchTrack, { backgroundColor: value ? colors.ink : colors.track, alignItems: value ? 'flex-end' : 'flex-start' }]}>
        <View style={styles.switchThumb} />
      </View>
      {label ? <Txt size={14}>{label}</Txt> : null}
    </Pressable>
  );
}

export function Segmented<T extends string | number>({ value, onChange, options, style }: { value: T; onChange: (v: T) => void; options: { value: T; label: string; icon?: string }[]; style?: StyleProp<ViewStyle> }) {
  return (
    <View style={[styles.segmented, style]} accessibilityRole="tablist">
      {options.map((o) => {
        const active = o.value === value;
        return (
          <Pressable
            key={String(o.value)}
            accessibilityRole="tab"
            accessibilityState={{ selected: active }}
            onPress={() => {
              tap();
              onChange(o.value);
            }}
            style={[styles.segment, active && styles.segmentActive]}>
            {o.icon ? <Icon name={o.icon} size={15} color={active ? colors.text : colors.muted} /> : null}
            <Txt size={13} weight="600" numberOfLines={1} style={{ color: active ? colors.text : colors.muted }}>{o.label}</Txt>
          </Pressable>
        );
      })}
    </View>
  );
}

/** Horizontally scrolling filter chips. */
export function Chips<T extends string>({ value, onChange, options }: { value: T; onChange: (v: T) => void; options: { value: T; label: string; count?: number; icon?: string }[] }) {
  return (
    <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 8, paddingHorizontal: 16 }}>
      {options.map((o) => {
        const active = o.value === value;
        return (
          <Pressable
            key={o.value}
            onPress={() => {
              tap();
              onChange(o.value);
            }}
            style={[styles.chip, active ? styles.chipActive : null]}>
            {o.icon ? <Icon name={o.icon} size={15} color={active ? '#fff' : colors.text2} /> : null}
            <Txt size={13} weight="600" style={{ color: active ? '#fff' : colors.text2 }}>{o.label}</Txt>
            {o.count ? (
              <View style={[styles.chipCount, active && { backgroundColor: 'rgba(255,255,255,0.22)' }]}>
                <Txt size={11} weight="700" style={{ color: active ? '#fff' : colors.text2 }}>{o.count}</Txt>
              </View>
            ) : null}
          </Pressable>
        );
      })}
    </ScrollView>
  );
}

export type Tone = 'neutral' | 'ok' | 'warn' | 'bad' | 'ink';
const TONES: Record<Tone, { bg: string; fg: string }> = {
  neutral: { bg: colors.fill2, fg: colors.text2 },
  ok: { bg: colors.okBg, fg: colors.ok },
  warn: { bg: colors.warnBg, fg: colors.warn },
  bad: { bg: colors.badBg, fg: colors.bad },
  ink: { bg: colors.ink, fg: '#fff' },
};

export function Badge({ children, tone = 'neutral', icon }: { children: ReactNode; tone?: Tone; icon?: string }) {
  const c = TONES[tone];
  return (
    <View style={[styles.badge, { backgroundColor: c.bg }]}>
      {icon ? <Icon name={icon} size={12} color={c.fg} /> : null}
      <Txt size={11} weight="700" style={{ color: c.fg }} numberOfLines={1}>{children}</Txt>
    </View>
  );
}

// ---------------------------------------------------------------- media

/** Image served by the API (needs the session headers) or any absolute / data URL. */
export function AuthImage({ src, style, contentFit = 'cover' }: { src?: string | null; style?: StyleProp<ViewStyle>; contentFit?: 'cover' | 'contain' }) {
  if (!src) return <View style={[{ backgroundColor: colors.fill2 }, style]} />;
  const isApi = src.startsWith('/api/');
  const source = isApi ? { uri: apiUrl(src), headers: authHeaders() } : { uri: src };
  return <Image source={source} style={style as never} contentFit={contentFit} transition={150} />;
}

export function Avatar({ name, src, size = 40 }: { name?: string | null; src?: string | null; size?: number }) {
  const initials = (name || '?').trim().split(/\s+/).slice(0, 2).map((p) => p[0]).join('').toUpperCase();
  const [failed, setFailed] = useState(false);
  if (src && !failed) {
    return (
      <Image
        source={src.startsWith('/api/') ? { uri: apiUrl(src), headers: authHeaders() } : { uri: src }}
        style={{ width: size, height: size, borderRadius: size / 2, backgroundColor: colors.fill2 }}
        onError={() => setFailed(true)}
      />
    );
  }
  return (
    <View style={{ width: size, height: size, borderRadius: size / 2, backgroundColor: colors.fill2, alignItems: 'center', justifyContent: 'center' }}>
      <Txt weight="700" size={size * 0.36} style={{ color: colors.text2 }}>{initials}</Txt>
    </View>
  );
}

// ---------------------------------------------------------------- states

export function Loading({ style }: { style?: StyleProp<ViewStyle> }) {
  return (
    <View style={[{ paddingVertical: 64, alignItems: 'center' }, style]}>
      <ActivityIndicator color={colors.muted} />
    </View>
  );
}

export function EmptyState({ icon = 'inbox', title, text, action }: { icon?: string; title: string; text?: string | null; action?: ReactNode }) {
  return (
    <View style={styles.empty}>
      <View style={styles.emptyIcon}>
        <Icon name={icon} size={26} color="#fff" duo />
      </View>
      <Txt weight="700" size={16} style={{ textAlign: 'center' }}>{title}</Txt>
      {text ? <Txt muted size={14} style={{ textAlign: 'center', maxWidth: 300 }}>{text}</Txt> : null}
      {action ? <View style={{ marginTop: 10 }}>{action}</View> : null}
    </View>
  );
}

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const { t } = useI18n();
  const message = error instanceof Error ? error.message : t('errors.generic');
  return (
    <EmptyState
      icon="warning"
      title={t('errors.title')}
      text={message}
      action={onRetry ? <Button icon="refresh" onPress={onRetry}>{t('common.retry')}</Button> : null}
    />
  );
}

// ---------------------------------------------------------------- list rows

export function ListRow({
  icon,
  leading,
  title,
  subtitle,
  trailing,
  onPress,
  chevron = !!onPress,
  danger,
  last,
}: {
  icon?: string;
  leading?: ReactNode;
  title: ReactNode;
  subtitle?: ReactNode;
  trailing?: ReactNode;
  onPress?: () => void;
  chevron?: boolean;
  danger?: boolean;
  last?: boolean;
}) {
  const { rtl } = useI18n();
  return (
    <Pressable
      disabled={!onPress}
      onPress={() => {
        tap();
        onPress?.();
      }}
      style={({ pressed }) => [styles.listRow, !last && styles.listRowLine, pressed && { backgroundColor: colors.fill }]}>
      {leading ?? (icon ? (
        <View style={[styles.listIcon, danger && { backgroundColor: colors.badBg }]}>
          <Icon name={icon} size={18} color={danger ? colors.bad : colors.text2} />
        </View>
      ) : null)}
      <View style={{ flex: 1, minWidth: 0 }}>
        {typeof title === 'string' ? <Txt size={15} weight="500" numberOfLines={1} style={danger && { color: colors.bad }}>{title}</Txt> : title}
        {subtitle ? (typeof subtitle === 'string' ? <Txt muted size={12} numberOfLines={2}>{subtitle}</Txt> : subtitle) : null}
      </View>
      {trailing}
      {chevron ? <Icon name="arrow_back" size={16} color={colors.faint} style={{ transform: [{ scaleX: rtl ? 1 : -1 }] }} /> : null}
    </Pressable>
  );
}

// ---------------------------------------------------------------- sheet (bottom modal)

export function Sheet({ visible, onClose, title, children, footer, scroll = true }: { visible: boolean; onClose: () => void; title?: string; children: ReactNode; footer?: ReactNode; scroll?: boolean }) {
  const insets = useSafeAreaInsets();
  const { t } = useI18n();
  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose} statusBarTranslucent>
      <KeyboardAvoidingView behavior={Platform.OS === 'ios' ? 'padding' : undefined} style={{ flex: 1, justifyContent: 'flex-end' }}>
        <Pressable style={[StyleSheet.absoluteFill, { backgroundColor: 'rgba(0,0,0,0.28)' }]} onPress={onClose} accessibilityLabel={t('common.close')} />
        <Glass strong style={[styles.sheet, { paddingBottom: Math.max(insets.bottom, 12) }]}>
          <View style={styles.sheetGrip} />
          {title ? (
            <View style={[styles.rowGap8, { paddingHorizontal: 20, paddingBottom: 6 }]}>
              <Txt weight="700" size={18} style={{ flex: 1 }}>{title}</Txt>
              <IconButton icon="close" label={t('common.close')} onPress={onClose} size={34} />
            </View>
          ) : null}
          {scroll ? (
            <ScrollView style={{ maxHeight: 560 }} contentContainerStyle={{ paddingHorizontal: 20, paddingVertical: 8, gap: 12 }} keyboardShouldPersistTaps="handled">
              {children}
            </ScrollView>
          ) : (
            <View style={{ paddingHorizontal: 20, paddingVertical: 8, gap: 12 }}>{children}</View>
          )}
          {footer ? <View style={styles.sheetFooter}>{footer}</View> : null}
        </Glass>
      </KeyboardAvoidingView>
    </Modal>
  );
}

// ---------------------------------------------------------------- toasts

type ToastItem = { id: number; text: string; tone: 'ok' | 'bad' | 'info' };
let toasts: ToastItem[] = [];
let toastSeq = 0;
const toastListeners = new Set<() => void>();
function pushToast(text: string, tone: ToastItem['tone']) {
  const id = ++toastSeq;
  toasts = [...toasts, { id, text, tone }].slice(-3);
  toastListeners.forEach((l) => l());
  setTimeout(() => {
    toasts = toasts.filter((x) => x.id !== id);
    toastListeners.forEach((l) => l());
  }, 3200);
}
export const toast = {
  success: (text: string) => {
    tap('success');
    pushToast(text, 'ok');
  },
  error: (text: string) => {
    tap('warning');
    pushToast(text, 'bad');
  },
  info: (text: string) => pushToast(text, 'info'),
};

export function ToastHost() {
  const items = useSyncExternalStore(
    (l) => {
      toastListeners.add(l);
      return () => toastListeners.delete(l);
    },
    () => toasts,
    () => toasts,
  );
  const insets = useSafeAreaInsets();
  return (
    <View style={[styles.toastHost, { top: insets.top + 8, pointerEvents: 'box-none' }]}>
      {items.map((item) => (
        <ToastView key={item.id} item={item} />
      ))}
    </View>
  );
}

function ToastView({ item }: { item: ToastItem }) {
  const [shown, setShown] = useState(false);
  useEffect(() => {
    const id = setTimeout(() => setShown(true), 10);
    return () => clearTimeout(id);
  }, []);
  const icon = item.tone === 'ok' ? 'check_circle' : item.tone === 'bad' ? 'error' : 'info';
  const color = item.tone === 'ok' ? colors.ok : item.tone === 'bad' ? colors.bad : colors.text2;
  return (
    <Glass strong style={[styles.toast, { opacity: shown ? 1 : 0 }]}>
      <Icon name={icon} size={18} color={color} />
      <Txt size={14} style={{ flexShrink: 1 }}>{item.text}</Txt>
    </Glass>
  );
}

// ---------------------------------------------------------------- styles

export const styles = StyleSheet.create({
  text: { fontFamily: Platform.select({ web: '-apple-system, BlinkMacSystemFont, "SF Pro Text", "SF Arabic", "Segoe UI", "Noto Sans Arabic", Tahoma, system-ui, sans-serif', default: undefined }) },
  blob: { position: 'absolute', width: 420, height: 420, borderRadius: 210, opacity: 0.9, ...Platform.select({ web: { filter: 'blur(40px)' } as object, default: {} }) },
  rowGap4: { flexDirection: 'row', alignItems: 'center', gap: 4 },
  rowGap8: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  pageHeader: { flexDirection: 'row', alignItems: 'center', gap: 12, paddingHorizontal: 20, paddingTop: 8, paddingBottom: 14 },
  pageTitle: { fontSize: 30, fontWeight: '800', letterSpacing: -0.6 },
  stackHeader: { borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.line, paddingBottom: 8, paddingHorizontal: 8, zIndex: 10 },
  stackHeaderRow: { flexDirection: 'row', alignItems: 'center', gap: 6, minHeight: 44 },
  card: { backgroundColor: 'rgba(255,255,255,0.74)', borderRadius: radius.lg, borderWidth: 1, borderColor: colors.glassEdge, ...shadow },
  button: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 6, borderRadius: radius.pill },
  buttonPrimary: { backgroundColor: colors.ink, ...Platform.select({ web: { boxShadow: '0 10px 24px -12px rgba(0,0,0,0.6)' } as object, default: { shadowColor: '#000', shadowOpacity: 0.25, shadowRadius: 10, shadowOffset: { width: 0, height: 6 } } }) },
  buttonSecondary: { backgroundColor: 'rgba(255,255,255,0.85)', borderWidth: 1, borderColor: colors.line },
  countBadge: { minWidth: 18, height: 18, borderRadius: 9, paddingHorizontal: 5, backgroundColor: colors.badSolid, alignItems: 'center', justifyContent: 'center' },
  input: { minHeight: 46, borderRadius: radius.md, borderWidth: 1, borderColor: colors.line, backgroundColor: 'rgba(255,255,255,0.75)', paddingHorizontal: 14, fontSize: 15, color: colors.text },
  switchTrack: { width: 44, height: 26, borderRadius: 13, padding: 2, justifyContent: 'center' },
  switchThumb: { width: 22, height: 22, borderRadius: 11, backgroundColor: '#fff', ...shadow },
  segmented: { flexDirection: 'row', backgroundColor: colors.track, borderRadius: radius.pill, padding: 3 },
  segment: { flex: 1, flexDirection: 'row', gap: 5, alignItems: 'center', justifyContent: 'center', height: 34, borderRadius: radius.pill, paddingHorizontal: 10 },
  segmentActive: { backgroundColor: '#fff', ...shadow },
  chip: { flexDirection: 'row', alignItems: 'center', gap: 6, height: 36, paddingHorizontal: 14, borderRadius: radius.pill, backgroundColor: 'rgba(255,255,255,0.8)', borderWidth: 1, borderColor: colors.line },
  chipActive: { backgroundColor: colors.ink, borderColor: colors.ink },
  chipCount: { minWidth: 20, height: 20, paddingHorizontal: 5, borderRadius: 10, backgroundColor: colors.fill2, alignItems: 'center', justifyContent: 'center' },
  badge: { flexDirection: 'row', alignItems: 'center', gap: 3, paddingHorizontal: 8, paddingVertical: 3, borderRadius: radius.pill, alignSelf: 'flex-start' },
  empty: { alignItems: 'center', justifyContent: 'center', gap: 8, paddingHorizontal: 28, paddingVertical: 56 },
  emptyIcon: { width: 56, height: 56, borderRadius: 18, backgroundColor: colors.ink, alignItems: 'center', justifyContent: 'center', marginBottom: 6 },
  listRow: { flexDirection: 'row', alignItems: 'center', gap: 12, paddingHorizontal: 14, paddingVertical: 12, minHeight: 54 },
  listRowLine: { borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.line },
  listIcon: { width: 34, height: 34, borderRadius: 11, backgroundColor: colors.fill2, alignItems: 'center', justifyContent: 'center' },
  sheet: { borderTopLeftRadius: 26, borderTopRightRadius: 26, paddingTop: 8, ...shadowFloat },
  sheetGrip: { alignSelf: 'center', width: 38, height: 5, borderRadius: 3, backgroundColor: colors.lineStrong, marginBottom: 8 },
  sheetFooter: { flexDirection: 'row', gap: 10, paddingHorizontal: 20, paddingTop: 12, borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: colors.line, marginTop: 6 },
  toastHost: { position: 'absolute', start: 0, end: 0, alignItems: 'center', gap: 8, zIndex: 1000 },
  toast: { flexDirection: 'row', alignItems: 'center', gap: 8, paddingHorizontal: 16, paddingVertical: 11, borderRadius: radius.pill, maxWidth: 360, ...shadowFloat },
});
