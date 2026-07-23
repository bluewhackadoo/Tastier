import { html, useState, useEffect, useRef, useCallback } from "./vendor.js";
import { api, wsUrl } from "./api.js";
import { fmt } from "./format.js";
import { TickerLogo } from "./components/TickerLogo.js";
import { GroupLegs } from "./components/legs.js";
import { Analysis } from "./components/Analysis.js";
import { SetupHelp } from "./components/SetupHelp.js";

export function App() {
  const [setup, setSetup] = useState(null);       // /api/setup/validate result
  const [account, setAccount] = useState(null);
  const [groups, setGroups] = useState({});
  const [clusters, setClusters] = useState({});   // server-side grouping per underlying
  const [sel, setSel] = useState(null);
  const [ana, setAna] = useState(null);
  const [quotes, setQuotes] = useState({});
  const [wsOn, setWsOn] = useState(false);
  const [setupErr, setSetupErr] = useState(null);
  const [hiddenLegs, setHiddenLegs] = useState(new Set());  // per-strategy chart toggles
  const anaTimer = useRef(null);
  const leftRef = useRef(null);
  const scrolledSelection = useRef(null);
  const hideParam = [...hiddenLegs].sort().join(",");

  // fetch positions; on initial load also pick a default selection
  const loadPositions = useCallback((preserveSel = true) => {
    if (!account) return;
    fetch(api(`/api/positions/${account}`))
      .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
      .then(d => {
        setGroups(d.groups);
        setClusters(d.clusters || {});
        if (!preserveSel) {
          const keys = Object.keys(d.groups);
          const saved = localStorage.getItem("tastier.sel");
          if (keys.length) setSel(s => s ?? (saved && d.groups[saved] ? saved : keys[0]));
        }
      })
      .catch(() => {});
  }, [account]);

  // toggle a whole strategy cluster's legs in/out of the chart
  const toggleCluster = syms => {
    setHiddenLegs(h => {
      const n = new Set(h);
      const allHidden = syms.every(s => n.has(s));
      syms.forEach(s => allHidden ? n.delete(s) : n.add(s));
      return n;
    });
    loadPositions(true);
  };

  // retry until the backend answers, so a restart mid-load can't strand
  // the page on "Checking setup…"
  useEffect(() => {
    let alive = true;
    const check = async () => {
      try {
        const ctl = new AbortController();
        const t = setTimeout(() => ctl.abort(), 10000);
        const r = await fetch(api("/api/setup/validate"), { signal: ctl.signal });
        clearTimeout(t);
        const s = await r.json();
        if (!alive) return;
        setSetupErr(null);
        setSetup(s);
        if (s.ok && s.accounts.length) setAccount(s.accounts[0].account_number);
      } catch (e) {
        if (!alive) return;
        setSetupErr(e.name === "AbortError" ? "timed out after 10s" : (e.message || String(e)));
        setTimeout(check, 2000);
      }
    };
    check();
    return () => { alive = false; };
  }, []);

  // load positions on account change, refresh every 30s, and retry on error
  useEffect(() => {
    if (!account) return;
    let alive = true;
    const load = () => {
      if (!alive) return;
      loadPositions(false);
      setTimeout(load, 30000);
    };
    load();
    return () => { alive = false; };
  }, [account, loadPositions]);

  // websocket quotes
  useEffect(() => {
    if (!account) return;
    let ws, alive = true, ping;
    const connect = () => {
      ws = new WebSocket(wsUrl("/ws/quotes"));
      ws.onopen = () => { setWsOn(true);
        ping = setInterval(() => ws.readyState === 1 && ws.send("ping"), 15000); };
      ws.onmessage = e => {
        const m = JSON.parse(e.data);
        if (m.symbol) setQuotes(q => {
          const prev = q[m.symbol], next = {...prev, ...m};
          if (m.mid != null && prev?.mid != null && m.mid !== prev.mid)
            next.dir = m.mid > prev.mid ? "up" : "dn";
          return {...q, [m.symbol]: next};
        });
      };
      ws.onclose = () => { setWsOn(false); clearInterval(ping);
        if (alive) setTimeout(connect, 1500); };
    };
    connect();
    return () => { alive = false; ws && ws.close(); clearInterval(ping); };
  }, [account]);

  // refresh positions whenever the user changes the selected position or sub-filter
  useEffect(() => {
    if (!account || !sel) return;
    loadPositions(true);
  }, [account, sel, loadPositions]);

  useEffect(() => {
    if (!account) return;
    loadPositions(true);
  }, [account, hideParam, loadPositions]);

  // clear strategy toggles when switching underlyings
  useEffect(() => setHiddenLegs(new Set()), [sel]);

  useEffect(() => {
    if (!account || !sel || !groups[sel]) return;
    const key = `${account}:${sel}`;
    if (scrolledSelection.current === key) return;
    const frame = requestAnimationFrame(() => {
      const selected = leftRef.current?.querySelector(".group.sel");
      if (!selected) return;
      selected.scrollIntoView({ block: "nearest" });
      scrolledSelection.current = key;
    });
    return () => cancelAnimationFrame(frame);
  }, [account, sel, groups]);

  // refresh analysis when selection/toggles change + every 3s (T+0 uses live IV/spot)
  useEffect(() => {
    if (!account || !sel) return;
    const qs = hideParam ? `?hide=${encodeURIComponent(hideParam)}` : "";
    const load = () => fetch(api(`/api/analysis/${account}/${sel}${qs}`))
      .then(r => r.ok ? r.json() : null).then(d => d && setAna(d))
      .catch(() => {});  // poll again on the next interval
    load();
    anaTimer.current = setInterval(load, 3000);
    return () => clearInterval(anaTimer.current);
  }, [account, sel, hideParam]);

  if (!setup) return html`<div class="empty">Checking setup…
    ${setupErr ? html`<div class="prob" style=${{marginTop:'10px'}}>
      backend not responding (${setupErr}) — retrying…</div>` : ''}</div>`;
  if (!setup.ok) return html`<${SetupHelp} setup=${setup} />`;

  const spotQ = quotes[sel] || {};
  const stale = spotQ.ts && (Date.now()/1000 - spotQ.ts) > 10;

  return html`
    <header>
      <h1>TASTIER LIVE ANALYSIS</h1>
      <span class="env ${setup.env==='live'?'live':''}">${setup.env.toUpperCase()}</span>
      <span class="acct" title="hover to reveal">
        <span class="acct-mask">acct ${'•'.repeat(Math.max(0,(account||'').length))}</span>
        <span class="acct-full">acct ${account}</span>
      </span>
      <span class="conn ${wsOn?'on':''}"><span class="dot"></span>${wsOn?'stream live':'stream down'}</span>
    </header>
    <main>
      <div id="left" ref=${leftRef}>
        ${Object.entries(groups).map(([u, legs]) => {
          const q = quotes[u]?.mid != null ? quotes[u]
                  : quotes[legs[0]?.underlying_streamer] || {};
          return html`
          <div key=${u} class="group ${sel===u?'sel':''}"
               onClick=${() => { loadPositions(true); setSel(u); localStorage.setItem("tastier.sel", u); }}>
            <div class="ghead">
              <${TickerLogo} sym=${u.replace(/^\//, "")} size=${16} className="glogo" />
              <span class="u">${u}</span>
              <span class="px ${q.dir || ''}">${fmt(q.mid)}</span>
            </div>
            <${GroupLegs} legs=${legs} spot=${q.mid} clusters=${clusters[u]} />
          </div>`;})}
        ${!Object.keys(groups).length && html`<div class="empty">No open positions</div>`}
      </div>
      <div id="right">
        ${ana ? html`<${Analysis} ana=${ana} stale=${stale} sel=${sel} account=${account}
                       hidden=${hiddenLegs} onToggle=${toggleCluster} />`
              : html`<div class="empty">Select a position</div>`}
      </div>
    </main>`;
}
