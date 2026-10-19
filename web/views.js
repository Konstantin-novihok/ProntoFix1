/*
 * Основные экраны: вход, регистрация (в т.ч. подрядчика по приглашению), заказы, карточка заказа (финансы, файлы, склад),
 * новый заказ, пользователи, настройки, «моя предоплата» (заказчик), «моя оплата» (сотрудник).
 */
'use strict';

function applyBrand() {
  const n = S.pub.app_name || 'Home Master';
  document.title = n;
  const b = $('#brand'); if (b) b.textContent = '🛠 ' + n;
}
async function afterAuth(data) {
  S.token = data.token; S.me = data.user;
  ls.set('hm_token', data.token);
  initSkin();
  if (isAdmin() || roleIn(2, 3) || true) resumeTracking();
  location.hash = '#/orders';
  render();
}
function resumeTracking() {
  if (S.me && [1, 2, 3, 7].includes(S.me.role) && ls.get('hm_tracking') === '1' && !Tracker.active()) Tracker.start();
}

// ───────────── Вход ─────────────
route('login', () => {
  const u = h('input', {autocomplete: 'username'}), p = h('input', {type: 'password', autocomplete: 'current-password'});
  const go = guard(async () => afterAuth(await api('POST', '/auth/login', {username: u.value, password: p.value})));
  p.addEventListener('keydown', (e) => { if (e.key === 'Enter') go(); });
  const server = BRIDGE() && BRIDGE().changeServer ? h('button', {class: 'ghost', onclick: () => BRIDGE().changeServer()}, t('server_change')) : null;
  return h('div', {class: 'card center'}, h('h1', {}, S.pub.app_name || t('app_title')),
    h('label', {}, t('username')), u, h('label', {}, t('password')), p,
    h('div', {class: 'row', style: 'margin-top:14px'}, h('button', {onclick: go}, t('login')),
      h('button', {class: 'ghost', onclick: () => { location.hash = '#/register'; }}, t('register')), server));
});

// ───────────── Регистрация ─────────────
route('register', (invite) => {
  if (!S.reg) S.reg = {files: [], lat: null, lon: null};
  const R = S.reg, f = {};
  const field = (key, label, type, val) => { f[key] = h('input', {type: type || 'text', autocomplete: 'off', value: val || ''}); return h('div', {}, h('label', {}, t(label)), f[key]); };
  const locInfo = h('div', {class: 'muted', style: 'margin:8px 0'});
  const showLoc = () => { locInfo.textContent = R.lat != null ? `${t('location_set')}: ${R.lat.toFixed(5)}, ${R.lon.toFixed(5)}` : t('location_none'); };
  showLoc();
  const files = fileList(R.files);
  const addFiles = (list) => { for (const x of list) { if (isDoc(x)) R.files.push(x); else toast(t('bad_file_type'), true); } files.redraw(); };
  const consent = h('input', {type: 'checkbox', id: 'consent'});
  const submit = guard(async () => {
    if (f.user.value.trim().length < 3 || f.pwd.value.length < 6 || f.fname.value.trim().split(/\s+/).length < 2) throw new Error(t('fill_required'));
    if (!consent.checked) throw new Error(t('consent_required'));
    const data = await api('POST', '/auth/register', {
      username: f.user.value.trim(), password: f.pwd.value, full_name: f.fname.value.trim(), phone: f.phone.value.trim(),
      company_name: f.company.value.trim(), website: f.website.value.trim(), address: f.address.value.trim(), tax_id: f.tax.value.trim(),
      lat: R.lat, lon: R.lon, passport_number: f.pnum.value.trim(), passport_issued: f.pissued.value.trim(), consent: true, invite_code: f.invite.value.trim()});
    S.token = data.token;                       // сразу используем токен, чтобы загрузить сканы
    try { await uploadFiles('/me/documents', R.files); } catch (e) { toast(e.message, true); }
    S.reg = null;
    await afterAuth(data);
    if (data.user.verification === 'pending') toast(t('pending_verification'));
  });
  return h('div', {class: 'card'}, h('h1', {}, t('register')),
    h('h2', {}, t('section_account')), field('user', 'username'), field('pwd', 'password', 'password'), field('invite', 'invite_code', 'text', invite || ''),
    h('p', {class: 'muted small'}, t('invite_hint')),
    h('h2', {}, t('section_person')), field('fname', 'full_name'), field('phone', 'phone', 'tel'),
    h('h2', {}, t('section_company')), field('company', 'company_name'), field('website', 'website', 'url'), field('address', 'address'), field('tax', 'tax_id'),
    h('div', {class: 'row', style: 'margin-top:10px'},
      h('button', {class: 'ghost', onclick: guard(async () => { const p = await gpsLocate(); R.lat = p.lat; R.lon = p.lon; showLoc(); })}, t('use_gps')),
      h('button', {class: 'ghost', onclick: guard(async () => { const p = await mapPicker(R.lat || 50.4501, R.lon || 30.5234); if (p) { R.lat = p.lat; R.lon = p.lon; showLoc(); } })}, t('set_location'))),
    locInfo,
    h('h2', {}, t('section_passport')), field('pnum', 'passport_number'), field('pissued', 'passport_issued'),
    h('h2', {}, t('section_documents')),
    h('div', {class: 'row'},
      h('button', {class: 'ghost', onclick: guard(async () => { const x = await cameraCapture(); if (x) addFiles([x]); })}, t('take_photo')),
      h('button', {class: 'ghost', onclick: guard(async () => addFiles(await chooseFiles(DOC_ACCEPT)))}, t('choose_document'))),
    files.el, h('p', {class: 'muted small'}, t('privacy_note')),
    h('div', {class: 'row'}, consent, h('label', {for: 'consent', style: 'margin:0'}, t('consent'))),
    h('div', {class: 'row', style: 'margin-top:14px'}, h('button', {onclick: submit}, t('register')),
      h('button', {class: 'ghost', onclick: () => { location.hash = '#/login'; }}, t('back'))));
});

