"""How well a run did, measured against the answer key: a file System 1 writes on the sim, which no tool can read. The
key is only opened here, once a run is over. Nothing here runs during a run, and nothing here reaches a prompt.

    rav eval --devices C,7 --faults none,random --error-rates 0,0.05 --repeats 2 --baseline
"""
from __future__ import annotations

import json
import math
import pathlib
import time
from typing import Any

from rav_contracts import Report, TestRequest

from .agent import AgentConfig, run_agent, sim_auto_approve
from .launch import Device, System1Process
from .ledger import Budget, Ledger
from .loop import run_test
from .manual import Manual
from .model import make_client
from .runlog import RunLog, read_events

MATCH_MM = 25.0


def _truth_map(scene_controls: list[dict], truth: list[dict]) -> dict[str, str]:
    """Each control the robot found, to the true part it is. By place when the key has places, else by id."""
    out, taken = {}, set()
    for c in scene_controls:
        best, gap = None, MATCH_MM
        for t in truth:
            if t.get("pos_mm") is None:
                continue
            d = math.dist(c["pos_mm"], t["pos_mm"])
            if t["id"] not in taken and d < gap:
                best, gap = t["id"], d
        if best is None and any(t["id"] == c["id"] for t in truth) and c["id"] not in taken:
            best = c["id"]
        if best:
            out[c["id"]] = best
            taken.add(best)
    return out


SCORING = pathlib.Path(__file__).resolve().parents[2] / "config" / "scoring.json"


def _unclear_by_design() -> set[str]:
    """Faults whose honest result is inconclusive: calling them passed is the mistake, and not finding them isn't one."""
    return set(json.loads(SCORING.read_text()).get("inconclusive_by_design", [])) if SCORING.is_file() else set()


REGISTRIES = ("appliances/registry.json",)  # where authored devices are listed (system-1/sim/tools/build.py writes it)


def find_authored(name: str, repo: pathlib.Path | None = None) -> dict:
    """An authored device by its id, from whichever registry lists it. Held-out devices are refused: they're never run."""
    from .model import REPO

    repo = repo or REPO
    for rel in REGISTRIES:
        path = repo / rel
        if not path.is_file():
            continue
        for entry in json.loads(path.read_text()):
            if entry.get("id") != name:
                continue
            if entry.get("split") == "held_out":
                raise ValueError(f"{name} is held out: it's never run")
            device = (repo / entry["device"]) if (repo / entry["device"]).is_file() else path.parent / name / "device.yaml"
            manual = (repo / entry["manual"]) if entry.get("manual") and (repo / entry["manual"]).is_file() else device.parent / "manual.md"
            return {**entry, "device_path": device, "manual_path": manual if manual.is_file() else None, "build_key": device.parent / "build" / "answer_key.json"}
    raise ValueError(f"no authored device called {name} in {', '.join(REGISTRIES)}")


def _settings() -> dict:
    return json.loads(SCORING.read_text()) if SCORING.is_file() else {}


DISPLAYED = ("lcd", "state", "ring", "light")  # what a verify step can expect besides channel readings


def symptoms(folder: pathlib.Path) -> dict[str, dict]:
    """Where each fault shows, from the device's own verify checks: the step its check fails at (`fails_at`), and what
    that step expects, without the channel the operated control drives itself. {fault: {"on": control or None, "reads": set}}.
    Scorer only: like the build key, nothing here reaches a model."""
    import yaml

    verify, device = folder / "verify.yaml", folder / "device.yaml"
    if not verify.is_file() or not device.is_file():
        return {}
    v, d = yaml.safe_load(verify.read_text()) or {}, yaml.safe_load(device.read_text()) or {}
    # a control's body can be a parameter a fault swaps ($name): resolve it as the designer meant it, Rev B
    params = {k: v2 for f in (d.get("faults") or {}).values() for k, v2 in (((f or {}).get("B") or {}).get("params") or {}).items()}
    body = {c["id"]: params.get(str(c.get("body", "")).lstrip("$"), c.get("body")) for c in d.get("controls", [])}
    own: dict[str, set] = {}
    for sensor in ((d.get("firmware") or {}).get("sensors") or []):
        for cid, b in body.items():
            if b and sensor.get("joint") == b:
                own.setdefault(cid, set()).add(sensor.get("channel"))
    out = {}
    for fid, f in (v.get("faults") or {}).items():
        steps, at = (f or {}).get("steps") or [], (f or {}).get("fails_at")
        if f.get("rev") or at is None or at >= len(steps):  # a variant check (another revision's mix), not the fault's own
            continue
        step, expect = steps[at], steps[at].get("expect") or {}
        reads = {*(expect.get("readings") or {}), *(expect.get("changed") or []), *(expect.get("unchanged") or []), *(k for k in DISPLAYED if k in expect)}
        on = next((st.get("target") for st in reversed(steps[:at + 1]) if st.get("target")), None)  # a wait shows what the last action started
        out[fid] = {"on": on, "reads": reads - own.get(step.get("target"), set())}
    return out


