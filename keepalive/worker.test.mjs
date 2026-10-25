// Tests of cloudflare-worker.js (garage-030 phase 4): `node --test keepalive/worker.test.mjs`.
//
// No network: global fetch is replaced by a script of answers, Date by a fixed instant,
// setTimeout by an immediate one that records its delay and AbortSignal.timeout by a spy.
// The token and URL below are synthetic; nothing here is a real secret.
import { afterEach, beforeEach, test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import worker from "./cloudflare-worker.js";

const KEEPALIVE_CRON = "*/12 * * * *";
const SYNC_CRON = "5 7,8 * * *";
const SYNC_URL = "https://garage.invalid/garage/strava/sync-all/";
const SYNC_TOKEN = "test-only-not-a-secret-xxxxxxxxxxxxxxxxxxxx";
const ENV = Object.freeze({ SYNC_URL, SYNC_TOKEN });
const TARGET = "https://REDACTED.onrender.com/healthz/";

const real = {
  Date: globalThis.Date, fetch: globalThis.fetch, setTimeout: globalThis.setTimeout,
  timeout: AbortSignal.timeout, log: console.log,
};
let calls, gaps, timeouts, logs;

beforeEach(() => {
  calls = []; gaps = []; timeouts = []; logs = [];
  globalThis.setTimeout = (fn, ms) => { gaps.push(ms); queueMicrotask(fn); return 0; };
  AbortSignal.timeout = (ms) => { timeouts.push(ms); return new AbortController().signal; };
  console.log = (...args) => { logs.push(args.join(" ")); };
  serve(json({ pending: 0, status: "ok", error: "" }));
});

afterEach(() => {
  globalThis.Date = real.Date;
  globalThis.fetch = real.fetch;
  globalThis.setTimeout = real.setTimeout;
  AbortSignal.timeout = real.timeout;
  console.log = real.log;
});

/** Freeze `new Date()` and `Date.now()` at an ISO instant (UTC). */
function at(iso) {
  const fixed = new real.Date(iso).getTime();
  globalThis.Date = class extends real.Date {
    constructor(...args) { super(...(args.length ? args : [fixed])); }
    static now() { return fixed; }
  };
}

function json(body, status = 200) {
  return { status, text: JSON.stringify(body) };
}

/** Answers in order; the last one repeats. An Error is thrown by fetch. */
function serve(...answers) {
  globalThis.fetch = async (url, init = {}) => {
    calls.push({ url: String(url), method: init.method || "GET", headers: { ...(init.headers || {}) },
                 body: init.body, signal: init.signal, redirect: init.redirect });
    const next = answers.length > 1 ? answers.shift() : answers[0];
    if (next instanceof Error) throw next;
    return new Response(next.text, { status: next.status, headers: next.headers || {} });
  };
}

const syncCalls = () => calls.filter((c) => c.url === SYNC_URL);
const pending = (n, extra = {}) => json({ pending: n, status: n ? "partial" : "ok", error: "", accounts: 1, ...extra });

async function runSync(...args) {
  const [env, iso] = args.length ? args : [ENV]; // runSync(undefined) really passes no env
  at(iso || "2026-07-15T07:05:00Z");
  await worker.scheduled({ cron: SYNC_CRON, scheduledTime: new Date().getTime() }, env, {});
}

function assertNoSecretsLogged() {
  for (const line of logs) {
    assert.ok(!line.includes(SYNC_TOKEN), `token in log: ${line}`);
    assert.ok(!line.includes(SYNC_URL) && !line.includes("garage.invalid"), `URL in log: ${line}`);
  }
}

// --- keep-alive: unchanged behaviour ---------------------------------------------------

test("keep-alive cron pings /healthz/ by GET with the curl UA and never calls the sync", async () => {
  at("2026-07-15T08:00:00Z"); // 10:00 Madrid (summer)
  serve({ status: 200, text: "ok\n" });
  await worker.scheduled({ cron: KEEPALIVE_CRON }, ENV, {});
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, TARGET);
  assert.equal(calls[0].method, "GET");
  assert.deepEqual(calls[0].headers, { "User-Agent": "curl/8.7.1" });
  assert.deepEqual(timeouts, [120000]);
  assert.deepEqual(logs, ['OK attempt 1: 200 body="ok"']);
  assert.equal(syncCalls().length, 0);
});

test("keep-alive skips before 09 Madrid and retries 4 times 20 s apart as before", async () => {
  at("2026-01-15T07:48:00Z"); // 08:48 Madrid (winter)
  await worker.scheduled({ cron: KEEPALIVE_CRON }, ENV, {});
  assert.equal(calls.length, 0);
  assert.deepEqual(logs, ["skip: 8h Madrid (outside 09-24)"]);

  logs = [];
  at("2026-01-15T22:59:00Z"); // 23:59 Madrid: still active
  serve({ status: 503, text: "waking" });
  await worker.scheduled({ cron: KEEPALIVE_CRON }, ENV, {});
  assert.equal(calls.length, 4);
  assert.ok(calls.every((c) => c.url === TARGET && c.method === "GET"));
  assert.deepEqual(gaps, [20000, 20000, 20000]);
  assert.deepEqual(timeouts, [120000, 120000, 120000, 120000]);
  assert.equal(logs.at(-1), "woke (no clean 200 in 4 tries; wake triggered)");
});

