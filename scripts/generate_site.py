#!/usr/bin/env python3
"""
Build the PDM ToT lesson handbook as static, responsive, printable HTML.

Source of truth: the PDM ToT Pilot Coda doc (also reachable as a Superhuman
Docs document -- same underlying platform, same REST API), read live via the
Coda REST API. Requires CODA_API_KEY in the environment.

Only lessons listed in LESSON_ALLOWLIST are published. A lesson's non-Knowledge-Check
content blocks must have a non-blank "Body Markdown" column in Coda -- that is the
only column the public REST API returns with real formatting intact (headings,
bold, callouts). The live canvas "Body Text" column comes back flattened plain
text over the API, so it is only used as a last-resort fallback (see
canvas_fallback_to_html below).

Usage:
    CODA_API_KEY=... python3 scripts/generate_site.py
"""
from __future__ import annotations

import html
import json
import os
import re
import ssl
import sys
import urllib.parse
import urllib.request
from pathlib import Path

import markdown as md

try:
    import certifi
    SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
except ImportError:  # pragma: no cover - certifi is in requirements.txt
    SSL_CONTEXT = ssl.create_default_context()

REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = REPO_ROOT / "docs"

CODA_DOC_ID = "5Mejl6KavB"
API_BASE = f"https://coda.io/apis/v1/docs/{CODA_DOC_ID}"

TABLES = {
    "lessons": "grid-L9Rx57iaaQ",
    "activities": "grid-NUOItFXygE",
    "blocks": "grid-mS2cmY619v",
    "kc_bank": "grid-yX0FdYPHaY",
}

# Column IDs (from the Coda doc's schema -- see BRAND_GUIDELINES.md's sibling
# note in the project memory for how these were found: table_columns_read).
C_LESSON_NAME = "c-eNfNc1RqVj"
C_LESSON_NUMBER = "c-iVvbMQ6QHJ"

C_ACT_NAME = "c-BEGY-ww5eC"
C_ACT_LESSON = "c-ZrWx3PcPwo"
C_ACT_ORDER = "c-q2qiPLaxKM"

C_BLK_LESSON = "c-5bw-cstdCi"
C_BLK_ACTIVITY = "c-N4MIvXUHSr"
C_BLK_TYPE = "c-AHIpP4heIf"
C_BLK_TITLE = "c-YUodFSZ5S-"
C_BLK_BODY_MD = "c-IpCnArtQMr"
C_BLK_BODY_TEXT = "c-FLnOinMGz-"
C_BLK_INCLUDE = "c-5SoBfGZYag"
C_BLK_ORDER_NUM = "c-eYc4nQdZ8f"
C_BLK_SHOW_WRITING = "c-0mjVl5DBg5"

C_KC_QUESTION = "c-M5dESzdlgX"
C_KC_ACTIVITY = "c-rXMeov530v"
C_KC_ORDER = "c-Fx3bn8kghS"
C_KC_OPTIONS = "c-KYUiO5a0Hv"

# Media (images/audio/video) is no longer a separate Media Assets lookup --
# team members embed it directly in Body Markdown as `![caption](url)`
# (2026-10-01). See classify_embed_url/EMBED_RE below. The Content Blocks
# "...Media Assets" column and the Media Assets table were removed from Coda
# as part of this same change -- don't reintroduce a C_BLK_MEDIA/C_MEDIA_*
# constant without also re-adding that column.

# Lessons published so far. A lesson can only be added here once every non-Knowledge-Check
# block under it (with PDM ToT Include? = true) has a real Body Markdown snapshot --
# run scripts/check_coverage.py first, or ask Claude to sync any gaps it finds.
LESSON_ALLOWLIST = [
    "0.0 — Why This ToT",
    "0.1 — Share Names & Community Agreement",
    "0.2 — My Successes so Far & Active Listening",
    "1.1 — Think-Feel-Do Cycle",
    "1.2 — Growth Mindset",
    "2.1 — My Tree of Life",
    "2.2 — Roots & Fruits of My Enterprise",
    "3.1 — Elephant Story and the Power of Words",
    "4.1 — Myself, My Friend",
    "4.2 — Planning for Your Time",
    "5.1 — Growth Steps",
    "5.2 — TAKE HOME ASSIGNMENT: Share your Tree of Life with a Friend or Family Member",
]

