
function esc(s) {
  if (s === null || s === undefined) return "";
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

(function wrapFetchForCSRF() {
  const _fetch = window.fetch.bind(window);
  const UNSAFE = new Set(["POST", "PUT", "PATCH", "DELETE"]);

  function readCookie(name) {
    const parts = document.cookie ? document.cookie.split("; ") : [];
    for (const p of parts) {
      const eq = p.indexOf("=");
      if (eq > 0 && p.slice(0, eq) === name) {
        return decodeURIComponent(p.slice(eq + 1));
      }
    }
    return "";
  }

  window.fetch = function (input, init) {
    init = init || {};
    const method = (init.method || (typeof input === "string" ? "GET" : (input.method || "GET"))).toUpperCase();
    const url = typeof input === "string" ? input : (input.url || "");
    if (UNSAFE.has(method) && url.startsWith("/api/")) {
      const token = readCookie("csrf_token");
      if (token) {
        init.headers = new Headers(init.headers || {});
        if (!init.headers.has("X-CSRF-Token")) init.headers.set("X-CSRF-Token", token);
      }
    }
    return _fetch(input, init);
  };
})();

function buildPageWindow(current, total, maxNeighbors = 1) {
  if (total <= 1) return [1];
  const pages = new Set([1, total, current]);
  for (let i = 1; i <= maxNeighbors; i++) {
    if (current - i >= 1) pages.add(current - i);
    if (current + i <= total) pages.add(current + i);
  }
  const sorted = [...pages].sort((a, b) => a - b);
  const out = [];
  for (let i = 0; i < sorted.length; i++) {
    if (i > 0 && sorted[i] - sorted[i - 1] > 1) out.push('\u2026');
    out.push(sorted[i]);
  }
  return out;
}

const RECEIPT_KINDS = {
  RECEIPT:  { title: 'STOCK IN RECEIPT',   label: 'Stock In',   badge: 'b-success', qty: 'Qty Received',
              sigLeft: 'Received / Recorded by', sigRight: 'Delivered by (Supplier)' },
  ISSUANCE: { title: 'STOCK OUT RECEIPT',  label: 'Stock Out',  badge: 'b-danger',  qty: 'Qty Issued',
              sigLeft: 'Released by',            sigRight: 'Received by (Client / Authorized Recipient)' },
  RETURN:   { title: 'BACK ORDER RECEIPT', label: 'Back Order', badge: 'b-warning', qty: 'Qty Returned',
              sigLeft: 'Recorded / Inspected by', sigRight: 'Received by' },
};
window.RECEIPT_KINDS = RECEIPT_KINDS;

const _rcEsc  = (s) => (typeof escapeHTML === 'function' ? escapeHTML(s) : esc(s));
const _rcNum  = (n) => (typeof NUM === 'function' ? NUM(n) : String(n));
const _rcPeso = (n) => (typeof PESO === 'function' ? PESO(n) : String(n));
const movNo   = (id, kind) => (id || id === 0) && String(id) !== ''
  ? `${kind === 'RETURN' ? 'BKO' : 'MOV'}-${String(id).padStart(4, '0')}` : '';

window.receiptNow = () => {
  const d = new Date();
  return d.toLocaleDateString('en-PH', { year: 'numeric', month: 'long', day: 'numeric' })
    + ' · ' + d.toLocaleTimeString('en-PH', { hour: 'numeric', minute: '2-digit' });
};

window.buildReceiptHTML = function (kind, items, info = {}) {
  const k = RECEIPT_KINDS[kind] || RECEIPT_KINDS.RECEIPT;
  const rows = items || [];
  const ids = rows.map(r => Number(r.movementId)).filter(n => Number.isFinite(n) && n > 0).sort((a, b) => a - b);
  const receiptNo = !ids.length ? 'Pending (assigned on save)'
    : ids.length === 1 ? movNo(ids[0], kind) : `${movNo(ids[0], kind)} – ${movNo(ids[ids.length - 1], kind)}`;
  const hasPrice = rows.some(r => Number(r.price) > 0);
  const multi = rows.length > 1;
  const units = [...new Set(rows.map(r => r.unit))];
  const totalQty = rows.reduce((s, r) => s + (Number(r.qty) || 0), 0);
  const totalAmt = rows.reduce((s, r) => s + (Number(r.qty) || 0) * (Number(r.price) || 0), 0);
  const logo = document.querySelector('.sidebar__brand img, img.logo-mark')?.getAttribute('src') || 'static/assets/img/logo.svg';

  const fields = (info.fields || []).filter(([, v]) => v !== undefined && v !== null && String(v).trim() !== '');
  const fieldHTML = fields.map(([label, value]) =>
    `<div class="col-6 col-md-4 mb-2"><div class="text-muted-2">${_rcEsc(label)}</div><div class="fw-medium">${_rcEsc(value)}</div></div>`).join('');

  const head = `<tr><th style="width:36px">#</th>${multi ? '<th style="white-space:nowrap">Ref No.</th>' : ''}<th>Material ID</th><th>Article / Description</th><th>Category</th>
      <th class="text-end">${k.qty}</th><th>Unit</th>${hasPrice ? '<th class="text-end">Unit Price</th><th class="text-end">Amount</th>' : ''}</tr>`;
  const body = rows.map((r, i) => `<tr>
      <td class="text-muted-2">${i + 1}</td>${multi ? `<td class="text-muted-2" style="white-space:nowrap">${movNo(r.movementId, kind) || '—'}</td>` : ''}
      <td class="fw-id">${_rcEsc(r.id || '—')}</td><td class="fw-medium">${_rcEsc(r.name || '—')}</td><td>${_rcEsc(r.cat || '—')}</td>
      <td class="text-end">${_rcNum(r.qty)}</td><td>${_rcEsc(r.unit || '')}</td>
      ${hasPrice ? `<td class="text-end">${Number(r.price) > 0 ? _rcPeso(r.price) : '—'}</td><td class="text-end">${Number(r.price) > 0 ? _rcPeso((Number(r.qty) || 0) * Number(r.price)) : '—'}</td>` : ''}
    </tr>`).join('');
  const span = 4 + (multi ? 1 : 0);
  const foot = `<tr class="fw-bold"><td colspan="${span}" class="text-end">Total${multi ? ` (${rows.length} items)` : ''}</td>
      <td class="text-end">${units.length === 1 ? _rcNum(totalQty) : '—'}</td><td>${units.length === 1 ? _rcEsc(units[0] || '') : 'mixed units'}</td>
      ${hasPrice ? `<td></td><td class="text-end">${_rcPeso(totalAmt)}</td>` : ''}</tr>`;

  const sig = (label, name) => `<div class="col-6"><div style="border-bottom:1px solid #999;height:34px" class="d-flex align-items-end justify-content-center pb-1 fw-medium">${_rcEsc(name || '')}</div>
      <div class="small text-muted-2 text-center mt-1">${_rcEsc(label)}</div></div>`;

  const wxLine = (wx, title, label) => {
    if (!wx || (wx.temp == null && wx.rain == null)) return '';
    const rainy = wx.rain != null && Number(wx.rain) >= 1;
    const icon = rainy ? 'bi-cloud-rain-fill' : 'bi-sun-fill';
    const parts = [];
    if (wx.temp != null) parts.push(`${Number(wx.temp).toFixed(1)}\u00b0C`);
    if (wx.rain != null) parts.push(rainy ? `${Number(wx.rain).toFixed(1)} mm rain` : 'No rain');
    if (wx.wind != null) parts.push(`${Number(wx.wind).toFixed(0)} km/h wind`);
    return `<div class="small mt-1" title="${_rcEsc(title)}">
      <i class="bi ${icon} me-1" style="color:${rainy ? '#2b6cb0' : '#e6a817'}"></i>${label ? `<span class="text-muted-2">${_rcEsc(label)}: </span>` : ''}<span class="fw-medium">${_rcEsc(parts.join(' \u00b7 '))}</span></div>`;
  };
  let weatherHTML = wxLine(info.weather, 'Weather in Lipa City on the day of this Stock Out', info.delivery ? 'Order day' : '');

  let deliveryHTML = '';
  const dv = info.delivery;
  if (dv) {
    if (dv.status === 'Delivered') {
      deliveryHTML = `<div class="small mt-2"><i class="bi bi-truck me-1 text-success"></i><span class="fw-medium text-success">Delivered</span>
          ${dv.at ? `<span class="text-muted-2"> \u00b7 ${_rcEsc(dv.at)}</span>` : ''}</div>
         ${wxLine(dv.weather, 'Weather in Lipa City on the delivery day', 'Delivery day')}`;
    } else if (dv.status === 'Returned') {
      deliveryHTML = `<div class="small mt-2"><i class="bi bi-arrow-counterclockwise me-1"></i><span class="fw-medium">Returned to inventory</span>
          ${dv.at ? `<span class="text-muted-2"> \u00b7 ${_rcEsc(dv.at)}</span>` : ''}</div>
         ${dv.reason ? `<div class="small"><span class="text-muted-2">Delivery failed: </span><span class="fw-medium">${_rcEsc(dv.reason)}</span></div>` : ''}`;
    } else if (dv.status === 'Failed') {
      deliveryHTML = `<div class="small mt-2"><i class="bi bi-x-octagon-fill me-1 text-danger"></i><span class="fw-medium text-danger">Delivery failed \u00b7 on standby</span>
          ${dv.at ? `<span class="text-muted-2"> \u00b7 ${_rcEsc(dv.at)}</span>` : ''}</div>
         ${dv.reason ? `<div class="small"><span class="text-muted-2">Reason: </span><span class="fw-medium">${_rcEsc(dv.reason)}</span></div>` : ''}
         ${wxLine(dv.weather, 'Weather in Lipa City on the day the delivery failed', 'Delivery day')}`;
    } else {
      deliveryHTML = `<div class="small mt-2"><i class="bi bi-hourglass-split me-1 text-warning"></i><span class="fw-medium text-warning-emphasis">Delivery pending</span></div>`;
    }
  }

  return `
    <div class="receipt-doc">
      <div class="d-flex justify-content-between align-items-start mb-3">
        <div class="d-flex gap-2 align-items-center"><img src="${_rcEsc(logo)}" alt="" style="width:42px">
          <div><div class="fw-bold" style="color:var(--primary)">PARABELLUM STEEL &amp; IRON WORKS</div>
          <div class="small text-muted-2">Inventory &amp; Service Optimization System</div></div></div>
        <div class="text-end"><div class="h5 mb-0">${k.title}</div>
          <div class="small text-muted-2">Receipt No. <span class="fw-medium text-dark">${_rcEsc(receiptNo)}</span></div>
          <div class="small text-muted-2">${_rcEsc(info.when || '')}</div>
          ${weatherHTML}${deliveryHTML}</div>
      </div><hr class="mt-0">
      <div class="row small mb-2">${fieldHTML}</div>
      <div class="table-responsive"><table class="table table-soft table-sm mb-2" style="font-size:.86rem"><thead>${head}</thead><tbody>${body}</tbody><tfoot>${foot}</tfoot></table></div>
      ${info.note ? `<div class="small text-muted-2 mb-2"><i class="bi bi-info-circle me-1"></i>${_rcEsc(info.note)}</div>` : ''}
      <div class="row g-4 mt-2 small">${sig(k.sigLeft, info.recordedBy)}${sig(k.sigRight, info.counterparty)}</div>
      <div class="d-flex justify-content-between align-items-center mt-3">
        <span class="badge ${k.badge}">${k.label}</span>
        <span class="small text-muted-2">System-generated receipt · Parabellum ISOS</span>
      </div>
    </div>`;
};

window.showTransactionReceipt = function (kind, items, info = {}) {
  let el = document.getElementById('moveSlipModal');
  if (!el) {
    document.body.insertAdjacentHTML('beforeend', `
      <div class="modal fade" id="moveSlipModal" tabindex="-1"><div class="modal-dialog modal-xl modal-dialog-centered modal-dialog-scrollable"><div class="modal-content">
        <div class="modal-header"><h5 class="modal-title"><i class="bi bi-receipt me-2" style="color:var(--primary)"></i><span id="moveSlipTitle">Receipt</span></h5><button class="btn-close" data-bs-dismiss="modal"></button></div>
        <div class="modal-body" id="moveSlipBody"></div>
        <div class="modal-footer"><button class="btn btn-light-2" data-bs-dismiss="modal">Close</button><button class="btn btn-primary" data-print-receipt><i class="bi bi-printer me-1"></i>Print Receipt</button></div>
      </div></div></div>`);
    el = document.getElementById('moveSlipModal');
    el.querySelector('[data-print-receipt]').addEventListener('click', () => window.print());
  }
  const k = RECEIPT_KINDS[kind] || RECEIPT_KINDS.RECEIPT;
  const title = el.querySelector('#moveSlipTitle') || el.querySelector('.modal-title');
  if (title) title.innerHTML = `<i class="bi bi-receipt me-2" style="color:var(--primary)"></i>${k.label} Receipt`;
  el.querySelector('#moveSlipBody').innerHTML = window.buildReceiptHTML(kind, items, info);
  const open = () => bootstrap.Modal.getOrCreateInstance(el).show();
  const closing = [...document.querySelectorAll('.modal.show, .modal.showing')].find(m => m !== el);
  if (closing) closing.addEventListener('hidden.bs.modal', open, { once: true });
  else open();
};

window.findNewMovement = function (type, code, beforeIds, preferId) {
  const all = window.ALL_MOVEMENTS || [];
  if (preferId) { const hit = all.find(m => String(m.movementId) === String(preferId)); if (hit) return hit; }
  return all.filter(m => m.type === type && m.id === code && !(beforeIds && beforeIds.has(m.movementId)))
            .sort((a, b) => b.movementId - a.movementId)[0] || null;
};

document.addEventListener('DOMContentLoaded', () => {

  if (document.getElementById('dashKpiProjects')) {
    (async () => {
      try {
        const res = await fetch('/api/dashboard');
        const json = await res.json();
        if (!json.ok) throw new Error(json.error || 'Dashboard request failed');
        const d = json.data;
        const set = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v; };

        set('dashKpiProjects', d.kpi.activeProjects);
        set('dashKpiTxns',     d.kpi.monthlyTxns);
        set('dashKpiTxnsLabel', d.kpi.monthlyLabel || 'No transactions yet');
        set('dashKpiItems',    d.kpi.totalItems);
        set('dashKpiLow',      d.kpi.lowStock);

        // Recent transactions table
        const tb = document.getElementById('dashTxnBody');
        if (tb && d.recent) {
          tb.innerHTML = '';
          d.recent.forEach(t => {
            const badge = (typeof payBadge === 'function') ? payBadge(t.pay) : t.pay;
            const money = (typeof PESO === 'function') ? PESO(t.total) : t.total;
            tb.insertAdjacentHTML('beforeend', `<tr>
              <td class="fw-id">${t.inv}</td><td>${t.cust}</td>
              <td class="fw-medium">${money}</td><td>${badge}</td>
              <td class="text-muted-2">${t.date}</td></tr>`);
          });
          if (!d.recent.length) {
            tb.innerHTML = '<tr><td colspan="5" class="text-center text-muted-2 py-3">No recent transactions.</td></tr>';
          }
        }

        const banner = document.getElementById('fcAlertBanner');
        if (banner) {
          if (d.alert) {
            const a = d.alert;
            const setT = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v; };
            setT('fcAlertMaterial', a.material);
            setT('fcAlertMonth', a.month || 'next month');
            setT('fcAlertPredicted', `${NUM(a.predicted)} ${a.unit}`);
            setT('fcAlertTrend', a.pct === 0 ? 'no change' : `${a.pct > 0 ? '\u25b2' : '\u25bc'} ${Math.abs(a.pct)}%`);
            setT('fcAlertStock', `${NUM(a.stock)} ${a.unit}`);
            setT('fcAlertQty', `${NUM(a.reorder)} ${a.unit}`);
            banner.style.display = '';
          } else {
            banner.style.display = 'none';
          }
        }

        if (typeof window.setUsageData === 'function') {
          const split = (rows) => [(rows || []).map(u => u.label), (rows || []).map(u => u.qty)];
          window.setUsageData('monthly', ...split(d.usage));
          window.setUsageData('weekly',  ...split(d.usageWeekly));
          window.setUsageData('daily',   ...split(d.usageDaily));
        }
      } catch (err) {
        console.error('Dashboard load failed:', err);
        const tbFail = document.getElementById('dashTxnBody');
        if (tbFail) tbFail.innerHTML = '<tr><td colspan="5" class="text-center text-muted-2 py-3">Could not load recent transactions.</td></tr>';
        showToast('Could not load dashboard figures from the database', 'error', 'bi-exclamation-triangle');
      }
    })();
  }

  (async () => {
    try {
      const res = await fetch('/api/me');
      const json = await res.json();
      if (!json.ok) throw new Error('not signed in');
      CURRENT_USER = json.data;
      if (!location.pathname.startsWith('/login') && !document.getElementById('chatScript')) {
        const cs = document.createElement('script');
        cs.id = 'chatScript'; cs.src = '/static/js/chat.js';
        document.body.appendChild(cs);
      }
    } catch {
      if (!location.pathname.startsWith('/login') && location.pathname !== '/') {
        window.location.href = '/login';
      }
    }
  })();

  document.querySelectorAll('a[href="/login"]').forEach(a => {
    if (!/sign out/i.test(a.textContent)) return;
    a.addEventListener('click', (e) => {
      e.preventDefault();
      try { sessionStorage.removeItem('parabellum.stockAlertsShown'); sessionStorage.removeItem('parabellum.lowStockModalShown'); sessionStorage.removeItem('parabellum.outStockModalShown'); } catch (_) {}
      fetch('/api/logout', { method: 'POST' }).finally(() => {
        window.location.href = '/login';
      });
    });
  });

  window.updateInventoryBadge = () => {
    if (typeof INVENTORY === 'undefined' || INVENTORY.length === 0) return;
    const oos = INVENTORY.filter(i => i.status === 'Out of Stock').length;
    document.querySelectorAll('.sidebar__nav a[href="/inventory"] .badge').forEach(b => {
      b.textContent = oos;
      b.classList.toggle('d-none', oos === 0);
    });
  };

  /* Notifications bell */
  window.refreshNotifications = async () => {
    const list = document.querySelector('[data-notif-list]');
    if (!list) return;
    const dot   = document.querySelector('[data-notif-dot]');
    const count = document.querySelector('[data-notif-count]');
    try {
      const res  = await fetch('/api/notifications');
      const json = await res.json();
      if (!json.ok) throw new Error(json.error || 'Notifications request failed');
      const items = json.data.items || [];
      list.innerHTML = items.length
        ? items.map(n => `
            <div class="dp-item">
              <div class="dp-ic ${escapeHTML(n.tone)}"><i class="bi ${escapeHTML(n.ic)}"></i></div>
              <div><div class="dp-title text-dark">${escapeHTML(n.title)}</div><div class="dp-time">${escapeHTML(n.time)}</div></div>
            </div>`).join('')
        : '<div class="text-center text-muted-2 small py-3">Nothing needs your attention right now.</div>';
      if (count) count.textContent = items.length;
      if (dot) dot.classList.toggle('d-none', items.length === 0);
    } catch (err) {
      console.error('Notifications load failed:', err);
      list.innerHTML = '<div class="text-center text-danger small py-3">Could not load notifications.</div>';
    }
  };
  window.refreshNotifications();

  /* Sidebar toggle */
  const sidebar   = document.querySelector('.sidebar');
  const hamburger = document.querySelector('.hamburger');
  const backdrop  = document.querySelector('.backdrop');
  const openNav  = () => { sidebar?.classList.add('open');  backdrop?.classList.add('show'); };
  const closeNav = () => { sidebar?.classList.remove('open'); backdrop?.classList.remove('show'); };
  hamburger?.addEventListener('click', () => {
    const root = document.documentElement;
    if (window.innerWidth >= 992 && root.classList.contains('sb-collapsible')) {
      const mini = root.classList.toggle('sb-mini');
      try { localStorage.setItem('sbMini', mini ? '1' : '0'); } catch (_) {}
      return;
    }
    sidebar?.classList.contains('open') ? closeNav() : openNav();
  });
  backdrop?.addEventListener('click', closeNav);
  document.querySelectorAll('.sidebar__nav .nav-link').forEach(a => {
    a.addEventListener('click', () => { if (window.innerWidth < 992) closeNav(); });
  });

  /* Live clock */
  const clockEl = document.getElementById('liveClock');
  const dateEl  = document.getElementById('liveDate');
  function tick() {
    const now = new Date();
    if (clockEl) clockEl.textContent = now.toLocaleTimeString('en-PH', { hour:'2-digit', minute:'2-digit', second:'2-digit' });
    if (dateEl)  dateEl.textContent  = now.toLocaleDateString('en-PH', { weekday:'long', year:'numeric', month:'long', day:'numeric' });
  }
  if (clockEl || dateEl) { tick(); setInterval(tick, 1000); }

  /* Tooltips */
  document.querySelectorAll('[data-bs-toggle="tooltip"]').forEach(el => new bootstrap.Tooltip(el));

  window.showToast = function (msg, tone = 'primary', icon = 'bi-check-circle-fill', action = null) {
    let host = document.getElementById('toastHost');
    if (!host) {
      host = document.createElement('div');
      host.id = 'toastHost';
      host.className = 'toast-container position-fixed bottom-0 end-0 p-3';
      host.style.zIndex = '1090';
      document.body.appendChild(host);
    }
    const colors = { primary:'#b11217', success:'#1f9d55', warning:'#e6a817', danger:'#c0392b', info:'#2b6cb0' };
    const el = document.createElement('div');
    el.className = 'toast align-items-center border-0 show';
    el.style.cssText = `background:#fff;border-left:4px solid ${colors[tone]||colors.primary};box-shadow:0 8px 24px rgba(0,0,0,.14);border-radius:10px;min-width:280px;`;
    const actionBtnHtml = action
      ? `<button type="button" class="btn btn-sm btn-primary ms-3" id="toastActionBtn">${esc(action.label)}</button>` : '';
    el.innerHTML = `<div class="d-flex">
        <div class="toast-body d-flex align-items-center gap-2" style="color:#1f2329;font-weight:500;">
          <i class="bi ${icon}" style="color:${colors[tone]||colors.primary};font-size:1.1rem;"></i> ${msg}${actionBtnHtml}
        </div>
        <button type="button" class="btn-close me-2 m-auto" data-bs-dismiss="toast"></button>
      </div>`;
    host.appendChild(el);
    const t = new bootstrap.Toast(el, { delay: action ? 6000 : 3200 });
    t.show();
    if (action) {
      el.querySelector('#toastActionBtn')?.addEventListener('click', () => {
        action.onClick();
        t.hide();
      });
    }
    el.addEventListener('hidden.bs.toast', () => el.remove());
  };

  /* Generic table search */
  document.querySelectorAll('[data-table-search]').forEach(input => {
    const target = document.querySelector(input.getAttribute('data-table-search'));
    input.addEventListener('input', () => {
      const q = input.value.toLowerCase().trim();
      target?.querySelectorAll('tbody tr').forEach(row => {
        row.style.display = row.textContent.toLowerCase().includes(q) ? '' : 'none';
      });
    });
  });

  document.querySelectorAll('[data-filter-target]').forEach(sel => {
    const target = document.querySelector(sel.getAttribute('data-filter-target'));
    const col = parseInt(sel.getAttribute('data-filter-col'), 10);
    sel.addEventListener('change', () => {
      const v = sel.value.toLowerCase();
      target?.querySelectorAll('tbody tr').forEach(row => {
        const cell = row.children[col];
        const text = (cell?.textContent || '').toLowerCase();
        row.style.display = (!v || text.includes(v)) ? '' : 'none';
      });
    });
  });

  /* Shared delete-confirmation dialog */
  window.confirmAction = function (title, message, label, onConfirm) {
    let m = document.getElementById('sharedActionModal');
    if (!m) {
      document.body.insertAdjacentHTML('beforeend', `
        <div class="modal fade" id="sharedActionModal" tabindex="-1"><div class="modal-dialog modal-dialog-centered"><div class="modal-content">
          <div class="modal-header"><h5 class="modal-title" id="sharedActionTitle"></h5><button class="btn-close" data-bs-dismiss="modal"></button></div>
          <div class="modal-body"><p class="mb-0" id="sharedActionMsg"></p></div>
          <div class="modal-footer"><button type="button" class="btn btn-light-2" data-bs-dismiss="modal">Cancel</button>
            <button type="button" class="btn btn-primary" id="sharedActionBtn"></button></div>
        </div></div></div>`);
      m = document.getElementById('sharedActionModal');
    }
    document.getElementById('sharedActionTitle').textContent = title;
    document.getElementById('sharedActionMsg').textContent = message;
    const btn = document.getElementById('sharedActionBtn');
    const clone = btn.cloneNode(true);
    clone.textContent = label;
    btn.replaceWith(clone);
    const modal = bootstrap.Modal.getOrCreateInstance(m);
    clone.addEventListener('click', () => { modal.hide(); onConfirm(); });
    modal.show();
  };

  window.confirmDelete = function (message, onConfirm, opts = {}) {
    let m = document.getElementById('sharedConfirmModal');
    if (!m) {
      document.body.insertAdjacentHTML('beforeend', `
        <div class="modal fade" id="sharedConfirmModal" tabindex="-1"><div class="modal-dialog modal-dialog-centered modal-sm"><div class="modal-content">
          <div class="modal-header"><h5 class="modal-title"><i class="bi bi-exclamation-triangle me-2" style="color:var(--primary)"></i><span id="sharedConfirmTitle">Confirm Delete</span></h5>
            <button class="btn-close" data-bs-dismiss="modal"></button></div>
          <div class="modal-body"><p class="mb-0" id="sharedConfirmMsg">Delete this record? This cannot be undone.</p></div>
          <div class="modal-footer"><button type="button" class="btn btn-light-2" data-bs-dismiss="modal">Cancel</button>
            <button type="button" class="btn btn-primary" id="sharedConfirmBtn">Delete</button></div>
        </div></div></div>`);
      m = document.getElementById('sharedConfirmModal');
    }
    document.getElementById('sharedConfirmMsg').textContent = message;
    document.getElementById('sharedConfirmTitle').textContent = opts.title || 'Confirm Delete';
    const btn = document.getElementById('sharedConfirmBtn');
    const clone = btn.cloneNode(true);
    clone.textContent = opts.button || 'Delete';
    btn.replaceWith(clone);
    const modal = bootstrap.Modal.getOrCreateInstance(m);
    clone.addEventListener('click', () => { modal.hide(); onConfirm(); });
    modal.show();
  };

  document.querySelectorAll('.needs-validation').forEach(form => {
    form.addEventListener('submit', (e) => {
      e.preventDefault();
      if (!form.checkValidity()) {
        e.stopPropagation();
        form.classList.add('was-validated');
        return;
      }
      const entity = form.getAttribute('data-entity');
      if (entity) {
        const data = Object.fromEntries(new FormData(form));
        const editId = form.getAttribute('data-edit-id') || null;
        const ev = new CustomEvent('entity:submit', { detail:{ entity, data, editId, form } });
        document.dispatchEvent(ev);
        form.removeAttribute('data-edit-id');
      }
      const msg = form.getAttribute('data-success-msg') || 'Saved successfully';
      showToast(msg, 'success');
      const modalEl = form.closest('.modal');
      if (modalEl) bootstrap.Modal.getInstance(modalEl)?.hide();
      if (form.hasAttribute('data-reset')) { form.reset(); form.classList.remove('was-validated'); }
      else form.classList.add('was-validated');
    });
  });

  if (document.getElementById('stockInBody') && typeof INVENTORY !== 'undefined') {

    INVENTORY.length = 0;

    const refreshInventory = async () => {
      try {
        const [invRes, moveRes, boRes, sumRes] = await Promise.all([
          fetch('/api/inventory'),
          fetch('/api/inventory/movements'),
          fetch('/api/inventory/backorders'),
          fetch('/api/inventory/summary'),
        ]);
        const invJson  = await invRes.json();
        const moveJson = await moveRes.json();
        const boJson   = await boRes.json();
        const sumJson  = await sumRes.json();
        if (!invJson.ok || !moveJson.ok || !boJson.ok || !sumJson.ok) {
          console.error('Failed to load real inventory from the server:',
                        invJson.error || moveJson.error || boJson.error || sumJson.error || invRes.status);
          showToast('Could not load inventory from the database — showing may be outdated', 'error', 'bi-exclamation-triangle');
          return;
        }
        INVENTORY.length = 0;
        invJson.data.forEach(r => INVENTORY.push(r));
        if (typeof window.updateInventoryBadge === 'function') window.updateInventoryBadge();
        window.ALL_MOVEMENTS = moveJson.data;
        window.ALL_BACKORDERS = boJson.data;
        window.STOCK_SUMMARY = sumJson.data;
        if (typeof window.renderInventory === 'function') window.renderInventory();
      } catch (err) {
        console.error('refreshInventory failed:', err);
        showToast('Could not connect to the server to load inventory', 'error', 'bi-exclamation-triangle');
      }
    };

    const wire = (selector, url, buildBody, opts = {}) => {
      const form = document.querySelector(selector);
      if (!form) return;
      form.addEventListener('submit', async (e) => {
        if (!form.checkValidity()) return;
        e.preventDefault();
        e.stopImmediatePropagation();

        const data = Object.fromEntries(new FormData(form));
        const body = buildBody(data, form);
        const targetUrl = typeof url === 'function' ? url(data, form) : url;
        const beforeIds  = new Set((window.ALL_MOVEMENTS || []).map(m => m.movementId));
        const itemBefore = data.itemId && typeof inventoryStore !== 'undefined' ? { ...(inventoryStore.find(data.itemId) || {}) } : null;
        try {
          const res = await fetch(targetUrl, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
          });
          const json = await res.json();
          if (!json.ok) throw new Error(json.error);

          await refreshInventory();
          const modalEl = form.closest('.modal');
          if (modalEl) bootstrap.Modal.getInstance(modalEl)?.hide();
          form.reset(); form.classList.remove('was-validated');
          form.removeAttribute('data-edit-id');
          const msg = typeof opts.successMsg === 'function' ? opts.successMsg(data, form) : (opts.successMsg || 'Saved');
          const action = typeof opts.successAction === 'function' ? opts.successAction(data, form) : null;
          showToast(msg, 'success', undefined, action);
          if (typeof opts.onSuccess === 'function') {
            try { opts.onSuccess(data, form, { json, beforeIds, itemBefore }); }
            catch (hookErr) { console.error('Receipt could not be shown:', hookErr); }
          }
        } catch (err) {
          showToast(err.message, 'error', 'bi-exclamation-triangle');
        }
      }, true);
    };

    wire('#stockInModal form',
      (d) => d.itemId ? '/api/inventory/stock-in' : '/api/inventory/save',
      (d) => (d.itemId
        ? { itemId: d.itemId, qty: d.qty, remarks: d.remarks }
        : { name: d.name, cat: d.cat, sup: d.sup, unit: d.unit, qty: d.qty, price: d.price, reorder: 0, loc: d.loc }),
      { successMsg: (d) => d.itemId ? 'Stock added to inventory' : 'New item added to inventory and stocked',
        onSuccess: (d, form, { json, beforeIds, itemBefore }) => {
          const code = d.itemId || json.code || json.id || '';
          const mv   = window.findNewMovement('RECEIPT', code, beforeIds, json.movementId);
          const item = (code && inventoryStore.find(code)) || itemBefore || {};
          const user = (typeof CURRENT_USER !== 'undefined' && CURRENT_USER.name) || mv?.recordedBy || '';
          window.showTransactionReceipt('RECEIPT', [{
            movementId: mv?.movementId, id: code, name: item.name || d.name, cat: item.cat || d.cat,
            qty: Number(d.qty), unit: item.unit || d.unit, price: Number(item.price ?? d.price) || 0,
          }], {
            when: window.receiptNow(),
            fields: [['Supplier', item.sup || d.sup], ['Warehouse / Location', item.loc || d.loc],
                     ['Remarks / Reference', d.remarks], ['Recorded by', user],
                     ['Transaction', d.itemId ? 'Stock received' : 'New item registered + first stock']],
            recordedBy: user, counterparty: item.sup || d.sup || '',
          });
        } });

    window.submitStockOutRequest = async (rows, ref, onProgress) => {
      const issued = [];
      const beforeIds = new Set((window.ALL_MOVEMENTS || []).map(m => m.movementId));
      const tagIssued = () => issued.forEach(r => {
        const mv = window.findNewMovement('ISSUANCE', r.itemId, beforeIds, r.movementId);
        if (mv) { r.movementId = mv.movementId; beforeIds.add(mv.movementId); }
      });
      for (let k = 0; k < rows.length; k++) {
        const row = rows[k];
        if (onProgress) onProgress(k + 1, rows.length, row);
        try {
          const res = await fetch('/api/inventory/stock-out', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ itemId: row.itemId, qty: String(row.requestedQty), ref }),
          });
          let json;
          try { json = await res.json(); }
          catch (_) { throw new Error(`The server returned an unexpected response (HTTP ${res.status}).`); }
          if (!json.ok) throw new Error(json.error || `Request failed (HTTP ${res.status}).`);
          issued.push({ ...row, movementId: json.movementId });
        } catch (err) {
          const error = err instanceof TypeError ? 'Could not connect to the server.' : err.message;
          if (issued.length) { await refreshInventory(); tagIssued(); }
          return { issued, failed: { row, error }, remaining: rows.slice(k) };
        }
      }
      await refreshInventory();
      tagIssued();
      return { issued, failed: null, remaining: [] };
    };
    window.refreshInventory = refreshInventory;

    (async () => {
      try {
        const res  = await fetch('/api/inventory/projects-for-stockout');
        const json = await res.json();
        if (!json.ok) return;
        if (typeof CUSTOMERS !== 'undefined') {
          CUSTOMERS.length = 0;
          json.customers.forEach(r => CUSTOMERS.push(r));
        }
        if (typeof PROJECTS !== 'undefined') {
          PROJECTS.length = 0;
          json.projects.forEach(r => PROJECTS.push(r));
        }
        if (typeof window.renderStockOutProjects === 'function') {
          window.renderStockOutProjects();
        }
      } catch (_) { }
    })();

    if (typeof inventoryStore !== 'undefined') {
      const originalRemove = inventoryStore.remove;
      inventoryStore.remove = (id) => {
        originalRemove(id);
        fetch('/api/inventory/delete', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ id }),
        }).then(r => r.json()).then(j => {
          if (!j.ok) showToast(j.error || 'Could not delete this item', 'error', 'bi-exclamation-triangle');
        }).catch(() => showToast('Could not reach the server', 'error', 'bi-exclamation-triangle'))
          .finally(() => refreshInventory());
      };
    }

    refreshInventory();
  }

  const wireEntityPage = (cfg) => {
    if (!document.getElementById(cfg.anchorId)) return;
    if (typeof window[cfg.arrayName] === 'undefined') return;
    const arr = window[cfg.arrayName];
    const store = window[cfg.storeName];

    arr.length = 0;

    const refresh = async () => {
      try {
        const res = await fetch(cfg.listUrl);
        const json = await res.json();
        if (!json.ok) return;
        arr.length = 0;
        json.data.forEach(r => arr.push(cfg.mapRow ? cfg.mapRow(r) : r));
        if (typeof window[cfg.renderName] === 'function') window[cfg.renderName]();
      } catch (_) {}
    };

    if (cfg.saveFnName) {
      window[cfg.saveFnName] = async (rec) => {
        const res = await fetch(cfg.saveUrl, {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ ...rec, edit_id: rec.id }),
        });
        const json = await res.json();
        if (!json.ok) throw new Error(json.error);
        await refresh();
        return json;
      };
    }

    const form = document.querySelector(cfg.formSelector);
    if (form) {
      form.addEventListener('submit', async (e) => {
        if (!form.checkValidity()) return;
        e.preventDefault();
        e.stopImmediatePropagation();
        const data = Object.fromEntries(new FormData(form));
        data.edit_id = form.getAttribute('data-edit-id') || null;
        try {
          const res = await fetch(cfg.saveUrl, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data),
          });
          const json = await res.json();
          if (!json.ok) throw new Error(json.error);
          await refresh();
          const modalEl = form.closest('.modal');
          if (modalEl) bootstrap.Modal.getInstance(modalEl)?.hide();
          form.reset(); form.classList.remove('was-validated');
          form.removeAttribute('data-edit-id');
          showToast(cfg.successMsg, 'success');
        } catch (err) {
          showToast(err.message, 'error', 'bi-exclamation-triangle');
        }
      }, true);
    }

    if (store && typeof store.remove === 'function') {
      const originalRemove = store.remove;
      store.remove = (id) => {
        originalRemove(id);
        fetch(cfg.deleteUrl, {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ id }),
        }).then(r => r.json()).then(j => {
          if (!j.ok) showToast(j.error || 'Could not delete this record', 'error', 'bi-exclamation-triangle');
        }).catch(() => showToast('Could not reach the server', 'error', 'bi-exclamation-triangle'))
          .finally(() => refresh());
      };
    }

    refresh();
  };

  wireEntityPage({
    anchorId: 'custBody', arrayName: 'CUSTOMERS', storeName: 'customerStore',
    renderName: 'renderCustomers', formSelector: '[data-entity="customers"]',
    listUrl: '/api/customers', saveUrl: '/api/customers/save',
    deleteUrl: '/api/customers/delete', successMsg: 'Customer saved',
  });

  wireEntityPage({
    anchorId: 'supBody', arrayName: 'SUPPLIERS', storeName: 'supplierStore',
    renderName: 'renderSuppliers', formSelector: '[data-entity="suppliers"]',
    listUrl: '/api/suppliers', saveUrl: '/api/suppliers/save',
    deleteUrl: '/api/suppliers/delete', successMsg: 'Supplier saved',
    saveFnName: 'saveSupplierRecord',
  });

  wireEntityPage({
    anchorId: 'projBody', arrayName: 'PROJECTS', storeName: 'projectStore',
    renderName: 'renderProjects', formSelector: '[data-entity="projects"]',
    listUrl: '/api/projects', saveUrl: '/api/projects/save',
    deleteUrl: '/api/projects/delete', successMsg: 'Project saved',
    mapRow: (r) => r,
  });

  if (document.getElementById('dashKpiProjects')) {
    if (typeof PROJECTS !== 'undefined') PROJECTS.length = 0;
    if (typeof TRANSACTIONS !== 'undefined') TRANSACTIONS.length = 0;
    if (typeof INVENTORY !== 'undefined') INVENTORY.length = 0;

    const loadDashboardData = async (url, arr, label) => {
      try {
        const res = await fetch(url);
        const json = await res.json();
        if (!json.ok) {
          console.error(`Failed to load ${label} for dashboard:`, json.error || res.status);
          showToast(`Could not load ${label} from the database`, 'error', 'bi-exclamation-triangle');
          return;
        }
        arr.length = 0;
        json.data.forEach(r => arr.push(r));
        (window.DASH_LOADED = window.DASH_LOADED || {})[label] = true;
        if (typeof window.updateInventoryBadge === 'function') window.updateInventoryBadge();
        if (typeof window.renderDashboard === 'function') window.renderDashboard();
      } catch (err) {
        console.error(`Dashboard ${label} fetch failed:`, err);
        showToast(`Could not connect to the server to load ${label}`, 'error', 'bi-exclamation-triangle');
      }
    };

    const _allowed = window.ALLOWED_PAGES || [];
    if (_allowed.includes('inventory')) loadDashboardData('/api/inventory', INVENTORY, 'inventory');
  }

  const projStaffSelect = document.getElementById('projStaffSelect');
  if (projStaffSelect) {
    fetch('/api/employees').then(r => r.json()).then(json => {
      if (!json.ok) return;
      EMPLOYEES.length = 0;
      json.data.forEach(e => EMPLOYEES.push(e));
      projStaffSelect.innerHTML = '<option value="">Unassigned</option>' + json.data.map(e =>
        `<option value="${esc(e.id)}">${esc(e.name)}${e.status && e.status !== 'Active' ? ' (inactive)' : ''}</option>`).join('');
    }).catch(() => {});
  }

  const projCustSelect = document.getElementById('projCustSelect');
  if (projCustSelect) {
    fetch('/api/customers').then(r => r.json()).then(json => {
      if (!json.ok) return;
      projCustSelect.innerHTML = ''+
        json.data.map(c => `<option value="${esc(c.id)}">${esc(c.name)}</option>`).join('');
    }).catch(() => {});
  }

  if (document.getElementById('txnBody') && typeof TRANSACTIONS !== 'undefined') {

    TRANSACTIONS.length = 0;

    const refreshTxns = async () => {
      try {
        const res = await fetch('/api/transactions');
        const json = await res.json();
        if (!json.ok) {
          console.error('Failed to load real transactions from the server:', json.error || res.status);
          showToast('Could not load transactions from the database — showing may be outdated', 'error', 'bi-exclamation-triangle');
          return;
        }
        TRANSACTIONS.length = 0;
        json.data.forEach(t => TRANSACTIONS.push(t));
        if (typeof window.renderTransactions === 'function') window.renderTransactions();
      } catch (err) {
        console.error('refreshTxns failed:', err);
        showToast('Could not connect to the server to load transactions', 'error', 'bi-exclamation-triangle');
      }
    };

    const fillSelect = (id, url, mapper, placeholder) => {
      const sel = document.getElementById(id);
      if (!sel) return;
      fetch(url).then(r => r.json()).then(json => {
        if (!json.ok) return;
        sel.innerHTML = (placeholder ? `<option value="">${placeholder}</option>` : '') +
          json.data.map(mapper).join('');
      }).catch(() => {});
    };
    fillSelect('txnCustSelect', '/api/customers',
      c => `<option value="${esc(c.id)}">${esc(c.name)}</option>`, 'Select…');
    fillSelect('txnProjSelect', '/api/projects',
      p => `<option value="${esc(p.id)}">${esc(p.id)} — ${esc(p.name)}</option>`, 'None');
    fillSelect('txnMatSelect', '/api/inventory',
      m => `<option value="${m.name}" data-price="${m.price}">${m.name}</option>`, 'Select…');

    document.getElementById('txnMatSelect')?.addEventListener('change', (e) => {
      const opt = e.target.selectedOptions[0];
      const priceInput = document.querySelector('#txnForm [name="price"]');
      if (opt && priceInput && opt.dataset.price) priceInput.value = opt.dataset.price;
    });

    const txnForm = document.getElementById('txnForm');
    if (txnForm) {
      txnForm.addEventListener('submit', async (e) => {
        if (!txnForm.checkValidity()) return;
        e.preventDefault();
        e.stopImmediatePropagation();
        const data = Object.fromEntries(new FormData(txnForm));
        try {
          const res = await fetch('/api/transactions/save', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data),
          });
          const json = await res.json();
          if (!json.ok) throw new Error(json.error);
          await refreshTxns();
          const modalEl = txnForm.closest('.modal');
          if (modalEl) bootstrap.Modal.getInstance(modalEl)?.hide();
          txnForm.reset(); txnForm.classList.remove('was-validated');
          showToast('Transaction created — inventory updated', 'success');
        } catch (err) {
          showToast(err.message, 'error', 'bi-exclamation-triangle');
        }
      }, true);
    }

    refreshTxns();
  }

  document.querySelectorAll('[data-pw-toggle]').forEach(toggle => {
    toggle.addEventListener('click', () => {
      const input = document.querySelector(toggle.getAttribute('data-pw-toggle'));
      if (!input) return;
      const show = input.type === 'password';
      input.type = show ? 'text' : 'password';
      toggle.querySelector('i')?.classList.toggle('bi-eye', !show);
      toggle.querySelector('i')?.classList.toggle('bi-eye-slash', show);
    });
  });

  const loginForm = document.getElementById('loginForm');
  if (loginForm) {
    const tfForm = document.getElementById('twoFactorForm');
    const goNext = (json) => {
      try { sessionStorage.removeItem('parabellum.stockAlertsShown'); } catch (_) {}
      window.location.href = (json.mustChangePassword || json.setup2fa) ? '/profile' : '/dashboard';
    };
    const showErr = (box, msg) => { if (box) { box.textContent = msg; box.classList.remove('d-none'); } };

    document.getElementById('forgotLink')?.addEventListener('click', (e) => {
      e.preventDefault();
      document.getElementById('forgotNote')?.classList.toggle('d-none');
    });

    loginForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      if (!loginForm.checkValidity()) { loginForm.classList.add('was-validated'); return; }
      const btn = document.getElementById('loginBtn');
      const errorBox = document.getElementById('loginError');
      errorBox?.classList.add('d-none');
      btn.disabled = true;
      btn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span> Signing in\u2026';
      try {
        const res = await fetch('/api/login', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            username: document.getElementById('username').value.trim(),
            password: document.getElementById('password').value,
            remember: document.getElementById('remember')?.checked !== false,
          }),
        });
        const json = await res.json();
        if (!json.ok) throw new Error(json.error || 'Invalid username or password.');
        if (json.twoFactor) {
          loginForm.classList.add('d-none');
          tfForm.classList.remove('d-none');
          document.getElementById('twoFactorCode').focus();
          return;
        }
        goNext(json);
      } catch (err) {
        showErr(errorBox, err.message);
      } finally {
        btn.disabled = false;
        btn.innerHTML = '<i class="bi bi-box-arrow-in-right me-1"></i> Sign In';
      }
    });

    tfForm?.addEventListener('submit', async (e) => {
      e.preventDefault();
      const codeEl = document.getElementById('twoFactorCode');
      const box = document.getElementById('twoFactorError');
      const btn = document.getElementById('twoFactorBtn');
      box.classList.add('d-none');
      if (!/^\d{6}$/.test(codeEl.value.trim())) { showErr(box, 'Enter the 6-digit code.'); return; }
      btn.disabled = true;
      try {
        const res = await fetch('/api/login/2fa', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ code: codeEl.value.trim() }),
        });
        const json = await res.json();
        if (json.ok) { goNext(json); return; }
        if (json.restart) {
          tfForm.classList.add('d-none'); loginForm.classList.remove('d-none');
          document.getElementById('password').value = '';
          showErr(document.getElementById('loginError'), json.error);
          return;
        }
        showErr(box, json.error || 'That code is not correct.');
        codeEl.select();
      } catch (_) {
        showErr(box, 'Could not reach the server.');
      } finally {
        btn.disabled = false;
      }
    });
    document.getElementById('twoFactorCode')?.addEventListener('input', (e) => {
      e.target.value = e.target.value.replace(/\D/g, '').slice(0, 6);
      if (e.target.value.length === 6) tfForm.requestSubmit();
    });
    document.getElementById('twoFactorBack')?.addEventListener('click', () => {
      fetch('/api/logout', { method: 'POST' }).finally(() => window.location.reload());
    });
  }

  const usageToggle = document.getElementById('usageToggle');
  if (usageToggle && typeof window.updateUsageChart === 'function') {
    const rangeLabel = document.getElementById('usageRangeLabel');
    usageToggle.querySelectorAll('button').forEach(btn => {
      btn.addEventListener('click', () => {
        usageToggle.querySelectorAll('button').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        const note = window.updateUsageChart(btn.dataset.range);
        if (rangeLabel && note) rangeLabel.textContent = note;
      });
    });
  }

  const projViewToggle = document.getElementById('projViewToggle');
  if (projViewToggle) {
    const tableView   = document.getElementById('projTableView');
    const galleryView = document.getElementById('projGalleryView');
    projViewToggle.querySelectorAll('button').forEach(btn => {
      btn.addEventListener('click', () => {
        projViewToggle.querySelectorAll('button').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        const gallery = btn.dataset.view === 'gallery';
        tableView?.classList.toggle('d-none', gallery);
        galleryView?.classList.toggle('d-none', !gallery);
      });
    });
  }

  document.querySelectorAll('[data-print]').forEach(btn => {
    btn.addEventListener('click', () => window.print());
  });

  document.querySelectorAll('[data-export]').forEach(btn => {
    btn.addEventListener('click', () => {
      const key = btn.dataset.report;
      const fmt = btn.dataset.format;
      if (key && fmt) {
        window.location.href = `/api/reports/${key}/${fmt === 'pdf' ? 'pdf' : 'excel'}`;
        showToast(`Generating ${fmt.toUpperCase()}\u2026`, 'primary', 'bi-download');
      } else {
        showToast(`Generating ${btn.getAttribute('data-export')} file\u2026`, 'primary', 'bi-download');
      }
    });
  });

});

