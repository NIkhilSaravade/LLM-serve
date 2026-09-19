import { test, expect, type Page } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'
import { mkdirSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const shots = join(dirname(fileURLToPath(import.meta.url)), '..', '.shots')
mkdirSync(shots, { recursive: true })

const SECTIONS = ['overview', 'results', 'load', 'journey', 'architecture', 'memory', 'motion', 'cpu', 'correctness', 'operations', 'problems', 'negative-results', 'methodology', 'limitations', 'reproduce']

async function scrollThrough(page: Page): Promise<void> {
  const h = await page.evaluate(() => document.documentElement.scrollHeight)
  for (let y = 0; y < h; y += 600) {
    await page.evaluate((v) => window.scrollTo(0, v), y)
    await page.waitForTimeout(90)
  }
  await page.evaluate(() => window.scrollTo(0, 0))
  await page.waitForTimeout(1400) // let draw-in animations finish
}

test('serves with production headers and renders without errors', async ({ page, request }, info) => {
  const problems: string[] = []
  page.on('console', (m) => { if (m.type() === 'error' || m.type() === 'warning') problems.push(`${m.type()}: ${m.text()}`) })
  page.on('pageerror', (e) => problems.push(`pageerror: ${String(e)}`))
  const external: string[] = []
  page.on('request', (r) => { if (!r.url().startsWith('http://localhost') && !r.url().startsWith('data:')) external.push(r.url()) })

  // headers exactly as Cloudflare will send them (from public/_headers)
  const html = await request.get('/')
  const h = html.headers()
  expect(h['content-security-policy']).toContain("script-src 'self'")
  expect(h['content-security-policy']).not.toContain('unsafe-inline')
  expect(h['content-security-policy']).toContain("frame-ancestors 'none'")
  expect(h['x-content-type-options']).toBe('nosniff')
  expect(h['strict-transport-security']).toContain('max-age=31536000')
  expect(h['cache-control']).toContain('must-revalidate')

  await page.goto('/')
  await expect(page.locator('h1')).toContainText('scheduling')
  await scrollThrough(page)

  const assets = await page.evaluate(() => [...document.querySelectorAll('script[src], link[rel=stylesheet]')].map((e) => e.getAttribute('src') ?? e.getAttribute('href')))
  const hashed = assets.find((a) => a?.startsWith('/assets/'))
  expect(hashed).toBeTruthy()
  const asset = await request.get(hashed as string)
  expect(asset.headers()['cache-control']).toContain('immutable')

  expect(await page.locator('script:not([src])').count()).toBe(0) // no inline script anywhere
  expect(external).toEqual([])
  expect(problems).toEqual([]) // includes any Content-Security-Policy violation

  const over = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
  expect(over).toBeLessThanOrEqual(0)
  const offenders = await page.evaluate(() =>
    [...document.querySelectorAll('main *, header *')]
      .filter((e) => !e.closest('.tscroll') && !e.closest('.hscroll'))
      .filter((e) => { const r = e.getBoundingClientRect(); return r.width > 0 && r.right > window.innerWidth + 1 })
      .map((e) => `${e.tagName}.${String(e.getAttribute('class') ?? '').slice(0, 40)}`)
      .slice(0, 8),
  )
  expect(offenders).toEqual([])

  for (const id of SECTIONS) await expect(page.locator(`section#${id}`)).toHaveCount(1)
  const text = await page.locator('main').innerText()
  expect(text).toContain('3.70')                       // headline number, read from the data
  expect(await page.locator('.tag.illustration').count()).toBe(2)
  expect(await page.locator('.tag.measured').count()).toBeGreaterThanOrEqual(8)

  await page.screenshot({ path: join(shots, `${info.project.name}-full.png`), fullPage: true })
  for (const id of ['overview', 'results', 'architecture', 'memory', 'correctness', 'operations', 'problems']) {
    await page.locator(`#${id}`).scrollIntoViewIfNeeded()
    await page.waitForTimeout(700)
    await page.locator(`#${id}`).screenshot({ path: join(shots, `${info.project.name}-${id}.png`) })
  }
})

test('navigation: sidebar on desktop, drawer on mobile', async ({ page }, info) => {
  await page.goto('/')
  const side = page.locator('#sidebar')
  if (info.project.name === 'mobile') {
    await expect(side).not.toBeInViewport()
    await page.getByRole('button', { name: 'Open navigation' }).first().click()
    await expect(side).toBeInViewport()
    await side.getByRole('link', { name: 'Problems fixed' }).click()
    await expect(side).not.toBeInViewport()
  } else {
    await expect(side).toBeInViewport()
    await side.getByRole('link', { name: 'Problems fixed' }).click()
    await expect(page.locator('#problems')).toBeInViewport()
    await expect(side.locator('a.on')).toContainText('Problems fixed') // scroll-spy follows
    // the active item must not shift: its label sits exactly where the inactive ones do (regression: the pill
    // element once became a flex child and pushed the label 10px right)
    const activeX = (await side.locator('.side-nav a.on span:not(.pill)').boundingBox())?.x
    const otherX = (await side.locator('.side-nav a:not(.on) span').first().boundingBox())?.x
    expect(activeX).toBeDefined()
    expect(activeX).toBe(otherX)
  }
})

test('interactions work', async ({ page }, info) => {
  await page.goto('/')

  // system map: select a component, then trace a request
  await page.locator('#architecture').scrollIntoViewIfNeeded()
  await page.getByRole('button', { name: /Block manager/ }).click()
  await expect(page.locator('.arch-detail h3')).toHaveText('Block manager')
  await page.getByRole('button', { name: 'Trace a request' }).click()
  await expect(page.locator('.trace-cap').first()).toContainText('1 / 10')

  // KV diagram: 16 tokens fill a 16-token block exactly, the next token opens a second block
  await page.locator('#memory').scrollIntoViewIfNeeded()
  await page.getByLabel('Sequence length in tokens').fill('16')
  await expect(page.locator('.kv-callout')).toContainText('Exactly full')
  await page.getByLabel('Sequence length in tokens').fill('17')
  await expect(page.locator('.kv-callout')).not.toContainText('Exactly full')

  // ablation workload tabs
  await page.locator('#results').scrollIntoViewIfNeeded()
  await page.getByRole('tab', { name: /C · high variance/ }).click()
  await expect(page.locator('#results .chart-sub').first()).toContainText('Heavy-tailed')

  // problems accordion
  await page.locator('#problems').scrollIntoViewIfNeeded()
  const first = page.locator('.prob-list button').first()
  await expect(first).toHaveAttribute('aria-expanded', 'true')
  await first.click()
  await expect(first).toHaveAttribute('aria-expanded', 'false')
  await page.locator('#problems .seg').getByRole('button', { name: /^Correctness/ }).click()
  expect(await page.locator('.prob-list > li').count()).toBeGreaterThanOrEqual(2)

  // theme toggle persists
  if (info.project.name === 'mobile') await page.getByRole('button', { name: 'Open navigation' }).first().click()
  await page.getByRole('button', { name: /Switch to light theme/ }).click()
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'light')
})

for (const theme of ['dark', 'light'] as const) {
  test(`accessibility (${theme}): no serious or critical axe violations`, async ({ page }) => {
    await page.addInitScript((t) => { try { localStorage.setItem('theme', t) } catch { /* ignore */ } }, theme)
    await page.goto('/')
    await scrollThrough(page)
    const results = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21aa']).analyze()
    const bad = results.violations
      .filter((v) => v.impact === 'serious' || v.impact === 'critical')
      .map((v) => `${v.id} (${v.impact}): ${v.nodes.slice(0, 3).map((n) => n.target.join(' ')).join(' | ')}`)
    expect(bad).toEqual([])
  })
}
