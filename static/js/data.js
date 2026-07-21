/* =====================================================================
 PARABELLUM ISOS - Sample Data Store
 Static, realistic sample data used across the prototype.
 (Frontend-only - no backend / no database.)
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
  'System Administrator': ['dashboard','inventory','customers','projects','transactions','commissions','forecasting','reports','settings','profile'],
  'Inventory Personnel':  ['dashboard','inventory','profile'],
  'Operations Personnel': ['dashboard','projects','transactions','profile'],
  'Management/Owner':     ['dashboard','projects','transactions','commissions','forecasting','reports','profile'],
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

/* ---------------------------------- Inventory ---------------------------------- */
const INVENTORY = [
  { id:'INV-1001', name:'Deformed Steel Bar 16mm', cat:'Bars',        sup:'SteelAsia',          qty:1240, unit:'pcs',    reorder:300, price:285.00, loc:'Warehouse A', added:'2026-05-12', status:'In Stock' },
  { id:'INV-1002', name:'MS Plate 4x8 (6mm)',       cat:'Plates',      sup:'Capitol Steel',      qty:86,   unit:'sheets', reorder:40,  price:3450.00, loc:'Yard 1',      added:'2026-05-09', status:'In Stock' },
  { id:'INV-1003', name:'GI Sheet Corrugated 0.5mm',cat:'Sheets',      sup:'Puyat Steel',        qty:24,   unit:'sheets', reorder:60,  price:520.00,  loc:'Warehouse B', added:'2026-04-28', status:'Low Stock' },
  { id:'INV-1004', name:'Angle Bar 50x50x6mm',      cat:'Bars',        sup:'Pag-asa Steel',      qty:540,  unit:'length', reorder:150, price:610.00,  loc:'Yard 1',      added:'2026-05-02', status:'In Stock' },
  { id:'INV-1005', name:'Square Tube 2x2 (1.5mm)',  cat:'Tubes & Pipes',sup:'Cathay Metal',      qty:0,    unit:'length', reorder:120, price:430.00,  loc:'Warehouse A', added:'2026-04-15', status:'Out of Stock' },
  { id:'INV-1006', name:'H-Beam 200x200',           cat:'Beams',       sup:'SteelAsia',          qty:38,   unit:'pcs',    reorder:20,  price:12800.00,loc:'Yard 2',      added:'2026-05-18', status:'In Stock' },
  { id:'INV-1007', name:'Round Bar 12mm',           cat:'Bars',        sup:'Treasure Steelworks',qty:910,  unit:'length', reorder:250, price:198.00,  loc:'Warehouse A', added:'2026-05-20', status:'In Stock' },
  { id:'INV-1008', name:'Chequered Plate 3mm',      cat:'Plates',      sup:'Capitol Steel',      qty:31,   unit:'sheets', reorder:35,  price:2980.00, loc:'Yard 1',      added:'2026-05-06', status:'Low Stock' },
  { id:'INV-1009', name:'Welding Rod E6013 (box)',  cat:'Consumables', sup:'Cathay Metal',       qty:175,  unit:'box',    reorder:50,  price:1250.00, loc:'Warehouse B', added:'2026-05-21', status:'In Stock' },
  { id:'INV-1010', name:'C-Purlins 2x6 (1.6mm)',    cat:'Beams',       sup:'Puyat Steel',        qty:420,  unit:'length', reorder:120, price:740.00,  loc:'Yard 2',      added:'2026-05-11', status:'In Stock' },
  { id:'INV-1011', name:'Stainless Sheet 1.2mm',    cat:'Sheets',      sup:'Cathay Metal',       qty:18,   unit:'sheets', reorder:25,  price:4180.00, loc:'Warehouse B', added:'2026-04-22', status:'Low Stock' },
  { id:'INV-1012', name:'Steel Pipe Sched 40 (3")', cat:'Tubes & Pipes',sup:'Pag-asa Steel',     qty:265,  unit:'length', reorder:80,  price:2240.00, loc:'Yard 1',      added:'2026-05-15', status:'In Stock' },
  { id:'INV-1013', name:'Flat Bar 25x6mm',          cat:'Bars',        sup:'Treasure Steelworks',qty:0,    unit:'length', reorder:100, price:165.00,  loc:'Warehouse A', added:'2026-04-10', status:'Out of Stock' },
  { id:'INV-1014', name:'Wire Mesh 6mm 6x6',        cat:'Consumables', sup:'SteelAsia',          qty:140,  unit:'roll',   reorder:40,  price:3650.00, loc:'Yard 2',      added:'2026-05-19', status:'In Stock' },
  { id:'INV-1015', name:'Hex Bolt & Nut 1/2"x4"',   cat:'Fasteners',   sup:'Cathay Metal',       qty:5800, unit:'pcs',    reorder:1000,price:18.50,   loc:'Warehouse B', added:'2026-05-23', status:'In Stock' },
  { id:'INV-1016', name:'I-Beam 150x75',            cat:'Beams',       sup:'Capitol Steel',      qty:22,   unit:'pcs',    reorder:15,  price:9600.00, loc:'Yard 2',      added:'2026-05-08', status:'In Stock' },
];

