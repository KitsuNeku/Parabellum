/* Profile page */
document.addEventListener('DOMContentLoaded', () => {
  const $ = (id) => document.getElementById(id);
  const esc = (v) => String(v == null ? '' : v).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const ICONS = {
    LOGIN_SUCCESS:   ['b-info',    'bi-box-arrow-in-right', 'Signed in'],
    LOGOUT:          ['b-neutral', 'bi-box-arrow-right',    'Signed out'],
    RUN_FORECAST:    ['b-success', 'bi-graph-up-arrow',     'Ran demand forecast'],
    REPORT_EXPORTED: ['b-gold',    'bi-file-earmark-text',  'Exported report'],
  };
  const look = (a) => ICONS[a] || (/DELETE|REMOVE/.test(a) ? ['b-danger','bi-trash','']
                    : /SETTING|ROLE|PERMISSION|USER/.test(a) ? ['b-neutral','bi-gear','']
                    : ['b-neutral','bi-activity','']);
  const nice = (a) => a.toLowerCase().replace(/_/g,' ').replace(/^./, c => c.toUpperCase());

  fetch('/api/profile', { credentials: 'same-origin' })
    .then(r => r.json())
    .then(res => {
      if (!res.ok) throw new Error(res.error || 'Failed');
      const d = res.data;
      $('profEmailLine').textContent = d.email || 'No email on file';
      $('profEmail').value = d.email || '';
      $('profUserCode').value = d.userCode;
      $('profDept').value = d.department || '';
      $('profStatLogins').textContent = d.stats.logins;
      $('profStatReports').textContent = d.stats.reports;
      $('profStatForecasts').textContent = d.stats.forecasts;
      if (window.setActivityChart) window.setActivityChart(d.week.map(x => x.label), d.week.map(x => x.n));
      $('profActivityList').innerHTML = d.recent.length
        ? d.recent.map(r => {
            const [tone, ic, label] = look(r.action);
            const title = label || nice(r.action);
            return `<div class="activity-item"><div class="activity-ic ${tone}"><i class="bi ${ic}"></i></div><div class="flex-grow-1"><div class="fw-medium">${esc(title)}</div><div class="small text-muted-2">${esc(r.details)}${r.details ? ' &middot; ' : ''}${esc(r.time)}</div></div></div>`;
          }).join('')
        : '<div class="small text-muted-2 py-2">No activity recorded yet.</div>';
    })
    .catch(() => {
      $('profActivityList').innerHTML = '<div class="small text-muted-2 py-2">Could not load your activity.</div>';
      if (typeof showToast === 'function') showToast('Could not load your profile details.', 'error', 'bi-exclamation-triangle');
    });
});

   document.addEventListener('DOMContentLoaded', () => {
     const input = document.getElementById('photoInput');
     const btn   = document.getElementById('changePhotoBtn');
     const avatar= document.getElementById('profileAvatar');
     btn?.addEventListener('click', () => input.click());
     input?.addEventListener('change', async () => {
       const file = input.files && input.files[0];
       if (!file) return;

       const previewUrl = URL.createObjectURL(file);
       avatar.innerHTML = `<img src="${previewUrl}" alt="Profile photo" style="width:100%;height:100%;object-fit:cover;border-radius:inherit;">`;

       const formData = new FormData();
       formData.append('photo', file);
       try {
         const res = await fetch('/api/profile/avatar', { method: 'POST', body: formData });
         const json = await res.json();
         if (!json.ok) throw new Error(json.error);
         showToast('Profile photo updated', 'success', 'bi-camera');
       } catch (err) {
         showToast(err.message, 'error', 'bi-exclamation-triangle');
       }
     });
   });


