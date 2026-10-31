(function () {
  const $ = (id) => document.getElementById(id);
  const STATUS_BADGE = {
    'Out of Stock': 'b-danger', 'Critical': 'b-danger', 'Low': 'b-warning', 'OK': 'b-success',
  };
  const DEL_BADGE = {
    Pending: ['b-warning', 'bi-hourglass-split'], Standby: ['b-danger', 'bi-pause-circle-fill'],
    Delivered: ['b-success', 'bi-check-circle-fill'], Returned: ['b-neutral', 'bi-arrow-counterclockwise'],
  };
  const RISK_BADGE = { Low: 'b-success', Medium: 'b-warning', High: 'b-danger' };

  let DATA = { materials: [], deliveries: [], summary: {}, canEditCritical: false, canManageDeliveries: false };
  let kpi = null;
  let delTab = '';
  let delPage = 1;
  const DEL_PER_PAGE = 15;
  let failId = null;

  const fmt = (n) => (n === null || n === undefined) ? '&mdash;' : NUM(Math.round(Number(n) * 100) / 100);
  const fmtDate = (iso) => {
    const d = new Date(iso);
    return isNaN(d) ? '' : d.toLocaleDateString('en-PH', { month: 'short', day: 'numeric', year: 'numeric' });
  };
  const fmtWhen = (iso) => {
    const d = new Date(iso);
    return isNaN(d) ? '' : fmtDate(iso) + ' · ' + d.toLocaleTimeString('en-PH', { hour: 'numeric', minute: '2-digit' });
  };

  async function api(url, body) {
    const res = await fetch(url, body === undefined ? {} : {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    });
    const json = await res.json().catch(() => ({ ok: false, error: 'Unexpected server response.' }));
    if (!json.ok) throw new Error(json.error || 'Request failed.');
    return json.data;
  }

  // KPI tiles
  function renderSummary() {
    const s = DATA.summary;
    $('olKpiCritical').textContent = NUM(s.critical || 0);
    $('olKpiLow').textContent = NUM(s.low || 0);
    $('olKpiRunout').textContent = NUM(s.willRunOut || 0);
    $('olKpiStandby').textContent = NUM(s.standby || 0);
    $('olKpiPending').textContent = `${NUM(s.pending || 0)} pending delivery`;
    const month = (DATA.materials.find(m => m.forecastMonth) || {}).forecastMonth;
    $('olForecastMonth').textContent = month ? `Forecast: ${month}` : 'No forecast yet';
    $('olKpiRunoutDesc').textContent = month ? `Stock below ${month} forecast` : 'Run a forecast first';
    $('olCriticalHelp').textContent = DATA.canEditCritical
      ? 'Critical level is the lowest stock a material should ever reach. Click a value to change it.'
      : 'Critical level is the lowest stock a material should ever reach. Only a System Administrator can change it.';
  }

  // Materials table
  function matchesFilter(m) {
    const q = $('olSearch').value.trim().toLowerCase();
    if (q && !(`${m.name} ${m.id} ${m.cat}`.toLowerCase().includes(q))) return false;
    const f = $('olStatusFilter').value;
    if (f === 'Critical' && !(m.status === 'Critical' || m.status === 'Out of Stock')) return false;
    if (f === 'Low' && m.status !== 'Low') return false;
    if (f === 'OK' && m.status !== 'OK') return false;
    if (f === 'runout' && !m.willRunOut) return false;
    if (kpi === 'critical' && !(m.status === 'Critical' || m.status === 'Out of Stock')) return false;
    if (kpi === 'low' && m.status !== 'Low') return false;
    if (kpi === 'runout' && !m.willRunOut) return false;
    return true;
  }

  function criticalCell(m) {
    const val = `${fmt(m.critical)} <span class="text-muted-2 small">${escapeHTML(m.unit)}</span>`;
    if (!DATA.canEditCritical) return `<td>${m.critical > 0 ? val : '<span class="text-muted-2">Not set</span>'}</td>`;
    return `<td><button type="button" class="btn btn-sm btn-light-2 py-0 px-2" data-crit-edit="${escapeHTML(m.id)}">
      ${m.critical > 0 ? val : '<span class="text-muted-2">Set level</span>'} <i class="bi bi-pencil ms-1 small"></i></button></td>`;
  }

  function renderMaterials() {
    const rows = DATA.materials.filter(matchesFilter);
    $('olMatCount').textContent = `${rows.length} of ${DATA.materials.length} materials`;
    if (!rows.length) {
      $('olMatBody').innerHTML = '<tr><td colspan="8" class="text-center text-muted-2 py-4">No materials match.</td></tr>';
      return;
    }
    $('olMatBody').innerHTML = rows.map(m => `<tr data-id="${escapeHTML(m.id)}">
      <td><div class="fw-semibold">${escapeHTML(m.name)}</div><div class="small text-muted-2">${escapeHTML(m.id)} &middot; ${escapeHTML(m.cat)}</div></td>
      <td class="text-end fw-semibold">${fmt(m.qty)} <span class="text-muted-2 small">${escapeHTML(m.unit)}</span></td>
      ${criticalCell(m)}
      <td class="text-end">${fmt(m.reorder)}</td>
      <td><span class="badge ${STATUS_BADGE[m.status] || 'b-neutral'}">${escapeHTML(m.status)}</span></td>
      <td class="text-end">${m.predicted === null ? '<span class="text-muted-2">&mdash;</span>'
        : `${fmt(m.predicted)}${m.willRunOut ? ' <i class="bi bi-graph-down-arrow text-danger" title="Current stock is below the forecast"></i>' : ''}`}</td>
      <td class="text-end">${m.restock ? `<span class="fw-semibold">${fmt(m.restock)}</span>` : (m.restock === 0 ? '0' : '<span class="text-muted-2">&mdash;</span>')}</td>
      <td class="text-end">${m.standbyQty ? `<span class="badge b-danger">${fmt(m.standbyQty)}</span>` : '<span class="text-muted-2">0</span>'}</td>
    </tr>`).join('');
  }

  function openCriticalEditor(id) {
    const m = DATA.materials.find(x => x.id === id);
    const row = $('olMatBody').querySelector(`tr[data-id="${CSS.escape(id)}"]`);
    if (!m || !row) return;
    const cell = row.children[2];
    cell.innerHTML = `<form class="d-flex gap-1" data-crit-form="${escapeHTML(id)}">
      <input type="number" class="form-control form-control-sm" style="max-width:90px" min="0" step="any" value="${m.critical}" required>
      <button type="submit" class="btn btn-sm btn-primary py-0 px-2" title="Save"><i class="bi bi-check-lg"></i></button>
      <button type="button" class="btn btn-sm btn-light-2 py-0 px-2" data-crit-cancel title="Cancel"><i class="bi bi-x-lg"></i></button>
    </form>`;
    const input = cell.querySelector('input');
    input.focus(); input.select();
  }

  async function saveCritical(form) {
    const id = form.dataset.critForm;
    const input = form.querySelector('input');
    const level = Number(input.value);
    if (input.value === '' || isNaN(level) || level < 0) { input.classList.add('is-invalid'); return; }
    form.querySelectorAll('button,input').forEach(el => el.disabled = true);
    try {
      const res = await api('/api/outlook/critical', { id, level });
      const m = DATA.materials.find(x => x.id === id);
      m.critical = res.critical; m.status = res.status;
      recount();
      renderSummary(); renderMaterials();
      showToast(`${m.name}: critical level set to ${NUM(res.critical)} ${m.unit}`, 'success', 'bi-check-circle-fill');
    } catch (err) {
      showToast(err.message, 'danger', 'bi-exclamation-triangle-fill');
      form.querySelectorAll('button,input').forEach(el => el.disabled = false);
    }
  }

  function recount() {
    DATA.summary.critical = DATA.materials.filter(m => m.status === 'Critical' || m.status === 'Out of Stock').length;
    DATA.summary.low = DATA.materials.filter(m => m.status === 'Low').length;
  }

  // Deliveries table
  function weatherText(d) {
    const parts = [];
    if (d.rain !== null && d.rain !== undefined) parts.push(`<i class="bi bi-cloud-rain me-1"></i>${fmt(d.rain)} mm`);
    if (d.temp !== null && d.temp !== undefined) parts.push(`${fmt(d.temp)}&deg;C`);
    if (d.wind !== null && d.wind !== undefined) parts.push(`${fmt(d.wind)} km/h`);
    return parts.length ? `<span class="small">${parts.join(' &middot; ')}</span>` : '<span class="text-muted-2 small">&mdash;</span>';
  }

  function deliveryActions(d) {
    if (!DATA.canManageDeliveries) return '';
    const id = d.movementId;
    if (d.status === 'Pending') return `<div class="d-inline-flex gap-1">
      <button type="button" class="btn btn-sm btn-light-2 py-0 px-2" data-ol-act="deliver" data-mid="${id}"><i class="bi bi-truck me-1"></i>Delivered</button>
      <button type="button" class="btn btn-sm btn-outline-danger py-0 px-2" data-ol-act="fail" data-mid="${id}"><i class="bi bi-x-octagon me-1"></i>Failed</button></div>`;
    if (d.status === 'Standby') return `<div class="d-inline-flex gap-1">
      <button type="button" class="btn btn-sm btn-light-2 py-0 px-2" data-ol-act="redeliver" data-mid="${id}"><i class="bi bi-arrow-repeat me-1"></i>Re-deliver</button>
      <button type="button" class="btn btn-sm btn-outline-secondary py-0 px-2" data-ol-act="return" data-mid="${id}"><i class="bi bi-box-arrow-in-down me-1"></i>Return to inventory</button></div>`;
    return '';
  }

  function renderDeliveries() {
    const all = DATA.deliveries.filter(d => !delTab || d.status === delTab);
    const pages = Math.max(1, Math.ceil(all.length / DEL_PER_PAGE));
    delPage = Math.min(Math.max(1, delPage), pages);
    const rows = all.slice((delPage - 1) * DEL_PER_PAGE, delPage * DEL_PER_PAGE);
    $('olDelCount').textContent = all.length
      ? `Showing ${(delPage - 1) * DEL_PER_PAGE + 1}\u2013${(delPage - 1) * DEL_PER_PAGE + rows.length} of ${all.length}` : '';
    $('olDelPager').innerHTML = pages < 2 ? '' : buildPageWindow(delPage, pages).map(p => p === '\u2026'
      ? '<li class="page-item disabled"><span class="page-link">\u2026</span></li>'
      : `<li class="page-item${p === delPage ? ' active' : ''}"><a class="page-link" href="#" data-page="${p}">${p}</a></li>`).join('');
    if (!rows.length) {
      $('olDelBody').innerHTML = '<tr><td colspan="7" class="text-center text-muted-2 py-4">No deliveries here.</td></tr>';
      return;
    }
    $('olDelBody').innerHTML = rows.map(d => {
      const [cls, icon] = DEL_BADGE[d.status] || ['b-neutral', 'bi-dot'];
      const extra = [];
      if (d.at && d.status !== 'Pending') extra.push(escapeHTML(fmtWhen(d.at)));
      if (d.attempts > 1) extra.push(`${d.attempts} attempts`);
      const reason = d.status === 'Standby' && d.reason
        ? `<div class="small mt-1" title="${escapeHTML(d.reason)}">${escapeHTML(d.reason.length > 60 ? d.reason.slice(0, 60) + '…' : d.reason)}</div>` : '';
      return `<tr>
        <td class="small">MOV-${String(d.movementId).padStart(4, '0')}${d.ref ? `<div class="text-muted-2">${escapeHTML(d.ref)}</div>` : ''}</td>
        <td><div class="fw-semibold">${escapeHTML(d.name)}</div><div class="small text-muted-2">${escapeHTML(d.id)}</div></td>
        <td class="text-end">${fmt(d.qty)} <span class="text-muted-2 small">${escapeHTML(d.unit)}</span></td>
        <td class="small">${escapeHTML(fmtDate(d.date))}</td>
        <td>${weatherText(d)}</td>
        <td><span class="badge ${cls}"><i class="bi ${icon} me-1"></i>${d.status}</span>
          ${extra.length ? `<div class="small text-muted-2 mt-1">${extra.join(' &middot; ')}</div>` : ''}${reason}</td>
        <td class="text-end">${deliveryActions(d)}</td>
      </tr>`;
    }).join('');
  }

  async function deliveryAction(act, mid, btn) {
    const d = DATA.deliveries.find(x => x.movementId === mid);
    if (!d) return;
    if (act === 'fail') {
      failId = mid;
      $('olFailRef').textContent = `MOV-${String(mid).padStart(4, '0')}`;
      $('olFailReason').value = '';
      $('olFailReason').classList.remove('is-invalid');
      bootstrap.Modal.getOrCreateInstance($('olFailModal')).show();
      return;
    }
    const run = async () => {
      if (btn) btn.disabled = true;
      try {
        if (act === 'deliver') await api('/api/inventory/stock-out/deliver', { movementId: mid, status: 'Delivered' });
        if (act === 'redeliver') await api('/api/inventory/stock-out/redeliver', { movementId: mid });
        if (act === 'return') await api('/api/inventory/stock-out/return-to-stock', { movementId: mid });
        const msg = { deliver: 'Marked as Delivered', redeliver: 'Back to Pending for another delivery',
                      return: `${NUM(d.qty)} ${d.unit} of ${d.name} returned to inventory` }[act];
        showToast(msg, 'success', act === 'return' ? 'bi-box-arrow-in-down' : 'bi-truck');
        await load();
      } catch (err) {
        showToast(err.message, 'danger', 'bi-exclamation-triangle-fill');
        if (btn) btn.disabled = false;
      }
    };
    if (act === 'return') {
      confirmDelete(`Return ${NUM(d.qty)} ${d.unit} of ${d.name} to inventory? This Stock Out will no longer count as used.`, run,
        { title: 'Return to Inventory', button: 'Return' });
      return;
    }
    run();
  }

  // Delivery risk
  function riskCard(label, r) {
    if (!r || !r.weather) return `<div class="col-md-6"><div class="p-3 rounded border h-100">
      <div class="small text-muted-2 mb-1">${label}</div><div class="text-muted-2">Weather not available.</div></div></div>`;
    const w = r.weather;
    const basis = r.basis === 'history'
      ? `${r.failureRate}% of ${r.samples} past deliveries in ${r.bucket.toLowerCase()} weather failed.`
      : `Not enough past deliveries in ${r.bucket.toLowerCase()} weather yet (${r.samples}), so this is based on the weather alone.`;
    return `<div class="col-md-6"><div class="p-3 rounded border h-100">
      <div class="d-flex justify-content-between align-items-start mb-2">
        <div><div class="small text-muted-2">${label} &middot; ${escapeHTML(fmtDate(r.date + 'T00:00:00'))}</div>
          <div class="fw-semibold">${escapeHTML(r.bucket)}</div></div>
        <span class="badge ${RISK_BADGE[r.risk] || 'b-neutral'}">${escapeHTML(r.risk || '?')} risk</span>
      </div>
      <div class="small mb-2"><i class="bi bi-cloud-rain me-1"></i>${fmt(w.rainfall_mm)} mm
        &middot; <i class="bi bi-thermometer-half"></i>${fmt(w.temp_c)}&deg;C
        ${w.wind_kmh !== undefined && w.wind_kmh !== null ? `&middot; <i class="bi bi-wind"></i> ${fmt(w.wind_kmh)} km/h` : ''}</div>
      <div class="small text-muted-2">${basis}${w.wind_kmh >= 50 ? ' Strong wind raises the risk.' : ''}</div>
    </div></div>`;
  }

  async function loadRisk() {
    try {
      const r = await api('/api/outlook/delivery-risk');
      $('olRiskCards').innerHTML = riskCard('Today', r.today) + riskCard('Tomorrow', r.tomorrow);
      $('olRiskHistory').innerHTML = r.history.map(h => `<tr>
        <td>${escapeHTML(h.bucket)}</td><td class="text-end">${NUM(h.deliveries)}</td>
        <td class="text-end">${h.deliveries ? `${NUM(h.failed)} <span class="text-muted-2 small">(${h.failureRate}%)</span>` : '<span class="text-muted-2">&mdash;</span>'}</td>
      </tr>`).join('');
    } catch (err) {
      $('olRiskCards').innerHTML = `<div class="col-12"><div class="text-muted-2">${escapeHTML(err.message)}</div></div>`;
    }
  }

  async function load() {
    try {
      DATA = await api('/api/outlook');
      renderSummary(); renderMaterials(); renderDeliveries();
    } catch (err) {
      $('olMatBody').innerHTML = `<tr><td colspan="8" class="text-center text-muted-2 py-4">${escapeHTML(err.message)}</td></tr>`;
      $('olDelBody').innerHTML = '<tr><td colspan="7" class="text-center text-muted-2 py-4">&mdash;</td></tr>';
    }
  }

  // Events
  window.onKpiFilter = (key) => {
    if (key === 'standby') {
      kpi = null;
      setDelTab('Standby');
      renderMaterials();
      setTimeout(() => $('olDeliveries').scrollIntoView({ behavior: 'smooth', block: 'start' }), 60);
      return;
    }
    kpi = key;
    renderMaterials();
    if (key) setTimeout(() => $('olMatBody').closest('.card').scrollIntoView({ behavior: 'smooth', block: 'start' }), 60);
  };

  function setDelTab(tab) {
    delTab = tab;
    delPage = 1;
    document.querySelectorAll('#olDelTabs [data-tab]').forEach(b => b.classList.toggle('active', b.dataset.tab === tab));
    renderDeliveries();
  }

  $('olSearch').addEventListener('input', renderMaterials);
  $('olStatusFilter').addEventListener('change', () => {
    kpi = null;
    if (typeof window.clearKpiSelection === 'function') window.clearKpiSelection();
    renderMaterials();
  });
  $('olDelTabs').addEventListener('click', (e) => {
    const b = e.target.closest('[data-tab]');
    if (b) setDelTab(b.dataset.tab);
  });

  $('olDelPager').addEventListener('click', (e) => {
    const a = e.target.closest('[data-page]');
    if (!a) return;
    e.preventDefault();
    delPage = parseInt(a.dataset.page, 10);
    renderDeliveries();
  });

  $('olMatBody').addEventListener('click', (e) => {
    const edit = e.target.closest('[data-crit-edit]');
    if (edit) { openCriticalEditor(edit.dataset.critEdit); return; }
    if (e.target.closest('[data-crit-cancel]')) renderMaterials();
  });
  $('olMatBody').addEventListener('submit', (e) => {
    const form = e.target.closest('[data-crit-form]');
    if (form) { e.preventDefault(); saveCritical(form); }
  });
  $('olMatBody').addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && e.target.closest('[data-crit-form]')) renderMaterials();
  });

  $('olDelBody').addEventListener('click', (e) => {
    const b = e.target.closest('[data-ol-act]');
    if (b) deliveryAction(b.dataset.olAct, parseInt(b.dataset.mid, 10), b);
  });

  $('olFailForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    const reason = $('olFailReason').value.trim();
    if (!reason) { $('olFailReason').classList.add('is-invalid'); return; }
    const btn = $('olFailSubmit');
    btn.disabled = true;
    try {
      await api('/api/inventory/stock-out/deliver', { movementId: failId, status: 'Failed', reason });
      bootstrap.Modal.getOrCreateInstance($('olFailModal')).hide();
      showToast('Delivery failed. Materials are on standby.', 'warning', 'bi-x-octagon');
      await load();
      loadRisk();
    } catch (err) {
      showToast(err.message, 'danger', 'bi-exclamation-triangle-fill');
    } finally {
      btn.disabled = false;
    }
  });

  load();
  loadRisk();
})();
