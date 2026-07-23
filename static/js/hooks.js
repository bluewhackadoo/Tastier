import { useRef } from "./vendor.js";

// Generic drag-to-resize hook. axis='y' → row-resize, axis='x' → col-resize.
// onDelta receives the raw px delta each mousemove; caller owns the state.
export function useDividerDrag(axis, onDelta) {
  const start = useRef(null);
  const onMouseDown = e => {
    e.preventDefault();
    start.current = axis === 'y' ? e.clientY : e.clientX;
    const onMove = ev => {
      const pos = axis === 'y' ? ev.clientY : ev.clientX;
      onDelta(pos - start.current);
      start.current = pos;
    };
    const onUp = () => {
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
    };
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
  };
  return onMouseDown;
}
