import { html } from "../vendor.js";
import { fmt, fmtK, signColor } from "../format.js";
import { interp, niceStep, DTE_SHADES } from "../scale.js";

// custom overlay: center price strip, top P/L@EXP row, bottom theta row, lot flags
export function chartOverlay(props, ana, yc) {
  const xMap = props.xAxisMap, yMap = props.yAxisMap;
  if (!xMap || !yMap) return null;
  const x = Object.values(xMap)[0].scale, y = Object.values(yMap)[0].scale;
  const { left, top, width, height } = props.offset;
  const y0 = y(0), right = left + width, bottom = top + height;
  const HALF = 13;                       // half-height of the center price strip
  const font = "Consolas, monospace";
  const FS = 13;                         // base font size for chart labels
  const tf = yc ? yc.tf : (v => v);      // P/L $ -> plot units

  const gridXs = ana.grid, expA = ana.expiration_pl, t0A = ana.t0_pl || [];
  const [lo, hi] = x.domain();  // reflects the current zoom window
  const step = niceStep((hi - lo) / Math.max(4, Math.floor(width / 48)));
  // only as many decimals as the step actually needs (72.5 vs 450)
  const dec = Number.isInteger(step) ? 0 : (Number.isInteger(step * 10) ? 1 : 2);
  const ticks = [];
  for (let t = Math.ceil(lo / step) * step; t <= hi + 1e-9; t += step)
    ticks.push(+t.toFixed(6));
  // keep tick value labels clear of the corner row labels (now inside the plot)
  const rowTicks = ticks.filter(t => x(t) > left + 88 && x(t) < right - 88);

  // right-edge series labels, de-overlapped; the nearest expiration is the
  // shaded (green) primary, later expirations are lines, T+0 is orange
  const hasOpts = (ana.legs || []).some(l => l.strike != null);
  const seriesLabels = [
    { v: interp(gridXs, ana.t0_pl, hi), color: "#f59e0b", txt: "T+0" },
    ...(ana.curves || []).map((c, j) => ({
      v: interp(gridXs, c.pl, hi),
      color: DTE_SHADES[j % DTE_SHADES.length].line,
      txt: c.label || (c.dte_days + "d") })),
    ...(hasOpts ? [{ v: interp(gridXs, expA, hi), color: "#8fd8a8",
                     txt: (ana.exp_dte ?? "") + "dte" }] : []),
  ].map(s => ({ ...s, yy: Math.min(Math.max(y(tf(s.v)), top + 12), bottom - 6) }))
   .sort((a, b) => a.yy - b.yy);
  for (let i = 1; i < seriesLabels.length; i++)
    if (seriesLabels[i].yy - seriesLabels[i - 1].yy < 15)
      seriesLabels[i].yy = seriesLabels[i - 1].yy + 15;

  // right-hand P/L axis: dollar ticks for the linear scale, skipping the strip band;
  // wheel over the right gutter zooms the whole Y axis.
  const axTicks = [];
  if (yc) {
    for (const sign of [1, -1]) {
      const vEdge = (sign > 0 ? yc.pos : yc.neg) / (0.9 * yc.zoom);
      const stepY = niceStep(vEdge / 4);
      for (let v = stepY; v <= vEdge * 1.001; v += stepY) {
        const yy = y(tf(sign * v));
        if (yy < top + 10 || yy > bottom - 4) continue;
        if (Math.abs(yy - y0) < HALF + 10) continue;
        axTicks.push({ yy, txt: (sign < 0 ? "-" : "") + fmtK(v),
                       color: sign > 0 ? "#2dd4a7" : "#ff5d73" });
      }
    }
  }

  // lot flags: long above the strip, short below; stagger when crowded
  const FW = 33, FH = 18, GAP = 9;
  const flags = (ana.legs || []).filter(l => l.strike != null && l.strike >= lo && l.strike <= hi)
    .map(l => ({ xx: x(l.strike), up: l.qty > 0, label: `${l.qty}${l.option_type}` }))
    .sort((a, b) => a.xx - b.xx);
  const lastAt = { up: [], dn: [] };     // last x per stagger level, per side
  for (const f of flags) {
    const lv = lastAt[f.up ? "up" : "dn"];
    let i = 0;
    while (i < lv.length && f.xx - lv[i] < FW + 6) i++;
    lv[i] = f.xx;
    f.lvl = i;
  }

  return html`<g>
    <!-- top row: P/L at expiration -->
    <text x=${left + 2} y=${top - 9} fill="#8b97a8" font-size=${FS} font-family=${font}>P/L @ EXP</text>
    <text x=${right - 2} y=${top - 9} text-anchor="end" fill="#8b97a8" font-size=${FS} font-family=${font}>P/L @ EXP</text>
    ${rowTicks.map(t => html`
      <text key=${"e" + t} x=${x(t)} y=${top - 9} text-anchor="middle" font-size=${FS}
            font-family=${font} fill=${signColor(interp(gridXs, expA, t))}>
        ${fmtK(interp(gridXs, expA, t))}</text>`)}

    <!-- vertical guides (drawn first so the strip covers them) -->
    ${ana.breakevens.filter(b => b >= lo && b <= hi).map(b => html`
      <line key=${"bl" + b} x1=${x(b)} x2=${x(b)} y1=${top} y2=${bottom}
            stroke="#f5b94e" stroke-dasharray="4 4" />`)}
    ${ana.spot >= lo && ana.spot <= hi ? html`
      <line x1=${x(ana.spot)} x2=${x(ana.spot)} y1=${top} y2=${bottom}
            stroke="#7aa5ff" stroke-width="1.5" />` : null}

    <!-- center price strip -->
    <rect x=${left} y=${y0 - HALF} width=${width} height=${HALF * 2} fill="#10151d"
          fill-opacity="0.15" />
    <line x1=${left} x2=${right} y1=${y0 - HALF} y2=${y0 - HALF} stroke="#2a3341" />
    <line x1=${left} x2=${right} y1=${y0 + HALF} y2=${y0 + HALF} stroke="#2a3341" />
    ${ticks.filter(t => Math.abs(x(t) - x(ana.spot)) > 22).map(t => html`
      <text key=${"p" + t} x=${x(t)} y=${y0 + 4.5} text-anchor="middle" font-size=${FS}
            font-family=${font} fill="#8b97a8">${fmt(t, dec)}</text>`)}
    ${ana.spot >= lo && ana.spot <= hi ? html`
      <circle cx=${x(ana.spot)} cy=${y0} r=${4} fill="#dfe6ef" stroke="#0e1116" />` : null}

    <!-- breakeven tags on the strip -->
    ${ana.breakevens.filter(b => b >= lo && b <= hi).map(b => html`
      <g key=${"b" + b}>
        <rect x=${x(b) - 29} y=${y0 - HALF - 19} width=${58} height=${17} rx=${3}
              fill="#2b2413" stroke="#f5b94e" stroke-width="0.5" />
        <text x=${x(b)} y=${y0 - HALF - 6} text-anchor="middle" font-size="12"
              font-family=${font} fill="#f5b94e">${fmt(b, 2)}</text>
      </g>`)}

    <!-- lot flags -->
    ${flags.map((f, i) => {
      const yr = f.up ? y0 - HALF - 22 - FH - f.lvl * (FH + 4)
                      : y0 + HALF + 22 + f.lvl * (FH + 4);
      return html`<g key=${"f" + i}>
        <line x1=${f.xx} x2=${f.xx} y1=${f.up ? yr + FH : y0 + HALF}
              y2=${f.up ? y0 - HALF : yr} stroke="#4a5568" />
        <rect x=${f.xx - FW/2} y=${yr} width=${FW} height=${FH} rx=${3}
              fill="#1d242f" stroke="#3a4656" />
        <rect x=${f.xx - FW/2} y=${yr} width=${3} height=${FH} fill="#ff5d73" />
        <text x=${f.xx + 1.5} y=${yr + FH - 5} text-anchor="middle" font-size="12"
              font-family=${font} fill="#dfe6ef">${f.label}</text>
      </g>`;})}

    <!-- bottom row: theoretical (T+0) P/L -->
    <text x=${left + 2} y=${bottom + 20} fill="#8b97a8" font-size=${FS} font-family=${font}>P/L THEO</text>
    <text x=${right - 2} y=${bottom + 20} text-anchor="end" fill="#8b97a8" font-size=${FS} font-family=${font}>P/L THEO</text>
    ${t0A.length ? rowTicks.map(t => html`
      <text key=${"t" + t} x=${x(t)} y=${bottom + 20} text-anchor="middle" font-size=${FS}
            font-family=${font} fill=${signColor(interp(gridXs, t0A, t))}>
        ${fmtK(interp(gridXs, t0A, t))}</text>`) : null}

    <!-- right-hand P/L axis (mousewheel over this gutter zooms Y) -->
    ${axTicks.map((a, i) => html`
      <text key=${"ay" + i} x=${right - 4} y=${a.yy} text-anchor="end"
            font-size=${FS} font-family=${font} fill=${a.color}
            stroke="#0e1116" stroke-width="3" paint-order="stroke">${a.txt}</text>`)}

    <!-- per-curve DTE labels at the right edge -->
    ${seriesLabels.map(s => html`
      <text key=${"sl" + s.txt} x=${right - 52} y=${s.yy} text-anchor="end"
            font-size="12" font-family=${font} fill=${s.color}
            stroke="#0e1116" stroke-width="3" paint-order="stroke">${s.txt}</text>`)}
  </g>`;
}
