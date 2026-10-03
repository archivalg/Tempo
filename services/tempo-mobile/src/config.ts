import Constants from 'expo-constants'

const extra = (Constants.expoConfig?.extra ?? {}) as { appEnv?: string; apiUrl?: string; eas?: { projectId?: string } }

export const APP_ENV = (extra.appEnv ?? 'development') as 'development' | 'test' | 'production'
export const API_URL = (extra.apiUrl ?? 'http://localhost:8017/v1').replace(/\/$/, '')
export const EAS_PROJECT_ID = extra.eas?.projectId || undefined
export const APP_VERSION = Constants.expoConfig?.version ?? '0.0.0'
export const IS_PRODUCTION = APP_ENV === 'production'
