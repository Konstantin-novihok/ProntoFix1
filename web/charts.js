/*
 * Графики и диаграммы по всем заказам (без внешних библиотек, чистый SVG).
 *
 *  Что откладывается по оси X («разрез»):  время (час / день недели), дата, неделя, месяц, компания заказчика, исполнитель,
 *                                           компания исполнителя, вид услуги, направление, статус, занятость.
 *  Что считается («показатель»):            число заказов, выручка, себестоимость, маржа, материалы, транспорт, оплата исполнителям,
 *                                           часы, километры, средняя оценка, остаток предоплаты, внесено и списано предоплаты.
 *  Виды:  комбинированный, столбцы, столбцы с накоплением, горизонтальные столбцы, линия, область, круговая, кольцевая,
 *         «зависимость» (точки: один показатель против другого + линия тренда + коэффициент корреляции r).
 *  Наложение: можно добавить сколько угодно слоёв (показателей) на один график; для каждого — вид, ось (левая/правая) и ЦВЕТ из палитры.
 *  Настройки можно сохранять и загружать (пресеты).
 */
'use strict';

const DIMS = ['month', 'week', 'date', 'weekday', 'hour', 'client_company', 'executor', 'executor_company', 'service_type', 'department', 'status', 'employment'];
const TIME_DIMS = ['month', 'week', 'date', 'weekday', 'hour'];
const MEASURES = {
  count: {agg: 'count'}, price: {agg: 'sum', money: 1}, cost: {agg: 'sum', money: 1}, margin: {agg: 'sum', money: 1}, materials: {agg: 'sum', money: 1},
  transport: {agg: 'sum', money: 1}, pay: {agg: 'sum', money: 1}, hours: {agg: 'sum'}, km: {agg: 'sum'}, rating: {agg: 'avg'},
  prepay_balance: {client: 'balance', money: 1}, prepaid_total: {client: 'prepaid_total', money: 1}, charged_total: {client: 'charged_total', money: 1},
};
const CHART_TYPES = ['combo', 'bar', 'stacked', 'hbar', 'line', 'area', 'pie', 'donut', 'scatter'];
const FILTERS = [['client_company', 'dim_client_company'], ['executor', 'dim_executor'], ['executor_company', 'dim_executor_company'], ['service_type', 'dim_service_type'],
  ['department', 'dim_department'], ['status', 'dim_status'], ['employment', 'dim_employment']];
const PALETTE = ['#2f6fed', '#e8590c', '#1b9e5a', '#8e44ad', '#e03131', '#0b7285', '#f08c00', '#5f3dc4'];

const dimLabel = (dim, v) => dim === 'weekday' ? t('wd_' + v) : dim === 'hour' ? `${String(v).padStart(2, '0')}:00` : dim === 'status' ? t('st_' + v)
  : dim === 'employment' ? (v === 'external' ? t('emp_external') : v === 'internal' ? t('emp_internal') : v) : String(v);
const fmtMeasure = (m, v) => v == null ? '–' : MEASURES[m] && MEASURES[m].money ? money(v) : num(v, 2);

