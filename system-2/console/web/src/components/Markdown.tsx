// The model writes Markdown. This renders the part of it the model uses: headings, lists, tables, code, bold and italics.
import type { ReactNode } from "react";

export type Block =
  | { kind: "h"; level: number; text: string }
  | { kind: "p"; text: string }
  | { kind: "ul" | "ol"; items: string[] }
  | { kind: "table"; head: string[]; rows: string[][] }
  | { kind: "code"; text: string };

const cells = (line: string) => line.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((c) => c.trim());
const BULLET = /^\s*[-*+]\s+/, NUMBER = /^\s*\d+[.)]\s+/, RULE = /^\s*\|?\s*:?-{2,}/;

export function blocksOf(text: string): Block[] {
  const lines = text.replace(/\r/g, "").split("\n"), blocks: Block[] = [];
  for (let i = 0; i < lines.length;) {
    const line = lines[i];
    const run = (test: (l: string) => boolean) => { const out: string[] = []; while (i < lines.length && test(lines[i])) out.push(lines[i++]); return out; };
    if (!line.trim()) { i++; continue; }
    if (line.startsWith("```")) {
      i++;
      const body = run((l) => !l.startsWith("```"));
      i++;
      blocks.push({ kind: "code", text: body.join("\n") });
    } else if (/^#{1,6}\s/.test(line)) {
      blocks.push({ kind: "h", level: line.match(/^#+/)![0].length, text: line.replace(/^#+\s*/, "") });
      i++;
    } else if (line.trim().startsWith("|") && RULE.test(lines[i + 1] ?? "")) {
      const [head, , ...rows] = run((l) => l.trim().startsWith("|"));
      blocks.push({ kind: "table", head: cells(head), rows: rows.map(cells) });
    } else if (BULLET.test(line) || NUMBER.test(line)) {
      const marker = BULLET.test(line) ? BULLET : NUMBER, items: string[] = [];
      while (i < lines.length && lines[i].trim() && !/^#{1,6}\s/.test(lines[i])) {
        if (marker.test(lines[i])) items.push(lines[i].replace(marker, ""));
        else if (items.length) items[items.length - 1] += ` ${lines[i].trim()}`; // a wrapped item
        i++;
      }
      blocks.push({ kind: marker === BULLET ? "ul" : "ol", items });
    } else {
      const body = run((l) => !!l.trim() && !l.startsWith("```") && !/^#{1,6}\s/.test(l) && !BULLET.test(l) && !NUMBER.test(l));
      blocks.push({ kind: "p", text: body.join(" ") });
    }
  }
  return blocks;
}

/** `code`, **bold** and *italics*, in that order of precedence. */
export function inline(text: string): ReactNode[] {
  return text.split(/(`[^`]+`|\*\*[^*]+\*\*|\*[^*\s][^*]*\*)/).map((part, i) => {
    if (i % 2 === 0) return part;
    if (part.startsWith("`")) return <code key={i}>{part.slice(1, -1)}</code>;
    if (part.startsWith("**")) return <b key={i}>{inline(part.slice(2, -2))}</b>;
    return <em key={i}>{part.slice(1, -1)}</em>;
  });
}

export function Markdown({ text, className = "md" }: { text: string; className?: string }) {
  return (
    <div className={className}>
      {blocksOf(text).map((b, i) => {
        switch (b.kind) {
          case "h": return <p key={i} className="mdh">{inline(b.text)}</p>;
          case "p": return <p key={i}>{inline(b.text)}</p>;
          case "ul": return <ul key={i}>{b.items.map((t, j) => <li key={j}>{inline(t)}</li>)}</ul>;
          case "ol": return <ol key={i}>{b.items.map((t, j) => <li key={j}>{inline(t)}</li>)}</ol>;
          case "code": return <pre key={i}>{b.text}</pre>;
          case "table": return (
            <table key={i} className="mdtable">
              <thead><tr>{b.head.map((h, j) => <th key={j}>{inline(h)}</th>)}</tr></thead>
              <tbody>{b.rows.map((r, j) => <tr key={j}>{r.map((c, k) => <td key={k}>{inline(c)}</td>)}</tr>)}</tbody>
            </table>
          );
        }
      })}
    </div>
  );
}
