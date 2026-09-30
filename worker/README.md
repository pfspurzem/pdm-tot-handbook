# PDM ToT QR redirect worker

A tiny Cloudflare Worker that every printed QR code points at, instead of at
a Google Drive link directly. It does two things:

1. **Redirects** `https://<your-worker>.workers.dev/<lessonId>/<asset-slug>`
   to that lesson's Google Drive **folder** (not the individual file — see
   below for why).
2. **Counts scans** per asset in Workers KV, with no third-party analytics
   account, no cookies, and no client-side JS anywhere.

## Why a folder, not a file link

A Drive file "view"/"preview" link is what broke the lesson 3.1 image embed.
A folder's share link doesn't change when a file inside it is replaced,
renamed, or re-uploaded — so once a lesson's folder is linked here, you can
swap the actual video/audio file inside it freely without ever touching a
QR code or reprinting a handout. The trade-off: a scan lands on the folder
listing, one tap short of the exact asset, instead of opening it directly.

## One-time setup

```
npm install -g wrangler        # or use `npx wrangler` instead of `wrangler` below
wrangler login                 # authorizes your existing Cloudflare account
cd worker
wrangler kv:namespace create SCAN_COUNTS
# copy the "id" it prints into wrangler.toml's kv_namespaces entry

# optional — only if you want /_stats to require a key in the URL:
wrangler secret put STATS_SECRET

# optional — only if you later want scans forwarded to PostHog too:
wrangler secret put POSTHOG_API_KEY
```

## Deploy

```
wrangler deploy
```

Prints the live URL — on the free plan, something like
`https://pdm-qr-redirect.<your-subdomain>.workers.dev`.

## Adding an asset

1. Create (or reuse) that lesson's Drive folder, share it "Anyone with the
   link can view," copy the folder URL.
2. Add a line to `DESTINATIONS` in `src/index.js`:
   `"<lessonId>/<slug>": "<folder URL>"`.
3. `wrangler deploy`.
4. Generate the QR for `https://<your-worker-url>/<lessonId>/<slug>` (not
   the Drive link itself) with segno, same as any other asset.

## Checking scan counts

```
curl https://<your-worker-url>/_stats
# or, if STATS_SECRET is set:
curl "https://<your-worker-url>/_stats?key=<the secret>"
```

Returns a count and last-scan time (UTC, plus country — Cloudflare gives
that for free on every request, no extra service needed) per asset. This is
enough to answer "is anyone using these" without adding PostHog. The
PostHog forwarding in `logScan()` is there but inert until
`POSTHOG_API_KEY` is set — only reach for it if `/_stats` turns out to be
too thin (e.g. you want scans broken out over time in a real dashboard).