/* ---------------------------------- Customers ---------------------------------- */
const CUSTOMERS = [
  { id:'CUS-201', name:'EEI Corporation',        contact:'Ramon Aquino',  phone:'0917-845-2210', email:'procurement@eei.com.ph',     addr:'Brgy. Ugong, Pasig City',        projects:6, txns:18, status:'Active' },
  { id:'CUS-202', name:'Megawide Construction',  contact:'Liza Tan',      phone:'0918-220-7741', email:'orders@megawide.com.ph',     addr:'Libis, Quezon City',             projects:4, txns:12, status:'Active' },
  { id:'CUS-203', name:'DATEM Incorporated',     contact:'Jose Marquez',  phone:'0920-661-9082', email:'supplies@datem.com.ph',      addr:'Cubao, Quezon City',             projects:3, txns:9,  status:'Active' },
  { id:'CUS-204', name:'Monolith Construction',  contact:'Karen Velasco', phone:'0915-773-1140', email:'admin@monolith.ph',          addr:'Bacoor, Cavite',                 projects:2, txns:5,  status:'On Hold' },
  { id:'CUS-205', name:'DMCI Homes',             contact:'Allan Reyes',   phone:'0917-009-4521', email:'materials@dmcihomes.com',    addr:'Makati City',                    projects:5, txns:14, status:'Active' },
  { id:'CUS-206', name:'JV Angeles Construction',contact:'Mariel Cruz',   phone:'0922-518-3307', email:'jvac.supply@gmail.com',      addr:'Angeles City, Pampanga',         projects:2, txns:7,  status:'Active' },
  { id:'CUS-207', name:'Vista Land Builders',    contact:'Paolo Lim',     phone:'0916-440-8812', email:'vistabuild@vistaland.com.ph',addr:'Las Piñas City',                 projects:1, txns:3,  status:'Inactive' },
  { id:'CUS-208', name:'Aboitiz InfraCapital',   contact:'Grace Uy',      phone:'0919-227-6650', email:'steel@aboitiz.com',          addr:'Cebu City',                      projects:3, txns:10, status:'Active' },
];

