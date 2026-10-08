/* =====================================================================
 PARABELLUM ISOS - App Interactivity (vanilla JS)
 ===================================================================== */

/* ------ Security helpers ---------------------------------------------
 esc(s)         - HTML-escape user-controlled strings before dropping
                  them into innerHTML / insertAdjacentHTML. Prevents
                  stored XSS via names / notes an admin could set.
 window.fetch   - Overridden below so every state-changing (POST / PUT /
                  PATCH / DELETE) call to /api/* automatically carries
                  the X-CSRF-Token header from the csrf_token cookie.
                  Existing call sites don't have to change; the wrapper
                  is transparent for GET requests and non-/api/ calls.
 -------------------------------------------------------------------- */
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

/* Shared by every page with a paginated table (inventory, transactions,
 etc.) - a proper "windowed" page list instead of
 rendering a button for every single page. With hundreds of records
 (e.g. 1121 transactions = 141 pages), rendering all of them in one
 unwrapped row overflows and overlaps on any screen, worst of all on
 mobile. Always shows page 1, the last page, and a small window around
 whichever page is currently active, collapsing the rest into "...". */
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

/* ---------------- Transaction receipts (Stock In / Stock Out / Back Order) ----------------
 ONE receipt renderer for every entry point, so a receipt looks the same
 whether it pops up right after Confirm, is reprinted from a table row, or is
 opened from the Reports page:
   buildReceiptHTML(kind, items, info)      -> the receipt's HTML
   showTransactionReceipt(kind, items, info) -> shows it in #moveSlipModal
 kind:  'RECEIPT' (Stock In) | 'ISSUANCE' (Stock Out) | 'RETURN' (Back Order)
 items: one row per material in the transaction:
        [{ movementId, id, name, cat, qty, unit, price }]
        (several items = one receipt with several rows, never one receipt each)
 info:  { when, fields: [[label, value], ...], recordedBy, counterparty, note }
 The modal footer has Close + Print (the app's existing [data-print] button),
 so printing is always optional. */
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
// Back orders live in their own table/id-space now (back_order_id), so
// they're numbered "BKO-####" rather than "MOV-####" - the two are never
// confused even though both ride in the same `movementId` JS field.
const movNo   = (id, kind) => (id || id === 0) && String(id) !== ''
  ? `${kind === 'RETURN' ? 'BKO' : 'MOV'}-${String(id).padStart(4, '0')}` : '';

