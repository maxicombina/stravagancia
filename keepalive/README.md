# Keep-alive

Keeps the Render-hosted app awake during the day so it isn't asleep when you open it.

> The app's public URL is intentionally **not** written in this repo (it's public) to
> avoid drive-by pings keeping the free-tier service awake. The real URL lives in the
> Cloudflare Worker (dashboard) and the deployment config.

## The problem

Render's free tier spins a service down after ~15 min of inactivity; the next
request then pays a ~30s cold start (and Render returns `503` while spinning up).
External pingers that **back off on failure** make this worse: a cron service like
cron-job.org records the cold-start `503` as a failure, backs off, and spaces its
pings past the 15-min window — so the service keeps re-sleeping and every ping is
cold. A manual `curl --retry --max-time 120` works because it rides through the
`503 → 200` in a single shot and never "gives up".

## The solution — a Cloudflare Worker

[`cloudflare-worker.js`](./cloudflare-worker.js) is deployed as the Cloudflare
Worker **`strava-keepalive`** with a **Cron Trigger `*/12 * * * *`** (every 12 min).

Why Cloudflare Workers:

- **No backoff** — a cron trigger fires on schedule regardless of the previous
  result, so a cold-start `503` never degrades the schedule (the fix cron-job.org
  and the old GitHub Actions pingers couldn't give us).
- **Behaves like the working `curl`** — the Worker `fetch`es `/healthz/` with
  `User-Agent: curl/8.7.1` and retries (4 attempts, 20s gap, 120s timeout each) to
  ride through the cold start. The custom UA also sidesteps any pinger filtering.
- **Free & zero-maintenance** — no VM, no public IP, no credit card. Free tier
  covers it easily (100k req/day; we do ~120). Cron can go down to 1-min intervals.

### Active hours

The Worker only pings **09:00–23:59 Europe/Madrid** (DST-aware, computed in code via
`Intl.DateTimeFormat`). Outside that it logs `skip` and does nothing, so Render is
left to sleep overnight and stays well under Render's 750h/month free cap. The cron
itself fires 24/7 (Cloudflare cron runs in UTC and can't track Madrid DST), but the
in-code hour gate is what actually decides whether to ping.

## Editing / redeploying

The live copy is edited in the Cloudflare dashboard (Workers → `strava-keepalive` →
Edit code → Deploy). This file is the source of record — keep them in sync, and set
the real target URL in the live copy (it's redacted here). The Cron Trigger lives
under the Worker's **Settings → Triggers → Cron Triggers**.

To test manually, open the Worker URL: the `fetch` handler runs the same ping and
returns the result (e.g. `OK attempt 1: 200 body="ok"`). Per-run output is visible
under the Worker's **Observability → Logs** (Live).

## Related

The Django side logs every `/healthz/` hit with the client IP + User-Agent
(`strava_integration/views_ui.py`), so keep-alive traffic is visible in Render logs.

> History: earlier attempts used cron-job.org (backed off), two GitHub Actions
> pinger workflows (GitHub drops most scheduled runs; now removed), a self-hosted
> Docker pinger on an Oracle Cloud Always Free ARM VM (perpetual "out of host
> capacity"), and GCP e2-micro (compute free but the in-use external IPv4 costs
> ~$3.65/mo, so not $0). Cloudflare Workers won on cost, reliability, and zero
> maintenance.
