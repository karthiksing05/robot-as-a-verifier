# Demo video storyboard

**Draft 4, Nov 8.** Goes with [script.md](script.md). Target 2:45, 1920 × 1080 at 30 fps.

**For now, every robot shot is rendered in MuJoCo (sim).** The real arm hasn't run yet. We'll probably edit the cut and re-record those shots with real footage later (see "Real footage, later"). The `SIMULATION` tag rule stays as it is.

**Audio is a placeholder.** The voiceover and music are coming soon from Karthik. Until they arrive, the Sound column, the music cues and the licensing list below are placeholders, and the cut is timed to a natural read at the script's word rates.

## Look

### Act one: rustic chalk (0:00–1:31)

Act one carries the problem, what RAAV is, and the reasoning behind its design, so the "why not one model" argument is drawn in chalk (shots 13–15) and only becomes the product at the turn.

- **Board:** green slate (about `#2e4a3c`), not flat. A faint texture of old, half-erased writing sits under everything, with eraser swirls, a dusty chalk tray along the bottom edge, and slight vignetting at the corners.
- **Chalk:** white for the argument, **chalk yellow** for anything about the robot. The yellow matches the SO-101 and the Console's accent (`#eebc24`), so the chalk world and the product read as one thing. Lines are imperfect: they vary in pressure, skip on the grain, overshoot corners, and leave a little dust that drifts down. Letters are hand-printed, not a font.
- **The sketcher is a robot.** Whiteboard-explainer videos (the RSA Animate style) show a hand drawing continuously while the camera follows it, so the argument builds up stroke by stroke. Here the hand is a **chalk-sprite SO-101 arm**, drawn in chalk-yellow line work after the Console's mock arm (`components/Field.tsx`: yellow base and links, dark servo blocks, the two-finger gripper) and holding a stub of chalk in its jaws.
  - **It is always drawing.** While the voice talks, the arm's tip is writing; it never sits still for more than about a second.
  - **The camera follows the tip,** framing about a third of the board, with a slight lag and ease so it feels hand-held. When an idea completes, the camera pulls back to show how it connects to what's already drawn, then pushes in to the next empty patch.
  - **Pace:** one new drawn element every 2–3 s, matched to the voice's nouns. Text draws at about speaking speed; diagrams are sped up so they finish on their noun.
  - **Its tics:** it blows chalk dust off a line (a puff), taps the chalk twice to make a point, and wipes a mistake with the side of its jaw. Use each once or twice, not more.
- **Eraser wipe:** the stroke from the cold open is the transition between chalk scenes. A swipe clears a patch and the arm starts drawing in it.
- **Source lines:** tool names, dates and citations the voice can't fit are written small under each drawing. They're meant to be read on pause.

### The turn (1:31–1:34, on "System 1 is the robot")

The board holds the two halves from shots 14–15: the chalk arm's skeleton with its IK triangle on the left, the `context` bubble on the right. The arm taps the dividing line twice. Then, over about 3 s:
1. The dust lifts off every line on the board and hangs in the air.
2. The arm's chalk outline snaps clean, and fills in, in the left half, link by link from the base up, with the Console's solid render: yellow plastic, dark servos, a metal horn.
3. The green slate darkens into the Console's dark background, and a faint measurement grid fades in where the old writing was. The halves' chalk headings retype as `SYSTEM 1 · the robot` and `SYSTEM 2 · the model`.
4. The hanging dust settles into the grid as small points, which become the point cloud the arm will build in act two.
5. The chalk `RAAV` from shot 11 returns crisp, typed in Michroma: **RAAV · ROBOT AS A VERIFIER**.

A low synth pad enters under the piano on step 2 and the music lifts (placeholder until the music arrives).

### Act two: technical (1:34–2:45)

