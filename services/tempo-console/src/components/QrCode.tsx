import { useEffect, useState } from 'react'
import QRCode from 'qrcode'

/** Drawn in the browser from the otpauth URI: the secret is never sent to a third-party QR service. */
export function QrCode({ value, label }: { value: string; label: string }) {
  const [src, setSrc] = useState<string | null>(null)
  useEffect(() => { let live = true; QRCode.toDataURL(value, { margin: 2, width: 200, errorCorrectionLevel: 'M' }).then((u) => { if (live) setSrc(u) }).catch(() => { if (live) setSrc(null) }); return () => { live = false } }, [value])
  return src ? <img src={src} width={200} height={200} alt={label} style={{ background: '#fff', borderRadius: 8 }} /> : null
}
