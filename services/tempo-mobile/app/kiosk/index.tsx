import { CameraView, useCameraPermissions } from 'expo-camera'
import { useKeepAwake } from 'expo-keep-awake'
import { Redirect, useRouter } from 'expo-router'
import { useCallback, useEffect, useReducer, useRef, useState } from 'react'
import { Image, Modal, Pressable, StatusBar, Text, View } from 'react-native'
import { SafeAreaView } from 'react-native-safe-area-context'
import { ApiError } from '../../src/api/client'
import * as store from '../../src/auth/storage'
import { authoriseExit, describeFailure, punch, whoami } from '../../src/kiosk/api'
import { ACTION_LABEL, IDENTIFY, RETURN_AFTER_MS, isSuccess, reduce, type Identity, type KioskAction } from '../../src/kiosk/state'
import { useOnline } from '../../src/net/network'
import { Banner, Button, Field, Loading } from '../../src/ui/kit'
import { colors, space } from '../../src/ui/theme'

const KEYS = ['1', '2', '3', '4', '5', '6', '7', '8', '9']
const hhmm = (iso: string | undefined) => (iso ? new Date(iso).toLocaleTimeString('en-AU', { hour: '2-digit', minute: '2-digit', hour12: false }) : null)

export default function Kiosk() {
  useKeepAwake()
  const router = useRouter()
  const online = useOnline()
  const [dev, setDev] = useState<store.KioskDevice | null | undefined>(undefined)
  const [s, dispatch] = useReducer(reduce, IDENTIFY)
  const [scanning, setScanning] = useState(false)
  const [exiting, setExiting] = useState(false)
  const [revoked, setRevoked] = useState(false)
  const [perm, askPerm] = useCameraPermissions()
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  useEffect(() => { void store.loadKiosk().then(setDev) }, [])

  // Everything returns to the identification screen by itself, clearing the employee's details with it.
  useEffect(() => {
    if (timer.current) clearTimeout(timer.current)
    const idle = s.screen === 'identify' ? (s.workerNo || s.pin ? RETURN_AFTER_MS.identify : 0) : RETURN_AFTER_MS[s.screen]
    if (idle) timer.current = setTimeout(() => dispatch({ type: 'reset' }), idle)
    return () => { if (timer.current) clearTimeout(timer.current) }
  }, [s])

  const identify = useCallback(async (identity: Identity) => {
    if (!dev) return
    dispatch({ type: 'busy' })
    try {
      const w = await whoami(dev, identity)
      dispatch({ type: 'identified', identity, masked: w.masked_identity, state: w.state, actions: w.allowed_actions })
    } catch (e) {
      const f = describeFailure(e)
      if (f.deviceRevoked) setRevoked(true)
      dispatch({ type: 'identify_failed', message: f.message, kind: f.kind })
    }
  }, [dev])

  const doPunch = async (action: KioskAction) => {
    if (!dev || s.screen !== 'choose') return
    dispatch({ type: 'busy' })
    try {
      const r = await punch(dev, s.identity, action)
      dispatch({ type: 'punch_result', action, duplicate: r.duplicate, at: hhmm(r.recorded_at ?? r.clocked_in_at ?? r.clocked_out_at) })
    } catch (e) {
      const f = describeFailure(e)
      if (f.deviceRevoked) setRevoked(true)
      dispatch(f.kind === 'network' ? { type: 'punch_network_failed', action } : { type: 'punch_refused', action, message: f.message })
    }
  }

  if (dev === undefined) return <Loading />
  if (dev === null) return <Redirect href="/kiosk/setup" />
  if (revoked) return (
    <SafeAreaView style={{ flex: 1, backgroundColor: colors.redBg, padding: space.xl, justifyContent: 'center', gap: space.l }}>
      <Banner tone="bad" title="This kiosk has been disabled">A manager has revoked this device. Ask a manager to set it up again, or to leave kiosk mode.</Banner>
      <Button title="Manager: leave kiosk mode" kind="secondary" onPress={() => setExiting(true)} />
      <ExitDialog visible={exiting} onClose={() => setExiting(false)} dev={dev} onExit={async () => { await store.clearKiosk(); router.replace('/login') }} />
    </SafeAreaView>
  )

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: colors.charcoal }}>
      <StatusBar hidden />
      <View style={{ flexDirection: 'row', alignItems: 'center', padding: space.l, justifyContent: 'space-between' }}>
        {/* Long-pressing the logo is the only way out, and it asks for a manager's sign-in. */}
        <Pressable onLongPress={() => setExiting(true)} delayLongPress={1500} accessibilityLabel="Tempo kiosk. Press and hold for manager options."><Image source={require('../../assets/lockup-dark.png')} style={{ width: 150, height: 48, resizeMode: 'contain' }} /></Pressable>
        <Text style={{ color: online ? colors.onDark : colors.amber, fontWeight: '700', fontSize: 16 }}>{online ? '● Connected' : '▲ Not connected: clockings will NOT be recorded'}</Text>
      </View>
      <View style={{ flex: 1, alignItems: 'center', justifyContent: 'center', padding: space.l }}>
        <View style={{ width: '100%', maxWidth: 560, backgroundColor: colors.surface, borderRadius: 18, padding: space.xl, gap: space.l }}>
          {s.screen === 'identify' && (
            <>
              <Text style={{ fontSize: 26, fontWeight: '800', color: colors.ink }}>Clock in or out</Text>
              <View style={{ flexDirection: 'row', gap: space.m }}>
                {(['worker', 'pin'] as const).map((f) => (
                  <Pressable key={f} accessibilityRole="button" accessibilityLabel={f === 'worker' ? 'Worker number' : 'PIN'} onPress={() => dispatch({ type: 'field', f })} style={{ flex: 1, minHeight: 64, borderWidth: 3, borderRadius: 12, borderColor: s.field === f ? colors.focus : colors.line, justifyContent: 'center', paddingHorizontal: space.m }}>
                    <Text style={{ color: colors.muted, fontSize: 13 }}>{f === 'worker' ? 'Worker number' : 'PIN'}</Text>
                    <Text style={{ fontSize: 28, fontWeight: '800', color: colors.ink }}>{f === 'worker' ? s.workerNo || '—' : '•'.repeat(s.pin.length) || '—'}</Text>
                  </Pressable>
                ))}
              </View>
              <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: space.m }}>
                {[...KEYS, 'C', '0', '⌫'].map((k) => (
                  <Pressable key={k} accessibilityRole="button" accessibilityLabel={k === 'C' ? 'Clear' : k === '⌫' ? 'Backspace' : k} onPress={() => dispatch(k === 'C' ? { type: 'clear' } : k === '⌫' ? { type: 'backspace' } : { type: 'digit', d: k })}
                    style={({ pressed }) => ({ width: '30.5%', minHeight: 72, borderRadius: 14, backgroundColor: pressed ? colors.line : colors.canvas, alignItems: 'center', justifyContent: 'center' })}>
                    <Text style={{ fontSize: 30, fontWeight: '700', color: colors.ink }}>{k}</Text>
                  </Pressable>
                ))}
              </View>
              {s.error ? <Banner tone="bad" title={s.error} /> : null}
              <Button title="Continue" busy={s.busy} disabled={!s.workerNo || !s.pin || !online} onPress={() => void identify({ mode: 'pin', workerNo: s.workerNo, pin: s.pin })} testID="kiosk-continue" />
              <Button title="Scan my QR code from the Tempo app" kind="secondary" disabled={!online} onPress={() => { if (!perm?.granted) void askPerm(); setScanning(true) }} />
            </>
          )}
          {s.screen === 'choose' && (
            <>
              <Text style={{ fontSize: 26, fontWeight: '800', color: colors.ink }}>Hello, worker {s.masked}</Text>
              <Text style={{ fontSize: 20, color: colors.ink2 }}>{s.stateLabel}</Text>
              {s.error ? <Banner tone="bad" title={s.error} /> : null}
              {s.actions.map((a) => <Button key={a} title={ACTION_LABEL[a]} kind={a === 'clock_out' || a === 'clock_in' ? 'primary' : 'secondary'} busy={s.busy} disabled={!online} onPress={() => void doPunch(a)} testID={`kiosk-${a}`} />)}
              <Button title="Cancel" kind="secondary" onPress={() => dispatch({ type: 'reset' })} />
            </>
          )}
          {s.screen === 'result' && (
            <View style={{ alignItems: 'center', gap: space.m, padding: space.l }} accessibilityLiveRegion="assertive">
              <Text style={{ fontSize: 72, color: isSuccess(s) ? colors.green : colors.red }}>{isSuccess(s) ? '✓' : '✕'}</Text>
              <Text style={{ fontSize: 28, fontWeight: '800', textAlign: 'center', color: isSuccess(s) ? colors.greenInk : colors.redInk }} testID="kiosk-result">{s.message}</Text>
              <Text style={{ color: colors.muted }}>This screen clears by itself.</Text>
              <Button title="Done" kind="secondary" onPress={() => dispatch({ type: 'reset' })} />
            </View>
          )}
        </View>
      </View>
      <Modal visible={scanning} animationType="slide" onRequestClose={() => setScanning(false)}>
        <SafeAreaView style={{ flex: 1, backgroundColor: '#000' }}>
          {perm?.granted ? (
            <CameraView style={{ flex: 1 }} facing="front" barcodeScannerSettings={{ barcodeTypes: ['qr'] }} onBarcodeScanned={(r) => { if (r.data?.startsWith('tqr_')) { setScanning(false); void identify({ mode: 'qr', token: r.data }) } }} />
          ) : <View style={{ flex: 1, justifyContent: 'center', padding: space.xl }}><Banner tone="warn" title="Camera permission needed">Allow the camera to scan QR codes, or use your number and PIN.</Banner></View>}
          <View style={{ padding: space.l }}><Button title="Cancel" kind="secondary" onPress={() => setScanning(false)} /></View>
        </SafeAreaView>
      </Modal>
      <ExitDialog visible={exiting} onClose={() => setExiting(false)} dev={dev} onExit={async () => { await store.clearKiosk(); router.replace('/login') }} />
    </SafeAreaView>
  )
}

