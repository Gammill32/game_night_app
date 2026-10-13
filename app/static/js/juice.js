/* Small feedback touches shared by every page (no libraries).
   Animations live in styles.css; with prefers-reduced-motion they become a plain fade or nothing. */
(function () {
  'use strict';
  var calm = matchMedia('(prefers-reduced-motion: reduce)').matches;
  var GN = (window.GN = { calm: calm });
  function $(sel, root) { return (root || document).querySelector(sel); }
  function $$(sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); }
  function store(key, value) {
    try {
      if (value === undefined) return localStorage.getItem(key);
      localStorage.setItem(key, value);
    } catch (e) { /* private mode / blocked storage */ }
    return null;
  }
  // Restart a CSS animation class on an element.
  function play(el, cls, ms) {
    el.classList.remove(cls); void el.offsetWidth; el.classList.add(cls);
    setTimeout(function () { el.classList.remove(cls); }, ms || 700);
  }
  GN.play = play;

  // ---- Flash messages: close button; successes fade after 4s ----
  function dismiss(el) {
    if (!el) return;
    el.classList.add('gn-out');
    setTimeout(function () { el.remove(); }, calm ? 0 : 300);
  }
  document.addEventListener('click', function (e) {
    var b = e.target.closest('[data-flash-close]');
    if (b) dismiss(b.closest('[data-flash]'));
  });
  $$('[data-flash][data-autohide]').forEach(function (el) {
    setTimeout(function () { if (!el.matches(':hover, :focus-within')) dismiss(el); }, 4000);
  });

  // The server's own message for a refused request (4xx with a short plain-text body), else null.
  GN.serverMessage = function (status, text) {
    text = (text || '').trim();
    return status >= 400 && status < 500 && text && text.length < 300 && text.indexOf('<') === -1 ? text : null;
  };
  // HTMX doesn't swap error responses, so say what went wrong (the tracker handles its own).
  document.addEventListener('htmx:responseError', function (e) {
    if (e.detail.elt.closest && e.detail.elt.closest('[data-tracker]')) return;
    var xhr = e.detail.xhr;
    GN.toast(GN.serverMessage(xhr.status, xhr.responseText) || 'Something went wrong. Try again.');
  });
  GN.toast = function (msg) {
    var t = document.createElement('div');
    t.className = 'gn-toast'; t.setAttribute('role', 'status'); t.textContent = msg;
    document.body.appendChild(t);
    setTimeout(function () { dismiss(t); }, 2600);
  };

  // ---- Badge dialog (markup in _badge_dialog.html) ----
  var dlg = document.getElementById('badgeDialog');
  function f(name) { return dlg.querySelector('[data-f="' + name + '"]'); }
  GN.openBadge = function (d, isNew, more) {
    f('icon').textContent = d.icon; f('name').textContent = d.name;
    f('rule').textContent = d.rule; f('when').textContent = d.when || '';
    var night = f('night'); night.hidden = !d.nightUrl;
    if (d.nightUrl) { night.href = d.nightUrl; night.textContent = d.nightLabel || 'See the game night →'; }
    f('eyebrow').hidden = !isNew;
    var m = f('more'); m.hidden = !more;
    m.textContent = more ? '+' + more + ' more new badge' + (more > 1 ? 's' : '') + ' →' : '';
    dlg.classList.toggle('gn-badge-new', !!isNew);
    dlg.showModal();
  };
  if (dlg) {
    document.addEventListener('click', function (e) {
      var b = e.target.closest('[data-badge-name]');
      if (!b) return;
      var d = b.dataset;
      GN.openBadge({ icon: d.badgeIcon, name: d.badgeName, rule: d.badgeRule, when: d.badgeWhen,
                     nightUrl: d.badgeNightUrl, nightLabel: d.badgeNightLabel });
    });
    dlg.querySelector('[data-close]').addEventListener('click', function () { dlg.close(); });
    dlg.addEventListener('click', function (e) { if (e.target === dlg) dlg.close(); });
  }

  // ---- "New badge!": newest badge ids vs. the last one this browser showed ----
  // Stored as "<person id>:<badge id>". Nothing stored yet (first visit, other person,
  // blocked storage) = remember the current newest silently instead of showing an old badge.
  var feed = document.getElementById('gn-new-badges');
  GN.seenBadge = Infinity;
  if (feed && dlg) {
    var list = JSON.parse(feed.textContent) || [];
    var uid = feed.dataset.uid, top = list.length ? list[0].id : 0;
    var saved = (store('gn_badge_seen') || '').split(':');
    var seen = saved[0] === uid && saved[1] !== undefined ? +saved[1] || 0 : null;
    GN.seenBadge = seen === null ? top : seen;
    if (seen === null || top > seen) store('gn_badge_seen', uid + ':' + top);
    var fresh = seen === null ? [] : list.filter(function (b) { return b.id > seen; });
    if (fresh.length && !$('[data-badge-page]')) {
      var b = fresh[0];
      GN.openBadge({ icon: b.icon, name: b.name, rule: b.rule, when: 'You just earned it.',
                     nightUrl: b.night_url, nightLabel: 'See the game night →' }, true, fresh.length - 1);
    }
  }

  // ---- Confetti burst (CSS-animated <i> pieces, removed after 1.2s) ----
  GN.confetti = function (el) {
    if (calm) return;
    var box = document.createElement('div'), colors = ['#dc2626', '#f59e0b', '#16a34a', '#2563eb', '#db2777'];
    box.className = 'gn-confetti'; box.setAttribute('aria-hidden', 'true');
    for (var i = 0; i < 24; i++) {
      var p = document.createElement('i'), a = Math.random() * 2 * Math.PI, r = 50 + Math.random() * 90;
      p.style.cssText = '--x:' + Math.round(Math.cos(a) * r) + 'px;--y:' + Math.round(Math.sin(a) * r - 50) +
        'px;--r:' + Math.round(Math.random() * 720 - 360) + 'deg;background:' + colors[i % 5];
      box.appendChild(p);
    }
    el.appendChild(box);
    setTimeout(function () { box.remove(); }, 1200);
  };

  GN.countUp = function (el, to, ms) {
    if (calm || !(to > 0)) return;
    var t0 = performance.now();
    (function step(now) {
      var k = Math.min(1, (now - t0) / ms);
      el.textContent = Math.round(to * (1 - Math.pow(1 - k, 3)));
      if (k < 1) requestAnimationFrame(step);
    })(t0);
  };

  // ---- Podium reveal right after "Finalize results" (?finalized=1) ----
  if (/[?&]finalized=1/.test(location.search)) {
    var q = location.search.replace(/([?&])finalized=1(&|$)/, '$1').replace(/[?&]$/, '');
    history.replaceState(history.state, '', location.pathname + q + location.hash);
    var pod = $('[data-podium]');
    if (pod && !calm) {
      pod.classList.add('gn-podium-reveal');
      var first = $('[data-place="1"]', pod);
      if (first) setTimeout(function () { GN.confetti(first); }, 560);
    }
  }

  // ---- Results just saved (#played?saved=<game>): sweep that game's winner row, count up ----
  if (location.hash === '#played') {
    var params = new URLSearchParams(location.search), saved = params.get('saved');
    var games = $$('#played [data-gng]');
    var target = saved ? $('#played [data-gng="' + CSS.escape(saved) + '"]') : games[games.length - 1];
    if (saved) {
      params.delete('saved');
      try { history.replaceState(null, '', location.pathname + (params.toString() ? '?' + params : '') + location.hash); } catch (e) {}
    }
    if (target && !calm) {
      $$('[data-winner-row]', target).forEach(function (r) { r.classList.add('gn-sweep'); });
      $$('[data-score-cell]', target).forEach(function (c) { GN.countUp(c, +c.textContent, 700); });
    }
  }

  // ---- Poll answered (HX-Trigger: pollAnswered): count down "N polls waiting" once per card ----
  document.addEventListener('pollAnswered', function (e) {
    var card = e.target.closest && e.target.closest('[data-needs-answer]');
    var line = $('[data-polls-waiting]');
    if (!card || card.dataset.counted || !line) return;
    card.dataset.counted = '1';
    var label = $('[data-needs-label]', card);
    if (label) { label.textContent = '✓ Answered'; label.className = 'text-xs font-semibold uppercase tracking-wide text-green-700'; }
    var n = Math.max(0, +line.dataset.pollsWaiting - 1);
    line.dataset.pollsWaiting = n;
    line.textContent = n ? n + ' poll' + (n > 1 ? 's' : '') + ' waiting on your answer' : 'All caught up ✓';
    line.className = 'text-sm font-medium ' + (n ? 'text-red-700' : 'text-green-700');
    if (!calm) play(line, 'gn-bump', 200);
  });

  // ---- Background POST for small toggles: <form data-juice="heart|bought"> ----
  // Posts with fetch and X-Background: the server answers 204, or 400 with its message.
  // A network failure falls back to a normal submit.
  document.addEventListener('submit', function (e) {
    var form = e.target, kind = form.dataset && form.dataset.juice;
    if (!kind || e.defaultPrevented || !window.fetch) return;
    e.preventDefault();
    var btn = form.querySelector('button');
    fetch(form.action, {
      method: 'POST', body: new FormData(form), credentials: 'same-origin', headers: { 'X-Background': '1' }
    }).then(function (r) {
      if (!r.ok) {
        r.text().then(function (t) { GN.toast(GN.serverMessage(r.status, t) || 'That didn’t work. Try again.'); });
        return;
      }
      if (kind === 'heart') {
        var on = btn.getAttribute('aria-pressed') !== 'true';
        btn.setAttribute('aria-pressed', on);
        btn.querySelector('[data-label]').textContent = on ? 'On your wishlist' : 'Add to wishlist';
        btn.querySelector('[data-heart]').textContent = on ? '♥' : '♡';
        if (on && !calm) play(btn, 'gn-heart-pop', 600);
      } else if (kind === 'bought') {
        GN.toast('📦 Added to the library');
        var row = form.closest('[data-wish-item]'), done = document.createElement('span');
        // On your own list buying takes the game off it, so the row leaves. On the group list
        // it stays (others may still want it): the button leaves and the row flashes green.
        if (row && form.hasAttribute('data-leaves-list')) {
          row.classList.add('gn-leave');
          setTimeout(function () {
            row.remove();
            if (!$('[data-wish-item]')) location.reload();  // show the empty-list message
          }, calm ? 0 : 300);
          return;
        }
        done.className = 'text-xs font-medium text-green-700'; done.textContent = '📦 In your library';
        form.classList.add('gn-leave');
        setTimeout(function () { form.replaceWith(done); }, calm ? 0 : 300);
        if (row && !calm) play(row, 'gn-sweep', 1400);
      }
    }, function () { form.removeAttribute('data-juice'); form.submit(); });
  });

  // ---- Live tracker: instant taps, HTMX reconciles ----
  // Every request in [data-tracker] queues on that element (hx-sync="... :queue all"), so taps
  // reach the server in order and none are dropped; cells use hx-swap="none" and are never
  // replaced, and only the last response in flight writes the server's number back.
  var tracker = $('[data-tracker]');
  if (tracker) {
    var pending = {};
    var leaders = function () {
      var cards = $$('[data-entity]', tracker), vals = cards.map(function (c) {
        var i = $('input[data-score]', c); return i ? +i.value || 0 : null;
      });
      var max = Math.max.apply(null, vals.filter(function (v) { return v !== null; }));
      var tie = vals.every(function (v) { return v === max; });
      cards.forEach(function (c, i) {
        var lead = !tie && vals[i] === max;
        c.classList.toggle('gn-leader', lead);
        $('[data-crown]', c).hidden = !lead;
      });
    };
    tracker.addEventListener('click', function (e) {
      var b = e.target.closest('[data-step]');
      if (!b) return;
      var cell = b.closest('[data-cell]'), input = $('input', cell), step = +b.dataset.step;
      input.value = (+input.value || 0) + step;
      pending[cell.id] = (pending[cell.id] || 0) + 1;
      if (navigator.vibrate) navigator.vibrate(8);
      if (!calm) {
        play(input, 'gn-bump', 200);
        var chip = document.createElement('span');
        chip.className = 'gn-float ' + (step > 0 ? 'text-green-600' : 'text-red-600');
        chip.textContent = (step > 0 ? '+' : '−') + Math.abs(step);
        cell.appendChild(chip);
        setTimeout(function () { chip.remove(); }, 650);
      }
      leaders();
    });
    tracker.addEventListener('change', function (e) {
      var cell = e.target.closest('[data-cell]');
      if (cell && e.target.type === 'number') { pending[cell.id] = (pending[cell.id] || 0) + 1; leaders(); }
    });
    tracker.addEventListener('htmx:afterRequest', function (e) {
      var cell = e.detail.elt.closest('[data-cell]');
      if (!cell) return;
      var input = $('input[type=number]', cell), xhr = e.detail.xhr;
      if (!e.detail.successful) {
        GN.toast(GN.serverMessage(xhr.status, xhr.responseText) || 'Couldn’t save that. Check your connection.');
        if (e.detail.elt.type === 'checkbox') e.detail.elt.checked = !e.detail.elt.checked;
      }
      if (!input) return;
      pending[cell.id] = Math.max(0, (pending[cell.id] || 1) - 1);
      if (!e.detail.successful) {
        var step = +e.detail.elt.dataset.step;
        if (step) input.value = (+input.value || 0) - step;
      } else if (!pending[cell.id]) {
        var doc = new DOMParser().parseFromString(e.detail.xhr.responseText, 'text/html');
        var fromServer = $('input[type=number]', doc);
        if (fromServer && document.activeElement !== input) input.value = fromServer.value;
      }
      leaders();
    });
    leaders();
  }
})();
