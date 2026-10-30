/*
 * ProntoFix / Home Master — ВЕБ-ВЕРСИЯ. Ядро: состояние, безопасный DOM-помощник h(), переводы, запросы к API,
 * окна (выбор, форма, подтверждение), таблицы, маршрутизатор. Остальные файлы добавляют экраны через route(...).
 * Работает одинаково в браузере и внутри Android-приложения (WebView). Без сборки и внешних библиотек.
 */
'use strict';

// ───────────── Константы и состояние ─────────────
const ROLE_KEYS = {1: 'role_owner', 2: 'role_head', 3: 'role_executor', 4: 'role_client', 5: 'role_staff', 6: 'role_observer', 7: 'role_admin'};
const STATUSES = ['new', 'assigned', 'accepted', 'in_progress', 'estimate', 'done', 'cancelled'];
const ADMIN_ROLES = [1, 7];
const STAFF_ROLES = [1, 2, 3, 6, 7];
const S = {lang: 'ru', tr: {}, en: {}, langs: [], token: null, me: null, mapCfg: {}, pub: {}, reg: null, draft: null, cleanup: []};
const $ = (sel, el = document) => el.querySelector(sel);
const isAdmin = () => !!S.me && ADMIN_ROLES.includes(S.me.role);
const roleIn = (...r) => !!S.me && r.includes(S.me.role);
const ls = {
  get: (k) => { try { return localStorage.getItem(k); } catch (e) { return null; } },
  set: (k, v) => { try { v == null ? localStorage.removeItem(k) : localStorage.setItem(k, v); } catch (e) { /* хранилище недоступно */ } },
};

// ───────────── DOM-помощник ─────────────
// h('div', {class:'x', onclick: fn}, 'текст', h('b', {}, 'ещё')) создаёт элементы БЕЗ innerHTML:
// текст от пользователей (названия заказов, чат, комментарии) никогда не исполняется как HTML.
function h(tag, props, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (v == null || v === false) continue;
    if (k === 'class') el.className = v;
    else if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
    else if (['value', 'checked', 'disabled', 'selected', 'hidden'].includes(k)) el[k] = v;
    else el.setAttribute(k, v === true ? '' : v);
  }
  const add = (k) => {
    if (Array.isArray(k)) k.forEach(add);
    else if (k == null || k === false) return;
    else el.append(k instanceof Node ? k : document.createTextNode(String(k)));
  };
  kids.forEach(add);
  if (props && 'value' in props) el.value = props.value;   // для <select>: значение после добавления <option>
  return el;
}
const svg = (tag, attrs, ...kids) => {
  const el = document.createElementNS('http://www.w3.org/2000/svg', tag);
  for (const [k, v] of Object.entries(attrs || {})) if (v != null) el.setAttribute(k, v);
  kids.flat().forEach((k) => k != null && el.append(k instanceof Node ? k : document.createTextNode(String(k))));
  return el;
};
const fmtDate = (iso) => { try { return new Date(iso + (iso.endsWith('Z') || iso.includes('+') ? '' : 'Z')).toLocaleString(); } catch (e) { return iso; } };
const fmtDay = (iso) => { try { return new Date(iso + (iso.endsWith('Z') ? '' : 'Z')).toLocaleDateString(); } catch (e) { return iso; } };
const personName = (u) => (u && (u.full_name || u.username || u.name)) || '-';
const money = (n) => `${Number(n || 0).toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})} ${S.pub.currency || ''}`.trim();
const num = (n, d = 2) => Number(n || 0).toLocaleString(undefined, {maximumFractionDigits: d});
const fmtBytes = (b) => b < 1024 ? b + ' B' : b < 1048576 ? (b / 1024).toFixed(0) + ' KB' : b < 1073741824 ? (b / 1048576).toFixed(1) + ' MB' : (b / 1073741824).toFixed(2) + ' GB';
const today = () => new Date().toISOString().slice(0, 10);
const daysAgo = (n) => new Date(Date.now() - n * 864e5).toISOString().slice(0, 10);

