import { html, useState } from "../vendor.js";
import { api } from "../api.js";

export function SetupHelp({ setup }) {
  const [secret, setSecret] = useState("");
  const [refresh, setRefresh] = useState("");
  const [env, setEnv] = useState("paper");
  const [saving, setSaving] = useState(false);
  const [saveErr, setSaveErr] = useState(null);
  const save = async (e) => {
    e.preventDefault();
    setSaving(true); setSaveErr(null);
    try {
      const r = await fetch(api("/api/setup/credentials"), {
        method: "POST", headers: {"Content-Type":"application/json"},
        body: JSON.stringify({tt_secret: secret, tt_refresh: refresh, tt_env: env})
      });
      const s = await r.json();
      if (s.ok) location.reload();
      else setSaveErr(s.problems?.join("; ") || "save failed");
    } catch (err) {
      // "Failed to fetch" = nothing answered at all — the local backend is
      // gone (closed, killed, or blocked), not a credential problem
      setSaveErr(/fetch/i.test(err.message || "")
        ? "the Tastier app isn't running (or was closed) — relaunch it, refresh this page, and try again"
        : (err.message || String(err)));
    }
    setSaving(false);
  };
  return html`
    <div class="setupbox">
      <h2 style=${{marginTop:0}}>Setup needed (stage: ${setup.stage})</h2>
      ${setup.problems.map(p => html`<div key=${p} class="prob">✗ ${p}</div>`)}

      <form class="setupform" onSubmit=${save}>
        <label>TT_SECRET</label>
        <input type="password" value=${secret} onInput=${e=>setSecret(e.target.value)}
               placeholder="your_client_secret" required />
        <label>TT_REFRESH</label>
        <input type="password" value=${refresh} onInput=${e=>setRefresh(e.target.value)}
               placeholder="your_refresh_token" required />
        <label>Environment</label>
        <select value=${env} onChange=${e=>setEnv(e.target.value)}>
          <option value="paper">paper (sandbox / cert)</option>
          <option value="live">live</option>
        </select>
        <button type="submit" disabled=${saving}>
          ${saving ? "Saving…" : "Save credentials locally & connect"}
        </button>
        ${saveErr ? html`<div class="prob">${saveErr}</div>` : null}
      </form>

      <details class="setuphint">
        <summary>How do I get TT_SECRET and TT_REFRESH?</summary>
        <ol>
          <li>Log in to <strong>my.tastytrade.com</strong> (or the sandbox portal for paper).</li>
          <li>Go to <strong>Manage → My Profile → API → OAuth Applications</strong>.</li>
          <li>Create a personal OAuth app. Scopes: <strong>read only</strong> (do not enable trade).</li>
          <li>Generate a personal grant. Copy the <strong>Client Secret</strong> → TT_SECRET.</li>
          <li>Copy the <strong>Refresh Token</strong> → TT_REFRESH.</li>
          <li>Paste both above. They are stored only on this computer in your local app data folder.</li>
        </ol>
      </details>

      <p style=${{color:'var(--dim)',fontSize:'12px',marginTop:'16px'}}>
        You can also create/edit the <code>.env</code> file directly in your OS user-data
        folder (Windows: <code>%LOCALAPPDATA%\\Tastier\\.env</code>, macOS:
        <code>~/Library/Application Support/Tastier/.env</code>) and restart the app.
      </p>
      <button class="reload" onClick=${()=>location.reload()}>Re-check</button>
    </div>`;
}
