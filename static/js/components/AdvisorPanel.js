import { html, useState, useEffect } from "../vendor.js";
import { api } from "../api.js";

// LLM position-management analysis, run on demand. The backend builds the
// dossier (legs, greeks, roll history, 1yr stats) and calls the provider
// configured in .env; only the generated text reaches the browser.
const REC_META = {
  hold_collect_theta: { label: "hold · theta", color: "#2dd4a7" },
  roll:               { label: "roll",         color: "#7aa5ff" },
  adjust_directional: { label: "directional",  color: "#c084fc" },
  cut_losses:         { label: "cut losses",   color: "#ff5d73" },
  take_profits:       { label: "take profits", color: "#3ddc97" },
  other:              { label: "other",        color: "#8b97a8" },
};

const LLM_LABELS = { anthropic: "Claude", openai: "OpenAI", gemini: "Gemini", deepseek: "DeepSeek", kimi: "Kimi" };
const LLM_META = {
  anthropic: { icon: "🅰", color: "#c4a1e7" },
  openai:    { icon: "⚡", color: "#10a37f" },
  gemini:    { icon: "♦", color: "#4285f4" },
  deepseek:  { icon: "🐋", color: "#4f6ef7" },
  kimi:      { icon: "🌙", color: "#a78bfa" },
};
const LLM_ORDER = ["anthropic", "openai", "gemini", "deepseek", "kimi"];

