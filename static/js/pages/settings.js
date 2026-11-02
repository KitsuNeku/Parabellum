/* Settings page */
document.addEventListener('DOMContentLoaded', () => {
  const roleBadge = (r) => {
    const m = { 'System Administrator':'badge-soft', 'Inventory Personnel':'b-info',
                'Operations Personnel':'b-info', 'Management/Owner':'b-gold' };
    return `<span class="badge ${m[r]||'b-neutral'}">${r}</span>`;
  };
  const userForm  = document.getElementById('userForm');
  const userModal = new bootstrap.Modal('#userModal');
  const pwLabel   = document.getElementById('userPasswordLabel');
  const pwInput   = document.getElementById('userPasswordInput');
  let usersCache  = [];

  function showTempPassword(username, pw){
    let m = document.getElementById('tempPwModal');
    if (!m) {
      document.body.insertAdjacentHTML('beforeend', `
        <div class="modal fade" id="tempPwModal" tabindex="-1"><div class="modal-dialog modal-dialog-centered"><div class="modal-content">
          <div class="modal-header"><h5 class="modal-title"><i class="bi bi-key me-2" style="color:var(--primary)"></i>Temporary Password</h5><button class="btn-close" data-bs-dismiss="modal"></button></div>
          <div class="modal-body">
            <p class="small mb-2">Give this to <strong id="tempPwUser"></strong>. It is shown only once. They will be asked to set a new password after signing in.</p>
            <div class="input-group"><input class="form-control fw-bold" id="tempPwValue" readonly style="letter-spacing:.06em"><button class="btn btn-light-2" id="tempPwCopy" type="button"><i class="bi bi-clipboard"></i> Copy</button></div>
          </div>
          <div class="modal-footer"><button type="button" class="btn btn-primary" data-bs-dismiss="modal">Done</button></div>
        </div></div></div>`);
      m = document.getElementById('tempPwModal');
      document.getElementById('tempPwCopy').addEventListener('click', () => {
        const v = document.getElementById('tempPwValue');
        v.select();
        (navigator.clipboard?.writeText(v.value) || Promise.reject()).then(() => showToast('Copied', 'success')).catch(() => document.execCommand('copy'));
      });
    }
    document.getElementById('tempPwUser').textContent = username;
    document.getElementById('tempPwValue').value = pw;
    bootstrap.Modal.getOrCreateInstance(m).show();
  }

  async function loadUsers(){
    const tb = document.getElementById('usersBody');
    try {
      const res = await fetch('/api/users');
      const json = await res.json();
      if (!json.ok) throw new Error(json.error);
      usersCache = json.data;
      tb.innerHTML = '';
      usersCache.forEach(u => {
        const accessTag = u.hasOverride
          ? `<span class="badge b-warning ms-1" title="This user's access is customized — not the role default">Custom access</span>`
          : '';
        tb.insertAdjacentHTML('beforeend', `<tr>
          <td><div class="fw-medium">${escapeHTML(u.name)}</div><div class="small text-muted-2">${escapeHTML(u.email)}</div></td>
          <td>${roleBadge(u.role)}${accessTag}</td><td>${escapeHTML(u.dept)}</td>
          <td><span class="badge ${u.status==='Active'?'b-success':'b-warning'}">${u.status}</span>${u.twoFactor ? ' <span class="badge b-info" title="Two-factor authentication is on">2FA</span>' : ''}${u.mustChangePassword ? ' <span class="badge b-gold" title="Must change the temporary password at next sign-in">Temp password</span>' : ''}</td>
          <td class="text-center">
            <button class="act-btn" data-bs-toggle="tooltip" title="Edit" data-act="edit" data-id="${u.id}"><i class="bi bi-pencil"></i></button>
            <button class="act-btn" data-bs-toggle="tooltip" title="Permissions" data-act="access" data-id="${u.id}"><i class="bi bi-shield-lock"></i></button>
            <button class="act-btn" data-bs-toggle="tooltip" title="Reset password" data-act="resetpw" data-id="${u.id}"><i class="bi bi-key"></i></button>
            ${u.twoFactor ? `<button class="act-btn" data-bs-toggle="tooltip" title="Reset 2FA" data-act="reset2fa" data-id="${u.id}"><i class="bi bi-phone"></i></button>` : ''}
            <button class="act-btn danger" data-bs-toggle="tooltip" title="Deactivate" data-act="deactivate" data-id="${u.id}"><i class="bi bi-person-x"></i></button>
          </td></tr>`);
      });
      initTooltips(tb);
      populatePermUserSelect();
    } catch (err) {
      tb.innerHTML = `<tr><td colspan="5" class="text-center text-danger py-3">${escapeHTML(err.message)}</td></tr>`;
    }
  }

  document.getElementById('usersBody').addEventListener('click', async (e) => {
    const editBtn = e.target.closest('[data-act="edit"]');
    if (editBtn) {
      const u = usersCache.find(x => x.id === editBtn.dataset.id); if (!u) return;
      userForm.setAttribute('data-edit-id', u.id);
      document.getElementById('userModalTitle').textContent = 'Edit User';
      document.getElementById('userModalSubmit').textContent = 'Save Changes';
      pwLabel.textContent = 'Password';
      pwInput.required = false;
      const f = userForm.elements;
      f.name.value = u.name; f.email.value = u.email; f.role.value = u.role;
      f.username.value = u.username; f.dept.value = u.dept; f.status.value = u.status;
      f.password.value = '';
      const isAdmin = (u.username === 'admin');
      f.role.disabled = isAdmin;
      const roleCell = f.role.closest('.col-md-6');
      let note = roleCell.querySelector('[data-admin-role-note]');
      if (isAdmin && !note) {
        note = document.createElement('div');
        note.setAttribute('data-admin-role-note', '');
        note.className = 'small text-muted-2 mt-1';
        note.innerHTML = '<i class="bi bi-shield-lock me-1"></i>The admin account always stays System Administrator.';
        roleCell.appendChild(note);
      } else if (!isAdmin && note) {
        note.remove();
      }
      userModal.show();
      return;
    }
    const resetPwBtn = e.target.closest('[data-act="resetpw"]');
    if (resetPwBtn) {
      const u = usersCache.find(x => x.id === resetPwBtn.dataset.id); if (!u) return;
      confirmAction('Reset Password', `Reset the password of ${u.name || u.username}? They will get a temporary password and must change it after signing in.`, 'Reset Password', async () => {
        const res = await fetch('/api/users/reset-password', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ id: u.id }) });
        const j = await res.json();
        if (!j.ok) { showToast(j.error || 'Could not reset the password', 'error', 'bi-exclamation-triangle'); return; }
        showTempPassword(j.data.username, j.data.temporaryPassword);
        loadUsers();
      });
      return;
    }
    const reset2faBtn = e.target.closest('[data-act="reset2fa"]');
    if (reset2faBtn) {
      const u = usersCache.find(x => x.id === reset2faBtn.dataset.id); if (!u) return;
      confirmAction('Reset Two-Factor', `Turn off two-factor authentication for ${u.name || u.username}? Use this if they lost their phone.`, 'Turn Off 2FA', async () => {
        const res = await fetch('/api/users/reset-2fa', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ id: u.id }) });
        const j = await res.json();
        if (!j.ok) { showToast(j.error || 'Could not reset 2FA', 'error', 'bi-exclamation-triangle'); return; }
        showToast('Two-factor authentication turned off for this user', 'success');
        loadUsers();
      });
      return;
    }
    const deactivateBtn = e.target.closest('[data-act="deactivate"]');
    if (deactivateBtn) {
      const u = usersCache.find(x => x.id === deactivateBtn.dataset.id); if (!u) return;
      if (!confirm(`Deactivate ${u.name}? They will no longer be able to sign in.`)) return;
      try {
        const res = await fetch('/api/users/deactivate', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ id: u.id }),
        });
        const json = await res.json();
        if (!json.ok) throw new Error(json.error);
        showToast('User deactivated', 'success');
        loadUsers();
      } catch (err) {
        showToast(err.message, 'error', 'bi-exclamation-triangle');
      }
    }
    const accessBtn = e.target.closest('[data-act="access"]');
    if (accessBtn) {
      const u = usersCache.find(x => x.id === accessBtn.dataset.id); if (!u) return;
      const sel = document.getElementById('permUserSelect');
      if (sel) { sel.value = u.id; sel.dispatchEvent(new Event('change')); }
      document.getElementById('permUserSelect')?.closest('.result-line')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  });

  const ACCESS_MODULES = [
    ['dashboard',    'Dashboard'],
    ['inventory',    'Inventory'],
    ['outlook',      'Stock Outlook'],
    ['suppliers',    'Suppliers'],
    ['customers',    'Customers'],
    ['projects',     'Projects'],
    ['transactions', 'Client Transactions'],
    ['support', 'Customer Support'],
    ['forecasting', 'Forecasting'],
    ['reports',      'Reports'],
    ['settings',     'Settings'],
    ['profile',      'Profile'],
  ];
  const permUserSelect = document.getElementById('permUserSelect');
  const permUserMeta   = document.getElementById('permUserMeta');
  const permEditor     = document.getElementById('permEditor');
  const permApplyBtn   = document.getElementById('permApplyBtn');
  const permResetBtn   = document.getElementById('permResetBtn');
  let currentPermUser  = null;

  function populatePermUserSelect(){
    if (!permUserSelect) return;
    const prevValue = permUserSelect.value;
    permUserSelect.innerHTML = ''+
      usersCache.map(u => `<option value="${u.id}">${escapeHTML(u.name)} (${escapeHTML(u.username)})</option>`).join('');
    if (prevValue && usersCache.some(u => u.id === prevValue)) {
      permUserSelect.value = prevValue;
      const u = usersCache.find(x => x.id === prevValue);
      if (u) renderPermEditor(u);
    }
  }

  function renderPermEditor(u){
    currentPermUser = u;
    permUserMeta.innerHTML = `${roleBadge(u.role)} <span class="ms-1">${escapeHTML(u.username)} · ${escapeHTML(u.email)}</span>`;

    const roleDefaults = new Set(u.rolePermissions || []);
    document.getElementById('permRoleDefaultList').textContent =
      [...roleDefaults].map(k => ACCESS_MODULES.find(m=>m[0]===k)?.[1] || k).join(', ') || '(nothing)';

    const effective = new Set(u.effectivePermissions || []);
    const container = document.getElementById('permCheckboxes');
    const isSelf = CURRENT_USER && CURRENT_USER.user_id === parseInt(u.id.split('-')[1], 10);
    const isAdmin = u.role === 'System Administrator';
    // The admin account itself is fully locked - cannot change its access from
    // here. Every checkbox is disabled and the Apply/Reset buttons are hidden.
    const isAdminAccount = u.username === 'admin';
    container.innerHTML = ACCESS_MODULES.map(([key, label]) => {
      const checked  = effective.has(key) ? 'checked' : '';
      const disabled = (isAdminAccount || (key === 'settings' && !isAdmin)) ? 'disabled' : '';
      const settingsAdminSelfLock = (key === 'settings' && isSelf && isAdmin && !isAdminAccount);
      const lockedNote = (!isAdminAccount && disabled)
        ? '<div class="small text-muted-2">Only System Administrators can hold this.</div>' : '';
      const selfLockAttr = settingsAdminSelfLock ? 'data-self-locked="1"' : '';
      return `<div class="col-md-6">
        <div class="form-check">
          <input class="form-check-input" type="checkbox" id="perm-${key}" data-perm="${key}" ${checked} ${disabled} ${selfLockAttr}>
          <label class="form-check-label" for="perm-${key}"><strong>${escapeHTML(label)}</strong></label>
          ${lockedNote}
        </div>
      </div>`;
    }).join('');

    document.getElementById('permAdminSelfHint').style.display =
      (isSelf && isAdmin && !isAdminAccount) ? '' : 'none';

    // Hide Apply/Reset for the admin account; show a locked notice instead.
    const applyBtn = document.getElementById('permApplyBtn');
    const resetBtn = document.getElementById('permResetBtn');
    let lockedBanner = document.getElementById('permAdminLockBanner');
    if (isAdminAccount) {
      if (applyBtn) applyBtn.style.display = 'none';
      if (resetBtn) resetBtn.style.display = 'none';
      if (!lockedBanner) {
        lockedBanner = document.createElement('div');
        lockedBanner.id = 'permAdminLockBanner';
        lockedBanner.className = 'alert alert-soft-info small mt-2 mb-0';
        lockedBanner.innerHTML = '<i class="bi bi-shield-lock me-1"></i>The admin account has fixed access and cannot be changed from here.';
        container.parentElement.appendChild(lockedBanner);
      } else {
        lockedBanner.style.display = '';
      }
    } else {
      if (applyBtn) applyBtn.style.display = '';
      if (resetBtn) resetBtn.style.display = '';
      if (lockedBanner) lockedBanner.style.display = 'none';
    }

    permEditor.style.display = '';
  }

  permUserSelect?.addEventListener('change', () => {
    const u = usersCache.find(x => x.id === permUserSelect.value);
    if (!u) {
      permEditor.style.display = 'none';
      currentPermUser = null;
      permUserMeta.textContent = 'Pick a user to see their current access.';
      return;
    }
    renderPermEditor(u);
  });

  document.getElementById('permCheckboxes')?.addEventListener('change', (e) => {
    const cb = e.target.closest('input[data-perm="settings"][data-self-locked="1"]');
    if (!cb) return;
    if (!cb.checked) {
      cb.checked = true;
      showToast('You can’t take away your own Settings access.', 'error', 'bi-exclamation-triangle');
    }
  });

  permApplyBtn?.addEventListener('click', async () => {
    if (!currentPermUser) return;
    const perms = [...document.querySelectorAll('#permCheckboxes input[type="checkbox"]:checked')]
      .map(cb => cb.dataset.perm);
    try {
      const res = await fetch('/api/users/permissions', {
        method: 'POST', headers: {'Content-Type':'application/json'},
        body: JSON.stringify({ id: currentPermUser.id, permissions: perms }),
      });
      const json = await res.json();
      if (!json.ok) throw new Error(json.error);
      showToast(`Permissions applied to ${currentPermUser.name} \u2014 refreshing\u2026`, 'success', 'bi-check-circle-fill');
      setTimeout(() => window.location.reload(), 700);
    } catch (err) {
      showToast(err.message, 'error', 'bi-exclamation-triangle');
    }
  });

  permResetBtn?.addEventListener('click', async () => {
    if (!currentPermUser) return;
    if (!confirm(`Reset ${currentPermUser.name}'s access back to the role defaults for ${currentPermUser.role}?`)) return;
    try {
      const res = await fetch('/api/users/permissions', {
        method: 'POST', headers: {'Content-Type':'application/json'},
        body: JSON.stringify({ id: currentPermUser.id, reset: true }),
      });
      const json = await res.json();
      if (!json.ok) throw new Error(json.error);
      showToast('Access reset to role defaults \u2014 refreshing\u2026', 'success', 'bi-check-circle-fill');
      setTimeout(() => window.location.reload(), 700);
    } catch (err) {
      showToast(err.message, 'error', 'bi-exclamation-triangle');
    }
  });

  document.getElementById('userModal').addEventListener('hidden.bs.modal', () => {
    userForm.removeAttribute('data-edit-id');
    userForm.reset(); userForm.classList.remove('was-validated');
    document.getElementById('userModalTitle').textContent = 'Add User';
    document.getElementById('userModalSubmit').textContent = 'Save User';
    pwLabel.textContent = 'Password';
    pwInput.required = false;
    userForm.elements.role.disabled = false;
    userForm.querySelector('[data-admin-role-note]')?.remove();
  });

  userForm.addEventListener('submit', async (e) => {
    if (!userForm.checkValidity()) return;
    e.preventDefault();
    e.stopImmediatePropagation();
    if (userForm.elements.role.disabled) userForm.elements.role.disabled = false;
    const data = Object.fromEntries(new FormData(userForm));
    data.edit_id = userForm.getAttribute('data-edit-id') || null;
    if (!data.edit_id && !data.password) {
      pwInput.setCustomValidity('Required for new accounts.');
      userForm.classList.add('was-validated');
      return;
    }
    pwInput.setCustomValidity('');
    try {
      const res = await fetch('/api/users/save', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
      });
      const json = await res.json();
      if (!json.ok) throw new Error(json.error);
      userModal.hide();
      showToast(data.edit_id ? 'User updated' : 'User created', 'success');
      loadUsers();
    } catch (err) {
      showToast(err.message, 'error', 'bi-exclamation-triangle');
    }
  }, true);

  async function loadLogs(){
    const lb = document.getElementById('logsBody');
    try {
      const res = await fetch('/api/audit-logs');
      const json = await res.json();
      if (!json.ok) throw new Error(json.error);
      lb.innerHTML = '';
      json.data.forEach(l => {
        lb.insertAdjacentHTML('beforeend', `<tr>
          <td class="text-muted-2">${escapeHTML(l.time)}</td><td>${escapeHTML(l.user)}</td>
          <td>${escapeHTML(l.action)}</td><td><span class="tag-chip">${escapeHTML(l.module)}</span></td></tr>`);
      });
      if (!json.data.length) {
        lb.innerHTML = '<tr><td colspan="4" class="text-center text-muted-2 py-3">No activity recorded yet.</td></tr>';
      }
    } catch (err) {
      lb.innerHTML = `<tr><td colspan="4" class="text-center text-danger py-3">${escapeHTML(err.message)}</td></tr>`;
    }
  }

  const IDB_DB = 'parabellum-backup', IDB_STORE = 'kv', IDB_KEY = 'autoBackupDir';
  function idbOpen(){
    return new Promise((res, rej) => {
      const req = indexedDB.open(IDB_DB, 1);
      req.onupgradeneeded = () => req.result.createObjectStore(IDB_STORE);
      req.onsuccess = () => res(req.result);
      req.onerror   = () => rej(req.error);
    });
  }
  async function idbGet(key){
    const db = await idbOpen();
    return new Promise((res, rej) => {
      const tx = db.transaction(IDB_STORE, 'readonly');
      const rq = tx.objectStore(IDB_STORE).get(key);
      rq.onsuccess = () => res(rq.result);
      rq.onerror   = () => rej(rq.error);
    });
  }
  async function idbSet(key, val){
    const db = await idbOpen();
    return new Promise((res, rej) => {
      const tx = db.transaction(IDB_STORE, 'readwrite');
      tx.objectStore(IDB_STORE).put(val, key);
      tx.oncomplete = () => res();
      tx.onerror    = () => rej(tx.error);
    });
  }
  async function idbDel(key){
    const db = await idbOpen();
    return new Promise((res, rej) => {
      const tx = db.transaction(IDB_STORE, 'readwrite');
      tx.objectStore(IDB_STORE).delete(key);
      tx.oncomplete = () => res();
      tx.onerror    = () => rej(tx.error);
    });
  }

  async function verifyPermission(handle, requestIfMissing){
    if (!handle || typeof handle.queryPermission !== 'function') return false;
    const opts = { mode: 'readwrite' };
    if ((await handle.queryPermission(opts)) === 'granted') return true;
    if (!requestIfMissing) return false;
    return (await handle.requestPermission(opts)) === 'granted';
  }

  async function writeBackupInto(dirHandle){
    const res = await fetch('/api/settings/backup');
    const json = await res.json();
    if (!json.ok) throw new Error(json.error || 'Could not generate the backup.');
    const fileHandle = await dirHandle.getFileHandle(json.filename, { create: true });
    const writable   = await fileHandle.createWritable();
    await writable.write(json.sql);
    await writable.close();
    return json.filename;
  }

  const backupBtn   = document.getElementById('createBackupBtn');
  const backupAlert = document.getElementById('backupStatusAlert');

  function setBackupStatus(html){
    if (backupAlert) backupAlert.innerHTML = `<i class="bi bi-check-circle me-1"></i>${html}`;
  }

  backupBtn?.addEventListener('click', async () => {
    if (typeof window.showDirectoryPicker !== 'function') {
      showToast('Saving to a local folder needs a Chromium browser (Chrome or Edge) - this browser does not support it.', 'error', 'bi-exclamation-triangle');
      return;
    }
    backupBtn.disabled = true;
    const originalHtml = backupBtn.innerHTML;
    backupBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Preparing backup…';
    try {
      let dirHandle;
      try {
        dirHandle = await window.showDirectoryPicker({ mode: 'readwrite' });
      } catch (pickErr) {
        if (pickErr && pickErr.name === 'AbortError') return;
        throw pickErr;
      }
      const filename = await writeBackupInto(dirHandle);
      const now = new Date();
      setBackupStatus(`Last backup: <strong>${now.toLocaleString()}</strong> — saved as <code>${escapeHTML(filename)}</code> in <strong>${escapeHTML(dirHandle.name)}</strong>`);
      showToast(`Backup saved to "${dirHandle.name}"`, 'success', 'bi-check-circle-fill');
    } catch (err) {
      showToast(err.message || 'Could not create the backup.', 'error', 'bi-exclamation-triangle');
    } finally {
      backupBtn.innerHTML = originalHtml;
      backupBtn.disabled = false;
    }
  });

  const restoreFileInput  = document.getElementById('restoreFileInput');
  const restoreChooseBtn  = document.getElementById('restoreChooseBtn');
  const restoreRunBtn     = document.getElementById('restoreRunBtn');
  const restoreFileNote   = document.getElementById('restoreFileNote');
  const restoreFileName   = document.getElementById('restoreFileName');
  const restoreFileSize   = document.getElementById('restoreFileSize');
  const restoreConfirmModalEl = document.getElementById('restoreConfirmModal');
  const restoreConfirmModal   = restoreConfirmModalEl ? new bootstrap.Modal(restoreConfirmModalEl) : null;
  let restoreSelectedFile = null;

  const fmtBytes = (n) => n < 1024 ? `${n} B` : n < 1024*1024 ? `${(n/1024).toFixed(1)} KB` : `${(n/1024/1024).toFixed(1)} MB`;

  restoreChooseBtn?.addEventListener('click', () => restoreFileInput.click());
  restoreFileInput?.addEventListener('change', () => {
    const file = restoreFileInput.files && restoreFileInput.files[0];
    restoreSelectedFile = file || null;
    if (!file) {
      restoreFileNote.style.display = 'none';
      restoreRunBtn.disabled = true;
      return;
    }
    restoreFileName.textContent = file.name;
    restoreFileSize.textContent = `(${fmtBytes(file.size)})`;
    restoreFileNote.style.display = '';
    restoreRunBtn.disabled = false;
  });

  restoreRunBtn?.addEventListener('click', () => {
    if (!restoreSelectedFile || !restoreConfirmModal) return;
    document.getElementById('restoreConfirmFileName').textContent = restoreSelectedFile.name;
    restoreConfirmModal.show();
  });

  document.getElementById('restoreConfirmBtn')?.addEventListener('click', async () => {
    if (!restoreSelectedFile) return;
    const confirmBtn = document.getElementById('restoreConfirmBtn');
    const originalHtml = confirmBtn.innerHTML;
    confirmBtn.disabled = true;
    confirmBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Restoring…';
    restoreRunBtn.disabled = true;
    try {
      const text = await restoreSelectedFile.text();
      const res = await fetch('/api/settings/restore', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ sql: text, filename: restoreSelectedFile.name }),
      });
      const json = await res.json();
      if (!json.ok) throw new Error(json.error || 'Restore failed.');

      restoreConfirmModal.hide();
      if (json.stayed_signed_in) {
        showToast(`Database restored from "${restoreSelectedFile.name}". Reloading…`, 'success', 'bi-check-circle-fill');
        setTimeout(() => { window.location.reload(); }, 1200);
      } else {
        showToast(`Database restored from "${restoreSelectedFile.name}". Signing you back in…`, 'success', 'bi-check-circle-fill');
        setTimeout(() => { window.location.href = '/login'; }, 1500);
      }
    } catch (err) {
      showToast(err.message || 'Could not restore the database.', 'error', 'bi-exclamation-triangle');
      confirmBtn.disabled = false;
      confirmBtn.innerHTML = originalHtml;
      restoreRunBtn.disabled = false;
    }
  });

  // Automatic Daily Backup
  const autoToggle      = document.getElementById('autoBackupToggle');
  const autoInfo        = document.getElementById('autoBackupInfo');
  const autoFolderName  = document.getElementById('autoBackupFolderName');
  const autoLastRun     = document.getElementById('autoBackupLastRun');
  const autoChangeBtn   = document.getElementById('autoBackupChangeFolderBtn');
  const autoRunNowBtn   = document.getElementById('autoBackupRunNowBtn');
  const autoPermWarn    = document.getElementById('autoBackupPermWarn');

  const LS_ENABLED  = 'parabellum.autoBackup.enabled';
  const LS_LAST_RUN = 'parabellum.autoBackup.lastRun';
  const ONE_DAY_MS  = 24 * 60 * 60 * 1000;

  function autoRefreshUI(handle){
    const enabled = localStorage.getItem(LS_ENABLED) === '1';
    autoToggle.checked = enabled;
    autoInfo.style.display = enabled ? '' : 'none';
    if (handle) {
      autoFolderName.textContent = handle.name;
    } else {
      autoFolderName.textContent = '—';
    }
    const last = localStorage.getItem(LS_LAST_RUN);
    autoLastRun.textContent = last ? new Date(last).toLocaleString() : 'Never';
  }

  async function autoSetFolder(){
    if (typeof window.showDirectoryPicker !== 'function') {
      showToast('Saving to a local folder needs a Chromium browser (Chrome or Edge) - this browser does not support it.', 'error', 'bi-exclamation-triangle');
      return null;
    }
    let handle;
    try {
      handle = await window.showDirectoryPicker({ mode: 'readwrite', id: 'parabellum-auto-backup' });
    } catch (err) {
      if (err && err.name === 'AbortError') return null;
      throw err;
    }
    await idbSet(IDB_KEY, handle);
    return handle;
  }

  async function autoRunBackup(handle, {silent = false} = {}){
    if (!handle) return false;
    const ok = await verifyPermission(handle, !silent);
    if (!ok) {
      autoPermWarn.style.display = '';
      return false;
    }
    autoPermWarn.style.display = 'none';
    try {
      const filename = await writeBackupInto(handle);
      const now = new Date();
      localStorage.setItem(LS_LAST_RUN, now.toISOString());
      autoLastRun.textContent = now.toLocaleString();
      if (!silent) {
        showToast(`Auto-backup saved to "${handle.name}"`, 'success', 'bi-check-circle-fill');
      }
      return true;
    } catch (err) {
      if (!silent) showToast(err.message || 'Automatic backup failed.', 'error', 'bi-exclamation-triangle');
      return false;
    }
  }

  autoToggle?.addEventListener('change', async () => {
    if (autoToggle.checked) {
      try {
        const handle = await autoSetFolder();
        if (!handle) {
          autoToggle.checked = false;
          return;
        }
        localStorage.setItem(LS_ENABLED, '1');
        autoRefreshUI(handle);
        await autoRunBackup(handle);
      } catch (err) {
        autoToggle.checked = false;
        showToast(err.message || 'Could not enable automatic backup.', 'error', 'bi-exclamation-triangle');
      }
    } else {
      localStorage.removeItem(LS_ENABLED);
      localStorage.removeItem(LS_LAST_RUN);
      try { await idbDel(IDB_KEY); } catch (_) {}
      autoRefreshUI(null);
      showToast('Automatic daily backup disabled.', 'info', 'bi-info-circle-fill');
    }
  });

  autoChangeBtn?.addEventListener('click', async () => {
    try {
      const handle = await autoSetFolder();
      if (!handle) return;
      autoRefreshUI(handle);
      await autoRunBackup(handle);
    } catch (err) {
      showToast(err.message || 'Could not change folder.', 'error', 'bi-exclamation-triangle');
    }
  });

  autoRunNowBtn?.addEventListener('click', async () => {
    const handle = await idbGet(IDB_KEY);
    if (!handle) {
      showToast('Pick a backup folder first.', 'error', 'bi-exclamation-triangle');
      return;
    }
    await autoRunBackup(handle);
  });

  (async () => {
    try {
      const enabled = localStorage.getItem(LS_ENABLED) === '1';
      const handle  = enabled ? await idbGet(IDB_KEY) : null;
      autoRefreshUI(handle);
      if (!enabled || !handle) return;
      const last = parseInt(localStorage.getItem(LS_LAST_RUN)
        ? new Date(localStorage.getItem(LS_LAST_RUN)).getTime()
        : 0, 10);
      if (Date.now() - last >= ONE_DAY_MS) {
        await autoRunBackup(handle, {silent: true});
      } else {
        const ok = await verifyPermission(handle, false);
        if (!ok) autoPermWarn.style.display = '';
      }
    } catch (_) { }
  })();

  loadUsers();
  loadLogs();
});