- **Background:** the Console's dark theme, with a fine grid and thin hairline rules. Labels in JetBrains Mono, as in the Console; titles in Michroma.
- **Colour:** the accent yellow for robot data, Console pass green and fail red for verdicts, everything else in greys.
- **Motion:** precise and quick, eased like the Console's UI. Nothing wobbles. Chalk appears only once more, as callout arrows on the CAD morph, as a deliberate echo of act one.
- **Tags:** `SIMULATION` in a small yellow tag at bottom right on all sim footage, which today is every robot shot (MuJoCo). Later, `REAL FOOTAGE · N×` on sped-up real clips.

### Freeze frames on robot footage

The footage runs at its own speed (sped up and tagged when real). At each key moment it freezes:
- The frame drops to about 40% saturation and dims, except the isolated element, which keeps full colour.
- A thin yellow outline traces the element, and a hairline leads to an overlay panel in the Console's style.
- A mono timestamp sits top left (`t = 00:41.2 · step 6/14`), so it reads as a record of that instant.
- Overlays build in about 0.4 s, hold, then the footage unfreezes with a short whoosh, never a hard cut.
- The voice keeps telling the story and never reads the overlay out. Each overlay is readable on pause, which is the point: it documents what the robot knew at that moment.

All overlay content comes from the run's own files (`events.jsonl`, traces and frames), never retyped by hand.

## Shots

Status: **have** means it exists now; **render** means we can make it ourselves from the repo; **film** means a camera is needed; **record** means voice or screen capture. Every **render (sim)** robot shot is MuJoCo for now. Every entry in the Sound column is a placeholder until Karthik's audio arrives.