// ───────────── Список заказов ─────────────
route('orders', async () => {
  const orders = await api('GET', '/orders');
  const filter = h('select', {onchange: () => draw()}, h('option', {value: ''}, `${t('status')}: *`), STATUSES.map((s) => h('option', {value: s}, t('st_' + s))));
  const q = h('input', {placeholder: t('search'), oninput: () => draw(), style: 'max-width:220px'});
  const list = h('div', {});
  const draw = () => {
    const needle = q.value.trim().toLowerCase();
    const rows = orders.filter((o) => (!filter.value || o.status === filter.value) && (!needle || `${o.id} ${o.title} ${o.address} ${o.client_company || ''} ${o.executor_name || ''}`.toLowerCase().includes(needle)));
    list.replaceChildren(...(rows.length ? rows.map((o) => h('div', {class: 'card click', onclick: () => { location.hash = '#/order/' + o.id; }},
      h('div', {class: 'row'}, h('b', {class: 'grow'}, `#${o.id} ${o.title}`), badge(o.status)),
      h('div', {class: 'muted small'}, [o.service_type, o.address, o.client_company && S.me.role !== 4 ? o.client_company : null,
        `${t('executor')}: ${o.executor_name || '-'}${o.executor_company ? ' (' + o.executor_company + ')' : ''}`, fmtDate(o.created_at)].filter(Boolean).join(' · ')))) : [h('p', {class: 'muted'}, t('no_data'))]));
  };
  draw();
  const pending = S.me.verification === 'pending' ? h('div', {class: 'card warn'}, t('pending_verification')) : null;
  return h('div', {}, pending, h('div', {class: 'row'}, h('h1', {class: 'grow'}, t('orders')), q, filter, h('button', {class: 'ghost', onclick: () => render()}, t('refresh'))), list);
});

// ───────────── Файлы заказа: показ ─────────────
function mediaItem(m, canDelete) {
  const url = mediaUrl(m.id);
  if (m.mime.startsWith('image/')) return h('div', {class: 'fcard'}, h('a', {href: url, target: '_blank', rel: 'noopener'}, h('img', {src: url, alt: m.original})), fileFoot(m, url));
  if (m.mime.startsWith('video/')) return h('div', {class: 'fcard'}, h('video', {src: url, controls: true, preload: 'metadata'}), fileFoot(m, url));
  return h('div', {class: 'fcard'}, h('div', {class: 'ficon'}, fileIcon(m.original, m.mime)), fileFoot(m, url));
}
function fileFoot(m, url) {
  return h('div', {class: 'ffoot'}, h('div', {class: 'fname'}, m.original), h('div', {class: 'muted small'}, [m.size != null ? fmtBytes(m.size) : null, m.uploader].filter(Boolean).join(' · ')),
    h('div', {class: 'row'}, h('a', {href: url, target: '_blank', rel: 'noopener'}, t('open')),
      h('button', {class: 'ghost small', onclick: guard(() => saveUrl(url, m.original, m.mime))}, t('save_as'))));
}

