import { useEffect, useRef, useState } from 'react'
import { patch, post, type Session, type Slot } from './lib'
import type { StudioView } from './App'
import FrameDial from './FrameDial'

export default function TabletPage({ studio }: { studio: StudioView }) {
  const { session, status, frames, busy, error, setError, run } = studio
  const [draft, setDraft] = useState<Slot[]>([null, null, null, null])
  const dirty = useRef(false)
  const saveTimer = useRef<number | undefined>(undefined)

  useEffect(() => {
    if (!session || dirty.current) return
    setDraft(session.arrangement)
  }, [session?.id, session?.updated_at, session?.arrangement])
  useEffect(() => () => window.clearTimeout(saveTimer.current), [])

  const save = async (value: Slot[]) => {
    if (!session) return
    window.clearTimeout(saveTimer.current)
    await patch<Session>(`/session/${session.id}/arrangement`, { slots: value })
    dirty.current = false
    await studio.refresh()
  }
  const update = (next: Slot[]) => {
    setDraft(next)
    dirty.current = true
    window.clearTimeout(saveTimer.current)
    saveTimer.current = window.setTimeout(() => { void save(next).catch((err) => setError(err.message)) }, 450)
  }
  const togglePhoto = (photoId: string) => {
    const chosen = draft.filter((slot): slot is Exclude<Slot, null> => slot !== null)
    const existing = chosen.findIndex((slot) => slot.photo_id === photoId)
    if (existing >= 0) chosen.splice(existing, 1)
    else if (chosen.length < 4) chosen.push({ photo_id: photoId })
    update([...chosen, ...Array.from({ length: 4 - chosen.length }, () => null)])
  }

  const complete = !!session && ['PRINT_REQUESTED', 'DONE'].includes(session.stage)
  const selectedCount = draft.filter(Boolean).length
  const chosenFrame = frames.find((frame) => frame.id === session?.frame_id)

  return <div className="app tablet-page">
    <main className="tablet-shell">
      {error && <div className="notice error" role="alert"><span>{error}</span><button onClick={() => { setError(''); void studio.refresh() }}>다시 확인</button></div>}

      {(!session || session.stage === 'LANDING') && <section className="tablet-center landing-stage">
        <h1>STEM<br />네컷</h1>
        {session
          ? <button className="text-action landing-button" aria-label="시작하기" disabled={busy} onClick={() => void run(() => post(`/session/${session.id}/enter`))}><span aria-hidden="true">▶</span> 시작하기</button>
          : <p className="waiting-note">잠시만 기다려 주세요</p>}
        {status?.camera.connected === false && <p className="device-note">카메라 연결을 확인해 주세요</p>}
      </section>}

      {session?.stage === 'QUANTITY' && <section className="tablet-center quantity-stage">
        <h1>출력 수량을 선택해주세요</h1>
        <div className="quantity-options">{[2, 4, 6].map((copies) => <button key={copies} className="quantity-option" aria-label={`${copies}장`} disabled={busy} onClick={() => void run(() => post(`/session/${session.id}/select-quantity`, { copies }))}>{copies}</button>)}</div>
      </section>}

      {session?.stage === 'SHOOTING' && <section className="shooting-stage">
        <h1 className="sr-only">촬영</h1>
        <div className="shooting-row">
          <div className="preview-wrap" role="img" aria-label="카메라 미리보기 영역" />
          <div className="shooting-actions">
            <span className="shooting-count" aria-label={`${session.photos.length}장 촬영됨`}>{session.photos.length} / 6</span>
            <button className="capture-button" disabled={busy || session.photos.length >= 6} onClick={() => void run(() => post(`/session/${session.id}/capture`))}>{busy ? '촬영 중' : '촬영'}</button>
            <button className="text-action finish-button" disabled={busy || session.photos.length < 4} onClick={() => void run(() => post(`/session/${session.id}/finish-capture`))}>촬영 마치기 <span aria-hidden="true">→</span></button>
            {status?.camera.connected === false && <p className="device-note">카메라 연결 확인</p>}
          </div>
        </div>
        <div className="capture-thumbs">{Array.from({ length: 6 }, (_, i) => <div className={`capture-thumb ${session.photos[i] ? 'captured' : ''}`} key={i} role="img" aria-label={`${i + 1}번째 사진 ${session.photos[i] ? '촬영됨' : '비어 있음'}`}><span>{i + 1}</span></div>)}</div>
      </section>}

      {session?.stage === 'CHOOSE_FRAME' && <FrameDial frames={frames} busy={busy} onSelect={(frameId) => void run(() => post(`/session/${session.id}/select-frame`, { frame_id: frameId }))} />}

      {session?.stage === 'ARRANGE' && <section className="arrange-stage">
        {chosenFrame ? <img className="selected-frame" src={chosenFrame.thumbnail_url} alt={`${chosenFrame.name} 프레임`} /> : <div className="selected-frame frame-empty" />}
        <div className="arrange-controls">
          <h1>사진 선택</h1>
          <div className="source-photos">{session.photos.map((photo, i) => {
            const selected = draft.findIndex((slot) => slot?.photo_id === photo.id)
            return <button className={selected >= 0 ? 'selected' : ''} key={photo.id} onClick={() => togglePhoto(photo.id)} aria-label={`${i + 1}번 사진 ${selected >= 0 ? `${selected + 1}컷 선택 해제` : '선택'}`}>
              <span className="photo-index" aria-hidden="true">{i + 1}</span>
              {selected >= 0 && <span className="selection-order" aria-hidden="true">{selected + 1}</span>}
            </button>
          })}</div>
          <button className="text-action arrange-next" disabled={busy || selectedCount !== 4} onClick={() => void run(async () => { await save(draft); await post(`/session/${session.id}/render`) })}>출력 화면으로 <span aria-hidden="true">→</span></button>
        </div>
      </section>}

      {session?.stage === 'REVIEW' && <section className="review-stage">
        {chosenFrame ? <img className="selected-frame" src={chosenFrame.thumbnail_url} alt={`${chosenFrame.name} 프레임`} /> : <div className="selected-frame frame-empty" />}
        <div className="review-controls">
          <h1>출력을 요청하세요</h1>
          <p className="print-count">{session.copies}장</p>
          <div className="review-buttons">
            <button className="text-action" disabled={busy} onClick={() => void run(() => post(`/session/${session.id}/back-to-arrange`))}>사진 다시 선택</button>
            <button className="text-action main-action" disabled={busy} onClick={() => void run(() => post(`/session/${session.id}/print-request`, {}))}>{busy ? '요청 중…' : '인쇄 요청 →'}</button>
          </div>
        </div>
      </section>}

      {complete && <section className="tablet-center done-stage"><h1>인쇄 요청이 접수되었습니다</h1><p>직원에게 사진을 받아주세요.</p></section>}
    </main>
  </div>
}
