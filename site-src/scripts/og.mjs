// Renders public/og.png (the social preview image) from the same data.json the page uses, so the
// numbers on it cannot go stale. Run: npm run og
import { chromium } from '@playwright/test'
import { readFile } from 'node:fs/promises'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { resolve } from 'node:path'

const here = fileURLToPath(new URL('.', import.meta.url))
const data = JSON.parse(await readFile(resolve(here, '../src/data.json'), 'utf8'))
const rows = data.ablation.B.rows
const g = (k) => rows.find((r) => r.key === k)?.goodput?.median
const ratio = (g('m3_continuous') / g('m2_static')).toFixed(1)

const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 1200, height: 630 } })
await page.goto(pathToFileURL(resolve(here, 'og-card.html')).href)
await page.evaluate(({ ratio, tests, runs }) => {
  document.getElementById('f1').innerHTML = `<b>${ratio}x</b> goodput over static batching`
  document.getElementById('f2').innerHTML = `<b>${tests}</b> token-exact tests`
  document.getElementById('f3').innerHTML = `<b>${runs}</b> load runs`
}, { ratio, tests: data.facts.tests, runs: data.meta.runs })
await page.evaluate(() => document.fonts.ready)
await page.screenshot({ path: resolve(here, '../public/og.png') })
await browser.close()
console.log('wrote public/og.png')