// ───────────── Карточка заказа ─────────────
route('order', async (id) => {
  const d = await api('GET', '/orders/' + id), o = d.order, role = S.me.role;
  const reload = () => render();
  const post = guard(async (action, body) => { await api('POST', `/orders/${id}/${action}`, body || {}); reload(); });
  const actions = h('div', {class: 'actions'});
  const act = (key, fn, cls) => actions.append(h('button', {class: cls || 'ghost', onclick: guard(fn)}, t(key)));
  const mapBox = h('div', {});
  if (o.lat != null) {
    act('show_map', async () => {
      mapBox.replaceChildren(h('div', {class: 'mapbox'}));
      await drawMap($('.mapbox', mapBox), o.lat, o.lon, true);
      mapBox.append(h('a', {href: mapLink(o.lat, o.lon), target: '_blank', rel: 'noopener'}, t('open_external')));
    });
    if ([3, 1, 7, 2].includes(role)) actions.append(h('a', {class: 'btnlink', href: mapLink(o.lat, o.lon), target: '_blank', rel: 'noopener'}, '🧭 ' + t('navigate')));
  }
  if (role === 3 && ['new', 'assigned'].includes(o.status) && [null, S.me.id].includes(o.executor_id)) act('accept', () => post('accept'), 'go');
  if ([1, 2, 7].includes(role) || (role === 3 && o.executor_id === S.me.id)) act('change_status', async () => {
    const s = await pick(t('change_status'), STATUSES.map((x) => ({label: t('st_' + x), value: x}))); if (s) await post('status', {status: s}); });
  if ([1, 2, 3, 7].includes(role)) act('estimate', async () => {
    const v = await formModal(t('estimate'), [{key: 'hours', label: 'hours', type: 'number'}, {key: 'price', label: 'price', type: 'number'}, {key: 'text', label: 'estimate_text'}]);
    if (!v) return;
    const hours = parseFloat(v.hours.replace(',', '.')), price = parseFloat(v.price.replace(',', '.'));
    if (isNaN(hours) || isNaN(price)) throw new Error('number?');
    await post('estimate', {hours, price, text: v.text}); });
  if ([1, 2, 7].includes(role)) act('assign_executor', async () => {
    const users = (await api('GET', '/users?role=3')).filter((u) => u.is_active && u.verification === 'verified' && (isAdmin() || u.department_id === o.department_id));
    if (!users.length) throw new Error(t('no_executors'));
    const uid = await pick(t('assign_executor'), users.map((u) => ({label: personName(u) + (u.company_name ? ' · ' + u.company_name : ''), value: u.id}))); if (uid) await post('assign', {executor_id: uid}); });
  if (isAdmin()) act('assign_dept', async () => {
    const ds = await api('GET', '/departments');
    const did = await pick(t('assign_dept'), ds.map((x) => ({label: x.name, value: x.id}))); if (did) await post('assign', {department_id: did}); });
  if (role === 4 && o.status === 'done') act('rate', async () => {
    const r = await pick(t('rate'), [5, 4, 3, 2, 1].map((n) => ({label: '★'.repeat(n), value: n}))); if (r) await post('rate', {rating: r}); });
  if (role === 4 && !['done', 'cancelled'].includes(o.status)) act('cancel', () => post('status', {status: 'cancelled'}), 'danger');
  const say = (pub) => async () => { const v = await formModal(t('message'), [{key: 'text', label: 'text', type: 'textarea'}]); if (v && v.text.trim()) await post('comments', {text: v.text, public: pub}); };
  if (role !== 6) {
    if ([1, 2, 3, 7].includes(role)) { act('message_client', say(true), 'go'); act('comment_internal', say(false)); } else act('message', say(true), 'go');
    act('attach_file', async () => { const fl = await chooseFiles(''); if (fl.length) { await uploadFiles(`/orders/${id}/media`, fl); toast(t('saved')); reload(); } });
    act('take_photo', async () => { const x = await cameraCapture().catch((e) => { toast(e.message, true); return null; }); if (x) { await uploadFiles(`/orders/${id}/media`, [x]); toast(t('saved')); reload(); } });
  }
  if (![4, 5].includes(role)) act('order_history', async () => {
    const rows = await api('GET', `/orders/${id}/history`);
    modal(t('order_history'), h('div', {}, rows.length ? rows.map((r) => h('div', {class: 'small', style: 'margin:6px 0'}, `${fmtDate(r.created_at)} — ${r.actor}: ${r.action} ${r.details}`)) : t('no_data'),
      h('div', {style: 'margin-top:10px'}, h('button', {onclick: (e) => e.target.closest('.modal-back').remove()}, t('close'))))); });

  const info = [[t('status'), badge(o.status)], [t('service_type'), o.service_type || '-'], [t('description'), o.description || '-'], [t('address'), o.address || '-'],
    [t('department'), o.department_name || '-'],
    [t('client'), `${o.client_name || '-'}${o.client_company ? ' · ' + o.client_company : ''}`], [t('created_by'), o.created_by_name || '-'],
    [t('executor'), o.executor_name ? h('span', {}, o.executor_name, o.executor_company ? ' · ' + o.executor_company + ' ' : ' ',
      h('span', {class: 'badge'}, o.executor_employment === 'external' ? t('emp_external') : t('emp_internal'))) : '-']];
  if (o.estimate_hours != null) info.push([t('estimate'), `${o.estimate_hours} ${t('hours')} / ${o.estimate_price}`]);
  if (o.arrived_at) info.push([t('arrived'), fmtDate(o.arrived_at) + (o.geo_verified ? ' · ' + t('geo_verified') : '')]);
  if (o.distance_km) info.push([t('km'), num(o.distance_km)]);
  if (o.rating) info.push([t('rating'), '★'.repeat(o.rating)]);
  const media = d.media.map((m) => mediaItem(m));
  const fin = [1, 2, 3, 4, 7, 6].includes(role) ? await financePanel(o) : null;
  return h('div', {}, h('div', {class: 'row'}, back('#/orders'), h('h1', {class: 'grow'}, `#${o.id} ${o.title}`)),
    h('div', {class: 'card'}, kvList(info)), actions, mapBox, fin,
    h('h2', {}, t('comments')), d.comments.length ? d.comments.map((c) => h('div', {class: 'comment' + (c.public ? '' : ' internal')},
      h('b', {}, c.author), ' ', h('span', {class: 'muted small'}, fmtDate(c.created_at) + (c.public ? '' : ` (${t('internal')})`)), h('div', {}, c.text))) : h('p', {class: 'muted'}, t('no_data')),
    h('h2', {}, t('media')), media.length ? h('div', {class: 'gallery'}, media) : h('p', {class: 'muted'}, t('no_data')));
});

