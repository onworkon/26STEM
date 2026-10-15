export type Photo = { id: string; url: string; width: number; height: number; low_quality: boolean }
export type Slot = { photo_id: string } | null
export type Session = { id: string; stage: string; active: number; frame_id: string | null; copies: number | null; photos: Photo[]; arrangement: Slot[]; updated_at: string; created_at: string }
export type Frame = { id: string; name: string; description: string; thumbnail_url: string; slots: { x: number; y: number; width: number; height: number }[] }
export type Job = { id: string; session_id: string; kind?: string; copies: number; sheets: number; status: string; detail: string; created_at: string }
export type Status = { active_id: string | null; stage: string; photo_count: number; camera: { mode: string; connected: boolean; detail: string; low_quality: boolean }; printer: { mode: string; connected: boolean; detail: string }; remote: { connected: boolean; detail: string; last_signal: string | null }; print_counts: Record<string, number> }
export type Devices = { camera: { mode: string; connected: boolean; detail: string; preview_mjpeg_url: string; snapshot_jpeg_url: string; snapshot_method: string; usb_index: number }; printer: { mode: string; name: string; connected: boolean; detail: string }; remote: { port: string; baudrate: number; connected: boolean; detail: string; last_signal: string | null }; printers: string[]; serial_ports: string[] }

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const pin = sessionStorage.getItem('stem_admin_pin')
  const headers: Record<string, string> = { ...(options.headers as Record<string, string> || {}) }
  if (pin) headers['X-Admin-Pin'] = pin
  if (options.body && !(options.body instanceof FormData)) headers['Content-Type'] = 'application/json'
  const response = await fetch('/api' + path, { ...options, headers })
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    throw new Error(body.detail || `요청 실패 (${response.status})`)
  }
  return response.json() as Promise<T>
}

export const post = <T,>(path: string, value?: unknown) => api<T>(path, { method: 'POST', body: value === undefined ? undefined : JSON.stringify(value) })
export const patch = <T,>(path: string, value: unknown) => api<T>(path, { method: 'PATCH', body: JSON.stringify(value) })
export const media = (sessionId: string, file: string, stamp?: string) => `/api/media/${sessionId}/${file}${stamp ? `?v=${encodeURIComponent(stamp)}` : ''}`
