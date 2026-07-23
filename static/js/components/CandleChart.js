import { html, useState, useEffect, useRef } from "../vendor.js";
import { api } from "../api.js";
import { fmt } from "../format.js";

// 1-minute mini candlestick chart for the selected group's spot symbol,
// fed by the local DXLink candle relay (/api/candles). Supports wheel zoom
// (centered on cursor), drag pan, and double-click reset — the view window
// is {n visible bars, endOffset bars hidden past the right edge}.
const CANDLE_DEFAULT_N = 75;

export function CandleChart({ symbol }) {
  const [cs, setCs] = useState(null);
  const [view, setView] = useState(null);   // {n, endOffset} or null = default
  const [hoverFrac, setHoverFrac] = useState(null);  // cursor x fraction, 0..1
  const boxRef = useRef(null);
  const viewRef = useRef(null); viewRef.current = view;
  const csRef = useRef(null); csRef.current = cs;

  useEffect(() => {
    if (!symbol) return;
    let alive = true;
    setCs(null); setView(null);
    const load = () => fetch(api(`/api/candles/${encodeURIComponent(symbol)}`))
      .then(r => r.ok ? r.json() : [])
      .then(d => { if (alive) setCs(d); })
      .catch(() => {});
    load();
    const t = setInterval(load, 15000);
    return () => { alive = false; clearInterval(t); };
  }, [symbol]);

  useEffect(() => {
    const el = boxRef.current;
    if (!el) return;
    const total = () => (csRef.current || []).length;
    const cur = () => viewRef.current
      || { n: Math.min(CANDLE_DEFAULT_N, total() || CANDLE_DEFAULT_N), endOffset: 0 };
    const onWheel = e => {
      e.preventDefault();
      const N = total(); if (!N) return;
      const { n, endOffset } = cur();
      const rightIdx = N - endOffset, startIdx = Math.max(0, rightIdx - n);
      const r = el.getBoundingClientRect();
      const f = Math.min(1, Math.max(0, (e.clientX - r.left) / r.width));
      const barUnder = startIdx + f * (rightIdx - startIdx);
      let n2 = Math.round(n * (e.deltaY > 0 ? 1.25 : 0.8));
      n2 = Math.max(10, Math.min(N, n2));
      const eo = Math.max(0, Math.min(N - n2, N - (barUnder - f * n2 + n2)));
      setView({ n: n2, endOffset: Math.round(eo) });
    };
    let drag = null;
    const down = e => { if (e.button !== 0) return;
      drag = { x: e.clientX, view: cur() }; e.preventDefault(); };
    const move = e => {
      if (!drag) return;
      const N = total(); if (!N) return;
      const r = el.getBoundingClientRect();
      const { n, endOffset } = drag.view;
      const dBars = (e.clientX - drag.x) / r.width * n;  // px -> bars, drag right = older
      setView({ n, endOffset: Math.max(0, Math.min(N - n, Math.round(endOffset + dBars))) });
    };
    const up = () => { drag = null; };
    const dbl = () => setView(null);
    el.addEventListener("wheel", onWheel, { passive: false });
    el.addEventListener("mousedown", down);
    el.addEventListener("dblclick", dbl);
    window.addEventListener("mousemove", move);
    window.addEventListener("mouseup", up);
    return () => {
      el.removeEventListener("wheel", onWheel);
      el.removeEventListener("mousedown", down);
      el.removeEventListener("dblclick", dbl);
      window.removeEventListener("mousemove", move);
      window.removeEventListener("mouseup", up);
    };
  }, []);

  if (!cs) return html`<div class="candlebox" ref=${boxRef}><div class="candle-empty">loading candles…</div></div>`;
  if (!cs.length) return html`<div class="candlebox" ref=${boxRef}><div class="candle-empty">no intraday data</div></div>`;
  const v = view || { n: Math.min(CANDLE_DEFAULT_N, cs.length), endOffset: 0 };
  const rightIdx = cs.length - v.endOffset, startIdx = Math.max(0, rightIdx - v.n);
  const bars = cs.slice(startIdx, rightIdx);
  if (!bars.length) return html`<div class="candlebox" ref=${boxRef}><div class="candle-empty">no intraday data</div></div>`;
  const lo = Math.min(...bars.map(b => b.l)), hi = Math.max(...bars.map(b => b.h));
  const H = 120, bw = 7, W = bars.length * bw, padY = 10;
  const span = hi - lo || 1;
  const y = p => H - padY - (p - lo) / span * (H - 2 * padY);
  const yPct = p => y(p) / H * 100;
  const last = bars[bars.length - 1];
  const chg = (last.c - bars[0].o) / (bars[0].o || 1) * 100;
  const hm = t => { const d = new Date(t);
    return String(d.getHours()).padStart(2, "0") + ":" + String(d.getMinutes()).padStart(2, "0"); };
  const yTicks = [hi, lo + span / 2, lo];
  const nx = Math.min(4, bars.length);
  const xTicks = Array.from({ length: nx }, (_, k) =>
    Math.round(k * (bars.length - 1) / (nx - 1 || 1)));
  const hi_ = hoverFrac == null ? null
    : Math.max(0, Math.min(bars.length - 1, Math.floor(hoverFrac * bars.length)));
  const hb = hi_ == null ? null : bars[hi_];
  const onHover = e => {
    const r = boxRef.current.getBoundingClientRect();
    setHoverFrac(Math.min(1, Math.max(0, (e.clientX - r.left) / r.width)));
  };
  return html`
    <div class="candlebox" ref=${boxRef}
         onMouseMove=${onHover} onMouseLeave=${() => setHoverFrac(null)}>
      <svg viewBox=${`0 0 ${W} ${H}`} preserveAspectRatio="none">
        ${bars.map((b, i) => {
          const cx = i * bw + bw / 2, up = b.c >= b.o, col = up ? "#2dd4a7" : "#ff5d73";
          return html`<g key=${b.t}>
            <line x1=${cx} x2=${cx} y1=${y(b.h)} y2=${y(b.l)} stroke=${col} />
            <rect x=${cx - 2.5} width="5" y=${y(Math.max(b.o, b.c))}
                  height=${Math.max(1, Math.abs(y(b.o) - y(b.c)))} fill=${col} />
          </g>`;})}
        ${hb ? html`<line x1=${hi_ * bw + bw / 2} x2=${hi_ * bw + bw / 2}
              y1=${0} y2=${H} stroke="#8b97a8" stroke-width="0.6" stroke-dasharray="3 3" />` : null}
      </svg>
      ${yTicks.map((p, i) => html`
        <div key=${"y" + i} class="cax y" style=${{top: yPct(p) + "%"}}>${fmt(p, 2)}</div>`)}
      ${xTicks.map(i => html`
        <div key=${"x" + i} class="cax x"
             style=${{left: (i + 0.5) / bars.length * 100 + "%", top: "90%"}}>${hm(bars[i].t)}</div>`)}
      ${hb ? html`<div class="chair-tag"
             style=${{left: Math.min(92, Math.max(8, (hi_ + 0.5) / bars.length * 100)) + "%"}}>
             <b>${fmt(hb.c)}</b> · ${hm(hb.t)}</div>` : null}
      <div class="cinfo">${symbol} · 1m · <b>${fmt(last.c)}</b>
        <span class="num ${chg >= 0 ? 'pos' : 'neg'}"> ${chg >= 0 ? '+' : ''}${fmt(chg, 2)}%</span></div>
    </div>`;
}
