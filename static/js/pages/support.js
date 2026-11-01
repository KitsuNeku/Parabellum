(function () {
  const $ = (id) => document.getElementById(id);
  const POLL_LIST = 15000, POLL_THREAD = 5000;
  const STATUS_BADGE = { Open: 'b-warning', Answered: 'b-success', Closed: 'b-neutral' };

  let LIST = { tickets: [], summary: {}, canReply: false };
  let tab = '', kpi = null, current = null, lastId = 0, lastDay = '', sending = false;
  let listTimer = null, threadTimer = null;

  async function api(url, body) {
    const res = await fetch(url, body === undefined ? {} : {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    });
    const json = await res.json().catch(() => ({ ok: false, error: 'Unexpected server response.' }));
    if (!json.ok) throw new Error(json.error || 'Request failed.');
    return json.data;
  }

  const clock = (d) => d.toLocaleTimeString('en-PH', { hour: 'numeric', minute: '2-digit' });
  const shortWhen = (iso) => {
    const d = new Date(iso); if (!iso || isNaN(d)) return '';
    const now = new Date();
    if (d.toDateString() === now.toDateString()) return clock(d);
    return d.toLocaleDateString('en-PH', { month: 'short', day: 'numeric' });
  };
  const dayLabel = (d) => d.toDateString() === new Date().toDateString()
    ? 'Today' : d.toLocaleDateString('en-PH', { month: 'long', day: 'numeric', year: 'numeric' });
  const fullWhen = (iso) => { const d = new Date(iso); return isNaN(d) ? '' : `${dayLabel(d)} · ${clock(d)}`; };

  // Ticket list
  function setNavBadge(n) {
    const b = $('supportNavBadge');
    if (!b) return;
    b.textContent = n;
    b.style.display = n ? '' : 'none';
  }

  function renderSummary() {
    const s = LIST.summary;
    $('spKpiUnread').textContent = NUM(s.unread || 0);
    $('spKpiOpen').textContent = NUM(s.Open || 0);
    $('spKpiAnswered').textContent = NUM(s.Answered || 0);
    $('spKpiClosed').textContent = NUM(s.Closed || 0);
    setNavBadge(s.unread || 0);
  }

  function renderList() {
    const q = $('spSearch').value.trim().toLowerCase();
    const rows = LIST.tickets.filter(t => {
      if (tab && t.status !== tab) return false;
      if (kpi === 'unread' && !t.unread) return false;
      if (q && !`${t.ticket} ${t.name} ${t.company} ${t.email} ${t.orderRef}`.toLowerCase().includes(q)) return false;
      return true;
    });
    if (!rows.length) {
      $('spList').innerHTML = `<div class="text-center text-muted-2 py-4 small">${LIST.tickets.length ? 'No tickets match.' : 'No support tickets yet.'}</div>`;
      return;
    }
    $('spList').innerHTML = rows.map(t => `
      <button type="button" class="support-item${t.unread ? ' has-unread' : ''}${current === t.id ? ' active' : ''}" data-id="${t.id}">
        <div class="si-top"><span class="text-truncate">${escapeHTML(t.name)}</span><span class="si-time">${escapeHTML(shortWhen(t.lastAt))}</span></div>
        <div class="si-sub">${t.ticket}${t.company ? ` &middot; ${escapeHTML(t.company)}` : ''}
          <span class="badge ${STATUS_BADGE[t.status]} ms-1">${t.status}</span>
          ${t.unread ? `<span class="badge b-danger ms-1">${t.unread} new</span>` : ''}</div>
        <div class="si-last">${t.lastSender === 'staff' ? 'You: ' : ''}${escapeHTML(t.last)}</div>
      </button>`).join('');
  }

  async function loadList() {
    try {
      LIST = await api('/api/support/admin/tickets');
      renderSummary(); renderList();
    } catch (err) {
      $('spList').innerHTML = `<div class="text-center text-muted-2 py-4 small">${escapeHTML(err.message)}</div>`;
    }
    clearTimeout(listTimer);
    listTimer = setTimeout(loadList, POLL_LIST);
  }

  // Thread
  function renderHead(t) {
    const txn = t.transaction;
    return `<div class="support-head">
      <div class="min-w-0">
        <div class="d-flex align-items-center gap-2 flex-wrap">
          <h2 class="panel-title mb-0">${escapeHTML(t.name)}</h2>
          <span class="badge ${STATUS_BADGE[t.status]}" id="spThreadStatus">${t.status}</span>
          <span class="small text-muted-2">${t.ticket}</span>
        </div>
        <div class="support-info">
          ${t.company ? `<span><i class="bi bi-building me-1"></i>${escapeHTML(t.company)}</span>` : ''}
          <span><i class="bi bi-envelope me-1"></i><a href="mailto:${escapeHTML(t.email)}">${escapeHTML(t.email)}</a></span>
          <span><i class="bi bi-telephone me-1"></i><a href="tel:${escapeHTML(t.phone)}">${escapeHTML(t.phone)}</a></span>
          ${t.orderRef ? `<span><i class="bi bi-receipt me-1"></i>${escapeHTML(t.orderRef)}${txn
            ? ` &middot; ${escapeHTML(txn.customer)} &middot; ${PESO(txn.amount)} &middot; ${escapeHTML(txn.status)}`
            : ' <span class="text-muted-2">(no matching transaction)</span>'}</span>` : ''}
          <span><i class="bi bi-clock me-1"></i>Opened ${escapeHTML(fullWhen(t.createdAt))}</span>
        </div>
      </div>
      ${t.canReply ? `<button type="button" class="btn btn-sm ${t.status === 'Closed' ? 'btn-light-2' : 'btn-outline-secondary'}" id="spToggleStatus">
        ${t.status === 'Closed' ? '<i class="bi bi-arrow-counterclockwise me-1"></i>Reopen' : '<i class="bi bi-check2-circle me-1"></i>Close Ticket'}</button>` : ''}
    </div>`;
  }

  function appendMessages(msgs, t) {
    const box = $('spMsgs');
    if (!box || !msgs.length) return;
    const nearBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 100;
    msgs.forEach(m => {
      const d = new Date(m.at);
      const day = dayLabel(d);
      if (day !== lastDay) { box.insertAdjacentHTML('beforeend', `<div class="support-day">${escapeHTML(day)}</div>`); lastDay = day; }
      const who = m.sender === 'staff' ? (m.staff || 'Staff') : t.name;
      box.insertAdjacentHTML('beforeend', `<div class="support-msg ${m.sender}">${escapeHTML(m.body)}<span class="sm-meta">${escapeHTML(who)} &middot; ${clock(d)}</span></div>`);
      lastId = Math.max(lastId, m.id);
    });
    if (nearBottom || msgs.some(m => m.sender === 'staff')) box.scrollTop = box.scrollHeight;
  }

  async function openTicket(id) {
    current = id; lastId = 0; lastDay = '';
    renderList();
    $('spThread').innerHTML = '<div class="support-placeholder">Loading&hellip;</div>';
    try {
      const t = await api(`/api/support/admin/tickets/${id}`);
      $('spThread').innerHTML = renderHead(t) + '<div class="support-msgs" id="spMsgs"></div>' + (t.canReply
        ? `<form class="support-compose" id="spReplyForm">
             <textarea class="form-control" id="spReply" rows="2" maxlength="500" placeholder="Reply to ${escapeHTML(t.name)}&hellip; (Enter to send, Shift+Enter for a new line)"></textarea>
             <button type="submit" class="btn btn-primary" id="spReplyBtn" disabled><i class="bi bi-send-fill"></i></button>
           </form>`
        : '<div class="support-note"><i class="bi bi-eye me-1"></i>View only. Replies are handled by Administrators and Operations Personnel.</div>');
      appendMessages(t.messages, t);
      $('spMsgs').scrollTop = $('spMsgs').scrollHeight;
      current = t.id;
      $('spThread').dataset.status = t.status;
      wireThread(t);
      const item = LIST.tickets.find(x => x.id === id);
      if (item && item.unread) {
        item.unread = 0;
        LIST.summary.unread = LIST.tickets.filter(x => x.unread).length;
        renderSummary(); renderList();
      }
      pollThread(t);
    } catch (err) {
      $('spThread').innerHTML = `<div class="support-placeholder">${escapeHTML(err.message)}</div>`;
    }
  }

  function pollThread(t) {
    clearTimeout(threadTimer);
    threadTimer = setTimeout(async () => {
      if (current !== t.id) return;
      if (document.visibilityState === 'visible') {
        try {
          const fresh = await api(`/api/support/admin/tickets/${t.id}?after=${lastId}`);
          if (current !== t.id) return;
          appendMessages(fresh.messages, t);
          if (fresh.status !== $('spThread').dataset.status) refreshStatus(fresh.status, t);
        } catch (_) { }
      }
      pollThread(t);
    }, POLL_THREAD);
  }

  function refreshStatus(status, t) {
    t.status = status;
    $('spThread').dataset.status = status;
    const b = $('spThreadStatus');
    if (b) { b.className = `badge ${STATUS_BADGE[status]}`; b.textContent = status; }
    const btn = $('spToggleStatus');
    if (btn) {
      btn.className = `btn btn-sm ${status === 'Closed' ? 'btn-light-2' : 'btn-outline-secondary'}`;
      btn.innerHTML = status === 'Closed' ? '<i class="bi bi-arrow-counterclockwise me-1"></i>Reopen' : '<i class="bi bi-check2-circle me-1"></i>Close Ticket';
    }
    const item = LIST.tickets.find(x => x.id === t.id);
    if (item) item.status = status;
  }

  function wireThread(t) {
    const form = $('spReplyForm');
    if (form) {
      const ta = $('spReply'), btn = $('spReplyBtn');
      ta.addEventListener('input', () => { btn.disabled = !ta.value.trim() || sending; });
      ta.addEventListener('keydown', (e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); form.requestSubmit(); } });
      form.addEventListener('submit', async (e) => {
        e.preventDefault();
        const text = ta.value.trim();
        if (!text || sending) return;
        sending = true; btn.disabled = true;
        try {
          await api(`/api/support/admin/tickets/${t.id}/reply`, { message: text });
          ta.value = '';
          const fresh = await api(`/api/support/admin/tickets/${t.id}?after=${lastId}`);
          appendMessages(fresh.messages, t);
          refreshStatus(fresh.status, t);
          loadList();
        } catch (err) {
          showToast(err.message, 'danger', 'bi-exclamation-triangle-fill');
        } finally {
          sending = false;
          btn.disabled = !ta.value.trim();
          ta.focus();
        }
      });
    }
    $('spToggleStatus')?.addEventListener('click', async (e) => {
      const btn = e.currentTarget;
      const next = t.status === 'Closed' ? 'Open' : 'Closed';
      btn.disabled = true;
      try {
        await api(`/api/support/admin/tickets/${t.id}/status`, { status: next });
        refreshStatus(next, t);
        renderSummaryFromList();
        renderList();
        showToast(next === 'Closed' ? `${t.ticket} closed` : `${t.ticket} reopened`, 'success', 'bi-check2-circle');
      } catch (err) {
        showToast(err.message, 'danger', 'bi-exclamation-triangle-fill');
      } finally {
        btn.disabled = false;
      }
    });
  }

  function renderSummaryFromList() {
    ['Open', 'Answered', 'Closed'].forEach(s => { LIST.summary[s] = LIST.tickets.filter(t => t.status === s).length; });
    renderSummary();
  }

  // Events
  window.onKpiFilter = (key) => {
    kpi = key === 'unread' ? 'unread' : null;
    setTab(key && key !== 'unread' ? key : '');
  };
  function setTab(t) {
    tab = t;
    document.querySelectorAll('#spTabs [data-tab]').forEach(b => b.classList.toggle('active', b.dataset.tab === t));
    renderList();
  }
  $('spTabs').addEventListener('click', (e) => {
    const b = e.target.closest('[data-tab]');
    if (!b) return;
    kpi = null;
    if (typeof window.clearKpiSelection === 'function') window.clearKpiSelection();
    setTab(b.dataset.tab);
  });
  $('spSearch').addEventListener('input', renderList);
  $('spList').addEventListener('click', (e) => {
    const b = e.target.closest('[data-id]');
    if (b) openTicket(parseInt(b.dataset.id, 10));
  });

  const fromUrl = new URLSearchParams(location.search).get('ticket');
  loadList().then(() => { if (fromUrl) openTicket(parseInt(String(fromUrl).replace(/\D/g, ''), 10)); });
})();