function shade(hex, i, n) {   // оттенки выбранного цвета для секторов круговой диаграммы
  const c = parseInt(hex.slice(1), 16), k = n <= 1 ? 0 : i / (n - 1);
  const mix = (v) => Math.round(v + (255 - v) * (k * 0.65 - 0.1 * (1 - k)));
  const r = Math.max(0, Math.min(255, mix((c >> 16) & 255))), g = Math.max(0, Math.min(255, mix((c >> 8) & 255))), b = Math.max(0, Math.min(255, mix(c & 255)));
  return '#' + [r, g, b].map((x) => x.toString(16).padStart(2, '0')).join('');
}
function niceScale(min, max, ticks = 5) {
  if (!isFinite(min) || !isFinite(max)) { min = 0; max = 1; }
  if (min === max) { max = min + 1; }
  const span = max - min, step0 = span / ticks, mag = Math.pow(10, Math.floor(Math.log10(step0))), norm = step0 / mag;
  const step = (norm >= 5 ? 10 : norm >= 2 ? 5 : norm >= 1 ? 2 : 1) * mag;
  const lo = Math.floor(min / step) * step, hi = Math.ceil(max / step) * step, out = [];
  for (let v = lo; v <= hi + step / 2; v += step) out.push(Math.round(v / step) * step);
  return {min: lo, max: hi, ticks: out};
}
function pearson(xs, ys) {
  const p = xs.map((x, i) => [x, ys[i]]).filter(([a, b]) => a != null && b != null && isFinite(a) && isFinite(b));
  const n = p.length;
  if (n < 3) return null;
  const mx = p.reduce((a, [x]) => a + x, 0) / n, my = p.reduce((a, [, y]) => a + y, 0) / n;
  let sxy = 0, sxx = 0, syy = 0;
  for (const [x, y] of p) { sxy += (x - mx) * (y - my); sxx += (x - mx) ** 2; syy += (y - my) ** 2; }
  return sxx && syy ? sxy / Math.sqrt(sxx * syy) : null;
}

// ───────────── Агрегация ─────────────
function aggregate(ds, cfg) {
  const f = cfg.filters || {};
  const rows = ds.orders.filter((r) => FILTERS.every(([k]) => !f[k] || String(r[k]) === f[k]));
  const dim = cfg.x;
  const groups = new Map();
  for (const r of rows) { const k = r[dim]; if (!groups.has(k)) groups.set(k, []); groups.get(k).push(r); }
  const usesClient = cfg.layers.some((l) => MEASURES[l.measure] && MEASURES[l.measure].client);
  const clientByCompany = new Map();
  if (usesClient && dim === 'client_company') {
    for (const c of ds.clients) { if (f.client_company && c.company !== f.client_company) continue; clientByCompany.set(c.company, (clientByCompany.get(c.company) || []).concat(c)); if (!groups.has(c.company)) groups.set(c.company, []); }
  }
  const value = (measure, rowsOf, key) => {
    const m = MEASURES[measure];
    if (!m) return null;
    if (m.client) return dim === 'client_company' ? (clientByCompany.get(key) || []).reduce((a, c) => a + c[m.client], 0) : null;
    if (m.agg === 'count') return rowsOf.length;
    if (m.agg === 'avg') { const v = rowsOf.map((r) => r[measure]).filter((x) => x != null); return v.length ? v.reduce((a, b) => a + b, 0) / v.length : null; }
    const key2 = measure === 'materials' || measure === 'transport' ? measure : measure;
    return rowsOf.reduce((a, r) => a + (Number(r[key2]) || 0), 0);
  };
  let keys = [...groups.keys()];
  if (TIME_DIMS.includes(dim)) keys.sort((a, b) => (typeof a === 'number' ? a - b : String(a).localeCompare(String(b))));
  else {
    const first = cfg.layers[0];
    keys.sort((a, b) => (value(first.measure, groups.get(b), b) || 0) - (value(first.measure, groups.get(a), a) || 0));
    if (cfg.top > 0) keys = keys.slice(0, cfg.top);
  }
  return {keys, labels: keys.map((k) => dimLabel(dim, k)), series: cfg.layers.map((l) => keys.map((k) => value(l.measure, groups.get(k) || [], k)))};
}

// ───────────── Рисование ─────────────
const W = 760, H = 380;
function emptyChart(msg) { return svg('svg', {viewBox: `0 0 ${W} 120`, class: 'chart'}, svg('text', {x: W / 2, y: 60, 'text-anchor': 'middle', fill: 'var(--muted)'}, msg)); }

