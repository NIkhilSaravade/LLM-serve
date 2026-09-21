# 08 — Deploying the results page

The page in `site-src/` is a static site: React, TypeScript, Tailwind and Motion, built by Vite into
`site/` (not committed) and served from Cloudflare Pages at `llm-serve.nikhilsaravade.com`. This document is the
whole path from source to a public URL, and what has and has not been checked.

## Status

The site **is live on Cloudflare Pages** at https://llm-serve.nikhilsaravade.com (deployed 2026-09-19 from `main`
by Git integration). A `curl -I` of the live URL returned 200 with the full header set from `public/_headers`
(CSP with `script-src 'self'`, HSTS, `nosniff`, `X-Frame-Options: DENY`, COOP/CORP, Permissions-Policy) and
`Cache-Control: public, max-age=0, must-revalidate` on the HTML; an unknown path returns 404. Compare with
"What is verified" for what was and was not checked.

## What ships

```
site-src/                 source (TypeScript strict), tests, Wrangler config (alternative path)
  src/data.json           every number on the page, generated from the raw benchmark runs
  src/content/*.json      problems log, bug-injection table, verification matrix (each entry quotes a repo doc)
  public/_headers         security headers and cache rules, applied by Cloudflare
  public/404.html         not-found page
  public/theme-init.js    sets the saved theme before first paint (external so CSP can ban inline script)
  .env.production         the public site URL and repository URL baked into the build
.node-version             pins Node 22 for the Pages build
site/                     the build output: index.html, hashed /assets/*, and the files from public/
```

## Local commands

```bash
make site-setup     # once: npm ci and a Chromium for the tests
make site           # regenerate data.json from results/bench, typecheck, production build
make site-test      # ... and run the browser tests against the build
make site-preview   # serve site/ with the real _headers on http://localhost:4173
npm --prefix site-src run dev       # Vite dev server with hot reload
```

`make site` is the same build production runs. Nothing on the page is typed by hand: numbers come from
`data.json`, and the hand-written entries in `src/content` are tested against the documents they cite
(`tests/test_site_content.py`).

## Deploying with Cloudflare Pages (Git integration)

This is the primary path: no API token and no GitHub secrets. Cloudflare builds and publishes on every push.

1. Cloudflare dashboard: **Workers & Pages, Create, Pages, Connect to Git**. Authorize GitHub and choose
   `NIkhilSaravade/LLM-serve`.
2. **Production branch:** `main`.
3. **Build settings:**
   - Framework preset: None
   - Build command: `npm --prefix site-src ci && npm --prefix site-src run build`
   - Build output directory: `site`
   - Root directory: leave blank
4. No environment variables are needed: `.node-version` selects Node 22 and `site-src/.env.production` supplies
   the site and repository URLs. (If a build ever picks the wrong Node, add `NODE_VERSION=22`.)
5. **Save and Deploy.** The first build takes about two minutes.
6. When it succeeds, open the project's **Custom domains** tab, choose **Set up a custom domain**, and enter
   `llm-serve.nikhilsaravade.com`. The domain is already on Cloudflare, so the DNS record and the HTTPS
   certificate are created automatically.
7. Verify: `curl -sI https://llm-serve.nikhilsaravade.com` should show `content-security-policy`,
   `strict-transport-security` and `cache-control: public, max-age=0, must-revalidate`.

Pages also builds every other branch and pull request to its own preview URL, and reads the same `_headers` and
`404.html` from the output directory.

What Pages does not do is wait for the GitHub Actions `ci` workflow. To make CI a gate, turn on branch
protection for `main` (Settings, Branches) and require the `ci` checks before merging; Pages then only ever builds
code that passed.

### The alternative: GitHub Actions and Workers

`.github/workflows/deploy-site.yml` deploys with `wrangler` to Workers static assets, using
`site-src/wrangler.jsonc`. It is manual-only (Actions tab, Run workflow) and needs two repository secrets,
`CLOUDFLARE_API_TOKEN` (the "Edit Cloudflare Workers" template) and `CLOUDFLARE_ACCOUNT_ID`. Use it only if you
prefer deploys to be driven from GitHub; do not enable both paths for the same domain.

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

Both `/` and `/index.html` are listed on purpose: a rule for one does not cover the other, and an uncovered HTML
document would be cached by default.

## Relationship to the engine's release pipeline

This page has its own, simpler pipeline: Cloudflare Pages builds `main` on every push. The engine image is released by
`.github/workflows/release.yml` (see `docs/09-release-pipeline.md`); the two are independent. The Pages build does not
wait for CI, which is why branch protection requiring the `ci` checks is worth enabling.

## Rollback

Pages keeps every deployment. In the project's **Deployments** tab, choose an earlier one and **Rollback to this
deployment**. Because assets are content-hashed and HTML revalidates on every request, a rollback is visible
immediately.

## What is verified

Verified on a development machine:

- `tsc --noEmit` under `strict` with `noUncheckedIndexedAccess`, and a production build that picks up the
  production URLs from `.env.production`.
- The browser tests in `site-src/tests/site.spec.ts` run against `scripts/serve.mjs`, which applies the real
  `_headers`: CSP present and free of `unsafe-inline`, no inline script anywhere, no request to any other
  origin, no console or CSP error, hashed assets marked immutable, HTML marked must-revalidate, no
  horizontal overflow, WCAG 2 A/AA with no serious or critical axe violation in both themes, and the
  interactions, on desktop and on a mobile viewport.
- `wrangler deploy --dry-run` accepts `site-src/wrangler.jsonc` (the alternative path).

Verified on the live URL (2026-09-19, by `curl`): status 200, every header in the table below present, HTML not
cached, canonical and `og:image` pointing at the custom domain, 404 for an unknown path. The GitHub Actions `ci`
workflow passes all five jobs on `main`.

Not verified: the browser tests against the live URL (they run against the local server with the same
`_headers`), the `/assets/*` immutable cache header on the live site, and behaviour in Firefox or Safari (the tests
use Chromium only).

## Costs and limits

Cloudflare Pages static hosting is free within its plan limits and needs no server code. The whole build is about
0.8 MB, of which the JavaScript is roughly 150 KB gzipped.
