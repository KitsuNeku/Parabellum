/* =====================================================================
 PARABELLUM ISOS - Shared frontend helpers + live data stores
 Formatting helpers, badge renderers and the in-memory stores the pages
 render from. The stores hold NO sample data: they are filled from the
 database by app.js (see the /api/... routes in app.py).
 ===================================================================== */
const PESO = (n) => '\u20b1' + Number(n).toLocaleString('en-PH', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const NUM  = (n) => Number(n).toLocaleString('en-PH');

/* ---------------------------------- Current session ----------------------------------
 Overwritten at page load by app.js with the real session user from GET /api/me.
 This placeholder only shows briefly before that call returns, or if a page is
 somehow reached without a session (which the server also blocks separately). */
let CURRENT_USER = { id:'', name:'', role:'' };

/* ---------------------------------- Role-based nav/action visibility (per capstone Table 3.2) ---------------------------------- */
const ROLE_PERMISSIONS = {
  'System Administrator': ['dashboard','inventory','suppliers','customers','projects','transactions','forecasting','reports','settings','profile'],
  'Inventory Personnel':  ['dashboard','inventory','suppliers','profile'],
  'Operations Personnel': ['dashboard','projects','transactions','profile'],
  'Management/Owner':     ['dashboard','projects','transactions','forecasting','reports','profile'],
};

/* ---------------------------------- Escape helper (safe HTML interpolation for user-editable fields) ---------------------------------- */
function escapeHTML(str){
  const d = document.createElement('div');
  d.textContent = String(str ?? '');
  return d.innerHTML;
}

/* ---------------------------------- Minimal in-memory store (backend swap seam) ----------------------------------
 .all() → GET /api/<entity> .add() → POST .update() → PATCH .remove() → DELETE */
function makeStore(arr, idKey='id'){
  return {
    all:    () => arr,
    find:   (id) => arr.find(x => x[idKey] === id),
    add:    (item) => { arr.push(item); return item; },
    update: (id, patch) => { const i = arr.findIndex(x => x[idKey] === id); if (i>-1) arr[i] = {...arr[i], ...patch}; return arr[i]; },
    remove: (id) => { const i = arr.findIndex(x => x[idKey] === id); if (i>-1) arr.splice(i,1); },
  };
}

/* ---------------------------------- ID generator + inventory status rule ---------------------------------- */
function nextId(prefix, arr, idKey='id'){
  const max = arr.reduce((m,x) => Math.max(m, parseInt(String(x[idKey]).replace(/\D/g,''),10)||0), 0);
  return `${prefix}${max+1}`;
}
function invStatus(qty, reorder){
  if (qty <= 0) return 'Out of Stock';
  if (qty <= reorder) return 'Low Stock';
  return 'In Stock';
}

/* ---------------------------------- Live data arrays ----------------------------------
 These start EMPTY on purpose. Every row the system shows comes from the
 database through the /api/... routes; app.js fills these arrays when a page
 loads. They used to be pre-filled with made-up sample suppliers, materials,
 customers, projects, transactions, staff, forecasts, usage figures and
 notifications - which painted on screen before the real data arrived, and
 stayed on screen on any page that had no loader of its own. Keeping them
 empty means the worst case is an honest empty state, never fake numbers.

 Suppliers are deactivated, never deleted, so a material's Stock In history
 always stays traceable back to who supplied it. */
const SUPPLIER_CATEGORIES = ['Raw Material Supplier','Hardware/Fastener Supplier','Equipment Supplier','Consumables Supplier','Other'];
const SUPPLIER_TERMS      = ['Cash on Delivery','Net 15','Net 30','Net 45','Net 60'];
const SUPPLIERS    = [];   // GET /api/suppliers
const INVENTORY    = [];   // GET /api/inventory
const CUSTOMERS    = [];   // GET /api/customers
const PROJECTS     = [];   // GET /api/projects
const TRANSACTIONS = [];   // GET /api/transactions
const EMPLOYEES    = [];   // GET /api/employees (Projects page staff dropdown)

/* ---------------------------------- Relational lookups (FK -> display name, mirrors DB joins) ----------------------------------
 Fallbacks only: the server already sends resolved names (e.g. /api/projects
 returns cust and staff), so these just return the raw code if a name isn't
 available yet. */
const custName  = (id) => CUSTOMERS.find(c => c.id === id)?.name  || id;
const staffName = (id) => EMPLOYEES.find(e => e.id === id)?.name || id;
const supplierName = (id) => SUPPLIERS.find(s => s.id === id)?.name || id || '';
/* An item's supplier id. Materials don't carry a supplier id column (the
 real `supplier` field on `materials` stays free text, unchanged), so this
 matches on name instead - the same seam the Suppliers page's "Materials
 Supplied" list and material count are built on. */
const itemSupplierId = (i) => i?.supId || SUPPLIERS.find(s => s.name === i?.sup)?.id || '';

/* ---------------------------------- Badge / render helpers ---------------------------------- */
function stockBadge(status){
  // §3.3.1 - status shown without color-coding (neutral badge, no colored dot)
  return `<span class="badge b-neutral">${status}</span>`;
}
function payBadge(p){
  const m={Paid:'b-success',Partial:'b-warning',Pending:'b-danger'};
  return `<span class="badge ${m[p]||'b-neutral'}">${p}</span>`;
}
function projStatusBadge(s){
  const m={'In Progress':'b-info','Completed':'b-success','On Hold':'b-warning'};
  return `<span class="badge ${m[s]||'b-neutral'}">${s}</span>`;
}
function priorityBadge(p){
  const m={High:'b-danger',Medium:'b-warning',Low:'b-neutral'};
  return `<span class="badge ${m[p]||'b-neutral'}">${p}</span>`;
}
function custStatusBadge(s){
  const m={Active:'b-success','On Hold':'b-warning',Inactive:'b-neutral'};
  return `<span class="badge ${m[s]||'b-neutral'}">${s}</span>`;
}
function supplierStatusBadge(s){
  const m={Active:'b-success',Inactive:'b-warning',Archived:'b-neutral'};
  return `<span class="badge ${m[s]||'b-neutral'}">${s}</span>`;
}
function progressBar(p){
  const cls = p>=100?'green':(p>=50?'':'gold');
  return `<div class="d-flex align-items-center gap-2">
      <div class="progress flex-grow-1" style="min-width:80px"><div class="progress-bar ${cls}" style="width:${p}%"></div></div>
      <span class="small fw-medium" style="width:34px">${p}%</span></div>`;
}
function actionBtns(id){
  /* Real action hooks - each page wires a delegated handler on data-act + data-id. */
  return `<div class="d-inline-flex">
      <button class="act-btn" data-bs-toggle="tooltip" title="View" data-act="view" data-id="${id}"><i class="bi bi-eye"></i></button>
      <button class="act-btn" data-bs-toggle="tooltip" title="Edit" data-act="edit" data-id="${id}"><i class="bi bi-pencil"></i></button>
      <button class="act-btn danger" data-bs-toggle="tooltip" title="Delete" data-act="del" data-id="${id}"><i class="bi bi-trash"></i></button>
    </div>`;
}
function initTooltips(scope){
  (scope||document).querySelectorAll('[data-bs-toggle="tooltip"]').forEach(e=>{ if(!bootstrap.Tooltip.getInstance(e)) new bootstrap.Tooltip(e); });
}

/* ---------------------------------- Entity stores (the exact seam a backend swaps into) ---------------------------------- */
const inventoryStore   = makeStore(INVENTORY);
const supplierStore    = makeStore(SUPPLIERS);
const customerStore    = makeStore(CUSTOMERS);
const projectStore     = makeStore(PROJECTS);
const transactionStore = makeStore(TRANSACTIONS, 'inv');

/* app.js's wireEntityPage() looks these up dynamically by name via
 window[cfg.arrayName] / window[cfg.storeName] so one generic function
 can wire up multiple entity pages. Top-level `const` creates a global
 BINDING but does NOT create a `window` PROPERTY (unlike `var` or a
 function declaration) - so without these explicit assignments,
 wireEntityPage's `typeof window[...] === 'undefined'` guard is always
 true and it silently never attaches, meaning Add/Edit never reaches
 the server at all. This is the fix for that. */
window.PROJECTS      = PROJECTS;
window.CUSTOMERS     = CUSTOMERS;
window.projectStore  = projectStore;
window.customerStore = customerStore;
window.SUPPLIERS     = SUPPLIERS;
window.supplierStore = supplierStore;