function cartesian(cfg, agg, hidden) {
  const layers = cfg.layers.map((l, i) => ({...l, i, vals: agg.series[i], hide: hidden.has(i)})).filter((l) => !l.hide);
  if (!layers.length || !agg.keys.length) return emptyChart(t('no_data'));
  const kindOf = (l) => cfg.type === 'bar' || cfg.type === 'stacked' ? 'bar' : cfg.type === 'line' ? 'line' : cfg.type === 'area' ? 'area' : l.kind || 'bar';
  const hasRight = layers.some((l) => l.axis === 'right') && cfg.type === 'combo';
  const M = {l: 64, r: hasRight ? 64 : 16, t: 16, b: agg.keys.length > 8 ? 92 : 56};
  const iw = W - M.l - M.r, ih = H - M.t - M.b;
  const stacked = cfg.type === 'stacked';
  const axisOf = (l) => (hasRight && l.axis === 'right' ? 'right' : 'left');
  const range = (axis) => {
    const ls = layers.filter((l) => axisOf(l) === axis);
    let mn = 0, mx = 0;
    if (stacked && axis === 'left') {
      agg.keys.forEach((_, k) => { let pos = 0, neg = 0; ls.forEach((l) => { const v = l.vals[k] || 0; v >= 0 ? pos += v : neg += v; }); mx = Math.max(mx, pos); mn = Math.min(mn, neg); });
    } else ls.forEach((l) => l.vals.forEach((v) => { if (v != null) { mx = Math.max(mx, v); mn = Math.min(mn, v); } }));
    return niceScale(mn, mx);
  };
  const sc = {left: range('left'), right: hasRight ? range('right') : null};
  const yOf = (axis, v) => M.t + ih - ((v - sc[axis].min) / (sc[axis].max - sc[axis].min)) * ih;
  const band = iw / agg.keys.length, cx = (k) => M.l + band * k + band / 2;
  const root = svg('svg', {viewBox: `0 0 ${W} ${H}`, class: 'chart', role: 'img'});
  for (const v of sc.left.ticks) {
    const y = yOf('left', v);
    root.append(svg('line', {x1: M.l, x2: W - M.r, y1: y, y2: y, stroke: 'var(--line)', 'stroke-width': v === 0 ? 1.5 : 1}), svg('text', {x: M.l - 6, y: y + 4, 'text-anchor': 'end', fill: 'var(--muted)', 'font-size': 11}, num(v, 2)));
  }
  if (hasRight) for (const v of sc.right.ticks) root.append(svg('text', {x: W - M.r + 6, y: yOf('right', v) + 4, fill: 'var(--muted)', 'font-size': 11}, num(v, 2)));
  const step = Math.ceil(agg.keys.length / 24);
  agg.labels.forEach((lb, k) => {
    if (k % step) return;
    const txt = svg('text', {x: cx(k), y: H - M.b + 16, 'text-anchor': agg.keys.length > 8 ? 'end' : 'middle', fill: 'var(--muted)', 'font-size': 11,
      transform: agg.keys.length > 8 ? `rotate(-40 ${cx(k)} ${H - M.b + 16})` : null}, lb.length > 16 ? lb.slice(0, 15) + '…' : lb);
    root.append(txt);
  });
  const bars = layers.filter((l) => kindOf(l) === 'bar');
  const nb = stacked ? 1 : bars.length;
  const bw = Math.max(3, Math.min(60, (band * 0.78) / Math.max(1, nb)));
  const posAcc = agg.keys.map(() => 0), negAcc = agg.keys.map(() => 0);
  bars.forEach((l, bi) => {
    l.vals.forEach((v, k) => {
      if (v == null) return;
      const ax = axisOf(l);
      let y0, y1;
      if (stacked) { if (v >= 0) { y0 = yOf(ax, posAcc[k]); posAcc[k] += v; y1 = yOf(ax, posAcc[k]); } else { y0 = yOf(ax, negAcc[k]); negAcc[k] += v; y1 = yOf(ax, negAcc[k]); } }
      else { y0 = yOf(ax, 0); y1 = yOf(ax, v); }
      const x = stacked ? cx(k) - bw / 2 : cx(k) - (bw * nb) / 2 + bi * bw;
      root.append(svg('rect', {x, y: Math.min(y0, y1), width: bw - 1, height: Math.max(1, Math.abs(y1 - y0)), fill: l.color, rx: 2}, svg('title', {}, `${agg.labels[k]} — ${t('ms_' + l.measure)}: ${fmtMeasure(l.measure, v)}`)));
    });
  });
  layers.filter((l) => kindOf(l) !== 'bar').forEach((l) => {
    const ax = axisOf(l), pts = l.vals.map((v, k) => v == null ? null : [cx(k), yOf(ax, v), v, k]);
    const segs = []; let cur = [];
    pts.forEach((p) => { if (p) cur.push(p); else if (cur.length) { segs.push(cur); cur = []; } }); if (cur.length) segs.push(cur);
    for (const sg of segs) {
      const d = sg.map((p, i) => (i ? 'L' : 'M') + p[0].toFixed(1) + ' ' + p[1].toFixed(1)).join(' ');
      if (kindOf(l) === 'area') root.append(svg('path', {d: `${d} L${sg[sg.length - 1][0]} ${yOf(ax, 0)} L${sg[0][0]} ${yOf(ax, 0)} Z`, fill: l.color, opacity: 0.22}));
      root.append(svg('path', {d, fill: 'none', stroke: l.color, 'stroke-width': 2.5, 'stroke-linejoin': 'round'}));
    }
    pts.forEach((p) => p && root.append(svg('circle', {cx: p[0], cy: p[1], r: 3.6, fill: l.color, stroke: 'var(--card)', 'stroke-width': 1}, svg('title', {}, `${agg.labels[p[3]]} — ${t('ms_' + l.measure)}: ${fmtMeasure(l.measure, p[2])}`))));
  });
  return root;
}