// ───────────── Финансы заказа (цена, расходы, себестоимость, расчёт) ─────────────
async function financePanel(o) {
  const role = S.me.role, id = o.id;
  let f;
  try { f = await api('GET', `/orders/${id}/finance`); } catch (e) { return null; }
  const reload = () => render();
  const manage = [1, 2, 7].includes(role);
  const mine = role === 3 && o.executor_id === S.me.id;
  const box = h('div', {class: 'card'}, h('h2', {style: 'margin-top:0'}, t('finance')));
  if (role === 4) {
    box.append(kvList([[t('price'), f.price ? money(f.price) : '-'], [t('status'), f.settled ? t('settled') : t('not_settled')]]));
    return box;
  }
  const pairs = [];
  if (f.price !== undefined) pairs.push([t('price'), money(f.price)]);
  if (f.materials !== undefined) pairs.push([t('materials'), money(f.materials)], [t('transport'), money(f.transport)], [t('other'), money(f.other)]);
  pairs.push([t('pay'), money(f.pay)]);
  if (f.cost_price !== undefined) pairs.push([t('cost_price'), h('b', {}, money(f.cost_price))], [t('margin'), h('b', {style: `color:var(--${f.margin >= 0 ? 'ok' : 'bad'})`}, `${money(f.margin)} (${num(f.margin_pct, 1)}%)`)]);
  pairs.push([t('hours'), num(f.labor_hours)], [t('km'), num(f.km)]);
  if (f.client_balance !== undefined) pairs.push([t('prepay_balance'), money(f.client_balance)]);
  pairs.push([t('status'), f.settled ? '✔ ' + t('settled') : t('not_settled')]);
  box.append(kvList(pairs));
  if (f.expenses && f.expenses.length) box.append(table([t('kind'), t('description'), t('qty'), t('price'), t('amount'), ''],
    f.expenses.map((e) => [t('exp_' + e.kind), e.description, num(e.qty), num(e.unit_cost), money(e.amount),
      manage && !f.settled && !e.auto ? h('button', {class: 'ghost small', onclick: guard(async () => { await api('DELETE', `/orders/${id}/expenses/${e.id}`); reload(); })}, '✕') : (e.auto ? '⚙' : '')]), {numCols: [2, 3, 4]}));
  const acts = h('div', {class: 'actions'});
  if ((manage || mine) && !f.settled) {
    acts.append(h('button', {class: 'ghost', onclick: guard(async () => {
      const v = await formModal(t('finance'), [...(manage ? [{key: 'price', label: 'price', type: 'number', value: f.price || ''}] : []),
        {key: 'hours', label: 'hours', type: 'number', value: f.labor_hours || ''},
        {key: 'service', label: 'service_type', type: 'select', value: o.service_type || '', options: [{value: '', label: '—'}, ...(S.pub.service_types || []).map((x) => ({value: x, label: x}))]}]);
      if (!v) return;
      const body = {labor_hours: v.hours === '' ? null : parseFloat(v.hours), service_type: v.service};
      if (manage && v.price !== '') body.price = parseFloat(v.price);
      await api('POST', `/orders/${id}/finance`, body); reload(); })}, t('edit')));
    acts.append(h('button', {class: 'ghost', onclick: guard(async () => {
      const v = await formModal(t('add_expense'), [{key: 'kind', label: 'kind', type: 'select', options: [{value: 'material', label: t('exp_material')}, {value: 'transport', label: t('exp_transport')}, {value: 'other', label: t('exp_other')}]},
        {key: 'description', label: 'description'}, {key: 'qty', label: 'qty', type: 'number', value: 1}, {key: 'unit_cost', label: 'price', type: 'number'}]);
      if (!v) return;
      await api('POST', `/orders/${id}/expenses`, {kind: v.kind, description: v.description, qty: parseFloat(v.qty) || 1, unit_cost: parseFloat(v.unit_cost) || 0}); reload(); })}, '+ ' + t('add_expense')));
    if (mine || manage) acts.append(h('button', {class: 'ghost', onclick: guard(async () => {
      const mineItems = (await api('GET', '/warehouse/mine')).filter((x) => x.kind === 'material');
      if (!mineItems.length) throw new Error(t('no_materials_on_hand'));
      const it = await pick(t('consume_material'), mineItems.map((x) => ({label: `${x.name} — ${num(x.qty)} ${x.unit}`, value: x})));
      if (!it) return;
      const v = await formModal(it.name, [{key: 'qty', label: 'qty', type: 'number', value: 1}]);
      if (!v) return;
      await api('POST', '/warehouse/moves', {item_id: it.item_id, kind: 'consume', qty: parseFloat(v.qty), order_id: id}); toast(t('saved')); reload(); })}, '📦 ' + t('consume_material')));
  }
  if (manage && !f.settled && o.status === 'done') acts.append(h('button', {class: 'ok', onclick: guard(async () => {
    if (!f.price) throw new Error(t('set_price_first'));
    if (await confirmBox(t('settle_confirm'))) { const r = await api('POST', `/orders/${id}/settle`); toast(`${t('settled')}. ${t('prepay_balance')}: ${r.client_balance != null ? money(r.client_balance) : '-'}`); reload(); } })}, '✔ ' + t('settle')));
  if (acts.children.length) box.append(acts);
  return box;
}

