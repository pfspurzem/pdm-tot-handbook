# PDM ToT Handbook

Static, responsive, print-ready lesson handbook for the PDM Light Touch ToT program, generated from the [PDM ToT Pilot Coda doc](https://docs.superhuman.com/d/_d5Mejl6KavB) and published via GitHub Pages.

**Live site:** https://pfspurzem.github.io/pdm-tot-handbook/ (enable Pages in repo settings if this 404s — see below)

## How it works

`scripts/generate_site.py` reads the doc's Lessons → Activities → Content Blocks (and the Knowledge Check Bank, and Media Assets) live via the Coda REST API, and writes one static HTML file per lesson into `docs/`, which GitHub Pages serves.

Each page is self-contained: the same CSS (`scripts/style_template.css`, embedded into every page) handles a responsive on-screen layout *and* a print stylesheet (`@media print`), so "Print" from the browser produces a clean handout — no separate print version to maintain.

## Publishing an update

Only lessons listed in `LESSON_ALLOWLIST` at the top of `scripts/generate_site.py` are published. A lesson can only be added there once every one of its content blocks (`PDM ToT Include? = true`, excluding Knowledge Check blocks, which read from the Knowledge Check Bank instead) has real content in its **Body Markdown** column in Coda — that's the only column the public Coda REST API returns with formatting (headings, bold, callouts) intact; the live canvas comes back as flattened plain text over the API. If a block's Body Markdown is blank or stale, ask Claude (which has direct canvas access) to refresh it before adding that lesson here.

To rebuild and publish:
1. Go to this repo's **Actions** tab → **Build & Publish** → **Run workflow**.
2. It pulls the current Coda content and pushes updated HTML to `docs/` if anything changed.

There's no scheduled rebuild yet — it only runs when triggered. Add a `schedule:` block to `.github/workflows/build.yml` if you want it to refresh automatically (e.g. nightly).

## Running locally

```
python3 -m venv .venv
.venv/bin/pip install -r scripts/requirements.txt
CODA_API_KEY=... .venv/bin/python3 scripts/generate_site.py
```

Open `docs/index.html` in a browser to preview.

## Brand

See `BRAND_GUIDELINES.md` for the SEE Change color palette, typography (Oswald/Quicksand), and voice — already baked into `scripts/style_template.css`.

## Repo secrets

- `CODA_API_KEY` — a Coda personal API token with read access to the PDM ToT Pilot doc. Set under Settings → Secrets and variables → Actions.

## QR codes for printed media

Video/audio assets that can't go on paper directly (currently the Elephant
Story clips and the Limiting Beliefs video, all Google Drive-hosted) get a
printed QR code that points at a small Cloudflare Worker rather than at the
Drive link itself, so scans can be counted and destinations repointed
without reprinting. See `worker/README.md`.
