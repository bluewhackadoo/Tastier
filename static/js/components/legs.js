import { html } from "../vendor.js";
import { mmmdd, dteDays, strk } from "../format.js";
import { detectRSB, serverClusters } from "../clusters.js";

// leg pill row shared by the left panel and the position table;
// fixed grid columns keep every row vertically aligned
export const LegPills = ({ l }) => l.strike == null
  ? html`<div class="leg2">
      <span class="pill qty">${l.qty}</span>
      <span class="pill shares">${l.symbol?.includes("/") ? "futures" : "shares"}</span>
    </div>`
  : html`<div class="leg2">
      <span class="pill qty">${l.qty}</span>
      <span class="pill">${mmmdd(l.expiration)}</span>
      <span class="pill dim">${dteDays(l)}d</span>
      <span class="pill strike">${strk(l.strike)}</span>
      <span class="pill pc">${l.option_type}</span>
    </div>`;

export function GroupLegs({ legs, spot, clusters }) {
  const rsb = detectRSB(legs, spot);
  return html`
    ${rsb ? html`<div class="rsbbadge">${rsb}</div>` : null}
    ${serverClusters(clusters, legs).map(c => html`
    <div key=${c.label + ":" + c.legs[0].symbol}>
      <div class="subexp">${c.label}</div>
      ${c.legs.map(l => html`<${LegPills} key=${l.symbol} l=${l} />`)}
    </div>`)}
  `;
}
