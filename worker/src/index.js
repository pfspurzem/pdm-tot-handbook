/**
 * PDM ToT — QR redirect + scan-count worker.
 *
 * Every printed QR code encodes a URL on this Worker, never a destination
 * directly. That buys two things segno alone can't:
 *   - a scan count per asset, via Workers KV — no third-party analytics
 *     account, no cookies, no client-side JS on the destination page
 *   - the ability to repoint a destination later (a moved file, a
 *     re-recorded video) without reprinting anything already handed out
 *
 * Destinations are Google Drive FOLDER links, one per lesson — not links to
 * individual files. A folder share link survives a file inside it being
 * replaced, renamed, or re-uploaded; a direct file "view"/"preview" link
 * does not reliably (this is what broke the lesson 3.1 image embed).
 *
 * Add a new asset: add one line to DESTINATIONS below, `wrangler deploy`.
 */

const DESTINATIONS = {
  // "<lessonId>/<asset-slug>": "<Google Drive folder URL for that lesson>"
  "3.1/elephant-story-pt1": "REPLACE_WITH_DRIVE_FOLDER_URL_FOR_3.1",
  "3.1/elephant-story-pt2": "REPLACE_WITH_DRIVE_FOLDER_URL_FOR_3.1",
  "3.1/limiting-beliefs-video": "REPLACE_WITH_DRIVE_FOLDER_URL_FOR_3.1",
};

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const slug = url.pathname.replace(/^\/+/, "").replace(/\/+$/, "");

    if (slug === "") {
      return new Response("PDM ToT QR redirect worker is running.\n", {
        headers: { "content-type": "text/plain" },
      });
    }

    if (slug === "_stats") {
      return handleStats(url, env);
    }

    const destination = DESTINATIONS[slug];
    if (!destination || destination.startsWith("REPLACE_WITH_")) {
      return new Response("Not found.\n", { status: 404 });
    }

    // Log after responding, not before — a KV hiccup should never slow or
    // block the redirect itself. waitUntil keeps the Worker alive long
    // enough for this to finish even though the response already went out.
    ctx.waitUntil(logScan(slug, request, env));

    return Response.redirect(destination, 302);
  },
};

async function logScan(slug, request, env) {
  if (env.SCAN_COUNTS) {
    const countKey = `${slug}:count`;
    const current = parseInt((await env.SCAN_COUNTS.get(countKey)) || "0", 10);
    await env.SCAN_COUNTS.put(countKey, String(current + 1));
    await env.SCAN_COUNTS.put(
      `${slug}:last`,
      JSON.stringify({
        at: new Date().toISOString(),
        country: request.cf?.country || null,
      })
    );
  }

  // Optional, off by default: forward the scan to PostHog too, if someone
  // ever wants a richer dashboard than the built-in /_stats. Only fires
  // when POSTHOG_API_KEY is set via `wrangler secret put` — no key set,
  // no network call, no dependency.
  if (env.POSTHOG_API_KEY) {
    const host = env.POSTHOG_HOST || "https://app.posthog.com";
    await fetch(`${host}/capture/`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        api_key: env.POSTHOG_API_KEY,
        event: "qr_scan",
        properties: {
          slug,
          country: request.cf?.country || null,
          distinct_id: slug, // no per-viewer identity is collected or wanted
        },
      }),
    }).catch((err) => console.error("posthog capture failed", err));
  }
}

async function handleStats(url, env) {
  if (env.STATS_SECRET && url.searchParams.get("key") !== env.STATS_SECRET) {
    return new Response("Unauthorized.\n", { status: 401 });
  }
  if (!env.SCAN_COUNTS) {
    return new Response(JSON.stringify({ error: "SCAN_COUNTS KV not bound" }), {
      status: 500,
      headers: { "content-type": "application/json" },
    });
  }
  const out = {};
  for (const slug of Object.keys(DESTINATIONS)) {
    const count = await env.SCAN_COUNTS.get(`${slug}:count`);
    const last = await env.SCAN_COUNTS.get(`${slug}:last`);
    out[slug] = {
      count: count ? parseInt(count, 10) : 0,
      last: last ? JSON.parse(last) : null,
    };
  }
  return new Response(JSON.stringify(out, null, 2), {
    headers: { "content-type": "application/json" },
  });
}
