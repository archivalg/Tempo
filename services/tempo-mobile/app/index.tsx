import { Redirect } from 'expo-router'
import { useEffect, useState } from 'react'
import * as store from '../src/auth/storage'
import { useSession } from '../src/auth/session'
import { Loading } from '../src/ui/kit'

/** Where to start: a tablet enrolled as a kiosk always opens the kiosk; otherwise the employee's session decides. */
export default function Index() {
  const { state } = useSession()
  const [kiosk, setKiosk] = useState<boolean | null>(null)
  useEffect(() => { void store.loadKiosk().then((k) => setKiosk(!!k)) }, [])
  if (kiosk === null || state === 'loading') return <Loading />
  if (kiosk) return <Redirect href="/kiosk" />
  return <Redirect href={state === 'signedIn' ? '/shifts' : '/login'} />
}
