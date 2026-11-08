// RAAV's design journey, for the wiki. docs/journey.md is the long form, with sources for every number.

export type Stage = "done" | "in progress" | "planned";

export interface Turn {
  when: string;
  stage: Stage;
  area: "Robot" | "Model" | "Product";
  title: string;
  problem: string;
  change: string;
  evidence?: string;
}

export const JOURNEY: Turn[] = [
  {
    when: "Nov 1–3", stage: "done", area: "Robot", title: "No CAD, no tags",
    problem: "The first sim knew each appliance's CAD and found it from a printed tag. That only works on products we've modelled.",
    change: "The robot finds and classifies controls itself. Every press ends on force, and touch fixes the last millimetre, as published button-pressing robots do.",
    evidence: "With CAD and a look first: 58 of 60 steps, against 18 of 60 blind",
  },
  {
    when: "Nov 3–4", stage: "done", area: "Robot", title: "Dropped the depth camera",
    problem: "A wrist depth camera was perfect in the sim. Modelled as the real stereo pair, it saw nothing on plain plastic.",
    change: "Measure depth from what a camera can actually see, and stop trusting a sensor model we hadn't checked.",
    evidence: "Real stereo model: 28 of 66 parts found, every door and display lost",
  },
  {
    when: "Nov 4", stage: "done", area: "Robot", title: "One $19 camera, plus touch",
    problem: "No depth sensor, and monocular depth networks were 1.6 to 8 times off at 12–20 cm.",
    change: "OWLv2 and SAM find parts in 2D, heights come from the shift between photos, and the fingertip measures the panel.",
    evidence: "Heights 93–95% within 1 mm. Touched plane 0.15–0.38 mm off",
  },
  {
    when: "Nov 4–5", stage: "done", area: "Robot", title: "Force from the servos alone",
    problem: "The skills assumed a perfect force sensor. Gear friction hides pushes from 0.4 N up to 16 N.",
    change: "Zero the estimate once the arm slows, ignore it until then, and keep thresholds above its noise.",
    evidence: "0 of 89 steps passed before, 84 of 89 after",
  },
  {
    when: "Nov 5", stage: "done", area: "Robot", title: "A pressure pad on the fingertip",
    problem: "The sim's point contacts put a whole push on one cell, so presses ran to 10–15 N.",
    change: "Spread each contact over a disc, as the pad's rubber does. The clean signal let contact thresholds drop from 2.5 N to 0.3 N.",
    evidence: "Skills matrix: no missed steps with the pad, 4 with servos only",
  },
  {
    when: "Nov 5–6", stage: "done", area: "Robot", title: "Reviews on devices the builder never saw",
    problem: "Toggles failed most often: SAM's outline took in the lever, so flips stopped short.",
    change: "Trim the lever before measuring, and wait for the pad to pass the lever's centre. Each fix was checked by a second agent on fresh seeds.",
    evidence: "Toggle flips on fresh devices: 4 passing to 10 passing",
  },
  {
    when: "Nov 6", stage: "done", area: "Product", title: "Two systems, one narrow channel",
    problem: "A model turn takes seconds, the control loop runs at 50 Hz, and a prompt must never drive a joint.",
    change: "System 1 owns the arm and verdicts. System 2 only starts named routines, and telemetry goes to the screen, never the model.",
    evidence: "No tool moves a joint. Every parameter is clamped by the robot",
  },
  {
    when: "Nov 7", stage: "done", area: "Robot", title: "The sim, rebuilt from bench measurements",
    problem: "The camera and servo numbers came from datasheets and guesses.",
    change: "Measured field of view, lens fit, servo dead zone and jitter on the team's parts, and surveyed with the wrist camera.",
    evidence: "16 unseen devices: 110 of 115 tests passed, 0 false failures",
  },
  {
    when: "Nov 7", stage: "done", area: "Model", title: "An honest test world for a model",
    problem: "One planted fault meant a model could look good by luck, and a robot slip followed by a clean retest still reported a broken device.",
    change: "Random faults from a catalogue, a 5% chance per action that the arm misbehaves, an answer key only the scorer reads, and a retest rule in code: repeat failures fail, a failure then passes is intermittent.",
    evidence: "Injected errors change the world, never the verdict",
  },
  {
    when: "Nov 7", stage: "done", area: "Model", title: "General, not taught to the test",
    problem: "Tuning prompts on the devices we score on would make the results meaningless.",
    change: "No device names in prompts or harness, devices differ only by data, and dev, validation and held-out sets are kept apart.",
    evidence: "A test scans prompts for device vocabulary and fails on a match",
  },
  {
    when: "Nov 7", stage: "done", area: "Model", title: "Four models through one route",
    problem: "The first probe hit quota limits, an overload error and an 85-second turn.",
    change: "Compare Claude Haiku 5.5, Claude Sonnet 5.5, GPT-5.4 and Grok 4.7 through Snowflake Cortex, with shared prompts and the model as a config value.",
    evidence: "Round 1: all four scored 1.00, the rules baseline 0.49",
  },
  {
    when: "Nov 7", stage: "in progress", area: "Model", title: "Harder rounds to separate the models",
    problem: "Round 1's short scenarios were too easy to rank the models.",
    change: "Round 2 runs on generated sim devices with arm errors. Round 3 is the centrifuge, Rev A and Rev B.",
  },
  {
    when: "Nov 7", stage: "in progress", area: "Product", title: "A vocabulary for devices",
    problem: "A model taught one appliance at a time learns that appliance, not appliances.",
    change: "Describe every device with shared pieces: parts, relations, procedures and test properties, so the model composes its tests from them.",
  },
  {
    when: "Nov 7", stage: "in progress", area: "Product", title: "Ten hand-made test devices",
    problem: "Generated devices vary in layout more than in how they work.",
    change: "Hand-made devices plus the centrifuge, each tagged with the theory pieces it exercises and split into dev, validation and held-out sets.",
  },
  {
    when: "Next", stage: "planned", area: "Robot", title: "The real arm",
    problem: "Every number so far is from simulation. Glare and real plastic are the largest unknowns.",
    change: "Bench tests first, then the full pipeline on the printed appliance with its planted fault.",
  },
];