// ───────────── Новый заказ ─────────────
route('new', async () => {
  const D = S.draft || (S.draft = {files: [], lat: null, lon: null});
  const [deps, clients] = await Promise.all([api('GET', '/departments'), [1, 2, 7].includes(S.me.role) ? api('GET', '/users?role=4') : []]);
  const title = h('input', {}), descr = h('textarea', {}), address = h('input', {});
  const svc = selectEl([{value: '', label: '—'}, ...(S.pub.service_types || []).map((x) => ({value: x, label: x}))], '');
  const dep = selectEl([{value: '', label: '—'}, ...deps.map((x) => ({value: x.id, label: x.name}))], '');
  const cli = selectEl([{value: '', label: '—'}, ...clients.map((x) => ({value: x.id, label: personName(x) + (x.company_name ? ' · ' + x.company_name : '')}))], '');
  const loc = h('div', {class: 'muted', style: 'margin:8px 0'});
  const showLoc = () => { loc.textContent = D.lat != null ? `${t('location')}: ${D.lat.toFixed(5)}, ${D.lon.toFixed(5)}` : t('location_none'); };
  showLoc();
  const files = fileList(D.files);
  const submit = guard(async () => {
    if (!title.value.trim()) throw new Error(t('title'));
    const o = await api('POST', '/orders', {title: title.value, description: descr.value, address: address.value, lat: D.lat, lon: D.lon, service_type: svc.value,
      department_id: dep.value ? +dep.value : null, client_id: cli.value ? +cli.value : null});
    try { await uploadFiles(`/orders/${o.id}/media`, D.files); } catch (e) { toast(e.message, true); }
    S.draft = null;
    toast(t('order_created'));
    location.hash = '#/order/' + o.id;
  });
  return h('div', {class: 'card'}, h('h1', {}, t('new_order')),
    h('label', {}, t('title')), title, h('label', {}, t('service_type')), svc, h('label', {}, t('description')), descr, h('label', {}, t('address')), address,
    h('label', {}, t('department')), dep, [1, 2, 7].includes(S.me.role) ? [h('label', {}, t('client')), cli] : null,
    h('div', {class: 'row', style: 'margin-top:10px'},
      h('button', {class: 'ghost', onclick: guard(async () => { const p = await gpsLocate(); D.lat = p.lat; D.lon = p.lon; showLoc(); })}, t('use_gps')),
      h('button', {class: 'ghost', onclick: guard(async () => { const p = await mapPicker(D.lat || 50.4501, D.lon || 30.5234); if (p) { D.lat = p.lat; D.lon = p.lon; showLoc(); } })}, t('set_location'))),
    loc,
    h('div', {class: 'row'},
      h('button', {class: 'ghost', onclick: guard(async () => { D.files.push(...await chooseFiles('')); files.redraw(); })}, t('attach_file')),
      h('button', {class: 'ghost', onclick: guard(async () => { const x = await cameraCapture(); if (x) { D.files.push(x); files.redraw(); } })}, t('take_photo'))),
    files.el, h('div', {style: 'margin-top:14px'}, h('button', {onclick: submit}, t('submit'))));
}, [1, 2, 4, 5, 7]);

