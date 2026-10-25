/* Garage: progressive enhancements only. Every page works without this file. */
(() => {
  'use strict';
  const root = document.documentElement;
  const store = {
    get(key) { try { return localStorage.getItem('garage:' + key); } catch (e) { return null; } },
    set(key, value) { try { localStorage.setItem('garage:' + key, value); } catch (e) { /* optional */ } },
  };

  // Time zone for monthly charts: the server validates it before use.
  try {
    const zone = Intl.DateTimeFormat().resolvedOptions().timeZone;
    const current = (document.cookie.match(/(?:^|; )garage_tz=([^;]*)/) || [])[1];
    // IANA names (letters, digits, / _ - +) are cookie-safe: store them raw.
    if (zone && /^[A-Za-z0-9/_+-]{1,64}$/.test(zone) && current !== zone) {
      document.cookie = `garage_tz=${zone}; Max-Age=31536000; Path=/; SameSite=Lax${location.protocol === 'https:' ? '; Secure' : ''}`;
    }
  } catch (e) { /* default zone on the server */ }

  // Service worker: offline page and cached static assets, never personal pages.
  const sw = root.dataset.sw;
  if (sw && 'serviceWorker' in navigator && (location.protocol === 'https:' || location.hostname === 'localhost' || location.hostname === '127.0.0.1')) {
    window.addEventListener('load', () => { navigator.serviceWorker.register(sw, { scope: root.dataset.swScope || '/garage/' }).catch(() => {}); });
  }

  // Install hint: iPhone needs instructions; Android offers the browser prompt.
  const hint = document.querySelector('[data-install]');
  const standalone = window.matchMedia('(display-mode: standalone)').matches || navigator.standalone === true;
  if (hint && !standalone && store.get('install-dismissed') !== '1') {
    const ios = /iP(hone|ad|od)/.test(navigator.userAgent) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
    const iosText = hint.querySelector('[data-install-ios]'), promptRow = hint.querySelector('[data-install-row]');
    if (ios && iosText) { iosText.hidden = false; hint.hidden = false; }
    let deferred = null;
    window.addEventListener('beforeinstallprompt', event => {
      event.preventDefault();
      deferred = event;
      if (promptRow) promptRow.hidden = false;
      hint.hidden = false;
    });
    hint.addEventListener('click', async event => {
      if (event.target.closest('[data-install-dismiss]')) {
        hint.hidden = true;
        store.set('install-dismissed', '1');
      } else if (event.target.closest('[data-install-prompt]') && deferred) {
        deferred.prompt();
        await deferred.userChoice.catch(() => null);
        deferred = null;
        hint.hidden = true;
      }
    });
    window.addEventListener('appinstalled', () => { hint.hidden = true; });
  }

  // Charts: tap, hover or arrow keys show one month's value.
  document.querySelectorAll('[data-chart]').forEach(wrap => {
    const svg = wrap.querySelector('svg');
    const tip = wrap.querySelector('.tip');
    if (!svg || !tip) return;
    const points = [...svg.querySelectorAll('[data-tip]')];
    const hl = svg.querySelector('.hl');
    const left = Number(svg.dataset.left), band = Number(svg.dataset.band);
    const box = svg.viewBox.baseVal;
    let current = -1;
    const hide = () => {
      current = -1;
      tip.hidden = true;
      points.forEach(p => p.classList.remove('on'));
      if (hl) hl.style.opacity = 0;
    };
    const pick = index => {
      const point = points[index];
      if (!point) { hide(); return; }
      current = index;
      const r = svg.getBoundingClientRect(), w = wrap.getBoundingClientRect();
      const x = Number(point.getAttribute('cx')), y = Number(point.dataset.y || box.height - 30);
      tip.textContent = point.dataset.tip;
      tip.hidden = false;
      const half = tip.offsetWidth / 2 + 2;
      tip.style.left = Math.max(half, Math.min(w.width - half, (r.left - w.left) + x * r.width / box.width)) + 'px';
      tip.style.top = ((r.top - w.top) + y * r.height / box.height) + 'px';
      points.forEach(p => p.classList.toggle('on', p === point && point.dataset.y !== undefined));
      if (hl) { hl.setAttribute('x1', x); hl.setAttribute('x2', x); hl.style.opacity = 1; }
    };
    const at = clientX => {
      const r = svg.getBoundingClientRect();
      return Math.floor(((clientX - r.left) * box.width / r.width - left) / band);
    };
    svg.addEventListener('pointermove', e => pick(at(e.clientX)));
    svg.addEventListener('pointerdown', e => pick(at(e.clientX)));
    svg.addEventListener('pointerleave', e => { if (e.pointerType === 'mouse') hide(); });
    svg.addEventListener('blur', hide);
    svg.addEventListener('keydown', e => {
      if (e.key === 'ArrowRight') { pick(Math.min(points.length - 1, current + 1)); e.preventDefault(); }
      else if (e.key === 'ArrowLeft') { pick(current < 0 ? points.length - 1 : Math.max(0, current - 1)); e.preventDefault(); }
      else if (e.key === 'Escape') hide();
    });
  });

  // Optional date-time pickers: iOS offers no reliable way to empty them.
  document.querySelectorAll('.page input[type="datetime-local"]:not([required])').forEach(input => {
    const clear = document.createElement('button');
    clear.type = 'button';
    clear.className = 'link-btn';
    clear.textContent = 'Vaciar';
    clear.setAttribute('aria-label', 'Vaciar ' + ((input.labels && input.labels[0]) ? input.labels[0].textContent : 'fecha'));
    clear.addEventListener('click', () => { input.value = ''; input.focus(); });
    input.insertAdjacentElement('afterend', clear);
  });

  // Useful life: an orientative suggestion fills the form with one tap.
  document.querySelectorAll('[data-fill]').forEach(button => {
    const form = document.querySelector('form[data-lifespan]');
    if (!form) return;
    button.hidden = false;
    button.addEventListener('click', () => {
      let values = {};
      try { values = JSON.parse(button.dataset.fill); } catch (e) { return; }
      const filled = Object.entries(values).map(([name, value]) => {
        const field = form.elements[name];
        if (field) { field.value = value; field.dispatchEvent(new Event('input', { bubbles: true })); }
        return field;
      }).filter(Boolean);
      if (filled[0]) filled[0].focus();  // the person sees and hears what changed
    });
  });
  // Useful life: the time in days, as it will be stored.
  const lifeForm = document.querySelector('form[data-lifespan]');
  const days = lifeForm && lifeForm.querySelector('[data-days]');
  if (days) {
    const factors = { days: 1, months: 30, years: 365 };
    const show = () => {
      const text = (lifeForm.elements.time_value?.value || '').trim();
      const amount = /^\d+$/.test(text) ? Number(text) : 0;  // the server accepts whole numbers only
      const factor = factors[lifeForm.elements.time_unit?.value] || 1;
      days.textContent = amount > 0 ? `= ${(amount * factor).toLocaleString('es-ES')} días. ` : '';
    };
    lifeForm.addEventListener('input', show);
    lifeForm.addEventListener('change', show);
    show();
  }

  // Ride review: choosing a bike switches gear to that bike's usual set; the
  // effect preview reloads as a server-rendered fragment.
  const form = document.querySelector('form[data-review]');
  if (form) {
    const effects = document.getElementById('effects');
    const previewUrl = form.dataset.preview;
    const switches = [...form.querySelectorAll('input[name="gear"]')];
    let controller = null, timer = null;
    const shown = form.querySelector('input[name="shown_bike"]');
    // Until a bike is chosen, the server's reviewed key (e.g. "none" for an undecided ride) applies.
    const selectedBike = () => (form.querySelector('input[name="bike"]:checked') || {}).value || form.dataset.selected || '';
    const usualFor = (input, bike) => (input.dataset.usual || '').split(' ').filter(Boolean).includes(bike);
    const tags = () => {
      const bike = selectedBike();
      const bikeName = (form.querySelector('input[name="bike"]:checked') || {}).dataset?.name || '';
      switches.forEach(input => {
        const usual = usualFor(input, bike);
        const tag = form.querySelector(`[data-tag="${input.value}"]`);
        if (!tag) return;
        tag.textContent = input.checked && usual ? (bikeName ? `Habitual en ${bikeName}` : 'Habitual')
          : input.checked ? 'Añadido sólo en esta salida' : usual ? 'Quitado sólo en esta salida' : '';
        tag.classList.toggle('ex', input.checked !== usual);
      });
    };
    const refresh = () => {
      clearTimeout(timer);
      timer = setTimeout(async () => {
        if (controller) controller.abort();
        controller = new AbortController();
        const params = new URLSearchParams(new FormData(form));
        params.delete('csrfmiddlewaretoken');
        params.delete('action');
        try {
          const response = await fetch(`${previewUrl}?${params}`, { headers: { 'X-Requested-With': 'fetch' }, signal: controller.signal, credentials: 'same-origin' });
          if (response.redirected) { window.location.reload(); return; }  // session expired: show the login page
          if ((response.ok || response.status === 400) && effects) effects.innerHTML = await response.text();
        } catch (e) { /* keep the previous preview */ }
      }, 120);
    };
    form.addEventListener('change', event => {
      if (event.target.name === 'bike') {
        const bike = selectedBike();
        switches.forEach(input => { input.checked = usualFor(input, bike); });
        if (shown) shown.value = bike;  // the switches now match this bike
      }
      tags();
      refresh();
    });
    const previewButton = form.querySelector('[data-preview-button]');
    if (previewButton) previewButton.hidden = true;
    tags();
  }
})();