test("an unknown or missing cron keeps the keep-alive behaviour", async () => {
  at("2026-07-15T10:00:00Z");
  serve({ status: 200, text: "ok" });
  await worker.scheduled({ cron: "0 * * * *" }, ENV, {});
  await worker.scheduled({}, ENV, {});
  assert.deepEqual(calls.map((c) => c.url), [TARGET, TARGET]);
});

test("the fetch handler only pings, even with the sync configured", async () => {
  at("2026-07-15T07:05:00Z"); // 09:05 Madrid
  serve({ status: 200, text: "ok" });
  const response = await worker.fetch(new Request("https://worker.invalid/"), ENV, {});
  assert.equal(await response.text(), 'OK attempt 1: 200 body="ok"\n');
  assert.deepEqual(calls.map((c) => c.url), [TARGET]);
});

// --- daily sync: when it acts -----------------------------------------------------------

for (const [label, acts, skips] of [
  ["summer (CEST, UTC+2)", "2026-07-15T07:05:00Z", "2026-07-15T08:05:00Z"],
  ["winter (CET, UTC+1)", "2026-01-15T08:05:00Z", "2026-01-15T07:05:00Z"],
  ["the day summer time starts", "2026-03-29T07:05:00Z", "2026-03-29T08:05:00Z"],
  ["the day summer time ends", "2026-10-25T08:05:00Z", "2026-10-25T07:05:00Z"],
]) {
  test(`sync acts only at 09 Madrid: ${label}`, async () => {
    await runSync(ENV, skips);
    assert.equal(calls.length, 0);
    assert.match(logs[0], /^sync skip: (8|10)h Madrid \(runs at 09\)$/);
    await runSync(ENV, acts);
    assert.equal(syncCalls().length, 1);
    assert.equal(calls.length, 1, "the sync cron never pings /healthz/");
  });
}

test("every day of 2026 exactly one of the two UTC fires acts", async () => {
  for (let day = 0; day < 365; day++) {
    const date = new real.Date(real.Date.UTC(2026, 0, 1 + day)).toISOString().slice(0, 10);
    const before = syncCalls().length;
    await runSync(ENV, `${date}T07:05:00Z`);
    await runSync(ENV, `${date}T08:05:00Z`);
    assert.equal(syncCalls().length - before, 1, date);
  }
});

test("the cron string is matched ignoring extra spaces", async () => {
  at("2026-07-15T07:05:00Z");
  await worker.scheduled({ cron: "  5  7,8 * *   * " }, ENV, {});
  assert.equal(syncCalls().length, 1);
});

// --- daily sync: the request and the loop ----------------------------------------------

test("each call is a bodiless POST with the token header, the curl UA and a 45 s timeout", async () => {
  await runSync();
  assert.equal(calls.length, 1);
  const [call] = calls;
  assert.equal(call.url, SYNC_URL);
  assert.equal(call.method, "POST");
  assert.deepEqual(call.headers, { "X-Sync-Token": SYNC_TOKEN, "User-Agent": "curl/8.7.1" });
  assert.equal(call.body, undefined);
  assert.equal(call.redirect, "manual", "a redirect is never followed with the token");
  assert.ok(call.signal instanceof AbortSignal);
  assert.deepEqual(timeouts, [45000]);
  assert.deepEqual(gaps, []);
  assert.equal(logs.at(-1), "sync done in 1 call(s)");
  assertNoSecretsLogged();
});

test("it repeats 2 s apart until pending is 0", async () => {
  serve(pending(2), pending(1), pending(0));
  await runSync();
  assert.equal(syncCalls().length, 3);
  assert.deepEqual(gaps, [2000, 2000]);
  assert.deepEqual(timeouts, [45000, 45000, 45000]);
  assert.deepEqual(logs, [
    "sync call 1: status=partial pending=2 error=none",
    "sync call 2: status=partial pending=1 error=none",
    "sync call 3: status=ok pending=0 error=none",
    "sync done in 3 call(s)",
  ]);
});

test("a non-empty error stops it at once, pending or not", async () => {
  serve(pending(1), pending(3, { status: "failed", error: "rate_limited" }), pending(0));
  await runSync();
  assert.equal(syncCalls().length, 2);
  assert.deepEqual(gaps, [2000]);
  assert.equal(logs.at(-1), "sync stop: rate_limited (pending 3 left for tomorrow)");
});

for (const status of [403, 404, 405, 500, 502, 201]) {
  test(`a ${status} answer stops it`, async () => {
    serve(pending(1), json({ pending: 1, error: "" }, status));
    await runSync();
    assert.equal(syncCalls().length, 2);
    assert.equal(logs.at(-1), `sync stop: call 2 answered ${status}`);
    assertNoSecretsLogged();
  });
}

