/*
 * Возможности устройства: карта (Leaflet), GPS, камера (макс. качество), выбор файлов из любого места,
 * сохранение файлов с выбором папки, фоновая запись трека (Tracker).
 * В Android-приложении часть функций выполняет нативный мост window.AndroidBridge (см. android/MainActivity.java).
 */
'use strict';

const BRIDGE = () => window.AndroidBridge || null;
const IN_APP = () => !!BRIDGE();

// ───────────── Карта (Leaflet) ─────────────
// Источник тайлов задаёт провайдер: google | osm | custom (настройки приходят с сервера: /config).
let leafletPromise = null;
function loadLeaflet() {
  if (window.L) return Promise.resolve(window.L);
  if (!leafletPromise) {
    leafletPromise = new Promise((resolve, reject) => {
      const base = 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/';
      document.head.append(h('link', {rel: 'stylesheet', href: base + 'leaflet.min.css'}));
      const s = h('script', {src: base + 'leaflet.min.js'});
      s.onload = () => resolve(window.L);
      s.onerror = () => { leafletPromise = null; reject(new Error('Leaflet')); };
      document.head.append(s);
      setTimeout(() => reject(new Error('Leaflet timeout')), 12000);
    });
  }
  return leafletPromise;
}
async function makeTileLayer(L) {
  const prov = ls.get('hm_map') || S.mapCfg.map_provider || 'osm';
  if (prov === 'google' && S.mapCfg.google_maps_key) {
    try {   // официальный Google Map Tiles API: создаём сессию, затем берём тайлы по ней
      const key = S.mapCfg.google_maps_key;
      const loc = {ru: 'ru-RU', uk: 'uk-UA', en: 'en-US', pt: 'pt-BR'}[S.lang] || 'en-US';
      const r = await fetch('https://tile.googleapis.com/v1/createSession?key=' + encodeURIComponent(key), {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({mapType: 'roadmap', language: loc, region: loc.slice(-2)})});
      const {session} = await r.json();
      if (session) return L.tileLayer(`https://tile.googleapis.com/v1/2dtiles/{z}/{x}/{y}?session=${session}&key=${key}`, {maxZoom: 22, attribution: 'Map data © Google'});
    } catch (e) { /* падаем на OSM */ }
  }
  if (prov === 'custom' && S.mapCfg.custom_tile_url) return L.tileLayer(S.mapCfg.custom_tile_url, {maxZoom: 19});
  return L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {maxZoom: 19, attribution: '© OpenStreetMap'});
}
async function drawMap(box, lat, lon, marker, zoom = 15) {
  const L = await loadLeaflet();
  const map = L.map(box).setView([lat, lon], zoom);
  (await makeTileLayer(L)).addTo(map);
  if (marker) L.marker([lat, lon]).addTo(map);
  setTimeout(() => map.invalidateSize(), 150);
  return map;
}
const STATUS_COLOR = {new: '#2f6fed', assigned: '#e08a00', accepted: '#e08a00', in_progress: '#e8590c', estimate: '#8e44ad', done: '#1b9e5a', cancelled: '#888'};
// Выбор точки: двигаем карту, красный крест в центре = выбранное место. → Promise<{lat, lon} | null>
function mapPicker(lat, lon) {
  return new Promise(async (resolve) => {
    const box = h('div', {class: 'mapbox big'}, h('div', {class: 'cross'}, '+'));
    let map = null, close;
    const body = h('div', {}, h('p', {class: 'muted small'}, t('pick_point_hint')), box,
      h('div', {class: 'row', style: 'margin-top:10px'},
        h('button', {onclick: () => { if (!map) return; const c = map.getCenter(); close(); resolve({lat: c.lat, lon: c.lng}); }}, t('set_here')),
        h('button', {class: 'ghost', onclick: () => { close(); resolve(null); }}, t('cancel'))));
    close = modal(t('set_location'), body, () => resolve(null));
    try { map = await drawMap(box, lat, lon, false); }
    catch (e) {   // нет интернета для карты → ввод координат вручную
      box.replaceChildren();
      const la = h('input', {value: lat}), lo = h('input', {value: lon});
      box.append(h('div', {style: 'padding:12px'}, h('label', {}, 'lat'), la, h('label', {}, 'lon'), lo));
      map = {getCenter: () => ({lat: parseFloat(la.value), lng: parseFloat(lo.value)})};
    }
  });
}
const mapLink = (lat, lon, label) => `https://www.google.com/maps/dir/?api=1&destination=${lat},${lon}`;