/** Leaving or reconfiguring kiosk mode needs a manager for THIS device's company and site. Without it the tablet stays a kiosk. */
function ExitDialog({ visible, onClose, dev, onExit }: { visible: boolean; onClose: () => void; dev: store.KioskDevice; onExit: () => Promise<void> }) {
  const [u, setU] = useState('')
  const [p, setP] = useState('')
  const [code, setCode] = useState('')
  const [challenge, setChallenge] = useState<string | null>(null)
  const [revoke, setRevoke] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const reset = () => { setU(''); setP(''); setCode(''); setChallenge(null); setErr(null); setRevoke(false); onClose() }
  const go = async () => {
    setBusy(true); setErr(null)
    try {
      const r = await authoriseExit(dev, { username: u, password: p, challenge: challenge ?? undefined, code: code || undefined, purpose: 'exit', revoke_device: revoke })
      if (r.mfa_required) { setChallenge(r.challenge ?? null); return }
      if (r.authorised) { reset(); await onExit() }
    } catch (e) {
      const a = e as ApiError
      setErr(a.kind === 'network' ? 'Cannot reach Tempo, so the manager could not be checked. The kiosk stays on.' : a.status === 403 ? 'That person is not a manager for this kiosk.' : 'Sign-in failed.')
    } finally { setBusy(false) }
  }
  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={reset}>
      <View style={{ flex: 1, backgroundColor: 'rgba(0,0,0,0.6)', justifyContent: 'center', padding: space.xl }}>
        <View style={{ backgroundColor: colors.surface, borderRadius: 14, padding: space.xl, gap: space.m }}>
          <Text style={{ fontSize: 20, fontWeight: '800', color: colors.ink }}>Manager sign-in</Text>
          <Text style={{ color: colors.ink2 }}>Needed to leave kiosk mode on this tablet.</Text>
          {challenge ? <Field label="Authenticator code" value={code} onChangeText={setCode} keyboardType="number-pad" /> : <>
            <Field label="Username" value={u} onChangeText={setU} autoCapitalize="none" autoCorrect={false} />
            <Field label="Password" value={p} onChangeText={setP} secureTextEntry />
            <Pressable onPress={() => setRevoke(!revoke)} accessibilityRole="checkbox" accessibilityState={{ checked: revoke }}><Text style={{ color: colors.ink }}>{revoke ? '☑' : '☐'} Also disable this kiosk device in Tempo</Text></Pressable></>}
          {err ? <Banner tone="bad" title={err} /> : null}
          <Button title={challenge ? 'Verify and leave kiosk mode' : 'Leave kiosk mode'} onPress={() => void go()} busy={busy} disabled={challenge ? code.length < 6 : !u || !p} />
          <Button title="Stay in kiosk mode" kind="secondary" onPress={reset} />
        </View>
      </View>
    </Modal>
  )
}
