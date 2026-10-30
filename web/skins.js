/*
 * Скины (темы). Скин меняет ТОЛЬКО цвета и шрифт. Масштаб, расположение кнопок и значков, функции и логика не меняются.
 * 20 готовых скинов + свои (создаёт любой пользователь). Администратор задаёт скин по умолчанию для всех и общие скины.
 * Значения проходят проверку и на сервере (только #rrggbb и шрифты из списка) — вставить чужой CSS через скин нельзя.
 */
'use strict';

const FONTS = {
  system: 'system-ui,-apple-system,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif',
  humanist: 'Candara,"Segoe UI","Trebuchet MS",Optima,Verdana,sans-serif',
  verdana: 'Verdana,Geneva,Tahoma,sans-serif',
  tahoma: 'Tahoma,"Segoe UI",Geneva,sans-serif',
  trebuchet: '"Trebuchet MS","Lucida Grande","Lucida Sans Unicode",sans-serif',
  georgia: 'Georgia,"Times New Roman",Times,serif',
  serif: '"Palatino Linotype","Book Antiqua",Palatino,"Times New Roman",serif',
  mono: 'ui-monospace,"Cascadia Code","SF Mono",Consolas,"Liberation Mono",monospace',
  rounded: '"Arial Rounded MT Bold","Segoe UI",system-ui,sans-serif',
  condensed: '"Arial Narrow","Roboto Condensed","Helvetica Neue",Arial,sans-serif',
};
const FONT_NAMES = {system: 'System', humanist: 'Humanist', verdana: 'Verdana', tahoma: 'Tahoma', trebuchet: 'Trebuchet', georgia: 'Georgia', serif: 'Palatino', mono: 'Monospace', rounded: 'Rounded', condensed: 'Condensed'};
const COLOR_KEYS = ['bg', 'card', 'text', 'muted', 'line', 'accent', 'accentText', 'ok', 'warn', 'bad'];
const CSS_VAR = {bg: '--bg', card: '--card', text: '--text', muted: '--muted', line: '--line', accent: '--accent', accentText: '--accent-text', ok: '--ok', warn: '--warn', bad: '--bad'};

