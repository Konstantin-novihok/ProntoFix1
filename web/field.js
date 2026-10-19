/*
 * Выездная работа:
 *   «Карта»        исполнитель видит заказы на карте, отмечает нужные, строит маршрут с километрами и стоимостью транспорта,
 *                  берёт заказы в работу, включает трекинг и отмечает «Прибыл» (координаты объекта уточняются по его GPS).
 *   «Сотрудники»   администратор видит всех сотрудников на карте (в сети/не в сети), контакты, трек за день.
 *   «Маршруты»     история маршрутов и километраж.
 */
'use strict';

const defaultCenter = () => ({lat: 50.4501, lon: 30.5234});
const pinIcon = (L, n, color) => L.divIcon({className: 'numpin-wrap', html: `<div class="numpin" style="background:${color}">${n}</div>`, iconSize: [28, 28], iconAnchor: [14, 14]});

route('map', async () => {
  const role = S.me.role;
  const executor = role === 3;
  const [orders, routes] = await Promise.all([api('GET', '/map/orders'), executor ? api('GET', '/routes?status=active') : []]);
  const active = routes[0] || null;
  if (active && Tracker.active()) Tracker.routeId = active.id;
  const selected = new Map();        // order_id → order
  let me = null;                     // моё положение
  let plan = null;                   // результат оценки маршрута
  const box = h('div', {class: 'mapbox big'});
  const panel = h('div', {});
  const root = h('div', {}, pageHead(t('map'), isAdmin() ? h('a', {class: 'btnlink', href: '#/staffmap'}, '👥 ' + t('staff_map')) : null, h('a', {class: 'btnlink', href: '#/routes'}, '🛣 ' + t('routes'))),
    box, panel);
  let map = null, L = null, layerRoute = null, markers = {};

  const redrawPanel = () => {
    const sel = [...selected.values()];
    const parts = [];
    if (active) parts.push(activePanel());
    if (executor) {
      parts.push(h('div', {class: 'card'}, h('div', {class: 'row'}, h('b', {class: 'grow'}, `${t('selected_orders')}: ${sel.length}`),
        h('button', {class: 'ghost', disabled: !sel.length, onclick: () => { selected.clear(); plan = null; clearRoute(); refreshMarkers(); redrawPanel(); }}, t('clear'))),
        sel.map((o) => h('div', {class: 'row small'}, h('span', {class: 'grow'}, `#${o.id} ${o.title}${o.address ? ' — ' + o.address : ''}`),
          me ? h('span', {class: 'muted'}, `≈ ${num(haversine(me, o), 1)} km`) : null,
          h('button', {class: 'ghost small', onclick: () => { selected.delete(o.id); plan = null; clearRoute(); refreshMarkers(); redrawPanel(); }}, '✕'))),
        plan ? planView() : null,
        h('div', {class: 'actions'},
          h('button', {class: 'ghost', disabled: !sel.length, onclick: guard(estimate)}, '🧮 ' + t('build_route')),
          h('button', {disabled: !sel.length || !!active, onclick: guard(startRoute)}, '▶ ' + t('take_and_start')))));
      if (!sel.length && !active) parts.push(h('p', {class: 'muted'}, t('map_hint')));
    }
    panel.replaceChildren(...parts);
  };
  const planView = () => h('div', {class: 'planbox'},
    h('div', {}, h('b', {}, `${t('total_km')}: ${num(plan.total_km, 1)} km`), plan.cost_per_km ? `  ·  ${t('transport_cost')}: ${money(plan.transport_cost)}` : ''),
    h('ol', {}, plan.sequence.map((s, i) => h('li', {}, `#${s.o.id} ${s.o.title}`, h('span', {class: 'muted'}, `  +${num(s.leg.km, 1)} km`, s.leg.source === 'measured' ? ` (${t('measured')})` : ` (${t('estimated')})`)))));
  const clearRoute = () => { if (layerRoute && map) { map.removeLayer(layerRoute); layerRoute = null; } };
  const drawRoute = (pts, color) => {
    clearRoute();
    layerRoute = L.layerGroup().addTo(map);
    L.polyline(pts.map((p) => [p.lat, p.lon]), {color: color || '#2f6fed', weight: 4, opacity: 0.8}).addTo(layerRoute);
    pts.forEach((p, i) => { if (p.n) L.marker([p.lat, p.lon], {icon: pinIcon(L, p.n, p.done ? '#1b9e5a' : '#2f6fed')}).addTo(layerRoute); });
    map.fitBounds(pts.map((p) => [p.lat, p.lon]), {padding: [30, 30]});
  };
  const estimate = async () => {
    const sel = [...selected.values()];
    const start = me ? {lat: me.lat, lon: me.lon} : null;
    const r = await api('POST', '/routes/estimate', {start, stops: sel.map((o) => ({lat: o.lat, lon: o.lon, order_id: o.id})), optimize: true});
    const seq = r.order.map((i, k) => ({o: sel[i], leg: r.legs[start ? k : k - 1] || {km: 0, source: 'estimate'}}));
    plan = {total_km: r.total_km, cost_per_km: r.cost_per_km, transport_cost: r.transport_cost, sequence: seq};
    if (L) drawRoute([...(start ? [start] : []), ...seq.map((s, i) => ({lat: s.o.lat, lon: s.o.lon, n: i + 1}))]);
    redrawPanel();
  };
  const startRoute = async () => {
    if (!plan) await estimate();
    const ids = plan.sequence.map((s) => s.o.id);
    const r = await api('POST', '/routes', {order_ids: ids, start: me ? {lat: me.lat, lon: me.lon} : null, optimize: false, accept: true});
    toast(`${t('route_started')}: ${num(r.planned_km, 1)} km`);
    if (!Tracker.active() && await confirmBox(t('start_tracking_q'))) Tracker.start(r.id);
    else if (Tracker.active()) Tracker.routeId = r.id;
    render();
  };
  const activePanel = () => {
    const stops = active.stops, done = stops.filter((s) => s.arrived_at).length;
    const actual = stops.reduce((a, s) => a + (s.actual_leg_km || 0), 0);
    return h('div', {class: 'card'}, h('div', {class: 'row'}, h('b', {class: 'grow'}, `${t('active_route')} #${active.id}`), h('span', {class: 'badge st-in_progress'}, `${done}/${stops.length}`)),
      h('div', {class: 'muted small'}, `${t('planned_km')}: ${num(active.planned_km, 1)} · ${t('actual_km')}: ${num(actual, 1)}`),
      stops.map((s, i) => h('div', {class: 'stop' + (s.arrived_at ? ' done' : '')},
        h('div', {class: 'row'}, h('span', {class: 'numpin static'}, i + 1), h('a', {class: 'grow', href: '#/order/' + s.order_id}, `#${s.order_id} ${s.title}`),
          s.arrived_at ? h('span', {class: 'muted small'}, `✔ ${num(s.actual_leg_km, 2)} km${s.actual_source === 'tracked' ? ' (GPS)' : ''}`) : h('span', {class: 'muted small'}, `≈ ${num(s.planned_leg_km, 1)} km`)),
        h('div', {class: 'muted small'}, s.address || ''),
        s.arrived_at ? null : h('div', {class: 'actions'},
          h('a', {class: 'btnlink', href: mapLink(s.lat, s.lon), target: '_blank', rel: 'noopener'}, '🧭 ' + t('navigate')),
          h('button', {onclick: guard(async () => {
            const p = await gpsLocate().catch(() => ({lat: s.lat, lon: s.lon, accuracy: null}));
            const r = await api('POST', `/routes/${active.id}/arrive`, {order_id: s.order_id, lat: p.lat, lon: p.lon, accuracy: p.accuracy});
            toast(`${t('arrived')}: ${num(r.stops.find((x) => x.order_id === s.order_id).actual_leg_km, 2)} km`); render(); })}, '📍 ' + t('arrive'))))),
      h('div', {class: 'actions'}, h('button', {class: 'ghost', onclick: guard(async () => {
        const r = await api('POST', `/routes/${active.id}/finish`); if (Tracker.active() && await confirmBox(t('stop_tracking_q'))) Tracker.stop();
        toast(`${t('route_finished')}: ${num(r.actual_km, 1)} km`); render(); })}, '■ ' + t('finish_route'))));
  };
  const refreshMarkers = () => {
    for (const [id, m] of Object.entries(markers)) m.setStyle({weight: selected.has(+id) ? 4 : 1, radius: selected.has(+id) ? 11 : 8, fillOpacity: selected.has(+id) ? 1 : 0.75});
  };

  setTimeout(async () => {      // карта строится после вставки на страницу
    try {
      me = await gpsLocate(true).catch(() => null);
      const c = me || (orders[0] ? {lat: orders[0].lat, lon: orders[0].lon} : defaultCenter());
      map = await drawMap(box, c.lat, c.lon, false, 12);
      L = window.L;
      onLeave(() => { try { map.remove(); } catch (e) { /* уже удалена */ } });
      if (me) L.circleMarker([me.lat, me.lon], {radius: 7, color: '#fff', weight: 2, fillColor: '#1c7ed6', fillOpacity: 1}).addTo(map).bindTooltip(t('you_are_here'));
      for (const o of orders) {
        const m = L.circleMarker([o.lat, o.lon], {radius: 8, color: '#fff', weight: 1, fillColor: STATUS_COLOR[o.status] || '#2f6fed', fillOpacity: 0.75}).addTo(map);
        markers[o.id] = m;
        const pop = h('div', {}, h('b', {}, `#${o.id} ${o.title}`), h('div', {class: 'small'}, o.address || ''), h('div', {class: 'small'}, t('st_' + o.status) + (o.geo_verified ? ' ✔' : '')),
          h('div', {class: 'row'}, h('a', {href: '#/order/' + o.id}, t('open')),
            executor && (o.executor_id == null || o.executor_id === S.me.id) ? h('button', {class: 'small', onclick: () => { selected.has(o.id) ? selected.delete(o.id) : selected.set(o.id, o); plan = null; clearRoute(); refreshMarkers(); redrawPanel(); m.closePopup(); }}, t('select_toggle')) : null));
        m.bindPopup(pop);
      }
      if (active) {
        const pts = [...(active.start ? [active.start] : []), ...active.stops.map((s, i) => ({lat: s.lat, lon: s.lon, n: i + 1, done: !!s.arrived_at}))];
        if (pts.length) drawRoute(pts, '#1b9e5a');
      }
    } catch (e) { box.replaceChildren(h('p', {class: 'muted', style: 'padding:12px'}, t('map_unavailable'))); }
  }, 50);
  redrawPanel();
  return root;
}, [1, 2, 3, 7]);

