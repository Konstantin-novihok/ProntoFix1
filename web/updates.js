/* Home Master Android release banner. The server advertises only published stable APK releases. */
(() => {
  'use strict';
  const DISMISSED = 'hm_update_dismissed_v1';
  let latest = null;
  let banner = null;

  function installedVersion() {
    try {
      if (window.AndroidBridge && typeof AndroidBridge.appVersion === 'function') return String(AndroidBridge.appVersion());
    } catch (_) {}
    return '';
  }
  function parts(v) {
    return String(v || '').replace(/^v/i, '').split(/[.+-]/).slice(0, 4).map(x => {
      const n = parseInt(x, 10); return Number.isFinite(n) ? n : 0;
    });
  }
  function newer(remote, local) {
    const a = parts(remote), b = parts(local);
    for (let i = 0; i < Math.max(a.length, b.length); i++) {
      const x = a[i] || 0, y = b[i] || 0;
      if (x !== y) return x > y;
    }
    return false;
  }
  function removeBanner() {
    if (banner) banner.remove();
    banner = null;
  }
  function download() {
    if (!latest || !latest.apk_url) return;
    const name = latest.apk_name || 'HomeMaster.apk';
    try {
      if (window.AndroidBridge && typeof AndroidBridge.saveUrl === 'function') {
        AndroidBridge.saveUrl(latest.apk_url, name, 'application/vnd.android.package-archive');
        return;
      }
    } catch (_) {}
    window.open(latest.apk_url, '_blank', 'noopener');
  }
  function show(force) {
    if (!latest || !newer(latest.version, installedVersion())) return;
    if (!force && localStorage.getItem(DISMISSED) === latest.version) return;
    removeBanner();
    banner = document.createElement('section');
    banner.setAttribute('role', 'status');
    banner.style.cssText = 'margin:12px auto;padding:14px 16px;max-width:1100px;border:1px solid #8ab4f8;border-radius:14px;background:#eef5ff;color:#172b4d;display:flex;gap:12px;align-items:center;flex-wrap:wrap';
    const info = document.createElement('div');
    info.style.cssText = 'flex:1;min-width:180px';
    const title = document.createElement('strong');
    title.textContent = 'Доступно обновление Home Master ' + latest.version;
    const desc = document.createElement('div');
    desc.textContent = 'Установлена версия ' + (installedVersion() || 'неизвестна') + '. Новая версия готова к загрузке.';
    desc.style.cssText = 'font-size:13px;margin-top:4px';
    info.append(title, desc);
    const apply = document.createElement('button');
    apply.type = 'button'; apply.textContent = 'Скачать обновление'; apply.addEventListener('click', download);
    const later = document.createElement('button');
    later.type = 'button'; later.className = 'ghost'; later.textContent = 'Позже';
    later.addEventListener('click', () => { try { localStorage.setItem(DISMISSED, latest.version); } catch (_) {} removeBanner(); });
    banner.append(info, apply, later);
    const header = document.querySelector('.top');
    if (header && header.parentNode) header.parentNode.insertBefore(banner, header.nextSibling);
  }
  async function check(force) {
    try {
      const response = await fetch('/updates/latest', {cache: 'no-store'});
      if (!response.ok) {
        if (response.status === 404) { latest = null; removeBanner(); return null; }
        throw new Error('HTTP ' + response.status);
      }
      latest = await response.json();
      show(!!force);
      return latest;
    } catch (e) {
      if (force && window.toast) toast('Не удалось проверить обновления: ' + e.message, true);
      return null;
    }
  }
  window.HomeMasterUpdates = {check, download, getLatest: () => latest};
  document.addEventListener('DOMContentLoaded', () => {
    check(false);
    document.addEventListener('visibilitychange', () => { if (!document.hidden) check(false); });
  });
})();
