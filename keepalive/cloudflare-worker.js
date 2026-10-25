// Cloudflare Worker — keep the Render app awake (and trigger Garage's daily Strava sync).
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
//
// Daily Garage <-> Strava sync (garage-030 phase 4), dispatched by event.cron:
// - A second Cron Trigger "5 7,8 * * *" (UTC) fires at 07:05 and 08:05 UTC; only the
//   run whose Europe/Madrid hour is 09 acts, so it is 09:05 Madrid in summer (UTC+2)
//   and in winter (UTC+1), once a day, while the keep-alive already keeps Render
//   awake (no extra Render hours).
// - It POSTs env.SYNC_URL (a plain dashboard variable, the app's
//   /garage/strava/sync-all/) with the header X-Sync-Token = env.SYNC_TOKEN, a Worker
//   SECRET equal to GARAGE_SYNC_TOKEN on Render. Neither is written in this file, and
//   neither value is ever logged. Without them the run logs which name is missing
//   and does nothing.
// - Each POST does a bounded slice of work (~30 s) and answers
//   {"pending": n, "error": "", ...}. The Worker calls again after 2 s while
//   pending > 0, and stops at pending 0, a non-empty error (e.g. rate_limited:
//   nothing more that day), a non-200 answer, a failed or timed-out call (45 s each)
//   or after SYNC_MAX_CALLS calls; whatever is left waits for the next day.
// - Redirects are never followed (redirect: "manual"): a 3xx (e.g. SYNC_URL without its
//   final slash, or http://) is a non-200 stop logged with its status, and the token
//   header is never re-sent to another URL.
// - The fetch() handler never syncs: visiting the Worker URL only pings.

const TARGET = "https://REDACTED.onrender.com/healthz/"; // set real URL in Cloudflare dashboard
const MAX_ATTEMPTS = 4;
const GAP_MS = 20000;
const FETCH_TIMEOUT_MS = 120000;

const SYNC_CRON = "5 7,8 * * *"; // UTC; must match the dashboard trigger
const SYNC_MADRID_HOUR = 9;
const SYNC_MAX_CALLS = 6;
const SYNC_GAP_MS = 2000;
const SYNC_TIMEOUT_MS = 45000;

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

function isSyncCron(cron) {
  return typeof cron === "string" && cron.trim().split(/\s+/).join(" ") === SYNC_CRON;
}

async function dailySync(env) {
  const h = madridHour();
  if (h !== SYNC_MADRID_HOUR) return `sync skip: ${h}h Madrid (runs at 09)`;
  const missing = ["SYNC_URL", "SYNC_TOKEN"].filter((name) => !(env && env[name]));
  if (missing.length) return `sync skip: ${missing.join(" and ")} not set`; // names only, never values
  for (let call = 1; call <= SYNC_MAX_CALLS; call++) {
    let data;
    try {
      const res = await fetch(env.SYNC_URL, {
        method: "POST",
        headers: { "X-Sync-Token": env.SYNC_TOKEN, "User-Agent": "curl/8.7.1" },
        redirect: "manual", // a 3xx stops below with its status; the token never follows it
        signal: AbortSignal.timeout(SYNC_TIMEOUT_MS),
      });
      if (res.status !== 200) return `sync stop: call ${call} answered ${res.status}`;
      data = await res.json();
    } catch (err) {
      // The error's name only (TimeoutError, TypeError…): its message could carry the URL.
      return `sync stop: call ${call} failed (${(err && err.name) || "error"})`;
    }
    const pending = data && data.pending;
    const error = data && data.error;
    if (!Number.isInteger(pending) || pending < 0 || typeof error !== "string") {
      return `sync stop: call ${call} gave an unexpected answer`;
    }
    console.log(`sync call ${call}: status=${data.status} pending=${pending} error=${error || "none"}`);
    if (error !== "") return `sync stop: ${error} (pending ${pending} left for tomorrow)`;
    if (pending === 0) return `sync done in ${call} call(s)`;
    if (call < SYNC_MAX_CALLS) await new Promise((r) => setTimeout(r, SYNC_GAP_MS));
  }
  return `sync stop: ${SYNC_MAX_CALLS} calls, the rest waits for tomorrow`;
}

export default {
  async scheduled(event, env, ctx) {
    if (isSyncCron(event && event.cron)) { console.log(await dailySync(env)); return; }
    const h = madridHour();
    if (h < 9) { console.log(`skip: ${h}h Madrid (outside 09-24)`); return; }
    console.log(await ping());
  },
  async fetch(request, env, ctx) {
    return new Response((await ping()) + "\n");
  },
};
