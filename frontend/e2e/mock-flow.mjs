import { chromium } from 'playwright-core'

const base = process.env.STEM_BASE_URL || 'http://127.0.0.1:8000'
const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH || '/usr/bin/chromium', headless: true, args: ['--no-sandbox'] })
const errors = []
const admin = await browser.newPage({ viewport: { width: 1440, height: 900 } })
const screenDir = process.env.STEM_SCREENSHOT_DIR
async function checkTabletLayout(page, stage, captureName) {
  const layout = await page.evaluate(() => {
    const buttons = [...document.querySelectorAll('.tablet-page button')]
      .filter((button) => button.getClientRects().length && button.getAttribute('aria-hidden') !== 'true')
      .map((button) => {
        const box = button.getBoundingClientRect()
        return { label: button.getAttribute('aria-label') || button.textContent?.trim(), width: box.width, height: box.height, bottom: box.bottom }
      })
    return {
      viewportWidth: window.innerWidth,
      viewportHeight: window.innerHeight,
      pageWidth: document.documentElement.scrollWidth,
      pageHeight: document.documentElement.scrollHeight,
      buttons,
    }
  })
  if (layout.viewportWidth !== 1280 || layout.viewportHeight !== 800) throw new Error(`${stage}: wrong Android viewport: ${JSON.stringify(layout)}`)
  if (layout.pageWidth > layout.viewportWidth) throw new Error(`${stage}: horizontal overflow: ${JSON.stringify(layout)}`)
  if (layout.pageHeight > layout.viewportHeight) throw new Error(`${stage}: vertical overflow: ${JSON.stringify(layout)}`)
  const small = layout.buttons.filter((button) => button.width < 48 || button.height < 48)
  if (small.length) throw new Error(`${stage}: touch targets below 48 px: ${JSON.stringify(small)}`)
  const offscreen = layout.buttons.filter((button) => button.bottom > layout.viewportHeight)
  if (offscreen.length) throw new Error(`${stage}: buttons below first screen: ${JSON.stringify(offscreen)}`)
  console.log(`${stage}: ${layout.pageWidth}×${layout.pageHeight}, ${layout.buttons.length} touch targets ≥48 px`)
  if (screenDir && captureName) await page.screenshot({ path: `${screenDir}/${captureName}`, fullPage: false })
}
try {
  admin.on('pageerror', (error) => errors.push(`admin: ${error.message}`))
  await admin.goto(`${base}/admin`)
  await admin.getByRole('heading', { name: '운영자 화면' }).waitFor()
  const reset = admin.getByRole('button', { name: '세션 종료' })
  if (await reset.isEnabled()) await reset.click()
  await admin.getByRole('button', { name: '새 세션 시작' }).click()

  const tablet = await browser.newPage({ viewport: { width: 1280, height: 800 }, isMobile: true, hasTouch: true, deviceScaleFactor: 1 })
  tablet.on('pageerror', (error) => errors.push(`tablet: ${error.message}`))
  await tablet.goto(`${base}/tablet`)
  await tablet.getByRole('heading', { name: 'STEM 네컷' }).waitFor()
  await checkTabletLayout(tablet, 'Landing', 'simple-tablet-01-landing.png')
  await tablet.getByRole('button', { name: '시작하기' }).click()
  await tablet.getByRole('heading', { name: '출력 수량을 선택해주세요' }).waitFor()
  await checkTabletLayout(tablet, 'Quantity', 'simple-tablet-02-quantity.png')
  await tablet.locator('.quantity-option').nth(1).click()
  await tablet.getByRole('heading', { name: '촬영', exact: true }).waitFor()
  await checkTabletLayout(tablet, 'Shooting', 'simple-tablet-03-shooting.png')
  const selectedSession = await (await tablet.request.get(`${base}/api/session/active`)).json()
  if (selectedSession.copies !== 4) throw new Error('Selected quantity was not saved')
  for (let i = 0; i < 5; i++) {
    await tablet.getByRole('button', { name: '촬영', exact: true }).click()
    await tablet.waitForTimeout(700)
  }
  await checkTabletLayout(tablet, 'Shooting with photos', 'simple-tablet-03-shooting.png')
  await tablet.getByRole('button', { name: '촬영', exact: true }).click()
  await tablet.getByRole('heading', { name: '사진 프레임을 선택해주세요' }).waitFor()
  await checkTabletLayout(tablet, 'Frame', 'simple-tablet-04-frame.png')
  const realFrames = await (await tablet.request.get(`${base}/api/frames`)).json()
  const dialFrames = [...realFrames, ...Array.from({ length: 7 }, (_, i) => ({
    ...realFrames[i % realFrames.length], id: `dial-demo-${i + 1}`, name: `다이얼 ${i + 1}`,
  }))]
  let offeredFrames = realFrames
  await tablet.route('**/api/frames', (route) => route.fulfill({ json: offeredFrames }))
  await tablet.reload()
  await tablet.getByRole('heading', { name: '사진 프레임을 선택해주세요' }).waitFor()
  offeredFrames = dialFrames
  await tablet.getByRole('button', { name: '다이얼 1 중앙으로 이동' }).waitFor()
  if (process.env.STEM_DIAL_TEST_SCREENSHOT) await tablet.screenshot({ path: process.env.STEM_DIAL_TEST_SCREENSHOT, fullPage: false })
  await checkTabletLayout(tablet, 'Nine-frame dial', null)
  if (await tablet.locator('.dial-frame[data-buffer="false"]').count() !== 7) throw new Error('Nine-frame dial did not show seven visible positions')
  const sizes = await tablet.locator('.dial-frame[data-buffer="false"]').evaluateAll((buttons) => buttons.map((button) => ({
    offset: button.getAttribute('data-offset'), height: button.getBoundingClientRect().height,
  })))
  if (!(sizes.find((item) => item.offset === '0').height > sizes.find((item) => item.offset === '1').height
    && sizes.find((item) => item.offset === '1').height > sizes.find((item) => item.offset === '2').height
    && sizes.find((item) => item.offset === '2').height > sizes.find((item) => item.offset === '3').height)) throw new Error('Frame sizes do not recede from the center')
  const firstCard = await tablet.locator('.dial-frame[data-offset="0"]').elementHandle()
  await tablet.locator('.dial-frame[data-offset="-1"]').click()
  await tablet.getByRole('button', { name: '다이얼 7 선택' }).waitFor()
  if (!await firstCard.evaluate((button) => button.isConnected && button.getAttribute('data-offset') === '1')) throw new Error('First frame did not move beside the last frame')
  await tablet.locator('.dial-frame[data-offset="1"]').click()
  await tablet.getByRole('button', { name: `${realFrames[0].name} 선택` }).waitFor()
  if (!await firstCard.evaluate((button) => button.isConnected && button.getAttribute('data-offset') === '0')) throw new Error('First frame did not return across the loop')
  await tablet.locator('.dial-frame[data-offset="1"]').click()
  await tablet.getByRole('button', { name: `${realFrames[1].name} 선택` }).waitFor()
  await tablet.locator('.frame-dial').dispatchEvent('pointerdown', { clientX: 800, pointerId: 1, pointerType: 'touch' })
  await tablet.locator('.frame-dial').dispatchEvent('pointerup', { clientX: 600, pointerId: 1, pointerType: 'touch' })
  await tablet.getByRole('button', { name: '다이얼 1 선택' }).waitFor()
  await tablet.locator('.frame-dial').focus()
  await tablet.keyboard.press('ArrowLeft')
  await tablet.getByRole('button', { name: `${realFrames[1].name} 선택` }).waitFor()
  await tablet.unroute('**/api/frames')
  await tablet.reload()
  await tablet.getByRole('heading', { name: '사진 프레임을 선택해주세요' }).waitFor()
  await tablet.locator('.dial-frame[data-offset="1"]').click()
  await tablet.getByRole('button', { name: `${realFrames[1].name} 선택` }).click()
  await tablet.getByRole('heading', { name: '사진 선택' }).waitFor()
  await checkTabletLayout(tablet, 'Photo selection', 'simple-tablet-05-photos.png')
  for (const i of [4, 2, 0, 1]) await tablet.locator('.source-photos button').nth(i).click()
  if (await tablet.locator('.selection-order').count() !== 4) throw new Error('Four photos were not selected')
  await checkTabletLayout(tablet, 'Four photos selected', 'simple-tablet-05-photos.png')
  if (await tablet.locator('input[type=range]').count()) throw new Error('Photo processing controls are still visible')
  await tablet.getByRole('button', { name: '출력 화면으로' }).click()
  await tablet.getByRole('heading', { name: '출력을 요청하세요' }).waitFor()
  await tablet.locator('.print-count').getByText('4장').waitFor()
  await checkTabletLayout(tablet, 'Output', 'simple-tablet-06-output.png')
  await tablet.getByRole('button', { name: /^인쇄 요청/ }).click()
  await tablet.getByRole('heading', { name: '인쇄 요청이 접수되었습니다' }).waitFor()
  await tablet.getByText('직원에게 사진을 받아주세요.').waitFor()
  await checkTabletLayout(tablet, 'Complete', 'simple-tablet-07-complete.png')
  if (errors.length) throw new Error(errors.join('\n'))
  console.log('Browser mock flow passed: landing → 4 strips → 6 captures → frame → 4 photo choices → output')
} finally {
  await admin.request.post(`${base}/api/admin/session/reset`).catch(() => {})
  await browser.close()
}
