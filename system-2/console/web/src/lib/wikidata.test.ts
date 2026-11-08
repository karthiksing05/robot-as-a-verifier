import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { JOURNEY } from "./journey";
import { deviceCards, demoHref, fmtCredits, fmtRatio, fmtTokens, fmtUsd, listOf, loadResults, pieceName, sections, tiedOnScore } from "./wikidata";

const committed = JSON.parse(fs.readFileSync(path.join(import.meta.dirname, "../data/model-results.json"), "utf8"));

describe("model results", () => {
  it("reads the committed file: every finished round but the partial one has four models and the baseline", () => {
    const r = loadResults(committed);
    expect(r.rounds.map((x) => [x.id, x.status])).toEqual([["1", "done"], ["2", "done"], ["2b", "done"], ["2c", "done"], ["3", "done"], ["3b", "done"], ["3m", "done"], ["3c", "done"], ["4", "planned"]]);
    const all = ["claude-haiku-5-5", "claude-sonnet-5-5", "openai-gpt-5.4", "grok-4.7", "rules"];
    for (const round of r.rounds.slice(0, 6)) expect(round.rows.map((x) => x.model)).toEqual(all);
    expect(r.rounds[6].rows.map((x) => x.model)).toEqual(["claude-haiku-5-5"]);
    expect(r.rounds[0].rows.filter((x) => !x.baseline).every((x) => x.score === 1)).toBe(true);
    expect(r.rounds[7].rows.map((x) => x.model)).toEqual(all);
    expect(r.rounds[8].rows).toEqual([]);
  });

  it("says when a round can't rank the models on score", () => {
    const r = loadResults(committed);
    expect(tiedOnScore(r.rounds[0])).toBe(true);
    const split = { ...r.rounds[0], rows: r.rounds[0].rows.map((x, i) => ({ ...x, score: i === 0 ? 0.5 : x.score })) };
    expect(tiedOnScore(split)).toBe(false);
  });

  it("survives a malformed file without inventing numbers", () => {
    const r = loadResults({ rounds: [{ id: 9, status: "weird", rows: [{ model: "m" }] }, { id: 2, status: "done", rows: [{ model: "x", score: "high" }] }] });
    expect(r.rounds[0].status).toBe("planned");
    expect(r.rounds[0].rows).toEqual([]);
    expect(r.rounds[1].rows[0].score).toBeNull();
    expect(r.rounds[1].rows[0].tokens).toBe(0);
    expect(loadResults(undefined).rounds).toEqual([]);
  });

  it("carries credits and assumed dollars for every finished round, per model and per run", () => {
    const r = loadResults(committed);
    expect(r.pricing?.usd_per_credit).toBe(2);
    expect(r.pricing?.usd_is).toMatch(/assumption/);
    for (const round of r.rounds.filter((x) => x.status === "done")) {
      expect(round.cost).not.toBeNull();
      for (const row of round.rows.filter((x) => !x.baseline)) {
        expect(row.credits).toBeGreaterThan(0);
        expect(row.usd).toBeCloseTo((row.credits ?? 0) * 2, 3);
        expect(row.per_run.length).toBe(row.runs);
      }
    }
    expect(r.rounds[8].cost).toBeNull();
    expect(fmtCredits(0.004)).toBe("<0.01");
    expect(fmtUsd(5.0082)).toBe("$5.01");
    expect(fmtUsd(null)).toBe("–");
  });

  it("formats counts plainly", () => {
    expect(fmtTokens(388590)).toBe("389k");
    expect(fmtTokens(1_234_000)).toBe("1.23M");
    expect(fmtRatio(2, 2)).toBe("2 of 2");
    expect(fmtRatio(0, 0)).toBe("–");
  });
});

describe("device docs", () => {
  const md = [
    "# Devices", "Ten devices and the centrifuge.",
    "## Kettle", "- **Split:** dev", "- **Controls:** button, `toggle`, dial", "- **Theory:** interlock, sequence", "- **Project:** sim-kettle", "- **Fault:** stuck button", "Boils water.",
    "## Vault", "**Faults:** door never latches", "- **Split:** held out", "- **Controls:** keypad", "The fault list lives with the scorer.", "A safe with a keypad.",
  ].join("\n");

  it("makes one card per device, with controls, theory pieces and a Demo link", () => {
    const [kettle] = deviceCards(md);
    expect(kettle.name).toBe("Kettle");
    expect(kettle.controls).toEqual(["button", "toggle", "dial"]);
    expect(kettle.theory).toEqual(["interlock", "sequence"]);
    expect(demoHref(kettle)).toBe("#/live?project=sim-kettle");
    expect(kettle.extra).toEqual([["Fault", "stuck button"]]);
  });

  it("never shows a held-out device's faults, wherever they sit in its section", () => {
    const vault = deviceCards(md)[1];
    expect(vault.heldOut).toBe(true);
    expect(JSON.stringify(vault)).not.toMatch(/fault|latch/i);
    expect(vault.body.join(" ")).toContain("A safe with a keypad.");
    expect(demoHref(vault)).toBe("#/live");
  });

  it("keeps the intro apart and handles a missing doc", () => {
    expect(sections(md).intro.join("").trim()).toBe("Ten devices and the centrifuge.");
    expect(deviceCards(null)).toEqual([]);
  });
});

describe("the device gallery, from docs/devices.md", () => {
  const docs = JSON.parse(fs.readFileSync(path.join(import.meta.dirname, "../data/wiki-docs.json"), "utf8"));
  const registry = JSON.parse(fs.readFileSync(path.join(import.meta.dirname, "../../../../../appliances/registry.json"), "utf8")) as { id: string; split: string; revs: string[] }[];
  const cards = deviceCards(docs.devices);

  it("has a card for every device in system-1's registry, with its split and revisions", () => {
    expect(cards.map((c) => c.id).sort()).toEqual(registry.map((d) => d.id).sort());
    for (const d of registry) {
      const card = cards.find((c) => c.id === d.id)!;
      expect(card.revisions).toEqual(d.revs);
      expect(card.heldOut).toBe(d.split === "held_out");
      expect(card.theory.length).toBeGreaterThan(3);
      expect(card.body.join(" ").trim().length).toBeGreaterThan(40);
      expect(demoHref(card)).toBe(`#/live?project=${d.id}`);
    }
  });

  it("names what's planted on dev and validation devices, and nothing about a held-out one's", () => {
    expect(cards.find((c) => c.id === "wall-thermostat")!.planted).toMatch(/F1/);
    for (const card of cards.filter((c) => c.heldOut)) {
      expect(card.planted).toBeNull();
      expect(JSON.stringify(card)).not.toMatch(/fault|\bF[0-9]\b/i);
    }
  });

  it("splits lists where they aren't inside brackets", () => {
    expect(listOf("POWER toggle; START, STOP and TIME+ buttons; display. No power switch.")).toEqual(["POWER toggle", "START, STOP and TIME+ buttons", "display", "No power switch"]);
    const theory = listOf("enables (power), displays (mode and setpoint; light by mode), and a timed `running` mode.");
    expect(theory).toEqual(["enables (power)", "displays (mode and setpoint; light by mode)", "a timed running mode"]);
    expect(theory.map(pieceName)).toEqual(["enables", "displays", "a timed running mode"]);
  });
});

it("journey entries are complete and say RAAV, not RAV", () => {
  for (const t of JOURNEY) {
    expect(t.title && t.problem && t.change).toBeTruthy();
    expect(JSON.stringify(t)).not.toMatch(/\bRAV\b/);
  }
});