// ───────────── Пользователи ─────────────
const EMP_BADGE = (u) => u.employment === 'external' ? h('span', {class: 'badge', style: 'background:var(--warn);color:#fff'}, t('emp_external')) : null;
const VER_BADGE = (u) => u.employment === 'external' ? h('span', {class: 'badge st-' + (u.verification === 'verified' ? 'done' : u.verification === 'rejected' ? 'cancelled' : 'assigned')}, t('ver_' + u.verification)) : null;
route('users', async () => {
  const users = await api('GET', '/users'), me = S.me;
  const reload = () => render();
  const rolePick = async () => {
    const roles = Object.entries(ROLE_KEYS).filter(([n]) => me.role === 1 || ![1, 7].includes(+n));
    return pick(t('role'), roles.map(([n, k]) => ({label: t(k), value: +n})));
  };
  const manage = guard(async (u) => {
    if (isAdmin()) {
      if (me.role !== 1 && [1, 7].includes(u.role)) return;
      const opts = [{label: t('change_role'), value: 'role'}, {label: t('change_department'), value: 'dep'}, {label: t('work_profile'), value: 'prof'},
        {label: t('toggle_active'), value: 'act'}, {label: t('view_private'), value: 'priv'}, {label: t('bonus_fine'), value: 'adj'}];
      if (u.employment === 'external') opts.splice(3, 0, {label: t('verify'), value: 'ver'});
      const a = await pick(personName(u), opts);
      if (a === 'role') { const r = await rolePick(); if (r) { await api('PATCH', '/users/' + u.id, {role: r}); reload(); } }
      if (a === 'dep') { const ds = await api('GET', '/departments'); const d = await pick(t('department'), [{label: t('none'), value: 0}, ...ds.map((x) => ({label: x.name, value: x.id}))]);
        if (d !== undefined) { await api('PATCH', '/users/' + u.id, {department_id: d || null}); reload(); } }
      if (a === 'act') { await api('PATCH', '/users/' + u.id, {is_active: !u.is_active}); reload(); }
      if (a === 'priv') await showPrivate(u);
      if (a === 'prof') await editProfile(u, reload);
      if (a === 'ver') await verifyDialog(u, reload);
      if (a === 'adj') await adjustDialog(u, reload);
    } else if (me.role === 2 && u.role === 3) {
      const a = await pick(personName(u), [{label: t('change_department'), value: 'dep'}, {label: t('bonus_fine'), value: 'adj'}]);
      if (a === 'dep') { await api('PATCH', '/users/' + u.id, {department_id: u.department_id === me.department_id ? null : me.department_id}); reload(); }
      if (a === 'adj') await adjustDialog(u, reload);
    }
  });
  const add = guard(async () => {
    const full = isAdmin() || me.role === 2;
    const deps = isAdmin() ? await api('GET', '/departments') : [];
    const fields = [{key: 'username', label: 'username'}, {key: 'password', label: 'password', type: 'password'}, {key: 'full_name', label: 'full_name'}, {key: 'phone', label: 'phone'}];
    if (isAdmin()) {
      const roles = Object.entries(ROLE_KEYS).filter(([n]) => me.role === 1 || ![1, 7].includes(+n));
      fields.push({key: 'role', label: 'role', type: 'select', value: 3, options: roles.map(([n, k]) => ({value: n, label: t(k)}))},
        {key: 'employment', label: 'employment', type: 'select', value: 'internal', options: [{value: 'internal', label: t('emp_internal')}, {value: 'external', label: t('emp_external')}]},
        {key: 'company_name', label: 'company_name'}, {key: 'employee_no', label: 'employee_no', hint: t('employee_no_hint')}, {key: 'tax_id', label: 'tax_id'},
        {key: 'rate_type', label: 'rate_type', type: 'select', value: 'hourly', options: ['hourly', 'per_order', 'percent'].map((x) => ({value: x, label: t('rate_' + x)}))},
        {key: 'rate_value', label: 'pay_rate', type: 'number', value: 0},
        {key: 'department_id', label: 'department', type: 'select', value: '', options: [{value: '', label: '—'}, ...deps.map((d) => ({value: d.id, label: d.name}))]});
    } else if (full) fields.push({key: 'employee_no', label: 'employee_no'});
    const v = await formModal(t('add_user'), fields);
    if (!v) return;
    const body = {...v};
    if (body.role) body.role = +body.role;
    if (body.rate_value !== undefined) body.rate_value = parseFloat(body.rate_value) || 0;
    body.department_id = body.department_id ? +body.department_id : null;
    await api('POST', '/users', body); reload();
  });
  const invite = guard(async () => {
    const v = await formModal(t('invite_contractor'), [{key: 'company_name', label: 'company_name'}, {key: 'rate_value', label: 'percent_of_profit', type: 'number', value: 30}, {key: 'days', label: 'invite_days', type: 'number', value: 14}, {key: 'note', label: 'note'}]);
    if (!v) return;
    const inv = await api('POST', '/invites', {company_name: v.company_name, rate_value: parseFloat(v.rate_value) || 0, days: parseInt(v.days) || 14, note: v.note});
    const link = `${location.origin}${location.pathname}#/register/${inv.code}`;
    modal(t('invite_contractor'), h('div', {}, h('p', {}, t('invite_code') + ':'), h('div', {class: 'bigcode'}, inv.code), h('p', {class: 'small muted', style: 'word-break:break-all'}, link),
      h('div', {class: 'row'}, h('button', {onclick: guard(async () => { await navigator.clipboard.writeText(link); toast(t('copied')); })}, t('copy')),
        h('button', {class: 'ghost', onclick: (e) => e.target.closest('.modal-back').remove()}, t('close')))));
  });
  return h('div', {}, pageHead(t('users'), roleIn(1, 2, 7) ? h('button', {class: 'ghost', onclick: invite}, '✉ ' + t('invite_contractor')) : null, h('button', {onclick: add}, '+ ' + t('add_user'))),
    users.length ? users.map((u) => h('div', {class: 'card' + (me.role < 3 || me.role === 7 ? ' click' : ''), onclick: () => manage(u)},
      h('div', {class: 'row'}, h('b', {class: 'grow'}, personName(u), ' ', h('span', {class: 'muted'}, '@' + u.username)), roleBadge(u.role), EMP_BADGE(u), VER_BADGE(u)),
      h('div', {class: 'muted small'}, [u.company_name, u.phone, u.employee_no ? '№ ' + u.employee_no : null, u.is_active ? null : t('inactive')].filter(Boolean).join(' · ')))) : h('p', {class: 'muted'}, t('no_data')));
}, [1, 2, 4, 7]);

