# Keep-alive

Keeps the Render-hosted app awake during the day so it isn't asleep when you open it,
and triggers Garage's daily Strava sync once a day (see *Daily Garage ↔ Strava sync* below).

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

## Daily Garage ↔ Strava sync (garage-030 phase 4)

The same Worker also triggers Garage's daily Strava sync. `scheduled()` dispatches
by `event.cron`, so the Worker has **two Cron Triggers**:

| Cron Trigger (UTC) | What it does |
|---|---|
| `*/12 * * * *` | The keep-alive above, unchanged (any cron other than the next one also runs it). |
| `5 7,8 * * *` | Daily sync. It fires at 07:05 and 08:05 UTC, but the code only acts when the Europe/Madrid hour is **09**, so it runs once a day at **09:05 Madrid** in summer (UTC+2) and in winter (UTC+1). Render is already awake then because of the keep-alive, so the sync adds no Render hours. |

Type the second trigger exactly as `5 7,8 * * *` (extra spaces are tolerated):
another value is treated as a keep-alive run.

When it acts, the Worker sends `POST` to `SYNC_URL` with the header
`X-Sync-Token: <SYNC_TOKEN>` and `User-Agent: curl/8.7.1`, no body and a 45 s
timeout per call. Each call does a bounded slice of work (about 30 s) and answers
JSON such as `{"pending": 0, "status": "ok", "error": "", ...}`. The Worker calls
again 2 s later while `pending > 0`, and stops at `pending == 0`, at a non-empty
`error` (for example `rate_limited`: nothing more that day), at any non-200
answer, at a failed or timed-out call, or after **6 calls**; whatever is left
waits for the next day. Visiting the Worker URL (the `fetch` handler) never syncs.

### Configuration (Cloudflare dashboard, done by the user)

Nothing here is deployed by anyone but the user, by hand, in the Cloudflare
dashboard (Workers → `strava-keepalive`):

- **Settings → Triggers → Cron Triggers**: add `5 7,8 * * *` next to the existing
  `*/12 * * * *`.
- **Settings → Variables and Secrets**:
  - `SYNC_URL` — plain variable (type *Text*): the app's sync endpoint,
    `https://<app>.onrender.com/garage/strava/sync-all/`. It must use `https` and
    end in `/sync-all/` with the final slash: the Worker never follows a redirect
    (`redirect: "manual"`), so a 3xx (Django's slash redirect, an http→https hop)
    stops the sync with `answered 301` instead of re-sending the token elsewhere.
  - `SYNC_TOKEN` — **secret** (type *Secret*): the same value as
    `GARAGE_SYNC_TOKEN` in the Render environment. Generate it once with
    `python manage.py garage_sync_token` (it prints a fresh random token and writes
    no file), paste it into both places and nowhere else.
- Then, in **Edit code**, paste this file **and replace `TARGET`** (redacted here as
  `REDACTED`) with the live `/healthz/` URL — keep the value the dashboard copy
  already has — and only then **Deploy**. Deploying this file as it is breaks the
  keep-alive: Render sleeps, and the 09:05 sync POST meets a cold start that can
  exceed its 45 s timeout.

Never write the token in this file, this README, the repo, an issue or a log. The
Worker reads it only from `env.SYNC_TOKEN` and never logs it or the URL; without
`SYNC_URL` or `SYNC_TOKEN` it logs which name is missing and does nothing. On the
Render side, without `GARAGE_SYNC_TOKEN` (or with fewer than 32 characters) the
endpoint answers 404, and a missing or different `X-Sync-Token` gets a bare 403.
The run can also be started by hand in Render's shell with
`python manage.py garage_strava_sync` (same bounded work, prints the JSON).

### Tests

```bash
node --check keepalive/cloudflare-worker.js
node --test keepalive/worker.test.mjs
```

The tests replace `fetch`, `Date`, `setTimeout` and `AbortSignal.timeout` (no
network, no waiting) and cover both crons, the 09 Madrid gate in summer, winter and
on both DST change days, the loop's stop conditions and the missing settings.

## Editing / redeploying

The live copy is edited in the Cloudflare dashboard (Workers → `strava-keepalive` →
Edit code → Deploy). This file is the source of record — keep them in sync, and set
the real target URL in the live copy (it's redacted here). The Cron Triggers live
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
