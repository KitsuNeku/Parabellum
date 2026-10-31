/* Suppliers page */
document.addEventListener('DOMContentLoaded', () => {
  const tb          = document.getElementById('supBody');
  const head        = document.getElementById('supHead');
  const supForm     = document.getElementById('supForm');
  const supModal    = new bootstrap.Modal('#addSupModal');
  const detailModal = new bootstrap.Modal('#supDetailModal');
  const statusModal = new bootstrap.Modal('#supStatusModal');
  let currentDetailId = null;

  /* Lookups */
  const materialsOf = (s) => s.materials || [];
  const isActive = (s) => s.status === 'Active';
  const fmtDate = (d) => d ? String(d).slice(0, 10) : '—';

  document.getElementById('supCategoryFilter').innerHTML =
    '<option value="">All Categories</option>' + SUPPLIER_CATEGORIES.map(c => `<option>${escapeHTML(c)}</option>`).join('');
  document.getElementById('supFormCategory').innerHTML =
    SUPPLIER_CATEGORIES.map(c => `<option>${escapeHTML(c)}</option>`).join('');
  document.getElementById('supFormTerms').innerHTML =
    SUPPLIER_TERMS.map(t => `<option ${t === 'Net 30' ? 'selected' : ''}>${escapeHTML(t)}</option>`).join('');

  const COLS = [
    { key:'id',        label:'Supplier ID' },
    { key:'name',      label:'Supplier / Company Name' },
    { key:'contact',   label:'Contact Person' },
    { key:'phone',     label:'Contact Number' },
    { key:'email',     label:'Email Address' },
    { key:'addr',      label:'Business Address' },
    { key:'category',  label:'Category / Type' },
    { key:'materials', label:'Materials Supplied', sortable:false },
    { key:'count',     label:'No. of Materials', cls:'text-center' },
    { key:'status',    label:'Status' },
    { key:'dateAdded', label:'Date Added' },
    { key:'remarks',   label:'Remarks', sortable:false },
    { key:'actions',   label:'Actions', sortable:false, cls:'text-center' },
  ];
  const view = { q:'', status:'', category:'', withMaterials:false, sortKey:'id', sortDir:'asc' };

  function renderHead(){
    head.innerHTML = COLS.map(c => {
      if (c.sortable === false) return `<th class="${c.cls || ''}" style="white-space:nowrap">${c.label}</th>`;
      const on = view.sortKey === c.key;
      const icon = on ? (view.sortDir === 'asc' ? 'bi-caret-up-fill' : 'bi-caret-down-fill') : 'bi-chevron-expand';
      return `<th class="${c.cls || ''}" style="white-space:nowrap" aria-sort="${on ? (view.sortDir === 'asc' ? 'ascending' : 'descending') : 'none'}">
        <button type="button" class="btn btn-link p-0 text-reset text-decoration-none" style="font:inherit;letter-spacing:inherit;text-transform:inherit" data-sort="${c.key}">
          ${c.label} <i class="bi ${icon} ms-1" style="opacity:${on ? 1 : .5}"></i></button></th>`;
    }).join('');
  }
  head.addEventListener('click', (e) => {
    const b = e.target.closest('[data-sort]'); if (!b) return;
    if (view.sortKey === b.dataset.sort) view.sortDir = view.sortDir === 'asc' ? 'desc' : 'asc';
    else { view.sortKey = b.dataset.sort; view.sortDir = 'asc'; }
    renderSuppliers();
  });

  function supActionBtns(s){
    const toggle = isActive(s)
      ? `<button class="act-btn danger" data-bs-toggle="tooltip" title="Deactivate" data-act="deactivate" data-id="${escapeHTML(s.id)}" aria-label="Deactivate ${escapeHTML(s.name)}"><i class="bi bi-slash-circle"></i></button>`
      : `<button class="act-btn" data-bs-toggle="tooltip" title="Reactivate" data-act="reactivate" data-id="${escapeHTML(s.id)}" aria-label="Reactivate ${escapeHTML(s.name)}"><i class="bi bi-arrow-counterclockwise"></i></button>`;
    return `<div class="d-inline-flex">
        <button class="act-btn" data-bs-toggle="tooltip" title="View" data-act="view" data-id="${escapeHTML(s.id)}" aria-label="View ${escapeHTML(s.name)}"><i class="bi bi-eye"></i></button>
        <button class="act-btn" data-bs-toggle="tooltip" title="Edit" data-act="edit" data-id="${escapeHTML(s.id)}" aria-label="Edit ${escapeHTML(s.name)}"><i class="bi bi-pencil"></i></button>
        ${toggle}
      </div>`;
  }

  function materialsSummary(mats){
    if (!mats.length) return '<span class="text-muted-2">—</span>';
    const names = mats.map(m => m.name);
    const shown = names.slice(0, 2).map(escapeHTML).join(', ');
    const more = names.length > 2 ? ` <span class="text-muted-2">+${names.length - 2} more</span>` : '';
    return `<span title="${escapeHTML(names.join(', '))}">${shown}${more}</span>`;
  }

  function renderSuppliers(){
    const all = supplierStore.all();
    const setStat = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v; };
    setStat('supStatTotal', all.length);
    setStat('supStatActive', all.filter(isActive).length);
    setStat('supStatInactive', all.filter(s => !isActive(s)).length);
    setStat('supStatMaterials', all.reduce((n, s) => n + materialsOf(s).length, 0));

    const q = view.q;
    const rows = all.map(s => ({ s, mats: materialsOf(s) })).filter(({ s, mats }) => {
      if (view.status && !view.status.split('|').includes(s.status)) return false;
      if (view.withMaterials && !mats.length) return false;
      if (view.category && s.category !== view.category) return false;
      if (q) {
        const hay = [s.id, s.name, s.contact, s.phone, s.email, s.addr, s.category, s.status, s.remarks, ...mats.map(m => m.name)]
          .join(' ').toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });
    const val = ({ s, mats }) => view.sortKey === 'count' ? mats.length : String(s[view.sortKey] ?? '').toLowerCase();
    rows.sort((a, b) => {
      const x = val(a), y = val(b);
      const r = typeof x === 'number' ? x - y : x.localeCompare(y, 'en', { numeric: true });
      return view.sortDir === 'asc' ? r : -r;
    });

    renderHead();
    tb.innerHTML = rows.length ? rows.map(({ s, mats }) => `<tr>
        <td class="fw-id" style="white-space:nowrap">${escapeHTML(s.id)}</td>
        <td class="fw-medium" style="min-width:160px">${escapeHTML(s.name)}</td>
        <td style="white-space:nowrap">${escapeHTML(s.contact || '—')}</td>
        <td style="white-space:nowrap">${escapeHTML(s.phone || '—')}</td>
        <td class="text-muted-2">${escapeHTML(s.email || '—')}</td>
        <td class="text-muted-2" style="min-width:150px">${escapeHTML(s.addr || '—')}</td>
        <td style="min-width:150px">${escapeHTML(s.category || '—')}</td>
        <td style="min-width:200px">${materialsSummary(mats)}</td>
        <td class="text-center"><span class="badge b-info">${mats.length}</span></td>
        <td>${supplierStatusBadge(s.status)}</td>
        <td class="text-muted-2" style="white-space:nowrap">${fmtDate(s.dateAdded)}</td>
        <td class="text-muted-2"><div class="text-truncate" style="max-width:180px" title="${escapeHTML(s.remarks || '')}">${escapeHTML(s.remarks || '—')}</div></td>
        <td class="text-center">${supActionBtns(s)}</td></tr>`).join('')
      : `<tr><td colspan="${COLS.length}" class="text-center text-muted-2 py-4">No suppliers match your search or filters.</td></tr>`;
    const el = document.getElementById('supCount');
    if (el) el.textContent = rows.length === all.length
      ? `Showing ${all.length} supplier${all.length === 1 ? '' : 's'}`
      : `Showing ${rows.length} of ${all.length} suppliers`;
    initTooltips(tb);
    if (currentDetailId && document.getElementById('supDetailModal').classList.contains('show')) {
      const s = supplierStore.find(currentDetailId); if (s) fillDetail(s);
    }
  }
  window.renderSuppliers = renderSuppliers;

  document.getElementById('supSearch').addEventListener('input', (e) => { view.q = e.target.value.toLowerCase().trim(); renderSuppliers(); });
  document.getElementById('supStatusFilter').addEventListener('change', (e) => { view.status = e.target.value; view.withMaterials = false; window.clearKpiSelection?.(); renderSuppliers(); });
  window.onKpiFilter = (key) => {
    const sel = document.getElementById('supStatusFilter');
    view.status = key === 'active' ? 'Active' : key === 'inactive' ? 'Inactive|Archived' : '';
    view.withMaterials = key === 'materials';
    sel.value = view.status;
    renderSuppliers();
  };
  document.getElementById('supCategoryFilter').addEventListener('change', (e) => { view.category = e.target.value; renderSuppliers(); });

  function fillDetail(s){
    const mats = materialsOf(s);
    const initials = escapeHTML(String(s.name || '?').split(/\s+/).map(w => w[0]).slice(0, 2).join('').toUpperCase());
    const info = (label, v, col = 'col-md-4 col-6') => `<div class="${col}"><div class="text-muted-2">${label}</div><div class="fw-medium">${v}</div></div>`;
    document.getElementById('supDetailBody').innerHTML = `
      <div class="d-flex align-items-center gap-3 mb-3">
        <div class="avatar-sm" style="width:54px;height:54px;font-size:1.1rem;">${initials}</div>
        <div><h5 class="mb-1">${escapeHTML(s.name)}</h5>
          <div class="d-flex align-items-center gap-2"><span class="fw-id small">${escapeHTML(s.id)}</span>${supplierStatusBadge(s.status)}</div></div>
      </div>
      <div class="row g-3 small mb-4">
        ${info('Contact Person', escapeHTML(s.contact || '—'))}
        ${info('Contact Number', escapeHTML(s.phone || '—'))}
        ${info('Email Address', escapeHTML(s.email || '—'))}
        ${info('Business Address', escapeHTML(s.addr || '—'))}
        ${info('Category / Type', escapeHTML(s.category || '—'))}
        ${info('Payment Terms', escapeHTML(s.terms || '—'))}
        ${info('Date Added', fmtDate(s.dateAdded))}
        ${info('Remarks', escapeHTML(s.remarks || '—'), 'col-md-8 col-12')}
      </div>

      <div class="d-flex justify-content-between align-items-center mb-2">
        <h6 class="panel-title mb-0">Materials Supplied</h6><span class="badge b-neutral">${mats.length} item${mats.length === 1 ? '' : 's'}</span>
      </div>
      <div class="table-wrap mb-0"><table class="table table-soft mb-0">
        <thead><tr><th>Material ID</th><th>Material Name</th><th>Category</th><th>Unit</th><th class="text-end">Current Stock</th>
          <th class="text-end">Unit Cost</th><th class="text-end">Reorder Level</th><th>Location</th><th>Stock Status</th></tr></thead>
        <tbody>${mats.length ? mats.map(i => `<tr>
            <td class="fw-id">${escapeHTML(i.id)}</td><td class="fw-medium">${escapeHTML(i.name)}</td><td>${escapeHTML(i.cat)}</td>
            <td>${escapeHTML(i.unit)}</td><td class="text-end">${NUM(i.qty)}</td><td class="text-end">${PESO(i.price)}</td>
            <td class="text-end">${NUM(i.reorder)}</td><td>${escapeHTML(i.loc)}</td><td>${stockBadge(escapeHTML(i.status))}</td></tr>`).join('')
          : '<tr><td colspan="9" class="text-center text-muted-2 py-3">No inventory items are linked to this supplier yet. Set this supplier on the item in Inventory.</td></tr>'}</tbody>
      </table></div>`;
    const btn = document.getElementById('sdStatusBtn');
    btn.innerHTML = isActive(s) ? '<i class="bi bi-slash-circle me-1"></i>Deactivate' : '<i class="bi bi-arrow-counterclockwise me-1"></i>Reactivate';
  }
  function openDetail(s){ currentDetailId = s.id; fillDetail(s); detailModal.show(); }

  /* Add / Edit */
  const idInput   = document.getElementById('supFormId');
  const nameInput = document.getElementById('supFormName');
  function validateUnique(){
    const editId = supForm.getAttribute('data-edit-id');
    const nm = nameInput.value.trim().toLowerCase();
    const dup = nm && (SUPPLIERS || []).find(s => s.id !== editId && String(s.name).trim().toLowerCase() === nm);
    nameInput.setCustomValidity(dup ? 'duplicate' : '');
    document.getElementById('supNameFeedback').textContent = dup ? `${dup.name} is already registered (${dup.id}).` : 'Required.';
  }
  nameInput.addEventListener('input', validateUnique);
  supForm.addEventListener('submit', validateUnique, true);

  document.getElementById('addSupModal').addEventListener('show.bs.modal', () => {
    if (!supForm.hasAttribute('data-edit-id')) {
      supForm.reset();
      supForm.classList.remove('was-validated');
      idInput.value = nextId('SUP-', SUPPLIERS);
    }
    validateUnique();
  });
  function openEdit(s){
    supForm.setAttribute('data-edit-id', s.id);
    document.getElementById('supModalTitle').textContent = 'Edit Supplier';
    document.getElementById('supModalSubmit').textContent = 'Save Changes';
    const f = supForm.elements;
    f.id.value = s.id; f.name.value = s.name || ''; f.contact.value = s.contact || ''; f.phone.value = s.phone || '';
    f.email.value = s.email || ''; f.addr.value = s.addr || ''; f.category.value = s.category || '';
    f.terms.value = s.terms || SUPPLIER_TERMS[0]; f.status.value = s.status || 'Active'; f.remarks.value = s.remarks || '';
    supModal.show();
  }
  document.getElementById('addSupModal').addEventListener('hidden.bs.modal', () => {
    supForm.removeAttribute('data-edit-id');
    document.getElementById('supModalTitle').textContent = 'Add Supplier';
    document.getElementById('supModalSubmit').textContent = 'Save Supplier';
  });

  let pendingStatus = null;
  function askStatusChange(s){
    const toActive = !isActive(s);
    pendingStatus = { id: s.id, status: toActive ? 'Active' : 'Inactive' };
    const n = materialsOf(s).length;
    document.getElementById('supStatusTitle').textContent = toActive ? 'Reactivate Supplier' : 'Deactivate Supplier';
    document.getElementById('supStatusMsg').textContent = toActive
      ? `Reactivate ${s.name} (${s.id})? It will be available again when adding items and recording Stock In.`
      : `Deactivate ${s.name} (${s.id})? It won't be offered for new items or Stock In. Its ${n} linked material${n === 1 ? '' : 's'} and all past Stock In records stay unchanged.`;
    document.getElementById('supStatusConfirm').textContent = toActive ? 'Reactivate' : 'Deactivate';
    statusModal.show();
  }
  document.getElementById('supStatusConfirm').addEventListener('click', async () => {
    if (!pendingStatus) return;
    const s = supplierStore.find(pendingStatus.id); if (!s) return;
    const next = pendingStatus.status;
    statusModal.hide();
    try {
      if (typeof window.saveSupplierRecord === 'function') await window.saveSupplierRecord({ ...s, status: next });
      else { supplierStore.update(s.id, { status: next }); renderSuppliers(); }
      showToast(`${s.name} ${next === 'Active' ? 'reactivated' : 'deactivated'}`, 'success');
    } catch (err) {
      showToast(err.message || 'Could not update the supplier.', 'error', 'bi-exclamation-triangle');
    }
  });

  /* Row + detail-modal actions */
  tb.addEventListener('click', (e) => {
    const btn = e.target.closest('[data-act]'); if (!btn) return;
    const s = supplierStore.find(btn.dataset.id); if (!s) return;
    bootstrap.Tooltip.getInstance(btn)?.hide();
    if (btn.dataset.act === 'view') openDetail(s);
    if (btn.dataset.act === 'edit') openEdit(s);
    if (btn.dataset.act === 'deactivate' || btn.dataset.act === 'reactivate') askStatusChange(s);
  });
  document.getElementById('sdEditBtn').addEventListener('click', () => {
    const s = supplierStore.find(currentDetailId); if (!s) return;
    detailModal.hide(); openEdit(s);
  });
  document.getElementById('sdStatusBtn').addEventListener('click', () => {
    const s = supplierStore.find(currentDetailId); if (!s) return;
    detailModal.hide(); askStatusChange(s);
  });

  document.addEventListener('entity:submit', (e) => {
    const { entity, data, editId } = e.detail;
    if (entity !== 'suppliers') return;
    const rec = { name:data.name.trim(), contact:(data.contact||'').trim(), phone:(data.phone||'').trim(),
                  email:(data.email||'').trim(), addr:(data.addr||'').trim(), category:data.category,
                  terms:data.terms, status:data.status, remarks:(data.remarks||'').trim() };
    if (editId) supplierStore.update(editId, rec);
    else supplierStore.add({ id: SUPPLIERS.some(s => s.id === data.id) ? nextId('SUP-', SUPPLIERS) : data.id,
                             dateAdded: new Date().toISOString().slice(0, 10), ...rec });
    renderSuppliers();
  });

  renderSuppliers();
});