function horizontal(cfg, agg, hidden) {
  const layers = cfg.layers.map((l, i) => ({...l, vals: agg.series[i], hide: hidden.has(i)})).filter((l) => !l.hide);
  if (!layers.length || !agg.keys.length) return emptyChart(t('no_data'));
  const rowH = 14 * layers.length + 12, Hh = Math.max(160, agg.keys.length * rowH + 40), M = {l: 150, r: 20, t: 10, b: 28};
  const iw = W - M.l - M.r;
  let mx = 0, mn = 0; layers.forEach((l) => l.vals.forEach((v) => { if (v != null) { mx = Math.max(mx, v); mn = Math.min(mn, v); } }));
  const s = niceScale(mn, mx), xOf = (v) => M.l + ((v - s.min) / (s.max - s.min)) * iw;
  const root = svg('svg', {viewBox: `0 0 ${W} ${Hh}`, class: 'chart'});
  for (const v of s.ticks) root.append(svg('line', {x1: xOf(v), x2: xOf(v), y1: M.t, y2: Hh - M.b, stroke: 'var(--line)'}), svg('text', {x: xOf(v), y: Hh - 10, 'text-anchor': 'middle', fill: 'var(--muted)', 'font-size': 11}, num(v, 2)));
  agg.keys.forEach((_, k) => {
    const y0 = M.t + k * rowH;
    const lb = agg.labels[k];
    root.append(svg('text', {x: M.l - 8, y: y0 + rowH / 2, 'text-anchor': 'end', fill: 'var(--text)', 'font-size': 12}, lb.length > 22 ? lb.slice(0, 21) + '…' : lb));
    layers.forEach((l, li) => { const v = l.vals[k]; if (v == null) return;
      root.append(svg('rect', {x: Math.min(xOf(0), xOf(v)), y: y0 + li * 14, width: Math.max(1, Math.abs(xOf(v) - xOf(0))), height: 12, fill: l.color, rx: 2}, svg('title', {}, `${lb} — ${t('ms_' + l.measure)}: ${fmtMeasure(l.measure, v)}`))); });
  });
  return root;
}

