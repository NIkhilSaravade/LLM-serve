import { test, expect } from '@playwright/test'
import { fileURLToPath, pathToFileURL } from 'node:url'
import path from 'node:path'
import fs from 'node:fs'

const here = path.dirname(fileURLToPath(import.meta.url))
const page_url = pathToFileURL(path.resolve(here, '../../site/index.html')).href
const shots = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../.shots')
fs.mkdirSync(shots, { recursive: true })

async function scrollThrough(page) {
  const h = await page.evaluate(() => document.documentElement.scrollHeight)
  for (let y = 0; y < h; y += 500) { await page.evaluate((v) => window.scrollTo(0, v), y); await page.waitForTimeout(120) }
  await page.evaluate(() => window.scrollTo(0, 0))
  await page.waitForTimeout(1500) // let the draw-in animations finish
}

test('page renders without errors, overflow or missing content', async ({ page }, info) => {
  const errors = []
  page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()) })
  page.on('pageerror', (e) => errors.push(String(e)))
  const requests = []
  page.on('request', (r) => { if (!r.url().startsWith('file:') && !r.url().startsWith('data:')) requests.push(r.url()) })

  await page.goto(page_url)
  await expect(page.locator('h1')).toContainText('batching')
  await scrollThrough(page)

  // no external requests: fonts, scripts and data are all inlined
  expect(requests).toEqual([])
  expect(errors).toEqual([])
  // no horizontal page scroll
  const over = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
  expect(over).toBeLessThanOrEqual(0)
  // and no element pokes past the viewport (tables scroll inside .tscroll on purpose)
  const offenders = await page.evaluate(() => [...document.querySelectorAll('main *, header *')]
    .filter((e) => !e.closest('.tscroll') && !e.closest('.nav-links'))
    .filter((e) => { const r = e.getBoundingClientRect(); return r.width > 0 && r.right > window.innerWidth + 1 })
    .map((e) => `${e.tagName}.${String(e.className && e.className.baseVal !== undefined ? e.className.baseVal : e.className).slice(0, 40)}`).slice(0, 8))
  expect(offenders).toEqual([])
  // headline numbers come from the data, and every section exists
  const text = await page.locator('main').innerText()
  expect(text).toContain('3.70')
  for (const id of ['results', 'how-it-works', 'cpu', 'negative-results', 'methodology', 'limitations', 'reproduce']) {
    await expect(page.locator(`#${id}`)).toHaveCount(1)
  }
  // every animated illustration is labelled
  expect(await page.locator('.tag.illustration').count()).toBe(2)
  expect(await page.locator('.tag.measured').count()).toBeGreaterThanOrEqual(6)

  await page.screenshot({ path: path.join(shots, `${info.project.name}-full.png`), fullPage: true })
  for (const id of ['top', 'results', 'how-it-works', 'cpu', 'negative-results', 'limitations']) {
    await page.locator(`#${id}`).scrollIntoViewIfNeeded()
    await page.waitForTimeout(900)
    await page.locator(`#${id}`).screenshot({ path: path.join(shots, `${info.project.name}-${id}.png`) })
  }
})