RESPONSE_TYPES = {"Activity", "Trainer Activity", "Prompt Question", "Facilitator Scenario Check"}
GROUP_TYPES = {"Group Activity", "Group Debrief", "Group Discussion Forum", "Online ToT"}
FACILITATOR_TYPES = {"Facilitation Tip", "Trainer Tip", "Flow Check (Training Logistics)", "Facilitator Scenario Check"}


def api_get(url: str) -> dict:
    key = os.environ.get("CODA_API_KEY")
    if not key:
        sys.exit("CODA_API_KEY is not set in the environment.")
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {key}"})
    with urllib.request.urlopen(req, context=SSL_CONTEXT) as resp:
        text = resp.read().decode("utf-8")
    # Coda row text can contain raw control characters (literal newlines inside
    # a JSON string that came from a canvas) -- strict JSON parsing rejects
    # those even though they are valid inside a JSON string per the spec's
    # intent; strict=False allows them.
    return json.loads(text, strict=False)


def fetch_all_rows(table_id: str) -> list[dict]:
    rows: list[dict] = []
    url = f"{API_BASE}/tables/{table_id}/rows?valueFormat=simple&limit=200"
    while url:
        data = api_get(url)
        rows.extend(data["items"])
        url = data.get("nextPageLink")
    return rows


def val(row: dict, col_id: str, default=""):
    return row.get("values", {}).get(col_id, default)


CALLOUT_RE = re.compile(r'<callout type="(?P<type>[^"]+)">\s*(?P<body>.*?)\s*</callout>', re.DOTALL)

CALLOUT_ICON = {"note": "📝", "info": "ℹ️", "tip": "💡", "warning": "⚠️"}

# Simple embeds: a team member types `![caption](url)` directly into Body
# Markdown (2026-10-01) instead of creating a Media Assets row -- that table
# and the Content Blocks lookup to it are gone. True images render inline
# via the standard markdown image syntax (untouched here); audio/video is
# intercepted and rendered as a link + QR code instead, since embedding an
# audio/video URL as <img> would just show a broken image icon.
EMBED_RE = re.compile(r'!\[(?P<alt>[^\]]*)\]\((?P<url>https?://[^\s)]+)\)')
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp"}
AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".ogg", ".aac", ".flac"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".webm", ".avi", ".mkv"}
VIDEO_DOMAINS = {"youtube.com", "youtu.be", "vimeo.com"}


def classify_embed_url(url: str) -> str:
    """'image', 'audio', or 'video' for a `![alt](url)` simple embed. File
    extension first, then known video host, else defaults to 'image' -- the
    literal reading of markdown's image syntax (e.g. a Google Drive share
    link has no extension to go on). Mirrors the same convention used in the
    PDM ToT Google Doc export script, for consistency across both pipelines.
    """
    parsed = urllib.parse.urlparse(url)
    ext = Path(parsed.path.lower()).suffix
    if ext in AUDIO_EXTENSIONS:
        return "audio"
    if ext in VIDEO_EXTENSIONS:
        return "video"
    if ext in IMAGE_EXTENSIONS:
        return "image"
    if any(d in parsed.netloc.lower() for d in VIDEO_DOMAINS):
        return "video"
    return "image"


def qr_code_url(target_url: str, size: int = 200) -> str:
    return (
        "https://api.qrserver.com/v1/create-qr-code/"
        f"?size={size}x{size}&data={urllib.parse.quote(target_url, safe='')}"
    )


def media_link_html(alt: str, url: str, kind: str) -> str:
    # Inline elements only (span + img, no p/div) -- an embed can land either
    # on its own line (becomes the sole content of a paragraph, then unwrapped
    # by _unwrap_placeholders) or mid-sentence (stays nested inside a real
    # <p>...</p> alongside surrounding text). A block-level replacement broke
    # the mid-sentence case (invalid <p> nested in <p>); this is valid either
    # way. CSS gives .media-qr display:block so it still reads as its own row.
    label = "Listen" if kind == "audio" else "Watch"
    text = alt or f"{label} this {kind}"
    qr = qr_code_url(url)
    return (
        '<span class="media-link">🔗 '
        f'<a href="{html.escape(url)}">{label}: {html.escape(text)}</a></span>'
        f'<img class="media-qr" src="{html.escape(qr)}" alt="QR code: {html.escape(text)}" loading="lazy">'
    )


