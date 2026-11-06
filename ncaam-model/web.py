"""Static web dashboard (docs/index.html) for GitHub Pages.

The page is one self-contained HTML file: data is embedded as JSON and drawn
with a little plain JavaScript, so it works on GitHub Pages and on a phone.
"""
from __future__ import annotations

import json
import math
from datetime import date, datetime
from pathlib import Path

import pandas as pd

import config

TODAY_COLS = [
    ("Time", "Time"), ("T1 Team", "Away"), ("T2 Team", "Home"), ("Line", "Line"),
    ("Books", "Books"), ("Best T1", "Best away"), ("Best T2", "Best home"),
    ("Proj T1 Margin", "Proj away margin"), ("Edge Pick", "Edge pick"), ("Edge Size", "Edge"),
    ("Model T1 Win%", "Model away win"), ("Market T1 Win%", "Market away win"),
    ("Games to Watch", "Watch"), ("Confidence", "Conf."), ("Model Pick", "Model pick"),
]
HIST_COLS = [
    ("date", "Date"), ("pick_type", "Type"), ("t1", "Away"), ("t2", "Home"), ("pick_team", "Pick"),
    ("pick_line", "Line"), ("edge", "Edge"), ("confidence", "Conf."), ("t1_score", "Away pts"),
    ("t2_score", "Home pts"), ("result", "Result"),
]


def _clean(v):
    if v is None:
        return None
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    if isinstance(v, (pd.Timestamp, datetime, date)):
        return str(v)
    if hasattr(v, "item"):
        try:
            return _clean(v.item())
        except Exception:
            return str(v)
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    return v


def _records(df: pd.DataFrame, cols) -> list[list]:
    if df is None or df.empty:
        return []
    have = [c for c, _ in cols]
    out = []
    for _, r in df.iterrows():
        out.append([_clean(r.get(c)) for c in have])
    return out


def build_payload(day: date, results: pd.DataFrame, record: pd.DataFrame, trend: pd.DataFrame,
                  history: pd.DataFrame, books: pd.DataFrame, notes: list[str]) -> dict:
    today = pd.DataFrame()
    if not results.empty and "Edge Size" in results:
        today = results[results["Line"].fillna("") != ""].sort_values("Edge Size", ascending=False, na_position="last")
    hist = history.copy()
    if not hist.empty:
        hist = hist.sort_values(["date", "start"], ascending=[False, True], na_position="last").head(3000)
    return {
        "day": day.strftime("%A, %B %d, %Y").replace(" 0", " "),
        "updated": datetime.now().strftime("%b %d, %Y %I:%M %p ET").replace(" 0", " "),
        "mode": "Legacy Excel" if config.LEGACY_EXCEL_MODE else "Standard",
        "edgeBuckets": list(config.EDGE_BUCKETS),
        "today": {"cols": [h for _, h in TODAY_COLS], "rows": _records(today, TODAY_COLS)},
        "record": {"cols": list(record.columns), "rows": _records(record, [(c, c) for c in record.columns])},
        "trend": {"cols": list(trend.columns), "rows": _records(trend, [(c, c) for c in trend.columns])},
        "history": {"cols": [h for _, h in HIST_COLS], "rows": _records(hist, HIST_COLS)},
        "books": {"cols": list(books.columns), "rows": _records(books, [(c, c) for c in books.columns])},
        "notes": list(notes),
        "games": int(len(results)) if not results.empty else 0,
    }


def write_site(docs: Path, payload: dict) -> Path:
    docs.mkdir(parents=True, exist_ok=True)
    data = json.dumps(payload, default=str).replace("</", "<\\/")
    html = TEMPLATE.replace("__DATA__", data)
    path = docs / "index.html"
    path.write_text(html, encoding="utf-8")
    (docs / ".nojekyll").write_text("", encoding="utf-8")
    return path


TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>NCAAM Model</title>
<meta name="robots" content="noindex">
<style>
:root{
  color-scheme:light;
  --bg:#f6f6f4; --surface:#fcfcfb; --surface-2:#f0efeb; --border:#e2e1dc;
  --text:#0b0b0b; --text-2:#52514e; --muted:#7a7974;
  --accent:#2a78d6; --series-1:#2a78d6; --grid:#e6e5e0;
  --good:#0f7b3d; --good-bg:#e3f4e9; --bad:#b42318; --bad-bg:#fbe9e7;
  --warn-bg:#fff4d6; --chip:#eceae4;
}
@media (prefers-color-scheme:dark){
  :root:where(:not([data-theme="light"])){
    color-scheme:dark;
    --bg:#121211; --surface:#1a1a19; --surface-2:#232321; --border:#33332f;
    --text:#f0efec; --text-2:#c3c2b7; --muted:#8f8e86;
    --accent:#3987e5; --series-1:#3987e5; --grid:#2c2c29;
    --good:#5cc98a; --good-bg:#16301f; --bad:#f08b80; --bad-bg:#3a1d1a;
    --warn-bg:#3a3214; --chip:#2a2a27;
  }
}
:root[data-theme="dark"]{
  color-scheme:dark;
  --bg:#121211; --surface:#1a1a19; --surface-2:#232321; --border:#33332f;
  --text:#f0efec; --text-2:#c3c2b7; --muted:#8f8e86;
  --accent:#3987e5; --series-1:#3987e5; --grid:#2c2c29;
  --good:#5cc98a; --good-bg:#16301f; --bad:#f08b80; --bad-bg:#3a1d1a;
  --warn-bg:#3a3214; --chip:#2a2a27;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font:15px/1.45 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
.wrap{max-width:1180px;margin:0 auto;padding:20px 16px 48px}
header{display:flex;flex-wrap:wrap;gap:8px 16px;align-items:baseline;justify-content:space-between}
h1{font-size:22px;margin:0}
.sub{color:var(--text-2);font-size:13px}
nav{display:flex;gap:4px;margin:18px 0 14px;overflow-x:auto;border-bottom:1px solid var(--border)}
nav button{background:none;border:0;border-bottom:2px solid transparent;color:var(--text-2);font:inherit;font-weight:600;padding:10px 12px;cursor:pointer;white-space:nowrap}
nav button[aria-selected="true"]{color:var(--text);border-bottom-color:var(--accent)}
section[hidden]{display:none}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin-bottom:16px}
.tile{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:12px 14px}
.tile .k{color:var(--text-2);font-size:12px;text-transform:uppercase;letter-spacing:.04em}
.tile .v{font-size:24px;font-weight:700;margin-top:2px;font-variant-numeric:tabular-nums}
.tile .s{color:var(--muted);font-size:12px}
.card{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:14px;margin-bottom:16px}
.card h2{font-size:15px;margin:0 0 10px}
.controls{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-bottom:10px}
select,input[type=search]{background:var(--surface-2);color:var(--text);border:1px solid var(--border);border-radius:8px;padding:7px 10px;font:inherit;font-size:14px}
input[type=search]{min-width:0;flex:1 1 180px}
.tbl{overflow-x:auto;border:1px solid var(--border);border-radius:8px}
table{border-collapse:collapse;width:100%;font-size:13px;font-variant-numeric:tabular-nums}
th,td{padding:7px 10px;text-align:left;white-space:nowrap;border-bottom:1px solid var(--border)}
th{position:sticky;top:0;background:var(--surface-2);color:var(--text-2);font-weight:600;cursor:pointer;user-select:none}
td.n,th.n{text-align:right}
tbody tr:hover{background:var(--surface-2)}
.chip{display:inline-block;padding:1px 8px;border-radius:999px;font-size:12px;font-weight:600;background:var(--chip)}
.W{background:var(--good-bg);color:var(--good)} .L{background:var(--bad-bg);color:var(--bad)}
.hi{background:var(--good-bg);color:var(--good)} .md{background:var(--warn-bg)}
.indent{padding-left:22px;color:var(--text-2)}
.chart{position:relative}
.chart svg{display:block;width:100%;height:auto}
.tip{position:absolute;pointer-events:none;background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:6px 9px;font-size:12px;box-shadow:0 4px 14px rgba(0,0,0,.15);display:none;white-space:nowrap}
.empty{color:var(--muted);padding:18px 4px}
footer{color:var(--muted);font-size:12px;margin-top:22px}
footer ul{margin:6px 0 0;padding-left:18px}
a{color:var(--accent)}
.theme{background:none;border:1px solid var(--border);color:var(--text-2);border-radius:8px;padding:4px 10px;font:inherit;font-size:12px;cursor:pointer}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div><h1>NCAAM Model</h1><div class="sub" id="day"></div></div>
    <div class="sub"><span id="updated"></span> &nbsp;<button class="theme" id="theme">Theme</button></div>
  </header>
  <nav role="tablist">
    <button role="tab" aria-selected="true" data-tab="today">Today</button>
    <button role="tab" aria-selected="false" data-tab="rate">Success Rate</button>
    <button role="tab" aria-selected="false" data-tab="history">History</button>
    <button role="tab" aria-selected="false" data-tab="books">Odds by Book</button>
  </nav>

  <section id="today">
    <div class="tiles" id="todayTiles"></div>
    <div class="controls">
      <label class="sub" for="edgeMin">Show edges of at least</label>
      <select id="edgeMin"></select>
      <input type="search" id="todaySearch" placeholder="Search team">
    </div>
    <div class="tbl" id="todayTbl"></div>
    <p class="sub">Away = T1, Home = T2. Edge = projected margin vs the line (points). Win % columns are for the away team.</p>
  </section>

  <section id="rate" hidden>
    <div class="tiles" id="rateTiles"></div>
    <div class="card"><h2>Cumulative success rate, sportsbook edge picks</h2>
      <div class="chart" id="chart"></div>
      <p class="sub">Dashed line = 52.4%, break-even against the spread at -110.</p>
    </div>
    <div class="card"><h2>Record by pick type</h2><div class="tbl" id="recordTbl"></div></div>
    <div class="card"><h2>Edge picks by day</h2><div class="tbl" id="trendTbl"></div></div>
  </section>

  <section id="history" hidden>
    <div class="controls">
      <select id="histType"><option value="">All pick types</option><option>Edge</option><option>Market</option><option>Watch</option><option>Model</option></select>
      <select id="histRes"><option value="">All results</option><option>W</option><option>L</option><option>P</option><option value="pending">Pending</option></select>
      <input type="search" id="histSearch" placeholder="Search team or date">
    </div>
    <div class="tbl" id="histTbl"></div>
  </section>

  <section id="books" hidden>
    <div class="controls"><input type="search" id="bookSearch" placeholder="Search team or book"></div>
    <div class="tbl" id="bookTbl"></div>
  </section>

  <footer>
    <div><a href="NCAAM_Dashboard.xlsx">Download the Excel dashboard</a> &middot; <a href="pick_history.csv">Pick history (CSV)</a></div>
    <div id="mode"></div>
    <ul id="notes"></ul>
  </footer>