async function showPrivate(u) {
  const p = await api('GET', `/users/${u.id}/private`);
  modal(`${t('view_private')}: ${personName(u)}`, h('div', {},
    kvList([[t('passport_number'), p.passport_number || '-'], [t('passport_issued'), p.passport_issued || '-'],
      [t('consent_at'), p.consent_at ? fmtDate(p.consent_at) : '-'], [t('company_name'), p.user.company_name || '-'], [t('website'), p.user.website || '-'],
      [t('address'), p.user.address || '-']]),
    h('h2', {}, t('documents')), p.documents.length ? p.documents.map((d) => h('div', {class: 'row'}, h('a', {href: docUrl(d.id), target: '_blank', rel: 'noopener'}, d.original),
      h('button', {class: 'ghost small', onclick: guard(() => saveUrl(docUrl(d.id), d.original, d.mime))}, t('save_as')))) : h('p', {class: 'muted'}, t('no_data')),
    h('div', {style: 'margin-top:10px'}, h('button', {onclick: (e) => e.target.closest('.modal-back').remove()}, t('close')))));
}
async function editProfile(u, reload) {
  const st = (await api('GET', '/staff')).find((x) => x.id === u.id) || {};
  const v = await formModal(t('work_profile') + ': ' + personName(u), [
    {key: 'full_name', label: 'full_name', value: u.full_name}, {key: 'phone', label: 'phone', value: u.phone},
    {key: 'employment', label: 'employment', type: 'select', value: u.employment || 'internal', options: [{value: 'internal', label: t('emp_internal')}, {value: 'external', label: t('emp_external')}]},
    {key: 'company_name', label: 'company_name', value: u.company_name}, {key: 'employee_no', label: 'employee_no', value: st.employee_no || u.employee_no || ''},
    {key: 'tax_id', label: 'tax_id', value: st.tax_id || ''},
    {key: 'rate_type', label: 'rate_type', type: 'select', value: st.rate_type || 'hourly', options: ['hourly', 'per_order', 'percent'].map((x) => ({value: x, label: t('rate_' + x)}))},
    {key: 'rate_value', label: 'pay_rate', type: 'number', value: st.rate_value || 0}]);
  if (!v) return;
  v.rate_value = parseFloat(v.rate_value) || 0;
  await api('PATCH', `/users/${u.id}/profile`, v); toast(t('saved')); reload();
}
async function verifyDialog(u, reload) {
  const c = (await api('GET', '/contractors')).find((x) => x.id === u.id);
  const docs = c ? c.documents : [];
  const s = await pick(`${personName(u)} — ${t('verify')}`, [{label: '✔ ' + t('ver_verified'), value: 'verified'}, {label: '✖ ' + t('ver_rejected'), value: 'rejected'}, {label: '… ' + t('ver_pending'), value: 'pending'}]);
  if (!s) return;
  await api('PATCH', `/users/${u.id}/verify`, {status: s}); toast(t('saved') + (docs.length ? '' : ' (' + t('no_documents') + ')')); reload();
}
async function adjustDialog(u, reload) {
  const v = await formModal(`${t('bonus_fine')}: ${personName(u)}`, [{key: 'kind', label: 'kind', type: 'select', options: [{value: 'bonus', label: t('bonus')}, {value: 'fine', label: t('fine')}]},
    {key: 'amount', label: 'amount', type: 'number'}, {key: 'reason', label: 'note'}]);
  if (!v) return;
  await api('POST', '/payroll/adjustments', {user_id: u.id, kind: v.kind, amount: parseFloat(v.amount), reason: v.reason}); toast(t('saved')); reload && reload();
}

