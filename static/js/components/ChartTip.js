import { html } from "../vendor.js";
import { fmt, signColor } from "../format.js";

export function ChartTip({ active, payload, curves }) {
  if (!active || !payload || !payload.length) return null;
  const d = payload[0].payload;
  const row = (k, v, c) => html`
    <div style=${{display:'flex',justifyContent:'space-between',gap:'18px'}}>
      <span style=${{color:'#8b97a8'}}>${k}</span><span style=${{color:c}}>${v}</span>
    </div>`;
  return html`
    <div style=${{background:'#1d242fee',border:'1px solid #2a3341',borderRadius:'4px',
                  padding:'8px 10px',font:'13px Consolas, monospace'}}>
      ${row("PRICE", fmt(d.spot), "#dfe6ef")}
      ${row("P/L THEO", fmt(d.t0), signColor(d.t0))}
      ${(curves || []).map((c, j) => row(`P/L ${c.label || c.dte_days + "d"}`, fmt(d["c" + j]),
          signColor(d["c" + j])))}
      ${row("P/L EXP", fmt(d.exp), signColor(d.exp))}
      ${row("θ THEO", fmt(d.theta), "#c26bd4")}
    </div>`;
}
