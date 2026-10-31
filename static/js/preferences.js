/* Preferences */
document.addEventListener('DOMContentLoaded', () => {
  const ACCENTS = {
    red:    ['#b11217', '177, 18, 23', '#8a1214', '#6e0f11'],
    blue:   ['#1d4ed8', '29, 78, 216', '#1e40af', '#1e3a8a'],
    green:  ['#047857', '4, 120, 87', '#065f46', '#064e3b'],
    purple: ['#7c3aed', '124, 58, 237', '#6d28d9', '#5b21b6'],
    slate:  ['#0f172a', '15, 23, 42', '#1e293b', '#020617'],
  };
  let prefs = window.PREFS || {};
  const root = document.documentElement;

  const apply = (p) => {
    root.setAttribute('data-bs-theme', p.dark ? 'dark' : 'light');
    root.classList.toggle('tbl-compact', !!p.compact);
    root.classList.toggle('sb-collapsible', !!p.sidebarCollapsible);
    if (!p.sidebarCollapsible) root.classList.remove('sb-mini');
    const props = ['--primary', '--primary-rgb', '--primary-dark', '--primary-darker', '--sidebar-top', '--sidebar-bottom'];
    if (p.accent && p.accent !== 'red' && ACCENTS[p.accent]) {
      const a = ACCENTS[p.accent];
      [a[0], a[1], a[2], a[3], a[0], a[3]].forEach((v, i) => root.style.setProperty(props[i], v));
      root.setAttribute('data-accent-custom', '');
    } else {
      props.forEach(pr => root.style.removeProperty(pr));
      root.removeAttribute('data-accent-custom');
    }
  };

  const paint = () => {
    document.querySelectorAll('[data-accent]').forEach(b => {
      const on = b.dataset.accent === (prefs.accent || 'red');
      b.classList.toggle('active', on);
      b.style.borderColor = on ? 'var(--text)' : 'var(--border)';
      b.style.boxShadow = on ? '0 0 0 3px var(--card) inset' : 'none';
    });
    document.querySelectorAll('[data-pref]').forEach(i => { i.checked = !!prefs[i.dataset.pref]; });
    document.querySelectorAll('[data-notify]').forEach(i => { i.checked = !!(prefs.notify || {})[i.dataset.notify]; });
  };

  const save = async (changes, label) => {
    const before = JSON.parse(JSON.stringify(prefs));
    prefs = { ...prefs, ...changes, notify: { ...(prefs.notify || {}), ...(changes.notify || {}) } };
    apply(prefs); paint();
    try {
      const res = await fetch('/api/profile/preferences', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(changes),
      });
      const j = await res.json();
      if (!j.ok) throw new Error(j.error);
      prefs = j.data; window.PREFS = prefs;
      apply(prefs); paint();
      showToast(label || 'Preference saved', 'success');
      if (changes.notify && typeof window.refreshNotifications === 'function') window.refreshNotifications();
    } catch (_) {
      prefs = before; apply(prefs); paint();
      showToast('Could not save your preference', 'error', 'bi-exclamation-triangle');
    }
  };

  document.querySelectorAll('[data-accent]').forEach(b => b.addEventListener('click', () => save({ accent: b.dataset.accent }, 'Accent color saved')));
  document.querySelectorAll('[data-pref]').forEach(i => i.addEventListener('change', () => save({ [i.dataset.pref]: i.checked })));
  document.querySelectorAll('[data-notify]').forEach(i => i.addEventListener('change', () => save({ notify: { [i.dataset.notify]: i.checked } }, 'Notification setting saved')));
  paint();
  document.querySelectorAll('.digest-note').forEach(el => el.classList.toggle('d-none', !!window.EMAIL_READY));
});
