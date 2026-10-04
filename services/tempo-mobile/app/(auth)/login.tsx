import { Redirect, useRouter } from 'expo-router'
import { useState } from 'react'
import { Image, KeyboardAvoidingView, Platform, View } from 'react-native'
import { SafeAreaView } from 'react-native-safe-area-context'
import { ApiError } from '../../src/api/client'
import { useSession } from '../../src/auth/session'
import { Banner, Button, Field, H1, P } from '../../src/ui/kit'
import { colors, space } from '../../src/ui/theme'

export default function Login() {
  const { state, signIn, submitMfa, mfaChallenge, notice } = useSession()
  const router = useRouter()
  const [u, setU] = useState('')
  const [p, setP] = useState('')
  const [code, setCode] = useState('')
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  if (state === 'signedIn') return <Redirect href="/shifts" />
  const go = async () => {
    setBusy(true); setErr(null)
    try { if (mfaChallenge) await submitMfa(code); else await signIn(u, p) } catch (e) { setErr(e instanceof ApiError ? (e.kind === 'network' || e.kind === 'timeout' ? 'No connection to Tempo. You have not been signed in.' : e.message) : 'Could not sign in.') } finally { setBusy(false) }
  }
  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: colors.charcoal }}>
      <KeyboardAvoidingView behavior={Platform.OS === 'ios' ? 'padding' : undefined} style={{ flex: 1, justifyContent: 'center', padding: space.xl, gap: space.l }}>
        <Image source={require('../../assets/lockup-dark.png')} style={{ width: 220, height: 71, resizeMode: 'contain', alignSelf: 'center' }} accessibilityLabel="Tempo" />
        <View style={{ backgroundColor: colors.surface, borderRadius: 14, padding: space.xl, gap: space.m }}>
          <H1>Sign in</H1>
          {notice ? <Banner tone="warn" title={notice} /> : null}
          {mfaChallenge ? (
            <>
              <P>Enter your 6-digit code: from your authenticator app, or the code we just emailed you.</P>
              <Field label="Code" value={code} onChangeText={setCode} keyboardType="number-pad" maxLength={8} autoComplete="one-time-code" />
            </>
          ) : (
            <>
              <Field label="Username" value={u} onChangeText={setU} autoCapitalize="none" autoCorrect={false} autoComplete="username" textContentType="username" />
              <Field label="Password" value={p} onChangeText={setP} secureTextEntry autoComplete="password" textContentType="password" />
            </>
          )}
          {err ? <Banner tone="bad" title={err} /> : null}
          <Button title={mfaChallenge ? 'Verify' : 'Sign in'} onPress={() => void go()} busy={busy} disabled={mfaChallenge ? code.length < 6 : !u || !p} testID="sign-in" />
          <P small muted>Your manager sends you an invitation link. Open it on this phone to choose your username and password.</P>
        </View>
        <View style={{ gap: space.s }}>
          <Button title="Set up this device as a kiosk" kind="secondary" onPress={() => router.push('/kiosk/setup')} />
        </View>
      </KeyboardAvoidingView>
    </SafeAreaView>
  )
}