function pie(cfg, agg, donut) {
  const l = cfg.layers[0], data = agg.keys.map((_, k) => ({label: agg.labels[k], v: Math.max(0, agg.series[0][k] || 0)})).filter((d) => d.v > 0);
  const total = data.reduce((a, d) => a + d.v, 0);
  if (!total) return emptyChart(t('no_data'));
  const root = svg('svg', {viewBox: `0 0 ${W} 330`, class: 'chart'}), cx = 190, cy = 165, R = 140, r0 = donut ? 78 : 0;
  let a0 = -Math.PI / 2;
  data.forEach((d, i) => {
    const a1 = a0 + (d.v / total) * Math.PI * 2, large = a1 - a0 > Math.PI ? 1 : 0;
    const p = (a, r) => [cx + Math.cos(a) * r, cy + Math.sin(a) * r];
    const [x0, y0] = p(a0, R), [x1, y1] = p(a1, R), [x2, y2] = p(a1, r0), [x3, y3] = p(a0, r0);
    const full = d.v === total;
    const path = full ? `M${cx - R} ${cy} a${R} ${R} 0 1 0 ${2 * R} 0 a${R} ${R} 0 1 0 ${-2 * R} 0` + (donut ? ` M${cx - r0} ${cy} a${r0} ${r0} 0 1 1 ${2 * r0} 0 a${r0} ${r0} 0 1 1 ${-2 * r0} 0` : '')
      : `M${x0} ${y0} A${R} ${R} 0 ${large} 1 ${x1} ${y1} ` + (donut ? `L${x2} ${y2} A${r0} ${r0} 0 ${large} 0 ${x3} ${y3} Z` : `L${cx} ${cy} Z`);
    root.append(svg('path', {d: path, fill: shade(l.color, i, data.length), stroke: 'var(--card)', 'stroke-width': 2, 'fill-rule': 'evenodd'}, svg('title', {}, `${d.label}: ${fmtMeasure(l.measure, d.v)} (${(d.v / total * 100).toFixed(1)}%)`)));
    a0 = a1;
  });
  if (donut) root.append(svg('text', {x: cx, y: cy - 2, 'text-anchor': 'middle', fill: 'var(--text)', 'font-size': 20, 'font-weight': 700}, fmtMeasure(l.measure, total)), svg('text', {x: cx, y: cy + 18, 'text-anchor': 'middle', fill: 'var(--muted)', 'font-size': 12}, t('ms_' + l.measure)));
  data.slice(0, 14).forEach((d, i) => {
    const y = 30 + i * 21;
    root.append(svg('rect', {x: 380, y: y - 11, width: 14, height: 14, fill: shade(l.color, i, data.length), rx: 3}),
      svg('text', {x: 402, y, fill: 'var(--text)', 'font-size': 12}, `${d.label.length > 26 ? d.label.slice(0, 25) + '…' : d.label} — ${(d.v / total * 100).toFixed(1)}%`));
  });
  return root;
}

