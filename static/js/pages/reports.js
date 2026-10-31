/* Reports page */
document.addEventListener('DOMContentLoaded', () => initTooltips());

document.addEventListener('DOMContentLoaded', () => {
  const peso = (n) => '\u20b1' + Number(n).toLocaleString('en-PH', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const short = (n) => {
    n = Number(n);
    if (Math.abs(n) >= 1e6) return '\u20b1' + (n / 1e6).toFixed(2) + 'M';
    if (Math.abs(n) >= 1e3) return '\u20b1' + (n / 1e3).toFixed(1) + 'K';
    return '\u20b1' + n.toFixed(2);
  };
  const $ = (id) => document.getElementById(id);
  const body = $('rpRecentBody');
  const esc = (v) => String(v == null ? '' : v).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

  fetch('/api/reports/overview', { credentials: 'same-origin' })
    .then(r => r.json())
    .then(res => {
      if (!res.ok) throw new Error(res.error || 'Failed');
      const d = res.data;
      $('rpStatExported').textContent = d.exportedThisYear;
      $('rpStatRevenue').textContent = short(d.ytdRevenue);
      $('rpStatRevenueLbl').textContent = d.ytdLabel || 'Year to date';
      $('rpStatInvValue').textContent = short(d.inventoryValue);
      if (d.growthPct == null) {
        $('rpStatGrowth').textContent = '\u2014';
        $('rpStatGrowthLbl').textContent = 'No prior-year data to compare';
      } else {
        $('rpStatGrowth').textContent = (d.growthPct >= 0 ? '+' : '') + Math.round(Number(d.growthPct)) + '%';
      }
      if (window.setRevenueChart)  window.setRevenueChart(d.revenueByMonth.map(x => x.label), d.revenueByMonth.map(x => x.amount));
      if (window.setCategoryChart) window.setCategoryChart(d.valueByCategory.map(x => x.label), d.valueByCategory.map(x => x.value));

      if (!d.recent.length) {
        body.innerHTML = '<tr><td colspan="6" class="text-center text-muted-2 py-3">No reports exported yet.</td></tr>';
        return;
      }
      body.innerHTML = d.recent.map(r => {
        const isPdf = r.format === 'PDF';
        const badge = r.format ? `<span class="badge ${isPdf ? 'b-danger' : 'b-success'}">${esc(r.format)}</span>` : '<span class="text-muted-2">&mdash;</span>';
        const dl = (r.key && r.format)
          ? `<button class="act-btn" data-recent-dl="${esc(r.key)}" data-fmt="${isPdf ? 'pdf' : 'excel'}" title="Download again"><i class="bi bi-download"></i></button>`
          : '<span class="text-muted-2">&mdash;</span>';
        return `<tr><td class="fw-id">${esc(r.ref)}</td><td>${esc(r.type)}</td><td>${esc(r.by)}</td><td class="text-muted-2">${esc(r.date)}</td><td>${badge}</td><td class="text-center">${dl}</td></tr>`;
      }).join('');
    })
    .catch(() => {
      body.innerHTML = '<tr><td colspan="6" class="text-center text-muted-2 py-3">Could not load recent reports.</td></tr>';
      if (typeof showToast === 'function') showToast('Could not load the report overview.', 'error', 'bi-exclamation-triangle');
    });

  body.addEventListener('click', (e) => {
    const b = e.target.closest('[data-recent-dl]');
    if (!b) return;
    window.location.href = `/api/reports/${b.dataset.recentDl}/${b.dataset.fmt}`;
  });
});

   document.addEventListener('DOMContentLoaded', () => {
     const modal = new bootstrap.Modal('#reportPreviewModal');
     const today = new Date().toLocaleDateString('en-PH', { year:'numeric', month:'long', day:'numeric' });
     const rpTitle = document.getElementById('rpTitle');
     const rpBody  = document.getElementById('rpBody');
     let currentKey = null;
     let currentRange = { from: '', to: '' };

     const wrap = (subtitle, columns, rows) => {
       const head = `<thead><tr>${columns.map(c=>`<th>${escapeHTML(c)}</th>`).join('')}</tr></thead>`;
       const body = rows.length
         ? rows.map(row => `<tr>${row.map(cell=>{ const t = String(cell); const st = t.includes('\n') ? 'white-space:pre-line;min-width:210px' : (t.length <= 14 ? 'white-space:nowrap' : 'white-space:pre-line'); return `<td style="${st}">${escapeHTML(t)}</td>`; }).join('')}</tr>`).join('')
         : `<tr><td colspan="${columns.length}" class="text-center text-muted-2 py-3">No records found.</td></tr>`;
       return `
         <div class="d-flex justify-content-between align-items-start mb-2">
           <div><div class="fw-bold" style="color:var(--primary)">PARABELLUM STEEL &amp; IRON WORKS</div>
           <div class="small text-muted-2">${escapeHTML(subtitle)}</div></div>
           <div class="small text-muted-2 text-end">Generated ${today}<br>by ${escapeHTML(CURRENT_USER.name || '')}</div>
         </div><hr class="mt-2">
         <div class="table-wrap"><table class="table table-soft">${head}<tbody>${body}</tbody></table></div>`;
     };

     const MOVE_REPORTS = {
       'stock-in':   { type: 'RECEIPT',  title: 'Stock In Report',   sub: 'Materials received into inventory', qty: 'Qty In' },
       'stock-out':  { type: 'ISSUANCE', title: 'Stock Out Report',  sub: 'Materials issued to clients / projects', qty: 'Qty Out' },
       'back-order': { type: 'RETURN',   title: 'Back Order Report', sub: 'Materials returned by clients / projects', qty: 'Qty Returned' },
     };
     const PRESETS = [['all','All'], ['today','Today'], ['yesterday','Yesterday'], ['week','This Week'], ['month','This Month'], ['custom','Custom']];
     const iso = (d) => `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;
     function presetRange(p){
       const now = new Date(); const d0 = new Date(now.getFullYear(), now.getMonth(), now.getDate());
       if (p === 'today') return { from: iso(d0), to: iso(d0) };
       if (p === 'yesterday') { const y = new Date(d0); y.setDate(y.getDate() - 1); return { from: iso(y), to: iso(y) }; }
       if (p === 'week') {
         const mon = new Date(d0); mon.setDate(mon.getDate() - ((mon.getDay() + 6) % 7));
         const sun = new Date(mon); sun.setDate(sun.getDate() + 6); return { from: iso(mon), to: iso(sun) };
       }
       if (p === 'month') return { from: iso(new Date(d0.getFullYear(), d0.getMonth(), 1)), to: iso(new Date(d0.getFullYear(), d0.getMonth() + 1, 0)) };
       return { from: '', to: '' };
     }
     const fmtDay = (s) => s ? new Date(s + 'T00:00:00').toLocaleDateString('en-PH', { year:'numeric', month:'short', day:'numeric' }) : '';
     const periodLabel = ({ from, to }) => !from && !to ? 'All dates'
       : from === to ? fmtDay(from) : `${from ? fmtDay(from) : 'Beginning'} \u2013 ${to ? fmtDay(to) : 'Today'}`;
     const inRange = (date, { from, to }) => { const d = String(date || '').slice(0, 10); return (!from || d >= from) && (!to || d <= to); };
     const movNo = (id, kind) => `${kind === 'RETURN' ? 'BKO' : 'MOV'}-${String(id).padStart(4,'0')}`;
     const dash = (v) => (v && v !== '\u2014') ? v : '\u2014';

     const mv = { key: null, preset: 'all', movements: null, fallback: null, items: null, viewing: null };

     async function loadStockSummary(){
       let items = [];
       try { const r = await fetch('/api/inventory'); const j = await r.json(); if (j.ok) items = j.data; } catch (_) {}
       const totalValue = items.reduce((sum, i) => sum + (Number(i.qty) || 0) * (Number(i.price) || 0), 0);
       const inStock    = items.filter(i => (Number(i.qty) || 0) > 0).length;
       const set = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val; };
       set('sumItemCount', `${items.length} item${items.length === 1 ? '' : 's'}`);
       set('sumTotalValue', PESO(totalValue));
       set('sumTotalQty', `${NUM(inStock)} of ${NUM(items.length)} items`);
       document.getElementById('sumByItem').innerHTML = items.length
         ? items.slice().sort((a, b) => (Number(b.qty)||0)*(Number(b.price)||0) - (Number(a.qty)||0)*(Number(a.price)||0)).map(i => `
           <div class="sl-item">
             <div><div class="sl-name">${escapeHTML(i.name)}</div><div class="sl-sub">${escapeHTML(i.id)} · ${NUM(i.qty)} ${escapeHTML(i.unit)}</div></div>
             <div class="sl-qty">${PESO((Number(i.qty)||0) * (Number(i.price)||0))}</div>
           </div>`).join('')
         : '<div class="stock-empty">No inventory items yet.</div>';
       if (items.length) mv.items = items;
     }
     loadStockSummary();

     async function loadMoveData(){
       try { const r = await fetch('/api/inventory'); const j = await r.json(); if (j.ok) mv.items = j.data; } catch (_) {}
       const endpoint = mv.key === 'back-order' ? '/api/inventory/backorders' : '/api/inventory/movements';
       try {
         const r = await fetch(endpoint); const j = await r.json();
         if (j.ok) { mv.movements = j.data; return; }
       } catch (_) {}
       mv.movements = null;
       const r = await fetch(`/api/reports/${mv.key}/data`); const j = await r.json();
       if (!j.ok) throw new Error(j.error || 'Could not load the report.');
       mv.fallback = j.data;
     }
     const itemOf = (code) => (mv.items || (typeof INVENTORY !== 'undefined' ? INVENTORY : [])).find(i => i.id === code) || {};

     function filterBar(){
       const btns = PRESETS.map(([k, label]) =>
         `<button type="button" class="btn btn-sm ${mv.preset === k ? 'btn-primary' : 'btn-soft'}" data-preset="${k}" aria-pressed="${mv.preset === k}">${label}</button>`).join('');
       const custom = mv.preset === 'custom' ? `
         <div class="d-flex flex-wrap align-items-center gap-2 mt-2">
           <label class="small text-muted-2" for="rpFrom">From</label><input type="date" class="form-control form-control-sm" style="max-width:170px" id="rpFrom" value="${currentRange.from}">
           <label class="small text-muted-2" for="rpTo">To</label><input type="date" class="form-control form-control-sm" style="max-width:170px" id="rpTo" value="${currentRange.to}">
         </div>` : '';
       return `<div class="mb-3 no-print"><div class="d-flex flex-wrap gap-1" role="group" aria-label="Date filter">${btns}</div>${custom}</div>`;
     }

     function summaryCards(stats){
       return `<div class="row g-2 mb-3">${stats.map(([label, value]) => `
         <div class="col-6 col-md-3"><div class="border rounded-3 p-2 h-100" style="border-color:var(--border)!important">
           <div class="small text-muted-2">${escapeHTML(label)}</div><div class="fw-bold">${escapeHTML(String(value))}</div></div></div>`).join('')}</div>`;
     }
     const qtyByUnit = (list) => {
       const by = {}; list.forEach(m => { by[m.unit] = (by[m.unit] || 0) + (Number(m.qty) || 0); });
       const parts = Object.entries(by).map(([u, q]) => `${NUM(q)} ${u}`);
       return parts.length ? parts.join(' \u00b7 ') : '0';
     };

     function renderMoveReport(){
       const cfg = MOVE_REPORTS[mv.key];
       rpTitle.textContent = cfg.title;
       const header = `
         <div class="d-flex justify-content-between align-items-start mb-2">
           <div><div class="fw-bold" style="color:var(--primary)">PARABELLUM STEEL &amp; IRON WORKS</div>
           <div class="small text-muted-2">${escapeHTML(cfg.sub)} \u00b7 <span class="fw-medium text-dark">${escapeHTML(periodLabel(currentRange))}</span></div></div>
           <div class="small text-muted-2 text-end">Generated ${today}<br>by ${escapeHTML(CURRENT_USER.name || '')}</div>
         </div><hr class="mt-2">`;

       if (!mv.movements) {
         const d = mv.fallback; const di = d.columns.findIndex(c => /date/i.test(c));
         const rows = di < 0 ? d.rows : d.rows.filter(r => inRange(r[di], currentRange));
         rpBody.innerHTML = filterBar() + header + summaryCards([['Transactions', rows.length]])
           + `<div class="table-wrap"><table class="table table-soft"><thead><tr>${d.columns.map(c => `<th>${escapeHTML(c)}</th>`).join('')}</tr></thead><tbody>${
               rows.length ? rows.map(r => `<tr>${r.map(c => `<td>${escapeHTML(String(c))}</td>`).join('')}</tr>`).join('')
               : `<tr><td colspan="${d.columns.length}" class="text-center text-muted-2 py-3">No transactions in this period.</td></tr>`}</tbody></table></div>`;
         return;
       }

       const list = mv.movements.filter(m => m.type === cfg.type && inRange(m.date, currentRange))
         .sort((a, b) => String(b.date).localeCompare(String(a.date)) || b.movementId - a.movementId);
       const stats = [['Transactions', list.length], [`Total ${cfg.qty}`, qtyByUnit(list)], ['Materials', new Set(list.map(m => m.id)).size]];
       if (cfg.type === 'ISSUANCE') stats.push(['Projects / References', new Set(list.map(m => m.remarks).filter(Boolean)).size]);
       else if (cfg.type === 'RETURN') stats.push(['Pending Disposition', list.filter(m => !m.disposition).length]);
       else stats.push(['Recorded by', new Set(list.map(m => m.recordedBy).filter(v => v && v !== '\u2014')).size + ' staff']);

       const extraHead = cfg.type === 'RECEIPT' ? '<th>Supplier</th><th>Remarks</th>'
         : cfg.type === 'ISSUANCE' ? '<th>Project / Reference</th>' : '<th>Received By</th><th>Reason</th><th>Disposition</th>';
       const dispositionCell = (m) => {
         if (m.disposition === 'Replaced' && m.replacedQty != null) return `Replaced (${NUM(m.replacedQty)} ${m.unit})`;
         if (m.disposition === 'Reimbursed' && m.reimbursedAmount != null) return `Reimbursed (${PESO(m.reimbursedAmount)})`;
         return m.disposition || 'Pending';
       };
       const extraCells = (m) => cfg.type === 'RECEIPT'
         ? `<td>${escapeHTML(dash(itemOf(m.id).sup))}</td><td class="text-muted-2">${escapeHTML(dash(m.remarks))}</td>`
         : cfg.type === 'ISSUANCE' ? `<td>${escapeHTML(dash(m.remarks))}</td>`
         : `<td>${escapeHTML(dash(m.backOrderBy))}</td><td class="text-muted-2">${escapeHTML(dash(m.remarks))}</td><td>${escapeHTML(dispositionCell(m))}</td>`;
       const cols = 7 + (cfg.type === 'ISSUANCE' ? 1 : cfg.type === 'RECEIPT' ? 2 : 3);
       rpBody.innerHTML = filterBar() + header + summaryCards(stats) + `
         <div class="table-wrap"><table class="table table-soft table-hover mb-1"><thead><tr>
           <th>Ref No.</th><th>Date</th><th>Material</th><th>Category</th><th class="text-end">${cfg.qty}</th><th>Unit</th>${extraHead}<th>Recorded By</th></tr></thead>
           <tbody>${list.length ? list.map(m => `<tr role="button" tabindex="0" style="cursor:pointer" data-open-movement="${m.movementId}" title="Open receipt">
               <td class="fw-id">${movNo(m.movementId, m.type)}</td><td class="text-muted-2" style="white-space:nowrap">${escapeHTML(m.date)}</td>
               <td><div class="fw-medium">${escapeHTML(m.name)}</div><div class="small text-muted-2">${escapeHTML(m.id)}</div></td>
               <td>${escapeHTML(m.cat)}</td><td class="text-end">${NUM(m.qty)}</td><td>${escapeHTML(m.unit)}</td>
               ${extraCells(m)}<td class="text-muted-2">${escapeHTML(dash(m.recordedBy))}</td></tr>`).join('')
             : `<tr><td colspan="${cols}" class="text-center text-muted-2 py-3">No transactions in this period.</td></tr>`}</tbody></table></div>
         ${list.length ? '<div class="small text-muted-2 no-print"><i class="bi bi-hand-index me-1"></i>Click a row to open its receipt.</div>' : ''}`;
     }

     function openMovementReceipt(id){
       const m = (mv.movements || []).find(x => String(x.movementId) === String(id)); if (!m) return;
       mv.viewing = m.movementId;
       const item = itemOf(m.id);
       const common = [['Date Recorded', m.date], ['Recorded by', m.recordedBy]];
       const fields = m.type === 'RECEIPT'
         ? [['Supplier', item.sup], ['Warehouse / Location', item.loc], ['Remarks / Reference', m.remarks], ...common]
         : m.type === 'ISSUANCE' ? [['Project / Reference', m.remarks], ['Location', item.loc], ...common]
         : [['Project Code', m.stockOutRef], ['Received By', m.backOrderBy], ['Reason for Return', m.remarks], ['Disposition', m.disposition || 'Pending'], ['Location', item.loc], ...common];
       rpTitle.textContent = `${RECEIPT_KINDS[m.type].label} Receipt`;
       rpBody.innerHTML = `<button type="button" class="btn btn-light-2 btn-sm mb-3 no-print" data-back-to-report><i class="bi bi-arrow-left me-1"></i>Back to report</button>`
         + window.buildReceiptHTML(m.type, [{ movementId: m.movementId, id: m.id, name: m.name, cat: m.cat, qty: m.qty, unit: m.unit, price: Number(item.price) || 0 }], {
             when: m.date, fields, recordedBy: m.recordedBy && m.recordedBy !== '\u2014' ? m.recordedBy : '',
             counterparty: m.type === 'RECEIPT' ? (item.sup || '') : (m.type === 'RETURN' ? (m.backOrderBy || '') : ''),
             note: 'Reprint of a recorded movement. Unit price shown is the item\u2019s current price.',
           });
     }

     rpBody.addEventListener('click', (e) => {
       if (!mv.key) return;
       const p = e.target.closest('[data-preset]');
       if (p) { mv.preset = p.dataset.preset; if (mv.preset !== 'custom') currentRange = presetRange(mv.preset); renderMoveReport(); return; }
       if (e.target.closest('[data-back-to-report]')) { mv.viewing = null; renderMoveReport(); return; }
       const row = e.target.closest('[data-open-movement]');
       if (row) openMovementReceipt(row.dataset.openMovement);
     });
     rpBody.addEventListener('keydown', (e) => {
       const row = e.target.closest('[data-open-movement]');
       if (row && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); openMovementReceipt(row.dataset.openMovement); }
     });
     rpBody.addEventListener('change', (e) => {
       if (!mv.key || !['rpFrom', 'rpTo'].includes(e.target.id)) return;
       const f = document.getElementById('rpFrom')?.value || '', t = document.getElementById('rpTo')?.value || '';
       currentRange = (f && t && f > t) ? { from: t, to: f } : { from: f, to: t };
       renderMoveReport();
     });

     document.querySelectorAll('[data-gen]').forEach(btn => btn.addEventListener('click', async () => {
       const key = btn.dataset.gen;
       currentKey = key;
       mv.key = MOVE_REPORTS[key] ? key : null;
       mv.preset = 'all'; mv.movements = null; mv.fallback = null; mv.viewing = null;
       currentRange = { from: '', to: '' };
       { const dlg = document.querySelector('#reportPreviewModal .modal-dialog'); dlg.classList.remove('modal-xl'); dlg.style.maxWidth = ''; }
       rpTitle.textContent = 'Loading\u2026';
       rpBody.innerHTML = '<div class="text-center py-4"><span class="spinner-border spinner-border-sm"></span></div>';
       modal.show();
       try {
         if (mv.key) { await loadMoveData(); renderMoveReport(); return; }
         const res = await fetch(`/api/reports/${key}/data`);
         const json = await res.json();
         if (!json.ok) throw new Error(json.error);
         const d = json.data;
         rpTitle.textContent = d.title;
         { const dlg = document.querySelector('#reportPreviewModal .modal-dialog'); dlg.classList.toggle('modal-xl', d.columns.length > 7); dlg.style.maxWidth = d.columns.length > 7 ? 'min(1400px, 96vw)' : ''; }
         rpBody.innerHTML = wrap(d.subtitle, d.columns, d.rows);
       } catch (err) {
         rpTitle.textContent = 'Report Preview';
         rpBody.innerHTML = `<div class="alert alert-danger mb-0">${escapeHTML(err.message)}</div>`;
       }
     }));

     const exportUrl = (fmt) => {
       const qs = mv.key && (currentRange.from || currentRange.to)
         ? '?' + new URLSearchParams({ from: currentRange.from, to: currentRange.to }).toString() : '';
       return `/api/reports/${currentKey}/${fmt}${qs}`;
     };
     document.getElementById('rpExportPdf')?.addEventListener('click', () => {
       if (currentKey) { if (window.STATIC_PREVIEW) return window.previewNotice('PDF export'); window.location.href = exportUrl('pdf'); }
     });
     document.getElementById('rpExportExcel')?.addEventListener('click', () => {
       if (currentKey) { if (window.STATIC_PREVIEW) return window.previewNotice('Excel export'); window.location.href = exportUrl('excel'); }
     });
   });
