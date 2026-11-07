"""The Console's Models page, from the comparison's run folders.

    cd system-2
    uv run python -m rav_harness.results_page          # writes console/web/src/data/model-results.json and wiki-docs.json

wiki-docs.json carries docs/device-theory.md and docs/devices.md to the wiki, with fault lines cut from held-out devices.

harness/config/model_rounds.json says which folders in runs/ make up each round, and what each round tests. Runs are
git-ignored, so the file this writes is what the page shows and what gets committed. It only summarises: every number
comes from a round's results.json (and, for reasoning text, its event logs), never from anything typed in by hand.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import statistics
import time
from typing import Any

SYSTEM_2 = pathlib.Path(__file__).resolve().parents[3]
CONFIG = SYSTEM_2 / "harness" / "config" / "model_rounds.json"
RUNS = SYSTEM_2 / "runs"
OUT = SYSTEM_2 / "console" / "web" / "src" / "data" / "model-results.json"


def _median(values: list[float]) -> float | None:
    return round(statistics.median(values), 2) if values else None


def _reasoning_chars(folder: pathlib.Path) -> int:
    """Reasoning text the model returned, from a run's event log."""
    path = folder / "events.jsonl"
    if not path.is_file():
        return 0
    total = 0
    for line in path.read_text().splitlines():
        if '"model_turn"' in line:
            payload = json.loads(line).get("payload") or {}
            total += len(payload.get("thinking") or "")
    return total


def _load(round_: dict, runs: pathlib.Path) -> list[dict]:
    """Every result in the round's folders. A model and scenario seen twice keeps its first result."""
    rows, seen = [], set()
    for name in round_.get("folders", []):
        path = runs / name / "results.json"
        if not path.is_file():
            raise SystemExit(f"{path} is missing: the round lists a folder that isn't in {runs}")
        for r in json.loads(path.read_text()).get("results", []):
            key = (r.get("model"), r.get("scenario") or r.get("run_id"))
            if key in seen:
                continue
            seen.add(key)
            r["_folder"] = runs / name
            rows.append(r)
    return rows


def soft_row(model: str, rows: list[dict], fault_scenarios: list[str]) -> dict[str, Any]:
    """Round 1's scenarios: each one is scored by checks, so the columns come from those checks."""
    faulty = [r for r in rows if r.get("scenario") in fault_scenarios]
    recovery = [r["checks"]["recovered"] for r in rows if "recovered" in (r.get("checks") or {})]
    latencies = [x for r in rows for x in r.get("latency_s", [])]
    return {
        "model": model, "runs": len(rows),
        "score": round(sum(r.get("score", 0) for r in rows) / len(rows), 3) if rows else None,
        "faults_found": sum(bool((r.get("checks") or {}).get("found_every_fault")) for r in faulty), "faults_planted": len(faulty),
        "false_findings": sum(not (r.get("checks") or {}).get("no_false_findings", True) for r in rows),
        "coverage": None,
        "recovered": sum(bool(x) for x in recovery), "recovery_tries": len(recovery),
        "tokens": sum(r.get("tokens", 0) for r in rows), "turns": sum(r.get("turns", 0) for r in rows),
        "median_turn_s": _median(latencies), "tool_errors": sum(r.get("tool_errors", 0) for r in rows),
        "crashes": sum("crashed" in r for r in rows),
        "reasoning_chars": sum(r.get("thinking_chars", 0) for r in rows),
        "missed": sorted({f"{r.get('scenario')}: {k.replace('_', ' ')}" for r in rows for k, v in (r.get("checks") or {}).items() if not v}
                         | {f"{r.get('scenario')}: crashed" for r in rows if "crashed" in r}),
    }