| # | Time | Picture | Motion | On screen | Sound | Source | Status |
|---|---|---|---|---|---|---|---|
| 1 | 0:00–0:06 | Real chalkboard full of buzzwords (*autoformalization, agents, VLA, world models, scaling laws, self-driving labs, end-to-end, AGI, foundation models, verification*) around a big **?** | Static wide shot. Karthik walks in from the left and erases the board. **Play source 0:00.0–0:10.5 at 1.75×**, so 10.5 s of footage fills the 6.0 s slot; the erase finishes at about 0:05 on screen | | Chalk dust, eraser (sped up with the picture). Music starts on the last stroke | `video/real-world-assets/intro.MOV` (measured 25.5 s, 1920 × 1080, 59.94 fps) | **have** (trim and speed in the edit; the file itself stays untouched) |
| 2 | 0:06–0:16 | The cleared board. The chalk arm enters from the right edge and writes `ETH: 3-SAT in 2^εn ?`, then crosses out the `?` and writes `claimed false · Oct 2026`, with a Lean ✓ beside it. Under the ✓, small chalk notes: `Lean · Mathlib` · `Liquid Tensor Experiment · 2022` · `AlphaProof · IMO 2024 silver · 28/42` | Camera follows the tip; at "experts are still examining" the arm draws a magnifying glass over the ✓ | Small source lines: *Impagliazzo, Paturi & Williams, Oct 26 2026* · *Lean community, July 2022* · *Google DeepMind, July 2024* | VO 2a | Chalk animation | **render** |
| 3 | 0:16–0:25 | Flow lines curling into a vortex, a spike at its centre labelled `blow-up?`. Then a 6 × 6 grid of numbers; the arm rubs one cell out and writes a new number | Pull back to show the ETH drawing, push in to the vortex, then to the grid | `Navier–Stokes · Millennium Prize` · *DeepMind, Sept 2025* · `weights, edited directly` | VO 2b | Chalk animation | **render** |
| 4 | 0:25–0:31 | One big loop through all three drawings: *propose → verify → retry*, with a ✓ at `verify`. Along the board's bottom edge, a chalk ledger of verification tools: `Lean` · `Rocq (Coq) · Four Colour Theorem, 2005` · `Isabelle/HOL · seL4, 2009` · `TLA+ · AWS, 10 systems` · `autoformalization: words → Lean` | Camera pulls back to the whole left half; the loop starts to spin slowly; the ledger draws on left to right under it | `verified ✓` | VO 2c | Chalk animation | **render** |
| 5 | 0:31–0:38 | Two chalk plaques on the left. **CompCert** · `verified C compiler` · `Airbus: flight-control evaluation, 2012` · `MTU: nuclear emergency-generator engines, 2017` · `ATR 42/72 avionics, 2026`. **seL4** · `verified kernel` · `DARPA HACMS · Boeing Little Bird` · `red team couldn't break out, in flight`. Then a vertical line down the middle, `software \| hardware`, and an arrow from the plaques that stops at the line, dotted and broken | Camera on the plaques, then pans right with the arm as it draws the line | Small source lines: *compcert.org; Bedin França et al., ERTS 2012; AbsInt/MTU 2017* · *DARPA HACMS; seL4 Foundation* | VO 3a | Chalk animation | **render** |
| 6 | 0:38–0:45 | Right of the line: a clean CAD box of the centrifuge (✓), then the same box "in the world", drawn rougher. A finger-and-thumb pinch on the lid fin, then crossed out. The ✓ smudges | The arm wipes the ✓ with the side of its jaw; a `?` replaces it | `no pinch · ADA §309.4` · `no formal verification` | VO 3b | Chalk animation | **render** |
| 7 | 0:45–0:49 | Eraser wipe. Heading `BIOSAFETY`. A lab building over a buried drain pipe, with a crack and a tree root through it; a few dots seep out | The arm draws fast, then taps the crack twice | `Pirbright, UK, 2007 · foot-and-mouth` · *HSE: cracked, root-breached drains, most likely source* | VO 4 | Chalk animation | **render** |
| 8 | 0:49–0:53 | Heading `MECHANICAL DESIGN`. A stack of vacuum-cleaner prototypes that keeps growing, with a tally counting up to `5,127` | Camera tracks up the stack | *Dyson DC01: 5,127 prototypes, 15 years* | VO 4 | Chalk animation | **render** |
| 9 | 0:53–0:57 | Heading `AEROSPACE`. A folded sunshield beside a big loudspeaker; small fasteners fall from it | One quick drawing; the fasteners drop with a little chalk dust | *JWST, 2018: fasteners loose in an acoustic test · 29-month delay, ~$1B* | VO 4 | Chalk animation | **render** |
| 10 | 0:57–1:00 | Heading `APPLIANCES`. A row of appliance buttons, a hand pressing them, a clipboard | One quick drawing | `tested by hand` | VO 4 | Chalk animation | **render** |
| 11 | 1:00–1:08 | **What RAAV is, in chalk.** Eraser wipe. The arm writes `RAAV` large, then `Robot As A Verifier` under it. Below, a loop: a prototype and a manual → the arm → `measured: force · frames` → a report | The camera follows the letters, then pulls back for the loop as it draws | `prototype + manual in · measurements out` | VO 5 | Chalk animation (optional: cut in intro.MOV's own 0:11–0:20, Karthik writing RAAV, at about 3×) | **render** |
| 12 | 1:08–1:15 | A cloud labelled `model` above the loop, with an arrow `plans tests` into it. A second arrow from the cloud to `verdict` is drawn, then struck out; a short line from the arm's `measured` to `verdict` takes its place | The arm strikes the arrow and taps `verdict` twice | `model plans · sensors decide` | VO 5 | Chalk animation | **render** |
| 13 | 1:15–1:22 | **Why not one model, in chalk.** Eraser wipe. The arm draws one big box labelled `see + decide + move + judge`, fed from the left by a tall stack of film reels that keeps growing (`~1M demos`). It circles `judge` and draws an arrow from the box's output back into its own input | The camera follows the stack up as it grows, then pulls back to the whole box for the loop-back arrow | *OpenVLA, Kim et al. 2024: 970k demonstrations* · `who verifies the judge?` | VO 6 | Chalk animation | **render** |
| 14 | 1:22–1:27 | The arm wipes the box in half with the side of its jaw. In the left half it draws its own skeleton: an IK triangle from base to tip, and a small feedback loop (`target → error → command`) | Camera pushes in on the left half; the triangle's sides draw on, then the loop spins once | `inverse kinematics · classical control` · `solved, mostly` | VO 6 | Chalk animation | **render** |
| 15 | 1:27–1:31 | In the right half, a speech bubble with a `?`. Around it, small notes: `what to test?`, `what does this failure mean?`, `what next?` | The arm writes the notes around the bubble; camera pulls back to show both halves side by side | `context` | VO 6 continued | Chalk animation | **render** |
| 16 | 1:31–1:34 | **The turn** (see Look). The two chalk halves stay where they are and are inked: left becomes `SYSTEM 1 · the robot`, right `SYSTEM 2 · the model`. The chalk arm becomes the rendered SO-101 in the left half; the board becomes the Console's grid; the title appears | One continuous move, about 3 s | **RAAV · ROBOT AS A VERIFIER** | VO 7a. Music lifts, synth pad enters | Chalk animation into the Console arm render | **render** |
| 17 | 1:34–1:43 | Split frame. Left: sim footage of the arm, with four labels ticking on: *perception · control · safety · verdict rules*, and a `no LLM` badge. Right: the model's reasoning streaming in Live, with *plan · recover · diagnose* | Seven thin lines run between the halves like a bus, each labelled with a tool name (`system_status`, `scene_get`, `evidence_get`, `routine_start`, `routine_wait`, `routine_resume`, `routine_stop`); pulses travel along them. A ghost line labelled `move joint` tries to cross and is struck out at the boundary | `seven tools · no joint commands` · `SIMULATION` on the left | VO 7b | MuJoCo sim footage plus Console Live replay (`#/live?replay=…`) | **render** (sim) plus **record** |
| 18 | 1:43–1:51 | **Freeze frame F0** on the split: a routine request crossing the line (table below). Then each half gets its own small test badge | Freeze, overlay, unfreeze; badges tick on | `each side tested on its own` | VO 7b continued | Same footage; a run's `events.jsonl` | **render** (sim) |
| 19 | 1:51–1:57 | The centrifuge, then its manual. The Quick start lines highlight one at a time and turn into numbered plan steps | Pages fan open; highlighted lines slide right into a plan list | `MC-6 centrifuge` · `manual → plan` | VO 8a | `appliances/centrifuge` render and `manual.md`; plan from a sim run's events | **have** plus **render** |
| 20 | 1:57–2:06 | **Robot footage with freeze frames F1–F4** (table below): survey and map, then POWER, START and SPEED | Footage at 2× between freezes | `SIMULATION` | VO 8a–b | MuJoCo sim run on the centrifuge, `--device centrifuge --rev A --effector stock`, wrist camera, route rgb | **render** (sim) |
| 21 | 2:06–2:12 | The lid attempt, ending in **freeze frame F5**. A finding card slides in as the footage unfreezes | | `Lid · can't open · no lip to hook` · `SIMULATION` | VO 8c | Same MuJoCo run, plus the Console's finding card | **render** (sim) plus **record** |
| 22 | 2:12–2:19 | The lid in CAD, close up. Rev A's fin morphs into Rev B's hook lip. Chalk callout arrows, the one return of act one's look, point to the lip | A slow orbit while the geometry morphs | `Rev A → Rev B` · `proposed by the model · approved by a person` | VO 9a | `appliances/centrifuge/build/meshes_revA` and `meshes_revB` | **render** |
| 23 | 2:19–2:25 | Two-up: Rev A fails on the left, Rev B passes on the right. The score ticks up between them | Both clips start together; the right one's verdict turns green | `same tests · score ↑` · `SIMULATION` | VO 9b | MuJoCo sim runs of both revisions | **render** (sim) |
| 24 | 2:25–2:34 | Console B-roll: a run page with a force trace and its frame, Studies, Live, Design Analysis, the models page | Slow parallax pans, a cut every 2–3 s. Words drop over it | `lab instruments · appliances · assistive devices` · `12 appliances · 4 models · in simulation` | VO 10a | Console screen capture | **record** |
| 25 | 2:34–2:39 | Back to a dark board with a faint grid. Typed lines appear: *Proofs → Lean*, *Software → CompCert · seL4*, *Hardware → ?*. The `?` becomes the yellow arm | Each line on its beat | | VO 10b–c. Music swells | Motion graphic | **render** |
| 26 | 2:39–2:45 | Title card: **RAAV · ROBOT AS A VERIFIER**. Under it, the innovations one per line, then the team and MakeCU 2026 | Lines fade in on the beat; the music resolves at 2:44 | the innovations, team | Music out | Motion graphic | **render** |

### Cold open notes (shot 1)

- **Measured:** `intro.MOV` runs 25.5 s (ffprobe: 25.50 s, 1920 × 1080, 59.94 fps, with audio). Draft 3 only said "needs trimming", which implied real time.
- **What's in it:** 0:00–0:02.5 the full board, static; 0:02.5–0:03 Karthik walks in; about 0:03–0:09 he erases the board in several strokes, left to right; 0:09–0:10.5 he steps off the right edge; 0:11–0:20 he comes back and writes `RAAV`; 0:20–0:25.5 he leaves and the camera pushes in on `RAAV`.
- **Speed and trim:** use source 0:00.0–0:10.5 at **1.75×**, which lands at **6.0 s on screen** (0:00–0:06). The last eraser stroke falls at about 0:05.1 on screen, where the music starts. The board is clean at the cut, so the eraser-wipe transition into shot 2 matches.
- **Don't re-encode the original.** Speed it up in the edit (for example ffmpeg `setpts=PTS/1.75` and `atempo=1.75`, or the editor's speed control) from a copy of the clip.
- **Unused material:** the `RAAV` writing (0:11–0:20) can be cut into shot 11 at about 3× if you want the real board to echo there.
- **Tag:** the `REAL FOOTAGE · N×` tag is for robot footage, which is evidence. The cold open is staged and carries no tag (see Questions).

