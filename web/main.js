/* Запуск приложения: переводы → публичные настройки (название, скин по умолчанию) → вход по сохранённому токену → экран. */
'use strict';
async function boot() {
  $('#lang').addEventListener('change', (e) => setLang(e.target.value));
  $('#logout').addEventListener('click', logout);
  await loadLocales();
  try { S.pub = await api('GET', '/settings/public'); } catch (e) { S.pub = {}; }
  try { S.mapCfg = await api('GET', '/config'); } catch (e) { S.mapCfg = {}; }
  S.token = ls.get('hm_token');
  if (S.token) { try { S.me = await api('GET', '/me'); } catch (e) { S.token = null; S.me = null; } }
  initSkin();
  document.title = S.pub.app_name || 'ProntoFix';
  const brand = $('#brand');
  if (brand) brand.textContent = '🛠 ' + (S.pub.app_name || 'ProntoFix');
  applyBrand();
  if (S.me) resumeTracking();
  window.addEventListener('hashchange', render);
  render();
}
boot();
