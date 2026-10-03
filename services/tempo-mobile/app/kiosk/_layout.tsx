import { Stack } from 'expo-router'

/** The kiosk is a device surface: no tabs, no headers, no way into the employee screens. */
export default function KioskLayout() {
  return <Stack screenOptions={{ headerShown: false, gestureEnabled: false }} />
}
