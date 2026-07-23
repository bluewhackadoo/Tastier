import { html, useState, useEffect, useRef } from "../vendor.js";
import { CandleChart } from "./CandleChart.js";

// Map an underlying to a TradingView symbol. Cash indices use freely
// embeddable proxies — the licensed index feeds (e.g. SP:SPX) throw
// "only available on TradingView" in third-party embeds, but the FOREX.com
// CFD proxies (SPXUSD, etc.) render fine. Futures use the continuous
// front-month contract; equities pass through.
const TV_SYMBOL = {
  SPX: "OANDA:SPX500USD",
  // NDX: "FOREXCOM:NSXUSD", NDXP: "FOREXCOM:NSXUSD", RUT: "FOREXCOM:US2000",
  // DJX: "FOREXCOM:DJI", VIX: "TVC:VIX", VX: "TVC:VIX",
};
// Futures that render as explicit monthly contracts on TradingView rather than
// continuous contracts (e.g. /CLU6 -> CLU2026).
const MONTHLY_FUTURES = new Set(["CL"]);

export function tvSymbol(sel) {
  if (!sel) return "";
  if (TV_SYMBOL[sel]) return TV_SYMBOL[sel];
  if (sel.startsWith("/")) {
    // Try /ROOTMONTHYEAR first (e.g. /CLU6 or /CLU26)
    const m = sel.slice(1).match(/^([A-Z0-9]+?)([FGHJKMNQUVXZ])(\d{1,2})$/);
    if (m) {
      const base = m[1];
      const month = m[2];
      let yr = parseInt(m[3], 10);
      const currentYear = new Date().getFullYear();
      let fullYear;
      if (yr < 10) {
        fullYear = Math.floor(currentYear / 10) * 10 + yr;
        if (fullYear < currentYear) fullYear += 10;
      } else {
        fullYear = 2000 + yr;
      }
      if (MONTHLY_FUTURES.has(base)) return `${base}${month}${fullYear}`;
      if (TV_SYMBOL[base]) return TV_SYMBOL[base];
      return `${base}${month}${fullYear}`;
    }
    // Otherwise fall back to continuous front-month contract.
    const m2 = sel.slice(1).match(/^([A-Z0-9]+)/);
    const base = m2 ? m2[1] : sel.slice(1);
    if (TV_SYMBOL[base]) return TV_SYMBOL[base];
    return base + "1!";
  }
  return sel;
}

// TradingView advanced-chart embed (5m bars over 5 trading days, dark,
// toolbars hidden) — matches the tradeclock.fyi ticker. Falls back to the
// local DXLink candle chart if the embed script can't load (offline).
export function TVTicker({ symbol, sel }) {
  const boxRef = useRef(null);
  const [failed, setFailed] = useState(false);
  const tv = tvSymbol(sel);
  useEffect(() => {
    setFailed(false);
    const box = boxRef.current;
    if (!box || !tv) return;
    box.innerHTML = "";
    const wrap = document.createElement("div");
    wrap.className = "tradingview-widget-container";
    const inner = document.createElement("div");
    inner.className = "tradingview-widget-container__widget";
    wrap.appendChild(inner);
    const s = document.createElement("script");
    s.src = "https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js";
    s.async = true;
    s.onerror = () => setFailed(true);
    s.innerHTML = JSON.stringify({
      symbol: tv, interval: "5", range: "5D", theme: "dark", style: "1",
      locale: "en", autosize: true, hide_top_toolbar: true, hide_legend: true,
      hide_side_toolbar: true, allow_symbol_change: false, save_image: false,
      calendar: false, withdateranges: false,
      backgroundColor: "#161b23", gridColor: "#2a3341",
    });
    wrap.appendChild(s);
    box.appendChild(wrap);
    return () => { box.innerHTML = ""; };
  }, [tv]);
  if (failed) return html`<${CandleChart} symbol=${symbol} />`;
  return html`<div class="tvbox">
    <div class="tvwatermark"><span>${tv}</span></div>
    <div ref=${boxRef} style=${{position:"absolute",inset:0,zIndex:1}}></div>
  </div>`;
}
