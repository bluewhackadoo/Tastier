import { html, Fragment, useState, useEffect, useMemo, useRef,
         ResponsiveContainer, ComposedChart, Line, Area, XAxis, YAxis,
         Tooltip, Customized } from "../vendor.js";
import { fmt, money } from "../format.js";
import { DTE_SHADES } from "../scale.js";
import { useDividerDrag } from "../hooks.js";
import { TickerLogo } from "./TickerLogo.js";
import { TVTicker } from "./TVTicker.js";
import { ChartTip } from "./ChartTip.js";
import { chartOverlay } from "./chartOverlay.js";
import { PositionTable } from "./PositionTable.js";
import { AdvisorPanel } from "./AdvisorPanel.js";

export function Analysis({ ana, stale, sel, account, hidden, onToggle }) {
  const data = useMemo(() => ana.grid.map((s, i) => ({
    spot: s, exp: ana.expiration_pl[i], t0: ana.t0_pl[i],
    theta: (ana.theta || [])[i] ?? 0,
    expPos: Math.max(ana.expiration_pl[i], 0),
    expNeg: Math.min(ana.expiration_pl[i], 0),
    ...Object.fromEntries((ana.curves || []).flatMap((c, j) => {
      const expVal = ana.expiration_pl[i];
      const cVal = c.pl[i];
      const cPos = Math.max(cVal, 0);
      return [
        ["c" + j, cVal],
        ["cPos" + j, cPos],
        ["cFill" + j, expVal > 0 ? cPos : 0],
      ];
    })),
  })), [ana]);
  // Linear vertical scale based on the largest absolute expiration P/L so the
  // green/red expiration lines stay aligned through the center strip.  yZoom
  // (mousewheel over the right-hand P/L axis) scales the whole Y axis.
  const [yZoom, setYZoom] = useState(1);
  useEffect(() => setYZoom(1), [sel]);
  // Single linear vertical scale based on the largest absolute expiration P/L.
  // This keeps the green/red expiration lines aligned (same slope through zero)
  // like the tastytrade payoff chart.  T+0 and other DTE curves may overflow.
  const scales = useMemo(() => {
    const m = Math.max(ana.max_profit, -ana.max_loss, 1);
    return { pos: m, neg: m };
  }, [ana]);
  const tf = v => (v >= 0 ? v / scales.pos : v / scales.neg) * 0.9 * yZoom;
  const plotData = useMemo(() => data.map(d => ({
    ...d,   // originals stay for the tooltip
    pExpPos: tf(d.expPos), pExpNeg: tf(d.expNeg), pT0: tf(d.t0),
    ...Object.fromEntries((ana.curves || []).flatMap((c, j) => [
      ["pC" + j, tf(d["c" + j])],
      ["pCFill" + j, tf(d["cFill" + j])],
    ])),
  })), [data, scales, yZoom]);

  // x-axis zoom (wheel, centered on cursor) and pan (drag); dblclick resets
  const [view, setView] = useState(null);           // [lo, hi] or null = full
  const chartRef = useRef(null);
  const viewRef = useRef(null); viewRef.current = view;
  const fullRef = useRef([0, 1]);
  fullRef.current = [ana.grid[0], ana.grid[ana.grid.length - 1]];
  useEffect(() => setView(null), [sel]);
  useEffect(() => {
    const el = chartRef.current;
    if (!el) return;
    const PAD = 12 + 12;  // #chart padding + chart margin
    const clamp = (lo, hi) => {
      const [flo, fhi] = fullRef.current, span = hi - lo;
      if (lo < flo) { lo = flo; hi = flo + span; }
      if (hi > fhi) { hi = fhi; lo = fhi - span; }
      return (hi - lo) >= (fhi - flo) - 1e-9 ? null : [Math.max(flo, lo), Math.min(fhi, hi)];
    };
    const onWheel = e => {
      e.preventDefault();
      const r = el.getBoundingClientRect();
      if (e.clientX > r.right - 70) {
        // over the right-hand P/L axis: zoom the vertical scale instead
        setYZoom(z => Math.min(8, Math.max(0.25, z * (e.deltaY > 0 ? 1 / 1.15 : 1.15))));
        return;
      }
      const [flo, fhi] = fullRef.current;
      const [lo, hi] = viewRef.current || [flo, fhi];
      const frac = Math.min(1, Math.max(0, (e.clientX - r.left - PAD) / (r.width - 2 * PAD)));
      const p = lo + frac * (hi - lo);
      const f = e.deltaY > 0 ? 1.25 : 0.8;
      let nlo = p - (p - lo) * f, nhi = p + (hi - p) * f;
      const minSpan = (fhi - flo) * 0.04;
      if (nhi - nlo < minSpan) { const c = (nlo + nhi) / 2; nlo = c - minSpan / 2; nhi = c + minSpan / 2; }
      setView(clamp(nlo, nhi));
    };
    let drag = null;
    const down = e => { if (e.button !== 0) return;
      drag = { x: e.clientX, view: viewRef.current || fullRef.current.slice() };
      el.style.cursor = "grabbing"; e.preventDefault(); };
    const move = e => {
      if (!drag) return;
      const r = el.getBoundingClientRect();
      const [lo, hi] = drag.view;
      const dP = (e.clientX - drag.x) / (r.width - 2 * PAD) * (hi - lo);
      setView(clamp(lo - dP, hi - dP));
    };
    const up = () => { drag = null; el.style.cursor = ""; };
    const dbl = () => { setView(null); setYZoom(1); };
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

  const [topbarH, setTopbarH] = useState(200);
  const [chartH, setChartH] = useState(480);
  const [topleftW, setTopleftW] = useState(320);
  const dragTopbar  = useDividerDrag('y', d => setTopbarH(h => Math.max(80, h + d)));
  const dragChart   = useDividerDrag('y', d => setChartH(h => Math.max(120, h + d)));
  const dragTopleft = useDividerDrag('x', d => setTopleftW(w => Math.max(120, w + d)));

  const pct = ana.net_open_cost ? ana.live_pl / Math.abs(ana.net_open_cost) * 100 : null;
  const sv = (v, txt) => html`<span class="num ${v>0?'pos':v<0?'neg':''}">${txt}</span>`;
  const cell = (k, v) => html`<div class="scell"><div class="k">${k}</div><div class="v">${v}</div></div>`;
  const candleSym = ana.legs?.[0]?.underlying_streamer || sel;
  const logoSym = (sel || "").replace(/^\//, "");
  return html`
    <div class="rstack">
      <div class="topbar" style=${{height: topbarH + "px"}}>
        <div class="topleft" style=${{flex: `0 0 ${topleftW}px`}}>
          <div class="syminfo">
            <${TickerLogo} key=${logoSym} sym=${logoSym} size=${30} />
            <span class="symname">${sel}</span>
            ${ana.description ? html`<span class="symdesc">${ana.description}</span>` : ''}
          </div>
          <div class="sumgrid">
            ${cell("Live P/L", sv(ana.live_pl, money(ana.live_pl)))}
            ${cell("P/L Opn%", pct == null ? "—" : sv(pct, fmt(pct, 1) + "%"))}
            ${cell("P/L Day", ana.pl_day == null ? "—" : sv(ana.pl_day, money(ana.pl_day)))}
            ${cell("Spot", html`${fmt(ana.spot)}${stale ? html`<span class="stale">stale</span>` : ''}`)}
            ${cell("Max Profit", sv(1, money(ana.max_profit)))}
            ${cell("Max Loss", sv(-1, money(ana.max_loss)))}
            ${cell("Breakevens", ana.breakevens.map(b => fmt(b, 1)).join("/") || "—")}
          </div>
        </div>
        <div class="vdivider" onMouseDown=${dragTopleft}></div>
        <${TVTicker} symbol=${candleSym} sel=${sel} />
      </div>
      <div class="hdivider" onMouseDown=${dragTopbar}></div>
      <div id="chart" ref=${chartRef} style=${{height: chartH + "px"}}>
        ${!(ana.legs || []).length ? html`
          <div class="candle-empty" style=${{height: "100%"}}>
            all strategies hidden — click a group row below to show one
          </div>` : html`
        <${ResponsiveContainer} width="100%" height="100%">
          <${ComposedChart} data=${plotData} margin=${{top:28,right:12,bottom:28,left:12}}>
            <${XAxis} dataKey="spot" hide=${true} type="number"
                      allowDataOverflow=${!!view}
                      domain=${view ?? ["dataMin", "dataMax"]} />
            <${YAxis} hide=${true} domain=${[-1, 1]} allowDataOverflow=${true} />
            <${Tooltip} content=${p => html`<${ChartTip} ...${p} curves=${ana.curves} />`} />
            ${(ana.curves || []).map((c, j) => html`
              <${Fragment} key=${"c" + j}>
                <${Area} type="linear" dataKey=${"pCFill" + j}
                         stroke=${DTE_SHADES[j % DTE_SHADES.length].line} strokeWidth=${1.5}
                         fill=${DTE_SHADES[j % DTE_SHADES.length].fill} fillOpacity=${0.45}
                         baseValue=${0} dot=${false} activeDot=${false}
                         isAnimationActive=${false} name=${c.label || (c.dte_days + "d")} />
                <${Line} type="linear" dataKey=${"pC" + j}
                         stroke=${DTE_SHADES[j % DTE_SHADES.length].line} strokeWidth=${1.5}
                         dot=${false} activeDot=${false}
                         isAnimationActive=${false} />
              <//>`)}
            <${Area} type="linear" dataKey="pExpPos" stroke="#3ddc97" strokeWidth=${1.5}
                     fill="#1b4d3a" fillOpacity=${0.6} baseValue=${0}
                     dot=${false} activeDot=${false} isAnimationActive=${false} />
            <${Area} type="linear" dataKey="pExpNeg" stroke="#e0455e" strokeWidth=${1.5}
                     fill="#5c1e26" fillOpacity=${0.6} baseValue=${0}
                     dot=${false} activeDot=${false} isAnimationActive=${false} />
            <${Line} type="linear" dataKey="pT0" stroke="#f59e0b" dot=${false}
                     strokeWidth=${2} isAnimationActive=${false} name="t0" />
            <${Customized} component=${p => chartOverlay(p, ana,
              { tf, pos: scales.pos, neg: scales.neg, zoom: yZoom })} />
          <//>
        <//>`}
      </div>
      <div class="hdivider" onMouseDown=${dragChart}></div>
      ${ana.leg_stats ? html`<${PositionTable} stats=${ana.leg_stats} rollBasis=${ana.roll_basis}
                              hidden=${hidden} onToggle=${onToggle} spot=${ana.spot}
                              serverGroups=${ana.clusters} />` : null}
      <${AdvisorPanel} account=${account} sel=${sel} />
    </div>`;
}
