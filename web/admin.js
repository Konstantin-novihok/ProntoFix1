/*
 * Администрирование (владелец и назначенные администраторы): работает и на телефоне.
 * Разделы: графики, отчёты Excel, финансы и предоплата, оплата сотрудников, подрядчики, карта сотрудников, хранилище файлов,
 * склад, настройки, оформление, направления, журнал.
 */
'use strict';

route('admin', () => {
  const tiles = [
    ['analytics', '📊', 'analytics', 'tile_analytics'], ['reports', '📑', 'reports', 'tile_reports'], ['finance', '💰', 'finance', 'tile_finance'],
    ['payroll', '🧾', 'payroll', 'tile_payroll'], ['contractors', '🤝', 'contractors', 'tile_contractors'], ['staffmap', '👥', 'staff_map', 'tile_staffmap'],
    ['routes', '🛣', 'routes', 'tile_routes'], ['files', '🗂', 'files', 'tile_files'], ['warehouse', '📦', 'warehouse', 'tile_warehouse'],
    ['users', '👤', 'users', 'tile_users'], ['departments', '🏢', 'departments', 'tile_departments'], ['appsettings', '⚙', 'app_settings', 'tile_settings'],
    ['skins', '🎨', 'skins', 'tile_skins'], ['audit', '📜', 'history', 'tile_audit'],
  ];
  return h('div', {}, h('h1', {}, t('admin')), h('p', {class: 'muted'}, `${personName(S.me)} — ${t(ROLE_KEYS[S.me.role])}`),
    h('div', {class: 'tiles'}, tiles.map(([r, icon, title, desc]) => h('a', {class: 'tile', href: '#/' + r}, h('div', {class: 'ticon'}, icon), h('b', {}, t(title)), h('span', {class: 'muted small'}, t(desc))))));
}, [1, 7]);

// ───────────── Финансы: предоплата заказчиков ─────────────
route('finance', async () => {
  const rows = await api('GET', '/finance/clients');
  const reload = () => render();
  const prepay = guard(async (c) => {
    const v = await formModal(`${t('add_prepayment')}: ${c.company || c.name}`, [{key: 'amount', label: 'amount', type: 'number'}, {key: 'note', label: 'note'}]);
    if (!v) return;
    const r = await api('POST', '/finance/prepayment', {client_id: c.id, amount: parseFloat(v.amount), note: v.note}); toast(`${t('prepay_balance')}: ${money(r.balance)}`); reload();
  });
  const adjust = guard(async (c) => {
    const v = await formModal(`${t('adjust')}: ${c.company || c.name}`, [{key: 'amount', label: 'amount_signed', type: 'number'}, {key: 'note', label: 'note'}]);
    if (!v) return;
    await api('POST', '/finance/adjust', {client_id: c.id, amount: parseFloat(v.amount), note: v.note}); reload();
  });
  const ledger = guard(async (c) => {
    const d = await api('GET', '/finance/ledger?client_id=' + c.id);
    modal(`${t('ledger')}: ${c.company || c.name}`, h('div', {}, h('div', {class: 'bignum', style: `color:var(--${d.balance >= 0 ? 'ok' : 'bad'})`}, money(d.balance)),
      table([t('date'), t('kind'), t('amount'), t('order'), t('note')], d.items.map((x) => [fmtDate(x.created_at), t('tx_' + x.kind), money(x.amount), x.order_id ? '#' + x.order_id : '', x.note]), {numCols: [2]}),
      h('div', {style: 'margin-top:10px'}, h('button', {onclick: (e) => e.target.closest('.modal-back').remove()}, t('close')))));
  });
  const sum = (k) => rows.reduce((a, r) => a + r[k], 0);
  return h('div', {}, pageHead(t('finance'), back('#/admin', t('admin')), h('button', {class: 'ghost', onclick: guard(() => downloadReport('finance'))}, '⬇ Excel')),
    h('div', {class: 'kpis'}, [[t('prepaid'), sum('prepaid_total'), 'ok'], [t('charged'), sum('charged_total'), 'accent'], [t('prepay_balance'), sum('balance'), sum('balance') >= 0 ? 'ok' : 'bad']].map(([k, v, c]) =>
      h('div', {class: 'kpi'}, h('div', {class: 'muted small'}, k), h('div', {class: 'kpival', style: `color:var(--${c})`}, money(v))))),
    table([t('company'), t('client'), t('prepaid'), t('charged'), t('prepay_balance'), ''], rows.map((c) => [c.company || '-', c.name, money(c.prepaid_total), money(c.charged_total),
      h('b', {style: `color:var(--${c.balance >= 0 ? 'ok' : 'bad'})`}, money(c.balance)),
      h('span', {class: 'row'}, h('button', {class: 'small', onclick: () => prepay(c)}, '+ ' + t('add_prepayment')), h('button', {class: 'ghost small', onclick: () => ledger(c)}, t('ledger')), h('button', {class: 'ghost small', onclick: () => adjust(c)}, '±'))]), {numCols: [2, 3, 4]}));
}, [1, 7]);

