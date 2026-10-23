/* =====================================================================
 PARABELLUM ISOS - Chat between accounts
 A floating button (bottom-right) on every signed-in page. It opens a small
 panel: a list of the other accounts, then a one-to-one conversation.
 Loaded by app.js once the session is confirmed (see "Session" block there).

 Updates by polling (no extra server needed, works on any host):
   unread badge   every 15 s while the panel is closed
   contact list   every  8 s while it is open
   conversation   every  4 s while it is open
 Polling pauses while the browser tab is in the background.
 Message text is only ever inserted with textContent (never as HTML).
 ===================================================================== */
(function () {
  if (window.__parabellumChat) return;
  window.__parabellumChat = true;

  const POLL_UNREAD = 15000, POLL_LIST = 8000, POLL_THREAD = 4000;
  const MAX_LEN = 500;

  const state = { open: false, view: 'list', peer: null, seen: new Set(), lastId: 0, timer: null, sending: false };

  /* ---------- tiny helpers ---------- */
  const h = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };

  async function api(path, opts) {
    const res = await fetch(path, opts);
    let json;
    try { json = await res.json(); } catch (_) { throw new Error('The server returned an unexpected response.'); }
    if (!json.ok) throw new Error(json.error || 'Request failed.');
    return json.data;
  }

  const sameDay = (a, b) => a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
  const clock = (d) => d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
  function stampMsg(iso) {
    const d = new Date(iso); if (isNaN(d)) return '';
    return sameDay(d, new Date()) ? clock(d) : d.toLocaleDateString([], { month: 'short', day: 'numeric' }) + ' · ' + clock(d);
  }
  function stampList(iso) {
    const d = new Date(iso); if (!iso || isNaN(d)) return '';
    const now = new Date(), y = new Date(now.getFullYear(), now.getMonth(), now.getDate() - 1);
    if (sameDay(d, now)) return clock(d);
    if (sameDay(d, y)) return 'Yesterday';
    return d.toLocaleDateString([], { month: 'short', day: 'numeric' });
  }
  const initial = (name) => (String(name || '?').trim()[0] || '?').toUpperCase();

  /* ---------- DOM ---------- */
  const fab = h('button', 'chat-fab no-print');
  fab.type = 'button'; fab.setAttribute('aria-label', 'Open chat'); fab.title = 'Chat';
  fab.innerHTML = '<i class="bi bi-chat-dots-fill"></i>';
  const badge = h('span', 'chat-badge'); badge.style.display = 'none'; fab.appendChild(badge);

  const panel = h('div', 'chat-panel no-print');
  panel.setAttribute('role', 'dialog'); panel.setAttribute('aria-label', 'Chat');

  const head = h('div', 'chat-head');
  const backBtn = h('button'); backBtn.type = 'button'; backBtn.setAttribute('aria-label', 'Back to contacts'); backBtn.innerHTML = '<i class="bi bi-arrow-left"></i>'; backBtn.style.display = 'none';
  const titleBox = h('div', 'chat-title');
  const titleMain = h('div', null, 'Messages'); const titleSub = h('div', 'chat-sub'); titleBox.append(titleMain, titleSub);
  const closeBtn = h('button'); closeBtn.type = 'button'; closeBtn.setAttribute('aria-label', 'Close chat'); closeBtn.innerHTML = '<i class="bi bi-x-lg"></i>';
  head.append(backBtn, titleBox, closeBtn);

  const body = h('div', 'chat-body');
  const errLine = h('div', 'chat-err'); errLine.style.display = 'none';
  const compose = h('form', 'chat-compose'); compose.style.display = 'none';
  const ta = h('textarea'); ta.rows = 1; ta.maxLength = MAX_LEN; ta.placeholder = 'Type a message…'; ta.setAttribute('aria-label', 'Message');
  const sendBtn = h('button'); sendBtn.type = 'submit'; sendBtn.setAttribute('aria-label', 'Send'); sendBtn.innerHTML = '<i class="bi bi-send-fill"></i>'; sendBtn.disabled = true;
  compose.append(ta, sendBtn);

  panel.append(head, body, errLine, compose);
  document.body.append(fab, panel);

  /* ---------- badge ---------- */
  function setBadge(n) {
    n = Number(n) || 0;
    badge.textContent = n > 99 ? '99+' : String(n);
    badge.style.display = n > 0 ? '' : 'none';
    fab.setAttribute('aria-label', n > 0 ? `Open chat (${n} unread)` : 'Open chat');
  }
  async function refreshUnread() {
    try { setBadge((await api('/api/chat/unread')).unread); } catch (_) { /* badge just stays as is */ }
  }

  /* ---------- contact list ---------- */
  async function showList() {
    state.view = 'list'; state.peer = null;
    backBtn.style.display = 'none'; compose.style.display = 'none'; errLine.style.display = 'none';
    titleMain.textContent = 'Messages'; titleSub.textContent = 'Choose an account to chat with';
    await loadList(true);
    schedule();
  }

  async function loadList(first) {
    if (state.view !== 'list') return;
    let rows;
    try { rows = await api('/api/chat/contacts'); }
    catch (e) { if (first) { body.replaceChildren(h('div', 'chat-note', e.message)); } return; }
    if (state.view !== 'list') return;
    setBadge(rows.reduce((s, r) => s + (r.unread || 0), 0));
    if (!rows.length) { body.replaceChildren(h('div', 'chat-empty', 'There are no other accounts to chat with yet.')); return; }
    const frag = document.createDocumentFragment();
    rows.forEach(r => {
      const b = h('button', 'chat-contact' + (r.unread ? ' has-unread' : '')); b.type = 'button';
      const meta = h('div', 'chat-meta');
      const nm = h('div', 'chat-name'); nm.append(h('span', null, r.name), h('span', 'chat-time', stampList(r.lastAt)));
      meta.append(nm, h('div', 'chat-role', r.role + (r.department ? ' · ' + r.department : '')),
        h('div', 'chat-last', r.lastBody ? (r.lastMine ? 'You: ' : '') + r.lastBody : 'No messages yet'));
      b.append(h('div', 'chat-avatar', initial(r.name)), meta);
      if (r.unread) b.append(h('span', 'chat-unread', r.unread > 99 ? '99+' : String(r.unread)));
      b.addEventListener('click', () => openThread(r));
      frag.appendChild(b);
    });
    body.replaceChildren(frag);
  }

  /* ---------- conversation ---------- */
  function bubble(m) {
    const d = h('div', 'chat-msg' + (m.mine ? ' mine' : ''));
    d.append(document.createTextNode(m.body), h('span', 'chat-ts', stampMsg(m.sentAt)));
    return d;
  }
  const nearBottom = () => body.scrollHeight - body.scrollTop - body.clientHeight < 80;

  async function openThread(peer) {
    state.view = 'thread'; state.peer = peer; state.seen = new Set(); state.lastId = 0;
    backBtn.style.display = ''; compose.style.display = ''; errLine.style.display = 'none';
    titleMain.textContent = peer.name; titleSub.textContent = peer.role;
    body.replaceChildren(h('div', 'chat-thread'));
    ta.value = ''; sendBtn.disabled = true; autosize();
    await loadThread(true);
    schedule();
    ta.focus();
  }

  function append(msgs, forceScroll) {
    const thread = body.querySelector('.chat-thread'); if (!thread) return;
    const stick = forceScroll || nearBottom();
    msgs.forEach(m => {
      if (state.seen.has(m.id)) return;
      state.seen.add(m.id); state.lastId = Math.max(state.lastId, m.id);
      thread.appendChild(bubble(m));
    });
    if (stick) body.scrollTop = body.scrollHeight;
  }

  async function loadThread(first) {
    const peer = state.peer; if (!peer || state.view !== 'thread') return;
    try {
      const msgs = await api(`/api/chat/messages?with=${encodeURIComponent(peer.id)}&after=${state.lastId}`);
      if (state.peer !== peer || state.view !== 'thread') return;      // user switched away meanwhile
      errLine.style.display = 'none';
      if (first && !msgs.length) body.querySelector('.chat-thread').appendChild(h('div', 'chat-empty', 'No messages yet. Say hello!'));
      if (msgs.length) { const e = body.querySelector('.chat-thread .chat-empty'); if (e) e.remove(); append(msgs, first); refreshUnread(); }
      else if (first) refreshUnread();
    } catch (e) {
      if (first) { body.replaceChildren(h('div', 'chat-note', e.message)); }
    }
  }

  function autosize() { ta.style.height = 'auto'; ta.style.height = Math.min(ta.scrollHeight, 96) + 'px'; }
  ta.addEventListener('input', () => { sendBtn.disabled = state.sending || !ta.value.trim(); autosize(); });
  ta.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); compose.requestSubmit(); }
  });

  compose.addEventListener('submit', async (e) => {
    e.preventDefault();
    const text = ta.value.trim();
    if (!text || state.sending || !state.peer) return;
    state.sending = true; sendBtn.disabled = true; errLine.style.display = 'none';
    try {
      const m = await api('/api/chat/send', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ to: state.peer.id, body: text }),
      });
      const empty = body.querySelector('.chat-thread .chat-empty'); if (empty) empty.remove();
      append([m], true);
      ta.value = ''; autosize();
    } catch (err) {
      errLine.textContent = err.message; errLine.style.display = '';   // the typed text stays so nothing is lost
    } finally {
      state.sending = false; sendBtn.disabled = !ta.value.trim();
      ta.focus();
    }
  });

  /* ---------- open / close / polling ---------- */
  function schedule() {
    clearTimeout(state.timer);
    const every = !state.open ? POLL_UNREAD : (state.view === 'thread' ? POLL_THREAD : POLL_LIST);
    state.timer = setTimeout(async () => {
      if (!document.hidden) {
        if (!state.open) await refreshUnread();
        else if (state.view === 'thread') await loadThread(false);
        else await loadList(false);
      }
      schedule();
    }, every);
  }

  function openPanel() {
    state.open = true; panel.classList.add('open');
    fab.setAttribute('aria-expanded', 'true');
    showList();
  }
  function closePanel() {
    state.open = false; panel.classList.remove('open');
    fab.setAttribute('aria-expanded', 'false');
    state.view = 'list'; state.peer = null;
    refreshUnread(); schedule();
  }

  fab.addEventListener('click', () => (state.open ? closePanel() : openPanel()));
  closeBtn.addEventListener('click', closePanel);
  backBtn.addEventListener('click', showList);
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && state.open && !document.querySelector('.modal.show')) closePanel(); });
  document.addEventListener('visibilitychange', () => { if (!document.hidden) { if (!state.open) refreshUnread(); else if (state.view === 'thread') loadThread(false); else loadList(false); } });

  refreshUnread();
  schedule();
})();