def _metric(name: str) -> str:
    return name.split(":", 1)[1].lower() if name.startswith("reading:") else name.lower()


def _failed_checks(events: list) -> dict[str, list[dict]]:
    """Every step's failed checks, by step id, with whether the step quoted the manual or named a source."""
    planned: dict[str, dict] = {}
    for e in events:
        for st in (e.payload.get("steps") or []) if isinstance(e.payload, dict) else []:
            if isinstance(st, dict) and st.get("id"):
                planned[st["id"]] = st
    out: dict[str, list[dict]] = {}
    for e in events:
        if e.type != "step_finished":
            continue
        trace = e.payload["trace"]
        st = planned.get(trace.get("step"), {})
        for c in trace.get("checks") or []:
            if c.get("passed") is False:
                sourced = bool(st.get("quote")) or any((x or {}).get("source") for x in st.get("check") or [] if (x or {}).get("metric") == c.get("metric"))
                out.setdefault(trace["step"], []).append({"metric": _metric(c.get("metric", "")), "sourced": sourced})
    return out


def score_authored(report: Report, events: list, key: dict, build: dict, symptom: dict[str, dict] | None = None) -> dict[str, Any]:
    """An authored device, against its build answer key: the revision's observable faults are what should be found. A
    masked fault counts only if its part is called passed. A fault that can only show with an object placed (the robot
    can't pick) counts as handled when its part isn't called passed."""
    choices = (key.get("device") or {}).get("rev") or {}
    rev = next((name for name, r in build["revs"].items() if r.get("choices") == choices), None)
    if rev is None:
        return {"scoring_error": f"the run's revision {choices} isn't one of the build key's"}
    faults = {f["id"]: f for f in build["faults"]}
    observable, masked = build["revs"][rev]["observable"], build["revs"][rev]["masked"]
    needs_object = set(_settings().get("needs_an_object", []))
    named: dict[str, str] = {}
    for e in events:
        if e.type == "scene_ready":
            named = {**_truth_map(e.payload["controls"], key.get("controls") or []), **named}
    cov = report.coverage
    part = lambda c: named.get(c, c)  # noqa: E731
    reported = {part(f.target): f for f in report.findings}
    passed = {part(c) for c in cov.passed}
    present = {faults[i]["piece"] for i in [*observable, *masked]}
    untestable = [i for i in observable if faults[i].get("property") in needs_object and faults[i]["piece"] not in reported and faults[i]["piece"] not in passed]
    judged = [i for i in observable if i not in untestable]
    # A finding found the fault if a failing check on it reads where the fault shows, on the step the fault shows at, and
    # quotes the manual's promise: a tester who reports the symptom found the fault, whichever control the check sat on.
    failed_checks, by_symptom, credited = _failed_checks(events), {}, set()
    for i in judged:  # a masked fault can't show, so nothing reads its symptom
        sym = (symptom or {}).get(i)
        if not sym:
            continue
        for p, f in reported.items():
            if (sym["on"] and p != sym["on"]) or p in present:  # a finding on another fault's own part is that fault's
                continue
            if any(c["sourced"] and c["metric"] in sym["reads"] for sid in f.step_ids for c in failed_checks.get(sid, [])):
                credited.add(p)  # it reports this fault, so it isn't a false finding, whether or not the fault's own part was reported too
                if faults[i]["piece"] not in reported:
                    by_symptom.setdefault(i, p)
    hit = lambda i: faults[i]["piece"] in reported or i in by_symptom  # noqa: E731
    return {
        "revision": rev, "faults_planted": judged, "faults_found": [i for i in judged if hit(i)],
        "faults_missed": [i for i in judged if not hit(i)], "faults_untestable_ok": untestable,
        "found_by_symptom": {i: p for i, p in by_symptom.items() if i in judged},
        "faults_called_passed": [i for i in [*observable, *masked] if faults[i]["piece"] in passed],
        "found_as_intermittent": [i for i in judged if faults[i]["piece"] in reported and reported[faults[i]["piece"]].label == "intermittent"],
        "masked": list(masked), "masked_found": [i for i in masked if hit(i)],
        "false_findings": sorted(p for p, f in reported.items() if p not in present | credited and f.label != "intermittent"),
        "noise_flags": sorted(p for p, f in reported.items() if p not in present | credited and f.label == "intermittent"),
        "truth_controls": len(key.get("controls") or []), "truth_found": len(named),
        "errors_injected": len(key.get("errors") or []),
        "errors_drawn": [{k: e.get(k) for k in ("kind", "when", "draw") if e.get(k) is not None} for e in key.get("errors") or []],
        "manual_reads": sum(1 for e in events if e.type == "tool_call" and e.payload.get("tool") == "read_manual"),
    }


