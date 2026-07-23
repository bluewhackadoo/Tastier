// Axis/curve math and the palette the payoff chart draws with.

// linear interpolation of ys over sorted xs
export const interp = (xs, ys, x) => {
  if (x <= xs[0]) return ys[0];
  if (x >= xs[xs.length-1]) return ys[ys.length-1];
  let lo = 0, hi = xs.length - 1;
  while (hi - lo > 1) { const m = (lo + hi) >> 1; xs[m] <= x ? lo = m : hi = m; }
  const f = (x - xs[lo]) / (xs[hi] - xs[lo]);
  return ys[lo] + f * (ys[hi] - ys[lo]);
};

export const niceStep = raw => {
  const p = Math.pow(10, Math.floor(Math.log10(raw)));
  for (const m of [1, 2, 2.5, 5, 10]) if (m * p >= raw) return m * p;
  return 10 * p;
};

// green shades for each earlier-dated position's expiration shape (nearest
// first), nested over the terminal combined shape; profit region is filled,
// losses read through the terminal's red — so DTE shapes stay "all green"
export const DTE_SHADES = [
  { fill: "#4fb488", line: "#8fe8c0" },
  { fill: "#7bbf4a", line: "#c4e89a" },
  { fill: "#3f9db4", line: "#8fd8e6" },
  { fill: "#b0a63f", line: "#e6dc9a" },
];