function scatter(cfg, agg, hidden) {
  if (cfg.layers.length < 2) return emptyChart(t('need_two_layers'));
  const [A, B] = cfg.layers, xs = agg.series[0], ys = agg.series[1];
  const pts = xs.map((x, k) => [x, ys[k], k]).filter((p) => p[0] != null && p[1] != null);
  if (pts.length < 2) return emptyChart(t('no_data'));
  const M = {l: 64, r: 20, t: 16, b: 48}, iw = W - M.l - M.r, ih = H - M.t - M.b;
  const sx = niceScale(Math.min(0, ...pts.map((p) => p[0])), Math.max(...pts.map((p) => p[0]))), sy = niceScale(Math.min(0, ...pts.map((p) => p[1])), Math.max(...pts.map((p) => p[1])));
  const X = (v) => M.l + ((v - sx.min) / (sx.max - sx.min)) * iw, Y = (v) => M.t + ih - ((v - sy.min) / (sy.max - sy.min)) * ih;
  const root = svg('svg', {viewBox: `0 0 ${W} ${H}`, class: 'chart'});
  for (const v of sy.ticks) root.append(svg('line', {x1: M.l, x2: W - M.r, y1: Y(v), y2: Y(v), stroke: 'var(--line)'}), svg('text', {x: M.l - 6, y: Y(v) + 4, 'text-anchor': 'end', fill: 'var(--muted)', 'font-size': 11}, num(v, 2)));
  for (const v of sx.ticks) root.append(svg('line', {x1: X(v), x2: X(v), y1: M.t, y2: H - M.b, stroke: 'var(--line)'}), svg('text', {x: X(v), y: H - M.b + 16, 'text-anchor': 'middle', fill: 'var(--muted)', 'font-size': 11}, num(v, 2)));
  root.append(svg('text', {x: M.l + iw / 2, y: H - 8, 'text-anchor': 'middle', fill: A.color, 'font-size': 12, 'font-weight': 700}, t('ms_' + A.measure)),
    svg('text', {x: 14, y: M.t + ih / 2, 'text-anchor': 'middle', fill: B.color, 'font-size': 12, 'font-weight': 700, transform: `rotate(-90 14 ${M.t + ih / 2})`}, t('ms_' + B.measure)));
  const n = pts.length, mx = pts.reduce((a, p) => a + p[0], 0) / n, my = pts.reduce((a, p) => a + p[1], 0) / n;
  let sxx = 0, sxy = 0; pts.forEach((p) => { sxx += (p[0] - mx) ** 2; sxy += (p[0] - mx) * (p[1] - my); });
  if (sxx) { const b = sxy / sxx, a = my - b * mx, x0 = sx.min, x1 = sx.max; root.append(svg('line', {x1: X(x0), y1: Y(a + b * x0), x2: X(x1), y2: Y(a + b * x1), stroke: 'var(--muted)', 'stroke-dasharray': '6 5', 'stroke-width': 2})); }
  pts.forEach((p) => root.append(svg('circle', {cx: X(p[0]), cy: Y(p[1]), r: 6, fill: B.color, opacity: 0.8, stroke: A.color, 'stroke-width': 2}, svg('title', {}, `${agg.labels[p[2]]}\n${t('ms_' + A.measure)}: ${fmtMeasure(A.measure, p[0])}\n${t('ms_' + B.measure)}: ${fmtMeasure(B.measure, p[1])}`))));
  return root;
}

// ───────────── Экран ─────────────
const defaultConfig = () => ({x: 'month', type: 'combo', top: 12, from: daysAgo(180), to: today(), filters: {},
  layers: [{measure: 'price', kind: 'bar', color: PALETTE[0], axis: 'left'}, {measure: 'margin', kind: 'line', color: PALETTE[1], axis: 'left'}]});