/* KPI tiles */
document.addEventListener('DOMContentLoaded', () => {
  const allowed = window.ALLOWED_PAGES || [];
  const tiles = [...document.querySelectorAll('.stat-card[data-kpi]')];
  tiles.forEach(t => {
    const href = t.dataset.kpiHref;
    if (href) {
      const page = href.replace(/^\//, '').split(/[?#]/)[0];
      if (page && !allowed.includes(page)) { t.removeAttribute('data-kpi'); return; }
    }
    t.setAttribute('role', 'button');
    t.setAttribute('tabindex', '0');
  });

  const select = (tile) => {
    const on = tile && !tile.classList.contains('is-selected');
    tiles.forEach(x => x.classList.remove('is-selected'));
    if (on) tile.classList.add('is-selected');
    return on;
  };

  const activate = (tile) => {
    if (!tile.hasAttribute('data-kpi')) return;
    if (tile.dataset.kpiHref) { window.location.href = tile.dataset.kpiHref; return; }
    if (tile.dataset.kpiScroll) {
      document.querySelector(tile.dataset.kpiScroll)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
      return;
    }
    const on = tile.dataset.kpi === 'all' ? (select(null), false) : select(tile);
    if (typeof window.onKpiFilter === 'function') window.onKpiFilter(on ? tile.dataset.kpi : null);
    const list = document.querySelector('.table-wrap');
    if (on && list) list.scrollIntoView({ behavior: 'smooth', block: 'center' });
  };

  tiles.forEach(t => {
    t.addEventListener('click', () => activate(t));
    t.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); activate(t); } });
  });

  window.clearKpiSelection = () => tiles.forEach(x => x.classList.remove('is-selected'));

  const fromUrl = new URLSearchParams(window.location.search).get('kpi');
  if (fromUrl) {
    const t = tiles.find(x => x.dataset.kpi === fromUrl && !x.dataset.kpiHref && !x.dataset.kpiScroll);
    if (t) setTimeout(() => activate(t), 0);
  }
});
