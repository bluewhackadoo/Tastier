import { html, Fragment } from "../vendor.js";
import { fmt } from "../format.js";
import { detectRSB, serverClusters } from "../clusters.js";
import { LegPills } from "./legs.js";

export function PositionTable({ stats, rollBasis, hidden, onToggle, spot, serverGroups }) {
  const isOff = c => hidden && c.legs.every(l => hidden.has(l.symbol));
  const rsb = detectRSB(stats, spot);
  const num = (v, d=2) => html`<span class="num ${v>0?'pos':v<0?'neg':''}">${fmt(v,d)}</span>`;
  const clusters = serverClusters(serverGroups, stats);
  const sum = (ls, k) => ls.reduce((a, s) => a + s[k], 0);
  const tot = k => sum(stats, k);
  // how many option legs share each expiration, so a roll basis (which spans
  // the whole expiration) is only applied to a cluster that IS that whole
  // expiration — not to a same-expiry cluster split into sub-strategies
  const expLegCount = {};
  stats.forEach(s => { if (s.strike != null) expLegCount[s.expiration] = (expLegCount[s.expiration] || 0) + 1; });
  // group Trd Prc: roll-adjusted (from transaction history) when this cluster
  // is a full, rolled expiration; otherwise the current-legs per-unit price
  const groupTrd = c => {
    const exp = c.legs[0].expiration;
    const rb = rollBasis && rollBasis[exp];
    const isFullExp = c.legs.every(l => l.strike != null) && c.legs.length === expLegCount[exp];
    if (rb && isFullExp && rb.rolls > 0) return { val: rb.trd_prc, rolls: rb.rolls };
    return { val: grpPrice(c.legs, sTrd), rolls: 0 };
  };
  // cash-flow signed per-contract prices, tastytrade-style: debits red (long
  // pays to open, so negative trd prc), credits green; mark is the signed
  // per-unit position value
  const sTrd = s => (s.qty > 0 ? -1 : 1) * s.trd_prc;
  const sMrk = s => (s.qty > 0 ? 1 : -1) * s.mark;
  const sumBy = (ls, f) => ls.reduce((a, s) => a + f(s), 0);
  // a group's net price must weight each leg by its contract count and
  // normalize to one unit of the spread (÷ gcd of the quantities), so e.g.
  // a +2/-4/+2 butterfly reports the per-1x credit, not the raw leg-price sum
  const gcd2 = (a, b) => b ? gcd2(b, a % b) : a;
  const unitDiv = ls => ls.reduce((g, s) => gcd2(g, Math.abs(Math.round(s.qty))), 0) || 1;
  const grpPrice = (ls, f) =>
    ls.reduce((a, s) => a + f(s) * Math.abs(Math.round(s.qty)), 0) / unitDiv(ls);
  return html`
    <table class="pos">
      <thead><tr>
        <th>Leg</th><th>Trd Prc</th><th>Mrk</th><th>DTE</th><th>Δ</th><th>θ</th>
        <th>IV</th><th>Cst</th><th>Ext</th><th>P/L Open</th>
      </tr></thead>
      <tbody>
        ${clusters.map((c, ci) => { const off = isOff(c); return html`
          <${Fragment} key=${c.label + ":" + c.legs[0].symbol}>
            <tr class="grp ${off ? 'off' : ''}" title="click to toggle this strategy on the chart"
                onClick=${() => onToggle && onToggle(c.legs.map(l => l.symbol))}>
              <td><span class="vis">${off ? '○' : '●'}</span>${c.label}${(() => { const r = groupTrd(c).rolls;
                return r > 0 ? html`<span class="rollbadge">w/ ${r} ${r > 1 ? 'rolls' : 'roll'}</span>` : ''; })()}${ci === 0 && rsb ? html`<span class="rsbbadge">${rsb}</span>` : ""}</td>
              <td>${num(groupTrd(c).val)}</td>
              <td>${num(grpPrice(c.legs, sMrk))}</td>
              <td>${c.legs[0].strike != null ? c.legs[0].dte_days + "d" : "—"}</td>
              <td>${fmt(sum(c.legs, "delta"))}</td>
              <td>${num(sum(c.legs, "theta"))}</td>
              <td></td>
              <td>${num(sum(c.legs, "cost"))}</td>
              <td>${num(sum(c.legs, "ext"))}</td>
              <td>${num(sum(c.legs, "pl_open"))}</td>
            </tr>
            ${c.legs.map(s => html`
              <tr key=${s.symbol} class=${off ? 'off' : ''}>
                <td><${LegPills} l=${s} /></td>
                <td>${num(sTrd(s))}</td>
                <td>${num(sMrk(s))}</td>
                <td>${s.strike != null ? s.dte_days + "d" : "—"}</td>
                <td>${fmt(s.delta)}</td>
                <td>${num(s.theta)}</td>
                <td>${s.iv != null ? (s.iv * 100).toFixed(1) + "%" : "—"}</td>
                <td>${num(s.cost)}</td>
                <td>${num(s.ext)}</td>
                <td>${num(s.pl_open)}</td>
              </tr>`)}
          <//>`;})}
        <tr class="tot">
          <td>Σ</td><td></td><td></td><td></td>
          <td>${fmt(tot("delta"))}</td>
          <td>${num(tot("theta"))}</td>
          <td></td>
          <td>${num(tot("cost"))}</td>
          <td>${num(tot("ext"))}</td>
          <td>${num(tot("pl_open"))}</td>
        </tr>
      </tbody>
    </table>`;
}
