/* Projects page */
document.addEventListener('DOMContentLoaded', () => {
  const tb  = document.getElementById('projBody');
  const gal = document.getElementById('projGallery');
  const projForm  = document.getElementById('projForm');
  const projModal = new bootstrap.Modal('#addProjModal');

  const PROJ_PAGE_SIZE = 10;
  let projCurrentPage = 1;
  let projSearchQuery = '';
  let projStatusFilterVal = '';
  let projPriorityFilterVal = '';
  let projSortByBudget = false;

  const searchInput    = document.getElementById('projSearchInput');
  const statusFilterEl = document.getElementById('projStatusFilter');
  const priorityFilterEl = document.getElementById('projPriorityFilter');
  searchInput?.addEventListener('input', () => {
    projSearchQuery = searchInput.value.toLowerCase().trim();
    projCurrentPage = 1;
    renderProjects();
  });
  statusFilterEl?.addEventListener('change', () => {
    projStatusFilterVal = statusFilterEl.value;
    projSortByBudget = false;
    window.clearKpiSelection?.();
    projCurrentPage = 1;
    renderProjects();
  });
  window.onKpiFilter = (key) => {
    projStatusFilterVal = key === 'active' ? 'In Progress' : key === 'hold' ? 'On Hold' : '';
    projSortByBudget = key === 'budget';
    if (statusFilterEl) statusFilterEl.value = projStatusFilterVal;
    projCurrentPage = 1;
    renderProjects();
  };
  priorityFilterEl?.addEventListener('change', () => {
    projPriorityFilterVal = priorityFilterEl.value;
    projCurrentPage = 1;
    renderProjects();
  });

  document.getElementById('projCustSelect').innerHTML = ''+
    CUSTOMERS.map(c => `<option value="${c.id}">${escapeHTML(c.name)}</option>`).join('');
  document.getElementById('projStaffSelect').innerHTML =
    EMPLOYEES.map(e2 => `<option value="${e2.id}">${escapeHTML(e2.name)}</option>`).join('');

  function renderProjPaginationControls(totalItems){
    const totalPages = Math.max(1, Math.ceil(totalItems / PROJ_PAGE_SIZE));
    if (projCurrentPage > totalPages) projCurrentPage = totalPages;
    const nav = document.getElementById('projPaginationNav');
    const ul  = document.getElementById('projPagination');
    if (!nav || !ul) return;
    if (totalPages <= 1) { nav.style.display = 'none'; return; }
    nav.style.display = '';
    const pageLink = (label, page, opts = {}) => `
      <li class="page-item ${opts.active ? 'active' : ''} ${opts.disabled ? 'disabled' : ''}">
        <a class="page-link" href="#" data-page="${page}">${label}</a>
      </li>`;
    let html = pageLink('<i class="bi bi-chevron-left"></i>', projCurrentPage - 1, { disabled: projCurrentPage === 1 });
    buildPageWindow(projCurrentPage, totalPages).forEach(p => {
      if (p === '\u2026') html += `<li class="page-item disabled"><span class="page-link">\u2026</span></li>`;
      else html += pageLink(p, p, { active: p === projCurrentPage });
    });
    html += pageLink('Next <i class="bi bi-chevron-right ms-1"></i>', projCurrentPage + 1, { disabled: projCurrentPage === totalPages });
    ul.innerHTML = html;
  }

  document.getElementById('projPagination')?.addEventListener('click', (e) => {
    const link = e.target.closest('[data-page]');
    if (!link || link.closest('.disabled')) return;
    e.preventDefault();
    const page = parseInt(link.dataset.page, 10);
    if (!page || page === projCurrentPage) return;
    projCurrentPage = page;
    renderProjects();
    document.getElementById('projTableView')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  });

  function renderFeatured(fullList){
    const box = document.getElementById('projFeatured');
    if (!box) return;
    const active = fullList.filter(p => p.status === 'In Progress');
    if (!active.length) { box.style.display = 'none'; return; }
    const p = active.reduce((a, b) => (Number(b.budget) || 0) > (Number(a.budget) || 0) ? b : a);
    const fmt = (d) => d ? new Date(d + 'T00:00:00').toLocaleDateString('en-PH', { year:'numeric', month:'short', day:'numeric' }) : 'Not set';
    let dueLine = fmt(p.due), dueCls = 'gold';
    if (p.due) {
      const days = Math.ceil((new Date(p.due + 'T00:00:00') - new Date(new Date().toDateString())) / 86400000);
      dueLine += days >= 0 ? ` \u00b7 ${days} day${days === 1 ? '' : 's'} left` : ` \u00b7 ${-days} day${days === -1 ? '' : 's'} overdue`;
    }
    document.getElementById('projFeatTitle').textContent = `Project Timeline \u2014 ${p.name} (${p.id})`;
    document.getElementById('projFeatSub').textContent = `${p.cust} \u00b7 Assigned: ${p.staff} \u00b7 Budget ${PESO(Number(p.budget) || 0)}`;
    document.getElementById('projFeatTimeline').innerHTML = `
      <div class="timeline-item done"><div class="fw-medium">Project Start</div><div class="small text-muted-2">${escapeHTML(fmt(p.start))}</div></div>
      <div class="timeline-item"><div class="fw-medium">Current Progress</div><div class="small text-muted-2">${Number(p.progress) || 0}% complete \u00b7 In Progress</div></div>
      <div class="timeline-item ${dueCls}"><div class="fw-medium">Target Completion</div><div class="small text-muted-2">${escapeHTML(dueLine)}</div></div>`;
    box.style.display = '';
  }

  function renderProjects(){
    const fullList = projectStore.all();
    renderFeatured(fullList);
    const setStat = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v; };
    const totalBudget = fullList.reduce((sum, p) => sum + (Number(p.budget) || 0), 0);
    const compactPeso = (n) => n >= 1e6 ? `\u20b1${(n/1e6).toFixed(1)}M`
                             : n >= 1e3 ? `\u20b1${(n/1e3).toFixed(1)}K` : PESO(n);
    setStat('projStatTotal', fullList.length);
    setStat('projStatActive', fullList.filter(p => p.status === 'In Progress').length);
    setStat('projStatHold', fullList.filter(p => p.status === 'On Hold').length);
    setStat('projStatBudget', compactPeso(totalBudget));

    const list = fullList.filter(p => {
      if (projStatusFilterVal && p.status !== projStatusFilterVal) return false;
      if (projPriorityFilterVal && p.priority !== projPriorityFilterVal) return false;
      if (projSearchQuery) {
        const hay = `${p.id} ${p.name} ${p.cust}`.toLowerCase();
        if (!hay.includes(projSearchQuery)) return false;
      }
      return true;
    });
    if (projSortByBudget) list.sort((a, b) => (Number(b.budget) || 0) - (Number(a.budget) || 0));

    const start = (projCurrentPage - 1) * PROJ_PAGE_SIZE;
    const pageItems = list.slice(start, start + PROJ_PAGE_SIZE);

    tb.innerHTML = ''; gal.innerHTML = '';
    if (pageItems.length === 0) {
      tb.insertAdjacentHTML('beforeend', `<tr><td colspan="9" class="text-center text-muted-2 py-4">
        No projects match your search or filters.</td></tr>`);
      gal.insertAdjacentHTML('beforeend', `<div class="col-12 text-center text-muted-2 py-4">
        No projects match your search or filters.</div>`);
    }
    pageItems.forEach(p => {
      tb.insertAdjacentHTML('beforeend', `<tr>
        <td class="fw-id">${p.id}</td><td class="fw-medium">${escapeHTML(p.name)}</td><td>${escapeHTML(p.cust)}</td>
        <td class="text-muted-2">${escapeHTML(p.staff)}</td><td>${projStatusBadge(p.status)}</td>
        <td>${priorityBadge(p.priority)}</td><td>${progressBar(p.progress)}</td>
        <td class="text-muted-2">${p.due}</td><td class="text-center">${actionBtns(p.id)}</td></tr>`);

      gal.insertAdjacentHTML('beforeend', `
        <div class="col-md-6 col-xl-4">
          <div class="proj-card">
            <div class="pc-head">
              <div><div class="pc-name">${escapeHTML(p.name)}</div><div class="pc-id">${p.id}</div></div>
              ${priorityBadge(p.priority)}
            </div>
            <div class="pc-cust"><i class="bi bi-building me-1"></i>${escapeHTML(p.cust)}</div>
            <div class="d-flex align-items-center gap-2 mb-2">${projStatusBadge(p.status)}<span class="small text-muted-2"><i class="bi bi-person me-1"></i>${escapeHTML(p.staff)}</span></div>
            ${progressBar(p.progress)}
            <div class="pc-meta">
              <span><i class="bi bi-calendar-event me-1"></i>Due ${p.due}</span>
              <span>${actionBtns(p.id)}</span>
            </div>
          </div>
        </div>`);
    });
    initTooltips(tb); initTooltips(gal);
    const countEl = document.getElementById('projCount');
    if (countEl) {
      countEl.textContent = pageItems.length === list.length
        ? `Showing ${list.length} project${list.length===1?'':'s'}`
        : `Showing ${start+1}\u2013${start+pageItems.length} of ${list.length} projects`;
    }
    renderProjPaginationControls(list.length);
  }
  window.renderProjects = renderProjects;

  function openEdit(p){
    projForm.setAttribute('data-edit-id', p.id);
    document.getElementById('projModalTitle').textContent = 'Edit Project';
    document.getElementById('projModalSubmit').textContent = 'Save Changes';
    const f = projForm.elements;
    f.name.value = p.name; f.custId.value = p.custId; f.staffId.value = p.staffId;
    f.budget.value = p.budget; f.start.value = p.start; f.due.value = p.due; f.priority.value = p.priority;
    projModal.show();
  }
  document.getElementById('addProjModal').addEventListener('hidden.bs.modal', () => {
    projForm.removeAttribute('data-edit-id');
    document.getElementById('projModalTitle').textContent = 'Add Project';
    document.getElementById('projModalSubmit').textContent = 'Create Project';
  });

  function handleAct(e){
    const btn = e.target.closest('[data-act]'); if (!btn) return;
    const p = projectStore.find(btn.dataset.id); if (!p) return;
    if (btn.dataset.act === 'view') {
      showToast(`${p.name} — ${p.status}, ${p.progress}% complete, due ${p.due}`, 'info', 'bi-kanban');
    }
    if (btn.dataset.act === 'edit') openEdit(p);
    if (btn.dataset.act === 'del')
      confirmDelete(`Delete project "${p.name}" (${p.id})? This cannot be undone.`, () => {
        projectStore.remove(p.id); renderProjects();
        showToast(`${p.name} deleted`, 'success', 'bi-trash');
      });
  }
  tb.addEventListener('click', handleAct);
  gal.addEventListener('click', handleAct);

  document.addEventListener('entity:submit', (e) => {
    const { entity, data, editId } = e.detail;
    if (entity !== 'projects') return;
    const rec = { name:data.name.trim(), custId:data.custId, staffId:data.staffId,
                  cust:custName(data.custId), staff:staffName(data.staffId),
                  budget:parseFloat(data.budget)||0, start:data.start, due:data.due||data.start,
                  priority:data.priority };
    if (editId) projectStore.update(editId, rec);
    else projectStore.add({ id:nextId('PRJ-', PROJECTS), status:'In Progress', progress:0, ...rec });
    renderProjects();
  });

  renderProjects();
  window.renderProjects = renderProjects;
});
