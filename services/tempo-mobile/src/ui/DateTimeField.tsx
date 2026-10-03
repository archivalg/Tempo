import DateTimePicker, { type DateTimePickerEvent } from '@react-native-community/datetimepicker'
import { useState } from 'react'
import { Platform, Pressable, Text, View } from 'react-native'
import { colors, radius, space } from './theme'

/** Date (and optionally time) chooser using the platform's own picker. `value` is a JS Date; the caller converts it to site-local meaning. */
export function DateTimeField({ label, value, onChange, withTime, minimum }: { label: string; value: Date; onChange: (d: Date) => void; withTime?: boolean; minimum?: Date }) {
  const [mode, setMode] = useState<null | 'date' | 'time'>(null)
  const show = (m: 'date' | 'time') => setMode(m)
  const handle = (e: DateTimePickerEvent, d?: Date) => {
    if (Platform.OS === 'android') setMode(null)
    if (e.type === 'dismissed' || !d) return
    const next = new Date(value)
    if (mode === 'time') next.setHours(d.getHours(), d.getMinutes(), 0, 0)
    else { next.setFullYear(d.getFullYear(), d.getMonth(), d.getDate()); if (Platform.OS === 'android' && withTime) setTimeout(() => setMode('time'), 0) }
    onChange(next)
  }
  const text = `${value.toLocaleDateString('en-AU', { weekday: 'short', day: 'numeric', month: 'short', year: 'numeric' })}${withTime ? ` ${value.toLocaleTimeString('en-AU', { hour: '2-digit', minute: '2-digit', hour12: false })}` : ''}`
  return (
    <View style={{ gap: 4 }}>
      <Text style={{ fontSize: 14, fontWeight: '600', color: colors.ink2 }}>{label}</Text>
      <Pressable accessibilityRole="button" accessibilityLabel={`${label}: ${text}`} onPress={() => show('date')} style={{ minHeight: 48, borderWidth: 1, borderColor: colors.line, borderRadius: radius.m, paddingHorizontal: space.m, justifyContent: 'center', backgroundColor: colors.surface }}>
        <Text style={{ fontSize: 16, color: colors.ink }}>{text}</Text>
      </Pressable>
      {mode && <DateTimePicker value={value} mode={Platform.OS === 'ios' && withTime ? 'datetime' : mode} minimumDate={minimum} onChange={handle} is24Hour />}
    </View>
  )
}