// ───────────── Моя предоплата (заказчик) ─────────────
route('myfinance', async () => {
  const d = await api('GET', '/me/finance');
  return h('div', {}, h('h1', {}, t('my_finance')), h('div', {class: 'card bigbalance'}, h('div', {class: 'muted'}, t('prepay_balance')), h('div', {class: 'bignum', style: `color:var(--${d.balance >= 0 ? 'ok' : 'bad'})`}, money(d.balance))),
    h('h2', {}, t('ledger')), table([t('date'), t('kind'), t('amount'), t('order'), t('note')], d.items.map((x) => [fmtDate(x.created_at), t('tx_' + x.kind), h('b', {style: `color:var(--${x.amount >= 0 ? 'ok' : 'bad'})`}, money(x.amount)), x.order_id ? '#' + x.order_id : '', x.note]), {numCols: [2]}));
}, [4]);

// ───────────── Моя оплата (сотрудник) ─────────────
route('mypay', async () => {
  const from = h('input', {type: 'date', value: daysAgo(30)}), to = h('input', {type: 'date', value: today()});
  const out = h('div', {});
  const load = guard(async () => {
    const d = await api('GET', `/me/payroll?frm=${from.value}&to=${to.value}`);
    const s = d.summary;
    out.replaceChildren(s ? kvList([[t('orders_count'), s.orders], [t('earned'), money(s.earned)], [t('bonus'), money(s.bonus)], [t('fine'), money(s.fine)], [t('total'), h('b', {}, money(s.total))],
      [t('rate_type'), `${t('rate_' + s.rate_type)} ${num(s.rate_value)}`]]) : h('p', {class: 'muted'}, t('no_data')),
      h('h2', {}, t('bonus_fine')), table([t('date'), t('kind'), t('amount'), t('note')], d.adjustments.map((a) => [fmtDate(a.created_at), t(a.kind), money(a.amount), a.reason]), {numCols: [2]}));
  });
  from.onchange = load; to.onchange = load; load();
  return h('div', {}, h('h1', {}, t('my_pay')), h('div', {class: 'row'}, h('div', {}, h('label', {}, t('from')), from), h('div', {}, h('label', {}, t('to')), to)), h('div', {class: 'card'}, out));
}, [2, 3]);

// ───────────── Настройки (у каждого) ─────────────
route('settings', () => {
  const m = S.me;
  const provLabel = () => ls.get('hm_map') ? t('mp_' + ls.get('hm_map')) : t('mp_server');
  const prov = h('button', {class: 'ghost'}, `${t('map_provider')}: ${provLabel()}`);
  prov.onclick = guard(async () => {
    const v = await pick(t('map_provider'), [{label: t('mp_server'), value: ''}, {label: t('mp_google'), value: 'google'}, {label: t('mp_osm'), value: 'osm'}, {label: t('mp_custom'), value: 'custom'}]);
    if (v !== undefined) { ls.set('hm_map', v || null); prov.textContent = `${t('map_provider')}: ${provLabel()}`; } });
  const up = (files) => guard(async () => { await uploadFiles('/me/documents', files); toast(t('uploaded')); });
  const track = [1, 2, 3, 7].includes(m.role) ? h('div', {class: 'card'}, h('b', {}, t('tracking')), h('p', {class: 'muted small'}, t('tracking_hint')),
    h('label', {class: 'row', style: 'margin:0'}, (() => { const c = h('input', {type: 'checkbox', checked: Tracker.active(), onchange: guard(async () => {
      if (c.checked) { if (!Tracker.start()) c.checked = false; } else Tracker.stop(); })}); return c; })(), t('tracking_on'))) : null;
  return h('div', {}, h('h1', {}, t('settings')),
    h('div', {class: 'card'}, h('b', {}, t('profile')), h('div', {}, personName(m), ' — ', t(ROLE_KEYS[m.role])),
      h('div', {class: 'muted small'}, [m.company_name, m.website, m.address].filter(Boolean).join(' · '))),
    h('div', {class: 'card'}, h('b', {}, t('language')), selectEl(S.langs.map((l) => ({value: l.code, label: l.name})), S.lang, {onchange: (e) => setLang(e.target.value)})),
    h('div', {class: 'card'}, h('a', {class: 'btnlink', href: '#/skins'}, '🎨 ' + t('skins'))),
    track, h('div', {class: 'card'}, prov),
    h('div', {class: 'card'}, h('b', {}, t('section_documents')), h('div', {class: 'actions'},
      h('button', {class: 'ghost', onclick: guard(async () => { const x = await cameraCapture(); if (x) await up([x])(); })}, t('take_photo')),
      h('button', {class: 'ghost', onclick: guard(async () => { const fl = (await chooseFiles(DOC_ACCEPT)).filter(isDoc); if (fl.length) await up(fl)(); })}, t('choose_document')))),
    BRIDGE() && BRIDGE().changeServer ? h('div', {class: 'card'}, h('button', {class: 'ghost', onclick: () => BRIDGE().changeServer()}, t('server_change'))) : null,
    h('div', {class: 'card'}, h('button', {class: 'danger', onclick: logout}, t('logout'))));
});