const sk = (id, name, mode, font, c) => ({id, name, mode, font, colors: {bg: c[0], card: c[1], text: c[2], muted: c[3], line: c[4], accent: c[5], accentText: c[6], ok: c[7], warn: c[8], bad: c[9]}});
const SKINS = [
  {id: 'auto', name: 'Auto', auto: true},
  sk('light', 'Light', 'light', 'system', ['#f3f5f8', '#ffffff', '#1d2530', '#6b7686', '#dde2ea', '#2f6fed', '#ffffff', '#1b9e5a', '#e08a00', '#d64545']),
  sk('dark', 'Dark', 'dark', 'system', ['#12161c', '#1b222b', '#e8edf3', '#98a4b3', '#2b3542', '#4c8dff', '#0b1220', '#3ec785', '#f0a030', '#ff6b6b']),
  sk('ocean', 'Ocean', 'light', 'system', ['#eaf4fb', '#ffffff', '#0b2a3d', '#4f7189', '#cfe3f1', '#0a7bc4', '#ffffff', '#1b9e7a', '#d98e00', '#d1443b']),
  sk('forest', 'Forest', 'light', 'humanist', ['#eef5ee', '#ffffff', '#1c2e1f', '#5b7560', '#d3e4d4', '#2e7d32', '#ffffff', '#2e7d32', '#c77f00', '#c0392b']),
  sk('sunset', 'Sunset', 'light', 'system', ['#fff3ea', '#fffaf6', '#3a1f14', '#8a5a44', '#f4d9c6', '#e8590c', '#ffffff', '#2f9e44', '#f08c00', '#c92a2a']),
  sk('lavender', 'Lavender', 'light', 'rounded', ['#f4f0fb', '#ffffff', '#2a1f3d', '#7a6a96', '#e0d6f2', '#7048e8', '#ffffff', '#2f9e6e', '#d9830a', '#d6336c']),
  sk('rose', 'Rose', 'light', 'system', ['#fdf0f3', '#ffffff', '#3d1a24', '#9a5a6b', '#f5d3dc', '#d6336c', '#ffffff', '#2f9e44', '#e67700', '#c92a2a']),
  sk('graphite', 'Graphite', 'dark', 'condensed', ['#1f2124', '#2a2d31', '#e6e6e6', '#a0a4a8', '#3a3e43', '#9aa5b1', '#14161a', '#5fbf8a', '#e0a040', '#e06c6c']),
  sk('midnight', 'Midnight', 'dark', 'system', ['#0b1020', '#141b33', '#e6ecff', '#8d9bd0', '#25305a', '#6c8cff', '#0b1020', '#45d4a0', '#ffb347', '#ff6b81']),
  sk('sand', 'Sand', 'light', 'georgia', ['#f6efe2', '#fffaf0', '#3b3224', '#8c7b62', '#e6dcc5', '#b7791f', '#ffffff', '#2f855a', '#c05621', '#c53030']),
  sk('mint', 'Mint', 'light', 'system', ['#e9f8f3', '#ffffff', '#12332b', '#4f7f72', '#c8ebe0', '#12a384', '#ffffff', '#12a384', '#d69e2e', '#d9534f']),
  sk('cherry', 'Cherry', 'light', 'system', ['#fbeff0', '#ffffff', '#3a0f16', '#94505a', '#f1cfd3', '#c2185b', '#ffffff', '#2e7d32', '#ef6c00', '#b71c1c']),
  sk('slate', 'Slate', 'light', 'tahoma', ['#e8ecf1', '#f7f9fb', '#1f2933', '#5f6b7a', '#d2d9e1', '#3e5c76', '#ffffff', '#2f855a', '#b7791f', '#c53030']),
  sk('amber', 'Amber', 'light', 'trebuchet', ['#fff8e1', '#fffdf5', '#3b2e00', '#8d7420', '#f5e6a8', '#f59f00', '#2b2000', '#2f9e44', '#e67700', '#d9480f']),
  sk('teal', 'Teal Night', 'dark', 'system', ['#0e2a2f', '#143a40', '#e0f7f5', '#8bc7c2', '#1f4f56', '#2dd4bf', '#06312c', '#4ade80', '#fbbf24', '#f87171']),
  sk('plum', 'Plum', 'dark', 'rounded', ['#2a1630', '#381d40', '#f7e8fb', '#c39ad0', '#522b5c', '#e879f9', '#2a1630', '#5eead4', '#fbbf24', '#fb7185']),
  sk('solar-light', 'Solar Light', 'light', 'serif', ['#fdf6e3', '#eee8d5', '#586e75', '#93a1a1', '#d9d2bd', '#268bd2', '#fdf6e3', '#859900', '#b58900', '#dc322f']),
  sk('solar-dark', 'Solar Dark', 'dark', 'mono', ['#002b36', '#073642', '#93a1a1', '#657b83', '#0f4a58', '#2aa198', '#002b36', '#859900', '#b58900', '#dc322f']),
  sk('contrast', 'High Contrast', 'dark', 'verdana', ['#000000', '#111111', '#ffffff', '#d0d0d0', '#ffffff', '#ffd400', '#000000', '#00e676', '#ffab00', '#ff5252']),
];

// Применить скин ко всему приложению (null = автоматически по теме устройства)
function applySkin(skin) {
  const root = document.documentElement;
  for (const v of Object.values(CSS_VAR)) root.style.removeProperty(v);
  root.style.removeProperty('--font');
  root.style.colorScheme = '';
  if (!skin || skin.auto || !skin.colors) return;
  for (const k of COLOR_KEYS) if (skin.colors[k]) root.style.setProperty(CSS_VAR[k], skin.colors[k]);
  root.style.setProperty('--font', FONTS[skin.font] || FONTS.system);
  root.style.colorScheme = skin.mode === 'dark' ? 'dark' : 'light';
  const meta = document.querySelector('meta[name=theme-color]');
  if (meta) meta.content = skin.colors.card;
}
// Стиль-строка для «живого» предпросмотра: переменные действуют только внутри предпросмотра
function skinStyle(skin) {
  if (!skin || !skin.colors) return '';
  return COLOR_KEYS.map((k) => `${CSS_VAR[k]}:${skin.colors[k]}`).join(';') + `;--font:${FONTS[skin.font] || FONTS.system};color-scheme:${skin.mode}`;
}
const cleanSkin = (s) => s && s.colors ? {name: s.name || '', mode: s.mode === 'dark' ? 'dark' : 'light', font: s.font || 'system', colors: Object.assign({}, s.colors)} : null;
// Загрузка скина при старте: личный → кэш устройства → скин по умолчанию (задал администратор) → авто
function initSkin() {
  let s = null;
  if (S.me && S.me.skin) s = S.me.skin;
  else if (!S.me) { try { s = JSON.parse(ls.get('hm_skin') || 'null'); } catch (e) { s = null; } }
  if (!s) s = S.pub.default_skin || null;
  applySkin(s);
  S.skin = s;
}
async function chooseSkin(skin) {
  const data = skin && !skin.auto ? cleanSkin(skin) : null;
  applySkin(data);
  S.skin = data;
  ls.set('hm_skin', data ? JSON.stringify(data) : null);
  if (S.me) { await api('PUT', '/me/skin', {skin: data}); S.me.skin = data; }
}
const sameSkin = (a, b) => (!a && !b) || (a && b && a.font === b.font && COLOR_KEYS.every((k) => a.colors[k] === b.colors[k]));

