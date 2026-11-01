/* Transactions page */
document.addEventListener('DOMContentLoaded', () => {
  const tb = document.getElementById('txnBody');
  const set = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v; };
  const TXN_PAGE_SIZE = 8;
  let txnCurrentPage = 1;
  const view = { q: '', pay: '', month: '' };
  const vatRate = () => (Number((window.COMPANY || {}).vat_rate ?? 12) || 0) / 100;
  const monthLabel = (m) => {
    const [y, mo] = m.split('-').map(Number);
    return new Date(y, mo - 1, 1).toLocaleDateString('en-PH', { month: 'short', year: 'numeric' });
  };
  const latestMonth = () => TRANSACTIONS.reduce((max, t) => ((t.date || '') > max ? t.date : max), '').slice(0, 7);

  const compactPeso = (n) => {
    if (n >= 1_000_000) return `\u20b1${(n / 1_000_000).toFixed(2)}M`;
    if (n >= 1_000) return `\u20b1${(n / 1_000).toFixed(1)}K`;
    return PESO(n);
  };

  function renderTxnStats(){
    if (!TRANSACTIONS.length) {
      set('txnStatTotal', 0); set('txnStatPaid', 0);
      set('txnStatPending', 0); set('txnStatRevenue', compactPeso(0));
      return;
    }
    const monthPrefix = latestMonth();
    const thisMonth = TRANSACTIONS.filter(t => (t.date || '').startsWith(monthPrefix));
    const paid = thisMonth.filter(t => t.pay === 'Paid').length;
    const pending = thisMonth.filter(t => t.pay === 'Pending' || t.pay === 'Partial').length;
    const revenue = thisMonth.reduce((sum, t) => sum + (t.qty * t.price * (1 + vatRate())), 0);

    set('txnStatTotal', thisMonth.length);
    set('txnStatPaid', paid);
    set('txnStatPending', pending);
    set('txnStatRevenue', compactPeso(revenue));
  }

  function renderTxnPaginationControls(totalItems){
    const totalPages = Math.max(1, Math.ceil(totalItems / TXN_PAGE_SIZE));
    if (txnCurrentPage > totalPages) txnCurrentPage = totalPages;
    const nav = document.getElementById('txnPaginationNav');
    const ul = document.getElementById('txnPagination');
    if (totalPages <= 1) { nav.style.display = 'none'; return; }
    nav.style.display = '';
    const pageLink = (label, page, opts = {}) => `
      <li class="page-item ${opts.active ? 'active' : ''} ${opts.disabled ? 'disabled' : ''}">
        <a class="page-link" href="#" data-page="${page}">${label}</a>
      </li>`;
    let html = pageLink('<i class="bi bi-chevron-left"></i>', txnCurrentPage - 1, { disabled: txnCurrentPage === 1 });
    buildPageWindow(txnCurrentPage, totalPages).forEach(p => {
      if (p === '\u2026') html += `<li class="page-item disabled"><span class="page-link">\u2026</span></li>`;
      else html += pageLink(p, p, { active: p === txnCurrentPage });
    });
    html += pageLink('<i class="bi bi-chevron-right"></i>', txnCurrentPage + 1, { disabled: txnCurrentPage === totalPages });
    ul.innerHTML = html;
  }

  document.getElementById('txnPagination').addEventListener('click', (e) => {
    const link = e.target.closest('[data-page]');
    if (!link || link.closest('.disabled')) return;
    e.preventDefault();
    const page = parseInt(link.dataset.page, 10);
    if (!page || page === txnCurrentPage) return;
    txnCurrentPage = page;
    renderTransactions();
  });

  function fillMonthFilter(){
    const sel = document.getElementById('txnMonthFilter');
    const months = [...new Set(TRANSACTIONS.map(t => (t.date || '').slice(0, 7)).filter(Boolean))].sort().reverse();
    const keep = sel.value;
    sel.innerHTML = '<option value="">All Months</option>' + months.map(m => `<option value="${m}">${monthLabel(m)}</option>`).join('');
    sel.value = months.includes(keep) ? keep : (view.month && months.includes(view.month) ? view.month : '');
  }

  function filtered(){
    const pays = view.pay ? view.pay.split('|') : null;
    return TRANSACTIONS.filter(t => {
      if (pays && !pays.includes(t.pay)) return false;
      if (view.month && !(t.date || '').startsWith(view.month)) return false;
      if (view.q && ![t.inv, t.cust, t.material, t.proj].join(' ').toLowerCase().includes(view.q)) return false;
      return true;
    });
  }

  function renderTransactions(){
    fillMonthFilter();
    const list = filtered();
    const start = (txnCurrentPage - 1) * TXN_PAGE_SIZE;
    const pageItems = list.slice(start, start + TXN_PAGE_SIZE);

    tb.innerHTML = '';
    pageItems.forEach(t => {
    const sub = t.qty * t.price; const total = sub * (1 + vatRate());
    tb.insertAdjacentHTML('beforeend', `<tr>
      <td class="fw-id">${t.inv}</td><td class="fw-medium">${t.cust}</td>
      <td>${t.material}</td><td class="text-end">${NUM(t.qty)}</td>
      <td class="text-end">${PESO(t.price)}</td><td class="text-end fw-medium">${PESO(total)}</td>
      <td>${payBadge(t.pay)}</td><td class="text-muted-2">${t.date}</td>
      <td class="text-center">
        <button class="act-btn print-inv" data-bs-toggle="tooltip" title="Invoice" data-inv="${t.inv}"><i class="bi bi-receipt"></i></button>
        <button class="act-btn view-txn" data-bs-toggle="tooltip" title="View" data-inv="${t.inv}"><i class="bi bi-eye"></i></button>
      </td></tr>`);
    });
    if (!list.length) tb.innerHTML = '<tr><td colspan="9" class="text-center text-muted-2 py-4">No transactions match the current filter.</td></tr>';
    const suffix = list.length === TRANSACTIONS.length ? '' : ` (filtered from ${TRANSACTIONS.length})`;
    set('txnCount', !list.length ? `0 transactions${suffix}` : pageItems.length === list.length
      ? `Showing ${list.length} transaction${list.length===1?'':'s'}${suffix}`
      : `Showing ${start+1}\u2013${start+pageItems.length} of ${list.length} transactions${suffix}`);
    renderTxnPaginationControls(list.length);
    renderTxnStats();
    initTooltips();
  }
  renderTransactions();
  window.renderTransactions = renderTransactions;

  const resetPage = () => { txnCurrentPage = 1; renderTransactions(); };
  document.getElementById('txnSearch').addEventListener('input', (e) => { view.q = e.target.value.toLowerCase().trim(); resetPage(); });
  document.getElementById('txnPayFilter').addEventListener('change', (e) => { view.pay = e.target.value; window.clearKpiSelection?.(); resetPage(); });
  document.getElementById('txnMonthFilter').addEventListener('change', (e) => { view.month = e.target.value; window.clearKpiSelection?.(); resetPage(); });
  window.onKpiFilter = (key) => {
    view.month = key ? latestMonth() : '';
    view.pay = key === 'paid' ? 'Paid' : key === 'pending' ? 'Pending|Partial' : '';
    document.getElementById('txnPayFilter').value = view.pay;
    document.getElementById('txnMonthFilter').value = view.month;
    resetPage();
  };

  document.body.insertAdjacentHTML('beforeend', `
    <div class="modal fade" id="txnDetailModal" tabindex="-1"><div class="modal-dialog modal-dialog-centered"><div class="modal-content">
      <div class="modal-header"><h5 class="modal-title"><i class="bi bi-receipt-cutoff me-2" style="color:var(--primary)"></i>Transaction Details</h5>
        <button class="btn-close" data-bs-dismiss="modal"></button></div>
      <div class="modal-body" id="txnDetailBody"></div>
      <div class="modal-footer"><button class="btn btn-light-2" data-bs-dismiss="modal">Close</button>
        <button class="btn btn-primary" id="txnDetailInvoiceBtn"><i class="bi bi-receipt me-1"></i>Open Invoice</button></div>
    </div></div></div>`);
  const detailModal = new bootstrap.Modal('#txnDetailModal');
  let currentTxn = null;
  tb.addEventListener('click', (e) => {
    const btn = e.target.closest('.view-txn'); if (!btn) return;
    const t = transactionStore.find(btn.dataset.inv); if (!t) return;
    currentTxn = t.inv;
    const sub = t.qty * t.price, vat = sub * vatRate(), total = sub + vat;
    document.getElementById('txnDetailBody').innerHTML = `
      <div class="d-flex align-items-center justify-content-between mb-3">
        <div><h5 class="mb-0">${t.inv}</h5><div class="small text-muted-2">${t.date}</div></div>
        ${payBadge(t.pay)}
      </div>
      <div class="row g-2 small">
        <div class="col-6"><div class="text-muted-2">Customer</div><div class="fw-medium">${escapeHTML(t.cust)}</div></div>
        <div class="col-6"><div class="text-muted-2">Project</div><div class="fw-medium">${t.proj}</div></div>
        <div class="col-6"><div class="text-muted-2">Material</div><div class="fw-medium">${escapeHTML(t.material)}</div></div>
        <div class="col-6"><div class="text-muted-2">Quantity</div><div class="fw-medium">${NUM(t.qty)}</div></div>
        <div class="col-6"><div class="text-muted-2">Unit Price</div><div class="fw-medium">${PESO(t.price)}</div></div>
        <div class="col-6"><div class="text-muted-2">Payment Method</div><div class="fw-medium">${t.method}</div></div>
        <div class="col-6"><div class="text-muted-2">VAT (${+(vatRate() * 100).toFixed(2)}%)</div><div class="fw-medium">${PESO(vat)}</div></div>
        <div class="col-6"><div class="text-muted-2">Total</div><div class="fw-bold" style="color:var(--primary)">${PESO(total)}</div></div>
      </div>`;
    detailModal.show();
  });
  document.getElementById('txnDetailInvoiceBtn').addEventListener('click', () => {
    detailModal.hide();
    document.querySelector(`.print-inv[data-inv="${currentTxn}"]`)?.click();
  });

  const modal = new bootstrap.Modal('#invoiceModal');
  tb.addEventListener('click', (e) => {
    const btn = e.target.closest('.print-inv'); if (!btn) return;
    const t = TRANSACTIONS.find(x => x.inv === btn.dataset.inv); if (!t) return;
    const sub = t.qty * t.price; const vat = sub * vatRate(); const total = sub + vat;
    document.getElementById('invoiceBody').innerHTML = `
      <div class="d-flex justify-content-between align-items-start mb-3">
        <div class="d-flex gap-2 align-items-center"><img src="/static/assets/img/logo.svg" style="width:40px"><div><div class="fw-bold" style="color:var(--primary)">${escapeHTML((window.COMPANY || {}).company_name || 'Parabellum Steel & Iron Works')}</div><div class="small text-muted-2">${escapeHTML([(window.COMPANY || {}).address, (window.COMPANY || {}).phone].filter(Boolean).join(' \u00b7 '))}</div>${(window.COMPANY || {}).tin ? `<div class="small text-muted-2">TIN ${escapeHTML(window.COMPANY.tin)}</div>` : ''}</div></div>
        <div class="text-end"><div class="h5 mb-0">INVOICE</div><div class="small text-muted-2">${t.inv}</div></div>
      </div><hr>
      <div class="row small mb-3"><div class="col-6"><div class="text-muted-2">Billed To</div><div class="fw-medium">${t.cust}</div><div>Project: ${t.proj}</div></div>
      <div class="col-6 text-end"><div class="text-muted-2">Date</div><div class="fw-medium">${t.date}</div><div>Method: ${t.method}</div></div></div>
      <div class="table-responsive"><table class="table table-soft"><thead><tr><th>Material</th><th class="text-end">Qty</th><th class="text-end">Unit Price</th><th class="text-end">Amount</th></tr></thead>
      <tbody><tr><td>${t.material}</td><td class="text-end">${NUM(t.qty)}</td><td class="text-end">${PESO(t.price)}</td><td class="text-end">${PESO(sub)}</td></tr></tbody></table></div>
      <div class="d-flex justify-content-end"><div class="table-responsive"><table class="small" style="min-width:240px">
        <tr><td class="text-muted-2 pe-4 py-1">Subtotal</td><td class="text-end">${PESO(sub)}</td></tr>
        <tr><td class="text-muted-2 pe-4 py-1">VAT (${+(vatRate() * 100).toFixed(2)}%)</td><td class="text-end">${PESO(vat)}</td></tr>
        <tr><td class="text-muted-2 pe-4 py-1">Discount</td><td class="text-end">₱0.00</td></tr>
        <tr style="border-top:2px solid var(--primary)"><td class="fw-bold pe-4 py-2">TOTAL</td><td class="text-end fw-bold py-2" style="color:var(--primary);font-size:1.1rem">${PESO(total)}</td></tr>
      </table></div>
      <div class="mt-3">${payBadge(t.pay)} <span class="small text-muted-2 ms-1">Payment status</span></div>`;
    modal.show();
  });
});