// ───────────── GPS ─────────────
function gpsLocate(quiet) {
  return new Promise((resolve, reject) => {
    if (!navigator.geolocation) return reject(new Error('Геолокация недоступна в этом браузере или WebView.'));
    if (!window.isSecureContext && location.hostname !== 'localhost') {
      return reject(new Error('Геолокация требует HTTPS (либо localhost). Проверьте адрес сервера.'));
    }
    if (!quiet) toast(t('gps_wait'));
    navigator.geolocation.getCurrentPosition(
      (p) => resolve({lat: p.coords.latitude, lon: p.coords.longitude, accuracy: p.coords.accuracy}),
      (e) => {
        const messages = {
          1: 'Нет разрешения на геолокацию. Разрешите доступ к местоположению в Android и браузере.',
          2: 'Телефон не смог определить местоположение. Проверьте GPS и системную геолокацию.',
          3: 'Истекло время ожидания GPS. Выйдите на открытое место и повторите попытку.'
        };
        reject(new Error(messages[e && e.code] || ('Не удалось получить координаты: ' + (e && e.message || 'неизвестная ошибка'))));
      },
      {enableHighAccuracy: true, timeout: 20000, maximumAge: quiet ? 60000 : 0}
    );
  });
}
// км по прямой между точками (для подсказок на экране; точный расчёт — на сервере)
function haversine(a, b) {
  const R = 6371.0088, rad = Math.PI / 180;
  const dLat = (b.lat - a.lat) * rad, dLon = (b.lon - a.lon) * rad;
  const x = Math.sin(dLat / 2) ** 2 + Math.cos(a.lat * rad) * Math.cos(b.lat * rad) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(x));
}

// ───────────── Камера в максимальном качестве ─────────────
async function toJpeg(blob) {
  const bmp = await createImageBitmap(blob);
  const c = document.createElement('canvas');
  c.width = bmp.width; c.height = bmp.height;
  c.getContext('2d').drawImage(bmp, 0, 0);
  return new Promise((r) => c.toBlob(r, 'image/jpeg', 0.95));
}
async function cameraCapture() {
  // HTTP origins in Android WebView are not secure contexts: getUserMedia is absent
  // even when Android CAMERA permission is granted. Fall back to Android's file picker;
  // it may offer Camera/Gallery depending on device. Live in-app capture needs HTTPS.
  if (!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia)) {
    const files = await chooseFiles('image/*', false, 'environment');
    if (!files || !files.length) return null;
    const f = files[0];
    if (!f.type || !f.type.startsWith('image/')) throw new Error('Выберите файл изображения.');
    return f;
  }
  const stream = await navigator.mediaDevices.getUserMedia({video: {facingMode: {ideal: 'environment'}, width: {ideal: 4096}, height: {ideal: 3072}}, audio: false});
  return new Promise((resolve) => {
    const video = h('video', {class: 'cam', autoplay: true, playsinline: true, muted: true});
    video.srcObject = stream;
    let close;
    const stop = () => stream.getTracks().forEach((tr) => tr.stop());
    const shoot = async () => {
      const track = stream.getVideoTracks()[0];
      let blob = null;
      try {
        if ('ImageCapture' in window) {   // полный кадр датчика, если браузер умеет
          const ic = new ImageCapture(track), caps = await ic.getPhotoCapabilities();
          blob = await ic.takePhoto({imageWidth: caps.imageWidth && caps.imageWidth.max, imageHeight: caps.imageHeight && caps.imageHeight.max});
        }
      } catch (e) { blob = null; }
      if (!blob) {   // запасной путь: кадр видеопотока в родном разрешении, JPEG 95%
        const c = document.createElement('canvas');
        c.width = video.videoWidth; c.height = video.videoHeight;
        c.getContext('2d').drawImage(video, 0, 0);
        blob = await new Promise((r) => c.toBlob(r, 'image/jpeg', 0.95));
      }
      if (blob.type !== 'image/jpeg') blob = await toJpeg(blob);
      stop(); close();
      resolve(new File([blob], `doc_${Date.now()}.jpg`, {type: 'image/jpeg'}));
    };
    const body = h('div', {}, h('p', {class: 'muted small'}, t('camera_hint')), video,
      h('div', {class: 'row', style: 'margin-top:10px'},
        h('button', {onclick: guard(shoot)}, t('shoot')),
        h('button', {class: 'ghost', onclick: () => { stop(); close(); resolve(null); }}, t('cancel'))));
    close = modal(t('take_photo'), body, () => { stop(); resolve(null); });
  });
}

