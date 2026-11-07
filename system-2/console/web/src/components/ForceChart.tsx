import { useState, type PointerEvent } from "react";

export interface Series {
  name: string;
  points: [number, number][];
  tone: "pass" | "fail";
}

const W = 520, H = 216, LEFT = 40, RIGHT = 14, TOP = 12, BOTTOM = 26;

/** Force over time, one shared axis. Lines draw themselves in; hover reads the nearest sample. */
export function ForceChart({ series, limit }: { series: Series[]; limit?: number }) {
  const [tip, setTip] = useState<{ x: number; y: number; text: string } | null>(null);
  const all = series.flatMap((s) => s.points);
  const maxT = Math.max(4, Math.ceil(Math.max(0, ...all.map(([t]) => t))));
  const maxN = Math.max(8, Math.ceil(Math.max(limit ?? 0, ...all.map(([, n]) => n)) / 2) * 2);
  const x = (t: number) => LEFT + (t / maxT) * (W - LEFT - RIGHT);
  const y = (n: number) => H - BOTTOM - (n / maxN) * (H - TOP - BOTTOM);
  const yTicks = Array.from({ length: maxN / 2 + 1 }, (_, i) => i * 2);
  const tickEvery = maxT > 40 ? 10 : maxT > 12 ? 5 : 1;
  const xTicks = Array.from({ length: maxT + 1 }, (_, i) => i).filter((t) => t % tickEvery === 0 || t === maxT).filter((t, i, all) => t === maxT || maxT - t >= tickEvery / 2 || i === all.length - 1);

  const onMove = (e: PointerEvent<SVGSVGElement>) => {
    const box = e.currentTarget.getBoundingClientRect();
    const px = ((e.clientX - box.left) / box.width) * W;
    const py = ((e.clientY - box.top) / box.height) * H;
    let best: { d: number; s: Series; p: [number, number] } | null = null;
    for (const s of series) for (const p of s.points) {
      const d = Math.hypot(x(p[0]) - px, y(p[1]) - py);
      if (!best || d < best.d) best = { d, s, p };
    }
    setTip(best && best.d < 60 ? { x: (x(best.p[0]) / W) * 100, y: (y(best.p[1]) / H) * 100, text: `${best.s.name}: ${best.p[1].toFixed(1)} N at ${best.p[0].toFixed(1)} s` } : null);
  };

  return (
    <div className="stack">
      {series.length > 1 && (
        <div className="legend">
          {series.map((s) => <span key={s.name}><i style={{ borderTopColor: `var(--${s.tone})` }} />{s.name}</span>)}
        </div>
      )}
      <div className="chart">
        <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={series.map((s) => `${s.name} peaks at ${Math.max(...s.points.map((p) => p[1]))} newtons`).join(". ")} onPointerMove={onMove} onPointerLeave={() => setTip(null)}>
          {yTicks.map((n) => (
            <g key={n}>
              <line className="grid" x1={LEFT} x2={W - RIGHT} y1={y(n)} y2={y(n)} />
              <text x={LEFT - 7} y={y(n) + 4} textAnchor="end">{n === maxN ? `${n} N` : n}</text>
            </g>
          ))}
          {xTicks.map((t) => <text key={t} x={x(t)} y={H - 8} textAnchor={t === maxT ? "end" : "middle"}>{t === maxT ? `${t} s` : t}</text>)}
          {limit !== undefined && (
            <>
              <line className="limit" x1={LEFT} x2={W - RIGHT} y1={y(limit)} y2={y(limit)} />
              <text x={W - RIGHT} y={y(limit) - 5} textAnchor="end">step force limit</text>
            </>
          )}
          {series.map((s) => {
            const last = s.points[s.points.length - 1];
            return (
              <g key={s.name}>
                <polyline className="ser draw-line" pathLength={1} points={s.points.map(([t, n]) => `${x(t)},${y(n)}`).join(" ")} style={{ stroke: `var(--${s.tone})` }} />
                <circle className="pop" cx={x(last[0])} cy={y(last[1])} r={5} style={{ fill: `var(--${s.tone})`, stroke: "var(--surface)", strokeWidth: 2 }} />
                <text className="val pop" x={x(last[0]) + 9} y={y(last[1]) + (s.tone === "fail" ? 17 : 4)}>{last[1].toFixed(1)} N</text>
              </g>
            );
          })}
        </svg>
        {tip && <div className="tip" style={{ left: `${tip.x}%`, top: `${tip.y}%` }}>{tip.text}</div>}
      </div>
    </div>
  );
}
