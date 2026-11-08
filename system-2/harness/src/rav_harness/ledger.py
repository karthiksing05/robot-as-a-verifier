"""What the models have cost, across every run and restart: one line per call in a file that's only ever appended to.

    rav spend                 the total, per model
    rav eval --budget-usd 20  stops before starting a run that could cross the cap

Prices come from a table anyone can edit (config/model_prices.json): Snowflake AI credits per million tokens, and one
dollar rate per credit, which is an assumption and says so. A model with no price is reported in tokens, and costs nothing
here only because nobody has said what it costs.
"""
from __future__ import annotations

import json
import os
import pathlib
import threading
import time
from dataclasses import dataclass

from .model import REPO, LedgeredClient, ModelReply  # noqa: F401 - LedgeredClient is used with a Ledger

LEDGER = pathlib.Path(os.environ.get("RAV_LEDGER") or REPO / "system-2/runs/model_ledger.jsonl")  # tests point it elsewhere
PRICES = REPO / "system-2/harness/config/model_prices.json"


def wire_name(model: str) -> str:
    return model.split(":", 1)[-1]


USD_PER_CREDIT = 2.0  # used only if the table doesn't say


def usd_per_credit(path: pathlib.Path = PRICES) -> float:
    """Dollars per AI credit: an assumption kept in the price table, not a quoted price."""
    if not path.is_file():
        return USD_PER_CREDIT
    return float(json.loads(path.read_text()).get("usd_per_credit") or USD_PER_CREDIT)


def load_prices(path: pathlib.Path = PRICES) -> dict[str, dict]:
    if not path.is_file():
        return {}
    return {name: p for name, p in json.loads(path.read_text()).get("models", {}).items() if p.get("input") is not None and p.get("output") is not None}


def cost_of(row: dict, prices: dict[str, dict]) -> float | None:
    """AI credits for one call, or None if there's no price. The ledger's input includes cache reads and writes, so those
    come off before the plain input rate applies; each costs its own rate when the table has one."""
    price = prices.get(wire_name(row["model"]))
    if price is None:
        return None
    cached, wrote = row.get("cached") or 0, row.get("cache_write") or 0
    plain = max(0, (row.get("input") or 0) - cached - wrote)
    out = (row.get("output") or 0) + (row.get("thinking") or 0)
    return (plain * price["input"] + cached * price.get("cached_input", price["input"]) + wrote * price.get("cache_write", price["input"]) + out * price["output"]) / 1e6


class Ledger:
    def __init__(self, path: pathlib.Path | str = LEDGER):
        self.path, self.lock = pathlib.Path(path), threading.Lock()

    def record(self, reply: ModelReply, run: str | None = None, error: str | None = None) -> None:
        row = {"at": round(time.time(), 1), "run": run, "model": reply.model, **({"error": error} if error else {}), "input": reply.tokens_in or 0, "output": reply.tokens_out or 0, "thinking": reply.tokens_thinking or 0,
               "cached": reply.tokens_cached or 0, "cache_write": reply.tokens_cache_write or 0, "latency_ms": reply.latency_ms}
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a") as f:  # flushed and closed per call, so a crash loses nothing
                f.write(json.dumps(row) + "\n")
                f.flush()
                os.fsync(f.fileno())

    def rows(self) -> list[dict]:
        if not self.path.is_file():
            return []
        return [json.loads(line) for line in self.path.read_text().splitlines() if line.strip()]


@dataclass
class Totals:
    calls: int = 0
    input: int = 0
    output: int = 0
    cached: int = 0
    cost: float = 0.0  # AI credits
    unpriced_calls: int = 0
    latency_ms: float = 0.0

    @property
    def tokens(self) -> int:
        return self.input + self.output


def totals(rows: list[dict], prices: dict[str, dict]) -> dict[str, Totals]:
    out: dict[str, Totals] = {}
    for row in rows:
        t = out.setdefault(wire_name(row["model"]), Totals())
        t.calls += 1
        t.input += row.get("input") or 0
        t.output += (row.get("output") or 0) + (row.get("thinking") or 0)
        t.cached += row.get("cached") or 0
        t.latency_ms += row.get("latency_ms") or 0
        cost = cost_of(row, prices)
        if cost is None:
            t.unpriced_calls += 1
        else:
            t.cost += cost
    return out


