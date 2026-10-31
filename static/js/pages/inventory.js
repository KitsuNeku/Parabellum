/* Inventory page */
document.addEventListener('DOMContentLoaded', () => {
  const set = (id,val)=>{ const el=document.getElementById(id); if(el) el.textContent=val; };
  let currentDetailId = null;

  function fitSearchResults(input, results){
    const rect = input.getBoundingClientRect();
    const spaceBelow = window.innerHeight - rect.bottom - 16;
    results.style.maxHeight = Math.max(100, Math.min(220, spaceBelow)) + 'px';
  }

  function wireItemSearch(searchId, hiddenId, resultsId, opts = {}){
    const searchInput = document.getElementById(searchId);
    const hiddenInput = document.getElementById(hiddenId);
    const results = document.getElementById(resultsId);
    if (!searchInput || !hiddenInput || !results) return;
    const allowUnmatched = !!opts.allowUnmatched;
    const unmatchedMsg = allowUnmatched ? '' : 'Search and select an item from the list.';

    const flagOutOfStock = !!opts.flagOutOfStock;

    const allowOthers = !!opts.allowOthers;
    const othersRow = `<div class="isr-item isr-item--other" data-other="1">
        <div class="fw-medium"><i class="bi bi-plus-lg me-1"></i>Others</div>
        <div class="small text-muted-2">Not in the list - add it as a new item</div>
      </div>`;

    function renderResults(query){
      const items = inventoryStore.all();
      const q = query.trim().toLowerCase();
      const matches = q
        ? items.filter(i => i.name.toLowerCase().includes(q) || i.id.toLowerCase().includes(q)).slice(0, 8)
        : items.slice(0, 8);
      results.innerHTML = (matches.length
        ? matches.map(i => {
            const outOfStock = flagOutOfStock && Number(i.qty) <= 0;
            return `<div class="isr-item${outOfStock ? ' isr-item--out' : ''}" data-id="${i.id}">
            <div class="fw-medium">${escapeHTML(i.name)}</div>
            <div class="small ${outOfStock ? '' : 'text-muted-2'}">${i.id} \u2022 ${outOfStock ? 'Out of stock' : `${NUM(i.qty)} ${i.unit} on hand`}</div>
          </div>`;
          }).join('')
        : `<div class="isr-empty">No matching items.</div>`) + (allowOthers ? othersRow : '');
      results.classList.add('show');
      fitSearchResults(searchInput, results);
    }

    searchInput.addEventListener('focus', () => renderResults(searchInput.value));
    searchInput.addEventListener('input', () => {
      const wasSelected = !!hiddenInput.value;
      hiddenInput.value = '';
      searchInput.setCustomValidity(unmatchedMsg);
      renderResults(searchInput.value);
      if (wasSelected && typeof opts.onClear === 'function') opts.onClear();
    });
    results.addEventListener('mousedown', (e) => {
      const item = e.target.closest('.isr-item'); if (!item) return;
      if (item.dataset.other) {
        const wasSelected = !!hiddenInput.value;
        hiddenInput.value = '';
        searchInput.value = '';
        searchInput.setCustomValidity(unmatchedMsg);
        results.classList.remove('show');
        if (wasSelected && typeof opts.onClear === 'function') opts.onClear();
        setTimeout(() => searchInput.focus(), 0);
        return;
      }
      const material = inventoryStore.find(item.dataset.id); if (!material) return;
      hiddenInput.value = material.id;
      searchInput.value = material.name;
      searchInput.setCustomValidity('');
      results.classList.remove('show');
      if (typeof opts.onSelect === 'function') opts.onSelect(material);
    });
    searchInput.addEventListener('blur', () => {
      setTimeout(() => results.classList.remove('show'), 150);
    });

    searchInput.closest('.modal')?.addEventListener('show.bs.modal', () => {
      searchInput.value = '';
      hiddenInput.value = '';
      searchInput.setCustomValidity(unmatchedMsg);
      results.classList.remove('show');
      if (typeof opts.onClear === 'function') opts.onClear();
    });
  }
  const stockInCatSel = document.querySelector('#stockInModal select[name="cat"]');
  const stockInCatOrigHTML = stockInCatSel ? stockInCatSel.innerHTML : '';
  const stockInUnitSel = document.querySelector('#stockInModal select[name="unit"]');
  const stockInUnitOrigHTML = stockInUnitSel ? stockInUnitSel.innerHTML : '';
  wireItemSearch('stockInItemSearch', 'stockInItemId', 'stockInItemResults', {
    allowUnmatched: true,
    allowOthers: true,
    onSelect: (material) => {
      const sup = document.getElementById('stockInSupplier');
      const price = document.getElementById('stockInPrice');
      const hint = document.getElementById('stockInSupplierHint');
      if (sup)   { sup.value = material.sup || ''; sup.readOnly = true; }
      if (price) { price.value = material.price != null ? Number(material.price).toFixed(2) : '0.00'; price.readOnly = true; }
      if (hint)  hint.textContent = 'Filled in automatically from this item’s record.';
      if (stockInCatSel) {
        const cat = material.cat || '';
        if (cat && ![...stockInCatSel.options].some(o => o.value === cat || o.textContent === cat)) {
          const extra = document.createElement('option');
          extra.textContent = cat;
          stockInCatSel.appendChild(extra);
        }
        if (cat) stockInCatSel.value = cat;
        stockInCatSel.disabled = true;
      }
      if (stockInUnitSel) {
        const unit = material.unit || '';
        if (unit && ![...stockInUnitSel.options].some(o => o.value === unit || o.textContent === unit)) {
          const extra = document.createElement('option');
          extra.textContent = unit;
          stockInUnitSel.appendChild(extra);
        }
        if (unit) stockInUnitSel.value = unit;
        stockInUnitSel.disabled = true;
      }
    },
    onClear: () => {
      const sup = document.getElementById('stockInSupplier');
      const price = document.getElementById('stockInPrice');
      const hint = document.getElementById('stockInSupplierHint');
      if (sup)   { sup.readOnly = false; sup.value = ''; }
      if (price) { price.readOnly = false; price.value = '0.00'; }
      if (hint)  hint.textContent = 'New item only - search an existing supplier, type a new one, or use Add Supplier above to fill out its full details.';
      if (stockInCatSel) {
        stockInCatSel.disabled = false;
        stockInCatSel.innerHTML = stockInCatOrigHTML;
        stockInCatSel.selectedIndex = 0;
      }
      if (stockInUnitSel) {
        stockInUnitSel.disabled = false;
        stockInUnitSel.innerHTML = stockInUnitOrigHTML;
        stockInUnitSel.selectedIndex = 0;
      }
    },
  });
  wireItemSearch('stockOutCartItemSearch', 'stockOutCartItemId', 'stockOutCartItemResults', { flagOutOfStock: true });

  let SUPPLIERS_CACHE = [];
  function loadSuppliers(){
    return fetch('/api/suppliers').then(r => r.ok ? r.json() : null).then(json => {
      if (json && json.ok) SUPPLIERS_CACHE = json.data.filter(s => s.status === 'Active');
      renderAddItemSupplierOptions();
      return SUPPLIERS_CACHE;
    }).catch(() => SUPPLIERS_CACHE);
  }
  function renderAddItemSupplierOptions(){
    const sel = document.getElementById('addItemSupplier');
    const hint = document.getElementById('addItemNoSuppliersHint');
    if (!sel) return;
    const current = sel.value;
    sel.innerHTML = SUPPLIERS_CACHE.map(s => `<option value="${escapeHTML(s.name)}">${escapeHTML(s.name)}</option>`).join('');
    if (current && SUPPLIERS_CACHE.some(s => s.name === current)) sel.value = current;
    if (hint) hint.style.display = SUPPLIERS_CACHE.length ? 'none' : '';
  }
  loadSuppliers();

  (function () {
    const searchInput = document.getElementById('stockInSupplier');
    const results = document.getElementById('stockInSupplierResults');
    if (!searchInput || !results) return;

    function renderResults(query){
      const q = query.trim().toLowerCase();
      const matches = q
        ? SUPPLIERS_CACHE.filter(s => s.name.toLowerCase().includes(q)).slice(0, 8)
        : SUPPLIERS_CACHE.slice(0, 8);
      results.innerHTML = matches.length
        ? matches.map(s => `<div class="isr-item" data-name="${escapeHTML(s.name)}">
            <div class="fw-medium">${escapeHTML(s.name)}</div>
            <div class="small text-muted-2">${escapeHTML(s.category || 'Supplier')}</div>
          </div>`).join('')
        : `<div class="isr-empty">No matching suppliers${q ? ' - "' + escapeHTML(query.trim()) + '" will be used as typed' : ''}.</div>`;
      results.classList.add('show');
      fitSearchResults(searchInput, results);
    }

    searchInput.addEventListener('focus', () => { if (!searchInput.readOnly) renderResults(searchInput.value); });
    searchInput.addEventListener('input', () => renderResults(searchInput.value));
    results.addEventListener('mousedown', (e) => {
      const item = e.target.closest('.isr-item'); if (!item) return;
      searchInput.value = item.dataset.name;
      results.classList.remove('show');
    });
    searchInput.addEventListener('blur', () => {
      setTimeout(() => results.classList.remove('show'), 150);
    });
    searchInput.closest('.modal')?.addEventListener('show.bs.modal', () => {
      results.classList.remove('show');
    });
  })();

  (function () {
    const form = document.getElementById('addItemForm');
    if (!form) return;
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      if (!form.checkValidity()) { e.stopPropagation(); form.classList.add('was-validated'); return; }
      const d = Object.fromEntries(new FormData(form));
      try {
        const res = await fetch('/api/inventory/save', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ name: d.name, cat: d.cat, sup: d.sup, unit: d.unit,
                                  price: d.price, reorder: d.reorder, loc: d.loc, qty: d.qty }),
        });
        const json = await res.json();
        if (!json.ok) throw new Error(json.error);
        await refreshInventory();
        bootstrap.Modal.getInstance(form.closest('.modal'))?.hide();
        form.reset(); form.classList.remove('was-validated');
        showToast('Item added to inventory', 'success');
      } catch (err) {
        showToast(err.message, 'error', 'bi-exclamation-triangle');
      }
    });
    form.closest('.modal')?.addEventListener('show.bs.modal', () => {
      form.reset(); form.classList.remove('was-validated');
    });
  })();

  (function () {
    const form = document.getElementById('addSupplierForm');
    if (!form) return;
    const catSel = document.getElementById('addSupplierCategory');
    const termsSel = document.getElementById('addSupplierTerms');
    if (catSel) catSel.innerHTML = SUPPLIER_CATEGORIES.map(c => `<option>${escapeHTML(c)}</option>`).join('');
    if (termsSel) termsSel.innerHTML =
      SUPPLIER_TERMS.map(t => `<option ${t === 'Net 30' ? 'selected' : ''}>${escapeHTML(t)}</option>`).join('');

    const saveBtn = document.getElementById('addSupplierSaveBtn');
    function setAddSupplierBusy(busy){
      form.querySelectorAll('[data-bs-dismiss="modal"]').forEach(b => b.disabled = busy);
      if (saveBtn) {
        saveBtn.disabled = busy;
        saveBtn.innerHTML = busy
          ? `<span class="spinner-border spinner-border-sm me-2" aria-hidden="true"></span>Saving…`
          : 'Save Supplier';
      }
    }
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      if (!form.checkValidity()) { e.stopPropagation(); form.classList.add('was-validated'); return; }
      if (saveBtn?.disabled) return;
      const d = Object.fromEntries(new FormData(form));
      setAddSupplierBusy(true);
      try {
        const res = await fetch('/api/suppliers/save', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ name: d.name, contact: d.contact, phone: d.phone, email: d.email,
                                  addr: d.addr, category: d.category, terms: d.terms, remarks: d.remarks,
                                  status: 'Active' }),
        });
        const json = await res.json();
        if (!json.ok) throw new Error(json.error);
        await loadSuppliers();
        bootstrap.Modal.getInstance(form.closest('.modal'))?.hide();
        form.reset(); form.classList.remove('was-validated');
        showToast('Supplier saved', 'success');
      } catch (err) {
        showToast(err.message, 'error', 'bi-exclamation-triangle');
      } finally {
        setAddSupplierBusy(false);
      }
    });
    form.closest('.modal')?.addEventListener('show.bs.modal', () => {
      form.reset(); form.classList.remove('was-validated');
      setAddSupplierBusy(false);
    });
  })();

  const modalReturnTo = {};
  let modalNavigating = false;
  document.addEventListener('click', (e) => {
    const btn = e.target.closest('[data-modal-nav]');
    if (!btn) return;
    e.preventDefault();
    const from = btn.closest('.modal');
    const toId = btn.dataset.modalNav;
    if (!from || modalNavigating) return;
    modalNavigating = true;
    modalReturnTo[toId] = from.id;
    from.addEventListener('hidden.bs.modal', () => {
      modalNavigating = false;
      bootstrap.Modal.getOrCreateInstance('#' + toId).show();
    }, { once: true });
    bootstrap.Modal.getInstance(from)?.hide();
  });
  ['addItemModal', 'addSupplierModal'].forEach(id => {
    document.getElementById(id)?.addEventListener('hidden.bs.modal', () => {
      if (modalNavigating) return;
      const back = modalReturnTo[id] || 'stockInModal';
      delete modalReturnTo[id];
      bootstrap.Modal.getOrCreateInstance('#' + back).show();
    });
  });

  function tickMoveDates(){
    const text = new Date().toLocaleDateString(undefined, { year: 'numeric', month: 'long', day: 'numeric' });
    const a = document.getElementById('stockInDate');  if (a) a.textContent = text;
    const b = document.getElementById('stockOutDate'); if (b) b.textContent = text;
    const c = document.getElementById('returnDate');   if (c) c.textContent = text;
  }
  tickMoveDates();
  setInterval(tickMoveDates, 60000);

  let stockOutCart = [];
  let stockOutIssued = [];
  let stockOutReceiptInfo = null;
  let stockOutBusy = false;
  const so = {
    modal:   document.getElementById('stockOutModal'),
    form:    document.getElementById('stockOutForm'),
    project: document.getElementById('stockOutProject'),
    client:  document.getElementById('stockOutClient'),
    address: document.getElementById('stockOutAddress'),
    contact: document.getElementById('stockOutContact'),
    search:  document.getElementById('stockOutCartItemSearch'),
    itemId:  document.getElementById('stockOutCartItemId'),
    results: document.getElementById('stockOutCartItemResults'),
    avail:   document.getElementById('stockOutCartAvail'),
    qty:     document.getElementById('stockOutCartQty'),
    addBtn:  document.getElementById('stockOutCartAddBtn'),
    error:   document.getElementById('stockOutCartError'),
    body:    document.getElementById('stockOutCartBody'),
    wrap:    document.getElementById('stockOutCartWrap'),
    empty:   document.getElementById('stockOutCartEmpty'),
    count:   document.getElementById('stockOutCartCount'),
    result:  document.getElementById('stockOutResult'),
    confirm: document.getElementById('stockOutConfirmBtn'),
  };
  const plural = (n, word) => `${n} ${word}${n === 1 ? '' : 's'}`;

  function renderStockOutProjects(){
    if (!so.project || typeof PROJECTS === 'undefined') return;
    const keep = so.project.value;
    const opt = p => `<option value="${escapeHTML(p.id)}">${escapeHTML(p.name)} \u2014 ${escapeHTML(custName(p.custId))}${p.status && p.status !== 'In Progress' ? ` (${escapeHTML(p.status)})` : ''}</option>`;
    const eligible = PROJECTS.filter(p => p.status !== 'Completed');
    const active = eligible.filter(p => p.status === 'In Progress');
    const other  = eligible.filter(p => p.status !== 'In Progress');
    so.project.innerHTML = (active.length ? `<optgroup label="Active projects">${active.map(opt).join('')}</optgroup>` : '')
      + (other.length  ? `<optgroup label="Other projects">${other.map(opt).join('')}</optgroup>` : '');
    so.project.value = eligible.some(p => p.id === keep) ? keep : '';
    onStockOutProjectChange();
  }
  window.renderStockOutProjects = renderStockOutProjects;

  function onStockOutProjectChange(){
    const p = (typeof PROJECTS !== 'undefined') ? PROJECTS.find(x => x.id === so.project.value) : null;
    const c = (p && typeof CUSTOMERS !== 'undefined') ? CUSTOMERS.find(x => x.id === p.custId) : null;
    so.client.textContent  = p ? (typeof custName === 'function' ? custName(p.custId) : (c?.name || '\u2014')) : '\u2014';
    so.address.textContent = c?.addr || '\u2014';
    so.contact.textContent = c ? ([c.contact, c.phone].filter(Boolean).join(' \u00b7 ') || '\u2014') : '\u2014';
    if (p) so.project.classList.remove('is-invalid');
    const locked = !p || stockOutBusy;
    so.search.disabled = locked; so.qty.disabled = locked; so.addBtn.disabled = locked;
    if (!p) { so.avail.textContent = 'Choose a project first.'; }
    else if (!so.itemId.value) { so.avail.textContent = 'Pick an item to see its available stock.'; }
    updateStockOutConfirm();
  }
  so.project?.addEventListener('change', onStockOutProjectChange);

  function showCartAvail(){
    const i = so.itemId.value ? inventoryStore.find(so.itemId.value) : null;
    if (!i) {
      so.avail.classList.remove('text-danger', 'fw-medium');
      so.avail.textContent = so.project.value ? 'Pick an item to see its available stock.' : 'Choose a project first.';
      return;
    }
    const inCart = stockOutCart.find(r => r.itemId === i.id);
    const outOfStock = Number(i.qty) <= 0;
    so.avail.classList.toggle('text-danger', outOfStock);
    so.avail.classList.toggle('fw-medium', outOfStock);
    so.avail.textContent = (outOfStock ? `Out of stock \u2014 0 ${i.unit} available` : `Available: ${NUM(i.qty)} ${i.unit}`)
      + (inCart ? ` \u00b7 ${NUM(inCart.requestedQty)} already in this request` : '');
  }
  function syncQtyMax(){
    const i = so.itemId.value ? inventoryStore.find(so.itemId.value) : null;
    if (!i) { so.qty.removeAttribute('max'); return; }
    const row = stockOutCart.find(r => r.itemId === i.id);
    const remaining = Math.max(0, (Number(i.qty) || 0) - (row ? row.requestedQty : 0));
    so.qty.max = String(remaining);
  }
  function clampQtyInput(inp){
    if (inp.value === '') return;
    let v = Number(inp.value);
    const max = inp.max === '' ? Infinity : Number(inp.max);
    const min = inp.min === '' ? -Infinity : Number(inp.min);
    if (Number.isFinite(max) && v > max) v = max;
    if (Number.isFinite(min) && v < min) v = min;
    if (String(v) !== inp.value) inp.value = String(v);
  }
  so.results?.addEventListener('mousedown', () => { showCartAvail(); syncQtyMax(); setCartError(''); });
  so.search?.addEventListener('input', () => { showCartAvail(); syncQtyMax(); setCartError(''); });
  so.qty?.addEventListener('input', () => { clampQtyInput(so.qty); setCartError(''); });

  function setCartError(msg){
    so.error.textContent = msg;
    so.qty.classList.toggle('is-invalid', !!msg && !!so.itemId.value);
    so.search.classList.toggle('is-invalid', !!msg && !so.itemId.value);
  }

  function addToStockOutCart(){
    const i = so.itemId.value ? inventoryStore.find(so.itemId.value) : null;
    if (!i) return setCartError('Search for an item and pick it from the list.');
    const qty = Number(so.qty.value);
    if (!Number.isInteger(qty) || qty < 1) return setCartError('Enter a requested quantity of at least 1.');
    const available = Number(i.qty) || 0;
    if (available <= 0) return setCartError(`${i.name} is out of stock.`);
    const row = stockOutCart.find(r => r.itemId === i.id);
    if (row) {
      const merged = row.requestedQty + qty;
      if (merged > available) return setCartError(`Only ${NUM(available)} ${i.unit} available \u2014 ${NUM(row.requestedQty)} already in this request.`);
      row.requestedQty = merged;
    } else {
      if (qty > available) return setCartError(`Only ${NUM(available)} ${i.unit} available.`);
      stockOutCart.push({ itemId: i.id, name: i.name, code: i.id, unit: i.unit, available, requestedQty: qty });
    }
    so.search.value = ''; so.itemId.value = ''; so.qty.value = '';
    setCartError(''); showCartAvail(); syncQtyMax(); hideStockOutResult();
    renderStockOutCart();
  }
  so.addBtn?.addEventListener('click', addToStockOutCart);

  const rowQtyError = (r) => (!Number.isInteger(r.requestedQty) || r.requestedQty < 1)
    ? 'At least 1.'
    : (r.requestedQty > r.available ? `Max ${NUM(r.available)}.` : '');
  function renderStockOutCart(){
    let cartTotal = 0;
    so.body.innerHTML = stockOutCart.map((r, idx) => {
      const err = rowQtyError(r);
      const unitPrice = Number(inventoryStore.find(r.itemId)?.price) || 0;
      const qtyForTotal = Number.isFinite(r.requestedQty) ? r.requestedQty : 0;
      const lineTotal = unitPrice * qtyForTotal;
      cartTotal += lineTotal;
      return `<tr>
        <td class="fw-medium">${escapeHTML(r.name)}</td>
        <td class="text-muted-2">${escapeHTML(r.code)}</td>
        <td class="text-end">${NUM(r.available)}</td>
        <td>
          <input type="number" class="form-control form-control-sm ${err ? 'is-invalid' : ''}" min="1" max="${r.available}" step="1"
                 value="${Number.isFinite(r.requestedQty) ? r.requestedQty : ''}" data-cart-idx="${idx}" aria-label="Requested quantity for ${escapeHTML(r.name)}" ${stockOutBusy ? 'disabled' : ''}>
          <div class="invalid-feedback">${err}</div>
        </td>
        <td class="text-muted-2">${escapeHTML(r.unit)}</td>
        <td class="text-end text-muted-2">${PESO(unitPrice)}</td>
        <td class="text-end fw-medium">${PESO(lineTotal)}</td>
        <td class="text-center"><button type="button" class="act-btn danger" data-cart-remove="${idx}" title="Remove from request" aria-label="Remove ${escapeHTML(r.name)} from request" ${stockOutBusy ? 'disabled' : ''}><i class="bi bi-trash"></i></button></td>
      </tr>`;
    }).join('');
    const n = stockOutCart.length;
    so.wrap.classList.toggle('d-none', n === 0);
    so.empty.classList.toggle('d-none', n > 0);
    so.count.textContent = plural(n, 'item');
    const totalWrap = document.getElementById('stockOutCartTotalWrap');
    const totalEl = document.getElementById('stockOutCartTotal');
    if (totalWrap) totalWrap.classList.toggle('d-none', n === 0);
    if (totalEl) totalEl.textContent = PESO(cartTotal);
    if (so.project) so.project.disabled = stockOutBusy || n > 0;
    document.getElementById('stockOutProjectLockHint')?.classList.toggle('d-none', n === 0);
    updateStockOutConfirm();
  }
  so.body?.addEventListener('input', (e) => {
    const inp = e.target.closest('[data-cart-idx]'); if (!inp) return;
    const r = stockOutCart[+inp.dataset.cartIdx]; if (!r) return;
    clampQtyInput(inp);
    r.requestedQty = inp.value === '' ? NaN : Number(inp.value);
    const err = rowQtyError(r);
    inp.classList.toggle('is-invalid', !!err);
    inp.nextElementSibling.textContent = err;
    updateStockOutConfirm();
  });
  so.body?.addEventListener('change', (e) => { if (e.target.closest('[data-cart-idx]')) renderStockOutCart(); });
  so.body?.addEventListener('click', (e) => {
    const btn = e.target.closest('[data-cart-remove]'); if (!btn) return;
    stockOutCart.splice(+btn.dataset.cartRemove, 1);
    renderStockOutCart(); showCartAvail();
  });

  function updateStockOutConfirm(){
    so.confirm.disabled = stockOutBusy || !so.project.value || stockOutCart.length === 0
      || stockOutCart.some(r => rowQtyError(r));
  }

  function hideStockOutResult(){ so.result.classList.add('d-none'); so.result.innerHTML = ''; }
  function showStockOutResult(html){ so.result.innerHTML = html; so.result.classList.remove('d-none'); }

  function resetStockOut(){
    stockOutCart = [];
    stockOutIssued = []; stockOutReceiptInfo = null;
    so.project.value = ''; so.project.classList.remove('is-invalid');
    so.search.value = ''; so.itemId.value = ''; so.qty.value = '';
    setCartError(''); hideStockOutResult();
    renderStockOutProjects();
    renderStockOutCart();
  }
  so.modal?.addEventListener('show.bs.modal', resetStockOut);
  function showStockOutReceipt(){
    if (!stockOutIssued.length || !stockOutReceiptInfo) return;
    const info = stockOutReceiptInfo;
    const items = stockOutIssued.map(r => {
      const i = inventoryStore.find(r.itemId) || {};
      return { movementId: r.movementId, id: r.itemId, name: r.name || i.name, cat: i.cat,
               qty: r.requestedQty, unit: r.unit || i.unit, price: Number(i.price) || 0 };
    });
    const locs = [...new Set(stockOutIssued.map(r => (inventoryStore.find(r.itemId) || {}).loc).filter(Boolean))].join(', ');
    const wmv = stockOutIssued.map(r => (window.ALL_MOVEMENTS || []).find(m => String(m.movementId) === String(r.movementId)))
                              .find(m => m && (m.weatherTemp != null || m.weatherRain != null));
    window.showTransactionReceipt('ISSUANCE', items, {
      when: info.when,
      weather: wmv ? { temp: wmv.weatherTemp, rain: wmv.weatherRain, wind: wmv.weatherWind } : null,
      delivery: { status: 'Pending' },
      fields: [['Client / Customer', info.client], ['Project', info.project], ['Delivery Address', info.address],
               ['Contact', info.contact], ['Purpose / Reference', info.projectId], ['Location', locs], ['Released by', info.user]],
      recordedBy: info.user, counterparty: '',
    });
  }
  so.modal?.addEventListener('hidden.bs.modal', () => {
    if (stockOutBusy) return;
    showStockOutReceipt();
    resetStockOut();
  });
  so.modal?.addEventListener('hide.bs.modal', (e) => { if (stockOutBusy) e.preventDefault(); });

  so.form?.addEventListener('keydown', (e) => {
    if (e.key !== 'Enter') return;
    if (e.target === so.qty || e.target === so.search) { e.preventDefault(); if (!so.addBtn.disabled) addToStockOutCart(); }
    else if (e.target.closest('[data-cart-idx]')) { e.preventDefault(); e.target.blur(); }
  });

  function setStockOutBusy(busy, label){
    stockOutBusy = busy;
    so.project.disabled = busy;
    so.modal.querySelectorAll('[data-bs-dismiss="modal"]').forEach(b => b.disabled = busy);
    so.confirm.innerHTML = busy
      ? `<span class="spinner-border spinner-border-sm me-2" aria-hidden="true"></span>${label || 'Issuing\u2026'}`
      : 'Confirm Stock Out';
    onStockOutProjectChange();
    renderStockOutCart();
  }

  so.form?.addEventListener('submit', async (e) => {
    e.preventDefault();
    if (stockOutBusy) return;
    if (!so.project.value) { so.project.classList.add('is-invalid'); so.project.focus(); return; }
    if (!stockOutCart.length || stockOutCart.some(r => rowQtyError(r))) return;
    if (typeof window.submitStockOutRequest !== 'function') {
      showToast('Stock Out is not connected to the server on this page.', 'error', 'bi-exclamation-triangle');
      return;
    }
    const projectId = so.project.value;
    const rows = stockOutCart.map(r => ({ ...r }));
    const proj = (typeof PROJECTS !== 'undefined') ? PROJECTS.find(x => x.id === projectId) : null;
    const txt = (el) => { const t = (el?.textContent || '').trim(); return t === '—' ? '' : t; };
    stockOutReceiptInfo = { projectId, project: proj ? `${proj.id} — ${proj.name}` : projectId,
      client: txt(so.client), address: txt(so.address), contact: txt(so.contact),
      user: (typeof CURRENT_USER !== 'undefined' && CURRENT_USER.name) || '', when: window.receiptNow() };
    hideStockOutResult();
    setStockOutBusy(true, `Issuing 1 of ${rows.length}\u2026`);
    let outcome;
    try {
      outcome = await window.submitStockOutRequest(rows, projectId,
        (k, total) => { so.confirm.lastChild.textContent = `Issuing ${k} of ${total}\u2026`; });
    } catch (err) {
      outcome = { issued: [], failed: { row: rows[0], error: err.message || 'Unexpected error.' }, remaining: rows };
    } finally {
      setStockOutBusy(false);
    }

    stockOutIssued.push(...(outcome.issued || []));
    if (!outcome.failed) {
      bootstrap.Modal.getInstance(so.modal)?.hide();
      showToast(`Stock issued for ${projectId} \u2014 ${plural(outcome.issued.length, 'item')}`, 'success');
      return;
    }
    stockOutCart = outcome.remaining.map(r => {
      const i = inventoryStore.find(r.itemId);
      return i ? { ...r, available: Number(i.qty) || 0 } : r;
    });
    renderStockOutCart();
    const names = list => list.map(r => `<strong>${escapeHTML(r.name)}</strong> (${NUM(r.requestedQty)} ${escapeHTML(r.unit)})`).join(', ');
    showStockOutResult(
      (outcome.issued.length
        ? `<div class="mb-1"><i class="bi bi-check-circle me-1"></i>Issued: ${names(outcome.issued)}.</div>`
        : `<div class="mb-1"><i class="bi bi-x-circle me-1"></i>Nothing was issued.</div>`)
      + `<div class="mb-1"><i class="bi bi-exclamation-triangle me-1"></i>Stopped at ${names([outcome.failed.row])}: ${escapeHTML(outcome.failed.error)}</div>`
      + `<div>The ${plural(stockOutCart.length, 'item')} still listed ${stockOutCart.length === 1 ? 'was' : 'were'} not issued. Adjust or remove ${stockOutCart.length === 1 ? 'it' : 'them'}, then confirm again.</div>`
      + (stockOutIssued.length ? `<div class="mt-1"><i class="bi bi-receipt me-1"></i>A receipt for the issued items appears when you finish or close this request.</div>` : ''));
    if (outcome.issued.length) showToast(`${plural(outcome.issued.length, 'item')} issued for ${projectId} \u2014 ${plural(stockOutCart.length, 'item')} still pending`, 'warning', 'bi-exclamation-triangle');
    else showToast(outcome.failed.error, 'error', 'bi-exclamation-triangle');
  });

  renderStockOutProjects();
  renderStockOutCart();

  const ret = {
    modal:  document.getElementById('returnModal'),
    form:   document.getElementById('returnForm'),
    search: document.getElementById('returnRefSearch'),
    results: document.getElementById('returnRefResults'),
    wrap:   document.getElementById('returnItemsWrap'),
    body:   document.getElementById('returnItemsBody'),
    submitBtn: document.getElementById('returnSubmitBtn'),
    viewBackOrdersBtn: document.getElementById('returnViewBackOrdersBtn'),
  };
  let returnSelectedRef = '';
  let returnRows = [];
  let returnIssued = [];
  let returnLastInfo = null;
  let returnBusy = false;

  function allBackOrderProjects(){
    return (typeof PROJECTS !== 'undefined' ? PROJECTS : [])
      .map(p => ({ ref: p.id, label: p.name, stocked: itemsForStockOutRef(p.id) }))
      .filter(p => p.stocked.length);
  }

  function itemsForStockOutRef(ref){
    const byItem = new Map();
    (window.ALL_MOVEMENTS || []).filter(m => m.type === 'ISSUANCE' && m.remarks === ref).forEach(m => {
      if (!byItem.has(m.id)) byItem.set(m.id, { itemId: m.id, name: m.name, unit: m.unit, stockedOut: 0 });
      byItem.get(m.id).stockedOut += Number(m.qty) || 0;
    });
    (window.ALL_BACKORDERS || []).filter(b => b.stockOutRef === ref).forEach(b => {
      const row = byItem.get(b.id);
      if (row) row.stockedOut -= Number(b.qty) || 0;
    });
    return [...byItem.values()].filter(r => r.stockedOut > 0);
  }

  function renderReturnItems(){
    if (!ret.body) return;
    ret.body.innerHTML = returnRows.map(r => `
      <tr data-item-id="${escapeHTML(r.itemId)}">
        <td><div class="fw-medium">${escapeHTML(r.name)}</div><div class="small text-muted-2">${escapeHTML(r.itemId)}</div></td>
        <td class="text-end">${NUM(r.stockedOut)} ${escapeHTML(r.unit)}</td>
        <td><input type="number" class="form-control form-control-sm text-end return-qty-input" min="0" max="${r.stockedOut}" step="any" value="0"></td>
      </tr>`).join('');
    ret.body.querySelectorAll('.return-qty-input').forEach(inp => {
      inp.addEventListener('input', () => {
        if (inp.value === '') return;
        let v = Number(inp.value);
        const max = Number(inp.max);
        if (Number.isFinite(max) && v > max) v = max;
        if (v < 0) v = 0;
        if (String(v) !== inp.value) inp.value = String(v);
      });
    });
  }

  function resetReturnPicker(){
    returnSelectedRef = '';
    returnRows = [];
    if (ret.search) { ret.search.value = ''; ret.search.setCustomValidity('Search and select a project from the list.'); }
    if (ret.wrap) ret.wrap.style.display = 'none';
    if (ret.body) ret.body.innerHTML = '';
    ret.results?.classList.remove('show');
  }

  function renderReturnRefResults(query){
    if (!ret.results) return;
    const q = query.trim().toLowerCase();
    const projects = allBackOrderProjects();
    const matches = q
      ? projects.filter(p => p.ref.toLowerCase().includes(q) || p.label.toLowerCase().includes(q))
      : projects;
    ret.results.innerHTML = matches.length
      ? matches.slice(0, 8).map(p => {
          const qty = p.stocked.reduce((s, r) => s + r.stockedOut, 0);
          return `<div class="isr-item" data-ref="${escapeHTML(p.ref)}">
              <div class="fw-medium">${escapeHTML(p.ref)} — ${escapeHTML(p.label)}</div>
              <div class="small text-muted-2">${plural(p.stocked.length, 'item')} stocked out • ${NUM(qty)} total</div>
            </div>`;
        }).join('')
      : `<div class="isr-empty">No matching project${projects.length ? '' : ' - nothing has been stocked out yet'}.</div>`;
    ret.results.classList.add('show');
    fitSearchResults(ret.search, ret.results);
  }

  if (ret.search && ret.results) {
    ret.search.addEventListener('focus', () => renderReturnRefResults(ret.search.value));
    ret.search.addEventListener('input', () => {
      returnSelectedRef = '';
      ret.search.setCustomValidity('Search and select a project from the list.');
      if (ret.wrap) ret.wrap.style.display = 'none';
      renderReturnRefResults(ret.search.value);
    });
    ret.results.addEventListener('mousedown', (e) => {
      const item = e.target.closest('.isr-item'); if (!item) return;
      const ref = item.dataset.ref;
      returnSelectedRef = ref;
      ret.search.value = ref;
      ret.search.setCustomValidity('');
      ret.results.classList.remove('show');
      returnRows = itemsForStockOutRef(ref);
      renderReturnItems();
      if (ret.wrap) ret.wrap.style.display = returnRows.length ? '' : 'none';
    });
    ret.search.addEventListener('blur', () => { setTimeout(() => ret.results.classList.remove('show'), 150); });
    ret.modal?.addEventListener('show.bs.modal', resetReturnPicker);
  }

  function setReturnBusy(busy, label){
    returnBusy = busy;
    ret.form?.querySelectorAll('[data-bs-dismiss="modal"]').forEach(b => b.disabled = busy);
    if (ret.submitBtn) {
      ret.submitBtn.disabled = busy;
      ret.submitBtn.innerHTML = busy
        ? `<span class="spinner-border spinner-border-sm me-2" aria-hidden="true"></span>${label || 'Recording…'}`
        : 'Confirm Return';
    }
  }

  function showReturnReceipt(){
    if (!returnIssued.length || !returnLastInfo) return;
    const info = returnLastInfo;
    const items = returnIssued.map(r => {
      const i = inventoryStore.find(r.itemId) || {};
      return { movementId: r.backOrderId, id: r.itemId, name: r.name, cat: i.cat, qty: r.qty, unit: r.unit, price: Number(i.price) || 0 };
    });
    window.showTransactionReceipt('RETURN', items, {
      when: info.when,
      fields: [['Project Code', info.ref], ['Received By', info.customer],
               ['Reason for Return', info.remarks],
               ['Disposition', 'Pending (mark Reimbursed / Replaced in the Back Orders table)'],
               ['Recorded / Inspected by', info.user]],
      recordedBy: info.user, counterparty: info.customer || '',
      note: 'Back orders are logged for the record and do not change on-hand stock.',
    });
  }

  function scrollToBackOrdersTable(){
    const table = document.getElementById('returnsTable');
    const card = table?.closest('.card');
    if (!card) return;
    card.scrollIntoView({ behavior: 'smooth', block: 'start' });
    card.classList.add('highlight-flash');
    setTimeout(() => card.classList.remove('highlight-flash'), 1800);
  }

  ret.viewBackOrdersBtn?.addEventListener('click', () => {
    if (ret.modal.classList.contains('show')) {
      ret.modal.addEventListener('hidden.bs.modal', scrollToBackOrdersTable, { once: true });
      bootstrap.Modal.getInstance(ret.modal)?.hide();
    } else {
      scrollToBackOrdersTable();
    }
  });

  ret.modal?.addEventListener('hidden.bs.modal', () => {
    if (returnBusy) return;
    showReturnReceipt();
    returnIssued = []; returnLastInfo = null;
    resetReturnPicker();
    ret.form?.reset();
  });
  ret.modal?.addEventListener('hide.bs.modal', (e) => { if (returnBusy) e.preventDefault(); });

  ret.form?.addEventListener('submit', async (e) => {
    e.preventDefault();
    if (returnBusy) return;
    if (!returnSelectedRef) {
      ret.search.setCustomValidity('Search and select a project from the list.');
      ret.search.reportValidity();
      return;
    }
    const rows = [...ret.body.querySelectorAll('tr')].map(tr => ({
      itemId: tr.dataset.itemId,
      qty: Number(tr.querySelector('.return-qty-input')?.value) || 0,
    })).filter(r => r.qty > 0);
    if (!rows.length) {
      showToast('Set a Qty to Return greater than 0 for at least one item.', 'error', 'bi-exclamation-triangle');
      return;
    }

    const d = Object.fromEntries(new FormData(ret.form));
    const user = (typeof CURRENT_USER !== 'undefined' && CURRENT_USER.name) || '';
    returnIssued = [];
    let failedRow = null, failedError = '';
    setReturnBusy(true);
    for (let k = 0; k < rows.length; k++) {
      const row = rows[k];
      const item = returnRows.find(r => r.itemId === row.itemId) || {};
      setReturnBusy(true, `Recording ${k + 1} of ${rows.length}…`);
      try {
        const res = await fetch('/api/inventory/return', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ itemId: row.itemId, qty: row.qty, customer: d.customer, remarks: d.remarks, stockOutRef: returnSelectedRef }),
        });
        let json;
        try { json = await res.json(); }
        catch (_) { throw new Error(`The server returned an unexpected response (HTTP ${res.status}).`); }
        if (!json.ok) throw new Error(json.error || `Request failed (HTTP ${res.status}).`);
        returnIssued.push({ itemId: row.itemId, name: item.name, unit: item.unit, qty: row.qty, backOrderId: json.backOrderId });
      } catch (err) {
        failedRow = row;
        failedError = err instanceof TypeError ? 'Could not connect to the server.' : err.message;
        break;
      }
    }
    setReturnBusy(false);

    if (!failedRow) {
      returnLastInfo = { when: window.receiptNow(), customer: d.customer, ref: returnSelectedRef, remarks: d.remarks, user };
      await refreshInventory();
      bootstrap.Modal.getInstance(ret.modal)?.hide();
      showToast(`Back-order return recorded — ${plural(returnIssued.length, 'item')}`, 'success', undefined, {
        label: 'View Back Order',
        onClick: scrollToBackOrdersTable,
      });
      return;
    }
    if (returnIssued.length) {
      await refreshInventory();
      returnIssued.forEach(r => {
        const input = ret.body.querySelector(`tr[data-item-id="${CSS.escape(r.itemId)}"] .return-qty-input`);
        if (input) input.value = '0';
      });
    }
    const failedItem = returnRows.find(r => r.itemId === failedRow.itemId) || {};
    showToast(
      (returnIssued.length ? `${plural(returnIssued.length, 'item')} recorded, ` : 'Nothing was recorded — ') +
      `stopped at ${failedItem.name || failedRow.itemId}: ${failedError}`,
      'error', 'bi-exclamation-triangle');
  });

  window.ALL_MOVEMENTS = window.ALL_MOVEMENTS || [];
  window.ALL_BACKORDERS = window.ALL_BACKORDERS || [];
  window.STOCK_SUMMARY = window.STOCK_SUMMARY || [];

  const MOVE_PAGE_SIZE = 10;
  let stockInPage  = 1;
  let stockOutPage = 1;
  let returnsPage  = 1;
  let summaryPage  = 1;
  let moveSearchQuery = '';
  let moveCategoryFilter = '';
  let moveDateFrom = '';
  let moveDateTo = '';

  function resetAllPages(){
    stockInPage = 1; stockOutPage = 1; returnsPage = 1; summaryPage = 1;
  }

  document.getElementById('moveSearchInput')?.addEventListener('input', (e) => {
    moveSearchQuery = e.target.value.toLowerCase().trim();
    resetAllPages();
    renderMovements(); renderBackOrders(); renderStockSummary();
  });
  document.getElementById('moveCategoryFilter')?.addEventListener('change', (e) => {
    moveCategoryFilter = e.target.value;
    resetAllPages();
    renderMovements(); renderBackOrders(); renderStockSummary();
  });
  document.getElementById('moveDateFrom')?.addEventListener('change', (e) => {
    moveDateFrom = e.target.value;
    resetAllPages();
    renderMovements(); renderBackOrders();
  });
  document.getElementById('moveDateTo')?.addEventListener('change', (e) => {
    moveDateTo = e.target.value;
    resetAllPages();
    renderMovements(); renderBackOrders();
  });
  document.getElementById('moveDateClearBtn')?.addEventListener('click', () => {
    moveDateFrom = ''; moveDateTo = ''; moveSearchQuery = '';
    const fromEl = document.getElementById('moveDateFrom');
    const toEl = document.getElementById('moveDateTo');
    const searchEl = document.getElementById('moveSearchInput');
    if (fromEl) fromEl.value = '';
    if (toEl) toEl.value = '';
    if (searchEl) searchEl.value = '';
    resetAllPages();
    renderMovements(); renderBackOrders(); renderStockSummary();
  });

  document.getElementById('stockTableSearchBtn')?.addEventListener('click', () => {
    resetAllPages();
    renderMovements(); renderBackOrders(); renderStockSummary();
  });

  function buildMovePagination(navId, ulId, currentPage, totalItems, onChange){
    const totalPages = Math.max(1, Math.ceil(totalItems / MOVE_PAGE_SIZE));
    const clampedPage = Math.min(currentPage, totalPages);
    const nav = document.getElementById(navId);
    const ul  = document.getElementById(ulId);
    if (!nav || !ul) return clampedPage;
    if (totalPages <= 1) { nav.style.display = 'none'; return clampedPage; }
    nav.style.display = '';
    const pageLink = (label, page, opts = {}) => `
      <li class="page-item ${opts.active ? 'active' : ''} ${opts.disabled ? 'disabled' : ''}">
        <a class="page-link" href="#" data-page="${page}">${label}</a>
      </li>`;
    let html = pageLink('<i class="bi bi-chevron-left"></i>', clampedPage - 1, { disabled: clampedPage === 1 });
    buildPageWindow(clampedPage, totalPages).forEach(p => {
      if (p === '\u2026') html += `<li class="page-item disabled"><span class="page-link">\u2026</span></li>`;
      else html += pageLink(p, p, { active: p === clampedPage });
    });
    html += pageLink('<i class="bi bi-chevron-right"></i>', clampedPage + 1, { disabled: clampedPage === totalPages });
    ul.innerHTML = html;
    ul.onclick = (e) => {
      const link = e.target.closest('[data-page]');
      if (!link || link.closest('.disabled')) return;
      e.preventDefault();
      const page = parseInt(link.dataset.page, 10);
      if (!page || page === clampedPage) return;
      onChange(page);
    };
    return clampedPage;
  }

  function fmtDeliveredAt(iso){
    const d = new Date(iso);
    if (isNaN(d)) return '';
    return d.toLocaleDateString('en-PH', { year: 'numeric', month: 'long', day: 'numeric' })
      + ' \u00b7 ' + d.toLocaleTimeString('en-PH', { hour: 'numeric', minute: '2-digit' });
  }
  function deliveryInfo(m){
    const weather = { temp: m.deliveryTemp, rain: m.deliveryRain, wind: m.deliveryWind };
    if (m.returnedAt) return { status: 'Returned', at: fmtDeliveredAt(m.returnedAt),
                               reason: m.deliveryFailureReason || '', weather };
    if (m.deliveredAt) return { status: 'Delivered', at: fmtDeliveredAt(m.deliveredAt), weather };
    if (m.deliveryFailedAt) return { status: 'Failed', at: fmtDeliveredAt(m.deliveryFailedAt),
                                     reason: m.deliveryFailureReason || '', weather };
    return { status: 'Pending', at: '', weather };
  }
  function deliveryCell(m){
    if (m.returnedAt) {
      return `<td><span class="badge b-neutral"><i class="bi bi-arrow-counterclockwise me-1"></i>Returned</span>
        <div class="small text-muted-2 mt-1">${escapeHTML(fmtDeliveredAt(m.returnedAt))}</div></td>`;
    }
    if (m.deliveredAt) {
      return `<td><span class="badge b-success"><i class="bi bi-check-circle-fill me-1"></i>Delivered</span>
        <div class="small text-muted-2 mt-1">${escapeHTML(fmtDeliveredAt(m.deliveredAt))}</div></td>`;
    }
    if (m.deliveryFailedAt) {
      const r = m.deliveryFailureReason || '';
      return `<td><span class="badge b-danger"><i class="bi bi-pause-circle-fill me-1"></i>Standby</span>
        <div class="small text-muted-2 mt-1">Failed ${escapeHTML(fmtDeliveredAt(m.deliveryFailedAt))}</div>
        ${r ? `<div class="small mt-1" title="${escapeHTML(r)}">${escapeHTML(r.length > 60 ? r.slice(0,60)+'\u2026' : r)}</div>` : ''}
        <div class="d-inline-flex gap-1 mt-1">
          <button type="button" class="btn btn-sm btn-light-2 py-0 px-2" data-redeliver data-movement-id="${m.movementId}">
            <i class="bi bi-arrow-repeat me-1"></i>Re-deliver</button>
          <button type="button" class="btn btn-sm btn-outline-secondary py-0 px-2" data-return-stock data-movement-id="${m.movementId}">
            <i class="bi bi-box-arrow-in-down me-1"></i>Return to inventory</button>
        </div></td>`;
    }
    return `<td><span class="badge b-warning me-1">Pending</span>
      <div class="d-inline-flex gap-1 mt-1">
        <button type="button" class="btn btn-sm btn-light-2 py-0 px-2" data-deliver data-movement-id="${m.movementId}">
          <i class="bi bi-truck me-1"></i>Mark as Delivered</button>
        <button type="button" class="btn btn-sm btn-outline-danger py-0 px-2" data-deliver-fail data-movement-id="${m.movementId}">
          <i class="bi bi-x-octagon me-1"></i>Failed</button>
      </div></td>`;
  }
  async function postDeliveryOutcome(movementId, status, reason, btn){
    if (btn) btn.disabled = true;
    try {
      const res = await fetch('/api/inventory/stock-out/deliver', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ movementId, status, reason }),
      });
      const json = await res.json();
      if (!json.ok) throw new Error(json.error);
      if (typeof window.refreshInventory === 'function') await window.refreshInventory();
      showToast(status === 'Delivered' ? 'Stock Out marked as Delivered' : 'Stock Out marked as Failed',
                status === 'Delivered' ? 'success' : 'warning',
                status === 'Delivered' ? 'bi-truck' : 'bi-x-octagon');
      return true;
    } catch (err) {
      if (btn) btn.disabled = false;
      showToast(err.message, 'error', 'bi-exclamation-triangle');
      return false;
    }
  }
  async function markDelivered(movementId, btn){ return postDeliveryOutcome(movementId, 'Delivered', '', btn); }
  async function postStandbyAction(movementId, action, btn){
    if (btn) btn.disabled = true;
    try {
      const res = await fetch(`/api/inventory/stock-out/${action}`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ movementId }),
      });
      const json = await res.json();
      if (!json.ok) throw new Error(json.error);
      if (typeof window.refreshInventory === 'function') await window.refreshInventory();
      showToast(action === 'redeliver' ? 'Back to Pending for another delivery' : 'Materials returned to inventory',
                'success', action === 'redeliver' ? 'bi-truck' : 'bi-box-arrow-in-down');
    } catch (err) {
      if (btn) btn.disabled = false;
      showToast(err.message, 'error', 'bi-exclamation-triangle');
    }
  }

  (function wireDeliverFailModal(){
    const modal = document.getElementById('deliverFailModal');
    if (!modal) return;
    const form = document.getElementById('deliverFailForm');
    const reason = document.getElementById('deliverFailReason');
    const movNo = document.getElementById('deliverFailMovNo');
    const submit = document.getElementById('deliverFailSubmit');
    let pending = null;
    window.openDeliverFailModal = (movementId) => {
      pending = movementId;
      reason.value = '';
      submit.disabled = false;
      movNo.textContent = 'MOV-' + String(movementId).padStart(4, '0');
      bootstrap.Modal.getOrCreateInstance(modal).show();
      setTimeout(() => reason.focus(), 200);
    };
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      const txt = reason.value.trim();
      if (!txt) { reason.focus(); return; }
      submit.disabled = true;
      const ok = await postDeliveryOutcome(pending, 'Failed', txt, submit);
      if (ok) bootstrap.Modal.getInstance(modal).hide();
    });
  })();

  function moveActionBtns(m){
    return `<div class="d-inline-flex">
        <button class="act-btn" data-bs-toggle="tooltip" title="View" data-act="view" data-id="${m.id}"><i class="bi bi-eye"></i></button>
        <button class="act-btn print-move" data-bs-toggle="tooltip" title="Print Slip" data-movement-id="${m.movementId}"><i class="bi bi-printer"></i></button>
        <button class="act-btn danger" data-bs-toggle="tooltip" title="Delete" data-act="del" data-id="${m.id}"><i class="bi bi-trash"></i></button>
      </div>`;
  }

  function backOrderActionBtns(m){
    const reimbursed = m.disposition === 'Reimbursed';
    const replaced = m.disposition === 'Replaced';
    const locked = reimbursed || replaced;
    const lockCls = locked ? ' is-locked' : '';
    const lockAttr = locked ? ' aria-disabled="true"' : '';
    const reimbursedTitle = reimbursed
      ? `Reimbursed (${PESO(m.reimbursedAmount || 0)}) \u2014 final, can\u2019t be changed`
      : (locked ? 'Already marked Replaced \u2014 can\u2019t be changed' : 'Mark as Reimbursed');
    const replacedTitle = replaced
      ? `Replaced (${NUM(m.replacedQty != null ? m.replacedQty : m.qty)} ${m.unit}) \u2014 final, can\u2019t be changed`
      : (locked ? 'Already marked Reimbursed \u2014 can\u2019t be changed' : 'Mark as Replaced');
    return `<div class="d-inline-flex gap-1">
        <button type="button" class="disposition-btn${reimbursed ? ' is-active is-reimbursed' : ''}${lockCls}"${lockAttr}
                data-disposition-btn data-disposition="Reimbursed" data-movement-id="${m.movementId}"
                data-bs-toggle="tooltip" title="${reimbursedTitle}">
          <i class="bi ${reimbursed ? 'bi-check-circle-fill' : 'bi-circle'}"></i> Reimbursed
        </button>
        <button type="button" class="disposition-btn${replaced ? ' is-active is-replaced' : ''}${lockCls}"${lockAttr}
                data-disposition-btn data-disposition="Replaced" data-movement-id="${m.movementId}"
                data-bs-toggle="tooltip" title="${replacedTitle}">
          <i class="bi ${replaced ? 'bi-check-circle-fill' : 'bi-circle'}"></i> Replaced
        </button>
        <button class="act-btn print-move" data-bs-toggle="tooltip" title="Print Receipt" data-movement-id="${m.movementId}"><i class="bi bi-printer"></i></button>
      </div>`;
  }

  function showMoveSlip(movementId){
    const m = (window.ALL_MOVEMENTS || []).find(x => x.movementId === movementId)
           || (window.ALL_BACKORDERS || []).find(x => x.movementId === movementId);
    if (!m) return;
    const item = inventoryStore.find(m.id) || {};
    const common = [['Date Recorded', m.date], ['Recorded by', m.recordedBy]];
    const fields = m.type === 'RECEIPT'
      ? [['Supplier', item.sup], ['Warehouse / Location', item.loc], ['Remarks / Reference', m.remarks], ...common]
      : m.type === 'ISSUANCE'
        ? [['Project / Reference', m.remarks], ['Location', item.loc], ...common]
        : [['Project Code', m.stockOutRef], ['Received By', m.backOrderBy], ['Reason for Return', m.remarks],
           ['Disposition', m.disposition || 'Pending'], ['Location', item.loc], ...common];
    window.showTransactionReceipt(m.type, [{
      movementId: m.movementId, id: m.id, name: m.name, cat: m.cat, qty: m.qty, unit: m.unit, price: Number(item.price) || 0,
    }], {
      when: m.date, fields,
      weather: m.type === 'ISSUANCE' ? { temp: m.weatherTemp, rain: m.weatherRain, wind: m.weatherWind } : null,
      delivery: m.type === 'ISSUANCE' ? deliveryInfo(m) : null,
      recordedBy: m.recordedBy && m.recordedBy !== '\u2014' ? m.recordedBy : '',
      counterparty: m.type === 'RECEIPT' ? (item.sup || '') : (m.type === 'RETURN' ? (m.backOrderBy || '') : ''),
      note: 'Reprint of a recorded movement. Unit price shown is the item\u2019s current price.',
    });
  }

  function renderMoveSection(rows, currentPage, ids, onPageChange, emptyNoun, showBackOrderedBy, showDelivery){
    const totalPages = Math.max(1, Math.ceil(rows.length / MOVE_PAGE_SIZE));
    const clampedPage = Math.min(currentPage, totalPages);
    const start = (clampedPage - 1) * MOVE_PAGE_SIZE;
    const pageItems = rows.slice(start, start + MOVE_PAGE_SIZE);
    const colCount = (showBackOrderedBy || showDelivery) ? 8 : 7;

    const tbody = document.getElementById(ids.tbody);
    tbody.innerHTML = '';
    if (pageItems.length === 0) {
      const reason = (moveSearchQuery || moveCategoryFilter || moveDateFrom || moveDateTo) ? 'match your search or filter' : 'yet';
      tbody.insertAdjacentHTML('beforeend', `<tr><td colspan="${colCount}" class="text-center text-muted-2 py-4">
        No ${emptyNoun} records ${reason}.</td></tr>`);
    }
    pageItems.forEach(m => {
      const backOrderedByCell = showBackOrderedBy
        ? `<td class="text-muted-2">${escapeHTML(m.backOrderBy || '\u2014')}</td>` : '';
      tbody.insertAdjacentHTML('beforeend', `<tr>
        <td><div class="fw-medium">${escapeHTML(m.name)}</div><div class="small text-muted-2">${m.id}</div></td>
        <td><span class="tag-chip">${escapeHTML(m.cat)}</span></td>
        <td class="text-end">${NUM(m.qty)} <span class="text-muted-2">${m.unit}</span></td>
        <td class="text-muted-2">${m.date}</td>
        <td class="text-muted-2">${escapeHTML(m.remarks || '\u2014')}</td>
        ${backOrderedByCell}
        <td class="text-muted-2">${escapeHTML(m.recordedBy || '\u2014')}</td>
        ${showDelivery ? deliveryCell(m) : ''}
        <td class="text-center">${showBackOrderedBy ? backOrderActionBtns(m) : moveActionBtns(m)}</td></tr>`);
    });
    initTooltips(tbody);
    set(ids.count, pageItems.length === rows.length
      ? `Showing ${rows.length} record${rows.length===1?'':'s'}`
      : `Showing ${start+1}\u2013${start+pageItems.length} of ${rows.length} records`);
    buildMovePagination(ids.nav, ids.ul, clampedPage, rows.length, onPageChange);
    return clampedPage;
  }

  function matchesMoveFilters(m){
    if (moveCategoryFilter && m.cat !== moveCategoryFilter) return false;
    if (moveSearchQuery) {
      const hay = `${m.id} ${m.name}`.toLowerCase();
      if (!hay.includes(moveSearchQuery)) return false;
    }
    const moveDate = (m.date || '').slice(0, 10);
    if (moveDateFrom && moveDate < moveDateFrom) return false;
    if (moveDateTo && moveDate > moveDateTo) return false;
    return true;
  }

  function renderMovements(){
    const filtered = (window.ALL_MOVEMENTS || []).filter(matchesMoveFilters);
    const inRows  = filtered.filter(m => m.type === 'RECEIPT');
    const outRows = filtered.filter(m => m.type === 'ISSUANCE');

    stockInPage = renderMoveSection(inRows, stockInPage,
      { tbody: 'stockInBody', count: 'stockInCount', nav: 'stockInPaginationNav', ul: 'stockInPagination' },
      (p) => { stockInPage = p; renderMovements(); }, 'stock-in');

    stockOutPage = renderMoveSection(outRows, stockOutPage,
      { tbody: 'stockOutBody', count: 'stockOutCount', nav: 'stockOutPaginationNav', ul: 'stockOutPagination' },
      (p) => { stockOutPage = p; renderMovements(); }, 'stock-out', false, true);
  }
  window.renderMovements = renderMovements;

  function renderBackOrders(){
    const retRows = (window.ALL_BACKORDERS || []).filter(matchesMoveFilters);
    returnsPage = renderMoveSection(retRows, returnsPage,
      { tbody: 'returnsBody', count: 'returnsCount', nav: 'returnsPaginationNav', ul: 'returnsPagination' },
      (p) => { returnsPage = p; renderBackOrders(); }, 'back-order', true);
  }
  window.renderBackOrders = renderBackOrders;

  function renderStockSummary(){
    const rows = (window.STOCK_SUMMARY || []).filter(r => {
      if (moveCategoryFilter && r.cat !== moveCategoryFilter) return false;
      if (moveSearchQuery) {
        const hay = `${r.id} ${r.name}`.toLowerCase();
        if (!hay.includes(moveSearchQuery)) return false;
      }
      return true;
    });
    const totalPages  = Math.max(1, Math.ceil(rows.length / MOVE_PAGE_SIZE));
    const clampedPage = Math.min(summaryPage, totalPages);
    summaryPage = clampedPage;
    const start     = (clampedPage - 1) * MOVE_PAGE_SIZE;
    const pageItems = rows.slice(start, start + MOVE_PAGE_SIZE);

    const tbody = document.getElementById('stockSummaryBody');
    if (!tbody) return;
    tbody.innerHTML = '';
    if (pageItems.length === 0) {
      const reason = (moveSearchQuery || moveCategoryFilter) ? 'match your search or filter' : 'yet';
      tbody.insertAdjacentHTML('beforeend', `<tr><td colspan="8" class="text-center text-muted-2 py-4">
        No items ${reason}.</td></tr>`);
    }
    pageItems.forEach(r => {
      tbody.insertAdjacentHTML('beforeend', `<tr>
        <td class="fw-id">${escapeHTML(r.id)}</td>
        <td class="fw-medium">${escapeHTML(r.name)}</td>
        <td><span class="tag-chip">${escapeHTML(r.cat)}</span></td>
        <td class="text-end text-success">${NUM(r.totalIn)} <span class="text-muted-2">${r.unit}</span></td>
        <td class="text-end text-danger">${NUM(r.totalOut)} <span class="text-muted-2">${r.unit}</span></td>
        <td class="text-end" style="color:var(--primary)">${NUM(r.backOrder)} <span class="text-muted-2">${r.unit}</span></td>
        <td class="text-end fw-medium">${NUM(r.netStock)} <span class="text-muted-2">${r.unit}</span></td>
        <td class="text-center">
          <button type="button" class="act-btn" data-bs-toggle="tooltip" title="Edit this item"
                  data-edit-item="${escapeHTML(r.id)}"><i class="bi bi-pencil"></i></button>
        </td>
      </tr>`);
    });
    initTooltips(tbody);
    set('stockSummaryCount', pageItems.length === rows.length
      ? `Showing ${rows.length} item${rows.length===1?'':'s'}`
      : `Showing ${start+1}–${start+pageItems.length} of ${rows.length} items`);
    buildMovePagination('stockSummaryPaginationNav', 'stockSummaryPagination',
      clampedPage, rows.length,
      (p) => { summaryPage = p; renderStockSummary(); });
  }
  window.renderStockSummary = renderStockSummary;

  async function setBackOrderDisposition(backOrderId, disposition, extra){
    try {
      const res = await fetch('/api/inventory/return/disposition', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(Object.assign({ backOrderId, disposition }, extra || {})),
      });
      const json = await res.json();
      if (!json.ok) throw new Error(json.error);
      if (typeof window.refreshInventory === 'function') await window.refreshInventory();
      showToast(json.disposition ? `Marked as ${json.disposition}` : 'Disposition cleared', 'success');
      return true;
    } catch (err) {
      showToast(err.message, 'error', 'bi-exclamation-triangle');
      return false;
    }
  }

  const dispoModalEl = document.getElementById('dispositionModal');
  const dispoModal = dispoModalEl ? new bootstrap.Modal(dispoModalEl) : null;
  const dispo = {
    form: document.getElementById('dispositionForm'),
    title: document.getElementById('dispoTitle'),
    itemName: document.getElementById('dispoItemName'),
    itemId: document.getElementById('dispoItemId'),
    supplier: document.getElementById('dispoSupplier'),
    receivedBy: document.getElementById('dispoReceivedBy'),
    qtyReturned: document.getElementById('dispoQtyReturned'),
    date: document.getElementById('dispoDate'),
    maxQtyHint: document.getElementById('dispoMaxQtyHint'),
    replacedWrap: document.getElementById('dispoReplacedWrap'),
    reimbursedWrap: document.getElementById('dispoReimbursedWrap'),
    qtyInput: document.getElementById('dispoQtyInput'),
    amountInput: document.getElementById('dispoAmountInput'),
    notes: document.getElementById('dispoNotes'),
    submitBtn: document.getElementById('dispoSubmitBtn'),
  };
  let dispoState = null;
  let dispoBusy = false;

  function setDispoBusy(busy, label){
    dispoBusy = busy;
    dispo.form?.querySelectorAll('[data-bs-dismiss="modal"]').forEach(b => b.disabled = busy);
    if (dispo.submitBtn) {
      dispo.submitBtn.disabled = busy;
      dispo.submitBtn.innerHTML = busy
        ? `<span class="spinner-border spinner-border-sm me-2" aria-hidden="true"></span>${label || 'Saving…'}`
        : 'Confirm';
    }
  }

  function openDispositionModal(m, disposition){
    if (!dispoModal || !dispo.form) { setBackOrderDisposition(m.movementId, disposition); return; }
    const item = inventoryStore.find(m.id) || {};
    dispoState = { backOrderId: m.movementId, disposition, maxQty: Number(m.qty) || 0 };

    dispo.title.innerHTML = disposition === 'Replaced'
      ? '<i class="bi bi-check2-circle me-2" style="color:var(--primary)"></i>Mark as Replaced'
      : '<i class="bi bi-check2-circle me-2" style="color:var(--primary)"></i>Mark as Reimbursed';
    dispo.itemName.textContent = m.name;
    dispo.itemId.textContent = m.id;
    dispo.supplier.textContent = item.sup || '—';
    dispo.receivedBy.textContent = m.backOrderBy || '—';
    dispo.qtyReturned.textContent = `${NUM(m.qty)} ${m.unit}`;
    dispo.date.textContent = m.date || '—';
    dispo.maxQtyHint.textContent = `${NUM(m.qty)} ${m.unit}`;

    const isReplaced = disposition === 'Replaced';
    dispo.replacedWrap.style.display = isReplaced ? '' : 'none';
    dispo.reimbursedWrap.style.display = isReplaced ? 'none' : '';
    dispo.qtyInput.required = isReplaced;
    dispo.amountInput.required = !isReplaced;

    if (isReplaced) {
      dispo.qtyInput.max = String(dispoState.maxQty);
      dispo.qtyInput.value = m.replacedQty != null ? m.replacedQty : dispoState.maxQty;
    } else {
      const unitPrice = Number(item.price) || 0;
      dispo.amountInput.value = m.reimbursedAmount != null
        ? m.reimbursedAmount
        : (dispoState.maxQty * unitPrice).toFixed(2);
    }
    dispo.notes.value = m.dispositionNotes || '';

    setDispoBusy(false);
    dispoModal.show();
  }

  dispo.form?.addEventListener('submit', async (e) => {
    e.preventDefault();
    if (!dispoState || dispoBusy) return;
    const { backOrderId, disposition, maxQty } = dispoState;
    const extra = { notes: dispo.notes.value.trim() };

    if (disposition === 'Replaced') {
      const qty = parseFloat(dispo.qtyInput.value);
      if (!Number.isFinite(qty) || qty <= 0) return showToast('Enter how many units were replaced.', 'error', 'bi-exclamation-triangle');
      if (qty > maxQty) return showToast(`Qty Replaced can’t exceed ${NUM(maxQty)} (the amount returned).`, 'error', 'bi-exclamation-triangle');
      extra.qty = qty;
    } else {
      const amount = parseFloat(dispo.amountInput.value);
      if (!Number.isFinite(amount) || amount <= 0) return showToast('Enter the amount reimbursed.', 'error', 'bi-exclamation-triangle');
      extra.amount = amount;
    }

    setDispoBusy(true);
    const ok = await setBackOrderDisposition(backOrderId, disposition, extra);
    setDispoBusy(false);
    if (ok) dispoModal.hide();
  });

  function handleRowAction(e){
    const delBtn = e.target.closest('[data-deliver]');
    if (delBtn) { markDelivered(parseInt(delBtn.dataset.movementId, 10), delBtn); return; }

    const failBtn = e.target.closest('[data-deliver-fail]');
    if (failBtn) { window.openDeliverFailModal(parseInt(failBtn.dataset.movementId, 10)); return; }

    const reBtn = e.target.closest('[data-redeliver]');
    if (reBtn) { postStandbyAction(parseInt(reBtn.dataset.movementId, 10), 'redeliver', reBtn); return; }

    const retBtn = e.target.closest('[data-return-stock]');
    if (retBtn) {
      const mid = parseInt(retBtn.dataset.movementId, 10);
      confirmDelete(`Return MOV-${String(mid).padStart(4, '0')} to inventory? The quantity goes back to stock and no longer counts as used.`,
        () => postStandbyAction(mid, 'return-to-stock', retBtn), { title: 'Return to Inventory', button: 'Return' });
      return;
    }

    const printBtn = e.target.closest('.print-move');
    if (printBtn) { showMoveSlip(parseInt(printBtn.dataset.movementId, 10)); return; }

    const dispBtn = e.target.closest('[data-disposition-btn]');
    if (dispBtn) {
      const backOrderId = parseInt(dispBtn.dataset.movementId, 10);
      const m = (window.ALL_BACKORDERS || []).find(x => x.movementId === backOrderId);
      const clicked = dispBtn.dataset.disposition;
      if (m && m.disposition) return;
      if (m) openDispositionModal(m, clicked);
      return;
    }

    const btn = e.target.closest('[data-act]'); if (!btn) return;
    const i = inventoryStore.find(btn.dataset.id); if (!i) return;
    if (btn.dataset.act === 'view') openDetail(i);
    if (btn.dataset.act === 'del')
      confirmDelete(`Delete "${i.name}" (${i.id})? This cannot be undone.`, () => {
        inventoryStore.remove(i.id);
        window.ALL_MOVEMENTS = (window.ALL_MOVEMENTS || []).filter(m => m.id !== i.id);
        window.ALL_BACKORDERS = (window.ALL_BACKORDERS || []).filter(m => m.id !== i.id);
        renderInventory();
        showToast(`${i.name} deleted`, 'success', 'bi-trash');
      });
  }
  document.getElementById('stockInBody').addEventListener('click', handleRowAction);
  document.getElementById('stockOutBody').addEventListener('click', handleRowAction);
  document.getElementById('returnsBody')?.addEventListener('click', handleRowAction);

  /* Item Edit Sidebar wiring */
  (function wireEditItemSidebar(){
    const sidebarEl = document.getElementById('editItemSidebar');
    if (!sidebarEl) return;
    const sidebar = bootstrap.Offcanvas.getOrCreateInstance(sidebarEl);
    const form = document.getElementById('editItemForm');
    const saveBtn = document.getElementById('editItemSaveBtn');
    let currentItem = null;
    let currentOnHand = 0;

    function populateSuppliers(selected){
      const sel = document.getElementById('editItemSupplier');
      sel.innerHTML = (window.SUPPLIERS_CACHE_FOR_EDIT || SUPPLIERS_CACHE)
        .map(s => `<option value="${escapeHTML(s.name)}">${escapeHTML(s.name)}</option>`).join('');
      if (selected && !sel.querySelector(`option[value="${CSS.escape(selected)}"]`)) {
        const o = document.createElement('option');
        o.value = o.textContent = selected;
        sel.insertBefore(o, sel.firstChild);
      }
      if (selected) sel.value = selected;
    }
    function openForItem(i){
      currentItem = i;
      currentOnHand = Number(i.qty) || 0;
      document.getElementById('editItemEditId').value = i.id;
      document.getElementById('editItemCode').textContent = i.id;
      document.getElementById('editItemName').value = i.name || '';
      document.getElementById('editItemPrice').value = Number(i.price || 0).toFixed(2);
      document.getElementById('editItemReorder').value = i.reorder || 0;
      document.getElementById('editItemOnHand').textContent = `${NUM(currentOnHand)} ${i.unit || ''}`;
      const cat = document.getElementById('editItemCat');
      if (i.cat && ![...cat.options].some(o => o.value === i.cat || o.textContent === i.cat)) {
        const extra = document.createElement('option');
        extra.textContent = i.cat; cat.appendChild(extra);
      }
      cat.value = i.cat || '';
      const unit = document.getElementById('editItemUnit');
      if (i.unit && ![...unit.options].some(o => o.value === i.unit || o.textContent === i.unit)) {
        const extra = document.createElement('option');
        extra.textContent = i.unit; unit.appendChild(extra);
      }
      unit.value = i.unit || 'pcs';
      const loc = document.getElementById('editItemLoc');
      if (i.loc && ![...loc.options].some(o => o.value === i.loc || o.textContent === i.loc)) {
        const extra = document.createElement('option');
        extra.textContent = i.loc; loc.appendChild(extra);
      }
      loc.value = i.loc || 'Warehouse A';
      populateSuppliers(i.sup || '');
      form.classList.remove('was-validated');
      sidebar.show();
    }
    document.getElementById('stockSummaryBody')?.addEventListener('click', (e) => {
      const btn = e.target.closest('[data-edit-item]'); if (!btn) return;
      const i = inventoryStore.find(btn.dataset.editItem); if (!i) return;
      openForItem(i);
    });

    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      if (!form.checkValidity()) { form.classList.add('was-validated'); return; }
      saveBtn.disabled = true;
      try {
        const payload = {
          edit_id: currentItem.id,
          name:    document.getElementById('editItemName').value.trim(),
          cat:     document.getElementById('editItemCat').value,
          sup:     document.getElementById('editItemSupplier').value,
          unit:    document.getElementById('editItemUnit').value,
          price:   document.getElementById('editItemPrice').value,
          reorder: document.getElementById('editItemReorder').value,
          loc:     document.getElementById('editItemLoc').value,
        };
        const res = await fetch('/api/inventory/save', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
        const json = await res.json();
        if (!json.ok) throw new Error(json.error || 'Save failed.');
        if (typeof window.refreshInventory === 'function') await window.refreshInventory();
        showToast(`${payload.name} updated`, 'success', 'bi-check-circle');
        sidebar.hide();
      } catch (err) {
        showToast(err.message, 'error', 'bi-exclamation-triangle');
      } finally {
        saveBtn.disabled = false;
      }
    });
  })();

  function renderInventory(){
    const items = inventoryStore.all();

    const low = items.filter(i => i.status === 'Low Stock');
    const out = items.filter(i => i.status === 'Out of Stock');
    set('lowStockCount', low.length); set('outStockCount', out.length);
    const row = (i, color, qtyText) => `
      <div class="sl-item">
        <div><div class="sl-name">${escapeHTML(i.name)}</div><div class="sl-sub">${i.loc} · Reorder at ${NUM(i.reorder)} ${i.unit}</div></div>
        <div class="sl-qty" style="color:${color}">${qtyText}</div>
      </div>`;
    document.getElementById('lowStockList').innerHTML = low.length
      ? low.map(i => row(i, 'var(--accent-dark)', `${NUM(i.qty)} ${i.unit}`)).join('')
      : '<div class="stock-empty">No low-stock materials.</div>';
    document.getElementById('outStockList').innerHTML = out.length
      ? out.map(i => row(i, 'var(--primary)', `0 ${i.unit}`)).join('')
      : '<div class="stock-empty">No out-of-stock materials.</div>';

    const todayStr = new Date().toISOString().slice(0, 10);
    const newStock = (window.ALL_MOVEMENTS || [])
      .filter(m => m.type === 'RECEIPT' && (m.date || '').slice(0, 10) === todayStr);
    set('newStockCount', newStock.length);
    document.getElementById('newStockList').innerHTML = newStock.length
      ? newStock.map(m => `
        <div class="sl-item">
          <div><div class="sl-name">${escapeHTML(m.name)}</div><div class="sl-sub">${escapeHTML(m.id)}${m.recordedBy && m.recordedBy !== '—' ? ' · ' + escapeHTML(m.recordedBy) : ''}</div></div>
          <div class="sl-qty" style="color:var(--success)">+${NUM(m.qty)} ${escapeHTML(m.unit)}</div>
        </div>`).join('')
      : '<div class="stock-empty">No stock added yet today.</div>';

    const oos = out.length;
    document.querySelectorAll('.sidebar__nav a[href="/inventory"] .badge')
      .forEach(b => { b.textContent = oos; b.classList.toggle('d-none', oos === 0); });

    renderMovements();
    renderBackOrders();
    renderStockSummary();
  }

  const detailModal = new bootstrap.Modal('#invDetailModal');
  function openDetail(i){
    currentDetailId = i.id;
    set('idName', i.name); set('idId', i.id); set('idCat', i.cat);
    set('idSup', i.sup); set('idLoc', i.loc); set('idPrice', PESO(i.price));
    set('idQty', NUM(i.qty)+' '+i.unit); set('idReorder', NUM(i.reorder)+' '+i.unit); set('idAdded', i.added);
    document.getElementById('idStatus').innerHTML = stockBadge(i.status);
    detailModal.show();
  }

  document.addEventListener('entity:submit', (e) => {
    const { entity, data } = e.detail;
    if (entity === 'stock-in' || entity === 'stock-out' || entity === 'return') {
      const i = inventoryStore.find(data.itemId); if (!i) return;
      const delta = (parseInt(data.qty,10)||0) * (entity==='stock-out' ? -1 : 1);
      const qty = Math.max(0, i.qty + delta);
      inventoryStore.update(i.id, { qty, status:invStatus(qty, i.reorder) });
      renderInventory();
    }
  });

  renderInventory();
  window.renderInventory = renderInventory;
});
