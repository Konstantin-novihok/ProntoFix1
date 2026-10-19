/*
 * Общий чат сотрудников: текст, фото/видео/документы, геопозиция, ссылка на складскую позицию (с тем, у кого она и где он).
 * История хранится на сервере. Файлы чата попадают в общее хранилище, где администратор может просмотреть и удалить любой.
 */
'use strict';

route('chat', async () => {
  const canWrite = roleIn(1, 2, 3, 7);
  const box = h('div', {class: 'chatbox'});
  const seen = new Set();
  let last = 0, first = 0;
  const nearBottom = () => box.scrollHeight - box.scrollTop - box.clientHeight < 120;

  const locBtn = (lat, lon, who) => h('button', {class: 'ghost small', onclick: () => holderMap({full_name: who, lat, lon, last_seen: null, phone: ''})}, '📍 ' + t('show_on_map'));
  const msgEl = (m) => {
    const mine = m.sender_id === S.me.id;
    const body = [];
    if (m.deleted) body.push(h('i', {class: 'muted'}, t('msg_deleted')));
    else {
      if (m.text) body.push(h('div', {class: 'msgtext'}, m.text));
      if (m.kind === 'location') body.push(h('div', {}, '📍 ' + t('shared_location')), h('div', {class: 'row'}, locBtn(m.lat, m.lon, m.sender),
        h('a', {class: 'btnlink small', href: mapLink(m.lat, m.lon), target: '_blank', rel: 'noopener'}, '🧭 ' + t('navigate'))));
      if (m.file) {
        const f = m.file, url = fileUrl(f.id);
        body.push(f.mime.startsWith('image/') ? h('a', {href: url, target: '_blank', rel: 'noopener'}, h('img', {class: 'chatimg', src: url, alt: f.original}))
          : f.mime.startsWith('video/') ? h('video', {class: 'chatimg', src: url, controls: true, preload: 'metadata'})
          : f.mime.startsWith('audio/') ? h('audio', {src: url, controls: true})
          : h('div', {class: 'row'}, h('span', {style: 'font-size:28px'}, fileIcon(f.original, f.mime)), h('a', {href: url, target: '_blank', rel: 'noopener'}, f.original)),
          h('div', {class: 'row small muted'}, `${f.original} · ${fmtBytes(f.size)}`, h('button', {class: 'ghost small', onclick: guard(() => saveUrl(url, f.original, f.mime))}, t('save_as'))));
      }
      if (m.item) {
        const it = m.item;
        body.push(h('div', {class: 'itemshare'}, h('b', {}, '📦 ', h('a', {href: '#/item/' + it.id}, it.name)),
          it.holders.length ? it.holders.map((x) => h('div', {class: 'row small'}, h('span', {class: 'dot ' + (x.online ? 'on' : '')}), h('span', {class: 'grow'}, `${x.name}: ${num(x.qty)} ${it.unit}`),
            x.lat != null ? h('button', {class: 'ghost small', onclick: () => holderMap(x)}, '📍') : null, x.phone ? h('a', {class: 'btnlink small', href: 'tel:' + x.phone}, '📞') : null))
            : h('div', {class: 'muted small'}, t('only_in_warehouse'))));
      }
    }
    return h('div', {class: 'msg' + (mine ? ' mine' : '')},
      h('div', {class: 'msghead'}, h('b', {}, m.sender), m.sender_company ? h('span', {class: 'muted small'}, ' · ' + m.sender_company) : null, h('span', {class: 'muted small'}, ' · ' + fmtDate(m.created_at)),
        isAdmin() && !m.deleted ? h('button', {class: 'ghost small', title: t('delete'), onclick: guard(async () => { if (await confirmBox(t('delete') + '?')) { await api('DELETE', '/chat/' + m.id); render(); } })}, '✕') : null),
      ...body);
  };
  const add = (list, prepend) => {
    const stick = nearBottom();
    const els = list.filter((m) => !seen.has(m.id)).map((m) => { seen.add(m.id); last = Math.max(last, m.id); first = first ? Math.min(first, m.id) : m.id; return msgEl(m); });
    if (prepend) els.reverse().forEach((e) => box.prepend(e)); else box.append(...els);
    if (!prepend && (stick || !box.dataset.ready)) { box.scrollTop = box.scrollHeight; box.dataset.ready = '1'; }
  };
  add(await api('GET', '/chat?limit=60'));
  const more = h('button', {class: 'ghost small', onclick: guard(async () => { const older = await api('GET', `/chat?before=${first}&limit=60`); if (!older.length) toast(t('no_data')); add(older, true); })}, t('load_earlier'));
  every(4000, async () => { const fresh = await api('GET', '/chat?after=' + last); if (fresh.length) add(fresh); });

  const text = h('input', {placeholder: t('message'), style: 'flex:1', onkeydown: (e) => { if (e.key === 'Enter') send(); }});
  const send = guard(async () => { const v = text.value.trim(); if (!v) return; text.value = ''; add([await api('POST', '/chat', {kind: 'text', text: v})]); });
  const sendFiles = guard(async (files) => {
    for (const f of files) { const fd = new FormData(); fd.append('file', f, f.name); add([await api('POST', '/chat/files', fd)]); }
  });
  const staffDir = guard(async () => {
    const st = await api('GET', '/staff');
    modal(t('staff_directory'), h('div', {}, table([t('employee'), t('company'), t('phone'), ''], st.map((s) => [h('span', {}, h('span', {class: 'dot ' + (s.online ? 'on' : '')}), ' ', personName(s)), s.company_name || '', s.phone ? h('a', {href: 'tel:' + s.phone}, s.phone) : '-',
      s.last_lat != null ? h('button', {class: 'ghost small', onclick: () => holderMap(s)}, '📍') : ''])), h('div', {style: 'margin-top:10px'}, h('button', {onclick: (e) => e.target.closest('.modal-back').remove()}, t('close')))));
  });
  const bar = canWrite ? h('div', {class: 'chatbar'}, text, h('button', {onclick: send}, '➤'),
    h('button', {class: 'ghost', title: t('attach_file'), onclick: guard(async () => sendFiles(await chooseFiles('')))}, '📎'),
    h('button', {class: 'ghost', title: t('take_photo'), onclick: guard(async () => { const x = await cameraCapture(); if (x) await sendFiles([x]); })}, '📷'),
    h('button', {class: 'ghost', title: t('share_location'), onclick: guard(async () => { const p = await gpsLocate(); add([await api('POST', '/chat', {kind: 'location', lat: p.lat, lon: p.lon})]); })}, '📍'),
    h('button', {class: 'ghost', title: t('share_item'), onclick: guard(async () => {
      const items = await api('GET', '/warehouse/items'); const it = await pick(t('share_item'), items.map((i) => ({label: `${i.name} (${num(i.in_warehouse)}+${num(i.with_staff)})`, value: i.id})));
      if (it) add([await api('POST', '/chat', {kind: 'item', item_id: it})]); })}, '📦')) : h('p', {class: 'muted'}, t('read_only'));
  return h('div', {}, pageHead(t('chat'), h('button', {class: 'ghost', onclick: staffDir}, '👥 ' + t('staff_directory'))), h('div', {class: 'chatwrap'}, h('div', {class: 'row', style: 'justify-content:center'}, more), box, bar));
}, [1, 2, 3, 6, 7]);