// ───────────── Файлы: выбор из любого места устройства ─────────────
// accept: '' = любые файлы (проводник/«Файлы» системы). capture: 'environment' откроет камеру.
function chooseFiles(accept, multiple = true, capture) {
  return new Promise((resolve) => {
    const inp = h('input', {type: 'file', multiple, style: 'display:none'});
    if (accept) inp.accept = accept;
    if (capture) inp.setAttribute('capture', capture);
    inp.addEventListener('change', () => { resolve([...inp.files]); inp.remove(); });
    document.body.append(inp);
    inp.click();
  });
}
const DOC_ACCEPT = 'image/jpeg,application/pdf,.jpg,.jpeg,.pdf';
const isDoc = (f) => /\.(jpe?g|pdf)$/i.test(f.name) || ['image/jpeg', 'application/pdf'].includes(f.type);
const fileIcon = (name, mime) => /^image\//.test(mime || '') ? '🖼' : /^video\//.test(mime || '') ? '🎞' : /^audio\//.test(mime || '') ? '🎵' : /pdf/.test(mime || name) ? '📄' : /xls|csv|ods/i.test(name) ? '📊' : /zip|rar|7z/i.test(name) ? '🗜' : '📎';
function fileList(files, onChange) {
  const box = h('div', {class: 'filelist'});
  const draw = () => box.replaceChildren(...files.map((f, i) => h('div', {class: 'item'},
    f.type.startsWith('image/') ? h('img', {src: URL.createObjectURL(f), alt: ''}) : h('div', {class: 'pdf'}, fileIcon(f.name, f.type)),
    h('div', {class: 'grow'}, f.name, h('div', {class: 'muted small'}, fmtBytes(f.size))),
    h('button', {class: 'ghost', onclick: () => { files.splice(i, 1); draw(); onChange && onChange(); }}, '✕'))));
  draw();
  return {el: box, redraw: draw};
}

