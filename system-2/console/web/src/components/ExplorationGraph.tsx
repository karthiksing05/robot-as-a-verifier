import { useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import { placeNodes, type GraphNode } from "../lib/graph";

const CELL_W = 148, CELL_H = 80, NODE_W = 122, NODE_H = 54, PAD = 18;

const nodeClass = (n: GraphNode, selected: boolean) => [
  "gnode",
  n.status ?? "",
  n.kind === "finding" || n.kind === "cause" || n.kind === "patch" ? "reason" : "",
  selected ? "selected" : "",
].join(" ");

/** Solid is logged, dashed is planned. New nodes draw in; existing ones don't move unless the layout has to. */
export function ExplorationGraph({ nodes, selected, onSelect, live = false, focus }: { nodes: GraphNode[]; selected: string | null; onSelect: (id: string) => void; live?: boolean; focus?: string | null }) {
  const placed = useMemo(() => placeNodes(nodes), [nodes]);
  const byId = useMemo(() => new Map(placed.map((n) => [n.id, n])), [placed]);
  const width = PAD * 2 + (Math.max(...placed.map((n) => n.rank)) + 1) * CELL_W;
  const height = PAD * 2 + (Math.max(...placed.map((n) => n.lane)) + 1) * CELL_H;
  const left = (n: { rank: number }) => PAD + n.rank * CELL_W;
  const top = (n: { lane: number }) => PAD + n.lane * CELL_H;
  const wrap = useRef<HTMLDivElement>(null);
  const [fit, setFit] = useState(false);

  // A node that appears live settles at once; opening a finished run staggers along its ranks.
  const delayRank = (n: { rank: number }) => (live ? 0 : n.rank);

  // Keep the selected node in view, including a new branch that lands past the right edge. A live run also follows
  // whatever is running.
  useEffect(() => {
    const node = placed.find((n) => n.id === (focus ?? selected));
    if (!node || fit || !wrap.current) return;
    const box = wrap.current;
    box.scrollTo({ left: Math.max(0, left(node) + NODE_W / 2 - box.clientWidth / 2), behavior: "smooth" });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected, focus, fit, placed.length]);

  return (
    <div className="graphwrap" ref={wrap}>
      <button className="linkbtn graphfit" type="button" aria-pressed={fit} onClick={() => setFit(!fit)}>{fit ? "Actual size" : "Fit to view"}</button>
      <svg className="graph" width={fit ? "100%" : width} height={fit ? undefined : height} viewBox={`0 0 ${width} ${height}`} role="group" aria-label="Exploration graph" style={{ display: "block" }}>
        <defs>
          <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path className="ah" d="M0,0L10,5L0,10z" /></marker>
        </defs>
        {placed.flatMap((n) => n.parents.map((pid) => {
          const p = byId.get(pid);
          if (!p) return null;
          const x1 = left(p) + NODE_W, y1 = top(p) + NODE_H / 2, x2 = left(n) - 2, y2 = top(n) + NODE_H / 2;
          const mid = (x1 + x2) / 2;
          const d = y1 === y2 ? `M${x1},${y1}H${x2}` : `M${x1},${y1}C${mid},${y1} ${mid},${y2} ${x2},${y2}`;
          const dashed = n.provenance !== "log";
          return (
            <path key={`${pid}-${n.id}`} d={d} pathLength={dashed ? undefined : 1} markerEnd="url(#arrow)"
              className={`edge gedge ${dashed ? "dash" : ""} ${n.provenance === "edit" ? "planned" : ""}`}
              style={{ "--rank": delayRank(n) } as CSSProperties} />
          );
        }))}
        {placed.map((n) => (
          // Position on the outer group: a CSS animation on the inner one would replace an SVG transform attribute.
          <g key={n.id} transform={`translate(${left(n)} ${top(n)})`}>
            <g className={nodeClass(n, n.id === selected)} style={{ "--rank": delayRank(n) } as CSSProperties}
              tabIndex={0} role="button" aria-pressed={n.id === selected} aria-label={`${n.title}, ${n.sub}${n.status ? `, ${n.status}` : ""}`}
              onClick={() => onSelect(n.id)} onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onSelect(n.id); } }}>
              <rect width={NODE_W} height={NODE_H} />
              <text x={10} y={22} fontSize={12}>{n.title}</text>
              <text className="sub" x={10} y={38}>{n.sub.length > 17 ? `${n.sub.slice(0, 16)}…` : n.sub}</text>
              {n.flags.length > 0 && <text className="sub" x={NODE_W - 8} y={15} textAnchor="end">{live ? n.flags[0] : `${n.flags.length} edit${n.flags.length > 1 ? "s" : ""}`}</text>}
            </g>
          </g>
        ))}
      </svg>
    </div>
  );
}