route('analytics', async () => {
  let cfg = Object.assign(defaultConfig(), (() => { try { return JSON.parse(ls.get('hm_chart') || 'null') || {}; } catch (e) { return {}; } })());
  if (!cfg.layers || !cfg.layers.length) cfg.layers = defaultConfig().layers;
  let ds = await api('GET', `/analytics/dataset?frm=${cfg.from}&to=${cfg.to}`);
  let presets = await api('GET', '/analytics/presets').catch(() => []);
  const hidden = new Set();
  const out = h('div', {class: 'out'}), ctl = h('div', {class: 'ctl'});
  const save = () => ls.set('hm_chart', JSON.stringify(cfg));

  const draw = () => {
    save();
    const agg = aggregate(ds, cfg);
    const chart = cfg.type === 'hbar' ? horizontal(cfg, agg, hidden) : cfg.type === 'pie' ? pie(cfg, agg, false) : cfg.type === 'donut' ? pie(cfg, agg, true)
      : cfg.type === 'scatter' ? scatter(cfg, agg, hidden) : cartesian(cfg, agg, hidden);
    const legend = h('div', {class: 'legend'}, cfg.layers.map((l, i) => h('span', {class: 'lg' + (hidden.has(i) ? ' off' : ''), onclick: () => { hidden.has(i) ? hidden.delete(i) : hidden.add(i); draw(); }},
      h('i', {style: `background:${l.color}`}), `${t('ms_' + l.measure)}${cfg.type === 'combo' && l.axis === 'right' ? ' ▶' : ''}`)));
    // зависимости: коэффициент корреляции между слоями
    const corr = [];
    for (let i = 0; i < cfg.layers.length; i++) for (let j = i + 1; j < cfg.layers.length; j++) {
      const r = pearson(agg.series[i], agg.series[j]);
      if (r != null) corr.push(h('div', {class: 'corr'}, h('i', {style: `background:${cfg.layers[i].color}`}), h('i', {style: `background:${cfg.layers[j].color}`}),
        ` ${t('ms_' + cfg.layers[i].measure)} ↔ ${t('ms_' + cfg.layers[j].measure)}: `, h('b', {}, `r = ${r.toFixed(2)}`), ` — ${t(Math.abs(r) >= 0.7 ? 'corr_strong' : Math.abs(r) >= 0.4 ? 'corr_medium' : 'corr_weak')}${r < 0 ? ', ' + t('corr_inverse') : ''}`));
    }
    const rows = agg.keys.map((_, k) => [agg.labels[k], ...cfg.layers.map((l, i) => fmtMeasure(l.measure, agg.series[i][k]))]);
    const csv = () => {
      const esc = (x) => `"${String(x).replace(/"/g, '""')}"`;
      const lines = [[t('dim_' + cfg.x), ...cfg.layers.map((l) => t('ms_' + l.measure))].map(esc).join(';'), ...agg.keys.map((_, k) => [agg.labels[k], ...cfg.layers.map((l, i) => agg.series[i][k] ?? '')].map(esc).join(';'))];
      return saveBlob(new Blob(['\ufeff' + lines.join('\n')], {type: 'text/csv'}), `chart_${cfg.x}_${today()}.csv`, 'text/csv');
    };
    out.replaceChildren(h('div', {class: 'card'}, chart, legend, ...corr),
      h('div', {class: 'row', style: 'margin:8px 0'}, h('b', {class: 'grow'}, t('chart_table')), h('button', {class: 'ghost small', onclick: guard(csv)}, '⬇ CSV')),
      table([t('dim_' + cfg.x), ...cfg.layers.map((l) => t('ms_' + l.measure))], rows, {numCols: cfg.layers.map((_, i) => i + 1)}));
  };

  const uniq = (k) => [...new Set(ds.orders.map((r) => r[k]))].sort().map(String);
  const drawControls = () => {
    const type = selectEl(CHART_TYPES.map((c) => ({value: c, label: t('ct_' + c)})), cfg.type, {onchange: (e) => { cfg.type = e.target.value; drawControls(); draw(); }});
    const x = selectEl(DIMS.map((d) => ({value: d, label: t('dim_' + d)})), cfg.x, {onchange: (e) => { cfg.x = e.target.value; draw(); }});
    const top = h('input', {type: 'number', min: 0, value: cfg.top, style: 'max-width:90px', onchange: (e) => { cfg.top = parseInt(e.target.value) || 0; draw(); }});
    const from = h('input', {type: 'date', value: cfg.from}), to = h('input', {type: 'date', value: cfg.to});
    const refetch = guard(async () => { cfg.from = from.value; cfg.to = to.value; ds = await api('GET', `/analytics/dataset?frm=${cfg.from}&to=${cfg.to}`); drawControls(); draw(); });
    from.onchange = refetch; to.onchange = refetch;
    const layersBox = h('div', {}, cfg.layers.map((l, i) => h('div', {class: 'layer'},
      h('input', {type: 'color', value: l.color, title: t('color'), oninput: (e) => { l.color = e.target.value; draw(); }}),
      selectEl(Object.keys(MEASURES).map((m) => ({value: m, label: t('ms_' + m)})), l.measure, {onchange: (e) => { l.measure = e.target.value; draw(); }}),
      cfg.type === 'combo' ? selectEl(['bar', 'line', 'area'].map((k) => ({value: k, label: t('lk_' + k)})), l.kind || 'bar', {onchange: (e) => { l.kind = e.target.value; draw(); }}) : null,
      cfg.type === 'combo' ? selectEl([{value: 'left', label: t('axis_left')}, {value: 'right', label: t('axis_right')}], l.axis || 'left', {onchange: (e) => { l.axis = e.target.value; draw(); }}) : null,
      cfg.layers.length > 1 ? h('button', {class: 'ghost small', onclick: () => { cfg.layers.splice(i, 1); hidden.clear(); drawControls(); draw(); }}, '✕') : null)));
    const filters = h('details', {class: 'card'}, h('summary', {}, t('filters') + (Object.values(cfg.filters).some(Boolean) ? ' ●' : '')),
      h('div', {class: 'filters'}, FILTERS.map(([k, label]) => fieldBox(label, selectEl([{value: '', label: t('all')}, ...uniq(k).map((v) => ({value: v, label: dimLabel(k, v)}))], cfg.filters[k] || '',
        {onchange: (e) => { cfg.filters[k] = e.target.value; draw(); drawControls(); }})))));
    const presetSel = selectEl([{value: '', label: '— ' + t('presets') + ' —'}, ...presets.map((p) => ({value: p.id, label: p.name}))], '', {onchange: (e) => {
      const p = presets.find((x) => String(x.id) === e.target.value); if (p) { cfg = Object.assign(defaultConfig(), JSON.parse(JSON.stringify(p.config))); hidden.clear(); refetch(); } }});
    ctl.replaceChildren(h('div', {class: 'card'}, h('div', {class: 'filters'}, fieldBox('chart_type', type), fieldBox('chart_x', x), cfg.type !== 'combo' || true ? fieldBox('top_n', top) : null, fieldBox('from', from), fieldBox('to', to)),
      h('h2', {style: 'margin-top:12px'}, t('layers') + ' (' + t('layers_hint') + ')'), layersBox,
      h('div', {class: 'row'}, h('button', {class: 'ghost small', onclick: () => { cfg.layers.push({measure: 'count', kind: 'line', color: PALETTE[cfg.layers.length % PALETTE.length], axis: cfg.layers.length ? 'right' : 'left'}); drawControls(); draw(); }}, '+ ' + t('add_layer')),
        presetSel,
        h('button', {class: 'ghost small', onclick: guard(async () => { const v = await formModal(t('save_preset'), [{key: 'name', label: 'name'}]); if (!v || !v.name.trim()) return;
          const p = await api('POST', '/analytics/presets', {name: v.name, config: cfg}); presets = await api('GET', '/analytics/presets'); drawControls(); toast(t('saved')); })}, '💾 ' + t('save_preset')),
        h('button', {class: 'ghost small', onclick: guard(async () => { const id = presetSel.value; if (!id) return; await api('DELETE', '/analytics/presets/' + id); presets = await api('GET', '/analytics/presets'); drawControls(); })}, '🗑'))), filters);
  };
  drawControls(); draw();
  return h('div', {class: 'analytics'}, pageHead(t('analytics'), isAdmin() ? back('#/admin', t('admin')) : null), h('p', {class: 'muted small'}, t('analytics_hint')), ctl, out);
}, [1, 2, 6, 7]);
