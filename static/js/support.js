(function () {
  const KEY = 'pb_support';
  const POLL_OPEN = 4000, POLL_CLOSED = 20000;
  const MAX_LEN = 500;
  let memory = null;
  const state = { open: false, lastId: 0, timer: null, sending: false, status: '', lastDay: '' };

  const store = {
    get() { try { return JSON.parse(localStorage.getItem(KEY)) || memory; } catch (_) { return memory; } },
    set(v) { memory = v; try { localStorage.setItem(KEY, JSON.stringify(v)); } catch (_) { } },
    clear() { memory = null; try { localStorage.removeItem(KEY); } catch (_) { } },
  };

  const csrf = () => (document.cookie.split('; ').find(c => c.startsWith('csrf_token=')) || '').split('=')[1] || '';

  async function api(path, body) {
    const s = store.get();
    const headers = { 'X-CSRF-Token': csrf() };
    if (s && s.token) headers['X-Support-Token'] = s.token;
    if (body !== undefined) headers['Content-Type'] = 'application/json';
    const res = await fetch(path, { method: body === undefined ? 'GET' : 'POST', headers,
      body: body === undefined ? undefined : JSON.stringify(body), credentials: 'same-origin' });
    let json;
    try { json = await res.json(); } catch (_) { throw new Error('Something went wrong. Please try again.'); }
    if (!json.ok) { const e = new Error(json.error || 'Request failed.'); e.status = res.status; e.fields = json.fields; throw e; }
    return json.data;
  }

  const h = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
  const $ = (id) => document.getElementById(id);

  // Chat widget
  const fab = h('button', 'sp-fab');
  fab.type = 'button'; fab.setAttribute('aria-label', 'Customer support chat'); fab.title = 'Need support?';
  fab.innerHTML = '<i class="bi bi-chat-dots-fill"></i>';
  const badge = h('span', 'sp-badge'); badge.style.display = 'none'; fab.appendChild(badge);

  const panel = h('div', 'sp-panel');
  panel.setAttribute('role', 'dialog'); panel.setAttribute('aria-label', 'Customer support chat');
  panel.innerHTML = `
    <div class="sp-head">
      <div class="sp-head-ic"><i class="bi bi-headset"></i></div>
      <div class="sp-title"><strong>Customer Support</strong><span id="spSub"></span></div>
      <button type="button" id="spNew" title="Start a new ticket" aria-label="Start a new ticket"><i class="bi bi-plus-square"></i></button>
      <button type="button" id="spClose" title="Close" aria-label="Close chat"><i class="bi bi-x-lg"></i></button>
    </div>
    <div class="sp-body" id="spBody"></div>
    <div class="sp-note" id="spNote" style="display:none"></div>
    <div class="sp-err" id="spErr" style="display:none"></div>
    <form class="sp-compose" id="spCompose">
      <textarea rows="1" maxlength="${MAX_LEN}" placeholder="Type a message&hellip;" aria-label="Message" id="spInput"></textarea>
      <button type="submit" aria-label="Send" id="spSend" disabled><i class="bi bi-send-fill"></i></button>
    </form>`;
  document.body.append(fab, panel);

  const body = $('spBody'), input = $('spInput'), sendBtn = $('spSend'), errLine = $('spErr'), note = $('spNote');

  const clock = (d) => d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
  const dayLabel = (d) => {
    const now = new Date();
    if (d.toDateString() === now.toDateString()) return 'Today';
    return d.toLocaleDateString([], { month: 'long', day: 'numeric', year: 'numeric' });
  };

  function setBadge(n) {
    badge.textContent = n > 9 ? '9+' : String(n);
    badge.style.display = n > 0 ? '' : 'none';
  }
  function showErr(msg) { errLine.textContent = msg || ''; errLine.style.display = msg ? '' : 'none'; }

  function setHeader(data) {
    state.status = data.status;
    $('spSub').innerHTML = `${data.ticket} <span class="sp-status">${data.status.toUpperCase()}</span>`;
    note.style.display = data.status === 'Closed' ? '' : 'none';
    note.textContent = 'This ticket was closed by our team. Send a message if you still need help and it will reopen.';
  }

  function appendMessages(msgs) {
    if (!msgs.length) return;
    const nearBottom = body.scrollHeight - body.scrollTop - body.clientHeight < 80;
    body.querySelector('.sp-empty')?.remove();
    msgs.forEach(m => {
      const d = new Date(m.at);
      const day = dayLabel(d);
      if (day !== state.lastDay) { body.appendChild(h('div', 'sp-day', day)); state.lastDay = day; }
      const el = h('div', 'sp-msg ' + (m.sender === 'customer' ? 'mine' : 'staff'));
      if (m.sender === 'staff') el.appendChild(h('span', 'sp-who', m.staff ? `${m.staff} · Support` : 'Support'));
      el.appendChild(document.createTextNode(m.body));
      el.appendChild(h('span', 'sp-ts', clock(d)));
      body.appendChild(el);
      state.lastId = Math.max(state.lastId, m.id);
    });
    if (nearBottom || msgs.some(m => m.sender === 'customer')) body.scrollTop = body.scrollHeight;
  }

  async function loadThread(reset) {
    if (reset) { state.lastId = 0; state.lastDay = ''; body.innerHTML = ''; }
    try {
      const data = await api(`/api/support/thread?after=${state.lastId}`);
      setHeader(data);
      appendMessages(data.messages);
      if (reset) body.scrollTop = body.scrollHeight;
      showErr('');
      setBadge(0);
    } catch (e) {
      if (e.status === 404) { store.clear(); closePanel(); openModal('find'); $('supportFindErr').textContent = e.message; return; }
      showErr(e.message);
    }
  }

  async function checkUnread() {
    if (!store.get()) return;
    try { setBadge((await api('/api/support/unread')).unread); } catch (_) { }
  }

  function schedule() {
    clearTimeout(state.timer);
    if (!store.get()) return;
    state.timer = setTimeout(async () => {
      if (document.visibilityState === 'visible') {
        if (state.open) await loadThread(false); else await checkUnread();
      }
      schedule();
    }, state.open ? POLL_OPEN : POLL_CLOSED);
  }

  function openPanel() {
    state.open = true;
    panel.classList.add('open');
    fab.innerHTML = '<i class="bi bi-chevron-down"></i>';
    fab.appendChild(badge);
    loadThread(true).then(() => input.focus());
    schedule();
  }
  function closePanel() {
    state.open = false;
    panel.classList.remove('open');
    fab.innerHTML = '<i class="bi bi-chat-dots-fill"></i>';
    fab.appendChild(badge);
    schedule();
  }

  fab.addEventListener('click', () => {
    if (state.open) return closePanel();
    if (store.get()) openPanel(); else openModal('new');
  });
  $('spClose').addEventListener('click', closePanel);
  $('spNew').addEventListener('click', () => {
    if (!confirm('Start a new ticket? You can still reopen this one later with its ticket number and your email.')) return;
    store.clear(); closePanel(); setBadge(0); openModal('new');
  });

  input.addEventListener('input', () => {
    sendBtn.disabled = !input.value.trim() || state.sending;
    input.style.height = 'auto';
    input.style.height = Math.min(input.scrollHeight, 100) + 'px';
  });
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); $('spCompose').requestSubmit(); }
  });
  $('spCompose').addEventListener('submit', async (e) => {
    e.preventDefault();
    const text = input.value.trim();
    if (!text || state.sending) return;
    state.sending = true; sendBtn.disabled = true;
    try {
      await api('/api/support/message', { message: text });
      input.value = ''; input.style.height = 'auto';
      await loadThread(false);
    } catch (err) {
      showErr(err.message);
    } finally {
      state.sending = false;
      sendBtn.disabled = !input.value.trim();
      input.focus();
    }
  });

  // Support modal
  const modalEl = $('supportModal');
  const modal = () => bootstrap.Modal.getOrCreateInstance(modalEl);
  const form = $('supportForm'), findForm = $('supportFindForm');

  function setView(view) {
    form.hidden = view !== 'new';
    findForm.hidden = view !== 'find';
    $('supportModalSub').textContent = view === 'new'
      ? 'Tell us about your concern and our team will reply in the chat.'
      : 'Continue a conversation you already started.';
  }
  function openModal(view) {
    setView(view || 'new');
    $('supportFormErr').textContent = '';
    $('supportFindErr').textContent = view === 'find' ? $('supportFindErr').textContent : '';
    modal().show();
  }

  document.querySelectorAll('[data-support-open]').forEach(b => b.addEventListener('click', () => {
    if (store.get()) openPanel(); else openModal('new');
  }));
  modalEl.addEventListener('click', (e) => {
    const v = e.target.closest('[data-support-view]');
    if (v) { setView(v.dataset.supportView); $('supportFindErr').textContent = ''; }
  });
  modalEl.addEventListener('shown.bs.modal', () => (form.hidden ? $('spFindTicket') : $('spName')).focus());

  const concern = $('spConcern');
  concern.addEventListener('input', () => { $('spConcernCount').textContent = `${concern.value.length} / 2000`; });

  const FIELD_IDS = { name: 'spName', email: 'spEmail', phone: 'spPhone', concern: 'spConcern' };
  function fieldError(key, msg) {
    const el = $(FIELD_IDS[key]);
    el.classList.toggle('is-invalid', !!msg);
    const fb = key === 'concern' ? $('spConcernErr') : el.parentElement.querySelector('.invalid-feedback');
    if (fb) fb.textContent = msg || '';
  }
  function validate(d) {
    const errs = {};
    if (!d.name) errs.name = 'Please enter your name.';
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(d.email)) errs.email = 'Please enter a valid email address.';
    if (!/^[0-9+()\-\s]{7,20}$/.test(d.phone)) errs.phone = 'Please enter a valid phone number.';
    if (d.concern.length < 5) errs.concern = 'Please describe your concern.';
    return errs;
  }
  Object.keys(FIELD_IDS).forEach(k => $(FIELD_IDS[k]).addEventListener('input', () => fieldError(k, '')));

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const d = {
      company: $('spCompany').value.trim(), name: $('spName').value.trim(), email: $('spEmail').value.trim(),
      phone: $('spPhone').value.trim(), orderRef: $('spOrder').value.trim(), concern: concern.value.trim(),
      website: $('spWebsite').value,
    };
    const errs = validate(d);
    Object.keys(FIELD_IDS).forEach(k => fieldError(k, errs[k]));
    if (Object.keys(errs).length) { $(FIELD_IDS[Object.keys(errs)[0]]).focus(); return; }
    const btn = $('supportSubmit');
    btn.disabled = true; $('supportFormErr').textContent = '';
    try {
      const res = await api('/api/support/tickets', d);
      store.set({ token: res.token, ticket: res.ticket });
      form.reset(); $('spConcernCount').textContent = '0 / 2000';
      modal().hide();
      openPanel();
    } catch (err) {
      if (err.fields) Object.entries(err.fields).forEach(([k, v]) => FIELD_IDS[k] && fieldError(k, v));
      $('supportFormErr').textContent = err.message;
    } finally {
      btn.disabled = false;
    }
  });

  findForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const ticket = $('spFindTicket').value.trim(), email = $('spFindEmail').value.trim();
    if (!ticket || !email) { $('supportFindErr').textContent = 'Enter your ticket number and email.'; return; }
    const btn = $('supportFindSubmit');
    btn.disabled = true; $('supportFindErr').textContent = '';
    try {
      const res = await api('/api/support/open', { ticket, email });
      store.set({ token: res.token, ticket: res.ticket });
      findForm.reset();
      modal().hide();
      openPanel();
    } catch (err) {
      $('supportFindErr').textContent = err.message;
    } finally {
      btn.disabled = false;
    }
  });

  if (store.get()) { checkUnread(); schedule(); }
})();
