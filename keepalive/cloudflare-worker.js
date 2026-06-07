// Cloudflare Worker — keep the Render app awake.
//
// THE keep-alive solution (replaces cron-job.org / the Docker pinger). Deployed
// to the Cloudflare Worker "strava-keepalive"
// (https://strava-keepalive.maxicombina.workers.dev/). This file is the source of
// record; the live copy is edited in the Cloudflare dashboard.
//
// - Cron Trigger "*/12 * * * *" fires the scheduled() handler every 12 min.
//   Cloudflare cron fires regardless of prior result (NO backoff — which is what
//   broke cron-job.org). Free tier: cron down to 1 min, 100k req/day, scheduled
//   workers up to 15 min wall-time, no per-subrequest timeout.
// - Pings /healthz/ with User-Agent "curl/8.7.1" (mimics the manual curl that
//   works) + retries with a long per-attempt timeout to ride through Render's
//   ~32s cold-start, mirroring keepalive/ping.sh (--max-time 120 --retry).
// - Active 09:00-23:59 Europe/Madrid (DST-aware, in code) so Render still sleeps
//   overnight and stays under the 750h/mo Render cap.
// - The fetch() handler runs the same ping so visiting the URL tests it manually.

const TARGET = "https://stravagancia.onrender.com/healthz/";
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
