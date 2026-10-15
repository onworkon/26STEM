import type { StudioView } from './App'

export default function DisplayPage({ studio }: { studio: StudioView }) {
  const session = studio.session
  const shooting = session?.stage === 'SHOOTING'
  const heading = !session ? '다음 촬영을 기다리고 있어요' : ({ LANDING: '촬영을 시작해 주세요', QUANTITY: '사진 장수를 고르고 있어요', CHOOSE_FRAME: '프레임을 고르고 있어요', ARRANGE: '사진을 고르고 있어요', REVIEW: '출력을 준비하고 있어요', PRINT_REQUESTED: '인쇄를 요청했어요', DONE: '인쇄를 요청했어요' } as Record<string, string>)[session.stage] || '잠시 기다려 주세요'
  return <div className="display-page"><header><span className="display-logo">STEM <b>4CUT</b></span><span>DRONE MAKER PHOTO</span></header><main>{shooting ? <><div className="display-preview" role="img" aria-label="카메라 미리보기 영역" /><div className="display-caption"><strong>촬영 중입니다</strong><span>촬영 {session.photos.length} / 6</span></div></> : <div className="display-wait"><p>STEM 4CUT</p><h1>{heading}</h1></div>}</main><footer>SEOUL STEM FESTIVAL  ·  MAKER PHOTO EXPERIENCE</footer></div>
}
