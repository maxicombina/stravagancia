// Cloudflare Worker — keep the Render app awake.
//
// THE keep-alive solution (replaces cron-job.org / the old GitHub Actions pingers).
// Deployed as the Cloudflare Worker "strava-keepalive". This file is the source of
// record; the live copy is edited in the Cloudflare dashboard.
//
// NOTE: TARGET is redacted in this public repo (we don't publish the Render URL to
// avoid drive-by pings keeping the free-tier service awake). The live Worker uses
// the real `https://<app>.onrender.com/healthz/` URL — set it in the dashboard.
//
// - Cron Trigger "*/12 * * * *" fires scheduled() every 12 min. Cloudflare cron
//   fires regardless of prior result (NO backoff — what broke cron-job.org). Free
//   tier: cron down to 1 min, 100k req/day, scheduled workers up to 15 min wall
//   time, no per-subrequest timeout.
// - Pings /healthz/ with User-Agent "curl/8.7.1" (mimics the manual curl that
//   works) + retries with a long per-attempt timeout to ride through Render's
//   ~32s cold start.
// - Active 09:00-23:59 Europe/Madrid (DST-aware, in code) so Render still sleeps
//   overnight and stays under the 750h/mo Render cap.
// - The fetch() handler runs the same ping so visiting the URL tests it manually.

const TARGET = "https://REDACTED.onrender.com/healthz/"; // set real URL in Cloudflare dashboard
const MAX_ATTEMPTS = 4;
const GAP_MS = 20000;
const FETCH_TIMEOUT_MS = 120000;

function madridHour() {
  return Number(new Intl.DateTimeFormat("en-GB", {
    timeZone: "Europe/Madrid", hour: "2-digit", hourCycle: "h23",
  }).format(new Date()));
}

async function ping() {
  for (let attempt = 1; attempt <= MAX_ATTEMPTS; attempt++) {
    try {
      const res = await fetch(TARGET, {
        headers: { "User-Agent": "curl/8.7.1" },
        signal: AbortSignal.timeout(FETCH_TIMEOUT_MS),
      });
      const body = (await res.text()).trim();
      if (res.ok) return `OK attempt ${attempt}: ${res.status} body="${body}"`;
      console.log(`attempt ${attempt}: status ${res.status}, retrying`);
    } catch (err) {
      console.log(`attempt ${attempt}: ${err}, retrying`);
    }
    if (attempt < MAX_ATTEMPTS) await new Promise((r) => setTimeout(r, GAP_MS));
  }
  return `woke (no clean 200 in ${MAX_ATTEMPTS} tries; wake triggered)`;
}

export default {
  async scheduled(event, env, ctx) {
    const h = madridHour();
    if (h < 9) { console.log(`skip: ${h}h Madrid (outside 09-24)`); return; }
    console.log(await ping());
  },
  async fetch(request, env, ctx) {
    return new Response((await ping()) + "\n");
  },
};
