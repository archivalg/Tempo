import { type ReactNode } from 'react'
import { ActivityIndicator, Pressable, RefreshControl, ScrollView, StyleSheet, Switch, Text, TextInput, View, type TextInputProps, type ViewStyle } from 'react-native'
import { SafeAreaView } from 'react-native-safe-area-context'
import { useOnline } from '../net/network'
import { colors, radius, space } from './theme'

export function Screen({ children, onRefresh, refreshing = false, scroll = true, style }: { children: ReactNode; onRefresh?: () => void; refreshing?: boolean; scroll?: boolean; style?: ViewStyle }) {
  const online = useOnline()
  const body = (
    <View style={[{ padding: space.l, gap: space.m }, style]}>
      {!online && <Banner tone="warn" icon="⚠" title="No connection">What you see may be out of date. Anything you change will not be saved until you are back online.</Banner>}
      {children}
    </View>
  )
  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: colors.canvas }} edges={['left', 'right']}>
      {scroll ? <ScrollView refreshControl={onRefresh ? <RefreshControl refreshing={refreshing} onRefresh={onRefresh} /> : undefined} keyboardShouldPersistTaps="handled">{body}</ScrollView> : body}
    </SafeAreaView>
  )
}

export function Card({ children, onPress, accessibilityLabel }: { children: ReactNode; onPress?: () => void; accessibilityLabel?: string }) {
  const inner = <View style={s.card}>{children}</View>
  return onPress ? <Pressable onPress={onPress} accessibilityRole="button" accessibilityLabel={accessibilityLabel} style={({ pressed }) => ({ opacity: pressed ? 0.85 : 1 })}>{inner}</Pressable> : inner
}

export const H1 = ({ children }: { children: ReactNode }) => <Text style={s.h1} accessibilityRole="header">{children}</Text>
export const H2 = ({ children }: { children: ReactNode }) => <Text style={s.h2} accessibilityRole="header">{children}</Text>
export const P = ({ children, muted, small }: { children: ReactNode; muted?: boolean; small?: boolean }) => <Text style={[s.p, muted && { color: colors.muted }, small && { fontSize: 13 }]}>{children}</Text>

export function Button({ title, onPress, kind = 'primary', disabled, busy, testID }: { title: string; onPress: () => void; kind?: 'primary' | 'secondary' | 'danger'; disabled?: boolean; busy?: boolean; testID?: string }) {
  const bg = kind === 'primary' ? colors.green : kind === 'danger' ? colors.red : colors.surface
  const fg = kind === 'secondary' ? colors.ink : '#fff'
  return (
    <Pressable testID={testID} accessibilityRole="button" accessibilityState={{ disabled: !!disabled || !!busy }} disabled={disabled || busy} onPress={onPress}
      style={({ pressed }) => [s.btn, { backgroundColor: bg, borderColor: kind === 'secondary' ? colors.line : bg, opacity: disabled ? 0.45 : pressed ? 0.85 : 1 }]}>
      {busy ? <ActivityIndicator color={fg} /> : <Text style={{ color: fg, fontSize: 16, fontWeight: '700' }}>{title}</Text>}
    </Pressable>
  )
}

const TONES = {
  ok: { bg: colors.greenBg, fg: colors.greenInk, icon: '✓' }, warn: { bg: colors.amberBg, fg: colors.amberInk, icon: '▲' }, bad: { bg: colors.redBg, fg: colors.redInk, icon: '✕' },
  info: { bg: colors.infoBg, fg: colors.infoInk, icon: 'i' }, neutral: { bg: colors.infoBg, fg: colors.infoInk, icon: '•' },
}
export type Tone = keyof typeof TONES
/** Status is always an icon AND a word, never colour alone. */
export function Pill({ tone, children }: { tone: Tone; children: ReactNode }) {
  const t = TONES[tone]
  return <View style={[s.pill, { backgroundColor: t.bg }]}><Text style={{ color: t.fg, fontWeight: '700', fontSize: 12 }}>{t.icon} {children}</Text></View>
}