// ───────────── Переводы ─────────────
// Тексты — в locales/<код>.json. Новый язык: скопируйте en.json в de.json и переведите: язык появится в списке сам.
const t = (key) => { const v = S.tr[key] || S.en[key]; if (!v) (S.missing || (S.missing = new Set())).add(key); return v || key; };
async function loadLocales() {
  try { S.langs = await (await fetch('/locales')).json(); } catch (e) { S.langs = [{code: 'en', name: 'English'}]; }
  S.en = await (await fetch('locales/en.json')).json().catch(() => ({}));
  const saved = ls.get('hm_lang');
  const guess = (navigator.language || 'ru').slice(0, 2);
  S.lang = [saved, guess, 'ru'].find((c) => c && S.langs.some((l) => l.code === c)) || 'en';
  await setLang(S.lang, false);
}
async function setLang(code, rerender = true) {
  S.lang = code;
  ls.set('hm_lang', code);
  S.tr = await (await fetch(`locales/${code}.json`)).json().catch(() => ({}));
  document.documentElement.lang = code;
  const sel = $('#lang');
  sel.replaceChildren(...S.langs.map((l) => h('option', {value: l.code, selected: l.code === code}, l.name)));
  $('#logout').textContent = t('logout');
  if (rerender) render();
}

// ───────────── Запросы к API ─────────────
// Durable local order outbox. Stored per authenticated account in localStorage; no files are queued.
const OUTBOX_KEY = 'hm_order_outbox_v1';
const queueOwner = () => S.me ? String(S.me.id) : 'anonymous';
function outboxRead() { try { const a=JSON.parse(ls.get(OUTBOX_KEY)||'[]'); return Array.isArray(a)?a:[]; } catch (_) { return []; } }
function outboxWrite(a) { ls.set(OUTBOX_KEY, JSON.stringify(a)); }
function outboxCount() { return outboxRead().filter(x=>x.owner===queueOwner()).length; }
function outboxId() { return 'hm-' + (crypto.randomUUID ? crypto.randomUUID() : Date.now()+'-'+Math.random().toString(16).slice(2)); }
async function queueOrder(payload, stableId) {
  const id=stableId || outboxId();
  const all=outboxRead(), existing=all.find(x=>x.id===id && x.owner===queueOwner());
  if(existing) {
    if(JSON.stringify(existing.payload)!==JSON.stringify(payload)) throw new Error('Конфликт данных для ID заявки');
    return {queued:true,client_request_id:existing.id};
  }
  const entry={id,owner:queueOwner(),payload,state:'pending',attempted:false,created_at:new Date().toISOString(),last_error:''};
  all.push(entry); outboxWrite(all);
  return {queued:true,client_request_id:entry.id};
}
async function syncOrderOutbox() {
  if (!S.token || !S.me || !navigator.onLine || window.__hmOutboxSyncing) return;
  window.__hmOutboxSyncing=true;
  try {
    const all=outboxRead(), owned=all.filter(x=>x.owner===queueOwner());
    for(const item of owned) {
      if(item.state==='cancelled' || item.state==='synced') continue;
      // A deterministic client/permission error needs user correction, not a retry loop.
      if(item.state==='error' && item.retryable===false) continue;
      // A prior page may have closed while its request was in flight. With the
      // same idempotency key, retry is safer than leaving the entry stuck.
      if(item.state==='sending') {
        item.state='uncertain';
        item.last_error='Восстановлено после прерывания; сервер мог принять заявку';
        outboxWrite(outboxRead().map(x=>x.id===item.id?item:x));
      }
      item.state='sending'; item.attempted=true; item.attempted_at=new Date().toISOString();
      outboxWrite(outboxRead().map(x=>x.id===item.id?item:x));
      try {
        const opt={method:'POST',headers:{Authorization:'Bearer '+S.token,'Content-Type':'application/json','X-Client-Request-ID':item.id},body:JSON.stringify(item.payload)};
        const res=await fetch('/orders',opt); const data=await res.json().catch(()=>null);
        if(!res.ok) { item.last_error=(data&&data.detail)||('HTTP '+res.status); item.state='error'; item.http_status=res.status; item.retryable=res.status===408 || res.status===429 || res.status>=500; }
        else { item.state='synced'; item.order_id=data.id; item.synced_at=new Date().toISOString(); item.last_error=''; item.retryable=false; }
        outboxWrite(outboxRead().map(x=>x.id===item.id?item:x));
      } catch(e) { item.last_error='Результат отправки неизвестен; безопасный повтор с тем же ID'; item.state='uncertain'; outboxWrite(outboxRead().map(x=>x.id===item.id?item:x)); break; }
    }
  } finally { window.__hmOutboxSyncing=false; }
}
window.addEventListener('online',()=>syncOrderOutbox().then(()=>{if(S.me)toast('Синхронизация локальной очереди завершена');}).catch(()=>{}));
document.addEventListener('visibilitychange',()=>{if(!document.hidden)syncOrderOutbox().catch(()=>{});});
async function api(method, path, body) {
  if (method === 'POST' && path === '/orders' && body && typeof body === 'object' && !(body instanceof FormData)) {\n    const reqId=outboxId();\n    await queueOrder(body,reqId);\n    const item=outboxRead().find(x=>x.id===reqId && x.owner===queueOwner());\n    item.state='sending'; item.attempted=true; item.attempted_at=new Date().toISOString();\n    outboxWrite(outboxRead().map(x=>x.id===reqId?item:x));\n    try { const opt={method,headers:{'Content-Type':'application/json','X-Client-Request-ID':reqId}}; if(S.token) opt.headers.Authorization='Bearer '+S.token; opt.body=JSON.stringify(body); const r=await fetch(path,opt); const data=await r.json().catch(()=>null); if(!r.ok){item.state='error';item.http_status=r.status;item.retryable=r.status===408 || r.status===429 || r.status>=500;item.last_error=(data&&data.detail)||('HTTP '+r.status);outboxWrite(outboxRead().map(x=>x.id===reqId?item:x));let d=data&&data.detail;if(Array.isArray(d))d=d.map(x=>x.msg).join('; ');const err=new Error(d||r.statusText);err.http=true;throw err;} item.state='synced';item.order_id=data.id;item.synced_at=new Date().toISOString();item.last_error='';outboxWrite(outboxRead().map(x=>x.id===reqId?item:x));return data; } catch(e) { if(e.http) throw e; item.state='uncertain';item.last_error='Результат отправки неизвестен; безопасный повтор с тем же ID';outboxWrite(outboxRead().map(x=>x.id===reqId?item:x));return {queued:true,client_request_id:reqId}; }\n  }\n  const opt = {method, headers: {}};
  if (S.token) opt.headers.Authorization = 'Bearer ' + S.token;
  if (body instanceof FormData) opt.body = body;
  else if (body !== undefined) { opt.headers['Content-Type'] = 'application/json'; opt.body = JSON.stringify(body); }
  const r = await fetch(path, opt);
  let data = null;
  try { data = await r.json(); } catch (e) { /* пустой ответ */ }
  if (!r.ok) {
    if (r.status === 401 && S.token) logout();
    let d = data && data.detail;
    if (Array.isArray(d)) d = d.map((x) => x.msg).join('; ');
    throw new Error(d || r.statusText);
  }
  return data;
}
const withToken = (p) => `${p}${p.includes('?') ? '&' : '?'}token=${encodeURIComponent(S.token)}`;
const mediaUrl = (id) => withToken(`/media/${id}`);
const docUrl = (id) => withToken(`/documents/${id}`);
const fileUrl = (id) => withToken(`/files/${id}`);
const storageUrl = (key) => withToken(`/storage/files/${encodeURIComponent(key)}/download`);
// guard: оборачивает обработчик — любая ошибка показывается всплывающим сообщением
const guard = (fn) => async (...a) => { try { await fn(...a); } catch (e) { toast(e.message, true); } };
function toast(msg, err) {
  const el = h('div', {class: 'toast' + (err ? ' err' : '')}, msg);
  $('#toasts').append(el);
  setTimeout(() => el.remove(), err ? 6000 : 3000);
}
// Загрузка файлов по одному: ошибка одного файла не мешает остальным.
async function uploadFiles(path, files, extra) {
  const failed = [];
  for (const f of files) {
    try {
      const fd = new FormData();
      fd.append('file', f, f.name || 'photo.jpg');
      if (extra) for (const [k, v] of Object.entries(extra)) fd.append(k, v);
      await api('POST', path, fd);
    } catch (e) { failed.push(`${f.name}: ${e.message}`); }
  }
  if (failed.length) throw new Error(failed.join('; '));
}

