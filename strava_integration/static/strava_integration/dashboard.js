// --- CSRF helper ---
function getCsrfToken() {
  const match = document.cookie.match(/csrftoken=([^;]+)/);
  return match ? decodeURIComponent(match[1]) : '';
}

// --- Message helper ---
let messageTimeout;
function showMessage(text, isError = false) {
  const el = document.getElementById('message');
  el.textContent = text;
  el.className = isError
    ? 'px-4 py-3 rounded text-sm font-medium bg-red-100 text-red-800'
    : 'px-4 py-3 rounded text-sm font-medium bg-green-100 text-green-800';
  clearTimeout(messageTimeout);
  messageTimeout = setTimeout(() => el.className = 'hidden', 8000);
}

// --- Format seconds as '1m 04s' or '45s' ---
function formatSeconds(s) {
  s = Math.round(s);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60), rem = s % 60;
  return `${m}m ${rem}s`;
}

// --- POST helper: disables all buttons during request ---
const buttons = ['btn-load-athlete', 'btn-detect', 'btn-load-missing'];
async function postAction(url) {
  buttons.forEach(id => document.getElementById(id).disabled = true);
  try {
    const res = await fetch(url, {
      method: 'POST',
      headers: { 'X-CSRFToken': getCsrfToken() },
    });
    const data = await res.json();
    return { ok: res.ok, data };
  } finally {
    buttons.forEach(id => document.getElementById(id).disabled = false);
  }
}

// --- Refresh counters from status API ---
async function refreshStatus() {
  const res = await fetch('/api/status/');
  const data = await res.json();
  document.getElementById('activities_count').textContent = data.activities_count;
  document.getElementById('missing_total').textContent = data.missing_total;
  document.getElementById('missing_unloaded').textContent = data.missing_unloaded;
}

// --- Button: load athlete ---
document.getElementById('btn-load-athlete').addEventListener('click', async () => {
  const { ok, data } = await postAction('/api/load-athlete/');
  if (ok) {
    showMessage(`Athlete loaded: ${data.athlete.first_name} ${data.athlete.last_name}`);
  } else {
    showMessage('Error loading athlete: ' + (data.message || 'unknown'), true);
  }
});

// --- Button: detect missing ---
document.getElementById('btn-detect').addEventListener('click', async () => {
  showMessage('Detecting missing activities…');
  const { ok, data } = await postAction('/api/detect-missing/');
  if (ok) {
    showMessage(`Done. New missing added: ${data.new_missing_added} · Total detected: ${data.total_missing_detected}`);
    await refreshStatus();
  } else {
    showMessage('Error detecting: ' + (data.message || 'unknown'), true);
  }
});

// --- Button: load missing (one by one, with progress bar and ETA) ---
document.getElementById('btn-load-missing').addEventListener('click', async () => {
  const statusRes = await fetch('/api/status/');
  const status = await statusRes.json();
  const total = status.missing_unloaded;

  if (total === 0) {
    showMessage('No missing activities to load.');
    return;
  }
  if (!confirm(`Load ${total} missing activities one by one. Continue?`)) return;

  // Mirror the management command logic:
  // 100 or more activities → enforce 9s delay to stay within Strava's 100 req/15 min limit
  const RATE_LIMIT_THRESHOLD = 100;
  const RATE_LIMIT_DELAY_MS = 9000;
  const delayMs = total >= RATE_LIMIT_THRESHOLD ? RATE_LIMIT_DELAY_MS : 0;
  if (delayMs > 0) {
    showMessage(`⚠️ ${total} activities — applying 9s delay between requests to avoid rate limits.`);
  }

  // Show progress bar
  const section = document.getElementById('progress-section');
  const bar = document.getElementById('progress-bar');
  const label = document.getElementById('progress-label');
  const countEl = document.getElementById('progress-count');
  const etaEl = document.getElementById('progress-eta');
  section.classList.remove('hidden');
  bar.style.width = '0%';

  buttons.forEach(id => document.getElementById(id).disabled = true);

  let done = 0;
  let allErrors = [];
  let totalElapsedMs = 0;

  for (let i = 0; i < total; i++) {
    label.textContent = `Loading activity ${i + 1} of ${total}…`;
    countEl.textContent = `${i + 1} / ${total}`;
    const iterStart = Date.now();

    const res = await fetch('/api/load-missing/', {
      method: 'POST',
      headers: {
        'X-CSRFToken': getCsrfToken(),
        'Content-Type': 'application/x-www-form-urlencoded',
      },
      body: 'limit=1',
    });
    const data = await res.json();

    if (res.ok) {
      done += data.processed;
      allErrors = allErrors.concat(data.errors);
      // Update counters live
      const unloadedEl = document.getElementById('missing_unloaded');
      unloadedEl.textContent = Math.max(0, parseInt(unloadedEl.textContent, 10) - data.processed);
      const activitiesEl = document.getElementById('activities_count');
      activitiesEl.textContent = parseInt(activitiesEl.textContent, 10) + data.processed;
    } else {
      allErrors.push({ id: '?', error: data.message || 'unknown' });
    }

    bar.style.width = `${Math.round(((i + 1) / total) * 100)}%`;

    // Wait between requests (skip delay after the last one)
    if (delayMs > 0 && i < total - 1) {
      const remaining = total - i - 1;
      label.textContent = `Waiting… (${remaining} left, rate limit pause)`;
      await new Promise(resolve => setTimeout(resolve, delayMs));
    }

    // ETA: measured after the full iteration (request + delay) for an accurate average
    totalElapsedMs += Date.now() - iterStart;
    const avgMs = totalElapsedMs / (i + 1);
    const remainingAfter = total - (i + 1);
    if (remainingAfter > 0) {
      etaEl.textContent = `ETA: ~${formatSeconds((remainingAfter * avgMs) / 1000)} remaining`;
    } else {
      etaEl.textContent = '';
    }
  }

  buttons.forEach(id => document.getElementById(id).disabled = false);
  label.textContent = 'Done';
  countEl.textContent = '';

  const errSection = document.getElementById('error-section');
  const errList = document.getElementById('error-list');
  if (allErrors.length > 0) {
    errList.innerHTML = allErrors
      .map(e => `<li>Activity ${e.id}: ${e.error}</li>`)
      .join('');
    errSection.classList.remove('hidden');
    showMessage(`Loaded ${done} · ${allErrors.length} errors (see below)`, true);
  } else {
    errSection.classList.add('hidden');
    showMessage(`Loaded ${done} activities — no errors`);
  }

  await refreshStatus();
  setTimeout(() => section.classList.add('hidden'), 3000);
});
