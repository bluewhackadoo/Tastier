// Strategy clusters as the browser sees them.
//
// Real grouping lives in app/grouping.py and is the single source of truth —
// the server ships the partition and everything here just rehydrates it.
// Never reintroduce a JS grouping implementation (see CLAUDE.md, invariant 1).

import { dteDays } from "./format.js";

// Detect a Ratio Super Bull (RSB) or reverse RSB across all option legs.
// Standard RSB: 2 short OTM puts, 1 long ATM call, 1 short OTM call.
// Reverse RSB: 2 short OTM puts, 1 long ATM put,  1 short OTM call.
// Typically the long option is a LEAP and the short puts are near-term,
// so the legs may span expirations and order chains.  Returns the type or null.
// We search for an RSB *core* inside the full position so added wings/strangles
// don't hide the original strategy.
export function detectRSB(legs, spot) {
  const opts = legs.filter(l => l.strike != null);
  if (opts.length < 3) return null;

  const hasSpot = spot != null && spot > 0;
  const otmPut = l => !hasSpot || l.strike < spot * 0.90;
  const otmCall = l => !hasSpot || l.strike > spot * 1.10;
  const longOk = l => !hasSpot || Math.abs(l.strike - spot) / spot <= 0.25;

  // Try standard RSB: for each long call, look for short puts totaling 2x qty
  // and a short call with matching qty, all ordered around the long call.
  for (const longCall of opts.filter(l => l.option_type === "C" && l.qty > 0)) {
    const q = longCall.qty;
    const puts = opts.filter(l => l !== longCall && l.option_type === "P" && l.qty < 0 && l.strike < longCall.strike && otmPut(l));
    const shortCalls = opts.filter(l => l !== longCall && l.option_type === "C" && l.qty < 0 && l.strike > longCall.strike && otmCall(l));
    const putQty = puts.reduce((total, l) => total - l.qty, 0);
    const shortCallQty = shortCalls.reduce((total, l) => total - l.qty, 0);
    if (putQty >= 2 * q && shortCallQty >= q && longOk(longCall))
      return "🐂RSB";
  }

  // Try reverse RSB: for each long put, look for short puts totaling 2x qty
  // and a short call with matching qty.
  for (const longPut of opts.filter(l => l.option_type === "P" && l.qty > 0)) {
    const q = longPut.qty;
    const puts = opts.filter(l => l !== longPut && l.option_type === "P" && l.qty < 0 && l.strike < longPut.strike && otmPut(l));
    const shortCalls = opts.filter(l => l !== longPut && l.option_type === "C" && l.qty < 0 && l.strike > longPut.strike && otmCall(l));
    const putQty = puts.reduce((total, l) => total - l.qty, 0);
    const shortCallQty = shortCalls.reduce((total, l) => total - l.qty, 0);
    if (putQty >= 2 * q && shortCallQty >= q && longOk(longPut))
      return "🐻Reverse RSB";
  }

  return null;
}

// Last-resort grouping if a payload arrives without server clusters (should
// not happen): one group per expiration, unlabeled by strategy. Real grouping
// lives in app/grouping.py — never reintroduce a JS implementation.
export function fallbackClusters(legs) {
  const eq = legs.filter(l => l.strike == null);
  const out = eq.length ? [{ label: "Stock", legs: eq }] : [];
  const byExp = {};
  for (const l of legs) if (l.strike != null) (byExp[l.expiration] ??= []).push(l);
  for (const exp of Object.keys(byExp).sort())
    out.push({ label: `${dteDays(byExp[exp][0])}d`, legs: byExp[exp] });
  return out;
}

// Rehydrate the server's canonical clusters (app/grouping.py) into the shape
// the renderers expect. Falls back to fallbackClusters() when the
// payload predates the server-side grouping (e.g. stale cached page).
export function serverClusters(clusters, legs) {
  if (!clusters || !clusters.length) return fallbackClusters(legs);
  const bySym = new Map(legs.map(l => [l.symbol, l]));
  const out = [];
  for (const c of clusters) {
    const ls = c.legs.map(s => bySym.get(s)).filter(Boolean);
    if (ls.length) out.push({ label: c.label, legs: ls });
  }
  return out.length ? out : fallbackClusters(legs);
}