// ───────────── Окна ─────────────
function modal(title, body, onClose) {
  const back = h('div', {class: 'modal-back'});
  const close = () => back.remove();
  back.append(h('div', {class: 'modal', role: 'dialog'}, title ? h('h3', {}, title) : null, body));
  back.addEventListener('mousedown', (e) => { if (e.target === back) { close(); onClose && onClose(); } });   // клик по фону = отмена
  $('#modals').append(back);
  return close;
}
// pick('Заголовок', [{label, value}]) → Promise<value | undefined>
function pick(title, options) {
  return new Promise((resolve) => {
    let close;
    const list = h('div', {class: 'pick'}, options.map((o) => h('button', {onclick: () => { close(); resolve(o.value); }}, o.label)),
      h('button', {class: 'ghost', onclick: () => { close(); resolve(undefined); }}, t('cancel')));
    close = modal(title, list, () => resolve(undefined));
  });
}
function confirmBox(message) {
  return new Promise((resolve) => {
    let close;
    close = modal(null, h('div', {}, h('p', {}, message), h('div', {class: 'row'},
      h('button', {class: 'danger', onclick: () => { close(); resolve(true); }}, t('ok')),
      h('button', {class: 'ghost', onclick: () => { close(); resolve(false); }}, t('cancel')))), () => resolve(false));
  });
}
// formModal('Заголовок', [{key,label,type,options,value,hint}]) → Promise<{key: значение} | null>
// type: text | password | number | date | textarea | select (options:[{value,label}]) | checkbox | color
function formModal(title, fields, okText) {
  return new Promise((resolve) => {
    let close;
    const inputs = {};
    const rows = fields.map((f) => {
      const lbl = f.raw ? f.label : t(f.label);
      let el;
      if (f.type === 'textarea') el = h('textarea', {value: f.value || ''});
      else if (f.type === 'select') el = h('select', {value: f.value != null ? String(f.value) : ''}, f.options.map((o) => h('option', {value: String(o.value)}, o.label)));
      else if (f.type === 'checkbox') el = h('input', {type: 'checkbox', checked: !!f.value});
      else el = h('input', {type: f.type || 'text', value: f.value != null ? f.value : '', autocomplete: 'off', step: f.type === 'number' ? 'any' : null});
      inputs[f.key] = el;
      return h('div', {class: f.type === 'checkbox' ? 'row' : ''}, f.type === 'checkbox' ? [el, h('label', {style: 'margin:0'}, lbl)] : [h('label', {}, lbl), el],
        f.hint ? h('div', {class: 'muted small'}, f.hint) : null);
    });
    const collect = () => { const v = {}; for (const f of fields) v[f.key] = f.type === 'checkbox' ? inputs[f.key].checked : inputs[f.key].value; return v; };
    const form = h('div', {}, rows, h('div', {class: 'row', style: 'margin-top:14px'},
      h('button', {onclick: () => { const v = collect(); close(); resolve(v); }}, okText || t('ok')),
      h('button', {class: 'ghost', onclick: () => { close(); resolve(null); }}, t('cancel'))));
    close = modal(title, form, () => resolve(null));
    const first = Object.values(inputs)[0];
    if (first && first.type !== 'checkbox' && first.type !== 'color') first.focus();
  });
}
// Таблица из заголовков и строк (ячейка может быть строкой, числом или элементом). onSort(i) делает заголовок кликабельным.
function table(headers, rows, opts = {}) {
  const head = h('tr', {}, headers.map((x, i) => h('th', {class: opts.sortable && opts.sortable.includes(i) ? 'sortable' : '',
    onclick: opts.sortable && opts.sortable.includes(i) ? () => opts.onSort(i) : null}, x, opts.sortCol === i ? (opts.sortDir === 'asc' ? ' ▲' : ' ▼') : '')));
  const body = rows.map((r) => h('tr', {class: opts.rowClass ? opts.rowClass(r) : ''}, r.map((c, i) => h('td', {class: opts.numCols && opts.numCols.includes(i) ? 'num' : ''}, c))));
  return h('div', {class: 'tablewrap'}, h('table', {}, h('thead', {}, head), h('tbody', {}, body.length ? body : h('tr', {}, h('td', {colspan: headers.length, class: 'muted'}, t('no_data'))))));
}
const kvList = (pairs) => h('dl', {class: 'kv'}, pairs.filter(Boolean).map(([k, v]) => [h('dt', {}, k), h('dd', {}, v)]));
const sectionTitle = (text) => h('h2', {}, text);
const back = (hash, label) => h('button', {class: 'ghost', onclick: () => { location.hash = hash; }}, '← ' + (label || ''));
const pageHead = (title, ...actions) => h('div', {class: 'row'}, h('h1', {class: 'grow'}, title), ...actions);
const badge = (s) => h('span', {class: 'badge st-' + s}, t('st_' + s));
const roleBadge = (r) => h('span', {class: 'badge'}, t(ROLE_KEYS[r]));
const fieldBox = (labelKey, input) => h('div', {}, h('label', {}, t(labelKey)), input);
const selectEl = (options, value, props) => h('select', Object.assign({value: value != null ? String(value) : ''}, props || {}), options.map((o) => h('option', {value: String(o.value)}, o.label)));

