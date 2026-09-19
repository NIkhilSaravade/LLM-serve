# 08 — Deploying the results page

The page in `site-src/` is a static site: React, TypeScript, Tailwind and Motion, built by Vite into
`site/` (not committed) and served from Cloudflare. This document is the whole path from source to a
public URL, and what has and has not been checked.

## Status

The site **has not been deployed to Cloudflare yet.** The build, the security headers, the caching rules
and the Wrangler configuration are all verified locally (see "What is verified"); no Cloudflare account
has been involved yet, because the repository had no remote when this was written.

## What ships

```
site-src/                 source (TypeScript strict), tests, Wrangler config
  src/data.json           every number on the page, generated from the raw benchmark runs
  src/content/*.json      problems log, bug-injection table, verification matrix (each entry quotes a repo doc)
  public/_headers         security headers and cache rules, applied by Cloudflare
  public/404.html         not-found page
  public/theme-init.js    sets the saved theme before first paint (external so CSP can ban inline script)
site/                     the build output: index.html, hashed /assets/*, and the files from public/
```

## Local commands

```bash
make site-setup     # once: npm ci and a Chromium for the tests
make site           # regenerate data.json from results/bench, typecheck, production build
make site-test      # ... and run the browser tests against the build
npm --prefix site-src run preview   # serve site/ with the real _headers on http://localhost:4173
npm --prefix site-src run dev       # Vite dev server with hot reload
```

`make site` is the same build production runs. Nothing on the page is typed by hand: numbers come from
`data.json`, and the hand-written entries in `src/content` are tested against the documents they cite
(`tests/test_site_content.py`).

## Production headers (`public/_headers`)

| Header | Value and why |
|---|---|
| `Content-Security-Policy` | `default-src 'none'`, then only same-origin script, style, font and image. **No inline script, no inline style, no third-party origin, no `connect-src`.** This is why the theme initialiser is an external file and the build never inlines assets. `frame-ancestors 'none'`, `base-uri 'none'`, `form-action 'none'`. |
| `Strict-Transport-Security` | one year, subdomains |
| `X-Content-Type-Options` | `nosniff` |
| `X-Frame-Options` | `DENY` (belt and braces with `frame-ancestors`) |
| `Referrer-Policy` | `strict-origin-when-cross-origin` |
| `Permissions-Policy` | camera, microphone, geolocation, payment, USB and sensors all denied |
| `Cross-Origin-Opener-Policy` / `-Resource-Policy` | `same-origin` |
| `Cache-Control` | `/assets/*`: one year, `immutable` (filenames are content hashes). `/` and `/index.html`: `max-age=0, must-revalidate`, so a deploy is visible immediately. |

Both `/` and `/index.html` are listed on purpose: a rule for one does not cover the other, and an
uncovered HTML document would be cached by default.

## First deployment

1. Push the repository to GitHub.
2. In Cloudflare, create an API token from the **Edit Cloudflare Workers** template and note the account id.
3. In the GitHub repository: **Settings, Secrets and variables, Actions**.
   - Secrets: `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID`.
   - Variable: `SITE_URL`, the final public URL without a trailing slash (used for the social preview image).
4. Create an environment named `production` (Settings, Environments). Add required reviewers if you want
   a manual approval before each deploy.
5. Merge to `main`. The `ci` workflow runs; when it passes, `deploy-site` builds the page and runs
   `wrangler deploy`, then smoke-tests the live URL for the security headers.
6. Open the `*.workers.dev` URL from the deploy log.

To deploy once from a laptop instead: `npx wrangler login`, then `npm --prefix site-src run deploy`.

### Custom domain

Add the domain to the Cloudflare account, then add a `routes` entry to `site-src/wrangler.jsonc`:

```jsonc
"routes": [{ "pattern": "your.domain.example", "custom_domain": true }]
```

Set the `SITE_URL` variable to the same address so the social preview image resolves.

### Using Cloudflare Pages instead

The output is a plain static folder, so Pages works too: connect the repository, set the build command to
`npm --prefix site-src ci && npm --prefix site-src run build`, and the output directory to `site`. Pages
reads the same `_headers` file. The GitHub Actions path above is preferred because CI gates the deploy.

## Rollback

Every deploy is a Workers version. `npx wrangler versions list`, then
`npx wrangler rollback <version-id>` (or use the Cloudflare dashboard). Because assets are content-hashed and
HTML revalidates on every request, a rollback is visible immediately.

## What is verified

Verified on a development machine:

- `tsc --noEmit` under `strict` with `noUncheckedIndexedAccess`, and a production build.
- The browser tests in `site-src/tests/site.spec.ts` run against `scripts/serve.mjs`, which applies the real
  `_headers`: CSP present and free of `unsafe-inline`, no inline script anywhere, no request to any other
  origin, no console or CSP error, hashed assets marked immutable, HTML marked must-revalidate, no
  horizontal overflow, WCAG 2 A/AA with no serious or critical axe violation in both themes, and the
  interactions, on desktop and on a mobile viewport.
- `wrangler deploy --dry-run` accepts `site-src/wrangler.jsonc`.

Not verified: an actual deployment, the live headers (the deploy workflow smoke-tests them, but it has never
run), and behaviour in Firefox or Safari (the tests use Chromium only).

## Costs and limits

Static assets on Workers are free within Cloudflare's plan limits and need no Worker code. The whole build is
about 0.8 MB, of which the JavaScript is roughly 150 KB gzipped.
