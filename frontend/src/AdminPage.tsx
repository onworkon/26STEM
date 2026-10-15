import { useCallback, useEffect, useState, type ChangeEvent } from 'react'
import { api, post, type Devices, type Job, type Session } from './lib'
import type { StudioView } from './App'

const stageNames: Record<string, string> = { LANDING: '시작 대기', QUANTITY: '장수 선택', SHOOTING: '촬영 중', CHOOSE_FRAME: '프레임 선택', ARRANGE: '사진 선택', REVIEW: '출력 확인', PRINT_REQUESTED: '인쇄 요청됨', DONE: '완료' }
const printNames: Record<string, string> = { queued: '대기', sending: '스풀 전송 중', spooled: '스풀 전송됨', file_saved: '파일 저장', error: '오류', uncertain: '상태 불명' }

export default function AdminPage({ studio }: { studio: StudioView }) {
  const { session, status, jobs, busy, error, setError, run } = studio
  const [devices, setDevices] = useState<Devices | null>(null)
  const [recent, setRecent] = useState<Session[]>([])
  const [logs, setLogs] = useState<string[]>([])
  const [paths, setPaths] = useState<{ sessions: string; prints: string } | null>(null)
  const [pin, setPin] = useState(sessionStorage.getItem('stem_admin_pin') || '')
  const [cameraMode, setCameraMode] = useState('mock')
  const [previewUrl, setPreviewUrl] = useState('')
  const [snapshotUrl, setSnapshotUrl] = useState('')
  const [snapshotMethod, setSnapshotMethod] = useState('GET')
  const [usbIndex, setUsbIndex] = useState(0)
  const [remotePort, setRemotePort] = useState('')
  const [baudrate, setBaudrate] = useState(115200)
  const [printerMode, setPrinterMode] = useState('mock')
  const [printerName, setPrinterName] = useState('')

  const loadAdmin = useCallback(async () => {
    try {
      const [nextDevices, nextRecent, nextLogs, nextPaths] = await Promise.all([
        api<Devices>('/admin/devices'), api<Session[]>('/admin/sessions'),
        api<{ lines: string[] }>('/admin/logs'), api<{ sessions: string; prints: string }>('/admin/paths'),
      ])
      setDevices(nextDevices); setRecent(nextRecent); setLogs(nextLogs.lines); setPaths(nextPaths)
    } catch (err) { setError(err instanceof Error ? err.message : '운영자 상태를 불러올 수 없습니다') }
  }, [setError])
  useEffect(() => { void loadAdmin(); const timer = window.setInterval(() => { void loadAdmin() }, 5000); return () => window.clearInterval(timer) }, [loadAdmin])
  useEffect(() => {
    if (!devices) return
    setCameraMode(devices.camera.mode); setPreviewUrl(devices.camera.preview_mjpeg_url || ''); setSnapshotUrl(devices.camera.snapshot_jpeg_url || '')
    setSnapshotMethod(devices.camera.snapshot_method || 'GET'); setUsbIndex(devices.camera.usb_index || 0)
    setRemotePort(devices.remote.port || ''); setBaudrate(devices.remote.baudrate || 115200)
    setPrinterMode(devices.printer.mode); setPrinterName(devices.printer.name || '')
  }, [devices?.camera.mode, devices?.camera.preview_mjpeg_url, devices?.camera.snapshot_jpeg_url, devices?.camera.snapshot_method, devices?.camera.usb_index,
      devices?.remote.port, devices?.remote.baudrate, devices?.printer.mode, devices?.printer.name])

  const action = async (fn: () => Promise<unknown>) => { await run(fn); await loadAdmin() }
  const upload = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    if (!file || !session) return
    const body = new FormData(); body.append('file', file)
    await action(() => api(`/admin/session/${session.id}/photos`, { method: 'POST', body }))
    event.target.value = ''
  }
  const configure = () => action(() => post('/admin/devices/configure', {
    camera: { mode: cameraMode, preview_mjpeg_url: previewUrl, snapshot_jpeg_url: snapshotUrl, snapshot_method: snapshotMethod, usb_index: usbIndex },
    remote: { port: remotePort, baudrate }, printer: { mode: printerMode, name: printerName },
  }))
  const savePin = () => { sessionStorage.setItem('stem_admin_pin', pin); setError(''); void loadAdmin() }
  const clearData = () => {
    if (!window.confirm('모든 종료된 세션의 원본 사진, 결과물, PDF와 기록을 삭제할까요?')) return
    void action(() => post('/admin/data/clear'))
  }
  const downloadPdf = async (jobId: string) => {
    try {
      const savedPin = sessionStorage.getItem('stem_admin_pin')
      const response = await fetch(`/api/admin/prints/${jobId}/pdf`, { headers: savedPin ? { 'X-Admin-Pin': savedPin } : {} })
      if (!response.ok) throw new Error(`PDF를 열 수 없습니다 (${response.status})`)
      const url = URL.createObjectURL(await response.blob())
      const link = document.createElement('a')
      link.href = url; link.download = `stem4cut-${jobId}.pdf`; link.click()
      window.setTimeout(() => URL.revokeObjectURL(url), 1000)
    } catch (err) { setError(err instanceof Error ? err.message : 'PDF를 열 수 없습니다') }
  }

  return <div className="app admin-page"><header className="topbar"><div className="brand"><span className="brand-mark">S4</span><div><strong>STEM 4CUT</strong><small>OPERATOR DESK</small></div></div><nav><a href="/tablet" target="_blank" rel="noreferrer">태블릿 열기</a><a href="/display" target="_blank" rel="noreferrer">외부 화면 열기</a></nav></header>
    <main className="admin-shell"><div className="admin-title"><div><p className="eyebrow">CONTROL ROOM</p><h1>운영자 화면</h1></div><div className="status-pill">{session ? stageNames[session.stage] || session.stage : '활성 세션 없음'}</div></div>
      {error && <div className="notice error" role="alert"><span>{error}</span><button onClick={() => { setError(''); void loadAdmin() }}>다시 확인</button></div>}
      <div className="admin-columns"><div className="admin-left"><section className="admin-card"><div className="card-head"><h2>현재 촬영</h2><span>{session ? `${session.photos.length} / 6장` : '대기'}</span></div><div className="admin-preview" role="img" aria-label="운영자 카메라 미리보기 영역" /><p className="device-line"><b className={status?.camera.connected ? 'online' : 'offline'} />카메라: {status?.camera.detail || '확인 중'}</p>{session?.photos.some((p) => p.low_quality) && <p className="warning-text">인쇄 해상도가 낮은 사진이 있습니다.</p>}
        <div className="admin-actions"><button className="primary" disabled={busy || !!session && !['PRINT_REQUESTED', 'DONE'].includes(session.stage)} onClick={() => void action(() => post('/admin/session/start'))}>새 세션 시작</button><button className="secondary" disabled={busy || !session || !['CHOOSE_FRAME', 'ARRANGE', 'REVIEW'].includes(session.stage)} onClick={() => session && void action(() => post(`/admin/session/${session.id}/return-to-shooting`))}>촬영 단계로 복귀</button><button className="danger" disabled={busy || !session} onClick={() => void action(() => post('/admin/session/reset'))}>세션 종료</button></div>
        {session?.stage === 'SHOOTING' && <div className="upload-block"><label className="upload-button">사진 파일 수동 추가<input type="file" accept="image/jpeg,image/png,image/webp" onChange={(e) => void upload(e)} /></label><small>카메라 오류 시 20MB 이하 원본을 추가합니다. 최대 6장.</small></div>}
      </section>
      <section className="admin-card"><div className="card-head"><h2>인쇄 대기열</h2><button className="text-button" disabled={busy} onClick={() => void action(() => post('/admin/print-test'))}>테스트 페이지 요청</button></div><p className="helper">스풀 전송됨은 프린터가 작업을 받았다는 뜻입니다. 실제 출력은 직원이 확인하세요.</p><div className="job-list">{jobs.length === 0 ? <p className="empty">인쇄 작업이 없습니다.</p> : jobs.map((job: Job) => <div className="job-row" key={job.id}><div><b>{job.session_id === '__test__' ? '테스트 페이지' : `세션 ${job.session_id.slice(0, 8)}`}</b><span>{job.copies}개 스트립 · 용지 {job.sheets}장</span><small>{job.detail}</small></div><div><span className={`job-status ${job.status}`}>{printNames[job.status] || job.status}</span>{['error', 'uncertain'].includes(job.status) && <button className="small-button" disabled={busy} onClick={() => void action(() => post(`/admin/prints/${job.id}/retry`))}>상태 확인 후 재시도</button>}<button className="small-link" onClick={() => void downloadPdf(job.id)}>PDF</button></div></div>)}</div></section>
      <section className="admin-card"><h2>최근 세션</h2><div className="recent-list">{recent.map((item) => <div key={item.id}><span><b>{item.id.slice(0, 8)}</b><small>{stageNames[item.stage] || item.stage} · 사진 {item.photos.length}장</small></span><button className="small-button" disabled={busy || !jobs.some((job) => job.session_id === item.id)} onClick={() => void action(() => post(`/admin/sessions/${item.id}/reprint`))}>명시적 재인쇄</button></div>)}</div></section>
      </div><div className="admin-right"><section className="admin-card"><h2>장비 연결</h2><p className="helper">장비 설정은 이 PC의 data/devices.json에 저장됩니다. 연결 오류가 있어도 Mock 모드로 전환할 수 있습니다.</p><div className="form-grid"><label>카메라 모드<select value={cameraMode} onChange={(e) => setCameraMode(e.target.value)}><option value="mock">MockCamera</option><option value="http">HTTP MJPEG/JPEG</option><option value="usb">USB UVC</option></select></label>{cameraMode === 'http' && <><label className="full">MJPEG 프리뷰 URL<input value={previewUrl} onChange={(e) => setPreviewUrl(e.target.value)} placeholder="http://192.168.../stream" /></label><label className="full">JPEG 스냅샷 URL<input value={snapshotUrl} onChange={(e) => setSnapshotUrl(e.target.value)} placeholder="http://192.168.../capture" /></label><label>스냅샷 방식<select value={snapshotMethod} onChange={(e) => setSnapshotMethod(e.target.value)}><option>GET</option><option>POST</option></select></label></>}{cameraMode === 'usb' && <label>USB 장치 번호<input type="number" min="0" value={usbIndex} onChange={(e) => setUsbIndex(Number(e.target.value))} /></label>}
        <label>시리얼 포트<input list="ports" value={remotePort} onChange={(e) => setRemotePort(e.target.value)} placeholder="비워두면 해제" /><datalist id="ports">{devices?.serial_ports.map((p) => <option key={p} value={p} />)}</datalist></label><label>Baud rate<input type="number" value={baudrate} onChange={(e) => setBaudrate(Number(e.target.value))} /></label><label>프린터 모드<select value={printerMode} onChange={(e) => setPrinterMode(e.target.value)}><option value="mock">MockPrinter · 파일 저장</option><option value="windows">Windows 프린터</option></select></label><label>프린터<select value={printerName} onChange={(e) => setPrinterName(e.target.value)}><option value="">기본 프린터</option>{devices?.printers.map((p) => <option key={p} value={p}>{p}</option>)}</select></label></div><button className="primary wide" disabled={busy} onClick={() => void configure()}>장비 설정 저장</button><div className="device-details"><span><b className={devices?.remote.connected ? 'online' : 'offline'} />시리얼: {devices?.remote.detail || '확인 중'}</span><span>마지막 셔터: {devices?.remote.last_signal || '없음'}</span><span><b className={devices?.printer.connected ? 'online' : 'offline'} />프린터: {devices?.printer.detail || '확인 중'}</span></div><p className="warning-text">실제 프린터는 Windows 기본 설정에서 4×6 세로 용지와 무테 옵션을 확인하세요.</p></section>
      <section className="admin-card"><h2>관리 · 복구</h2><label className="pin-field">관리자 PIN (원격 관리자 접속 시)<input type="password" value={pin} onChange={(e) => setPin(e.target.value)} placeholder="PC localhost는 PIN 불필요" /><button className="secondary" onClick={savePin}>이 브라우저에 저장</button></label><p className="helper">PIN은 config.yaml에 별도로 설정해야 합니다. 기본값은 PC localhost 전용입니다.</p><div className="path-list"><span>사진: {paths?.sessions || '확인 중'}</span><span>PDF: {paths?.prints || '확인 중'}</span></div><div className="admin-actions"><button className="secondary" disabled={busy} onClick={() => void action(() => post('/admin/open-folder/sessions'))}>사진 폴더 열기</button><button className="secondary" disabled={busy} onClick={() => void action(() => post('/admin/open-folder/prints'))}>PDF 폴더 열기</button></div><button className="danger wide" disabled={busy || !!session} onClick={clearData}>종료된 사진·출력물 일괄 삭제</button></section><section className="admin-card"><div className="card-head"><h2>최근 로그</h2><button className="text-button" onClick={() => void loadAdmin()}>새로고침</button></div><pre className="log-box">{logs.length ? logs.join('\n') : '기록이 없습니다.'}</pre></section></div></div>
    </main><footer className="footer"><span>STEM 4CUT · OPERATOR</span><span>관리자 API는 PC localhost 또는 설정한 PIN만 허용</span></footer></div>
}