// Карточка-образец скина
function skinCard(skin, active, onClick, extra) {
  const c = skin.auto ? null : skin.colors;
  const style = c ? skinStyle(skin) : '';
  return h('div', {class: 'skincard' + (active ? ' active' : ''), style, onclick: onClick},
    h('div', {class: 'swatch'}, c ? COLOR_KEYS.slice(0, 6).map((k) => h('i', {style: `background:${c[k]}`})) : [h('i', {style: 'background:linear-gradient(90deg,#f3f5f8 50%,#12161c 50%);width:100%'})]),
    h('b', {style: c ? `font-family:${FONTS[skin.font]}` : ''}, skin.auto ? t('skin_auto') : skin.name), extra || null);
}

// Редактор скина: 10 цветов из палитры + шрифт. Размеры, расположение и логика недоступны.
function skinEditor(initial, opts) {
  const cur = cleanSkin(initial) || cleanSkin(SKINS[1]);
  const name = h('input', {value: cur.name || '', placeholder: t('skin_name')});
  const mode = selectEl([{value: 'light', label: t('mode_light')}, {value: 'dark', label: t('mode_dark')}], cur.mode);
  const font = selectEl(Object.keys(FONTS).map((k) => ({value: k, label: FONT_NAMES[k]})), cur.font);
  const inputs = {};
  const preview = h('div', {class: 'skinpreview'});
  const read = () => ({name: name.value.trim(), mode: mode.value, font: font.value, colors: Object.fromEntries(COLOR_KEYS.map((k) => [k, inputs[k].value]))});
  const redraw = () => {
    const s = read();
    preview.setAttribute('style', skinStyle(s));
    preview.replaceChildren(h('div', {class: 'pv-card'}, h('b', {}, name.value || t('skin_preview')), h('p', {}, 'Aa Бб Ўў 123 — ' + t('skin_preview')),
      h('p', {class: 'pv-muted'}, t('skin_preview')), h('div', {class: 'row'}, h('button', {}, t('ok')), h('button', {class: 'ghost'}, t('cancel')),
        h('span', {class: 'badge st-done'}, 'OK'), h('span', {class: 'badge st-assigned'}, '!'), h('span', {class: 'badge', style: 'background:var(--bad);color:#fff'}, '×'))));
  };
  const grid = h('div', {class: 'colorgrid'}, COLOR_KEYS.map((k) => {
    inputs[k] = h('input', {type: 'color', value: cur.colors[k], oninput: redraw});
    return h('label', {class: 'colorpick'}, inputs[k], h('span', {}, t('c_' + k)));
  }));
  mode.onchange = redraw; font.onchange = redraw; name.oninput = redraw;
  const setFrom = (s) => { name.value = s.name || ''; mode.value = s.mode; font.value = s.font; COLOR_KEYS.forEach((k) => { inputs[k].value = s.colors[k]; }); redraw(); };
  const base = selectEl([{value: '', label: '— ' + t('skin_builtin') + ' —'}, ...SKINS.filter((s) => !s.auto).map((s) => ({value: s.id, label: s.name}))], '');
  base.onchange = () => { const s = SKINS.find((x) => x.id === base.value); if (s) setFrom(s); };
  redraw();
  const el = h('div', {class: 'card'}, h('p', {class: 'muted small'}, t('skin_note_layout')),
    fieldBox('skin_name', name), h('div', {class: 'row'}, h('div', {class: 'grow'}, fieldBox('skin_mode', mode)), h('div', {class: 'grow'}, fieldBox('font', font))),
    h('label', {}, t('skin_builtin')), base, h('h2', {}, t('skin_palette')), grid, preview,
    h('div', {class: 'row', style: 'margin-top:12px'}, h('button', {onclick: () => applySkin(read())}, t('skin_apply')),
      ...(opts.actions || []).map((a) => h('button', {class: a.cls || 'ghost', onclick: guard(() => a.fn(read()))}, a.label))));
  return {el, read};
}