// ───────────── Оплата сотрудников ─────────────
route('payroll', async () => {
  const from = h('input', {type: 'date', value: daysAgo(30)}), to = h('input', {type: 'date', value: today()});
  const out = h('div', {});
  const load = guard(async () => {
    const rows = await api('GET', `/payroll?frm=${from.value}&to=${to.value}`);
    const tot = (k) => rows.reduce((a, r) => a + r[k], 0);
    out.replaceChildren(h('div', {class: 'kpis'}, [[t('earned'), tot('earned')], [t('bonus'), tot('bonus')], [t('fine'), tot('fine')], [t('total'), tot('total')]].map(([k, v]) =>
      h('div', {class: 'kpi'}, h('div', {class: 'muted small'}, k), h('div', {class: 'kpival'}, money(v))))),
    table([t('employee'), t('company'), t('employment'), t('pay_rate'), t('orders_count'), t('earned'), t('bonus'), t('fine'), t('total'), ''], rows.map((r) => [r.name, r.company || '-',
      r.employment === 'external' ? t('emp_external') : t('emp_internal'), `${t('rate_' + r.rate_type)} ${num(r.rate_value)}${r.rate_type === 'percent' ? '%' : ''}`, r.orders, money(r.earned), money(r.bonus), money(r.fine), h('b', {}, money(r.total)),
      h('button', {class: 'ghost small', onclick: () => adjustDialog({id: r.user_id, full_name: r.name}, load)}, t('bonus_fine'))]), {numCols: [4, 5, 6, 7, 8]}));
  });
  from.onchange = load; to.onchange = load; load();
  return h('div', {}, pageHead(t('payroll'), back('#/admin', t('admin')), h('button', {class: 'ghost', onclick: guard(() => downloadReport('payroll', {frm: from.value, to: to.value}))}, '⬇ Excel')),
    h('p', {class: 'muted small'}, t('payroll_hint')), h('div', {class: 'row'}, fieldBox('from', from), fieldBox('to', to)), out);
}, [1, 7]);