// ───────────── Сотрудники на карте (администратор) ─────────────
route('staffmap', async () => {
  const box = h('div', {class: 'mapbox big'});
  const list = h('div', {});
  let map = null, L = null, layer = null, trackLayer = null, staff = [];
  const draw = () => {
    list.replaceChildren(table([t('employee'), t('company'), t('phone'), t('last_seen'), ''], staff.map((s) => [
      h('span', {}, h('span', {class: 'dot ' + (s.online ? 'on' : '')}), ' ', personName(s), ' ', roleBadge(s.role)), s.company_name || '',
      s.phone ? h('a', {href: 'tel:' + s.phone}, s.phone) : '-', s.last_seen ? fmtDate(s.last_seen) : t('no_location'),
      s.last_lat != null ? h('button', {class: 'ghost small', onclick: () => { map && map.setView([s.last_lat, s.last_lon], 15); }}, '◎') : ''])));
    if (!map) return;
    if (layer) map.removeLayer(layer);
    layer = L.layerGroup().addTo(map);
    const pts = [];
    for (const s of staff) {
      if (s.last_lat == null) continue;
      pts.push([s.last_lat, s.last_lon]);
      const m = L.circleMarker([s.last_lat, s.last_lon], {radius: 10, color: '#fff', weight: 2, fillColor: s.online ? '#1b9e5a' : '#888', fillOpacity: 0.95}).addTo(layer);
      m.bindPopup(h('div', {}, h('b', {}, personName(s)), h('div', {class: 'small'}, [s.company_name, t(ROLE_KEYS[s.role])].filter(Boolean).join(' · ')),
        h('div', {class: 'small'}, s.last_seen ? fmtDate(s.last_seen) : ''), s.phone ? h('div', {}, h('a', {href: 'tel:' + s.phone}, '📞 ' + s.phone)) : null,
        h('div', {class: 'row'}, h('a', {href: '#/chat'}, '💬 ' + t('chat')), h('button', {class: 'small', onclick: guard(async () => {
          const r = await api('GET', `/tracking/points?user_id=${s.id}&frm=${today()}&to=${today()}`);
          if (trackLayer) map.removeLayer(trackLayer);
          if (r.points.length > 1) { trackLayer = L.polyline(r.points.map((p) => [p.lat, p.lon]), {color: '#e8590c', weight: 4}).addTo(map); map.fitBounds(trackLayer.getBounds(), {padding: [30, 30]}); }
          toast(`${t('track_today')}: ${num(r.distance_km, 1)} km`); })}, t('track_today')))));
    }
    return pts;
  };
  const load = async () => { staff = await api('GET', '/staff'); return draw(); };
  const root = h('div', {}, pageHead(t('staff_map'), back('#/admin', t('admin'))), box, h('div', {class: 'card'}, list));
  setTimeout(async () => {
    try {
      await load();
      const first = staff.find((s) => s.last_lat != null);
      const c = first ? {lat: first.last_lat, lon: first.last_lon} : defaultCenter();
      map = await drawMap(box, c.lat, c.lon, false, 11);
      L = window.L;
      onLeave(() => { try { map.remove(); } catch (e) { /* ok */ } });
      const pts = draw();
      if (pts && pts.length > 1) map.fitBounds(pts, {padding: [40, 40]});
      every(30000, async () => { await load(); });
    } catch (e) { box.replaceChildren(h('p', {class: 'muted', style: 'padding:12px'}, t('map_unavailable'))); await load().catch(() => {}); }
  }, 50);
  return root;
}, [1, 7]);

// ───────────── История маршрутов и километры ─────────────
route('routes', async () => {
  const rows = await api('GET', '/routes');
  const total = rows.reduce((a, r) => a + (r.actual_km || r.planned_km || 0), 0);
  return h('div', {}, pageHead(t('routes'), isAdmin() ? h('button', {class: 'ghost', onclick: guard(() => downloadReport('routes'))}, '⬇ Excel') : null),
    h('p', {class: 'muted'}, `${t('total_km')}: ${num(total, 1)} km`),
    table(['#', t('executor'), t('date'), t('status'), t('stops'), t('planned_km'), t('actual_km')], rows.map((r) => [r.id, r.user_name, fmtDate(r.created_at), r.status === 'active' ? t('route_active') : t('route_done'),
      r.stops.length, num(r.planned_km, 1), r.actual_km != null ? num(r.actual_km, 1) : '-']), {numCols: [4, 5, 6]}));
}, [1, 3, 7]);