def render_markdown(text: str) -> str:
    """Body Markdown -> HTML. Handles our custom <callout> construct and
    audio/video simple embeds by stashing their rendered HTML behind a
    placeholder token, running the standard markdown converter (headings,
    bold, italic, lists, links, true images, hr) on everything else, then
    restoring the stashed HTML. A true image embed is left for markdown's
    own native image syntax to handle."""
    if not text or not text.strip():
        return ""

    placeholders: list[str] = []

    def _unwrap_placeholders(html_in: str) -> str:
        # markdown wraps a block-level placeholder token in <p>...</p> since
        # it looked like inline text; unwrap so the <aside>/<img> (which may
        # itself be or contain a block element) isn't invalidly nested in a <p>.
        return re.sub(r"<p>\s*(\x00(?:CALLOUT|MEDIA)\d+\x00)\s*</p>", r"\1", html_in)

    def _stash_media(m: re.Match) -> str:
        kind = classify_embed_url(m.group("url"))
        if kind == "image":
            return m.group(0)  # leave as-is for markdown's native ![]() handling
        placeholders.append(media_link_html(m.group("alt"), m.group("url"), kind))
        return f"\x00MEDIA{len(placeholders) - 1}\x00"

    def _stash_callout(m: re.Match) -> str:
        ctype = m.group("type")
        inner_source = EMBED_RE.sub(_stash_media, m.group("body"))
        inner_html = md.markdown(inner_source, extensions=["sane_lists", "tables"])
        inner_html = _unwrap_placeholders(inner_html)
        # Resolve any media placeholder nested inside this callout right away --
        # a single outer re.sub pass later won't recurse into this callout's own
        # stored HTML, so an unresolved \x00MEDIA..\x00 token would otherwise
        # survive verbatim into the final page.
        inner_html = re.sub(r"\x00MEDIA(\d+)\x00", lambda mm: placeholders[int(mm.group(1))], inner_html)
        # Demote heading levels inside the callout by one, so a "###" written
        # inside <callout> (h3) nests correctly under the block's own h3 title.
        for level in (3, 2, 1):
            inner_html = inner_html.replace(f"<h{level}", f"<h{level + 1}").replace(f"</h{level}>", f"</h{level + 1}>")
        icon = CALLOUT_ICON.get(ctype, "📝")
        placeholders.append(
            f'<aside class="callout callout-{html.escape(ctype)}" role="note">'
            f'<span class="callout-icon" aria-hidden="true">{icon}</span>'
            f'<div class="callout-body">{inner_html}</div></aside>'
        )
        return f"\x00CALLOUT{len(placeholders) - 1}\x00"

    without_callouts = CALLOUT_RE.sub(_stash_callout, text)
    without_media = EMBED_RE.sub(_stash_media, without_callouts)
    body_html = md.markdown(without_media, extensions=["sane_lists", "tables"])

    def _restore(m: re.Match) -> str:
        return placeholders[int(m.group(1))]

    body_html = _unwrap_placeholders(body_html)
    return re.sub(r"\x00(?:CALLOUT|MEDIA)(\d+)\x00", _restore, body_html)


def canvas_fallback_to_html(flat_text: str) -> str:
    """Last-resort renderer for a block with no Body Markdown snapshot: the
    live canvas came back from the API as flattened plain text (formatting
    stripped), so just turn blank-line-separated chunks into paragraphs."""
    if not flat_text or not flat_text.strip():
        return ""
    paras = [p.strip() for p in flat_text.split("\n") if p.strip()]
    return "\n".join(f"<p>{html.escape(p)}</p>" for p in paras)


