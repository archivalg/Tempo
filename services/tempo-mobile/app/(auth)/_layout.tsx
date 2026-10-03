import { Stack } from 'expo-router'
import { colors } from '../../src/ui/theme'

export default function AuthLayout() {
  return <Stack screenOptions={{ headerStyle: { backgroundColor: colors.charcoal }, headerTintColor: colors.onDark, headerTitle: 'Tempo' }} />
}