## Freeze frames (shots 18, 20 and 21)

Six freezes. F0 documents the boundary between the systems; F1–F5 each document one stage of the centrifuge run. Holds are timed to read once; the footage between them runs at 2×. All of it is MuJoCo footage for now.

| # | Freezes on | Isolated | Overlay shows | Hold | From |
|---|---|---|---|---|---|
| F0 | The split frame, as System 2 starts a routine | The bus between the halves | The tool call as it crossed, from the run log: `routine_start · run_plan · 6 steps`. On System 1's side, its answer: each parameter checked against its own limits (for example a requested force beside the 14 N step limit, which is rejected rather than clamped if exceeded), then `accepted`. A dimmed `move joint` call sits beside it with `no such tool`. Tags: `System 2 asks` on the right, `System 1 decides how` on the left | 2.5 s | The run's `events.jsonl` |
| F1 | The wrist camera's first look at the panel, during the survey | The control panel | OWLv2 boxes, then SAM outlines tracing each control, each with its label and kind: `POWER · toggle`, `START · button`, `STOP · button`, `TIME+ · button`, `SPEED · dial`, `lid handle`. Corner note: `one $19 wrist camera` | 2.0 s | The run's perception frame and detections |
| F2 | The arm mid-scan, after a few nearby photos | The arm and the panel | The 3D map building: a point cloud from the shift between photos settles onto the panel, then a fingertip tap marks the touched plane with a small ring. Labels: `heights from nearby photos` · `plane from touch` | 2.0 s | The run's scene inventory and map |
| F3 | The moment before the first press | The plan, beside the arm | The model's plan line for this step, as it appears in the run log, for example `step 3 · press START · expect display to count down`, with a hairline to the START outline. A small tag: `planned by System 2` | 1.5 s | The run's plan events |
| F4 | START at full press | The fingertip on START | A force trace growing left to right, with a dashed line for the 15 N safety cap well above it, and the press's peak marked. Then the verdict rule's line types in green, for example `pressed · display changed → pass`, with the tag `decided by System 1` | 2.5 s | The step's trace and verdict |
| F5 | The jaw sliding off the lid fin | The jaw and the fin | A close-up inset of the fin with no lip; the force trace drops to zero as the jaw slips; the lid angle readout stays at `0°`. The retest rule fires: `failed · retested · failed again → fail`, in red, with `decided by System 1` | 2.5 s | The lid step's trace, frames and verdict |

