/*
 * Склад: материалы и оборудование, остатки на складе и «на руках» у сотрудников, движение, фото/видео и описание позиций.
 * Видно исполнителям и администраторам. У каждой позиции видно, у кого она, где он сейчас и как с ним связаться.
 */
'use strict';

const MOVE_KINDS = ['receipt', 'take', 'transfer', 'return', 'consume', 'writeoff'];
const isManager = () => roleIn(1, 2, 7);

function holderMap(h0) {   // окно с картой: где сейчас сотрудник с деталью
  const box = h('div', {class: 'mapbox'});
  const body = h('div', {}, h('b', {}, personName(h0)), h('div', {class: 'muted small'}, `${t('last_seen')}: ${h0.last_seen ? fmtDate(h0.last_seen) : '-'}`), box,
    h('div', {class: 'row', style: 'margin-top:10px'}, h0.phone ? h('a', {class: 'btnlink', href: 'tel:' + h0.phone}, '📞 ' + h0.phone) : null,
      h('button', {onclick: (e) => e.target.closest('.modal-back').remove()}, t('close'))));
  modal(t('where_is_it'), body);
  setTimeout(() => drawMap(box, h0.lat, h0.lon, true).catch(() => box.replaceChildren(h('p', {class: 'muted', style: 'padding:12px'}, `${h0.lat}, ${h0.lon}`))), 60);
}

async function moveDialog(item, kind, reload) {
  const staff = (await api('GET', '/staff')).filter((s) => s.is_active);
  const fields = [{key: 'qty', label: 'qty', type: 'number', value: 1}];
  const staffOpts = (excludeMe) => staff.filter((s) => !(excludeMe && s.id === S.me.id)).map((s) => ({value: s.id, label: personName(s) + (s.company_name ? ' · ' + s.company_name : '')}));
  if (kind === 'take' && isManager()) fields.push({key: 'to_user_id', label: 'to_employee', type: 'select', value: S.me.id, options: staffOpts(false)});
  if (kind === 'transfer') {
    if (isManager()) fields.push({key: 'from_user_id', label: 'from_employee', type: 'select', value: S.me.id, options: staffOpts(false)});
    fields.push({key: 'to_user_id', label: 'to_employee', type: 'select', value: '', options: [{value: '', label: '—'}, ...staffOpts(true)]});
  }
  if ((kind === 'return' || kind === 'writeoff') && isManager()) fields.push({key: 'from_user_id', label: 'from_employee', type: 'select', value: kind === 'writeoff' ? '' : S.me.id, options: [{value: '', label: kind === 'writeoff' ? t('warehouse') : '—'}, ...staffOpts(false)]});
  if (kind === 'consume') {
    const orders = (await api('GET', '/orders')).filter((o) => !['done', 'cancelled'].includes(o.status) || !o.settled);
    fields.push({key: 'order_id', label: 'order', type: 'select', value: '', options: [{value: '', label: '—'}, ...orders.slice(0, 100).map((o) => ({value: o.id, label: `#${o.id} ${o.title}`}))]});
  }
  if (kind === 'receipt') fields.push({key: 'unit_cost', label: 'purchase_price', type: 'number', value: item.unit_cost});
  fields.push({key: 'note', label: 'note'});
  const v = await formModal(`${t('mv_' + kind)}: ${item.name}`, fields);
  if (!v) return;
  const body = {item_id: item.id, kind, qty: parseFloat(v.qty), note: v.note || ''};
  for (const k of ['to_user_id', 'from_user_id', 'order_id']) if (v[k]) body[k] = +v[k];
  if (v.unit_cost !== undefined && v.unit_cost !== '') body.unit_cost = parseFloat(v.unit_cost);
  if (kind === 'consume' && !body.order_id) throw new Error(t('order'));
  await api('POST', '/warehouse/moves', body);
  toast(t('saved')); reload();
}
async function itemForm(item) {
  const v = await formModal(item ? t('edit') : t('add_item'), [{key: 'name', label: 'name', value: item && item.name}, {key: 'sku', label: 'sku', value: item && item.sku},
    {key: 'kind', label: 'kind', type: 'select', value: item ? item.kind : 'material', options: [{value: 'material', label: t('wh_material')}, {value: 'equipment', label: t('wh_equipment')}]},
    {key: 'unit', label: 'unit', value: item ? item.unit : 'pcs'}, {key: 'unit_cost', label: 'price', type: 'number', value: item ? item.unit_cost : 0},
    {key: 'min_qty', label: 'min_qty', type: 'number', value: item ? item.min_qty : 0}, {key: 'description', label: 'description', type: 'textarea', value: item && item.description}]);
  if (!v) return null;
  const body = {...v, unit_cost: parseFloat(v.unit_cost) || 0, min_qty: parseFloat(v.min_qty) || 0};
  return item ? api('PATCH', '/warehouse/items/' + item.id, body) : api('POST', '/warehouse/items', body);
}