document.addEventListener('DOMContentLoaded', () => {
  const KEY = 'isos.settings.tab';
  const pills = document.querySelectorAll('[data-bs-toggle="pill"][data-bs-target]');
  pills.forEach(b => b.addEventListener('shown.bs.tab', () => {
    try { sessionStorage.setItem(KEY, b.getAttribute('data-bs-target')); } catch (e) {}
  }));
  try {
    const saved = sessionStorage.getItem(KEY);
    const btn = saved && [...pills].find(b => b.getAttribute('data-bs-target') === saved);
    if (btn && !btn.classList.contains('active')) bootstrap.Tab.getOrCreateInstance(btn).show();
  } catch (e) {}
});

/* Company */
document.addEventListener('DOMContentLoaded', () => {
  const form = document.getElementById('companyForm');
  if (!form) return;
  const fill = (c) => {
    ['company_name', 'tin', 'email', 'phone', 'address', 'currency', 'vat_rate'].forEach(k => {
      if (form.elements[k]) form.elements[k].value = c[k] ?? '';
    });
  };
  fill(window.COMPANY || {});
  fetch('/api/settings/company').then(r => r.json()).then(j => { if (j.ok) fill(j.data); }).catch(() => {});
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    if (!form.checkValidity()) { form.classList.add('was-validated'); return; }
    const btn = document.getElementById('companySaveBtn');
    btn.disabled = true;
    try {
      const body = Object.fromEntries(new FormData(form));
      const res = await fetch('/api/settings/company', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
      });
      const j = await res.json();
      if (!j.ok) { showToast(j.error || 'Could not save company information', 'error', 'bi-exclamation-triangle'); return; }
      fill(j.data);
      window.COMPANY = j.data;
      document.querySelectorAll('.app-footer span').forEach(el => {
        if (el.textContent.includes('Inventory & Service')) el.textContent = `© 2026 ${j.data.company_name} · Inventory & Service Optimization System`;
      });
      document.getElementById('companyUpdated').textContent = 'Saved just now';
      showToast('Company information saved', 'success');
    } catch (_) {
      showToast('Could not reach the server', 'error', 'bi-exclamation-triangle');
    } finally {
      btn.disabled = false;
    }
  });
});