Exact rule text, numbers and step numbers come from whichever sim run we film; the examples above show the shape, not values to retype.

## Music

**Placeholder.** Karthik is bringing the voiceover and music soon. The brief and cues below are what we'd ask for; swap them for what he brings.

**Brief:** soft, inspirational piano with light strings or felt marimba, about 90–100 BPM, and a low synth pad that enters only at the turn.

| Time | Cue |
|---|---|
| 0:05 | Piano enters on the last eraser stroke, sparse |
| 0:06–1:31 | Quiet under the voice. A small lift at 0:25 when the loop starts spinning, back down for "it ends where software ends" at 0:35, a brighter figure under "So we built RAAV" at 1:00, and a darker chord under "the model that acts would also be the judge" at 1:20 |
| 1:31 | The turn: strings and the synth pad come in, the beat steadies |
| 1:43 and 1:57–2:12 | Thins out. Each freeze frame lands on a soft hit, and the music holds a note through it |
| 2:12 | Picks up for the fix |
| 2:34 | Swells for the close |
| 2:44 | Resolves within the last second |

No lyrics, and nothing that fights the voiceover in the 1–4 kHz range.

**Licensing:** the video will be public, so the track needs a licence that covers that, ideally with no attribution required and no Content ID claims. These candidates need auditioning (only if Karthik's track doesn't cover it):