def eval_row(model: str, rows: list[dict]) -> dict[str, Any]:
    """Full runs on the sim, scored from each run's answer key. Recovery: runs with an injected error that still completed,
    rather than stopping or aborting, and wrote a report."""
    keyed = [r for r in rows if "faults_planted" in r]
    with_detected = [r for r in rows if r.get("detected")]
    scored = [r["reward"] for r in rows if r.get("reward") is not None]
    hit = [r for r in rows if r.get("errors_injected")]
    return {
        "model": model, "runs": len(rows), "score": round(sum(scored) / len(scored), 3) if scored else None,
        "faults_found": sum(len(r.get("faults_found", [])) for r in keyed), "faults_planted": sum(len(r.get("faults_planted", [])) for r in keyed),
        "false_findings": sum(len(r.get("false_findings", [])) for r in keyed),
        "coverage": round(sum(r["covered"] / r["detected"] for r in with_detected) / len(with_detected), 3) if with_detected else None,
        "recovered": sum(bool(r.get("report_written")) and r.get("finished") == "completed" for r in hit), "recovery_tries": len(hit),
        "tokens": sum(r.get("tokens", 0) for r in rows), "turns": sum(r.get("turns", 0) for r in rows),
        "median_turn_s": _median([r["median_turn_s"] for r in rows if r.get("median_turn_s") is not None]),
        "tool_errors": sum(r.get("tool_errors", 0) for r in rows), "crashes": sum(bool(r.get("crashed")) for r in rows),
        "reasoning_chars": sum(_reasoning_chars(r["_folder"] / r["run_id"]) for r in rows if r.get("run_id")),
        "noise_flags": sum(len(r.get("noise_flags", [])) for r in keyed), "recoveries": sum(r.get("recoveries", 0) for r in rows),
        "wall_s": round(sum(r.get("seconds", 0) for r in rows), 1),
        "errors_drawn": sorted(f"{e.get('kind')} ({e.get('when')})" for r in rows for e in r.get("errors_drawn", [])),
        "missed": sorted({f"{r.get('run_id')}: missed {p}" for r in keyed for p in r.get("faults_missed", [])}
                         | {f"{r.get('run_id')}: false finding on {p}" for r in keyed for p in r.get("false_findings", [])}
                         | {f"{r.get('run_id')}: crashed" for r in rows if r.get("crashed")}),
    }


def build(config: dict, runs: pathlib.Path) -> dict[str, Any]:
    rounds = []
    for round_ in config["rounds"]:
        rows = _load(round_, runs) if round_.get("folders") else []
        out_rows = []
        for model in [*config["models"], config["baseline"]]:
            mine = [r for r in rows if r.get("model") == model]
            if not mine:
                continue
            row = soft_row(model, mine, round_.get("fault_scenarios", [])) if round_["kind"] == "soft" else eval_row(model, mine)
            row["baseline"] = model == config["baseline"]
            row["reasoning"] = None if row["baseline"] else config.get("reasoning", {}).get(model)
            out_rows.append(row)
        rounds.append({k: round_.get(k) for k in ("id", "title", "status", "date", "kind", "test_set", "spend", "takeaway")} | {"rows": out_rows})
    return {"generated": time.strftime("%Y-%m-%d"), "route": config.get("route"), "models": config["models"], "rounds": rounds}


DOCS = SYSTEM_2.parent / "docs"
WIKI_DOCS = OUT.with_name("wiki-docs.json")


def held_out_safe(markdown: str) -> str:
    """Drops every line that mentions a fault from a held-out device's section, so its answer never ships in the page.
    A device is a `##` section, or a `###` one under a `##` group."""
    sections: list[list[str]] = [[]]
    for line in markdown.splitlines():
        if line.startswith(("## ", "### ")):
            sections.append([])
        sections[-1].append(line)
    out = []
    for lines in sections:
        held = any("split" in l.lower() and "held" in l.lower() for l in lines[1:])
        out += [l for l in lines if not (held and "fault" in l.lower() and not l.startswith("#"))]
    return "\n".join(out)


def wiki_docs(docs: pathlib.Path) -> dict[str, str | None]:
    """docs/device-theory.md and docs/devices.md, for the wiki. Vite only serves system-2, so they travel as data."""
    read = lambda name: (docs / name).read_text() if (docs / name).is_file() else None  # noqa: E731
    devices = read("devices.md")
    return {"theory": read("device-theory.md"), "devices": held_out_safe(devices) if devices else None}


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="python -m rav_harness.results_page", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default=str(CONFIG))
    ap.add_argument("--runs", default=str(RUNS))
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args(argv)
    data = build(json.loads(pathlib.Path(args.config).read_text()), pathlib.Path(args.runs))
    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, indent=2) + "\n")
    for r in data["rounds"]:
        print(f"round {r['id']} ({r['status']}): {len(r['rows'])} rows")
    print(f"wrote {out}")
    docs = wiki_docs(DOCS)
    out.with_name(WIKI_DOCS.name).write_text(json.dumps(docs, indent=2) + "\n")
    print(f"wrote {out.with_name(WIKI_DOCS.name)} (theory: {'yes' if docs['theory'] else 'not written yet'}, devices: {'yes' if docs['devices'] else 'not written yet'})")


if __name__ == "__main__":
    main()