// ───────────── Подрядчики и приглашения ─────────────
route('contractors', async () => {
  const [cons, invs] = await Promise.all([api('GET', '/contractors'), api('GET', '/invites')]);
  const reload = () => render();
  const newInvite = guard(async () => {
    const v = await formModal(t('invite_contractor'), [{key: 'company_name', label: 'company_name'}, {key: 'rate_value', label: 'percent_of_profit', type: 'number', value: 30}, {key: 'days', label: 'invite_days', type: 'number', value: 14}, {key: 'note', label: 'note'}]);
    if (!v) return;
    const inv = await api('POST', '/invites', {company_name: v.company_name, rate_value: parseFloat(v.rate_value) || 0, days: parseInt(v.days) || 14, note: v.note});
    const link = `${location.origin}${location.pathname}#/register/${inv.code}`;
    modal(t('invite_contractor'), h('div', {}, h('p', {}, t('invite_code') + ':'), h('div', {class: 'bigcode'}, inv.code), h('p', {class: 'small muted', style: 'word-break:break-all'}, link),
      h('div', {class: 'row'}, h('button', {onclick: guard(async () => { await navigator.clipboard.writeText(link); toast(t('copied')); })}, t('copy')),
        h('button', {class: 'ghost', onclick: (e) => { e.target.closest('.modal-back').remove(); reload(); }}, t('close')))));
  });
  const verBadge = (c) => h('span', {class: 'badge st-' + (c.verification === 'verified' ? 'done' : c.verification === 'rejected' ? 'cancelled' : 'assigned')}, t('ver_' + c.verification));
  return h('div', {}, pageHead(t('contractors'), back('#/admin', t('admin')), h('button', {onclick: newInvite}, '✉ ' + t('invite_contractor'))),
    h('p', {class: 'muted small'}, t('contractor_hint')),
    cons.length ? cons.map((c) => h('div', {class: 'card'}, h('div', {class: 'row'}, h('b', {class: 'grow'}, personName(c), ' ', h('span', {class: 'muted'}, '@' + c.username)), verBadge(c)),
      kvList([[t('company'), c.company_name || '-'], [t('tax_id'), c.tax_id || '-'], [t('phone'), c.phone || '-'], [t('pay_rate'), `${t('rate_' + c.rate_type)} ${num(c.rate_value)}${c.rate_type === 'percent' ? '%' : ''}`],
        [t('documents'), c.documents.length ? c.documents.map((d) => h('a', {href: docUrl(d.id), target: '_blank', rel: 'noopener', style: 'margin-right:10px'}, d.original)) : h('span', {class: 'muted'}, t('no_documents'))]]),
      h('div', {class: 'actions'}, h('button', {class: 'ok', onclick: guard(async () => { await api('PATCH', `/users/${c.id}/verify`, {status: 'verified'}); reload(); })}, '✔ ' + t('ver_verified')),
        h('button', {class: 'danger', onclick: guard(async () => { await api('PATCH', `/users/${c.id}/verify`, {status: 'rejected'}); reload(); })}, '✖ ' + t('ver_rejected')),
        h('button', {class: 'ghost', onclick: guard(() => editProfile(c, reload))}, t('work_profile'))))) : h('p', {class: 'muted'}, t('no_data')),
    h('h2', {}, t('invites')), table([t('invite_code'), t('company'), t('percent_of_profit'), t('expires'), t('used_by'), ''], invs.map((i) => [h('b', {}, i.code), i.company_name || '-', num(i.rate_value) + '%', i.expires_at ? fmtDay(i.expires_at) : '-', i.used_by_name || '-',
      i.used_by ? '' : h('button', {class: 'ghost small', onclick: guard(async () => { await api('DELETE', '/invites/' + i.id); reload(); })}, '✕')])));
}, [1, 2, 7]);

