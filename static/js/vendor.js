// The CDN bundles (React, ReactDOM, Recharts, htm) are classic <script> tags
// in index.html. Module scripts are always deferred, so those globals exist
// before any module here runs. This file is the ONLY place they are read —
// everything else imports from it, so there is a single line to change if the
// app ever moves to npm + a bundler.

export const { useState, useEffect, useRef, useMemo, useCallback, createElement } = React;
export const Fragment = React.Fragment;
export const { createRoot } = ReactDOM;

export const html = htm.bind(createElement);

export const { ResponsiveContainer, ComposedChart, Line, Area, XAxis, YAxis,
                Tooltip, Customized } = Recharts;