export function Banner({ tone, icon, title, children, testID }: { tone: Tone; icon?: string; title: string; children?: ReactNode; testID?: string }) {
  const t = TONES[tone]
  return (
    <View testID={testID} accessibilityRole="alert" style={[s.banner, { backgroundColor: t.bg }]}>
      <Text style={{ color: t.fg, fontWeight: '800', fontSize: 15 }}>{icon ?? t.icon} {title}</Text>
      {children ? <Text style={{ color: t.fg, fontSize: 14, marginTop: 2 }}>{children}</Text> : null}
    </View>
  )
}

export const Loading = ({ label = 'Loading…' }: { label?: string }) => <View style={s.center} accessibilityLabel={label}><ActivityIndicator color={colors.green} /><Text style={{ color: colors.muted, marginTop: space.s }}>{label}</Text></View>
export const Empty = ({ title, children }: { title: string; children?: ReactNode }) => <View style={s.center}><Text style={{ fontWeight: '700', fontSize: 16, color: colors.ink }}>{title}</Text>{children ? <Text style={{ color: colors.muted, textAlign: 'center', marginTop: 4 }}>{children}</Text> : null}</View>
export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return <View style={{ gap: space.s }}><Banner tone="bad" title="Could not load">{message}</Banner>{onRetry ? <Button title="Try again" kind="secondary" onPress={onRetry} /> : null}</View>
}

export function Field({ label, error, ...rest }: { label: string; error?: string | null } & TextInputProps) {
  return (
    <View style={{ gap: 4 }}>
      <Text style={s.label}>{label}</Text>
      <TextInput accessibilityLabel={label} placeholderTextColor={colors.muted} {...rest} style={[s.input, error ? { borderColor: colors.red } : null, rest.style]} />
      {error ? <Text style={{ color: colors.redInk, fontSize: 13 }}>{error}</Text> : null}
    </View>
  )
}

export function Toggle({ label, hint, value, onChange, disabled }: { label: string; hint?: string; value: boolean; onChange: (v: boolean) => void; disabled?: boolean }) {
  return (
    <View style={{ flexDirection: 'row', alignItems: 'center', gap: space.m, opacity: disabled ? 0.5 : 1 }}>
      <View style={{ flex: 1 }}><Text style={{ fontSize: 16, color: colors.ink }}>{label}</Text>{hint ? <Text style={{ color: colors.muted, fontSize: 13 }}>{hint}</Text> : null}</View>
      <Switch accessibilityLabel={label} value={value} onValueChange={onChange} disabled={disabled} trackColor={{ true: colors.green, false: colors.line }} />
    </View>
  )
}

export const Row = ({ children, style }: { children: ReactNode; style?: ViewStyle }) => <View style={[{ flexDirection: 'row', alignItems: 'center', gap: space.s }, style]}>{children}</View>

const s = StyleSheet.create({
  card: { backgroundColor: colors.surface, borderRadius: radius.m, borderWidth: 1, borderColor: colors.line, padding: space.l, gap: space.s },
  h1: { fontSize: 24, fontWeight: '800', color: colors.ink }, h2: { fontSize: 18, fontWeight: '700', color: colors.ink }, p: { fontSize: 16, color: colors.ink2 },
  btn: { minHeight: 48, borderRadius: radius.m, borderWidth: 1, alignItems: 'center', justifyContent: 'center', paddingHorizontal: space.l },
  pill: { alignSelf: 'flex-start', borderRadius: 999, paddingHorizontal: 10, paddingVertical: 4 },
  banner: { borderRadius: radius.m, padding: space.m },
  center: { alignItems: 'center', justifyContent: 'center', padding: space.xl },
  label: { fontSize: 14, fontWeight: '600', color: colors.ink2 },
  input: { minHeight: 48, borderWidth: 1, borderColor: colors.line, borderRadius: radius.m, paddingHorizontal: space.m, fontSize: 16, backgroundColor: colors.surface, color: colors.ink },
})
