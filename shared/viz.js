/* House chart toolkit. Shared by every demo in this repo so the whole set reads
   as one system: same scales, same marks, same tooltip, same validated palette.
   Exposed as window.V; each demo destructures what it needs. */
window.V = (() => {
"use strict";
const NS = "http://www.w3.org/2000/svg";
const $ = s => document.querySelector(s);
const el = (t, a = {}, kids = []) => { const e = document.createElementNS(NS, t);
  for (const k in a) if (a[k] !== null && a[k] !== undefined) e.setAttribute(k, a[k]);
  for (const c of [].concat(kids)) e.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
  return e; };
const tok = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();

/* ---------- formatting: deal-desk conventions ---------- */
const MINUS = "−";
const m2 = v => (v < 0 ? MINUS : "") + "£" + (Math.abs(v) / 1e6).toFixed(2) + "m";
const m2s = v => (v < 0 ? MINUS : "+") + "£" + (Math.abs(v) / 1e6).toFixed(2) + "m";
const m1 = v => (v < 0 ? MINUS : "") + "£" + (Math.abs(v) / 1e6).toFixed(1) + "m";
const acct = (v, d = 2) => v < 0 ? "(" + (Math.abs(v) / 1e6).toFixed(d) + ")" : (v / 1e6).toFixed(d);
const pc = (v, d = 1) => (v * 100).toFixed(d) + "%";
const pcs = (v, d = 1) => (v < 0 ? MINUS : "+") + (Math.abs(v) * 100).toFixed(d) + "%";
const pp = (v, d = 1) => (v < 0 ? MINUS : "+") + (Math.abs(v) * 100).toFixed(d) + "pp";
const int = v => Math.round(v).toLocaleString("en-GB");

/* ---------- tooltip ---------- */
const tip = $("#tip");
function showTip(e, title, rows) {
  tip.innerHTML = '<div class="t"></div>' + rows.map(() => '<div class="r"><span></span><span></span></div>').join("");
  tip.querySelector(".t").textContent = title;
  tip.querySelectorAll(".r").forEach((r, i) => {
    r.children[0].textContent = rows[i][0]; r.children[1].textContent = rows[i][1];
  });
  tip.style.opacity = 1; moveTip(e);
}
function moveTip(e) {
  const b = tip.getBoundingClientRect();
  let x = e.clientX + 14, y = e.clientY - b.height - 12;
  if (x + b.width > innerWidth - 8) x = e.clientX - b.width - 14;
  if (y < 8) y = e.clientY + 18;
  tip.style.left = x + "px"; tip.style.top = y + "px";
}
const hideTip = () => { tip.style.opacity = 0; };
function hit(target, title, rows) {
  target.addEventListener("mouseenter", e => showTip(e, title, rows));
  target.addEventListener("mousemove", moveTip);
  target.addEventListener("mouseleave", hideTip);
}

/* ---------- scales & axes ---------- */
const lin = (d0, d1, r0, r1) => v => r0 + (v - d0) / (d1 - d0) * (r1 - r0);
function niceTicks(lo, hi, n = 5) {
  const raw = (hi - lo) / n, mag = Math.pow(10, Math.floor(Math.log10(raw)));
  const step = [1, 1.5, 2, 2.5, 3, 4, 5, 7.5, 10].map(x => x * mag).find(x => x >= raw) || 10 * mag;
  const out = []; for (let t = Math.ceil(lo / step) * step; t <= hi + 1e-9; t += step) out.push(t);
  return out;
}
/** Padded domain first, ticks second. Returns a scale that always contains the data. */
function axisScale(lo, hi, r0, r1, o = {}) {
  const span = (hi - lo) || Math.abs(hi) || 1;
  const dlo = lo - span * (o.padLo ?? 0.08), dhi = hi + span * (o.padHi ?? 0.08);
  return { y: lin(dlo, dhi, r0, r1), dlo, dhi,
           ticks: niceTicks(dlo, dhi, o.n ?? 5).filter(t => t >= dlo && t <= dhi) };
}
function gridY(g, ticks, y, x0, x1, fmt) {
  ticks.forEach(t => {
    g.appendChild(el("line", { x1: x0, x2: x1, y1: y(t), y2: y(t), stroke: tok("--rule"), "stroke-width": 1 }));
    g.appendChild(el("text", { x: x0 - 9, y: y(t) + 4, "text-anchor": "end", fill: tok("--ink-3"),
      "font-size": 11, "font-family": "IBM Plex Mono, monospace" }, fmt(t)));
  });
}
function xLabels(g, items, cx, yTop, slot) {
  const rotate = slot < 94;
  items.forEach((s, i) => {
    const x = cx(i);
    if (rotate) {
      const t = el("text", { x: 0, y: 0, "text-anchor": "end", fill: tok("--ink-2"), "font-size": 11 }, s);
      t.setAttribute("transform", `translate(${x},${yTop + 14}) rotate(-40)`); g.appendChild(t);
    } else {
      const words = s.split(" "); const lines = words.length > 2
        ? [words.slice(0, Math.ceil(words.length / 2)).join(" "), words.slice(Math.ceil(words.length / 2)).join(" ")]
        : [s];
      lines.forEach((ln, j) => g.appendChild(el("text", { x, y: yTop + 16 + j * 13, "text-anchor": "middle",
        fill: tok("--ink-2"), "font-size": 11.5 }, ln)));
    }
  });
}

/* ---------- waterfall ---------- */
function waterfall(w, steps, opt = {}) {
  const compact = !!opt.compact;
  const rotate = (w - 66) / steps.length < 94;
  const H = opt.height || (compact ? 250 : Math.max(330, Math.min(430, w * 0.46)));
  const M = { t: 30, r: 8, b: rotate ? 74 : (compact ? 44 : 52), l: 58 };
  const iw = Math.max(40, w - M.l - M.r), ih = H - M.t - M.b;
  const svg = el("svg", { viewBox: `0 0 ${w} ${H}`, width: w, height: H, role: "img" });
  const g = el("g", { transform: `translate(${M.l},${M.t})` });

  let cum = 0; const bars = steps.map(s => {
    if (s.kind === "total") { cum = s.value; return { ...s, lo: 0, hi: s.value, base: true }; }
    const a = cum, b = cum + s.value; cum = b; return { ...s, lo: Math.min(a, b), hi: Math.max(a, b), end: b };
  });
  const vals = bars.flatMap(b => b.base ? [b.value] : [b.lo, b.hi]);
  const sc = axisScale(Math.min(...vals), Math.max(...vals), ih, 0, { padLo: 0.16, padHi: 0.14, n: 5 });
  const y = sc.y, floor = sc.dlo;
  gridY(g, sc.ticks, y, 0, iw, t => (t / 1e6).toFixed(0));
  g.appendChild(el("text", { x: -M.l + 2, y: -12, fill: tok("--ink-3"), "font-size": 10.5,
    "font-weight": 600, "letter-spacing": ".06em" }, "£m"));

  const slot = iw / steps.length, bw = Math.min(slot * 0.6, 62);
  const cx = i => slot * i + slot / 2;

  if (opt.hatch) {
    const defs = el("defs"); const p = el("pattern", { id: opt.hatchId, width: 6, height: 6,
      patternUnits: "userSpaceOnUse", patternTransform: "rotate(45)" });
    p.appendChild(el("rect", { width: 6, height: 6, fill: tok("--surface") }));
    p.appendChild(el("line", { x1: 0, y1: 0, x2: 0, y2: 6, stroke: "currentColor", "stroke-width": 3.4 }));
    defs.appendChild(p); svg.appendChild(defs);
  }

  bars.forEach((b, i) => {
    const x = cx(i) - bw / 2;
    const top = y(b.base ? b.value : b.hi), bot = y(b.base ? floor : b.lo);
    const col = b.base ? tok("--total") : (b.value >= 0 ? tok("--pos") : tok("--neg"));
    const shade = opt.hatch && !b.base && opt.ratings && opt.ratings[b.label] && opt.ratings[b.label] !== "Recurring";
    const h = Math.max(2, bot - top);
    const r = el("rect", { x, y: top, width: bw, height: h, rx: 2.5,
      fill: shade ? `url(#${opt.hatchId})` : col, color: col,
      stroke: shade ? col : "none", "stroke-width": shade ? 1.2 : 0 });
    g.appendChild(r);

    if (i < bars.length - 1) {
      const nx = cx(i + 1) - bw / 2, ly = y(b.base ? b.value : b.end);
      g.appendChild(el("line", { x1: x + bw, x2: nx, y1: ly, y2: ly, stroke: tok("--rule-2"), "stroke-width": 1 }));
    }
    const lab = b.base ? m2(b.value) : m2s(b.value);
    const ly = b.value >= 0 || b.base ? top - 9 : bot + 15;
    g.appendChild(el("text", { x: cx(i), y: ly, "text-anchor": "middle", fill: tok("--ink"),
      "font-size": compact ? 11 : 12, "font-weight": 600, "font-family": "IBM Plex Mono, monospace" }, lab));

    const hitr = el("rect", { x: cx(i) - slot / 2, y: 0, width: slot, height: ih, fill: "transparent" });
    const rows = [[b.base ? "Revenue" : "Movement", lab]];
    if (!b.base) rows.push(["Running total", m2(b.end)]);
    if (opt.ratings && opt.ratings[b.label]) rows.push(["Durability", opt.ratings[b.label]]);
    hit(hitr, b.label, rows);
    if (b.note) hitr.addEventListener("mouseenter", () => {
      const n = document.createElement("div"); n.className = "tiny";
      n.style.cssText = "margin-top:6px;padding-top:6px;border-top:1px solid var(--rule)";
      n.textContent = b.note; tip.appendChild(n);
    });
    g.appendChild(hitr);
  });

  xLabels(g, steps.map(s => s.label), cx, ih, slot);
  svg.appendChild(g); return svg;
}

/* ---------- multi-line chart ---------- */
function lineChart(w, cfg) {
  const H = cfg.height || Math.max(230, Math.min(320, w * 0.5));
  const M = { t: 16, r: cfg.rightPad || 44, b: 34, l: 46 };
  const iw = Math.max(40, w - M.l - M.r), ih = H - M.t - M.b;
  const svg = el("svg", { viewBox: `0 0 ${w} ${H}`, width: w, height: H, role: "img" });
  const g = el("g", { transform: `translate(${M.l},${M.t})` });
  const n = cfg.labels.length;
  const all = cfg.series.flatMap(s => s.values);
  const sc = axisScale(Math.min(...all), Math.max(...all), ih, 0, { n: 4 });
  const y = sc.y;
  const x = i => n === 1 ? iw / 2 : i * (iw / (n - 1));
  gridY(g, sc.ticks, y, 0, iw, cfg.fmtAxis);

  cfg.labels.forEach((l, i) => { if (i % (cfg.every || 1) === 0)
    g.appendChild(el("text", { x: x(i), y: ih + 20, "text-anchor": "middle", fill: tok("--ink-3"), "font-size": 10.5 }, l)); });

  if (cfg.markIndex !== undefined && cfg.markIndex !== null) {
    g.appendChild(el("line", { x1: x(cfg.markIndex), x2: x(cfg.markIndex), y1: 0, y2: ih,
      stroke: tok("--rule-2"), "stroke-width": 1.5 }));
    if (cfg.markLabel) g.appendChild(el("text", { x: x(cfg.markIndex) + 6, y: 11,
      fill: tok("--ink-3"), "font-size": 10.5, "font-weight": 600 }, cfg.markLabel));
  }
  cfg.series.forEach(s => {
    const col = tok(s.token);
    g.appendChild(el("path", { d: s.values.map((v, i) => (i ? "L" : "M") + x(i) + "," + y(v)).join(" "),
      fill: "none", stroke: col, "stroke-width": 2, "stroke-linejoin": "round", "stroke-linecap": "round" }));
    const li = s.values.length - 1;
    g.appendChild(el("circle", { cx: x(li), cy: y(s.values[li]), r: 4, fill: col,
      stroke: tok("--surface"), "stroke-width": 2 }));
    g.appendChild(el("text", { x: x(li) + 9, y: y(s.values[li]) + 4, fill: tok("--ink-2"),
      "font-size": 11, "font-weight": 600, "font-family": "IBM Plex Mono, monospace" }, cfg.fmtEnd(s.values[li])));
  });

  const cross = el("line", { y1: 0, y2: ih, stroke: tok("--rule-2"), "stroke-width": 1, opacity: 0 });
  g.appendChild(cross);
  const dots = cfg.series.map(s => { const c = el("circle", { r: 4.5, fill: tok(s.token),
    stroke: tok("--surface"), "stroke-width": 2, opacity: 0 }); g.appendChild(c); return c; });
  const surface = el("rect", { x: 0, y: 0, width: iw, height: ih, fill: "transparent" });
  surface.addEventListener("mousemove", e => {
    const r = surface.getBoundingClientRect();
    const i = Math.max(0, Math.min(n - 1, Math.round((e.clientX - r.left) / (iw / Math.max(n - 1, 1)))));
    cross.setAttribute("x1", x(i)); cross.setAttribute("x2", x(i)); cross.setAttribute("opacity", 1);
    cfg.series.forEach((s, k) => { dots[k].setAttribute("cx", x(i)); dots[k].setAttribute("cy", y(s.values[i]));
      dots[k].setAttribute("opacity", 1); });
    showTip(e, cfg.labels[i], cfg.series.map(s => [s.name, cfg.fmtEnd(s.values[i])]));
  });
  surface.addEventListener("mouseleave", () => { hideTip(); cross.setAttribute("opacity", 0);
    dots.forEach(d => d.setAttribute("opacity", 0)); });
  g.appendChild(surface);
  svg.appendChild(g); return svg;
}

/* ---------- horizontal bars (signed) ---------- */
function hBars(w, items, cfg) {
  const rowH = cfg.rowH || 40, M = { t: 6, r: 58, b: 22, l: cfg.left || 128 };
  const H = M.t + M.b + items.length * rowH;
  const iw = Math.max(40, w - M.l - M.r);
  const svg = el("svg", { viewBox: `0 0 ${w} ${H}`, width: w, height: H, role: "img" });
  const g = el("g", { transform: `translate(${M.l},${M.t})` });
  const vals = items.map(d => d.value);
  const lo = Math.min(0, ...vals), hi = Math.max(0, ...vals), span = (hi - lo) || 1;
  const x = lin(lo - span * 0.04, hi + span * 0.08, 0, iw);
  const zero = x(0);
  g.appendChild(el("line", { x1: zero, x2: zero, y1: -2, y2: items.length * rowH - 4,
    stroke: tok("--rule-2"), "stroke-width": 1 }));
  items.forEach((d, i) => {
    const yy = i * rowH, bh = Math.min(19, rowH - 16);
    const xa = Math.min(zero, x(d.value)), bw = Math.max(2, Math.abs(x(d.value) - zero));
    const col = tok(d.token || cfg.token || (d.value >= 0 ? "--pos" : "--neg"));
    g.appendChild(el("rect", { x: xa, y: yy + (rowH - bh) / 2 - 4, width: bw, height: bh, rx: 2.5, fill: col }));
    g.appendChild(el("text", { x: -12, y: yy + rowH / 2 + 0, "text-anchor": "end", fill: tok("--ink"),
      "font-size": 12, "font-weight": 500 }, d.label));
    if (d.sub) g.appendChild(el("text", { x: -12, y: yy + rowH / 2 + 13, "text-anchor": "end",
      fill: tok("--ink-3"), "font-size": 10.5 }, d.sub));
    const outside = d.value >= 0 ? xa + bw + 8 : xa - 8;
    const fits = d.value >= 0 ? true : outside > 34;
    g.appendChild(el("text", { x: fits ? outside : xa + 7, y: yy + rowH / 2 + 4,
      "text-anchor": fits ? (d.value >= 0 ? "start" : "end") : "start",
      fill: fits ? tok("--ink") : "#fff", "font-size": 11.5, "font-weight": 600,
      "font-family": "IBM Plex Mono, monospace" }, cfg.fmt(d.value)));
    const hr = el("rect", { x: -M.l, y: yy - 2, width: w - 8, height: rowH, fill: "transparent" });
    hit(hr, d.label, d.rows || [[cfg.valueName || "Value", cfg.fmt(d.value)]]); g.appendChild(hr);
  });
  svg.appendChild(g); return svg;
}

/* ---------- grouped bars ---------- */
function groupBars(w, groups, series, cfg) {
  const H = cfg.height || 260, M = { t: 24, r: 8, b: 42, l: 52 };
  const iw = Math.max(40, w - M.l - M.r), ih = H - M.t - M.b;
  const svg = el("svg", { viewBox: `0 0 ${w} ${H}`, width: w, height: H, role: "img" });
  const g = el("g", { transform: `translate(${M.l},${M.t})` });
  const all = series.flatMap(s => s.values);
  const sc = axisScale(Math.min(0, ...all), Math.max(0, ...all), ih, 0, { n: 4 });
  const y = sc.y;
  gridY(g, sc.ticks, y, 0, iw, cfg.fmtAxis);
  const slot = iw / groups.length, bw = Math.min((slot * 0.68) / series.length, 38);
  groups.forEach((gr, i) => {
    const cx0 = slot * i + slot / 2;
    series.forEach((s, k) => {
      const v = s.values[i];
      const x = cx0 - (bw * series.length + 2 * (series.length - 1)) / 2 + k * (bw + 2);
      const top = Math.min(y(v), y(0)), h = Math.max(2, Math.abs(y(v) - y(0)));
      g.appendChild(el("rect", { x, y: top, width: bw, height: h, rx: 2.5, fill: tok(s.token) }));
      g.appendChild(el("text", { x: x + bw / 2, y: v >= 0 ? top - 7 : top + h + 14, "text-anchor": "middle",
        fill: tok("--ink-2"), "font-size": 10.5, "font-weight": 600,
        "font-family": "IBM Plex Mono, monospace" }, cfg.fmt(v)));
    });
    g.appendChild(el("text", { x: cx0, y: ih + 20, "text-anchor": "middle", fill: tok("--ink-2"), "font-size": 11.5 }, gr));
    const hr = el("rect", { x: slot * i, y: 0, width: slot, height: ih, fill: "transparent" });
    hit(hr, gr, series.map(s => [s.name, cfg.fmt(s.values[i])])); g.appendChild(hr);
  });
  g.appendChild(el("line", { x1: 0, x2: iw, y1: y(0), y2: y(0), stroke: tok("--rule-2"), "stroke-width": 1 }));
  svg.appendChild(g); return svg;
}

/* ---------- dumbbell ---------- */
function dumbbell(w, items, cfg) {
  const rowH = 44, M = { t: 20, r: 22, b: 26, l: cfg.left || 150 };
  const H = M.t + M.b + items.length * rowH;
  const iw = Math.max(40, w - M.l - M.r);
  const svg = el("svg", { viewBox: `0 0 ${w} ${H}`, width: w, height: H, role: "img" });
  const g = el("g", { transform: `translate(${M.l},${M.t})` });
  const all = items.flatMap(d => [d.a, d.b]);
  const sc = axisScale(Math.min(...all), Math.max(...all), 0, iw, { padLo: 0.14, padHi: 0.12, n: 4 });
  const x = sc.y;
  sc.ticks.forEach(t => {
    g.appendChild(el("line", { x1: x(t), x2: x(t), y1: -8, y2: items.length * rowH - 10,
      stroke: tok("--rule"), "stroke-width": 1 }));
    g.appendChild(el("text", { x: x(t), y: items.length * rowH + 8, "text-anchor": "middle",
      fill: tok("--ink-3"), "font-size": 10.5, "font-family": "IBM Plex Mono, monospace" }, pc(t, 0)));
  });
  items.forEach((d, i) => {
    const yy = i * rowH + rowH / 2 - 12, up = d.b >= d.a;
    const col = tok(up ? "--pos" : "--neg");
    g.appendChild(el("line", { x1: x(d.a), x2: x(d.b), y1: yy, y2: yy, stroke: col,
      "stroke-width": 2.5, "stroke-linecap": "round", opacity: .35 }));
    g.appendChild(el("circle", { cx: x(d.a), cy: yy, r: 5, fill: tok("--surface"),
      stroke: tok("--ink-3"), "stroke-width": 2 }));
    g.appendChild(el("circle", { cx: x(d.b), cy: yy, r: 5.5, fill: col, stroke: tok("--surface"), "stroke-width": 2 }));
    g.appendChild(el("text", { x: -12, y: yy + 4, "text-anchor": "end", fill: tok("--ink"), "font-size": 12 }, d.label));
    g.appendChild(el("text", { x: -12, y: yy + 17, "text-anchor": "end", fill: tok("--ink-3"),
      "font-size": 10.5, "font-family": "IBM Plex Mono, monospace" }, d.sub));
    const hr = el("rect", { x: -M.l, y: i * rowH - 8, width: w - 8, height: rowH, fill: "transparent" });
    hit(hr, d.label, d.rows); g.appendChild(hr);
  });
  svg.appendChild(g); return svg;
}

/* ---------- sparkline ---------- */
function spark(w, values, o = {}) {
  const h = o.height || 34, pad = 3;
  const svg = el("svg", { viewBox: `0 0 ${w} ${h}`, width: w, height: h, role: "img",
                          "aria-label": o.label || "trend" });
  const lo = Math.min(...values), hi = Math.max(...values), span = (hi - lo) || 1;
  const x = i => pad + i * (w - 2 * pad) / Math.max(values.length - 1, 1);
  const y = v => h - pad - (v - lo) / span * (h - 2 * pad);
  const d = values.map((v, i) => (i ? "L" : "M") + x(i) + "," + y(v)).join(" ");
  const col = tok(o.token || "--s1");
  svg.appendChild(el("path", { d: `${d} L${x(values.length - 1)},${h} L${x(0)},${h} Z`,
    fill: col, opacity: .12 }));
  svg.appendChild(el("path", { d, fill: "none", stroke: col, "stroke-width": 1.8,
    "stroke-linejoin": "round", "stroke-linecap": "round" }));
  const li = values.length - 1;
  svg.appendChild(el("circle", { cx: x(li), cy: y(values[li]), r: 3, fill: col }));
  return svg;
}

/* ---------- diverging heatmap ---------- */
function heatmap(w, cfg) {
  const cols = cfg.cols, rows = cfg.rows;
  const M = { t: cfg.top || 86, r: 6, b: 6, l: cfg.left || 54 };
  const cw = Math.max(30, (w - M.l - M.r) / cols.length);
  const ch = cfg.cellH || 40;
  const H = M.t + M.b + rows.length * ch;
  const svg = el("svg", { viewBox: `0 0 ${w} ${H}`, width: w, height: H, role: "img" });
  const g = el("g", { transform: `translate(${M.l},${M.t})` });

  cols.forEach((c, j) => {
    const t = el("text", { x: 0, y: 0, "text-anchor": "start", fill: tok("--ink-2"), "font-size": 11 }, c);
    t.setAttribute("transform", `translate(${j * cw + cw / 2 - 4},${-10}) rotate(-42)`);
    g.appendChild(t);
  });
  rows.forEach((r, i) => {
    g.appendChild(el("text", { x: -10, y: i * ch + ch / 2 + 4, "text-anchor": "end",
      fill: tok("--ink"), "font-size": 12, "font-weight": 500 }, r.label));
    cols.forEach((c, j) => {
      const cell = cfg.cell(i, j), x = j * cw + 1, y = i * ch + 1;
      const wd = cw - 2, hd = ch - 2;
      if (cell.d === null || cell.d === undefined) {
        g.appendChild(el("rect", { x, y, width: wd, height: hd, rx: 3, fill: tok("--surface-2") }));
        g.appendChild(el("text", { x: x + wd / 2, y: y + hd / 2 + 4, "text-anchor": "middle",
          fill: tok("--ink-3"), "font-size": 11 }, "—"));
      } else {
        const col = tok(cell.d >= 0 ? "--pos" : "--neg");
        g.appendChild(el("rect", { x, y, width: wd, height: hd, rx: 3, fill: tok("--surface-2") }));
        g.appendChild(el("rect", { x, y, width: wd, height: hd, rx: 3, fill: col,
          opacity: Math.max(0.14, Math.min(1, Math.abs(cell.d))) }));
        if (wd > 44) g.appendChild(el("text", { x: x + wd / 2, y: y + hd / 2 + 4, "text-anchor": "middle",
          fill: Math.abs(cell.d) > 0.55 ? "#fff" : tok("--ink"), "font-size": 10.5, "font-weight": 600,
          "font-family": "IBM Plex Mono, monospace" }, cell.d.toFixed(2)));
      }
      const hr = el("rect", { x, y, width: wd, height: hd, fill: "transparent" });
      hit(hr, cfg.title(i, j), cfg.rowsOf(i, j)); g.appendChild(hr);
    });
  });
  svg.appendChild(g); return svg;
}

/* ---------- legends ---------- */
function legend(id, items) {
  const n = $(id); if (!n) return;
  n.innerHTML = items.map(i => `<span><b style="background:${i.swatch}"></b>${i.name}</span>`).join("");
}

/* ---------- render registry: resize, theme change and font load all redraw ---------- */
const charts = [], after = [];
const reg = (id, fn) => charts.push({ id, fn });
const onRender = fn => after.push(fn);
function render() {
  for (const { id, fn } of charts) {
    const host = document.getElementById(id); if (!host) continue;
    host.replaceChildren(fn(Math.max(260, Math.floor(host.clientWidth))));
  }
  after.forEach(f => f());
}
function boot() {
  render();
  let t; const redraw = () => { clearTimeout(t); t = setTimeout(render, 120); };
  addEventListener("resize", redraw);
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", redraw);
  new MutationObserver(redraw).observe(document.documentElement,
    { attributes: true, attributeFilter: ["data-theme"] });
  if (document.fonts) document.fonts.ready.then(render);
}

return { el, tok, $, MINUS, m2, m2s, m1, acct, pc, pcs, pp, int,
         showTip, moveTip, hideTip, hit, lin, niceTicks, axisScale, gridY, xLabels,
         waterfall, lineChart, hBars, groupBars, dumbbell, heatmap, spark, legend,
         reg, onRender, render, boot };
})();
