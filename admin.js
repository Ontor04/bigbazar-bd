/* BIG BAZAR BD – admin behaviour (CSP-safe: no inline scripts) */
(function () {
  'use strict';
  var $$ = function (s, r) { return [].slice.call((r || document).querySelectorAll(s)); };

  /* mobile menu */
  $$('[data-menu]').forEach(function (b) {
    b.addEventListener('click', function () { document.body.classList.toggle('menu-open'); });
  });
  $$('.scrim').forEach(function (s) { s.addEventListener('click', function () { document.body.classList.remove('menu-open'); }); });

  /* confirm before destructive actions */
  document.addEventListener('submit', function (e) {
    var f = e.target, msg = f.getAttribute && f.getAttribute('data-confirm');
    if (msg && !window.confirm(msg)) e.preventDefault();
  });

  /* selects that submit their form on change (quick status change, filters) */
  $$('[data-autosubmit]').forEach(function (s) { s.addEventListener('change', function () { s.form.submit(); }); });

  /* image preview for uploads */
  $$('input[type=file][data-preview]').forEach(function (inp) {
    inp.addEventListener('change', function () {
      var img = document.getElementById(inp.dataset.preview), f = inp.files && inp.files[0];
      if (!img || !f) return;
      if (f.size > 8 * 1024 * 1024) { alert('Image is too large (max 8 MB).'); inp.value = ''; return; }
      img.src = URL.createObjectURL(f);
    });
  });

  /* show/hide password */
  $$('[data-toggle-pw]').forEach(function (b) {
    b.addEventListener('click', function () {
      var i = document.getElementById(b.dataset.togglePw);
      i.type = i.type === 'password' ? 'text' : 'password';
      b.textContent = i.type === 'password' ? 'Show' : 'Hide';
    });
  });

  /* print */
  $$('[data-print]').forEach(function (b) { b.addEventListener('click', function () { window.print(); }); });

  /* ------------------------------------------------------ bar chart */
  function group(n) {
    var s = String(Math.abs(Math.round(n)));
    if (s.length > 3) {
      var h = s.slice(0, -3), t = s.slice(-3), p = [];
      while (h.length > 2) { p.unshift(h.slice(-2)); h = h.slice(0, -2); }
      if (h) p.unshift(h);
      s = p.concat([t]).join(',');
    }
    return s;
  }
  function fmt(v, kind) { return kind === 'money' ? '৳' + group(v) : group(v); }
  function short(v, kind) {
    var p = kind === 'money' ? '৳' : '';
    if (v >= 100000) return p + (v / 100000).toFixed(v % 100000 ? 1 : 0) + 'L';
    if (v >= 1000) return p + (v / 1000).toFixed(v % 1000 ? 1 : 0) + 'k';
    return p + v;
  }
  function niceMax(v) {
    if (v <= 0) return 4;
    var e = Math.pow(10, Math.floor(Math.log10(v))), f = v / e;
    return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 4 ? 4 : f <= 5 ? 5 : 10) * e;
  }
  var NS = 'http://www.w3.org/2000/svg';
  function s(tag, attrs, parent) {
    var n = document.createElementNS(NS, tag);
    for (var k in attrs) n.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(n);
    return n;
  }

  function barChart(host) {
    var d;
    try { d = JSON.parse(host.dataset.chart); } catch (e) { return; }
    var labels = d.labels || [], vals = d.values || [], kind = d.fmt || 'int', series = d.name || '';
    if (!labels.length) { host.textContent = 'No data yet'; host.className += ' empty'; return; }
    var W = 700, H = 240, L = 46, R = 8, T = 10, B = 28, iw = W - L - R, ih = H - T - B;
    var max = niceMax(Math.max.apply(null, vals)), n = vals.length, step = iw / n, bw = Math.min(34, step * 0.62);
    var svg = s('svg', { viewBox: '0 0 ' + W + ' ' + H, role: 'img', 'aria-label': d.title || series });
    var grid = s('g', { 'class': 'grid' }, svg);
    for (var i = 0; i <= 4; i++) {
      var y = T + ih - (ih * i / 4);
      s('line', { x1: L, x2: W - R, y1: y, y2: y }, grid);
      var t = s('text', { x: L - 8, y: y + 4, 'text-anchor': 'end' }, svg);
      t.textContent = short(max * i / 4, kind);
    }
    var every = Math.ceil(n / 8);
    var tip = document.createElement('div'); tip.className = 'tip'; tip.hidden = true; host.appendChild(tip);
    vals.forEach(function (v, k) {
      var x = L + step * k + (step - bw) / 2, h = Math.max(v > 0 ? 3 : 0, ih * v / max), y = T + ih - h, r = Math.min(4, h, bw / 2);
      var bar = s('path', {
        'class': 'bar',
        d: h ? 'M' + x + ',' + (T + ih) + 'V' + (y + r) + 'Q' + x + ',' + y + ' ' + (x + r) + ',' + y + 'H' + (x + bw - r) +
          'Q' + (x + bw) + ',' + y + ' ' + (x + bw) + ',' + (y + r) + 'V' + (T + ih) + 'Z' : ''
      }, svg);
      if (k % every === 0 || k === n - 1) {
        var lt = s('text', { x: x + bw / 2, y: H - 8, 'text-anchor': 'middle' }, svg);
        lt.textContent = labels[k];
      }
      var hit = s('rect', { 'class': 'hit', x: L + step * k, y: T, width: step, height: ih + B - 4 }, svg);
      function show() {
        bar.setAttribute('class', 'bar hot');
        tip.hidden = false; tip.textContent = '';
        var b = document.createElement('b'); b.textContent = fmt(v, kind); tip.appendChild(b);
        tip.appendChild(document.createTextNode(labels[k] + (series ? ' · ' + series : '')));
        var pct = (L + step * k + step / 2) / W, hostW = host.clientWidth;
        tip.style.left = Math.max(50, Math.min(hostW - 50, pct * hostW)) + 'px';
        tip.style.top = (y / H * svg.getBoundingClientRect().height) + 'px';
      }
      function hide() { bar.setAttribute('class', 'bar'); tip.hidden = true; }
      hit.addEventListener('mouseenter', show); hit.addEventListener('mouseleave', hide);
      hit.addEventListener('touchstart', show, { passive: true });
    });
    document.addEventListener('touchstart', function (e) { if (!host.contains(e.target)) tip.hidden = true; }, { passive: true });
    host.insertBefore(svg, tip);
    // accessible table alternative
    var tbl = document.createElement('table'); tbl.className = 'sr-only';
    var head = tbl.createTHead().insertRow();
    ['Period', series || 'Value'].forEach(function (h) { var c = document.createElement('th'); c.textContent = h; head.appendChild(c); });
    var tb = tbl.createTBody();
    labels.forEach(function (lb, k) { var r = tb.insertRow(); r.insertCell().textContent = lb; r.insertCell().textContent = fmt(vals[k], kind); });
    host.appendChild(tbl);
  }
  $$('[data-chart]').forEach(barChart);
})();
