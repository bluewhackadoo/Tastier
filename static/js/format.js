// Display formatting shared by every renderer. Pure functions, no I/O.

export const fmt = (v, d=2) => v == null ? "—" :
  v.toLocaleString("en-US", {minimumFractionDigits:d, maximumFractionDigits:d});
export const money = v => (v < 0 ? "-$" : "$") + fmt(Math.abs(v)).replace(/\.00$/, "");
export const fmtK = v => {
  const av = Math.abs(v);
  if (av >= 1000) return ((v/1000).toFixed(2) + "K").replace(/\.00K$/, "K");
  if (av >= 1) return String(Math.round(v));
  return fmt(v, 2);
};
export const signColor = v => v >= 0 ? "#2dd4a7" : "#ff5d73";

export const MONTHS = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
export const mmmdd = iso => {
  if (!iso) return "";
  const [, m, d] = iso.split("-");
  return `${MONTHS[+m - 1]} ${+d}`;
};
export const strk = v => v == null ? "" : String(+v);
export const dteDays = l => l.dte_days ?? Math.round(l.dte_years * 365);
