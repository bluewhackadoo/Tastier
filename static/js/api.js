// Anchor every URL to the real origin. In some embedding contexts (e.g. an
// about:srcdoc iframe) document.baseURI can't resolve a relative "/api/..."
// path, so fetch() throws "Failed to parse URL"; an absolute origin avoids it.
export const ORIGIN = (location.origin && location.origin !== "null") ? location.origin : "";
export const api = p => ORIGIN + p;
export const wsUrl = p => (ORIGIN ? ORIGIN.replace(/^http/, "ws") : `ws://${location.host}`) + p;