// ───────────── Настройки приложения ─────────────
route('appsettings', async () => {
  const s = await api('GET', '/settings');
  const currencyOptions = [
    ['UAH', 'UAH — гривна'], ['USD', 'USD — доллар США'], ['EUR', 'EUR — евро'], ['GBP', 'GBP — фунт'],
    ['PLN', 'PLN — злотый'], ['CZK', 'CZK — чешская крона'], ['HUF', 'HUF — форинт'], ['RON', 'RON — румынский лей'],
    ['MDL', 'MDL — молдавский лей'], ['BGN', 'BGN — болгарский лев'], ['CHF', 'CHF — швейцарский франк'],
    ['CAD', 'CAD — канадский доллар'], ['AUD', 'AUD — австралийский доллар'], ['JPY', 'JPY — иена'],
    ['CNY', 'CNY — юань'], ['TRY', 'TRY — турецкая лира'], ['AED', 'AED — дирхам ОАЭ'],
    ['SAR', 'SAR — саудовский риял'], ['SEK', 'SEK — шведская крона'], ['NOK', 'NOK — норвежская крона'],
    ['DKK', 'DKK — датская крона'], ['ISK', 'ISK — исландская крона'], ['HRK', 'HRK — куна'],
    ['RSD', 'RSD — сербский динар'], ['GEL', 'GEL — лари'], ['KZT', 'KZT — тенге'],
    ['INR', 'INR — индийская рупия'], ['ILS', 'ILS — новый шекель'], ['MXN', 'MXN — мексиканское песо'],
    ['BRL', 'BRL — бразильский реал']
  ];
  const currencySelect = selectEl(currencyOptions.map(([value, label]) => ({value, label})), s.currency || 'UAH');
  const F = {
    company_name: h('input', {value: s.company_name || ''}), currency: currencySelect,
    cost_per_km: h('input', {type: 'number', step: 'any', value: s.cost_per_km}), road_factor: h('input', {type: 'number', step: '0.05', value: s.road_factor}),
    overdraft_allowed: h('input', {type: 'checkbox', checked: !!s.overdraft_allowed}), require_employee_no: h('input', {type: 'checkbox', checked: !!s.require_employee_no}),
    id_rules_text: h('textarea', {value: s.id_rules_text || ''}), service_types: h('textarea', {value: (s.service_types || []).join('\n'), style: 'min-height:140px'}),
  };
  const save = guard(async () => {
    const values = {company_name: F.company_name.value, currency: F.currency.value, cost_per_km: parseFloat(F.cost_per_km.value) || 0, road_factor: parseFloat(F.road_factor.value) || 1.3,
      overdraft_allowed: F.overdraft_allowed.checked, require_employee_no: F.require_employee_no.checked, id_rules_text: F.id_rules_text.value, service_types: F.service_types.value.split('\n')};
    const r = await api('PUT', '/settings', {values});
    S.pub.currency = r.currency; S.pub.company_name = r.company_name; S.pub.service_types = r.service_types; S.pub.id_rules_text = r.id_rules_text;
    toast(t('saved'));
  });
  const chk = (k, label) => h('label', {class: 'row', style: 'margin:8px 0'}, F[k], t(label));
  return h('div', {}, pageHead(t('app_settings'), back('#/admin', t('admin'))),
    h('div', {class: 'card'}, h('h2', {style: 'margin-top:0'}, t('section_company')), fieldBox('own_company', F.company_name), fieldBox('currency', F.currency)),
    h('div', {class: 'card'}, h('h2', {style: 'margin-top:0'}, t('costing')), fieldBox('cost_per_km', F.cost_per_km), fieldBox('road_factor', F.road_factor), h('p', {class: 'muted small'}, t('road_factor_hint')), chk('overdraft_allowed', 'overdraft_allowed')),
    h('div', {class: 'card'}, h('h2', {style: 'margin-top:0'}, t('identification')), chk('require_employee_no', 'require_employee_no'), fieldBox('id_rules', F.id_rules_text), h('p', {class: 'muted small'}, t('id_rules_hint'))),
    h('div', {class: 'card'}, h('h2', {style: 'margin-top:0'}, t('service_types')), F.service_types, h('p', {class: 'muted small'}, t('one_per_line'))),
    h('div', {class: 'row'}, h('button', {onclick: save}, t('ok')), h('a', {class: 'btnlink', href: '#/skins'}, '🎨 ' + t('skins'))));
}, [1, 7]);

// ───────────── Отчёты Excel ─────────────
route('reports', () => {
  const from = h('input', {type: 'date', value: daysAgo(30)}), to = h('input', {type: 'date', value: today()});
  const cards = [['orders', '📋', 'rep_orders', 'rep_orders_d'], ['payroll', '🧾', 'rep_payroll', 'rep_payroll_d'], ['finance', '💰', 'rep_finance', 'rep_finance_d'],
    ['warehouse', '📦', 'rep_warehouse', 'rep_warehouse_d'], ['routes', '🛣', 'rep_routes', 'rep_routes_d']];
  return h('div', {}, pageHead(t('reports'), back('#/admin', t('admin'))), h('p', {class: 'muted'}, t('reports_hint')),
    h('div', {class: 'row'}, fieldBox('from', from), fieldBox('to', to)),
    h('div', {class: 'tiles'}, cards.map(([k, icon, title, desc]) => h('div', {class: 'tile'}, h('div', {class: 'ticon'}, icon), h('b', {}, t(title)), h('span', {class: 'muted small'}, t(desc)),
      h('button', {onclick: guard(async () => { const r = await downloadReport(k, {frm: from.value, to: to.value}); if (r === 'download') toast(t('saved')); })}, '⬇ ' + t('save_xlsx'))))));
}, [1, 7]);