for (const status of [301, 302, 307, 308]) {
  test(`a ${status} redirect is not followed: one call, the token sent once, a stop with its status`, async () => {
    // Django's slash redirect for a SYNC_URL without its final "/" (or an http->https hop).
    serve({ status, text: "", headers: { Location: "https://elsewhere.invalid/garage/strava/sync-all/" } }, pending(0));
    await runSync();
    assert.equal(calls.length, 1);
    assert.equal(calls[0].redirect, "manual");
    assert.equal(logs.at(-1), `sync stop: call 1 answered ${status}`);
    assertNoSecretsLogged();
  });
}

test("it stops after K = 6 calls while work remains", async () => {
  serve(pending(4));
  await runSync();
  assert.equal(syncCalls().length, 6);
  assert.deepEqual(gaps, [2000, 2000, 2000, 2000, 2000]);
  assert.equal(logs.at(-1), "sync stop: 6 calls, the rest waits for tomorrow");
});

test("a timed-out or failed call stops it without logging the URL", async () => {
  const timeout = new DOMException(`The operation to ${SYNC_URL} was aborted due to timeout`, "TimeoutError");
  serve(pending(1), timeout);
  await runSync();
  assert.equal(syncCalls().length, 2);
  assert.equal(logs.at(-1), "sync stop: call 2 failed (TimeoutError)");
  calls = []; logs = [];
  serve(new TypeError(`fetch failed for ${SYNC_URL} with ${SYNC_TOKEN}`));
  await runSync();
  assert.equal(syncCalls().length, 1);
  assert.equal(logs.at(-1), "sync stop: call 1 failed (TypeError)");
  assertNoSecretsLogged();
});

for (const [label, text] of [
  ["not JSON", "<html>oops</html>"],
  ["no pending", JSON.stringify({ status: "ok", error: "" })],
  ["a fractional pending", JSON.stringify({ pending: 1.5, error: "" })],
  ["a negative pending", JSON.stringify({ pending: -1, error: "" })],
  ["a text pending", JSON.stringify({ pending: "2", error: "" })],
  ["no error", JSON.stringify({ pending: 2 })],
  ["null", "null"],
]) {
  test(`an unexpected answer (${label}) stops it`, async () => {
    serve({ status: 200, text });
    await runSync();
    assert.equal(syncCalls().length, 1);
    assert.match(logs.at(-1), /^sync stop: call 1 (gave an unexpected answer|failed \(SyntaxError\))$/);
  });
}

// --- daily sync: configuration and secrets ---------------------------------------------

for (const [label, env, names] of [
  ["no SYNC_URL", { SYNC_TOKEN }, "SYNC_URL"],
  ["no SYNC_TOKEN", { SYNC_URL }, "SYNC_TOKEN"],
  ["an empty SYNC_TOKEN", { SYNC_URL, SYNC_TOKEN: "" }, "SYNC_TOKEN"],
  ["neither", {}, "SYNC_URL and SYNC_TOKEN"],
  ["no env at all", undefined, "SYNC_URL and SYNC_TOKEN"],
]) {
  test(`with ${label} it calls nothing and logs only the missing names`, async () => {
    await runSync(env);
    assert.equal(calls.length, 0);
    assert.deepEqual(logs, [`sync skip: ${names} not set`]);
    assertNoSecretsLogged();
  });
}

test("the Worker source and its README hold no secret nor real URL", () => {
  for (const name of ["cloudflare-worker.js", "README.md"]) {
    const text = readFileSync(new URL(`./${name}`, import.meta.url), "utf8");
    assert.doesNotMatch(text, /[A-Za-z0-9_-]{40,}/, `${name}: a token-like string`);
    // Only placeholders (REDACTED, <app>) may name the Render host.
    assert.doesNotMatch(text, /https:\/\/[a-z0-9-]+\.onrender\.com/, `${name}: a real-looking Render URL`);
  }
  const source = readFileSync(new URL("./cloudflare-worker.js", import.meta.url), "utf8");
  assert.match(source, /"X-Sync-Token": env\.SYNC_TOKEN/);
  assert.match(source, /redirect: "manual"/);
  assert.doesNotMatch(source, /SYNC_TOKEN\s*=/, "the token is never assigned in code");
});

test("the README's deploy steps restore the live TARGET before Deploy and ask for an https SYNC_URL", () => {
  // This file's TARGET is redacted: deploying it as it is would break the keep-alive (review of phase 4).
  const readme = readFileSync(new URL("./README.md", import.meta.url), "utf8");
  const steps = readme.slice(readme.indexOf("### Configuration"), readme.indexOf("### Tests"));
  assert.ok(steps.length > 0);
  assert.match(steps, /replace `TARGET`[\s\S]*live `\/healthz\/` URL[\s\S]*Deploy/);
  assert.match(steps, /must use `https` and\s+end in `\/sync-all\/` with the final slash/);
});