// ───────────── Сохранение файла с выбором места ─────────────
// 1) в Android-приложении — системное окно «Сохранить как…» (можно выбрать папку/SD-карту/Google Диск);
// 2) в настольном Chrome/Edge — окно выбора папки и имени (File System Access API);
// 3) иначе — обычная загрузка браузером.
function blobToBase64(blob) {
  return new Promise((res, rej) => { const r = new FileReader(); r.onload = () => res(String(r.result).split(',')[1]); r.onerror = rej; r.readAsDataURL(blob); });
}
async function saveBlob(blob, name, mime) {
  mime = mime || blob.type || 'application/octet-stream';
  if (BRIDGE() && BRIDGE().saveBase64) { BRIDGE().saveBase64(name, mime, await blobToBase64(blob)); return 'app'; }
  if (window.showSaveFilePicker) {
    try {
      const ext = (name.split('.').pop() || '').toLowerCase();
      const fh = await window.showSaveFilePicker({suggestedName: name, types: ext ? [{description: name, accept: {[mime]: ['.' + ext]}}] : undefined});
      const w = await fh.createWritable();
      await w.write(blob); await w.close();
      toast(t('saved'));
      return 'picker';
    } catch (e) { if (e && e.name === 'AbortError') return 'cancel'; }
  }
  const a = h('a', {href: URL.createObjectURL(blob), download: name});
  document.body.append(a); a.click(); a.remove();
  return 'download';
}
// Сохранить файл с сервера по ссылке (большие видео в приложении качаются напрямую, минуя память страницы)
async function saveUrl(url, name, mime) {
  if (BRIDGE() && BRIDGE().saveUrl) { BRIDGE().saveUrl(new URL(url, location.href).href, name, mime || ''); return 'app'; }
  const r = await fetch(url);
  if (!r.ok) throw new Error(r.statusText);
  return saveBlob(await r.blob(), name, mime);
}
// Скачать отчёт .xlsx и предложить сохранить
async function downloadReport(kind, params) {
  const qs = new URLSearchParams(Object.assign({lang: S.lang}, params || {})).toString();
  const r = await fetch(`/reports/${kind}.xlsx?${qs}`, {headers: {Authorization: 'Bearer ' + S.token}});
  if (!r.ok) { let d = null; try { d = (await r.json()).detail; } catch (e) { /* не JSON */ } throw new Error(d || r.statusText); }
  const cd = r.headers.get('Content-Disposition') || '';
  const name = (cd.match(/filename="?([^";]+)"?/) || [])[1] || `${kind}.xlsx`;
  return saveBlob(await r.blob(), name, 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet');
}

// ───────────── Трекинг положения ─────────────
// Пока включён, положение пишется в фоне страницы, пачками уходит на сервер (раз в 20 с). Сервер по точкам считает
// фактический километраж и показывает сотрудника на карте администратора. Экран при этом не гаснет (wake lock / мост приложения).
const Tracker = {
  watchId: null, buf: [], timer: null, routeId: null, last: null, wake: null, lastSent: 0,
  active() { return this.watchId != null; },
  badge(on) { const b = $('#gps-badge'); if (b) b.hidden = !on; },
  async keepAwake(on) {
    if (BRIDGE() && BRIDGE().keepScreenOn) BRIDGE().keepScreenOn(!!on);
    try {
      if (on && navigator.wakeLock) this.wake = await navigator.wakeLock.request('screen');
      else if (!on && this.wake) { await this.wake.release(); this.wake = null; }
    } catch (e) { /* не поддерживается */ }
  },
  start(routeId) {
    if (!navigator.geolocation) { toast(t('gps_unavailable'), true); return false; }
    if (routeId) this.routeId = routeId;
    if (this.watchId != null) return true;
    this.watchId = navigator.geolocation.watchPosition((p) => this.onPos(p), () => {}, {enableHighAccuracy: true, maximumAge: 3000, timeout: 30000});
    this.timer = setInterval(() => this.flush(), 20000);
    ls.set('hm_tracking', '1');
    this.keepAwake(true); this.badge(true);
    return true;
  },
  stop(persist = true) {
    if (this.watchId != null) navigator.geolocation.clearWatch(this.watchId);
    clearInterval(this.timer);
    this.watchId = null; this.timer = null;
    this.flush();
    this.keepAwake(false); this.badge(false);
    if (persist) ls.set('hm_tracking', null);
  },
  onPos(p) {
    const c = p.coords;
    if (c.accuracy != null && c.accuracy > 150) return;      // слишком неточная точка
    const pt = {lat: c.latitude, lon: c.longitude, accuracy: c.accuracy, speed: c.speed, ts: new Date(p.timestamp).toISOString()};
    if (this.last && haversine(this.last, pt) * 1000 < 4 && p.timestamp - this.last.t < 60000) return;   // дрожание на месте
    this.last = {lat: pt.lat, lon: pt.lon, t: p.timestamp};
    this.buf.push(pt);
    if (this.buf.length >= 12) this.flush();
  },
  async flush() {
    if (!this.buf.length || !S.token) return;
    const pts = this.buf.splice(0, 500);
    try { await api('POST', '/tracking/points', {points: pts, route_id: this.routeId}); this.lastSent = Date.now(); }
    catch (e) { this.buf.unshift(...pts); if (this.buf.length > 3000) this.buf.splice(0, this.buf.length - 3000); }
  },
};
document.addEventListener('visibilitychange', () => { if (!document.hidden && Tracker.active()) { Tracker.keepAwake(true); Tracker.flush(); } });
