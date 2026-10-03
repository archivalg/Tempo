import type { ExpoConfig } from 'expo/config'

/**
 * One codebase, three configurations. Choose with APP_ENV=development|test|production at build/start time.
 * Nothing secret lives here: the app only knows the PUBLIC API address. Credentials come from the person signing in
 * (employee session) or from a manager enrolling a kiosk device (device credential), and live in the device's secure storage.
 *
 * Bundle identifiers below are PROPOSALS (reverse-DNS of ensemblesolutions.com.au). They must be confirmed before the
 * first TestFlight / Play upload because they cannot be changed afterwards.
 */
type Env = 'development' | 'test' | 'production'
const env = (process.env.APP_ENV ?? 'development') as Env

const BASE_ID = 'au.com.ensemblesolutions.tempo'
const CONFIG: Record<Env, { name: string; id: string; apiUrl: string; scheme: string }> = {
  // Android emulators reach the host's loopback as 10.0.2.2; iOS simulators use localhost.
  development: { name: 'Tempo (Dev)', id: `${BASE_ID}.dev`, apiUrl: 'http://localhost:8017/v1', scheme: 'tempo-dev' },
  // Tempo has one deployed environment today; "test" points at it. A separate UAT API would change only this line.
  test: { name: 'Tempo (Test)', id: `${BASE_ID}.test`, apiUrl: 'https://tempo.ensemblesolutions.com.au/v1', scheme: 'tempo-test' },
  production: { name: 'Tempo', id: BASE_ID, apiUrl: 'https://tempo.ensemblesolutions.com.au/v1', scheme: 'tempo' },
}
const c = CONFIG[env]

const config: ExpoConfig = {
  name: c.name,
  slug: 'tempo-mobile',
  version: '0.1.0',
  orientation: 'default',
  icon: './assets/icon.png',
  scheme: c.scheme,
  userInterfaceStyle: 'light',
  ios: {
    bundleIdentifier: c.id,
    supportsTablet: true,
    infoPlist: {
      NSCameraUsageDescription: 'Tempo uses the camera on a kiosk tablet to scan an employee’s QR code for clocking in.',
      ITSAppUsesNonExemptEncryption: false,
    },
  },
  android: {
    package: c.id,
    adaptiveIcon: { foregroundImage: './assets/android-icon-foreground.png', backgroundImage: './assets/android-icon-background.png', monochromeImage: './assets/android-icon-monochrome.png' },
    permissions: ['CAMERA', 'POST_NOTIFICATIONS'],
    predictiveBackGestureEnabled: false,
  },
  plugins: [
    'expo-router',
    ['expo-splash-screen', { image: './assets/splash-icon.png', imageWidth: 200, backgroundColor: '#1b262b' }],
    'expo-secure-store',
    ['expo-notifications', { color: '#069b57' }],
    ['expo-camera', { cameraPermission: 'Tempo uses the camera on a kiosk tablet to scan an employee’s QR code for clocking in.', recordAudioAndroid: false }],
    '@react-native-community/datetimepicker',
  ],
  experiments: { typedRoutes: false },
  extra: {
    appEnv: env,
    // EXPO_PUBLIC_API_URL lets a developer or CI point a build at another API without editing code.
    apiUrl: process.env.EXPO_PUBLIC_API_URL ?? c.apiUrl,
    // Filled in by `eas init` once an Expo project exists; required for push tokens. Not a secret.
    eas: { projectId: process.env.EAS_PROJECT_ID ?? '' },
  },
}
export default config