def spend_table(ledger: Ledger | None = None, prices: dict[str, dict] | None = None, rate: float | None = None) -> str:
    rows = (ledger or Ledger()).rows()
    prices = load_prices() if prices is None else prices
    rate = usd_per_credit() if rate is None else rate
    all_totals = totals(rows, prices)
    lines = [f"{'model':<34}{'calls':>7}{'input':>11}{'cached':>11}{'output':>10}{'avg s':>8}{'credits':>10}{'USD':>10}"]
    for name, t in sorted(all_totals.items()):
        credits, usd = (f"{t.cost:.4f}", f"{t.cost * rate:.4f}") if not t.unpriced_calls else ("no price", "")
        lines.append(f"{name:<34}{t.calls:>7}{t.input:>11}{t.cached:>11}{t.output:>10}{t.latency_ms / max(1, t.calls) / 1000:>8.1f}{credits:>10}{usd:>10}")
    unpriced = sum(t.unpriced_calls for t in all_totals.values())
    credits = sum(t.cost for t in all_totals.values())
    lines.append(f"total: {sum(t.tokens for t in all_totals.values())} tokens, {credits:.4f} credits, ${credits * rate:.4f} at an assumed ${rate:.2f} per credit"
                 + (f", plus {unpriced} calls with no price" if unpriced else ""))
    return "\n".join(lines)


def run_spend(rows: list[dict], prices: dict[str, dict] | None = None, rate: float | None = None) -> dict:
    """Tokens, credits and dollars for a set of ledger rows (one run, or a round)."""
    prices = load_prices() if prices is None else prices
    rate = usd_per_credit() if rate is None else rate
    costs = [cost_of(r, prices) for r in rows]
    credits = sum(c or 0 for c in costs)
    return {"calls": len(rows), "tokens": sum((r.get("input") or 0) + (r.get("output") or 0) + (r.get("thinking") or 0) for r in rows),
            "credits": round(credits, 4), "usd": round(credits * rate, 4), "unpriced_calls": sum(c is None for c in costs)}


RUN_GAP_S = 600.0  # a run never waits this long between model calls; the same label after that is another run


class Budget:
    """Decides whether another run may start. A run can cost as much as the dearest one measured so far on that model, plus
    a margin; before anything's been measured, a conservative guess from the token cap."""

    def __init__(self, budget_usd: float | None = None, ledger: Ledger | None = None, prices: dict[str, dict] | None = None, no_price_ok: bool = False,
                 token_cap: int | None = None, first_run_tokens: int = 60_000, margin: float = 1.5, rate: float | None = None):
        self.budget_usd, self.ledger, self.no_price_ok, self.token_cap = budget_usd, ledger or Ledger(), no_price_ok, token_cap
        self.prices = load_prices() if prices is None else prices
        self.rate = usd_per_credit() if rate is None else rate  # dollars per credit
        self.first_run_tokens, self.margin = first_run_tokens, margin

    def _worst_run(self, model: str) -> tuple[float | None, int]:
        per_run: dict[tuple[str, int], list[dict]] = {}
        last: dict[str, tuple[float, int]] = {}  # label -> (time of its last call, which run of that label)
        for row in sorted(self.ledger.rows(), key=lambda r: r.get("at", 0)):
            if wire_name(row["model"]) != wire_name(model):
                continue
            label, at = str(row.get("run")), row.get("at", 0)
            seen, n = last.get(label, (None, 0))
            if seen is not None and at - seen > RUN_GAP_S:  # labels repeat across rounds: a long silence starts another run
                n += 1
            last[label] = (at, n)
            per_run.setdefault((label, n), []).append(row)
        if not per_run:
            return None, self.first_run_tokens
        costs = [sum(cost_of(r, self.prices) or 0 for r in rows) * self.rate for rows in per_run.values()]
        tokens = [sum((r.get("input") or 0) + (r.get("output") or 0) + (r.get("thinking") or 0) for r in rows) for rows in per_run.values()]
        return max(costs), max(tokens)

    def spent(self) -> tuple[float, int]:
        rows = self.ledger.rows()
        return sum(cost_of(r, self.prices) or 0 for r in rows) * self.rate, sum((r.get("input") or 0) + (r.get("output") or 0) + (r.get("thinking") or 0) for r in rows)

    def refuse(self, model: str) -> str | None:
        """Why this run mustn't start, or None."""
        if model == "rules":
            return None
        price = self.prices.get(wire_name(model))
        spent, tokens = self.spent()
        worst_cost, worst_tokens = self._worst_run(model)
        if price is None and not self.no_price_ok:
            return f"{wire_name(model)} has no price in {PRICES.name}. Add one, or pass --no-price-ok to cap by tokens"
        if price is None or self.budget_usd is None:
            if self.token_cap is not None and tokens + worst_tokens * self.margin > self.token_cap:
                return f"{tokens} tokens used and a run could add {worst_tokens * self.margin:.0f}: over the cap of {self.token_cap}"
            return None
        if worst_cost is None:
            worst_cost = self.first_run_tokens * max(price["input"], price["output"]) / 1e6 * self.rate
        if spent + worst_cost * self.margin > self.budget_usd:
            return f"${spent:.2f} spent and a run could add ${worst_cost * self.margin:.2f}: over the ${self.budget_usd:.2f} budget"
        return None