/* ---------------------------------- Projects ---------------------------------- */
const PROJECTS = [
  { id:'PRJ-301', name:'Warehouse Structural Frame', custId:'CUS-201',       staffId:'EMP-01', budget:2850000, start:'2026-03-10', due:'2026-07-15', status:'In Progress', priority:'High',   progress:68 },
  { id:'PRJ-302', name:'Steel Roof Truss — Plant B',  custId:'CUS-202', staffId:'EMP-02',   budget:1420000, start:'2026-04-02', due:'2026-06-28', status:'In Progress', priority:'Medium', progress:54 },
  { id:'PRJ-303', name:'Mezzanine Deck Fabrication',  custId:'CUS-205',            staffId:'EMP-03', budget:980000,  start:'2026-02-18', due:'2026-05-30', status:'Completed',   priority:'Medium', progress:100 },
  { id:'PRJ-304', name:'Perimeter Gate & Fence',      custId:'CUS-203',    staffId:'EMP-04',        budget:540000,  start:'2026-05-01', due:'2026-06-20', status:'In Progress', priority:'Low',    progress:32 },
  { id:'PRJ-305', name:'Heavy-Duty Steel Columns',    custId:'CUS-208',  staffId:'EMP-05',    budget:3650000, start:'2026-03-25', due:'2026-08-10', status:'In Progress', priority:'High',   progress:45 },
  { id:'PRJ-306', name:'Conveyor Support Structure',  custId:'CUS-201',       staffId:'EMP-01', budget:1180000, start:'2026-01-15', due:'2026-04-12', status:'Completed',   priority:'High',   progress:100 },
  { id:'PRJ-307', name:'Catwalk & Handrails',         custId:'CUS-206',staffId:'EMP-02',  budget:420000,  start:'2026-05-12', due:'2026-07-01', status:'On Hold',     priority:'Low',    progress:18 },
  { id:'PRJ-308', name:'Storage Tank Skid Frame',     custId:'CUS-204', staffId:'EMP-03', budget:760000,  start:'2026-04-20', due:'2026-06-15', status:'In Progress', priority:'Medium', progress:60 },
];

/* ---------------------------------- Transactions ---------------------------------- */
const TRANSACTIONS = [
  { inv:'TXN-4501', custId:'CUS-201',        proj:'PRJ-301', material:'Deformed Steel Bar 16mm', qty:200, price:285.00,  pay:'Paid',     method:'Bank Transfer', date:'2026-06-21' },
  { inv:'TXN-4502', custId:'CUS-202',  proj:'PRJ-302', material:'C-Purlins 2x6',           qty:120, price:740.00,  pay:'Paid',     method:'Check',         date:'2026-06-20' },
  { inv:'TXN-4503', custId:'CUS-205',             proj:'PRJ-303', material:'Chequered Plate 3mm',     qty:24,  price:2980.00, pay:'Partial',  method:'Bank Transfer', date:'2026-06-19' },
  { inv:'TXN-4504', custId:'CUS-208',   proj:'PRJ-305', material:'H-Beam 200x200',          qty:14,  price:12800.00,pay:'Pending',  method:'On Account',    date:'2026-06-18' },
  { inv:'TXN-4505', custId:'CUS-203',     proj:'PRJ-304', material:'Angle Bar 50x50x6mm',     qty:80,  price:610.00,  pay:'Paid',     method:'Cash',          date:'2026-06-17' },
  { inv:'TXN-4506', custId:'CUS-206',proj:'PRJ-307', material:'Round Bar 12mm',          qty:150, price:198.00,  pay:'Pending',  method:'On Account',    date:'2026-06-16' },
  { inv:'TXN-4507', custId:'CUS-201',        proj:'PRJ-306', material:'I-Beam 150x75',           qty:10,  price:9600.00, pay:'Paid',     method:'Bank Transfer', date:'2026-06-14' },
  { inv:'TXN-4508', custId:'CUS-204',  proj:'PRJ-308', material:'MS Plate 4x8 (6mm)',      qty:30,  price:3450.00, pay:'Partial',  method:'Check',         date:'2026-06-12' },
  { inv:'TXN-4509', custId:'CUS-205',             proj:'PRJ-303', material:'Welding Rod E6013',        qty:40,  price:1250.00, pay:'Paid',     method:'Cash',          date:'2026-06-10' },
  { inv:'TXN-4510', custId:'CUS-202',  proj:'PRJ-302', material:'Steel Pipe Sched 40 (3")', qty:25,  price:2240.00, pay:'Pending',  method:'On Account',    date:'2026-06-08' },
];