route('warehouse', async (tab) => {
  tab = tab || 'items';
  const tabs = h('div', {class: 'tabs'}, [['items', 'wh_items'], ['mine', 'wh_mine'], ['moves', 'wh_moves']].map(([k, key]) => h('a', {href: '#/warehouse/' + (k === 'items' ? '' : k), class: tab === k ? 'on' : ''}, t(key))));
  const head = (extra) => pageHead(t('warehouse'), extra, isManager() && tab === 'items' ? h('button', {onclick: guard(async () => { if (await itemForm(null)) render(); })}, '+ ' + t('add_item')) : null);
  if (tab === 'mine') {
    const mine = await api('GET', '/warehouse/mine');
    return h('div', {}, head(), tabs, table([t('item'), t('kind'), t('qty'), ''], mine.map((x) => [h('a', {href: '#/item/' + x.item_id}, x.name), t('wh_' + x.kind), `${num(x.qty)} ${x.unit}`,
      h('button', {class: 'ghost small', onclick: guard(async () => { const it = (await api('GET', '/warehouse/items/' + x.item_id)).item; await moveDialog(it, x.kind === 'material' ? 'consume' : 'return', () => render()); })}, x.kind === 'material' ? t('mv_consume') : t('mv_return'))]), {numCols: [2]}));
  }
  if (tab === 'moves') {
    const [items, staff] = await Promise.all([api('GET', '/warehouse/items'), roleIn(3) ? [] : api('GET', '/staff')]);
    const f = {item: selectEl([{value: '', label: t('all')}, ...items.map((i) => ({value: i.id, label: i.name}))], ''), kind: selectEl([{value: '', label: t('all')}, ...MOVE_KINDS.map((k) => ({value: k, label: t('mv_' + k)}))], ''),
      user: selectEl([{value: '', label: t('all')}, ...staff.map((s) => ({value: s.id, label: personName(s)}))], ''), from: h('input', {type: 'date', value: daysAgo(30)}), to: h('input', {type: 'date', value: today()})};
    const out = h('div', {});
    const load = guard(async () => {
      const qs = new URLSearchParams({frm: f.from.value, to: f.to.value, limit: 1000});
      if (f.item.value) qs.set('item_id', f.item.value); if (f.kind.value) qs.set('kind', f.kind.value); if (f.user.value) qs.set('user_id', f.user.value);
      const rows = await api('GET', '/warehouse/moves?' + qs);
      out.replaceChildren(table([t('date'), t('item'), t('kind'), t('qty'), t('from'), t('to'), t('order'), t('by'), t('note')], rows.map((m) => [fmtDate(m.created_at), h('a', {href: '#/item/' + m.item_id}, m.item),
        t('mv_' + m.kind), `${num(m.qty)} ${m.unit}`, m.from_name || '', m.to_name || '', m.order_id ? h('a', {href: '#/order/' + m.order_id}, '#' + m.order_id) : '', m.by || '', m.note]), {numCols: [3]}));
    });
    Object.values(f).forEach((e) => { e.onchange = load; });
    load();
    return h('div', {}, head(h('button', {class: 'ghost', onclick: guard(() => downloadReport('warehouse', {frm: f.from.value, to: f.to.value}))}, '⬇ Excel')), tabs,
      h('div', {class: 'filters'}, fieldBox('item', f.item), fieldBox('kind', f.kind), roleIn(3) ? null : fieldBox('employee', f.user), fieldBox('from', f.from), fieldBox('to', f.to)), out);
  }
  const q = h('input', {placeholder: t('search'), style: 'max-width:240px'});
  const list = h('div', {});
  let items = await api('GET', '/warehouse/items');
  const draw = () => {
    const needle = q.value.trim().toLowerCase();
    const rows = items.filter((i) => !needle || `${i.name} ${i.sku}`.toLowerCase().includes(needle));
    list.replaceChildren(...(rows.length ? rows.map((i) => h('div', {class: 'card click itemcard', onclick: () => { location.hash = '#/item/' + i.id; }},
      i.thumb ? h('img', {src: fileUrl(i.thumb), alt: ''}) : h('div', {class: 'thumbph'}, i.kind === 'equipment' ? '🔧' : '📦'),
      h('div', {class: 'grow'}, h('div', {class: 'row'}, h('b', {class: 'grow'}, i.name), h('span', {class: 'badge'}, t('wh_' + i.kind)), i.low ? h('span', {class: 'badge st-cancelled', style: 'background:var(--bad);color:#fff'}, t('low_stock')) : null),
        h('div', {class: 'muted small'}, [i.sku, `${t('in_warehouse')}: ${num(i.in_warehouse)} ${i.unit}`, `${t('with_staff')}: ${num(i.with_staff)}`, i.mine ? `${t('on_me')}: ${num(i.mine)}` : null].filter(Boolean).join(' · '))))) : [h('p', {class: 'muted'}, t('no_data'))]));
  };
  q.oninput = draw; draw();
  return h('div', {}, head(q), tabs, list);
}, [1, 2, 3, 6, 7]);

