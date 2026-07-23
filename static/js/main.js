// Entry point. index.html loads this as <script type="module">, which is
// deferred — the CDN <script> tags for React/Recharts/htm have already run
// by the time this executes (see vendor.js).
import { html, createRoot } from "./vendor.js";
import { App } from "./App.js";

createRoot(document.getElementById("root")).render(html`<${App} />`);