export function AdvisorPanel({ account, sel }) {
  const [loading, setLoading] = useState(false);
  const [hist, setHist] = useState([]);   // saved runs, newest first
  const [idx, setIdx] = useState(0);      // which run is displayed
  const [err, setErr] = useState(null);
  const [avail, setAvail] = useState({}); // provider -> key present
  const [prov, setProv] = useState("");   // selected provider name
  const [models, setModels] = useState([]); // valid models for selected provider
  const [model, setModel] = useState("");   // selected model name
  const res = idx >= 0 ? hist[idx] : null;
  // fetch the models the selected provider can actually use
  useEffect(() => {
    if (!prov || !avail[prov]) { setModels([]); setModel(""); return; }
    let alive = true;
    fetch(api(`/api/llm/models/${prov}`))
      .then(r => r.ok ? r.json() : {})
      .then(d => {
        if (!alive) return;
        const list = d.models || [];
        setModels(list);
        setModel(m => {
          if (m && list.some(x => x.id === m)) return m;
          const latest = hist.find(h => h.provider === prov);
          if (latest && latest.model && list.some(x => x.id === latest.model)) return latest.model;
          const rec = list.find(x => x.recommended) || list.find(x => x.id === d.default);
          return rec?.id || list[0]?.id || "";
        });
      })
      .catch(() => {});
    return () => { alive = false; };
  }, [prov, avail]);
  // which providers actually have API keys; default-select the backend's pick
  useEffect(() => {
    let alive = true;
    fetch(api("/api/health"))
      .then(r => r.ok ? r.json() : {})
      .then(d => {
        if (!alive) return;
        const llm = d.llm || {};
        const av = llm.available || {};
        setAvail(av);
        setProv(p => p && av[p] ? p
          : (llm.provider || LLM_ORDER.find(x => av[x]) || ""));
      })
      .catch(() => {});
    return () => { alive = false; };
  }, []);
  // load saved history so a refresh / new browser shows the last run
  useEffect(() => {
    setHist([]); setIdx(0); setErr(null); setLoading(false);
    if (!account || !sel) return;
    let alive = true;
    fetch(api(`/api/analyses/${account}/${sel}`))
      .then(r => r.ok ? r.json() : [])
      .then(h => {
        if (!alive || !Array.isArray(h)) return;
        setHist(h);
        // when switching positions, always surface the latest available run
        // regardless of which provider/model was selected before
        if (h.length && avail[h[0].provider]) {
          setProv(h[0].provider);
          setModel(h[0].model);
          setIdx(0);
        }
      })
      .catch(() => {});
    return () => { alive = false; };
  }, [account, sel, avail]);
  const run = async () => {
    setLoading(true); setErr(null);
    try {
      const params = new URLSearchParams();
      if (prov && avail[prov]) params.set("provider", prov);
      if (model) params.set("model", model);
      const qs = params.toString();
      const r = await fetch(api(`/api/analyze/${account}/${sel}${qs ? `?${qs}` : ""}`), { method: "POST" });
      const d = await r.json();
      if (d.ok) { setHist(h => [d, ...h]); setIdx(0); }
      else setErr((d.problems || [d.detail || "analysis failed"]).join("; "));
    } catch (e) {
      setErr(/fetch/i.test(e.message || "")
        ? "backend not reachable — is the app still running?"
        : (e.message || String(e)));
    }
    setLoading(false);
  };
  const ts = h => {
    const g = h && h.generated_at;
    if (!g) return "";
    try {
      const d = new Date(g);
      const weekday = d.toLocaleDateString("en-US", { weekday: "short" });
      const month = d.getMonth() + 1;
      const day = d.getDate();
      const h24 = d.getHours();
      const m = d.getMinutes().toString().padStart(2, "0");
      const ampm = h24 >= 12 ? "pm" : "am";
      const h12 = h24 % 12 || 12;
      return `(${weekday} ${month}/${day}, ${h12}:${m}${ampm})`;
    } catch { return g.replace("T", " ").slice(0, 16); }
  };
  const toBullets = text => {
    if (!text) return [];
    if (Array.isArray(text)) return text.filter(Boolean);
    return String(text).split(/(?<=[.!?])\s+/).map(s => s.trim()).filter(Boolean);
  };
  // backend returns ratings.{health,risk,pl} = {score: 1-10, label}; risk is
  // inverted (10 = severe), so flip it before picking green/yellow/red
  const rateCard = (title, r, invert) => {
    const score = r && r.score != null && isFinite(+r.score)
      ? Math.max(1, Math.min(10, Math.round(+r.score))) : null;
    const good = score == null ? null : (invert ? 11 - score : score);
    const color = good == null ? "#8b97a8"
      : good >= 7 ? "#3ddc97" : good >= 4 ? "#f5b94e" : "#ff5d73";
    return html`
      <div class="arate">
        <div class="rk">${title}</div>
        <div class="rv" style=${{ color }}>${score != null ? `${score}/10` : "—"}</div>
        <div class="rl">${(r && r.label) || ""}</div>
        <div class="bar"><i style=${{ width: `${(score || 0) * 10}%`, background: color }}></i></div>
      </div>`;
  };
  const bulletList = (items, key) => html`
    <ul>${items.map((b, i) => html`<li key=${`${key}-${i}`}>${b}</li>`)}</ul>`;
  return html`
    <div class="advisor">
      <div class="ahead">
        <h3>Position analysis</h3>
        ${prov && LLM_META[prov] ? html`<span class="llmdot" style=${{ background: LLM_META[prov].color }} title=${LLM_LABELS[prov]}></span>` : null}
        <select class="aprov" value=${prov} onChange=${e => {
          const p = e.target.value;
          if (p === prov) return;
          setProv(p);
          const i = hist.findIndex(h => h.provider === p);
          setIdx(i >= 0 ? i : -1);
          if (i >= 0) setModel(hist[i].model);
        }}>
          ${LLM_ORDER.map(p => html`
            <option key=${p} value=${p} disabled=${!avail[p]}>
              ${LLM_META[p].icon} ${LLM_LABELS[p]}${avail[p] ? "" : " (no key)"}</option>`)}
        </select>
        ${prov && avail[prov] && models.length ? html`
          <select class="aprov" value=${model} onChange=${e => setModel(e.target.value)}>
            ${models.map(m => html`<option key=${m.id} value=${m.id}>
              ${m.id}${m.input != null && m.output != null
                ? ` · $${m.input}/$${m.output} per 1M`
                : ""}${m.recommended ? " · default" : ""}
            </option>`)}
          </select>` : null}
        ${res ? html`
          <select class="meta ahist" value=${idx} onChange=${e => {
            const i = +e.target.value;
            setIdx(i);
            if (hist[i]) {
              setProv(hist[i].provider);
              setModel(hist[i].model);
            }
          }}>
            ${hist.map((h, i) => html`<option key=${i} value=${i}>${LLM_META[h.provider]?.icon || ""} ${ts(h)} · ${h.model}${i === 0 ? " · latest" : ""}</option>`)}
          </select>` : null}
        <button class="abtn" disabled=${loading} onClick=${run}>
          ${loading ? "Analyzing…" : (res ? "Update analysis" : "Get analysis")}</button>
      </div>
      ${err ? html`<div class="prob" style=${{marginTop:'10px'}}>${err}</div>` : null}
      ${res ? html`
        <div class="aratings">
          ${rateCard("Current health", (res.ratings || {}).health, false)}
          ${rateCard("Future risk", (res.ratings || {}).risk, true)}
          ${rateCard("P/L rating", (res.ratings || {}).pl, false)}
        </div>
        <div class="agrid">
          <div class="aquad">
            <h4>Summary</h4>
            ${bulletList(toBullets(res.summary), "sum")}
          </div>
          <div class="aquad">
            <h4>Outlook</h4>
            ${bulletList(toBullets(res.outlook), "out")}
          </div>
          <div class="aquad warn">
            <h4>Risks</h4>
            ${bulletList(toBullets(res.warnings), "risk")}
          </div>
          <div class="aquad">
            <h4>Key actions</h4>
            ${bulletList((res.recommendations || []).map(r => html`<b>${r.title}</b>${r.details ? ` — ${r.details}` : ""}`), "act")}
          </div>
        </div>
        ${(res.recommendations || []).map((r, i) => {
          const m = REC_META[r.type] || REC_META.other;
          return html`
            <div key=${i} class="rec" style=${{borderLeftColor: m.color}}>
              <span class="rtag" style=${{color: m.color}}>${m.label}</span>
              <span class="rbody"><b>${r.title}</b><div>${r.details}</div></span>
              <span class="conf">${r.confidence || ""}</span>
            </div>`;})}
        ${res.warnings && !toBullets(res.warnings).length ? html`<div class="awarn">⚠ ${res.warnings}</div>` : null}` : null}
      ${!res && !err && !loading ? html`<div class="adisc">
        ${prov && hist.length ? `${LLM_LABELS[prov] || prov} hasn't analyzed ${sel} yet — click Get analysis.`
          : html`Runs your configured LLM (set ANTHROPIC_API_KEY, OPENAI_API_KEY, or
            GEMINI_API_KEY in the app's .env; optional LLM_PROVIDER / LLM_MODEL)
            over the open legs, roll history, and trailing-1yr stats for ${sel}.`}</div>` : null}
      <div class="adisc">AI-generated decision support, not financial advice — nothing is executed.</div>
    </div>`;
}
