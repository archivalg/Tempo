import { Ionicons } from '@expo/vector-icons'
import { Redirect, Tabs } from 'expo-router'
import { useSession } from '../../src/auth/session'
import { Loading } from '../../src/ui/kit'
import { colors } from '../../src/ui/theme'

export default function AppLayout() {
  const { state } = useSession()
  if (state === 'loading') return <Loading />
  if (state === 'signedOut') return <Redirect href="/login" />
  const icon = (name: keyof typeof Ionicons.glyphMap) => ({ color, size }: { color: import('react-native').ColorValue; size: number }) => <Ionicons name={name} color={color} size={size} />
  return (
    <Tabs screenOptions={{ headerStyle: { backgroundColor: colors.charcoal }, headerTintColor: colors.onDark, tabBarActiveTintColor: colors.green, tabBarLabelStyle: { fontSize: 12 } }}>
      <Tabs.Screen name="shifts" options={{ title: 'Shifts', tabBarIcon: icon('calendar-outline') }} />
      <Tabs.Screen name="offers" options={{ title: 'Offers', tabBarIcon: icon('swap-horizontal-outline') }} />
      <Tabs.Screen name="requests" options={{ title: 'Requests', tabBarIcon: icon('create-outline') }} />
      <Tabs.Screen name="attendance" options={{ title: 'Clockings', tabBarIcon: icon('time-outline') }} />
      <Tabs.Screen name="settings" options={{ title: 'Settings', tabBarIcon: icon('settings-outline') }} />
      <Tabs.Screen name="shifts/[id]" options={{ href: null, title: 'Shift' }} />
      <Tabs.Screen name="changes" options={{ href: null, title: 'Roster changes' }} />
      <Tabs.Screen name="notifications" options={{ href: null, title: 'Notifications' }} />
    </Tabs>
  )
}