/* ---------------------------------- Commissions ---------------------------------- */
const EMPLOYEES = [
  { id:'EMP-01', name:'Engr. Juan Dela Cruz', role:'Senior Sales Engineer', completed:8, rate:5.0, sales:5840000, monthly:48200 },
  { id:'EMP-02', name:'Engr. Maria Santos',   role:'Sales Engineer',        completed:6, rate:4.5, sales:4120000, monthly:36800 },
  { id:'EMP-03', name:'Engr. Carlos Mendoza', role:'Project Engineer',      completed:5, rate:4.0, sales:3460000, monthly:29400 },
  { id:'EMP-04', name:'Engr. Ana Lim',        role:'Sales Engineer',        completed:4, rate:4.5, sales:2280000, monthly:21600 },
  { id:'EMP-05', name:'Engr. Pedro Reyes',    role:'Senior Sales Engineer', completed:7, rate:5.0, sales:5120000, monthly:42500 },
];

/* ---------------------------------- Relational lookups (FK -> display name, mirrors DB joins) ---------------------------------- */
const custName  = (id) => CUSTOMERS.find(c => c.id === id)?.name  || id;
const staffName = (id) => EMPLOYEES.find(e => e.id === id)?.name || id;
/* Derive display fields once so existing render code (p.cust / t.cust / p.staff) keeps working. */
PROJECTS.forEach(p => { p.cust = custName(p.custId); p.staff = staffName(p.staffId); });
TRANSACTIONS.forEach(t => { t.cust = custName(t.custId); });

/* ---------------------------------- System users (Settings > User Management) ---------------------------------- */
const USERS = [
  { id:'USR-01', name:'Admin User',          email:'admin@parabellumsteel.ph',   role:'System Administrator', dept:'IT / Management',  status:'Active' },
  { id:'USR-02', name:'Rosa Manalo',         email:'rosa.m@parabellumsteel.ph',  role:'Inventory Personnel',  dept:'Warehouse',        status:'Active' },
  { id:'USR-03', name:'Diego Fernandez',     email:'diego.f@parabellumsteel.ph', role:'Operations Personnel', dept:'Operations',       status:'Active' },
  { id:'USR-04', name:'Teresa Villanueva',   email:'teresa.v@parabellumsteel.ph',role:'Management/Owner',     dept:'Executive',        status:'Active' },
];

/* ---------------------------------- Activity log (Settings > System Logs) ---------------------------------- */
const ACTIVITY_LOG = [
  { time:'2026-06-26 09:41', user:'Admin User',        action:'Generated Inventory Status Report',           module:'Reports'   },
  { time:'2026-06-26 08:15', user:'Rosa Manalo',       action:'Stock In: +50 pcs Deformed Steel Bar 16mm',   module:'Inventory' },
  { time:'2026-06-25 16:03', user:'Diego Fernandez',   action:'Updated PRJ-302 progress to 54%',             module:'Projects'  },
  { time:'2026-06-25 14:22', user:'Admin User',        action:'Marked TXN-4501 as Paid',                     module:'Client Transactions' },
  { time:'2026-06-25 09:00', user:'System',            action:'Monthly demand forecast batch completed',     module:'Forecasting' },
];


/* ---------------------------------- Forecasting ---------------------------------- */
const FORECAST_HISTORY = [
  { id:'FC-091', material:'Deformed Steel Bar 16mm', month:'Jul 2026', predicted:150, actual:'—',  conf:'92%', date:'2026-06-24' },
  { id:'FC-090', material:'C-Purlins 2x6',            month:'Jun 2026', predicted:128, actual:121,  conf:'89%', date:'2026-05-26' },
  { id:'FC-089', material:'MS Plate 4x8 (6mm)',       month:'Jun 2026', predicted:62,  actual:58,   conf:'90%', date:'2026-05-26' },
  { id:'FC-088', material:'Angle Bar 50x50x6mm',      month:'Jun 2026', predicted:95,  actual:102,  conf:'87%', date:'2026-05-25' },
  { id:'FC-087', material:'H-Beam 200x200',           month:'Jun 2026', predicted:18,  actual:16,   conf:'85%', date:'2026-05-25' },
  { id:'FC-086', material:'Round Bar 12mm',           month:'May 2026', predicted:140, actual:135,  conf:'91%', date:'2026-04-27' },
];

