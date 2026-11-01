const PESO = (n) => '\u20b1' + Number(n).toLocaleString('en-PH', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const NUM  = (n) => Number(n).toLocaleString('en-PH');

let CURRENT_USER = { id:'', name:'', role:'' };

function escapeHTML(str){
  const d = document.createElement('div');
  d.textContent = String(str ?? '');
  return d.innerHTML;
}

function makeStore(arr, idKey='id'){
  return {
    all:    () => arr,
    find:   (id) => arr.find(x => x[idKey] === id),
    add:    (item) => { arr.push(item); return item; },
    update: (id, patch) => { const i = arr.findIndex(x => x[idKey] === id); if (i>-1) arr[i] = {...arr[i], ...patch}; return arr[i]; },
    remove: (id) => { const i = arr.findIndex(x => x[idKey] === id); if (i>-1) arr.splice(i,1); },
  };
}

function nextId(prefix, arr, idKey='id'){
  const max = arr.reduce((m,x) => Math.max(m, parseInt(String(x[idKey]).replace(/\D/g,''),10)||0), 0);
  return `${prefix}${max+1}`;
}
function invStatus(qty, reorder){
  if (qty <= 0) return 'Out of Stock';
  if (qty <= reorder) return 'Low Stock';
  return 'In Stock';
}

const SUPPLIER_CATEGORIES = ['Raw Material Supplier','Hardware/Fastener Supplier','Equipment Supplier','Consumables Supplier','Other'];
const SUPPLIER_TERMS      = ['Cash on Delivery','Net 15','Net 30','Net 45','Net 60'];
const SUPPLIERS    = [];
const INVENTORY    = [];
const CUSTOMERS    = [];
const PROJECTS     = [];
const TRANSACTIONS = [];
const EMPLOYEES    = [];

const custName  = (id) => CUSTOMERS.find(c => c.id === id)?.name  || id;
const staffName = (id) => EMPLOYEES.find(e => e.id === id)?.name || id;
const supplierName = (id) => SUPPLIERS.find(s => s.id === id)?.name || id || '';
const itemSupplierId = (i) => i?.supId || SUPPLIERS.find(s => s.name === i?.sup)?.id || '';

/* Badge / render helpers */
function stockBadge(status){
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
  return `<div class="d-inline-flex">
      <button class="act-btn" data-bs-toggle="tooltip" title="View" data-act="view" data-id="${id}"><i class="bi bi-eye"></i></button>
      <button class="act-btn" data-bs-toggle="tooltip" title="Edit" data-act="edit" data-id="${id}"><i class="bi bi-pencil"></i></button>
      <button class="act-btn danger" data-bs-toggle="tooltip" title="Delete" data-act="del" data-id="${id}"><i class="bi bi-trash"></i></button>
    </div>`;
}
function initTooltips(scope){
  (scope||document).querySelectorAll('[data-bs-toggle="tooltip"]').forEach(e=>{ if(!bootstrap.Tooltip.getInstance(e)) new bootstrap.Tooltip(e); });
}

const inventoryStore   = makeStore(INVENTORY);
const supplierStore    = makeStore(SUPPLIERS);
const customerStore    = makeStore(CUSTOMERS);
const projectStore     = makeStore(PROJECTS);
const transactionStore = makeStore(TRANSACTIONS, 'inv');

window.PROJECTS      = PROJECTS;
window.CUSTOMERS     = CUSTOMERS;
window.projectStore  = projectStore;
window.customerStore = customerStore;
window.SUPPLIERS     = SUPPLIERS;
window.supplierStore = supplierStore;
