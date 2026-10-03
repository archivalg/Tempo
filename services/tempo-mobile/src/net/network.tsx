import NetInfo from '@react-native-community/netinfo'
import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'

const C = createContext<{ online: boolean }>({ online: true })

export function NetworkProvider({ children }: { children: ReactNode }) {
  const [online, setOnline] = useState(true)
  useEffect(() => NetInfo.addEventListener((s) => setOnline(s.isConnected !== false && s.isInternetReachable !== false)), [])
  return <C.Provider value={{ online }}>{children}</C.Provider>
}
export const useOnline = () => useContext(C).online