/* ---------------------------------- Inventory usage (dashboard chart: daily / weekly / monthly) ---------------------------------- */
/* The LAST entry in each set is the current/most-recent period (highlighted gold in the chart). */
const USAGE_MONTHLY = { labels:['Jan','Feb','Mar','Apr','May','Jun'],                 data:[182,205,231,198,256,243],          note:'Tons of steel consumed per month (last 6 months).' };
const USAGE_WEEKLY  = { labels:['Wk 1','Wk 2','Wk 3','Wk 4','Wk 5','Wk 6'],            data:[58,62,49,71,64,68],                note:'Tons of steel consumed per week (last 6 weeks).' };
const USAGE_DAILY   = { labels:['Mon','Tue','Wed','Thu','Fri','Sat','Today'],          data:[9.2,11.4,8.7,12.1,10.6,7.3,6.1],   note:'Tons of steel consumed per day (last 7 days).' };

/* ---------------------------------- Current forecast per material (read-only, pre-computed batch output) ---------------------------------- */
const FORECAST_UPDATED = 'June 24, 2026';
const FORECAST_CURRENT = [
  { material:'Deformed Steel Bar 16mm',   month:'July 2026', predicted:150, unit:'pcs',    stock:1240, conf:'92%', trend:'+18%' },
  { material:'GI Sheet Corrugated 0.5mm', month:'July 2026', predicted:70,  unit:'sheets', stock:24,   conf:'89%', trend:'+12%' },
  { material:'MS Plate 4x8 (6mm)',        month:'July 2026', predicted:62,  unit:'sheets', stock:86,   conf:'90%', trend:'+6%'  },
  { material:'Angle Bar 50x50x6mm',       month:'July 2026', predicted:95,  unit:'length', stock:540,  conf:'87%', trend:'+9%'  },
  { material:'H-Beam 200x200',            month:'July 2026', predicted:28,  unit:'pcs',    stock:38,   conf:'85%', trend:'+15%' },
  { material:'C-Purlins 2x6 (1.6mm)',     month:'July 2026', predicted:135, unit:'length', stock:420,  conf:'89%', trend:'+11%' },
  { material:'Square Tube 2x2 (1.5mm)',   month:'July 2026', predicted:88,  unit:'length', stock:0,    conf:'86%', trend:'+21%' },
];

/* ---------------------------------- Notifications ---------------------------------- */
const NOTIFICATIONS = [
  { ic:'bi-exclamation-triangle-fill', tone:'b-danger',  title:'Low stock: GI Sheet Corrugated 0.5mm', time:'8 minutes ago' },
  { ic:'bi-graph-up-arrow',            tone:'b-info',    title:'Forecast completed for Deformed Steel Bar', time:'1 hour ago' },
  { ic:'bi-receipt',                   tone:'b-success', title:'Transaction TXN-4501 marked as Paid', time:'3 hours ago' },
  { ic:'bi-kanban',                    tone:'b-gold',    title:'Project PRJ-302 progress updated to 54%', time:'Yesterday' },
  { ic:'bi-x-octagon-fill',           tone:'b-danger',  title:'Out of stock: Square Tube 2x2 (1.5mm)', time:'Yesterday' },
];

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
const customerStore    = makeStore(CUSTOMERS);
const projectStore     = makeStore(PROJECTS);
const transactionStore = makeStore(TRANSACTIONS, 'inv');
const userStore        = makeStore(USERS);