/* Date + time the receipt was produced, e.g. "October 2, 2026 · 2:45 PM". */
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

  return `
    <div class="receipt-doc">
      <div class="d-flex justify-content-between align-items-start mb-3">
        <div class="d-flex gap-2 align-items-center"><img src="${_rcEsc(logo)}" alt="" style="width:42px">
          <div><div class="fw-bold" style="color:var(--primary)">PARABELLUM STEEL &amp; IRON WORKS</div>
          <div class="small text-muted-2">Inventory &amp; Service Optimization System</div></div></div>
        <div class="text-end"><div class="h5 mb-0">${k.title}</div>
          <div class="small text-muted-2">Receipt No. <span class="fw-medium text-dark">${_rcEsc(receiptNo)}</span></div>
          <div class="small text-muted-2">${_rcEsc(info.when || '')}</div></div>
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

/* Shows a receipt in #moveSlipModal (created here if the page doesn't have
 one, e.g. Reports). If another modal is still closing (the Stock In / Stock
 Out / Back Order form), waits for it so the two don't overlap. */
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

/* The movement a save just created. Uses the id the server returned when it
 sends one (json.movementId); otherwise the newest movement of that type for
 that material that wasn't in the list before the save - read from the
 freshly re-fetched ALL_MOVEMENTS, never from unsaved form/cart state. */
window.findNewMovement = function (type, code, beforeIds, preferId) {
  const all = window.ALL_MOVEMENTS || [];
  if (preferId) { const hit = all.find(m => String(m.movementId) === String(preferId)); if (hit) return hit; }
  return all.filter(m => m.type === type && m.id === code && !(beforeIds && beforeIds.has(m.movementId)))
            .sort((a, b) => b.movementId - a.movementId)[0] || null;
};

document.addEventListener('DOMContentLoaded', () => {

  /* ---------------- Dashboard: fill KPIs, alert and usage chart from the DB ----------
 Nothing on the dashboard is pre-filled with sample figures any more: the KPI
 cards start as "-" and this fills them from /api/dashboard. The Forecast
 Alert banner stays hidden unless a real forecast produced an alert, and the
 usage chart starts empty and is filled for all three ranges. If the fetch
 fails, the page shows dashes / an empty chart and a toast - never made-up
 numbers. */
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

        // Forecast alert banner: shown ONLY when a real forecast produced one.
        const banner = document.getElementById('fcAlertBanner');
        if (banner) {
          if (d.alert) {
            const mat = document.getElementById('fcAlertMaterial');
            const pct = document.getElementById('fcAlertPct');
            const qty = document.getElementById('fcAlertQty');
            if (mat) mat.textContent = d.alert.material;
            if (pct) pct.textContent = Math.abs(d.alert.pct) + '%';
            if (qty) qty.textContent = d.alert.reorder + ' ' + d.alert.unit;
            // Flip "increase"/"decrease" to match the real direction.
            const verb = document.getElementById('fcAlertVerb');
            if (verb) verb.textContent = d.alert.pct < 0 ? 'decrease' : 'increase';
            banner.style.display = '';
          } else {
            banner.style.display = 'none';
          }
        }

        // Material usage chart: real totals for each of the three ranges.
        if (typeof window.setUsageData === 'function') {
          const split = (rows) => [(rows || []).map(u => u.label), (rows || []).map(u => u.qty)];
          window.setUsageData('monthly', ...split(d.usage));
          window.setUsageData('weekly',  ...split(d.usageWeekly));
          window.setUsageData('daily',   ...split(d.usageDaily));
        }
      } catch (err) {
        console.error('Dashboard load failed:', err);
        // Don't leave "Loading..." on screen forever when the request fails.
        const tbFail = document.getElementById('dashTxnBody');
        if (tbFail) tbFail.innerHTML = '<tr><td colspan="5" class="text-center text-muted-2 py-3">Could not load recent transactions.</td></tr>';
        showToast('Could not load dashboard figures from the database', 'error', 'bi-exclamation-triangle');
      }
    })();
  }

  /* ---------------- Session: keep CURRENT_USER populated ----------------
 Identity and role-filtered nav are now rendered server-side (Jinja,
 from the session) on first paint - no flash of the wrong account
 switching between logins. This fetch just keeps the CURRENT_USER JS
 variable populated for pages that still reference it in script (e.g.
 reports.html's "Generated by ..." line), and bounces to /login if a
 cached page is somehow viewed without a live session. */
  (async () => {
    try {
      const res = await fetch('/api/me');
      const json = await res.json();
      if (!json.ok) throw new Error('not signed in');
      CURRENT_USER = json.data;
    } catch {
      if (!location.pathname.startsWith('/login') && location.pathname !== '/') {
        window.location.href = '/login';
      }
    }
  })();

  /* ---------------- Sign out (every "Sign Out" control, any page) ----------------
 Clears the server-side session first, THEN navigates to /login.
 Just linking to /login (the old behavior) left the session live. */
  document.querySelectorAll('a[href="/login"]').forEach(a => {
    if (!/sign out/i.test(a.textContent)) return;
    a.addEventListener('click', (e) => {
      e.preventDefault();
      // Also clear the "already shown this session" flag for the dashboard's
      // auto-popping Low Stock Materials modal, so it pops again right after
      // the next login instead of staying silently dismissed for whoever
      // logs in next on this browser tab (see dashboard.html).
      try { sessionStorage.removeItem('parabellum.lowStockModalShown'); } catch (_) {}
      fetch('/api/logout', { method: 'POST' }).finally(() => {
        window.location.href = '/login';
      });
    });
  });

  /* Sidebar inventory badge = live out-of-stock count. The server renders the
 first value from the database (see _user_context in app.py), so every page
 starts correct. Pages that load the full inventory list (Inventory,
 Dashboard) call this again after each refresh so it follows stock changes
 without a reload. It only recounts once inventory has really loaded - an
 empty array means "not loaded yet", not "zero out of stock". */
  window.updateInventoryBadge = () => {
    if (typeof INVENTORY === 'undefined' || INVENTORY.length === 0) return;
    const oos = INVENTORY.filter(i => i.status === 'Out of Stock').length;
    document.querySelectorAll('.sidebar__nav a[href="/inventory"] .badge').forEach(b => {
      b.textContent = oos;
      b.classList.toggle('d-none', oos === 0);
    });
  };

  /* ---------------- Notifications bell: live feed from /api/notifications ----------------
 Replaces the five identical hardcoded alerts every page used to carry. The
 red dot only shows when there is something to report. */
  (async () => {
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
  })();

  /* ---------------- Sidebar toggle (mobile) ---------------- */
  const sidebar   = document.querySelector('.sidebar');
  const hamburger = document.querySelector('.hamburger');
  const backdrop  = document.querySelector('.backdrop');
  const openNav  = () => { sidebar?.classList.add('open');  backdrop?.classList.add('show'); };
  const closeNav = () => { sidebar?.classList.remove('open'); backdrop?.classList.remove('show'); };
  hamburger?.addEventListener('click', () => sidebar?.classList.contains('open') ? closeNav() : openNav());
  backdrop?.addEventListener('click', closeNav);
  document.querySelectorAll('.sidebar__nav .nav-link').forEach(a => {
    a.addEventListener('click', () => { if (window.innerWidth < 992) closeNav(); });
  });

  /* ---------------- Live clock ---------------- */
  const clockEl = document.getElementById('liveClock');
  const dateEl  = document.getElementById('liveDate');
  function tick() {
    const now = new Date();
    if (clockEl) clockEl.textContent = now.toLocaleTimeString('en-PH', { hour:'2-digit', minute:'2-digit', second:'2-digit' });
    if (dateEl)  dateEl.textContent  = now.toLocaleDateString('en-PH', { weekday:'long', year:'numeric', month:'long', day:'numeric' });
  }
  if (clockEl || dateEl) { tick(); setInterval(tick, 1000); }

  /* ---------------- Tooltips ---------------- */
  document.querySelectorAll('[data-bs-toggle="tooltip"]').forEach(el => new bootstrap.Tooltip(el));

  /* ---------------- Toast helper ----------------
   action (optional): { label, onClick } — renders a small button in the
   toast, bottom-right of the screen (the toast host is already
   position-fixed bottom-0 end-0), e.g. "View Back Order" after recording
   a return, which scrolls the page down to that record. Clicking it also
   dismisses the toast. A toast with an action stays up a little longer
   so there's time to click it. */
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

  /* ---------------- Generic table search ---------------- */
  document.querySelectorAll('[data-table-search]').forEach(input => {
    const target = document.querySelector(input.getAttribute('data-table-search'));
    input.addEventListener('input', () => {
      const q = input.value.toLowerCase().trim();
      target?.querySelectorAll('tbody tr').forEach(row => {
        row.style.display = row.textContent.toLowerCase().includes(q) ? '' : 'none';
      });
    });
  });

  /* ---------------- Generic column filter (data-filter on selects) ---------------- */
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

  /* ---------------- Backend-only operations (server-side by nature; wired once backend exists) ---------------- */
  document.querySelectorAll('[data-backend-action]').forEach(btn => {
    btn.addEventListener('click', () => {
      const action = btn.getAttribute('data-backend-action');
      showToast(`${action} — this operation runs on the server and will be available once the backend is connected.`, 'info', 'bi-info-circle-fill');
    });
  });

  /* ---------------- Shared delete-confirmation dialog ---------------- */
  window.confirmDelete = function (message, onConfirm) {
    let m = document.getElementById('sharedConfirmModal');
    if (!m) {
      document.body.insertAdjacentHTML('beforeend', `
        <div class="modal fade" id="sharedConfirmModal" tabindex="-1"><div class="modal-dialog modal-dialog-centered modal-sm"><div class="modal-content">
          <div class="modal-header"><h5 class="modal-title"><i class="bi bi-exclamation-triangle me-2" style="color:var(--primary)"></i>Confirm Delete</h5>
            <button class="btn-close" data-bs-dismiss="modal"></button></div>
          <div class="modal-body"><p class="mb-0" id="sharedConfirmMsg">Delete this record? This cannot be undone.</p></div>
          <div class="modal-footer"><button type="button" class="btn btn-light-2" data-bs-dismiss="modal">Cancel</button>
            <button type="button" class="btn btn-primary" id="sharedConfirmBtn">Delete</button></div>
        </div></div></div>`);
      m = document.getElementById('sharedConfirmModal');
    }
    document.getElementById('sharedConfirmMsg').textContent = message;
    const btn = document.getElementById('sharedConfirmBtn');
    const clone = btn.cloneNode(true);          // drop any previous listener
    btn.replaceWith(clone);
    const modal = bootstrap.Modal.getOrCreateInstance(m);
    clone.addEventListener('click', () => { modal.hide(); onConfirm(); });
    modal.show();
  };

  /* ---------------- Forms: Bootstrap validation + entity-aware submit ----------------
 Forms tagged data-entity="inventory|customers|projects|users|stock-in|stock-out"
 dispatch an "entity:submit" event that the page's script handles (store mutation +
 re-render). Forms without data-entity keep the simple save-toast behavior. */
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

  /* ---------------- Inventory: back the page onto the database --------------
 The inventory page reads everything through inventoryStore / INVENTORY and
 re-renders with window.renderInventory(). We (1) load real rows from the DB
 on page load, and (2) intercept the Add/Stock-In/Stock-Out forms and the
 delete action so they persist. The server owns the negative-stock rule -
 a stock-out that exceeds the balance is rejected, not silently clamped. */
  if (document.getElementById('stockInBody') && typeof INVENTORY !== 'undefined') {

    // Clear demo rows NOW, before the page's own inline script (runs
    // right after this) paints them as if real. See the matching
    // comment in wireEntityPage for why this ordering matters.
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
        INVENTORY.length = 0;               // clear sample rows, keep the array reference
        invJson.data.forEach(r => INVENTORY.push(r));
        if (typeof window.updateInventoryBadge === 'function') window.updateInventoryBadge();
        window.ALL_MOVEMENTS = moveJson.data;    // Stock In / Stock Out tables read this
        window.ALL_BACKORDERS = boJson.data;     // Back Orders table reads this (its own table now)
        window.STOCK_SUMMARY = sumJson.data;     // per-item In/Out/Back Order aggregate table
        if (typeof window.renderInventory === 'function') window.renderInventory();
      } catch (err) {
        console.error('refreshInventory failed:', err);
        showToast('Could not connect to the server to load inventory', 'error', 'bi-exclamation-triangle');
      }
    };

    // Intercept the three inventory forms in the CAPTURE phase, so this runs
    // before the generic form handler and we can stop its optimistic "success".
    const wire = (selector, url, buildBody, opts = {}) => {
      const form = document.querySelector(selector);
      if (!form) return;
      form.addEventListener('submit', async (e) => {
        if (!form.checkValidity()) return;  // let the generic validation show
        e.preventDefault();
        e.stopImmediatePropagation();       // block the generic (fake-success) handler

        const data = Object.fromEntries(new FormData(form));
        const body = buildBody(data, form);
        // `url` can be a fixed string, or a function(data, form) => string for
        // a form that posts to different endpoints depending on its own state
        // (e.g. the Stock In modal's "Existing Item" vs "New Item" toggle).
        const targetUrl = typeof url === 'function' ? url(data, form) : url;
        // Snapshot BEFORE saving: which movements already existed (so the new
        // one can be told apart after the re-fetch) and the item's details.
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
          // opts.successAction: optional (data, form) => { label, onClick } for
          // a button on the success toast (e.g. "View Back Order").
          const action = typeof opts.successAction === 'function' ? opts.successAction(data, form) : null;
          showToast(msg, 'success', undefined, action);
          // e.g. pop up the transaction receipt (only reached after the server saved it)
          if (typeof opts.onSuccess === 'function') {
            try { opts.onSuccess(data, form, { json, beforeIds, itemBefore }); }
            catch (hookErr) { console.error('Receipt could not be shown:', hookErr); }
          }
        } catch (err) {
          // e.g. "Cannot issue 500 pcs - only 120 in stock." Keep the modal open.
          showToast(err.message, 'error', 'bi-exclamation-triangle');
        }
      }, true);  // <-- capture phase
    };

    /* Stock In doubles as "register a brand-new item + its first delivery"
     (the old, separate Add Item module's job, folded directly into this
     one form - no mode toggle to click first). inventory.html's item-name
     box clears #stockInItemId the moment the typed text no longer matches
     a selected item (see wireItemSearch), so itemId being empty at submit
     time IS the signal that this is a new item, not an existing one:
       itemId set   -> existing item -> /api/inventory/stock-in
       itemId empty -> new item      -> /api/inventory/save, which creates
                                         the material AND - since this is
                                         its first stock - logs that
                                         quantity as a RECEIPT so it shows
                                         up in the Stock In table/report
                                         like any other delivery. */
    wire('#stockInModal form',
      (d) => d.itemId ? '/api/inventory/stock-in' : '/api/inventory/save',
      (d) => (d.itemId
        ? { itemId: d.itemId, qty: d.qty, remarks: d.remarks }
        // Stock In's "new item" path no longer asks for Reorder Level (it's
        // still set explicitly via Add Item, or editable afterward from the
        // item's own Edit form) - 50 is the same default Add Item's own
        // Reorder Level field starts at, so a new item registered this way
        // still gets sensible Low Stock alerting out of the box.
        : { name: d.name, cat: d.cat, sup: d.sup, unit: d.unit, qty: d.qty, price: d.price, reorder: 50, loc: d.loc }),
      { successMsg: (d) => d.itemId ? 'Stock added to inventory' : 'New item added to inventory and stocked',
        // Stock In receipt: exactly the item + quantity just received.
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

    /* Stock Out is now a multi-item request (cart-style). inventory.html
     builds the cart and calls this on "Confirm Stock Out". The server
     endpoint is unchanged (one item per POST, negative-stock guard on the
     server), so rows are sent one at a time, in order. If a row fails, we
     STOP there: rows already issued stay issued (reported back, never
     resent) and the failed row + everything after it come back as
     `remaining`. Inventory is re-fetched once at the end if anything was
     issued so the on-hand numbers stay honest.
       rows: [{ itemId, requestedQty, ... }], ref: project id (e.g. "PRJ-301")
       returns { issued: [...], failed: { row, error } | null, remaining: [...] } */
    window.submitStockOutRequest = async (rows, ref, onProgress) => {
      const issued = [];
      const beforeIds = new Set((window.ALL_MOVEMENTS || []).map(m => m.movementId));
      // After the re-fetch, tag each issued row with the movement it created.
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
          issued.push({ ...row, movementId: json.movementId });   // only rows the server actually deducted
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

    // Record Return (Back Order) is no longer a single-item wire() form -
    // it's a reference-code-driven, multi-item submit (pick a Stock Out
    // reference, edit a Qty to Return per item it covers) handled entirely
    // in inventory.html's own script, the same way Stock Out's cart is.
    // See the "Record Return (Back Order)" block there.

    // The Stock Out Request modal's Project dropdown needs CUSTOMERS +
    // PROJECTS loaded on the Inventory page (they're not otherwise loaded
    // here). We use a scoped endpoint (/api/inventory/projects-for-stockout)
    // that returns only the fields the modal needs and is gated to
    // "inventory" - so Inventory Personnel, who don't have "customers" or
    // "projects" permission, can still pick a project when issuing stock.
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
      } catch (_) { /* connection issues already surfaced by refreshInventory() */ }
    })();

    // Persist deletes: the page calls inventoryStore.remove(id) then re-renders.
    // Wrap remove() so it also tells the server.
    if (typeof inventoryStore !== 'undefined') {
      const originalRemove = inventoryStore.remove;
      inventoryStore.remove = (id) => {
        originalRemove(id);                 // optimistic local removal
        fetch('/api/inventory/delete', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ id }),
        }).catch(() => {});
      };
    }

    refreshInventory();  // load real data on page open
  }

  /* ---------------- Customers & Projects: back onto the database ------------
 Same pattern as inventory: load real rows on open, intercept the entity
 forms to persist via the API, and wrap store.remove() to persist deletes. */
  const wireEntityPage = (cfg) => {
    if (!document.getElementById(cfg.anchorId)) return;
    if (typeof window[cfg.arrayName] === 'undefined') return;
    const arr = window[cfg.arrayName];
    const store = window[cfg.storeName];

    // Clear the demo/sample rows RIGHT NOW, synchronously - before the
    // page's own inline script (which runs after this, since app.js
    // loads first) gets a chance to paint them as if they were real.
    // Without this, the page briefly shows plausible-looking but WRONG
    // numbers (baked-in sample data) until the async fetch below
    // resolves and replaces them - a confusing "flash of wrong data"
    // that looks exactly like a real bug even though nothing is
    // actually broken. Clearing first means the initial paint honestly
    // shows an empty/loading state instead.
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

    // Optional: expose a direct save-one-record function (not tied to the
    // Add/Edit form) for pages that need to persist a change made outside
    // that form - e.g. Suppliers' Deactivate/Reactivate button, which only
    // flips `status` and shouldn't have to fake a form submit to do it.
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
        }).catch(() => {});
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
    saveFnName: 'saveSupplierRecord',   // used by the Deactivate/Reactivate button
  });

  wireEntityPage({
    anchorId: 'projBody', arrayName: 'PROJECTS', storeName: 'projectStore',
    renderName: 'renderProjects', formSelector: '[data-entity="projects"]',
    listUrl: '/api/projects', saveUrl: '/api/projects/save',
    deleteUrl: '/api/projects/delete', successMsg: 'Project saved',
    // /api/projects already returns the resolved display names (cust, staff),
    // looked up by the database from the real customers/employees tables, so
    // rows are used as-is. (This used to resolve names from hardcoded sample
    // arrays, which showed the wrong name whenever a real code matched one.)
    mapRow: (r) => r,
  });

  // --------------------------------------------------------------
  // Dashboard page: pulls from PROJECTS, TRANSACTIONS, and INVENTORY
  // all at once for its KPI cards + recent-transactions table. None of
  // the wiring above engages here (it's all gated behind projBody/
  // txnBody/stockInBody, which don't exist on this page), so without this
  // block the dashboard would show data.js's sample numbers forever -
  // not just a brief flash like the dedicated list pages, since nothing
  // would ever fetch real data for it at all.
  // --------------------------------------------------------------
  if (document.getElementById('dashKpiProjects')) {
    // Clear sample rows immediately, before this page's own inline
    // script paints them - see the matching comment on wireEntityPage
    // for why this ordering matters (avoids a flash of demo numbers).
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
        (window.DASH_LOADED = window.DASH_LOADED || {})[label] = true;   // renderDashboard() waits on this
        if (typeof window.updateInventoryBadge === 'function') window.updateInventoryBadge();
        if (typeof window.renderDashboard === 'function') window.renderDashboard();
      } catch (err) {
        console.error(`Dashboard ${label} fetch failed:`, err);
        showToast(`Could not connect to the server to load ${label}`, 'error', 'bi-exclamation-triangle');
      }
    };

    // The KPI cards and the Recent Client Transactions table are filled
    // from /api/dashboard above (aggregates + 5 latest rows), so the
    // projects / transactions lists are NOT fetched here any more. They
    // used to be, which (a) overwrote the monthly-transactions KPI with the
    // all-time count and (b) threw "Could not load ... from the database"
    // toasts for accounts without Projects / Transactions access (e.g.
    // Inventory Personnel). The full inventory list is only needed for the
    // Low Stock pop-up, so it is fetched only for accounts that may open
    // the Inventory page.
    const _allowed = window.ALLOWED_PAGES || [];
    if (_allowed.includes('inventory')) loadDashboardData('/api/inventory', INVENTORY, 'inventory');
  }

  // On the projects page, fill the "Assigned Personnel" dropdown from the
  // employees table (it used to come from a hardcoded 5-person array).
  const projStaffSelect = document.getElementById('projStaffSelect');
  if (projStaffSelect) {
    fetch('/api/employees').then(r => r.json()).then(json => {
      if (!json.ok) return;
      EMPLOYEES.length = 0;
      json.data.forEach(e => EMPLOYEES.push(e));
      projStaffSelect.innerHTML = json.data.map(e =>
        `<option value="${esc(e.id)}">${esc(e.name)}${e.status && e.status !== 'Active' ? ' (inactive)' : ''}</option>`).join('');
    }).catch(() => {});
  }

  // On the projects page, fill the Customer dropdown from the REAL customer
  // list so a saved project links to an actual customer record (not a sample).
  const projCustSelect = document.getElementById('projCustSelect');
  if (projCustSelect) {
    fetch('/api/customers').then(r => r.json()).then(json => {
      if (!json.ok) return;
      projCustSelect.innerHTML = '<option value="">Select…</option>' +
        json.data.map(c => `<option value="${esc(c.id)}">${esc(c.name)}</option>`).join('');
    }).catch(() => {});
  }

  /* ---------------- Transactions: back onto the database -------------------
 The page renders through TRANSACTIONS + window.renderTransactions(). We
 load real rows, fill the Customer/Project/Material dropdowns from the DB,
 and intercept the create form. Saving a transaction also deducts the sold
 material from inventory server-side (Objective 1.3), with the same
 negative-stock guard as Stock Out. */
  if (document.getElementById('txnBody') && typeof TRANSACTIONS !== 'undefined') {

    // Clear demo rows NOW, before the page's own inline script (runs
    // right after this) paints them as if real. This is the fix for
    // "the page briefly shows old numbers then switches to real ones" -
    // that was always a harmless loading flash, never lost/wrong data,
    // but it looked exactly like a bug. See the matching comment in
    // wireEntityPage for the full explanation.
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
        // A network error, a non-JSON response (e.g. an HTML error page),
        // or anything else unexpected lands here. This used to fail
        // completely silently, leaving the page stuck showing whatever
        // demo/sample rows were on screen before this call ran, with no
        // indication anything was wrong - that's the exact bug behind
        // "the page shows old data instead of the database."
        console.error('refreshTxns failed:', err);
        showToast('Could not connect to the server to load transactions', 'error', 'bi-exclamation-triangle');
      }
    };

    // Populate the three dropdowns from real data.
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

    // Auto-fill unit price when a material is chosen (nice touch, uses catalog price).
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

  /* ---------------- Login submit → real server-side check ---------------- */
  const loginForm = document.getElementById('loginForm');
  if (loginForm) {
    loginForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      if (!loginForm.checkValidity()) { loginForm.classList.add('was-validated'); return; }

      const btn = document.getElementById('loginBtn');
      const errorBox = document.getElementById('loginError');
      errorBox?.classList.add('d-none');
      if (btn) {
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span> Signing in…';
      }

      try {
        const res = await fetch('/api/login', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            username: document.getElementById('username').value.trim(),
            password: document.getElementById('password').value,
          }),
        });
        const json = await res.json();
        if (!json.ok) throw new Error(json.error || 'Invalid username or password.');
        window.location.href = '/dashboard';
      } catch (err) {
        if (errorBox) {
          errorBox.textContent = err.message;
          errorBox.classList.remove('d-none');
        }
        if (btn) {
          btn.disabled = false;
          btn.innerHTML = '<i class="bi bi-box-arrow-in-right me-1"></i> Sign In';
        }
      }
    });
  }

  /* ---------------- Forecasting: LIVE Multiple Linear Regression --------------
 Calls POST /api/forecast. Flask trains the model on monthly_demand,
 evaluates it on months it never saw, forecasts NEXT MONTH for every
 material, and returns real MAE / RMSE / MAPE / R2.
 --------------------------------------------------------------------------- */
  const fcSelect = document.getElementById('fcMaterialSelect');
  if (fcSelect) {
    const set = (id, v) => { const e = document.getElementById(id); if (e) e.textContent = v; };
    const setHTML = (id, v) => { const e = document.getElementById(id); if (e) e.innerHTML = v; };
    let RESULT = null;   // the last full forecast run

    const showError = (msg) => {
      ['kpiMaterial','kpiPredicted','kpiReorder','fcResMaterial',
       'fcResPredicted','fcResMonth','fcResStock','fcResTrend','fcResConf',
       'fcMAE','fcRMSE','fcMAPE','fcR2',
       'fcWxTemp','fcWxRain','fcWxDays','fcWxIndex','fcWxSource'].forEach(id => set(id, '—'));
      setHTML('fcResReorder', `<span class="text-danger fw-semibold">${msg}</span>`);
      setHTML('fcWxInsight', '—');
      if (!fcSelect.value) fcSelect.innerHTML = '<option value="">Unavailable</option>';
      const bar = document.getElementById('fcWxBar');
      if (bar) bar.style.width = '0%';
      const badge = document.getElementById('fcWxBadge');
      if (badge) { badge.textContent = '—'; badge.className = 'badge'; }
    };

    const render = (name) => {
      if (!RESULT) return;
      const f = RESULT.forecasts.find(x => x.material_name === name) || RESULT.forecasts[0];
      if (!f) return;
      const m = RESULT.metrics;

      set('fcResMaterial',  f.material_name);
      set('fcResMonth',     RESULT.forecast_month);
      set('fcResPredicted', f.predicted_demand + ' ' + f.unit);
      set('fcResStock',     f.current_stock + ' ' + f.unit);
      set('fcResTrend',     f.prev_demand
                              ? (((f.predicted_demand - f.prev_demand) / f.prev_demand * 100)
                                  .toFixed(1) + '%')
                              : '—');
      set('fcResConf',      'R² ' + m.r2);

      set('fcMAE',  m.mae);
      set('fcRMSE', m.rmse);
      set('fcMAPE', m.mape === null ? 'n/a' : m.mape + '%');
      set('fcR2',   m.r2);

      set('kpiMaterial',  f.material_name.replace(/\s*\(.*\)/, ''));
      set('kpiPredicted', f.predicted_demand);
      set('kpiReorder',   f.reorder_qty);
      set('fcUpdated',    new Date().toLocaleString());

      setHTML('fcResReorder', f.reorder_qty > 0
        ? `Restock about <strong>${f.reorder_qty} ${f.unit}</strong> before ${RESULT.forecast_month} to meet the predicted demand.`
        : `Current stock is sufficient for the predicted demand in ${RESULT.forecast_month}. No restock needed yet.`);

      // Weather Outlook panel -- forecast-month conditions plus THIS material's
      // own weather->demand relationship (from its per-material MLR fit).
      const wx = RESULT.weather;
      if (wx) {
        set('fcWxTemp',   wx.avg_temp_c + '°C');
        set('fcWxRain',   wx.total_rainfall_mm + ' mm');
        set('fcWxDays',   wx.rainy_days + ' days');
        set('fcWxIndex',  wx.favorability_index + ' / 100 — ' + wx.favorability_label);
        set('fcWxSource', wx.source);

        let insightHTML = f.weather_insight || '—';
        if (f.sample_size_warning) {
          insightHTML += ` <span class="text-warning-emphasis">` +
                         `(Based on only ${f.training_rows} months of history — ` +
                         `treat this coefficient as tentative until more data accumulates.)</span>`;
        }
        if (f.model_type === 'pooled fallback') {
          insightHTML = `<div class="mb-1"><span class="badge b-warning">Pooled fallback</span> ` +
                        `Not enough history for a material-specific model yet.</div>` + insightHTML;
        }
        setHTML('fcWxInsight', insightHTML);

        const bar = document.getElementById('fcWxBar');
        if (bar) {
          bar.style.width = wx.favorability_index + '%';
          bar.className = 'progress-bar ' + (
            wx.favorability_label === 'Favorable'   ? 'bg-success' :
            wx.favorability_label === 'Moderate'    ? 'bg-warning' : 'bg-danger'
          );
        }
        const badge = document.getElementById('fcWxBadge');
        if (badge) {
          badge.textContent = wx.favorability_label;
          badge.className = 'badge ' + (
            wx.favorability_label === 'Favorable'   ? 'b-success' :
            wx.favorability_label === 'Moderate'    ? 'b-warning' : 'b-danger'
          );
        }
      }

      // Repaint the three forecasting charts with the selected material's real
      // history from the DB (last 6 months), plus the MLR-predicted dot.
      const history = f.history || [];
      const fcLabel = f.forecast_label || RESULT.forecast_month;
      if (typeof window.updateForecastChart === 'function')
        window.updateForecastChart(history, fcLabel, f.predicted_demand);
      if (typeof window.updateHistoricalChart === 'function')
        window.updateHistoricalChart(history);
      if (typeof window.updateInventoryChart === 'function')
        window.updateInventoryChart(history);
    };

    const runForecast = async () => {
      fcSelect.disabled = true;
      set('fcResPredicted', 'Running model…');
      try {
        const res  = await fetch('/api/forecast', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({})
        });
        const json = await res.json();
        if (!json.ok) throw new Error(json.error);

        RESULT = json.data;

        const chosen = fcSelect.value;
        fcSelect.innerHTML = '';
        RESULT.forecasts.forEach(f => {
          const o = document.createElement('option');
          o.value = o.textContent = f.material_name;
          fcSelect.appendChild(o);
        });
        if (RESULT.forecasts.some(f => f.material_name === chosen)) fcSelect.value = chosen;

        render(fcSelect.value);

        // Newly saved forecast rows should show up immediately in the
        // Prediction History table below.
        if (typeof window.reloadForecastHistory === 'function')
          window.reloadForecastHistory();
      } catch (err) {
        showError(err.message);
      } finally {
        fcSelect.disabled = false;
      }
    };

    fcSelect.addEventListener('change', () => render(fcSelect.value));
    const runBtn = document.getElementById('fcRunBtn');
    if (runBtn) runBtn.addEventListener('click', runForecast);
    runForecast();
  }

  /* ---------------- Dashboard: inventory-usage timeframe toggle (Daily / Weekly / Monthly) ---------------- */
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

  /* ---------------- Projects: Table / Gallery view toggle ---------------- */
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

  /* ---------------- Print (invoice / report) ---------------- */
  document.querySelectorAll('[data-print]').forEach(btn => {
    btn.addEventListener('click', () => window.print());
  });

  /* ---------------- Export buttons: REAL PDF / Excel downloads ----------------
 Buttons with data-report + data-format hit the real export endpoint,
 which generates the file server-side from the live database and the
 browser downloads it directly. Buttons without those attributes (the
 bulk "Recent Reports" header buttons) keep the old placeholder toast -
 there isn't a single report type for them to export yet. */
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

  /* ---------------- Settings theme toggle (demo) ---------------- */
  document.querySelectorAll('[data-theme-swatch]').forEach(sw => {
    sw.addEventListener('click', () => {
      document.querySelectorAll('[data-theme-swatch]').forEach(s => s.classList.remove('active'));
      sw.classList.add('active');
      showToast('Theme preference saved', 'success');
    });
  });

});
