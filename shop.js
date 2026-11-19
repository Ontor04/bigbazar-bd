/* BIG BAZAR BD – storefront behaviour (no frameworks, CSP-safe: no inline scripts) */
(function () {
  'use strict';
  var body = document.body;
  var LANG = body.dataset.lang || 'bn';
  var BN = '০১২৩৪৫৬৭৮৯';

  function digits(s) {
    s = String(s);
    return LANG === 'bn' ? s.replace(/\d/g, function (d) { return BN[d]; }) : s;
  }
  function group(n) { // 1250000 -> 12,50,000
    var s = String(Math.abs(Math.round(n)));
    if (s.length > 3) {
      var head = s.slice(0, -3), tail = s.slice(-3), parts = [];
      while (head.length > 2) { parts.unshift(head.slice(-2)); head = head.slice(0, -2); }
      if (head) parts.unshift(head);
      s = parts.concat([tail]).join(',');
    }
    return (n < 0 ? '-' : '') + s;
  }
  function money(n) { return digits('৳' + group(n)); }
  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }

  /* ---------------------------------------------------------------- toast */
  var toastTimer;
  function toast(msg, ok) {
    var t = document.getElementById('toast');
    if (!t) {
      t = el('div', 'toast');
      t.id = 'toast';
      t.setAttribute('role', 'status');
      t.setAttribute('aria-live', 'polite');
      document.body.appendChild(t);
    }
    t.textContent = msg;
    t.className = 'toast show ' + (ok === false ? 'toast-error' : 'toast-ok');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { t.className = 'toast'; }, 2600);
  }

  /* ------------------------------------------------------- hero slider */
  document.querySelectorAll('[data-hero]').forEach(function (track) {
    var slides = [].slice.call(track.querySelectorAll('.hero-slide'));
    var dots = [].slice.call(track.querySelectorAll('[data-dots] button'));
    if (!slides.length) return;
    var i = 0, timer = null, startX = null;
    function show(n) {
      i = (n + slides.length) % slides.length;
      slides.forEach(function (s, k) { s.classList.toggle('is-active', k === i); });
      dots.forEach(function (d, k) { d.classList.toggle('on', k === i); });
    }
    function play() {
      if (slides.length < 2 || window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
      stop();
      timer = setInterval(function () { show(i + 1); }, 5500);
    }
    function stop() { if (timer) { clearInterval(timer); timer = null; } }
    dots.forEach(function (d, k) { d.addEventListener('click', function () { show(k); play(); }); });
    track.addEventListener('mouseenter', stop);
    track.addEventListener('mouseleave', play);
    track.addEventListener('touchstart', function (e) { startX = e.touches[0].clientX; stop(); }, { passive: true });
    track.addEventListener('touchend', function (e) {
      if (startX !== null) {
        var dx = e.changedTouches[0].clientX - startX;
        if (Math.abs(dx) > 40) show(i + (dx < 0 ? 1 : -1));
        startX = null;
      }
      play();
    });
    show(0);
    play();
  });

  /* -------------------------------------------------- quantity steppers */
  document.querySelectorAll('[data-qty]').forEach(function (box) {
    var input = box.querySelector('input');
    function clamp(v) {
      var min = parseInt(input.min || '1', 10), max = parseInt(input.max || '99', 10);
      v = isNaN(v) ? min : v;
      return Math.max(min, Math.min(max, v));
    }
    box.querySelector('[data-dec]').addEventListener('click', function () { input.value = clamp(parseInt(input.value, 10) - 1); });
    box.querySelector('[data-inc]').addEventListener('click', function () { input.value = clamp(parseInt(input.value, 10) + 1); });
    input.addEventListener('change', function () { input.value = clamp(parseInt(input.value, 10)); });
  });

  /* ----------------------------------------------------- add to cart (ajax) */
  document.addEventListener('submit', function (e) {
    var form = e.target;
    if (!form.matches || !form.matches('[data-cart-add]')) return;
    var sub = e.submitter;
    if (sub && sub.hasAttribute('data-no-ajax')) return;        // "Buy now" -> normal post
    if (!window.fetch) return;
    e.preventDefault();
    var url = (sub && sub.getAttribute('formaction')) || form.getAttribute('action');
    var btn = sub || form.querySelector('button[type=submit]');
    if (btn) btn.disabled = true;
    fetch(url, {
      method: 'POST', body: new FormData(form), credentials: 'same-origin',
      headers: { 'X-Requested-With': 'fetch' }
    }).then(function (r) {
      if (!r.ok) throw new Error('bad');
      return r.json();
    }).then(function (j) {
      toast(j.message, j.ok);
      var badge = document.getElementById('cart-count');
      if (badge && j.ok) {
        badge.textContent = digits(j.count);
        badge.hidden = !j.count;
        badge.classList.remove('bump'); void badge.offsetWidth; badge.classList.add('bump');
      }
    }).catch(function () {
      form.submit();                                           // fall back to a normal page post
    }).then(function () { if (btn) btn.disabled = false; });
  });

  /* --------------------------------------------------------- live search */
  var input = document.getElementById('q'), box = document.getElementById('suggest');
  if (input && box) {
    var url = body.dataset.searchUrl, timer = null, ctrl = null, items = [], cur = -1, lastQ = null;
    var T = function (k) { return body.dataset['t' + k.charAt(0).toUpperCase() + k.slice(1)] || ''; };

    function close() { box.hidden = true; input.setAttribute('aria-expanded', 'false'); cur = -1; }
    function open() { box.hidden = false; input.setAttribute('aria-expanded', 'true'); }
    function title(txt) { return el('div', 'sg-title', txt); }
    function chips(list, label) {
      var wrap = el('div', 'sg-chips');
      list.forEach(function (c) {
        var a = el('a', 'sg-chip', c.name);
        a.href = c.url; a.setAttribute('role', 'option');
        wrap.appendChild(a);
      });
      box.appendChild(title(label)); box.appendChild(wrap);
    }
    function render(data) {
      box.textContent = '';
      var has = data.products.length || data.categories.length || data.brands.length;
      if (!has) {
        var none = el('div', 'sg-none');
        none.appendChild(el('b', null, T('none')));
        none.appendChild(el('span', null, T('noneSub')));
        box.appendChild(none);
        open(); items = []; return;
      }
      if (data.categories.length) chips(data.categories, T('cats'));
      if (data.brands.length) chips(data.brands, T('brands'));
      if (data.products.length) {
        box.appendChild(title(data.popular ? T('popular') : T('prods')));
        data.products.forEach(function (p) {
          var a = el('a', 'sg-item'); a.href = p.url; a.setAttribute('role', 'option');
          var img = el('img'); img.src = p.image; img.alt = ''; img.width = 46; img.height = 46; img.loading = 'lazy';
          var info = el('div');
          info.appendChild(el('b', null, p.name));
          var line = el('small');
          line.appendChild(el('span', 'p', p.price));
          if (p.old) { var s = el('s', null, ' ' + p.old); line.appendChild(s); }
          if (!p.in_stock) line.appendChild(document.createTextNode(' · ' + T('out')));
          info.appendChild(line);
          a.appendChild(img); a.appendChild(info);
          box.appendChild(a);
        });
      }
      if (data.q) {
        var all = el('a', 'sg-all', T('all') + ' “' + data.q + '” →');
        all.href = input.form.action + '?q=' + encodeURIComponent(data.q);
        box.appendChild(all);
      }
      items = [].slice.call(box.querySelectorAll('.sg-item, .sg-chip, .sg-all'));
      cur = -1; open();
    }
    function fetchSuggest() {
      var v = input.value.trim();
      if (v === lastQ) { open(); return; }
      lastQ = v;
      if (ctrl) ctrl.abort();
      ctrl = window.AbortController ? new AbortController() : null;
      fetch(url + '?q=' + encodeURIComponent(v), { signal: ctrl ? ctrl.signal : undefined, credentials: 'same-origin' })
        .then(function (r) { return r.json(); })
        .then(function (d) { if (input.value.trim() === v) render(d); })
        .catch(function () {});
    }
    input.addEventListener('input', function () { clearTimeout(timer); timer = setTimeout(fetchSuggest, 160); });
    input.addEventListener('focus', fetchSuggest);
    input.addEventListener('keydown', function (e) {
      if (box.hidden || !items.length) { if (e.key === 'Escape') close(); return; }
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        e.preventDefault();
        cur = (cur + (e.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length;
        items.forEach(function (n, k) { n.classList.toggle('on', k === cur); });
        items[cur].scrollIntoView({ block: 'nearest' });
      } else if (e.key === 'Enter' && cur >= 0) {
        e.preventDefault(); items[cur].click();
      } else if (e.key === 'Escape') { close(); }
    });
    document.addEventListener('click', function (e) { if (!input.form.contains(e.target)) close(); });
  }

  /* ----------------------------------------------- checkout live totals */
  var co = document.querySelector('[data-checkout]');
  if (co) {
    var sub = +co.dataset.sub, dh = +co.dataset.dhaka, out = +co.dataset.out;
    var free = (LANG === 'bn') ? 'ফ্রি' : 'Free';
    function upd() {
      var sel = co.querySelector('input[name=area]:checked');
      var d = sel && sel.value === 'outside' ? out : dh;
      document.getElementById('sum-delivery').textContent = d ? money(d) : free;
      document.getElementById('sum-total').textContent = money(sub + d);
    }
    co.querySelectorAll('input[name=area]').forEach(function (r) { r.addEventListener('change', upd); });
    co.addEventListener('submit', function () {
      var b = co.querySelector('button[type=submit]');
      if (b) setTimeout(function () { b.disabled = true; }, 0);   // stop double orders
    });
    upd();
  }

  /* ----------------------------------------- copy-to-clipboard buttons */
  document.querySelectorAll('[data-copy]').forEach(function (b) {
    b.addEventListener('click', function () {
      if (navigator.clipboard) navigator.clipboard.writeText(b.dataset.copy).then(function () { toast('✓'); });
    });
  });
})();