// ───────────── Маршрутизатор и меню ─────────────
const ROUTES = {};
// route('имя', функция(arg), [роли, которым доступно])  — пустой список ролей = любому вошедшему
function route(name, fn, roles) { ROUTES[name] = {fn, roles: roles || null}; }
// Меню: [маршрут, ключ перевода, роли]. Чтобы добавить раздел — допишите строку и вызовите route(...).
const NAV = [
  ['orders', 'orders', [1, 2, 3, 4, 5, 6, 7]],
  ['new', 'new_order', [1, 2, 4, 5, 7]],
  ['map', 'map', [1, 2, 3, 7]],
  ['chat', 'chat', [1, 2, 3, 6, 7]],
  ['warehouse', 'warehouse', [1, 2, 3, 6, 7]],
  ['users', 'users', [1, 2, 4, 7]],
  ['analytics', 'analytics', [2, 6]],
  ['myfinance', 'my_finance', [4]],
  ['mypay', 'my_pay', [2, 3]],
  ['admin', 'admin', [1, 7]],
  ['settings', 'settings', [1, 2, 3, 4, 5, 6, 7]],
];
function logout() {
  if (window.Tracker) Tracker.stop(false);
  S.token = null; S.me = null;
  ls.set('hm_token', null);
  location.hash = '#/login';
  render();
}
function drawNav(name) {
  const role = S.me && S.me.role;
  const admin = ['admin', 'finance', 'payroll', 'contractors', 'appsettings', 'reports', 'files', 'staffmap', 'analytics', 'appearance', 'departments', 'audit', 'orderfin'];
  $('#nav').replaceChildren(...(role ? NAV.filter((n) => n[2].includes(role)).map((n) => {
    const on = name === n[0] || (name === 'order' && n[0] === 'orders') || (n[0] === 'admin' && admin.includes(name) && name !== 'analytics') || (n[0] === 'map' && name === 'staffmap' && false);
    return h('a', {href: '#/' + n[0], class: on ? 'on' : ''}, t(n[1]));
  }) : []));
  $('#logout').hidden = !role;
}
async function render() {
  (S.cleanup || []).splice(0).forEach((f) => { try { f(); } catch (e) { /* таймеры и подписки предыдущего экрана */ } });
  const [name, arg] = (location.hash || '#/orders').slice(2).split('/');
  const open = ['login', 'register'].includes(name);
  const view = $('#view');
  if (!S.me && !open) { location.hash = '#/login'; return; }
  if (S.me && open) { location.hash = '#/orders'; return; }
  const r = ROUTES[name];
  if (!r || (r.roles && S.me && !r.roles.includes(S.me.role))) { location.hash = S.me ? '#/orders' : '#/login'; return; }
  drawNav(name);
  view.replaceChildren(h('p', {class: 'muted'}, t('loading')));
  try {
    const el = await r.fn(arg);
    if ((location.hash || '#/orders').slice(2).split('/')[0] === name) { view.replaceChildren(el); window.scrollTo(0, 0); }   // не затираем, если маршрут уже сменился
  } catch (e) {
    view.replaceChildren(h('div', {class: 'card'}, h('b', {}, t('error')), h('p', {}, e.message)));
  }
}
// Подписка, которую надо снять при уходе с экрана (таймеры опроса, карты, GPS)
const onLeave = (fn) => S.cleanup.push(fn);
function every(ms, fn) { const id = setInterval(() => fn().catch(() => {}), ms); onLeave(() => clearInterval(id)); }