async function view_skins() {
  const mine = await api('GET', '/skins');
  const draw = () => render();
  const apply = guard(async (s) => { await chooseSkin(s); toast(t('saved')); draw(); });
  const current = S.skin;
  const own = mine.filter((x) => x.mine && !x.shared), shared = mine.filter((x) => x.shared);
  const delBtn = (x) => h('button', {class: 'ghost small', style: 'margin-top:6px', onclick: guard(async (e) => { e.stopPropagation(); if (await confirmBox(t('delete') + '?')) { await api('DELETE', '/skins/' + x.id); draw(); } })}, '✕');
  const setDefault = (x) => isAdmin() ? h('button', {class: 'ghost small', style: 'margin-top:6px', onclick: guard(async (e) => { e.stopPropagation(); await api('PUT', '/settings', {values: {default_skin: cleanSkin(x.data || x)}}); S.pub.default_skin = cleanSkin(x.data || x); toast(t('saved')); }) }, t('skin_default_all')) : null;
  const editorBox = h('div', {});
  const openEditor = (init) => {
    const actions = [{label: t('skin_save'), cls: '', fn: async (s) => {
      if (!s.name) throw new Error(t('skin_name'));
      await api('POST', '/skins', {name: s.name, data: s, shared: false}); await chooseSkin(s); toast(t('saved')); draw(); }}];
    if (isAdmin()) {
      actions.push({label: t('skin_share'), fn: async (s) => { if (!s.name) throw new Error(t('skin_name')); await api('POST', '/skins', {name: s.name, data: s, shared: true}); toast(t('saved')); draw(); }});
      actions.push({label: t('skin_default_all'), fn: async (s) => { await api('PUT', '/settings', {values: {default_skin: cleanSkin(s)}}); S.pub.default_skin = cleanSkin(s); toast(t('saved')); }});
    }
    editorBox.replaceChildren(skinEditor(init || current, {actions}).el);
    editorBox.scrollIntoView({behavior: 'smooth'});
  };
  const nameInput = h('input', {value: S.pub.app_name || ''});
  return h('div', {}, pageHead(t('skins')),
    h('p', {class: 'muted'}, t('skin_note_layout')),
    h('h2', {}, t('skin_builtin')), h('div', {class: 'skingrid'}, SKINS.map((s) => skinCard(s, s.auto ? !current : sameSkin(current, s), () => apply(s), setDefault(s)))),
    shared.length ? [h('h2', {}, t('skin_shared')), h('div', {class: 'skingrid'}, shared.map((x) => skinCard(x.data, sameSkin(current, x.data), () => apply(x.data), h('div', {}, setDefault(x), isAdmin() ? delBtn(x) : null))))] : null,
    h('h2', {}, t('skin_mine')), h('div', {class: 'skingrid'}, own.map((x) => skinCard(x.data, sameSkin(current, x.data), () => apply(x.data), delBtn(x)))),
    h('div', {class: 'row', style: 'margin:12px 0'}, h('button', {onclick: () => openEditor()}, '+ ' + t('skin_create'))), editorBox,
    isAdmin() ? [
      h('div', {class: 'card'}, h('h2', {}, t('app_name')), nameInput, h('div', {style: 'margin-top:10px'}, h('button', {onclick: guard(async () => {
        await api('PUT', '/settings', {values: {app_name: nameInput.value}}); S.pub.app_name = nameInput.value; document.title = nameInput.value; const b = $('#brand'); if (b) b.textContent = '🛠 ' + nameInput.value; applyBrand(); toast(t('saved')); })}, t('ok')))),
      h('div', {class: 'card'}, h('h2', {}, 'Публикация обновления Android'),
        h('p', {class: 'muted small'}, 'Старые версии остаются совместимыми по умолчанию. Ссылка должна вести на APK по HTTPS.'),
        ...[['version_code','Код версии','number'],['version_name','Название версии','text'],['download_url','HTTPS-ссылка на APK','url'],['sha256','SHA-256 (необязательно)','text'],['notes','Описание изменений','text']].map(([k,label,type]) => h('label', {class:'field'}, h('span',{},label), h('input',{type, id:'release-'+k, placeholder:label}))),
        h('label', {class:'field'}, h('span',{},'Минимальная версия клиента (1 = не блокировать старые)'), h('input',{type:'number',id:'release-min',value:'1'})),
        h('label', {class:'field'}, h('span',{},'Совместимый API (минимум / максимум)'), h('div',{class:'row'},h('input',{type:'number',id:'release-api-min',value:'1'}),h('input',{type:'number',id:'release-api-max',value:'1'}))),
        h('button', {onclick:guard(async()=>{
          const v=id=>$('#release-'+id).value.trim();
          await api('POST','/app/releases',{platform:'android',version_code:Number(v('version_code')),version_name:v('version_name'),download_url:v('download_url'),sha256:v('sha256'),notes:v('notes'),min_client_version:Number($('#release-min').value||1),api_min:Number($('#release-api-min').value||1),api_max:Number($('#release-api-max').value||1),mandatory:false});
          toast('Обновление опубликовано'); ['version_code','version_name','download_url','sha256','notes'].forEach(k=>$('#release-'+k).value='');
        })},'Опубликовать обновление'))
    ] : null);
}
route('skins', view_skins);