| Source | Why | Check |
|---|---|---|
| YouTube Studio Audio Library | Free, filterable by mood (Inspirational) and by "no attribution required" | Each track's own credit line |
| Pixabay Music | Free under its content licence; many soft piano tracks | The licence page, and whether the track is registered for Content ID |
| [BudgetPixel](https://budgetpixel.com/background-music/uplifting-cinematic-piano-led-orchestral-6401f38b) | Lists uplifting piano tracks as royalty-free with no attribution | AI-generated; read the exact terms |
| [Silverman Sound, "Spark of Inspiration"](https://www.silvermansound.com/free-music/spark-of-inspiration) | Close to the brief | The free version appears to need a credit line |

## Real footage, later

For now every robot shot (17, 18, 20, 21 and 23) is rendered in MuJoCo and tagged `SIMULATION`. The real arm hasn't run yet and Rev B hasn't been printed. We'll probably edit the cut and re-record real footage later: when the arm runs on the printed centrifuge, re-film shots 20, 21 and 23 (and the left half of 17 if it's worth it), speed them up, and change the tag to `REAL FOOTAGE · N×` with the true factor. The freeze frames carry over unchanged: they're built from the run's files, which look the same for sim and real. The cuts are timed so a real clip can replace a sim clip of the same length without re-editing anything else.

## How we'd make it, after your OK

- **Chalk scenes:** drawn in code. Each stroke is a path that the chalk arm's tip follows, with a chalk-texture brush, dust particles and a following camera. Rendered frame by frame, so the timing is exact.
- **The turn:** the same renderer, cross-fading the chalk arm into the Console's arm drawing.
- **Sim clips and freeze frames:** recorded from the existing MuJoCo sim on the centrifuge (Rev A and Rev B), with overlays drawn from the run's files. This only runs System 1's code; we don't change it.
- **Console B-roll:** scripted browser captures at 1080p, so they can be re-shot after any UI change.
- **Cold open:** trimmed and sped to 1.75× in the edit from a copy of `intro.MOV`.
- **Voiceover and music:** coming from Karthik. Until then, a placeholder read keeps the timing honest.
- **Assembly:** ffmpeg, from an edit list in this folder, so any shot can be swapped and the whole video rebuilt with one command.

## Claims on screen

Every number or source line on screen is from the script's [checks table](script.md#checks-before-recording) and [Sources](script.md#sources). Extra on-screen items:

| On screen | Holds because | Watch for |
|---|---|---|
| `Lean · Mathlib` · `Liquid Tensor Experiment · 2022` · `AlphaProof · IMO 2024 silver · 28/42` (shot 2) | Script sources 12–14 | AlphaProof's IMO problems were translated into Lean by hand first; don't write "autoformalized the IMO" |
| `Rocq (Coq) · Four Colour Theorem, 2005` · `Isabelle/HOL · seL4, 2009` · `TLA+ · AWS, 10 systems` · `autoformalization: words → Lean` (shot 4) | Script sources 15, 16, 20, 23; AlphaProof's model was fine-tuned to turn natural-language problems into formal statements (source 12); Hales on FLT (source 11) | "10 systems" was AWS's count at the time of writing (2014–15) |
| CompCert plaque (shot 5) | Script sources 17–19 | The 2012 Airbus line is an evaluation, so write `evaluation`. The ATR line is a 2026 qualification "with guidance from Airbus" |
| seL4 plaque (shot 5) | Script sources 20–22 | The red team was given a partition and couldn't break out; write that, not "unhackable" |
| `no pinch · ADA §309.4` | Access Board guide to §309.4 (script source 9) | It's a US building standard. Use it as the reason the rule exists, not as a claim that appliances must meet it |
| `Pirbright, UK, 2007` (shot 7) | HSE final report, via script source 24 | Keep "most likely source" |
| `Dyson DC01: 5,127 prototypes, 15 years` (shot 8) | Script source 25 | Other Dyson accounts say five years from a different start; keep "15 years" with this source |
| `JWST, 2018 … 29-month delay, ~$1B` (shot 9) | Script source 26 | Write "acoustic test" only with this source; others say vibration test |
| `inverse kinematics · classical control` (shot 14) | System 1 uses IK and fixed policies (`system-1/README.md`) | Don't write MPC or LQR on the board unless labelled as general classical control, not RAAV's stack |
| `~1M demos` (shot 13) | OpenVLA abstract: 970k real-world robot demonstrations (script source 10) | Keep the source line visible while the number is |
| `14 N` step limit (F0) | `docs/decisions.md` D31: a step may ask for at most 14 N, rejected above that | Use the value from the filmed run |
| `15 N safety cap` (F4) | `docs/decisions.md` D34: "The 15 N cap is unchanged" | Re-check the value before rendering |

## Sources

All claim sources are listed in [script.md](script.md#sources). The style reference for the chalk scenes is the RSA Animate series of whiteboard explainers (a hand drawing continuously, the camera following it); it is a visual reference only, not cited on screen.

## Questions for Karthik

1. **The cold open:** `intro.MOV` is in `video/real-world-assets/`. Is that the final take, or will you re-film it? And is 1.75× the speed you want, or faster still?
2. **Tag on the cold open:** it's real footage sped up 1.75×, but it's staged, not evidence. Leave it untagged, or add `REAL FOOTAGE · 1.75×` for consistency?
3. **How much text on the chalk board:** the source lines under each drawing (shots 2–5 and 7–9) are small, and shots 4 and 5 now carry a lot. Keep them, or move all sources to an end card?
4. **Freeze-frame count:** five centrifuge freezes in about 15 s is dense at 2:45. Drop F2 (the map), or take the 3:00 option in the script?
5. **The turn:** RAAV is now named in chalk at 1:00 and the crisp title lands at 1:31. Fine, or should the turn move up to 1:00 and "why not one model" be drawn in the technical style?