</div>

<script id="payload" type="application/json">__DATA__</script>
<script>
(function(){
const D = JSON.parse(document.getElementById('payload').textContent);
const $ = id => document.getElementById(id);
const el = (tag, props, kids) => { const e = document.createElement(tag); if (props) Object.assign(e, props); (kids||[]).forEach(k => e.append(k)); return e; };
const isNum = v => typeof v === 'number' && isFinite(v);
const pct = v => isNum(v) ? (v*100).toFixed(1) + '%' : '';
const sgn = v => isNum(v) ? (v > 0 ? '+' : '') + (Math.round(v*10)/10).toFixed(1) : '';

// theme toggle
const root = document.documentElement;
try { const t = localStorage.getItem('theme'); if (t) root.dataset.theme = t; } catch(e) {}
$('theme').onclick = () => {
  const dark = root.dataset.theme ? root.dataset.theme === 'dark' : matchMedia('(prefers-color-scheme: dark)').matches;
  root.dataset.theme = dark ? 'light' : 'dark';
  try { localStorage.setItem('theme', root.dataset.theme); } catch(e) {}
  drawChart();
};

$('day').textContent = D.day;
$('updated').textContent = 'Updated ' + D.updated;
$('mode').textContent = 'Model mode: ' + D.mode;
D.notes.forEach(n => $('notes').append(el('li', {textContent: n})));

// tabs
document.querySelectorAll('nav button').forEach(b => b.onclick = () => {
  document.querySelectorAll('nav button').forEach(x => x.setAttribute('aria-selected', x === b));
  document.querySelectorAll('section').forEach(s => s.hidden = s.id !== b.dataset.tab);
  if (b.dataset.tab === 'rate') drawChart();
  try { localStorage.setItem('tab', b.dataset.tab); } catch(e) {}
});
try { const t = localStorage.getItem('tab'); if (t) { const b = document.querySelector('nav button[data-tab="'+t+'"]'); if (b) b.click(); } } catch(e) {}

// generic sortable table
function table(host, cols, rows, fmt) {
  host.replaceChildren();
  if (!rows.length) { host.append(el('div', {className: 'empty', textContent: 'Nothing to show yet.'})); return; }
  let sortI = -1, dir = 1;
  const numCol = cols.map((_, i) => rows.some(r => isNum(r[i])) && rows.every(r => r[i] == null || isNum(r[i])));
  const t = el('table'), thead = el('thead'), tb = el('tbody'), hr = el('tr');
  cols.forEach((c, i) => {
    const th = el('th', {textContent: c, className: numCol[i] ? 'n' : ''});
    th.onclick = () => { dir = sortI === i ? -dir : (numCol[i] ? -1 : 1); sortI = i; body(); };
    hr.append(th);
  });
  thead.append(hr); t.append(thead, tb); host.append(t);
  function body() {
    const rs = rows.slice();
    if (sortI >= 0) rs.sort((a, b) => {
      const x = a[sortI], y = b[sortI];
      if (x == null) return 1; if (y == null) return -1;
      return (x > y ? 1 : x < y ? -1 : 0) * dir;
    });
    tb.replaceChildren(...rs.map(r => {
      const tr = el('tr');
      r.forEach((v, i) => {
        const td = el('td', {className: numCol[i] ? 'n' : ''});
        const out = fmt ? fmt(cols[i], v, r) : null;
        if (out instanceof Node) td.append(out); else td.textContent = out != null ? out : (v == null ? '' : String(v));
        tr.append(td);
      });
      return tr;
    }));
  }
  body();
}
const chip = (text, cls) => el('span', {className: 'chip ' + (cls || ''), textContent: text});

// ---------- Today
const T = D.today, ti = name => T.cols.indexOf(name);
const buckets = D.edgeBuckets.length ? D.edgeBuckets : [0, 2, 4, 6];
buckets.forEach(b => $('edgeMin').append(el('option', {value: b, textContent: b === 0 ? 'Any edge' : b + '+ pts'})));
if (buckets.length > 1) $('edgeMin').value = buckets[1];
const strong = T.rows.filter(r => isNum(r[ti('Edge')]) && r[ti('Edge')] >= (buckets[1] || 2)).length;
const big = T.rows.filter(r => isNum(r[ti('Edge')]) && r[ti('Edge')] >= (buckets[2] || 4)).length;
const watch = T.rows.filter(r => r[ti('Watch')] === 'YES').length;
[['Games', D.games, 'on the ESPN slate'], ['With a line', T.rows.length, 'priced by books'],
 ['Edges ' + (buckets[1] || 2) + '+ pts', strong, (big) + ' at ' + (buckets[2] || 4) + '+ pts'],
 ['Games to Watch', watch, 'original screen']].forEach(([k, v, s]) =>
  $('todayTiles').append(el('div', {className: 'tile'}, [el('div', {className: 'k', textContent: k}), el('div', {className: 'v', textContent: v}), el('div', {className: 's', textContent: s})])));
function fmtToday(c, v) {
  if (v == null) return '';
  if (c === 'Edge') return chip(v.toFixed(1), v >= (buckets[2] || 4) ? 'hi' : v >= (buckets[1] || 2) ? 'md' : '');
  if (c === 'Conf.') return v ? chip(v, v === 'High' ? 'hi' : v === 'Medium' ? 'md' : '') : '';
  if (c === 'Watch') return v === 'YES' ? chip('YES', 'md') : '';
  if (c.indexOf('win') >= 0) return pct(v);
  if (c.indexOf('margin') >= 0 || c.indexOf('Best') === 0) return sgn(v);
  return null;
}
function drawToday() {
  const min = +$('edgeMin').value, q = $('todaySearch').value.trim().toLowerCase();
  const rows = T.rows.filter(r => (min === 0 || (isNum(r[ti('Edge')]) && r[ti('Edge')] >= min)) &&
    (!q || (String(r[ti('Away')]) + ' ' + String(r[ti('Home')])).toLowerCase().includes(q)));
  table($('todayTbl'), T.cols, rows, fmtToday);
}
$('edgeMin').onchange = drawToday; $('todaySearch').oninput = drawToday; drawToday();

// ---------- Success rate
const R = D.record, ri = n => R.cols.indexOf(n);
function recRow(label) { return R.rows.find(r => String(r[0]).trim() === label); }
const e = recRow('Sportsbook Edge (all)') || [], m = recRow('Market Edge (all, straight up)') || [];
const tile = (k, v, s) => $('rateTiles').append(el('div', {className: 'tile'}, [el('div', {className: 'k', textContent: k}), el('div', {className: 'v', textContent: v}), el('div', {className: 's', textContent: s})]));
tile('Edge record', e.length ? e[ri('W')] + '-' + e[ri('L')] + '-' + e[ri('P')] : '0-0-0', 'W-L-P against the spread');
tile('Edge success', pct(e[ri('Success Rate')]) || 'n/a', 'break-even 52.4%');
tile('Edge units', isNum(e[ri('Units')]) ? (e[ri('Units')] > 0 ? '+' : '') + e[ri('Units')].toFixed(2) : 'n/a', '1 unit per pick at -110');
tile('Market picks', m.length ? m[ri('W')] + '-' + m[ri('L')] : '0-0', (isNum(m[ri('Success Rate')]) ? pct(m[ri('Success Rate')]) + ' ' : '') + 'straight up');
table($('recordTbl'), R.cols, R.rows, (c, v, r) => {
  if (c === 'Pick Type') { const s = String(v); return el('span', {className: s.startsWith('  ') ? 'indent' : '', textContent: s.trim()}); }
  if (c === 'Success Rate') return pct(v);
  if (c === 'Units') return isNum(v) ? (v > 0 ? '+' : '') + v.toFixed(2) : '';
  return null;
});
table($('trendTbl'), D.trend.cols, D.trend.rows.slice().reverse(), (c, v) => (c.indexOf('Rate') >= 0 ? pct(v) : null));

function drawChart() {
  const host = $('chart'); host.replaceChildren();
  const tc = D.trend.cols, rows = D.trend.rows, di = tc.indexOf('Date'), ci = tc.indexOf('Cum Rate'), wi = tc.indexOf('Cum W'), li = tc.indexOf('Cum L');
  const pts = rows.filter(r => isNum(r[ci]));
  if (pts.length < 2) { host.append(el('div', {className: 'empty', textContent: 'The chart appears after two days of graded edge picks.'})); return; }
  const W = Math.max(host.clientWidth || 640, 300), H = 240, pad = {l: 44, r: 14, t: 12, b: 28};
  const cs = getComputedStyle(document.documentElement), col = n => cs.getPropertyValue(n).trim();
  const ys = pts.map(p => p[ci]).concat([0.524]);
  let lo = Math.max(0, Math.floor((Math.min(...ys) - 0.05) * 10) / 10), hi = Math.min(1, Math.ceil((Math.max(...ys) + 0.05) * 10) / 10);
  const x = i => pad.l + i * (W - pad.l - pad.r) / (pts.length - 1), y = v => pad.t + (hi - v) * (H - pad.t - pad.b) / (hi - lo);
  const NS = 'http://www.w3.org/2000/svg', s = document.createElementNS(NS, 'svg');
  s.setAttribute('viewBox', '0 0 ' + W + ' ' + H); s.setAttribute('role', 'img');
  s.setAttribute('aria-label', 'Cumulative success rate of edge picks by day');
  const add = (tag, at) => { const n = document.createElementNS(NS, tag); for (const k in at) n.setAttribute(k, at[k]); s.append(n); return n; };
  for (let v = lo; v <= hi + 1e-9; v += 0.1) {
    add('line', {x1: pad.l, x2: W - pad.r, y1: y(v), y2: y(v), stroke: col('--grid'), 'stroke-width': 1});
    add('text', {x: pad.l - 6, y: y(v) + 4, 'text-anchor': 'end', 'font-size': 11, fill: col('--muted')}).textContent = Math.round(v * 100) + '%';
  }
  add('line', {x1: pad.l, x2: W - pad.r, y1: y(0.524), y2: y(0.524), stroke: col('--text-2'), 'stroke-width': 1, 'stroke-dasharray': '4 4'});
  const step = Math.ceil(pts.length / 6);
  pts.forEach((p, i) => { if (i % step === 0 || i === pts.length - 1) add('text', {x: x(i), y: H - 8, 'text-anchor': 'middle', 'font-size': 11, fill: col('--muted')}).textContent = String(p[di]).slice(5); });
  add('path', {d: pts.map((p, i) => (i ? 'L' : 'M') + x(i) + ' ' + y(p[ci])).join(' '), fill: 'none', stroke: col('--series-1'), 'stroke-width': 2, 'stroke-linejoin': 'round', 'stroke-linecap': 'round'});
  const last = pts.length - 1;
  add('circle', {cx: x(last), cy: y(pts[last][ci]), r: 4, fill: col('--series-1'), stroke: col('--surface'), 'stroke-width': 2});
  const hair = add('line', {y1: pad.t, y2: H - pad.b, stroke: col('--text-2'), 'stroke-width': 1, visibility: 'hidden'});
  const dot = add('circle', {r: 4, fill: col('--series-1'), stroke: col('--surface'), 'stroke-width': 2, visibility: 'hidden'});
  const tip = el('div', {className: 'tip'});
  host.append(s, tip);
  const hit = add('rect', {x: pad.l, y: 0, width: W - pad.l - pad.r, height: H, fill: 'transparent'});
  const show = ev => {
    const b = s.getBoundingClientRect(), px = (ev.clientX - b.left) * W / b.width;
    const i = Math.max(0, Math.min(last, Math.round((px - pad.l) / ((W - pad.l - pad.r) / last)))), p = pts[i];
    hair.setAttribute('x1', x(i)); hair.setAttribute('x2', x(i)); hair.setAttribute('visibility', 'visible');
    dot.setAttribute('cx', x(i)); dot.setAttribute('cy', y(p[ci])); dot.setAttribute('visibility', 'visible');
    tip.replaceChildren(el('div', {textContent: p[di]}), el('div', {textContent: 'Cumulative ' + pct(p[ci]) + ' (' + p[wi] + '-' + p[li] + ')'}));
    tip.style.display = 'block';
    const left = x(i) * b.width / W;
    tip.style.left = Math.min(left + 10, b.width - tip.offsetWidth - 4) + 'px'; tip.style.top = '8px';
  };
  hit.addEventListener('pointermove', show); hit.addEventListener('pointerdown', show);
  hit.addEventListener('pointerleave', () => { tip.style.display = 'none'; hair.setAttribute('visibility', 'hidden'); dot.setAttribute('visibility', 'hidden'); });
}
addEventListener('resize', () => { if (!$('rate').hidden) drawChart(); });
if (!$('rate').hidden) drawChart();

// ---------- History
const Hh = D.history, hi_ = n => Hh.cols.indexOf(n);
function drawHist() {
  const ty = $('histType').value, rs = $('histRes').value, q = $('histSearch').value.trim().toLowerCase();
  const rows = Hh.rows.filter(r => (!ty || r[hi_('Type')] === ty) &&
    (!rs || (rs === 'pending' ? !r[hi_('Result')] : r[hi_('Result')] === rs)) &&
    (!q || r.join(' ').toLowerCase().includes(q)));
  table($('histTbl'), Hh.cols, rows, (c, v, r) => {
    if (c === 'Result') return v ? chip(v, v === 'W' ? 'W' : v === 'L' ? 'L' : '') : chip('Pending');
    if (c === 'Line') return isNum(v) ? (v > 0 ? '+' : '') + v : '';
    if (c === 'Edge') return isNum(v) ? (r[hi_('Type')] === 'Market' ? pct(v) : v.toFixed(1)) : '';
    return null;
  });
}
['histType', 'histRes'].forEach(i => $(i).onchange = drawHist); $('histSearch').oninput = drawHist; drawHist();

// ---------- Books
function drawBooks() {
  const q = $('bookSearch').value.trim().toLowerCase();
  table($('bookTbl'), D.books.cols, D.books.rows.filter(r => !q || r.join(' ').toLowerCase().includes(q)),
    (c, v) => (c.indexOf('Line') >= 0 ? sgn(v) : null));
}
$('bookSearch').oninput = drawBooks; drawBooks();
})();
</script>
</body>
</html>
"""