/* Security */
document.addEventListener('DOMContentLoaded', () => {
  const req = document.getElementById('secRequire2fa');
  if (!req) return;
  const alerts = document.getElementById('secLoginAlerts');
  const timeout = document.getElementById('secTimeout');
  const status = document.getElementById('secEmailStatus');
  let state = null;

  const paint = (d) => {
    state = d;
    req.checked = d.require_2fa_admins;
    alerts.checked = d.login_alerts;
    alerts.disabled = !d.emailConfigured && !d.login_alerts;
    timeout.value = String(d.session_timeout_min);
    status.innerHTML = d.emailConfigured
      ? '<span class="text-success"><i class="bi bi-check-circle me-1"></i>Email server is set up.</span>'
      : '<span class="text-muted-2"><i class="bi bi-info-circle me-1"></i>Email server not set up yet (SMTP settings), so emails can\'t be sent.</span>';
  };

  const save = async (changes) => {
    try {
      const res = await fetch('/api/settings/security', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ...state, ...changes }),
      });
      const j = await res.json();
      if (!j.ok) { showToast(j.error || 'Could not save', 'error', 'bi-exclamation-triangle'); paint(state); return; }
      paint(j.data);
      showToast('Security settings saved', 'success');
    } catch (_) {
      showToast('Could not reach the server', 'error', 'bi-exclamation-triangle'); paint(state);
    }
  };

  fetch('/api/settings/security').then(r => r.json()).then(j => { if (j.ok) paint(j.data); }).catch(() => {});
  req.addEventListener('change', () => save({ require_2fa_admins: req.checked }));
  alerts.addEventListener('change', () => save({ login_alerts: alerts.checked }));
  timeout.addEventListener('change', () => save({ session_timeout_min: Number(timeout.value) }));
  document.querySelectorAll('[data-goto-tab]').forEach(a => a.addEventListener('click', (e) => {
    e.preventDefault();
    document.querySelector(`[data-bs-target="${a.dataset.gotoTab}"]`)?.click();
  }));
});