route('item', async (id) => {
  const d = await api('GET', '/warehouse/items/' + id), it = d.item;
  const reload = () => render();
  const acts = h('div', {class: 'actions'});
  const a = (kind, cls) => acts.append(h('button', {class: cls || 'ghost', onclick: guard(() => moveDialog(it, kind, reload))}, t('mv_' + kind)));
  if (roleIn(1, 2, 3, 7)) {
    a('take', 'go');
    if (it.mine > 0 || isManager()) { a('transfer'); a('return'); if (it.kind === 'material') a('consume'); }
  }
  if (isManager()) { a('receipt'); a('writeoff', 'danger'); acts.append(h('button', {class: 'ghost', onclick: guard(async () => { if (await itemForm(it)) reload(); })}, t('edit'))); }
  if (roleIn(1, 2, 3, 7)) acts.append(h('button', {class: 'ghost', onclick: guard(async () => {
    const fl = await chooseFiles('image/*,video/*,.pdf'); if (!fl.length) return;
    const v = await formModal(t('description'), [{key: 'description', label: 'description', type: 'textarea'}]); if (!v) return;
    await uploadFiles(`/warehouse/items/${id}/files`, fl, {description: v.description}); toast(t('saved')); reload(); })}, '📷 ' + t('add_photo_video')));
  acts.append(h('button', {class: 'ghost', onclick: guard(async () => { await api('POST', '/chat', {kind: 'item', item_id: +id}); toast(t('shared_to_chat')); })}, '💬 ' + t('share_chat')));
  const gallery = d.files.map((f) => {
    const url = fileUrl(f.id);
    return h('div', {class: 'fcard'}, f.mime.startsWith('image/') ? h('a', {href: url, target: '_blank', rel: 'noopener'}, h('img', {src: url, alt: f.original}))
      : f.mime.startsWith('video/') ? h('video', {src: url, controls: true, preload: 'metadata'}) : h('div', {class: 'ficon'}, fileIcon(f.original, f.mime)),
      h('div', {class: 'ffoot'}, f.description ? h('div', {}, f.description) : null, h('div', {class: 'muted small'}, `${f.original} · ${fmtBytes(f.size)} · ${f.uploader || ''}`),
        h('button', {class: 'ghost small', onclick: guard(() => saveUrl(url, f.original, f.mime))}, t('save_as'))));
  });
  return h('div', {}, h('div', {class: 'row'}, back('#/warehouse'), h('h1', {class: 'grow'}, it.name)),
    h('div', {class: 'card'}, kvList([[t('sku'), it.sku || '-'], [t('kind'), t('wh_' + it.kind)], [t('in_warehouse'), `${num(it.in_warehouse)} ${it.unit}`], [t('with_staff'), `${num(it.with_staff)} ${it.unit}`],
      [t('on_me'), `${num(it.mine)} ${it.unit}`], isManager() ? [t('price'), money(it.unit_cost)] : null, [t('min_qty'), num(it.min_qty)], [t('description'), it.description || '-']])), acts,
    h('h2', {}, t('who_has_it')), table([t('employee'), t('company'), t('qty'), t('last_seen'), ''], d.holders.map((x) => [h('span', {}, h('span', {class: 'dot ' + (x.online ? 'on' : '')}), ' ', x.name), x.company || '', `${num(x.qty)} ${it.unit}`,
      x.last_seen ? fmtDate(x.last_seen) : '-', h('span', {class: 'row'}, x.lat != null ? h('button', {class: 'ghost small', onclick: () => holderMap(x)}, '📍 ' + t('where_is_it')) : null,
        x.phone ? h('a', {class: 'btnlink small', href: 'tel:' + x.phone}, '📞') : null, h('a', {class: 'btnlink small', href: '#/chat'}, '💬'))]), {numCols: [2]}),
    h('h2', {}, t('media')), gallery.length ? h('div', {class: 'gallery'}, gallery) : h('p', {class: 'muted'}, t('no_data')),
    h('h2', {}, t('wh_moves')), table([t('date'), t('kind'), t('qty'), t('from'), t('to'), t('order'), t('by')], d.moves.map((m) => [fmtDate(m.created_at), t('mv_' + m.kind), `${num(m.qty)} ${m.unit}`, m.from_name || '', m.to_name || '', m.order_id ? '#' + m.order_id : '', m.by || '']), {numCols: [2]}));
}, [1, 2, 3, 6, 7]);