// ───────────── Хранилище файлов ─────────────
route('files', async () => {
  const st = {sort: 'date', dir: 'desc', q: '', source: ''};
  const out = h('div', {});
  const q = h('input', {placeholder: t('search'), style: 'max-width:240px', oninput: () => { st.q = q.value; load(); }});
  const src = selectEl([{value: '', label: t('all')}, ...['order', 'document', 'chat', 'warehouse'].map((s) => ({value: s, label: t('src_' + s)}))], '', {onchange: () => { st.source = src.value; load(); }});
  const cols = ['name', 'source', 'sender', 'size', 'date'];
  const load = guard(async () => {
    const d = await api('GET', `/storage/files?sort=${st.sort}&dir=${st.dir}&q=${encodeURIComponent(st.q)}&source=${st.source}`);
    const sortable = [0, 2, 3, 4], map = {0: 'name', 2: 'sender', 3: 'size', 4: 'date'};
    out.replaceChildren(h('div', {class: 'kpis'}, h('div', {class: 'kpi'}, h('div', {class: 'muted small'}, t('files_count')), h('div', {class: 'kpival'}, d.count)),
      h('div', {class: 'kpi'}, h('div', {class: 'muted small'}, t('total_size')), h('div', {class: 'kpival'}, fmtBytes(d.total_bytes))),
      ...Object.entries(d.by_source).map(([k, v]) => h('div', {class: 'kpi'}, h('div', {class: 'muted small'}, t('src_' + k)), h('div', {class: 'kpival'}, fmtBytes(v))))),
    table([t('file'), t('source'), t('sender'), t('size'), t('date'), ''], d.items.map((f) => [h('span', {}, fileIcon(f.name, f.mime), ' ', h('a', {href: storageUrl(f.key), target: '_blank', rel: 'noopener'}, f.name)), t('src_' + f.source), f.sender, fmtBytes(f.size), fmtDate(f.date),
      h('span', {class: 'row'}, h('button', {class: 'ghost small', onclick: guard(() => saveUrl(storageUrl(f.key), f.name, f.mime))}, t('save_as')),
        h('button', {class: 'danger small', onclick: guard(async () => { if (await confirmBox(`${t('delete')}: ${f.name}?`)) { await api('DELETE', '/storage/files/' + encodeURIComponent(f.key)); load(); } })}, '🗑'))]),
      {sortable, sortCol: Object.entries(map).find(([, v]) => v === st.sort)?.[0] * 1, sortDir: st.dir, numCols: [3],
        onSort: (i) => { const key = map[i]; if (st.sort === key) st.dir = st.dir === 'asc' ? 'desc' : 'asc'; else { st.sort = key; st.dir = key === 'name' || key === 'sender' ? 'asc' : 'desc'; } load(); }}));
  });
  load();
  return h('div', {}, pageHead(t('files'), back('#/admin', t('admin'))), h('p', {class: 'muted small'}, t('files_hint')), h('div', {class: 'row'}, q, src), out);
}, [1, 7]);

// ───────────── Направления ─────────────
route('departments', async () => {
  const ds = await api('GET', '/departments');
  const add = guard(async () => { const v = await formModal(t('add_department'), [{key: 'name', label: 'name'}]); if (v && v.name.trim()) { await api('POST', '/departments', {name: v.name}); render(); } });
  const setHead = guard(async (d) => {
    const us = (await api('GET', '/users')).filter((u) => u.is_active);
    const id = await pick(t('set_head'), us.map((u) => ({label: personName(u), value: u.id})));
    if (id) { await api('PATCH', '/departments/' + d.id, {head_id: id}); render(); } });
  return h('div', {}, pageHead(t('departments'), back('#/admin', t('admin')), h('button', {onclick: add}, '+ ' + t('add_department'))),
    ds.map((d) => h('div', {class: 'card click', onclick: () => setHead(d)}, h('b', {}, d.name), h('div', {class: 'muted small'}, `${t('head')}: ${d.head_name || '-'}`))));
}, [1, 7]);

// ───────────── Журнал действий ─────────────
route('audit', async () => {
  const rows = await api('GET', '/audit?limit=500');
  return h('div', {}, pageHead(t('history'), back('#/admin', t('admin'))), table([t('date'), t('executor'), t('action'), t('note')], rows.map((r) => [fmtDate(r.created_at), r.actor, `${r.action} → ${r.target_type} #${r.target_id ?? ''}`, r.details])));
}, [1, 7]);