def score(report: Report, events: list, key: dict | None, build: dict | None = None, symptom: dict[str, dict] | None = None) -> dict[str, Any]:
    """Everything worth comparing about one run. Only `faults_*`, `false_*` and `noise_*` need the key."""
    types = [e.type for e in events]
    turns = [e.payload for e in events if e.type == "model_turn"]
    calls = [e.payload for e in events if e.type == "tool_call" and e.payload.get("caller") == "model"]
    finished = next((e.payload.get("status") for e in reversed(events) if e.type == "run_finished"), None)
    cov = report.coverage
    out: dict[str, Any] = {
        "finished": finished, "report_written": "report_ready" in types, "reward": report.reward.value, "detected": cov.detected, "covered": cov.covered,
        "passed": len(cov.passed), "failed": list(cov.failed), "intermittent": list(cov.intermittent), "inconclusive": list(cov.inconclusive), "skipped": sorted(cov.skipped),
        "turns": len(turns), "tool_calls": len(calls), "tool_errors": sum(not c.get("ok", True) for c in calls),
        "tokens": sum((t.get("tokens_in") or 0) + (t.get("tokens_out") or 0) for t in turns),
        "model_seconds": round(sum(t.get("latency_ms") or 0 for t in turns) / 1000, 1),
        "crossings": types.count("crossing"), "duration_s": round(events[-1].t, 1) if events else 0,
        "looks": types.count("scene_ready"), "approvals": types.count("approved"),
        "models": sorted({t.get("model") for t in turns if t.get("model")}),
        "recoveries": sum(1 for c in calls if c.get("tool") == "recover" and c.get("ok", True)),
        "stops_handled": sum(1 for c in calls if c.get("tool") == "answer_stop" and c.get("ok", True)),
        "median_turn_s": round(sorted(t.get("latency_ms") or 0 for t in turns)[len(turns) // 2] / 1000, 2) if turns else None,
        "model_gave_up": any(e.type == "message" and "rule-based plan" in str(e.payload.get("text")) for e in events),
        "checkback": next((e.payload["checkback"] for e in reversed(events) if e.type == "message" and isinstance(e.payload.get("checkback"), dict)), None),
        "hypotheses": [c.get("ok", True) for c in calls if c.get("tool") == "record_hypothesis"],
    }
    if key is None:
        return out
    if build is not None:
        return {**out, **score_authored(report, events, key, build, symptom)}
    truth = key.get("controls") or []
    named: dict[str, str] = {}
    scene = {"controls": []}
    for e in events:  # findings keep a control's first name, and it may have been looked at more than once
        if e.type == "scene_ready":
            scene = e.payload
            named = {**_truth_map(scene["controls"], truth), **named}
    faults = key.get("faults") or []
    by_design = _unclear_by_design()
    is_unclear = lambda f: f.get("expect") == "inconclusive" or f.get("fault") in by_design  # noqa: E731
    faulty = {f.get("part") for f in faults if not is_unclear(f)}
    unclear = {f.get("part") for f in faults if is_unclear(f)}
    called_passed = sorted(p for p in unclear if p in {named.get(c, c) for c in cov.passed})
    found_parts = {named.get(f.target, f.target): f for f in report.findings}
    found = sorted(p for p in faulty if p in found_parts)
    false = sorted(p for p, f in found_parts.items() if p not in faulty | unclear and f.label != "intermittent")
    noise = sorted(p for p, f in found_parts.items() if p not in faulty | unclear and f.label == "intermittent")
    wanted = key.get("expected") or {}
    seen: dict[str, Any] = {}
    for e in events:
        if e.type == "step_finished":
            for channel, values in (e.payload["trace"].get("readout_change") or {}).items():
                seen.setdefault(channel, []).extend(values)
    workflow = wanted.get("workflow")
    out["errors_drawn"] = [{k: e.get(k) for k in ("kind", "when", "target", "stage") if e.get(k) is not None} for e in key.get("errors") or []]
    out.update(faults_planted=sorted(p for p in faulty if p), faults_found=found, faults_missed=sorted(p for p in faulty if p and p not in found_parts),
               faults_called_passed=called_passed, false_findings=false, noise_flags=noise, errors_injected=len(key.get("errors") or []),
               truth_controls=len(truth), truth_found=len(named),
               workflow_done=None if workflow is None else all(w["value"] in seen.get(w["channel"], []) for w in workflow))
    return out


def run_one(device: Device, model: str, folder: pathlib.Path, run_id: str, config: AgentConfig | None = None, ledger: Ledger | None = None,
            authored: dict | None = None) -> dict[str, Any]:
    """One run on a fresh server. A run that crashes is a result, too."""
    process = System1Process(device, folder / run_id, run_id)
    system1 = None
    record: dict[str, Any] = {"run_id": run_id, "model": model, "seed": device.seed, "faults": device.faults, "error_rate": device.error_rate, "error_seed": device.error_seed, "fault_seed": device.fault_seed}
    log = RunLog(run_id, folder)
    started = time.monotonic()
    product = (authored or {}).get("title") or "Device under test"
    manual = Manual((authored or {})["manual_path"]) if (authored or {}).get("manual_path") else None
    request = TestRequest(request_id=run_id, product=product, revision=device.rev or "A")
    if authored:
        record.update(authored=authored["id"], rev=device.rev, effector=device.effector, manual=bool(manual))
    try:
        system1 = process.start()
        if model == "rules":
            report = run_test(system1, request, log)
        else:
            report = run_agent(system1, request, log, make_client(model, ledger=ledger or Ledger(), run=run_id), approve=sim_auto_approve, config=config, manual=manual)
        key = json.loads(process.key.read_text()) if process.key and process.key.is_file() else None
        build = json.loads(authored["build_key"].read_text()) if authored else None  # read here, after the run, by the scorer alone
        symptom = symptoms(authored["device_path"].parent) if authored else None
        record.update(score(report, read_events(log.path), key, build, symptom))
    except Exception as e:  # noqa: BLE001 - recovery is one of the things being measured
        record.update(crashed=f"{type(e).__name__}: {e}", finished=None, report_written=False)
    finally:
        if system1 is not None:
            try:
                system1.close()
            except Exception:  # noqa: BLE001, S110
                pass
        process.stop()
    record["seconds"] = round(time.monotonic() - started, 1)
    return record


def summarize(results: list[dict]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for model in sorted({r["model"] for r in results}):
        rows = [r for r in results if r["model"] == model]
        keyed = [r for r in rows if "faults_planted" in r]
        planted = sum(len(r["faults_planted"]) for r in keyed)
        out[model] = {
            "runs": len(rows), "reports": sum(bool(r.get("report_written")) for r in rows),
            "faults_found": sum(len(r["faults_found"]) for r in keyed), "faults_planted": planted,
            "runs_with_false_findings": sum(bool(r["false_findings"]) for r in keyed), "noise_flags": sum(len(r["noise_flags"]) for r in keyed), "faults_called_passed": sum(len(r.get("faults_called_passed", [])) for r in keyed),
            "mean_coverage": round(sum(r.get("covered", 0) / r["detected"] for r in rows if r.get("detected")) / max(1, sum(1 for r in rows if r.get("detected"))), 3),
            "tokens": sum(r.get("tokens", 0) for r in rows), "turns": sum(r.get("turns", 0) for r in rows),
            "tool_errors": sum(r.get("tool_errors", 0) for r in rows), "recoveries": sum(r.get("recoveries", 0) for r in rows),
            "errors_injected": sum(r.get("errors_injected", 0) for r in keyed), "crashes": sum(bool(r.get("crashed")) for r in rows),
            "wall_s": round(sum(r.get("seconds", 0) for r in rows), 1),
            "checkback": checkback_totals(rows),
            "median_turn_s": sorted(r["median_turn_s"] for r in rows if r.get("median_turn_s") is not None)[len([r for r in rows if r.get("median_turn_s") is not None]) // 2] if any(r.get("median_turn_s") is not None for r in rows) else None,
        }
    return out


def checkback_totals(rows: list[dict]) -> dict[str, int]:
    """How often check-back stepped in (plans refused) and caught something: an output that disagreed after a part moved,
    a read-back that failed, a closing look that differed from the first."""
    cbs = [r["checkback"] for r in rows if isinstance(r.get("checkback"), dict)]
    total = {k: sum(c.get(k, 0) for c in cbs) for k in ("plans_refused", "output_checks_failed", "checkbacks_run", "checkbacks_failed", "closing_looks", "side_effects")}
    total["runs_with_closing_differences"] = sum(bool(c.get("closing_differences")) for c in cbs)
    total["runs_where_it_caught_something"] = sum(bool(c.get("output_checks_failed") or c.get("checkbacks_failed") or c.get("closing_differences")) for c in cbs)
    total["runs"] = len(cbs)
    return total


def run_matrix(devices: list[str], faults: list[str], error_rates: list[float], models: list[str], repeats: int = 1, route: str = "depth",
               out: str | pathlib.Path = "runs", base_seed: int = 0, config: AgentConfig | None = None, budget: Budget | None = None, error_schedule: str | None = None) -> dict:
    stamp = time.strftime("eval-%m%d-%H%M%S")
    folder = pathlib.Path(out).resolve() / stamp
    folder.mkdir(parents=True, exist_ok=True)
    results = []
    n = 0
    stopped = None
    ledger = budget.ledger if budget else Ledger()
    for name in devices:
        seed = None if name == "C" else int(name)
        for fault in faults:
            for rate in error_rates:
                for repeat in range(repeats):
                    for model in models:
                        if budget and (why := budget.refuse(model)):
                            stopped = stopped or f"before a {model} run: {why}"
                            continue
                        n += 1
                        device = Device(seed=seed, faults=[] if fault == "none" else [fault], route=route, error_rate=rate, error_seed=base_seed + repeat, error_schedule=error_schedule,
                                        fault_seed=(seed or 0) * 1000 + base_seed + repeat if fault == "random" else None)  # a different fault on each repeat
                        run_id = f"{n:03d}-{model.replace(':', '-')}-{name}-{fault.replace(':', '-')}-{rate:g}-{repeat}"
                        results.append(run_one(device, model, folder, run_id, config, ledger))
                        (folder / "results.json").write_text(json.dumps({"results": results, "summary": summarize(results)}, indent=2, default=str) + "\n")
    return {"folder": str(folder), "results": results, "summary": summarize(results), "stopped": stopped}


def rescore(folder: str | pathlib.Path) -> dict:
    """Scores every run in an eval folder again from what it saved: the report, the events and the answer key. One scoring
    rule for every row, whenever it ran. The final report is what counts: a finding in it counts, whatever the summary says."""
    folder = pathlib.Path(folder)
    saved = json.loads((folder / "results.json").read_text())
    rows = []
    for r in saved["results"]:
        run = folder / r["run_id"]
        if (run / "report.json").is_file() and (run / "events.jsonl").is_file():
            key = json.loads((run / "answer_key.json").read_text()) if (run / "answer_key.json").is_file() else None
            found = find_authored(r["authored"]) if r.get("authored") else None
            build = json.loads(found["build_key"].read_text()) if found else None
            symptom = symptoms(found["device_path"].parent) if found else None
            r = {**r, **score(Report.model_validate_json((run / "report.json").read_text()), read_events(run / "events.jsonl"), key, build, symptom)}
        rows.append(r)
    return {"results": rows, "summary": summarize(rows)}


def run_authored(specs: list[str], models: list[str], error_rate: float = 0.0, error_seed: int = 0, error_schedule: str | None = None,
                   effector: str = "probe", out: str | pathlib.Path = "runs", config: AgentConfig | None = None, budget: Budget | None = None) -> dict:
    """Authored devices, each as `id:rev`, in the order given; every model on each before the next."""
    folder = pathlib.Path(out).resolve() / time.strftime("eval-%m%d-%H%M%S")
    folder.mkdir(parents=True, exist_ok=True)
    results, stopped, n = [], None, 0
    ledger = budget.ledger if budget else Ledger()
    for spec in specs:
        name, _, rev = spec.partition(":")
        authored = find_authored(name)
        for model in models:
            if budget and (why := budget.refuse(model)):
                stopped = stopped or f"before {model} on {spec}: {why}"
                continue
            n += 1
            device = Device(path=str(authored["device_path"]), rev=rev or "A", effector=effector, error_rate=error_rate, error_seed=error_seed, error_schedule=error_schedule)
            run_id = f"{n:03d}-{model.replace(':', '-')}-{name}-{rev or 'A'}"
            results.append(run_one(device, model, folder, run_id, config, ledger, authored))
            (folder / "results.json").write_text(json.dumps({"results": results, "summary": summarize(results)}, indent=2, default=str) + "\n")
    return {"folder": str(folder), "results": results, "summary": summarize(results), "stopped": stopped}
