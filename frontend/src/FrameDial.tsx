import { useEffect, useRef, useState } from 'react'
import type { Frame } from './lib'

type Props = {
  frames: Frame[]
  busy: boolean
  onSelect: (frameId: string) => void
}

export default function FrameDial({ frames, busy, onSelect }: Props) {
  const [dial, setDial] = useState<{ id: string | null; position: number }>({ id: null, position: 0 })
  const startX = useRef<number | null>(null)
  const ignoreClickUntil = useRef(0)
  const lastWheel = useRef(0)
  const centerIndex = Math.max(0, frames.findIndex((frame) => frame.id === dial.id))
  const center = frames[centerIndex]

  useEffect(() => {
    if (frames.length && !frames.some((frame) => frame.id === dial.id)) {
      setDial((current) => ({ ...current, id: frames[0].id }))
    }
  }, [dial.id, frames])

  const rotate = (direction: number) => {
    if (busy || frames.length < 2) return
    setDial((current) => {
      const index = Math.max(0, frames.findIndex((frame) => frame.id === current.id))
      return { id: frames[(index + direction + frames.length) % frames.length].id, position: current.position + direction }
    })
  }
  const sideCount = Math.min(3, Math.floor(frames.length / 2))
  const slots = frames.length ? Array.from({ length: (sideCount + 1) * 2 + 1 }, (_, index) => {
    const offset = index - sideCount - 1
    return { frame: frames[(centerIndex + offset + frames.length * 2) % frames.length], offset }
  }) : []

  return <section className="tablet-center frame-stage">
    <h1>사진 프레임을 선택해주세요</h1>
    <div className="frame-dial" aria-label="프레임 다이얼. 좌우로 넘기고 중앙 프레임을 눌러 선택하세요" tabIndex={0}
      onKeyDown={(event) => {
        if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
          event.preventDefault()
          rotate(event.key === 'ArrowRight' ? 1 : -1)
        }
      }}
      onWheel={(event) => {
        const motion = Math.abs(event.deltaX) > Math.abs(event.deltaY) ? event.deltaX : event.deltaY
        if (Math.abs(motion) < 20 || Date.now() - lastWheel.current < 350) return
        lastWheel.current = Date.now()
        rotate(motion > 0 ? 1 : -1)
      }}
      onPointerDown={(event) => { startX.current = event.clientX }}
      onPointerUp={(event) => {
        if (startX.current === null) return
        const distance = event.clientX - startX.current
        startX.current = null
        if (Math.abs(distance) < 45) return
        ignoreClickUntil.current = Date.now() + 350
        rotate(distance < 0 ? 1 : -1)
      }}
      onPointerCancel={() => { startX.current = null }}>
      {slots.map(({ frame, offset }) => <button key={dial.position + offset} className="dial-frame" data-offset={offset}
          data-buffer={Math.abs(offset) > sideCount} aria-hidden={Math.abs(offset) > sideCount} tabIndex={Math.abs(offset) > sideCount ? -1 : 0} disabled={busy}
          aria-label={offset === 0 ? `${frame.name} 선택` : `${frame.name} 중앙으로 이동`}
          aria-current={offset === 0 ? 'true' : undefined}
          onClick={() => {
            if (Date.now() < ignoreClickUntil.current) return
            if (offset === 0) onSelect(frame.id)
            else setDial((current) => ({ id: frame.id, position: current.position + offset }))
          }}>
          <img src={frame.thumbnail_url} alt="" draggable={false} />
        </button>)}
    </div>
    {center ? <span className="sr-only" aria-live="polite">중앙 프레임: {center.name}</span> : <p className="dial-loading">프레임을 불러오는 중입니다</p>}
  </section>
}
