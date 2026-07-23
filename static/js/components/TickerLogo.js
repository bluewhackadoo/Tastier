import { html, useState, useEffect } from "../vendor.js";
import { api } from "../api.js";

// Logo component — tracks 404/error in React state so switching symbols
// never leaves a stale display:none on the DOM node
export function TickerLogo({ sym, size = 22, className = "symlogo" }) {
  const [err, setErr] = useState(false);
  useEffect(() => setErr(false), [sym]);
  if (!sym || err) return null;
  return html`<img class=${className} alt=""
    src=${api(`/api/logo/${encodeURIComponent(sym)}`)}
    style=${{width: size + "px", height: size + "px"}}
    onError=${() => setErr(true)} />`;
}
