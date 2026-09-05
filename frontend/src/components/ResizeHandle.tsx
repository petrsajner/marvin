import React, { useRef } from "react";

export function ResizeHandle({ side, label, value, onChange, onReset }: {
  side: "left" | "right";
  label: string;
  value?: number;
  onChange: (value: number) => void;
  onReset: () => void;
}) {
  const drag = useRef<{ x: number; width: number; max: number } | null>(null);
  const min = side === "left" ? 200 : 240;
  const clamp = (width: number, max: number) => Math.round(Math.max(min, Math.min(max, width)));
  return <div
    className={"column-resizer " + side}
    role="separator" aria-orientation="vertical" aria-label={label}
    aria-valuemin={min} aria-valuemax={700} aria-valuenow={value}
    tabIndex={0} title={label}
    onDoubleClick={onReset}
    onKeyDown={(event) => {
      if (event.key === "Home") { event.preventDefault(); onReset(); }
      if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
      event.preventDefault();
      const width = event.currentTarget.parentElement!.getBoundingClientRect().width;
      const delta = (event.key === "ArrowRight" ? 16 : -16) * (side === "left" ? 1 : -1);
      onChange(clamp(width + delta, Math.min(700, window.innerWidth * .45)));
    }}
    onPointerDown={(event) => {
      if (event.button !== 0) return;
      event.preventDefault();
      const parent = event.currentTarget.parentElement!;
      const width = parent.getBoundingClientRect().width;
      drag.current = { x: event.clientX, width, max: Math.min(700, window.innerWidth * .45) };
      event.currentTarget.setPointerCapture(event.pointerId);
    }}
    onPointerMove={(event) => {
      if (!drag.current) return;
      onChange(clamp(drag.current.width + (event.clientX - drag.current.x) * (side === "left" ? 1 : -1), drag.current.max));
    }}
    onPointerUp={(event) => { drag.current = null; event.currentTarget.releasePointerCapture(event.pointerId); }}
    onPointerCancel={() => { drag.current = null; }}
    onLostPointerCapture={() => { drag.current = null; }}
  />;
}