/* Profile + password forms */
document.addEventListener('DOMContentLoaded', () => {
  const post = async (url, body) => {
    const res = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    return res.json();
  };

  const pf = document.getElementById('profileForm');
  pf?.addEventListener('submit', async (e) => {
    e.preventDefault();
    if (!pf.checkValidity()) { pf.classList.add('was-validated'); return; }
    const btn = document.getElementById('profSaveBtn'); btn.disabled = true;
    try {
      const j = await post('/api/profile/save', Object.fromEntries(new FormData(pf)));
      if (!j.ok) { showToast(j.error || 'Could not save your profile', 'error', 'bi-exclamation-triangle'); return; }
      const name = j.data.name;
      const initials = name.split(/\s+/).filter(Boolean).map(w => w[0]).join('').toUpperCase().slice(0, 2);
      document.querySelectorAll('.u-name, .p-name, .profile-user-name').forEach(el => { el.textContent = name; });
      document.querySelectorAll('.avatar-gold, .avatar-sm').forEach(el => { if (!el.querySelector('img')) el.textContent = initials; });
      const line = document.getElementById('profEmailLine');
      if (line) line.textContent = j.data.email || 'No email on file';
      pf.classList.remove('was-validated');
      showToast('Profile updated', 'success');
    } catch (_) {
      showToast('Could not reach the server', 'error', 'bi-exclamation-triangle');
    } finally { btn.disabled = false; }
  });

  const pw = document.getElementById('passwordForm');
  pw?.addEventListener('submit', async (e) => {
    e.preventDefault();
    const confirm = pw.elements.confirm;
    confirm.setCustomValidity(confirm.value && confirm.value !== pw.elements.new.value ? 'mismatch' : '');
    if (!pw.checkValidity()) { pw.classList.add('was-validated'); return; }
    const btn = document.getElementById('pwSaveBtn'); btn.disabled = true;
    try {
      const j = await post('/api/profile/password', Object.fromEntries(new FormData(pw)));
      if (!j.ok) { showToast(j.error || 'Could not change your password', 'error', 'bi-exclamation-triangle'); return; }
      pw.reset(); pw.classList.remove('was-validated');
      showToast('Password changed', 'success');
      document.dispatchEvent(new Event('password:changed'));
    } catch (_) {
      showToast('Could not reach the server', 'error', 'bi-exclamation-triangle');
    } finally { btn.disabled = false; }
  });
  pw?.elements.confirm.addEventListener('input', () => pw.elements.confirm.setCustomValidity(''));
});

/* Two-factor */
document.addEventListener('DOMContentLoaded', () => {
  const $ = (id) => document.getElementById(id);
  if (!$('tfCard')) return;
  const post = async (url, body) => {
    const res = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) });
    return res.json();
  };
  const digits = (el) => el.addEventListener('input', () => { el.value = el.value.replace(/\D/g, '').slice(0, 6); });
  digits($('tfEnableCode')); digits($('tfDisableCode'));

  const drawQr = (text) => {
    const { QRCode, Level } = window.QRCodeLib;
    const q = new QRCode(-1, Level.M); q.addData(text); q.make();
    const n = q.getModuleCount(), s = 5, pad = 2, W = (n + pad * 2) * s;
    let rects = '';
    for (let r = 0; r < n; r++) for (let c = 0; c < n; c++) {
      if (q.isDark(r, c)) rects += `<rect x="${(c + pad) * s}" y="${(r + pad) * s}" width="${s}" height="${s}"/>`;
    }
    $('tfQr').innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${W}" viewBox="0 0 ${W} ${W}"><rect width="100%" height="100%" fill="#fff"/><g fill="#000">${rects}</g></svg>`;
  };

  const setState = (on) => {
    $('tfStatus').textContent = on ? 'On' : 'Off';
    $('tfStatus').className = `badge ${on ? 'b-success' : 'b-neutral'}`;
    $('tfOn').classList.toggle('d-none', !on);
    $('tfOff').classList.toggle('d-none', on);
    $('tfSetup').classList.add('d-none');
    $('tfStartBtn').classList.remove('d-none');
  };

  $('tfStartBtn').addEventListener('click', async () => {
    const j = await post('/api/profile/2fa/setup');
    if (!j.ok) { showToast(j.error || 'Could not start setup', 'error', 'bi-exclamation-triangle'); return; }
    $('tfSecret').textContent = j.data.secret.replace(/(.{4})/g, '$1 ').trim();
    drawQr(j.data.uri);
    $('tfSetup').classList.remove('d-none');
    $('tfStartBtn').classList.add('d-none');
    $('tfEnableCode').focus();
  });

  $('tfEnableBtn').addEventListener('click', async () => {
    const j = await post('/api/profile/2fa/enable', { code: $('tfEnableCode').value });
    if (!j.ok) { showToast(j.error || 'Code is not correct', 'error', 'bi-exclamation-triangle'); return; }
    $('tfEnableCode').value = '';
    setState(true);
    $('force2faBanner')?.remove();
    showToast('Two-factor authentication is on', 'success');
  });

  $('tfDisableBtn').addEventListener('click', async () => {
    const j = await post('/api/profile/2fa/disable', { password: $('tfDisablePw').value, code: $('tfDisableCode').value });
    if (!j.ok) { showToast(j.error || 'Could not turn it off', 'error', 'bi-exclamation-triangle'); return; }
    $('tfDisablePw').value = ''; $('tfDisableCode').value = '';
    setState(false);
    showToast('Two-factor authentication is off', 'success');
  });
});

/* Temporary password banner */
document.addEventListener('DOMContentLoaded', () => {
  const banner = document.getElementById('mustChangeBanner');
  if (!banner) return;
  document.getElementById('passwordForm')?.scrollIntoView({ behavior: 'smooth', block: 'center' });
  document.addEventListener('password:changed', () => {
    banner.className = 'alert alert-soft-success';
    banner.innerHTML = '<i class="bi bi-check-circle me-1"></i>Password updated. You can now use the whole system.';
  });
});