def writing_box(label: str) -> str:
    return (
        f'<div class="writing-box"><span class="writing-box-label">{html.escape(label)}</span>'
        f'<div class="writing-box-lines" aria-hidden="true"></div></div>'
    )


def render_kc_block(activity_name: str, kc_rows: list[dict]) -> str:
    questions = sorted(
        (r for r in kc_rows if val(r, C_KC_ACTIVITY) == activity_name),
        key=lambda r: val(r, C_KC_ORDER, 0) or 0,
    )
    if not questions:
        return "<p><em>No knowledge check questions yet for this activity.</em></p>"
    items = []
    for q in questions:
        qtext = html.escape(str(val(q, C_KC_QUESTION, "")).strip())
        options_raw = str(val(q, C_KC_OPTIONS, "")).strip()
        if options_raw:
            opts = "".join(
                f'<li><span class="option-box" aria-hidden="true"></span> {html.escape(o.strip())}</li>'
                for o in options_raw.split("\n") if o.strip()
            )
            answer_html = f'<ul class="kc-options">{opts}</ul>'
        else:
            answer_html = writing_box("Your answer")
        items.append(f"<li><p>{qtext}</p>{answer_html}</li>")
    return f'<ol class="kc-questions">{"".join(items)}</ol>'


def render_block(block: dict, kc_rows: list[dict]) -> str:
    btype = str(val(block, C_BLK_TYPE, "")).strip()
    title = str(val(block, C_BLK_TITLE, "")).strip()
    # Block titles already carry their own author-chosen emoji (📘, 👤, 🔑, ...)
    # almost everywhere in this doc, so we don't prepend a second icon here --
    # content type is instead distinguished by the type-* CSS class below.
    heading = f"<h3>{html.escape(title)}</h3>" if title else ""

    # Media is no longer a separate lookup -- it's embedded directly in the
    # body as `![caption](url)` and handled inside render_markdown itself.

    if btype == "Knowledge Check":
        activity_name = str(val(block, C_BLK_ACTIVITY, "")).strip()
        body = render_kc_block(activity_name, kc_rows)
    else:
        body_md = str(val(block, C_BLK_BODY_MD, "")).strip()
        if body_md:
            body = render_markdown(body_md)
        else:
            body = canvas_fallback_to_html(str(val(block, C_BLK_BODY_TEXT, "")))

    extra_box = ""
    show_writing = bool(val(block, C_BLK_SHOW_WRITING, False))
    if btype in GROUP_TYPES:
        extra_box = writing_box("Team notes & insights")
    elif btype in RESPONSE_TYPES:
        extra_box = writing_box("Your response")
    elif show_writing:
        extra_box = writing_box("Write or draw here")

    type_class = "type-" + re.sub(r"[^a-z0-9]+", "-", btype.lower()).strip("-") if btype else "type-other"
    facilitator_class = " facilitator-note" if btype in FACILITATOR_TYPES else ""

    return (
        f'<section class="content-block {type_class}{facilitator_class}">'
        f"{heading}{body}{extra_box}</section>"
    )


def slugify(text: str) -> str:
    text = re.sub(r"[’‘'\"]", "", text)
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return text or "lesson"


PAGE_CSS = (REPO_ROOT / "scripts" / "style_template.css").read_text(encoding="utf-8")


def page_shell(*, title: str, subtitle: str, nav_html: str, body_html: str, is_index: bool = False) -> str:
    home_link = "" if is_index else '<a class="back-link" href="../index.html">&larr; All lessons</a>'
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)} — PDM Light Touch ToT</title>
<meta name="description" content="{html.escape(subtitle)}">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Oswald:wght@300;500&amp;family=Quicksand:wght@400;500;700&amp;display=swap" rel="stylesheet">
<style>
{PAGE_CSS}
</style>
</head>
<body>
<a class="skip-link" href="#main">Skip to content</a>
<header class="site-header">
  <div class="wrap header-inner">
    <a class="brand" href="{'index.html' if is_index else '../index.html'}"><span class="brand-mark" aria-hidden="true">〜</span> SEE change <span class="brand-sub">PDM Light Touch ToT</span></a>
    {home_link}
  </div>
