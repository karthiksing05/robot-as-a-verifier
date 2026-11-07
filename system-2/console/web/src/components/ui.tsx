import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";

export const stagger = (i: number) => ({ "--i": i }) as CSSProperties;

const GLYPH: Record<string, string> = {
  passed: "✓", failed: "✕", intermittent: "≈", observed: "◐", skipped: "⊘", inconclusive: "?", pending: "·", planned: "◇", approved: "✓",
  rejected: "✕", withdrawn: "–",
};

/** Status always carries a glyph and a word, so it doesn't rely on color. */
export function Pill({ status, children }: { status: string; children?: ReactNode }) {
  return <span className={`pill ${status}`}>{GLYPH[status] ?? ""} <b>{children ?? status}</b></span>;
}

/** Counts up to a value when it first appears or changes. */
export function CountUp({ value, digits = 2 }: { value: number; digits?: number }) {
  const [shown, setShown] = useState(value);
  const from = useRef(0);
  useEffect(() => {
    if (matchMedia("(prefers-reduced-motion: reduce)").matches) {
      setShown(value);
      return;
    }
    const start = performance.now();
    const origin = from.current;
    let frame = 0;
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / 700);
      const eased = 1 - (1 - t) ** 3;
      setShown(origin + (value - origin) * eased);
      if (t < 1) frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    from.current = value;
    return () => cancelAnimationFrame(frame);
  }, [value]);
  return <>{shown.toFixed(digits)}</>;
}

export function Stat({ label, value, digits, text, i = 0 }: { label: string; value?: number; digits?: number; text?: string; i?: number }) {
  return (
    <div className="stat rise" style={stagger(i)}>
      <span className="label">{label}</span>
      <span className="value">{value !== undefined ? <CountUp value={value} digits={digits} /> : text}</span>
    </div>
  );
}

export function HBar({ label, value, i = 0 }: { label: ReactNode; value: number; i?: number }) {
  return (
    <div className="hbar">
      <span>{label}</span>
      <span className="num">{value.toFixed(2)}</span>
      <div className="track"><span className="fill grow-x" style={{ ...stagger(i), width: `${Math.min(1, value) * 100}%` }} /></div>
    </div>
  );
}

export function downloadText(name: string, text: string, type = "application/json") {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  URL.revokeObjectURL(url);
}
