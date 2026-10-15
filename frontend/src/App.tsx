import { useCallback, useEffect, useState } from 'react'
import { api, type Frame, type Job, type Session, type Status } from './lib'
import TabletPage from './TabletPage'
import DisplayPage from './DisplayPage'
import AdminPage from './AdminPage'

export type StudioView = {
  session: Session | null
  status: Status | null
  frames: Frame[]
  jobs: Job[]
  refresh: () => Promise<void>
  busy: boolean
  error: string
  setError: (message: string) => void
  run: (action: () => Promise<unknown>) => Promise<void>
}

export default function App() {
  const [session, setSession] = useState<Session | null>(null)
  const [status, setStatus] = useState<Status | null>(null)
  const [frames, setFrames] = useState<Frame[]>([])
  const [jobs, setJobs] = useState<Job[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const refresh = useCallback(async () => {
    try {
      const [nextSession, nextStatus, nextJobs, nextFrames] = await Promise.all([
        api<Session | null>('/session/active'), api<Status>('/status'), api<Job[]>('/prints'), api<Frame[]>('/frames'),
      ])
      setSession(nextSession)
      setStatus(nextStatus)
      setJobs(nextJobs)
      setFrames(nextFrames)
    } catch (err) {
      setError(err instanceof Error ? err.message : '서버에 연결할 수 없습니다')
    }
  }, [])
  useEffect(() => {
    void refresh()
    const timer = window.setInterval(() => { void refresh() }, 2500)
    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:'
    let socket: WebSocket | undefined
    try {
      socket = new WebSocket(`${protocol}//${location.host}/ws`)
      socket.onmessage = () => { void refresh() }
    } catch { /* Polling remains available. */ }
    return () => { window.clearInterval(timer); socket?.close() }
  }, [refresh])
  useEffect(() => {
    if (session?.stage !== 'CHOOSE_FRAME') return
    const timer = window.setInterval(() => {
      api<Frame[]>('/frames').then(setFrames).catch(() => { /* The regular refresh reports server errors. */ })
    }, 1000)
    return () => window.clearInterval(timer)
  }, [session?.stage])

  const run = async (action: () => Promise<unknown>) => {
    if (busy) return
    setBusy(true)
    setError('')
    try { await action(); await refresh() }
    catch (err) { setError(err instanceof Error ? err.message : '요청을 처리하지 못했습니다') }
    finally { setBusy(false) }
  }
  const view: StudioView = { session, status, frames, jobs, refresh, busy, error, setError, run }
  const path = location.pathname
  return path === '/admin' ? <AdminPage studio={view} /> : path === '/display' ? <DisplayPage studio={view} /> : <TabletPage studio={view} />
}
