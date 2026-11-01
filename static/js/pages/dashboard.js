/* Dashboard page */
let autoShownStockModal = false;
function renderDashboard(){
  const L = window.DASH_LOADED || {};
  const set = (id,v)=>{ const el=document.getElementById(id); if(el) el.textContent=v; };
  if (L.inventory) set('dashKpiItems', INVENTORY.length);
  const low = INVENTORY.filter(i=>i.status==='Low Stock')
    .sort((a, b) => (a.qty / (a.reorder || 1)) - (b.qty / (b.reorder || 1)));
  if (L.inventory) set('dashKpiLow', low.length);

  const lowList = document.getElementById('dashLowStockList');
  if (lowList && L.inventory) lowList.innerHTML = low.length
    ? low.map(i => `
      <div class="sl-item">
        <div><div class="sl-name">${escapeHTML(i.name)}</div><div class="sl-sub">${i.loc} · Reorder at ${NUM(i.reorder)} ${i.unit}</div></div>
        <div class="sl-qty" style="color:var(--accent-dark)">${NUM(i.qty)} ${i.unit}</div>
      </div>`).join('')
    : '<div class="stock-empty">No low-stock materials.</div>';

  const out = INVENTORY.filter(i => i.status === 'Out of Stock')
    .sort((a, b) => String(a.name).localeCompare(String(b.name)));
  const outList = document.getElementById('dashOutStockList');
  if (outList && L.inventory) outList.innerHTML = out.length
    ? out.map(i => `
      <div class="sl-item">
        <div><div class="sl-name">${escapeHTML(i.name)}</div><div class="sl-sub">${i.loc} · Reorder at ${NUM(i.reorder)} ${i.unit}</div></div>
        <div class="text-end"><div class="sl-qty" style="color:var(--primary)">0 ${i.unit}</div>
          <div class="sl-sub">Back ordered: ${NUM(i.backOrdered || 0)} ${i.unit}</div></div>
      </div>`).join('')
    : '<div class="stock-empty">No out-of-stock materials.</div>';

  const outCount = document.getElementById('dashOutStockCount');
  const lowCount = document.getElementById('dashLowStockCount');
  if (L.inventory) {
    if (outCount) outCount.textContent = '(' + out.length + ')';
    if (lowCount) lowCount.textContent = '(' + low.length + ')';
  }

  let alertsAlreadyShown = false;
  try { alertsAlreadyShown = sessionStorage.getItem('parabellum.stockAlertsShown') === '1'; } catch (_) {}
  if (!autoShownStockModal && !alertsAlreadyShown && L.inventory && (out.length || low.length)) {
    autoShownStockModal = true;
    try { sessionStorage.setItem('parabellum.stockAlertsShown', '1'); } catch (_) {}
    bootstrap.Modal.getOrCreateInstance('#dashStockModal').show();
  }
}
window.renderDashboard = renderDashboard;

document.addEventListener('DOMContentLoaded', renderDashboard);

document.addEventListener('keydown', (e) => {
  const card = e.target.closest?.('.stat-card[data-bs-target="#dashStockModal"]');
  if (!card || (e.key !== 'Enter' && e.key !== ' ')) return;
  e.preventDefault();
  bootstrap.Modal.getOrCreateInstance('#dashStockModal').show();
});
