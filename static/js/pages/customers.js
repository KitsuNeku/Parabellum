/* Customers page */
document.addEventListener('DOMContentLoaded', () => {
  const tb = document.getElementById('custBody');
  const detailModal = new bootstrap.Modal('#custDetailModal');
  const custForm  = document.getElementById('custForm');
  const custModal = new bootstrap.Modal('#addCustModal');
  let currentDetailId = null;

  const view = { q: '', status: '' };

  function renderCustomers(){
    const all = customerStore.all();
    const setStat = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v; };
    setStat('custStatTotal', all.length);
    setStat('custStatActive', all.filter(c => c.status === 'Active').length);
    setStat('custStatHold', all.filter(c => c.status === 'On Hold').length);
    setStat('custStatProjects', all.reduce((sum, c) => sum + (Number(c.projects) || 0), 0));
    const list = all.filter(c => {
      if (view.status && c.status !== view.status) return false;
      if (view.q && ![c.id, c.name, c.contact, c.phone, c.email].join(' ').toLowerCase().includes(view.q)) return false;
      return true;
    });
    tb.innerHTML = list.length ? '' : '<tr><td colspan="8" class="text-center text-muted-2 py-4">No customers match the current filter.</td></tr>';
    list.forEach(c => {
      tb.insertAdjacentHTML('beforeend', `<tr>
        <td class="fw-id">${c.id}</td>
        <td><div class="fw-medium">${escapeHTML(c.name)}</div><div class="small text-muted-2">${escapeHTML(c.contact)}</div></td>
        <td>${escapeHTML(c.phone)}</td><td class="text-muted-2">${escapeHTML(c.email)}</td>
        <td>${custStatusBadge(c.status)}</td>
        <td class="text-center"><span class="badge b-info">${c.projects}</span></td>
        <td class="text-center"><span class="badge b-neutral">${c.txns}</span></td>
        <td class="text-center">${actionBtns(c.id)}</td></tr>`);
    });
    const el = document.getElementById('custCount');
    if (el) el.textContent = list.length === all.length
      ? `Showing ${all.length} customer${all.length===1?'':'s'}`
      : `Showing ${list.length} of ${all.length} customers`;
    initTooltips(tb);
  }
  window.renderCustomers = renderCustomers;

  function openDetail(c){
    currentDetailId = c.id;
    document.getElementById('custDetailBody').innerHTML = `
      <div class="d-flex align-items-center gap-3 mb-3">
        <div class="avatar-sm" style="width:54px;height:54px;font-size:1.1rem;">${escapeHTML(c.name.split(' ').map(w=>w[0]).slice(0,2).join(''))}</div>
        <div><h5 class="mb-0">${escapeHTML(c.name)}</h5>${custStatusBadge(c.status)}</div></div>
      <div class="row g-2 small">
        <div class="col-6"><div class="text-muted-2">Customer ID</div><div class="fw-medium">${c.id}</div></div>
        <div class="col-6"><div class="text-muted-2">Contact Person</div><div class="fw-medium">${escapeHTML(c.contact)}</div></div>
        <div class="col-6"><div class="text-muted-2">Phone</div><div class="fw-medium">${escapeHTML(c.phone)}</div></div>
        <div class="col-6"><div class="text-muted-2">Email</div><div class="fw-medium">${escapeHTML(c.email)}</div></div>
        <div class="col-12"><div class="text-muted-2">Address</div><div class="fw-medium">${escapeHTML(c.addr)}</div></div>
        <div class="col-6"><div class="text-muted-2">Projects</div><div class="fw-medium">${c.projects}</div></div>
        <div class="col-6"><div class="text-muted-2">Transactions</div><div class="fw-medium">${c.txns}</div></div>
      </div>`;
    detailModal.show();
  }

  function openEdit(c){
    custForm.setAttribute('data-edit-id', c.id);
    document.getElementById('custModalTitle').textContent = 'Edit Customer';
    document.getElementById('custModalSubmit').textContent = 'Save Changes';
    const f = custForm.elements;
    f.name.value = c.name; f.contact.value = c.contact; f.phone.value = c.phone;
    f.email.value = c.email; f.addr.value = c.addr; f.status.value = c.status;
    custModal.show();
  }
  document.getElementById('addCustModal').addEventListener('hidden.bs.modal', () => {
    custForm.removeAttribute('data-edit-id');
    document.getElementById('custModalTitle').textContent = 'Add Customer';
    document.getElementById('custModalSubmit').textContent = 'Save Customer';
  });

  tb.addEventListener('click', (e) => {
    const btn = e.target.closest('[data-act]'); if (!btn) return;
    const c = customerStore.find(btn.dataset.id); if (!c) return;
    if (btn.dataset.act === 'view') openDetail(c);
    if (btn.dataset.act === 'edit') openEdit(c);
    if (btn.dataset.act === 'del')
      confirmDelete(`Delete customer "${c.name}" (${c.id})? This cannot be undone.`, () => {
        customerStore.remove(c.id); renderCustomers();
        showToast(`${c.name} deleted`, 'success', 'bi-trash');
      });
  });
  document.getElementById('cdEditBtn').addEventListener('click', () => {
    const c = customerStore.find(currentDetailId); if (!c) return;
    detailModal.hide(); openEdit(c);
  });

  document.addEventListener('entity:submit', (e) => {
    const { entity, data, editId } = e.detail;
    if (entity !== 'customers') return;
    const rec = { name:data.name.trim(), contact:data.contact.trim(), phone:data.phone.trim(),
                  email:data.email.trim(), addr:(data.addr||'').trim(), status:data.status };
    if (editId) customerStore.update(editId, rec);
    else customerStore.add({ id:nextId('CUS-', CUSTOMERS), projects:0, txns:0, ...rec });
    renderCustomers();
  });

  renderCustomers();
  window.renderCustomers = renderCustomers;
  document.getElementById('custSearch').addEventListener('input', (e) => { view.q = e.target.value.toLowerCase().trim(); renderCustomers(); });
  document.getElementById('custStatusFilter').addEventListener('change', (e) => { view.status = e.target.value; window.clearKpiSelection?.(); renderCustomers(); });
  window.onKpiFilter = (key) => {
    view.status = key === 'active' ? 'Active' : key === 'hold' ? 'On Hold' : '';
    document.getElementById('custStatusFilter').value = view.status;
    renderCustomers();
  };
});
