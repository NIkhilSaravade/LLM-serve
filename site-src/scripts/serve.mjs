// Serves ../site exactly as Cloudflare will: same files, same _headers. Used by `npm run preview` and by the
// Playwright tests, so the Content-Security-Policy and cache rules are tested, not assumed.
import { createServer } from 'node:http'
import { readFile, stat } from 'node:fs/promises'
import { existsSync } from 'node:fs'
import { extname, join, normalize, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = resolve(fileURLToPath(new URL('../../site', import.meta.url)))
const port = Number(process.env.PORT ?? 4173)

const TYPES = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.woff2': 'font/woff2',
  '.json': 'application/json',
  '.txt': 'text/plain; charset=utf-8',
}

const escapeRegex = (s) => s.replace(/[.+?^${}()|[\]\\]/g, '\\$&')

/** Parse Cloudflare's _headers format: an unindented path line, then indented "Name: value" lines. */
function parseHeaders(text) {
  const rules = []
  let cur = null
  for (const raw of text.split(/\r?\n/)) {
    if (!raw.trim() || raw.trim().startsWith('#')) continue
    if (!/^\s/.test(raw)) {
      cur = { pattern: raw.trim(), headers: [] }
      rules.push(cur)
      continue
    }
    const i = raw.indexOf(':')
    if (cur && i > 0) cur.headers.push([raw.slice(0, i).trim(), raw.slice(i + 1).trim()])
  }
  return rules.map((r) => ({
    re: new RegExp('^' + r.pattern.split('*').map(escapeRegex).join('.*') + '$'),
    headers: r.headers,
  }))
}

const headerFile = join(root, '_headers')
const rules = existsSync(headerFile) ? parseHeaders(await readFile(headerFile, 'utf8')) : []

createServer(async (req, res) => {
  const url = new URL(req.url ?? '/', 'http://x')
  let path = normalize(decodeURIComponent(url.pathname))
  if (path.endsWith('/') || path.endsWith('\\')) path = '/index.html'
  let file = join(root, path)
  let status = 200
  if (!file.startsWith(root) || !existsSync(file) || (await stat(file)).isDirectory()) {
    file = join(root, '404.html')
    status = 404
  }
  const headers = { 'Content-Type': TYPES[extname(file)] ?? 'application/octet-stream' }
  for (const r of rules) {
    if (r.re.test(url.pathname)) {
      for (const [k, v] of r.headers) headers[k] = headers[k] ? `${headers[k]}, ${v}` : v
    }
  }
  res.writeHead(status, headers)
  res.end(await readFile(file))
}).listen(port, () => console.log(`serving ${root} with _headers on http://localhost:${port}`))