</header>
<main id="main" class="wrap">
  <h1>{html.escape(title)}</h1>
  {f'<p class="subtitle">{html.escape(subtitle)}</p>' if subtitle else ''}
  {nav_html}
  {body_html}
</main>
<footer class="site-footer">
  <div class="wrap">
    <p>SEE Change Initiative · Johns Hopkins Bloomberg School of Public Health</p>
  </div>
</footer>
</body>
</html>
"""


def build():
    print("Fetching Coda data…")
    lessons = fetch_all_rows(TABLES["lessons"])
    activities = fetch_all_rows(TABLES["activities"])
    blocks = fetch_all_rows(TABLES["blocks"])
    kc_rows = fetch_all_rows(TABLES["kc_bank"])

    lessons_by_name = {str(val(r, C_LESSON_NAME)): r for r in lessons}
    published = [name for name in LESSON_ALLOWLIST if name in lessons_by_name]
    missing = [name for name in LESSON_ALLOWLIST if name not in lessons_by_name]
    if missing:
        print(f"WARNING: lessons not found in Coda, skipping: {missing}", file=sys.stderr)

    published.sort(key=lambda name: val(lessons_by_name[name], C_LESSON_NUMBER, 0) or 0)

    lessons_dir = OUT_DIR / "lessons"
    lessons_dir.mkdir(parents=True, exist_ok=True)

    index_items = []
    for lesson_name in published:
        lesson_activities = sorted(
            (a for a in activities if val(a, C_ACT_LESSON) == lesson_name),
            key=lambda a: val(a, C_ACT_ORDER, 0) or 0,
        )
        sections = []
        nav_items = []
        for act in lesson_activities:
            act_name = str(val(act, C_ACT_NAME)).strip()
            act_blocks = sorted(
                (
                    b for b in blocks
                    if val(b, C_BLK_ACTIVITY) == act_name and val(b, C_BLK_LESSON) == lesson_name
                    and bool(val(b, C_BLK_INCLUDE, False))
                ),
                key=lambda b: val(b, C_BLK_ORDER_NUM, 9999) or 9999,
            )
            if not act_blocks:
                # A genuine content gap (this activity has zero blocks in Coda,
                # same as some lessons) -- skip it rather than render an empty
                # heading that still eats a full page break in print.
                print(f"WARNING: activity '{act_name}' has no included content blocks, skipping", file=sys.stderr)
                continue
            act_id = slugify(act_name)
            nav_items.append(f'<li><a href="#{act_id}">{html.escape(act_name)}</a></li>')
            rendered_blocks = "".join(render_block(b, kc_rows) for b in act_blocks)
            sections.append(
                f'<article class="activity" id="{act_id}"><h2>{html.escape(act_name)}</h2>{rendered_blocks}</article>'
            )

        if not lesson_activities:
            print(f"WARNING: lesson '{lesson_name}' has no activities", file=sys.stderr)

        nav_html = f'<nav class="lesson-nav" aria-label="Activities in this lesson"><ul>{"".join(nav_items)}</ul></nav>' if nav_items else ""
        page_html = page_shell(
            title=lesson_name,
            subtitle="",
            nav_html=nav_html,
            body_html="".join(sections),
        )
        slug = slugify(lesson_name)
        out_path = lessons_dir / f"{slug}.html"
        out_path.write_text(page_html, encoding="utf-8")
        print(f"  wrote {out_path.relative_to(REPO_ROOT)}")
        index_items.append((lesson_name, slug))

    index_list = "".join(
        f'<li><a href="lessons/{slug}.html">{html.escape(name)}</a></li>' for name, slug in index_items
    )
    index_html = page_shell(
        title="PDM Light Touch ToT",
        subtitle="Lesson handbook — mobile-friendly to read, print-ready to hand out.",
        nav_html="",
        body_html=f'<ul class="lesson-index">{index_list}</ul>',
        is_index=True,
    )
    (OUT_DIR / "index.html").write_text(index_html, encoding="utf-8")
    print(f"  wrote {OUT_DIR / 'index.html'}")
    print(f"Done: {len(index_items)} lesson page(s) published.")


if __name__ == "__main__":
    build()
