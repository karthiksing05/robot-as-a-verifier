# Demo video storyboard

**Draft 5, Nov 8.** Goes with [script.md](script.md). Target 2:45, 1920 × 1080 at 30 fps.

**What changed from Draft 4:** we get to RAAV and the robot sooner. The problem is one short chalk section (shots 2–4), the turn moves to 0:23, and the first robot footage is on screen at 0:26. The "why not one model" beat is now about VLAs in general and is drawn in the technical style. The tool plaques and field vignettes that used to open the video now form a chalk coda at 1:59–2:25, just before the close.

**For now, every robot shot is rendered in MuJoCo (sim).** The real arm hasn't run yet. We'll probably edit the cut and re-record those shots with real footage later (see "Real footage, later"). The `SIMULATION` tag rule stays as it is.

**Audio is a placeholder.** Karthik will record the voiceover himself as an mp3, and the music is coming from him too. Until they arrive, the Sound column, the music cues and the licensing list are placeholders. **The final cut will be re-timed to his recording**: the timestamps below are targets for a natural read at the script's word rates, and each shot will stretch or shrink to match his actual lines.

## Look

### Act one: rustic chalk (0:00–0:23)

Act one states the problem, briefly. It's chalk because it's an argument, not the product.

- **Board:** green slate (about `#2e4a3c`), not flat. A faint texture of old, half-erased writing sits under everything, with eraser swirls, a dusty chalk tray along the bottom edge, and slight vignetting at the corners.
- **Chalk:** white for the argument, **chalk yellow** for anything about the robot. The yellow matches the SO-101 and the Console's accent (`#eebc24`), so the chalk world and the product read as one thing. Lines are imperfect: they vary in pressure, skip on the grain, overshoot corners, and leave a little dust that drifts down. Letters are hand-printed, not a font.
- **The sketcher is a robot.** Whiteboard-explainer videos (the RSA Animate style) show a hand drawing continuously while the camera follows it, so the argument builds up stroke by stroke. Here the hand is a **chalk-sprite SO-101 arm**, drawn in chalk-yellow line work after the Console's mock arm (`components/Field.tsx`: yellow base and links, dark servo blocks, the two-finger gripper) and holding a stub of chalk in its jaws.
  - **It is always drawing.** While the voice talks, the arm's tip is writing; it never sits still for more than about a second.
  - **The camera follows the tip,** framing about a third of the board, with a slight lag and ease so it feels hand-held. When an idea completes, the camera pulls back to show how it connects to what's already drawn, then pushes in to the next empty patch.
  - **Pace:** one new drawn element every 2–3 s, matched to the voice's nouns. Text draws at about speaking speed; diagrams are sped up so they finish on their noun.
  - **Its tics:** it blows chalk dust off a line (a puff), taps the chalk twice to make a point, and wipes a mistake with the side of its jaw. Use each once or twice, not more.
- **Eraser wipe:** the stroke from the cold open is the transition between chalk scenes. A swipe clears a patch and the arm starts drawing in it.
- **Source lines:** citations the voice can't fit are written small under each drawing, to be read on pause.

### The turn (0:23–0:26, on "So we built RAAV")

The board holds the problem: the Lean ✓, the `software | hardware` line, the crossed-out pinch on the CAD lid, the hand at the buttons. The arm taps the dividing line twice. Then, over about 3 s:
1. The dust lifts off every line on the board and hangs in the air.
2. The arm's chalk outline snaps clean, and fills in, link by link from the base up, with the Console's solid render: yellow plastic, dark servos, a metal horn.
3. The green slate darkens into the Console's dark background, and a faint measurement grid fades in where the old writing was.
4. The hanging dust settles into the grid as small points, which become the point cloud the arm will build later.
5. The title types in Michroma, crisp: **RAAV · ROBOT AS A VERIFIER**.

A low synth pad enters under the piano on step 2 and the music lifts (placeholder until the music arrives).

### Act two: technical (0:26–1:59)

- **Background:** the Console's dark theme, with a fine grid and thin hairline rules. Labels in JetBrains Mono, as in the Console; titles in Michroma.
- **Colour:** the accent yellow for robot data, Console pass green and fail red for verdicts, everything else in greys.
- **Motion:** precise and quick, eased like the Console's UI. Nothing wobbles. Chalk appears in act two only as callout arrows on the CAD morph, a deliberate echo of act one.
- **Tags:** `SIMULATION` in a small yellow tag at bottom right on all sim footage, which today is every robot shot (MuJoCo). Later, `REAL FOOTAGE · N×` on sped-up real clips.

### Coda: chalk returns (1:59–2:25)

"Why this matters" goes back to the slate, as a bookend: an eraser wipe across the Console grid reveals green slate, and the chalk arm draws the detail the opening no longer carries (tool plaques, a ledger of results, the field vignettes). The close (2:25–2:45) cuts back to the technical look for the Console B-roll and the title card.

### Freeze frames on robot footage

The footage runs at its own speed (sped up and tagged when real). At each key moment it freezes:
- The frame drops to about 40% saturation and dims, except the isolated element, which keeps full colour.
- A thin yellow outline traces the element, and a hairline leads to an overlay panel in the Console's style.
- A mono timestamp sits top left (`t = 00:41.2 · step 6/14`), so it reads as a record of that instant.
- Overlays build in about 0.4 s, hold, then the footage unfreezes with a short whoosh, never a hard cut.
- The voice keeps telling the story and never reads the overlay out. Each overlay is readable on pause, which is the point: it documents what the robot knew at that moment.

All overlay content comes from the run's own files (`events.jsonl`, traces and frames), never retyped by hand.

## Shots

Status: **have** means it exists now; **render** means we can make it ourselves from the repo; **film** means a camera is needed; **record** means voice or screen capture. Every **render (sim)** robot shot is MuJoCo for now. Every entry in the Sound column is a placeholder until Karthik's mp3 and music arrive, and every time will be re-cut to his read.

| # | Time | Picture | Motion | On screen | Sound | Source | Status |
|---|---|---|---|---|---|---|---|
| 1 | 0:00–0:06 | Real chalkboard full of buzzwords (*autoformalization, agents, VLA, world models, scaling laws, self-driving labs, end-to-end, AGI, foundation models, verification*) around a big **?** | Static wide shot. Karthik walks in from the left and erases the board. **Play source 0:00.0–0:10.5 at 1.75×**, so 10.5 s of footage fills the 6.0 s slot; the erase finishes at about 0:05 on screen | | Chalk dust, eraser (sped up with the picture). Music starts on the last stroke | `video/real-world-assets/intro.MOV` (measured 25.5 s, 1920 × 1080, 59.94 fps) | **have** (trim and speed in the edit; the file itself stays untouched) |
| 2 | 0:06–0:13 | The cleared board. The chalk arm enters from the right edge and writes `ETH: 3-SAT in 2^εn ?`, crosses out the `?`, writes `claimed false · Oct 2026`, and puts a Lean ✓ beside it | Camera follows the tip; the arm taps the ✓ twice | `a bound on solving hard problems` · *Impagliazzo, Paturi & Williams, Oct 26 2026* | VO 2a | Chalk animation | **render** |
| 3 | 0:13–0:19 | A vertical line down the middle, `software \| hardware`. An arrow from the ✓ stops at the line, dotted and broken. Right of it, a clean CAD box of the centrifuge (✓), then a finger-and-thumb pinch on the lid fin, crossed out; the ✓ smudges into a `?` | Camera pans right with the arm; it wipes the ✓ with the side of its jaw | `no pinch · ADA §309.4` | VO 2b | Chalk animation | **render** |
| 4 | 0:19–0:23 | A row of appliance buttons, a hand pressing them, a clipboard | One quick drawing; camera pulls back to the whole board | `tested by hand` | VO 2c | Chalk animation | **render** |
| 5 | 0:23–0:26 | **The turn** (see Look). The chalk arm becomes the rendered SO-101; the board becomes the Console's grid; the title appears | One continuous move, about 3 s | **RAAV · ROBOT AS A VERIFIER** | VO 3a. Music lifts, synth pad enters | Chalk animation into the Console arm render (optional: open on 1 s of intro.MOV's `RAAV` writing at about 3×) | **render** |
| 6 | 0:26–0:32 | First footage: the arm in front of the centrifuge, its manual open beside it as a flat card | Slow push in; labels tick on | `prototype + manual in` · `SIMULATION` | VO 3b | MuJoCo sim run on the centrifuge | **render** (sim) |
| 7 | 0:32–0:38 | The arm presses START at 2×; a small force trace draws beside it. On the right, the model's plan streams in from Live; a `grades` label next to it is struck out and `sensors decide` appears under the trace | Footage at 2×; overlays slide in | `measurements out` · `model plans · sensors decide` · `SIMULATION` | VO 3c | Same sim run, plus Console Live replay (`#/live?replay=…`) | **render** (sim) plus **record** |
| 8 | 0:38–0:49 | **Why not one VLA.** A motion graphic: one box, `perception + reasoning + control`, labelled `RT-2 · OpenVLA · π0`. Its input slot reads `image + instruction`. A tall stack of demo reels feeds it (`~1M demos`). A new device slides in; the box flashes `+ new demos · fine-tune` | The reel stack grows; the camera follows it up, then pulls back to the box | *OpenVLA, Kim et al. 2024: 970k demos; new setups: 10–150 demos + fine-tuning* · *RT-2, Brohan et al. 2023* · *π0, Black et al. 2024* | VO 4a | Motion graphic | **render** |
| 9 | 0:49–1:00 | A thick manual drops toward the input slot and doesn't fit (`instruction only`). Then an arrow from the box's output loops back into its input, labelled `judge` | The manual bounces off; the loop arrow draws, then pulses once | `who verifies the judge?` | VO 4b | Motion graphic | **render** |
| 10 | 1:00–1:04 | The box splits down the middle. Left: `SYSTEM 1 · the robot`, with an IK triangle and a small control loop. Right: `SYSTEM 2 · the model`, with the manual now sliding in easily (`reads the manual · no new training`) | One clean split, about 1 s, then labels type on | `inverse kinematics · classical control` | VO 5a | Motion graphic | **render** |
| 11 | 1:04–1:14 | Split frame. Left: sim footage of the arm, with four labels ticking on: *perception · IK and control · safety · verdict rules*, and a `no LLM` badge. Right: the model's reasoning streaming in Live, with *plan · recover · diagnose* | Seven thin lines run between the halves like a bus, each labelled with a tool name (`system_status`, `scene_get`, `evidence_get`, `routine_start`, `routine_wait`, `routine_resume`, `routine_stop`); pulses travel along them. A ghost line labelled `move joint` tries to cross and is struck out at the boundary | `seven tools · no joint commands` · `SIMULATION` on the left | VO 5b | MuJoCo sim footage plus Console Live replay | **render** (sim) plus **record** |
| 12 | 1:14–1:22 | **Freeze frame F0** on the split: a routine request crossing the line (table below). Then each half gets its own small test badge | Freeze, overlay, unfreeze; badges tick on | `each side tested on its own` | VO 5c | Same footage; a run's `events.jsonl` | **render** (sim) |
| 13 | 1:22–1:28 | The centrifuge, then its manual. The Quick start lines highlight one at a time and turn into numbered plan steps | Pages fan open; highlighted lines slide right into a plan list | `MC-6 centrifuge` · `manual → plan` | VO 6a | `appliances/centrifuge` render and `manual.md`; plan from a sim run's events | **have** plus **render** |
| 14 | 1:28–1:40 | **Robot footage with freeze frames F1–F4** (table below): survey and map, then POWER, START and SPEED | Footage at 2× between freezes | `SIMULATION` | VO 6a–b | MuJoCo sim run on the centrifuge, `--device centrifuge --rev A --effector stock`, wrist camera, route rgb | **render** (sim) |
| 15 | 1:40–1:46 | The lid attempt, ending in **freeze frame F5**. A finding card slides in as the footage unfreezes | | `Lid · can't open · no lip to hook` · `SIMULATION` | VO 6c | Same MuJoCo run, plus the Console's finding card | **render** (sim) plus **record** |
| 16 | 1:46–1:53 | The lid in CAD, close up. Rev A's fin morphs into Rev B's hook lip. Chalk callout arrows point to the lip | A slow orbit while the geometry morphs | `Rev A → Rev B` · `proposed by the model · approved by a person` | VO 7a | `appliances/centrifuge/build/meshes_revA` and `meshes_revB` | **render** |
| 17 | 1:53–1:59 | Two-up: Rev A fails on the left, Rev B passes on the right. The score ticks up between them | Both clips start together; the right one's verdict turns green | `same tests · score ↑` · `SIMULATION` | VO 7b | MuJoCo sim runs of both revisions | **render** (sim) |
| 18 | 1:59–2:07 | **Coda, in chalk.** An eraser wipe across the Console grid reveals slate. The arm draws two plaques. **CompCert** · `verified C compiler` · `ATR 42/72 avionics, 2026` · `MTU: nuclear emergency-generator engines, 2017` · `Airbus: flight-control evaluation, 2012`. **seL4** · `verified kernel` · `DARPA HACMS · Boeing Little Bird` · `red team couldn't break out, in flight` | Camera follows the tip from plaque to plaque | Small source lines: *compcert.org; AbsInt/MTU 2017; Bedin França et al., ERTS 2012* · *DARPA HACMS; seL4 Foundation* | VO 8a | Chalk animation | **render** |
| 19 | 2:07–2:14 | A third plaque, **TLA+** · `AWS: 10 systems · a 35-step DynamoDB bug`. Under all three, a ledger: `Lean · Mathlib` · `Liquid Tensor Experiment, 2022` · `AlphaProof · IMO 2024 silver, 28/42` · `Rocq (Coq) · Four Colour Theorem, 2005` · `Isabelle/HOL · seL4, 2009` · `fluid singularities · DeepMind 2025` · `weight-space programming · 2026`. Then the `software \| hardware` line again; nothing crosses it | The ledger writes on fast, left to right; camera pulls back to the whole left half, then pans to the line | *Newcombe et al., CACM 2015* · ledger sources from the script | VO 8b | Chalk animation | **render** |
| 20 | 2:14–2:18 | Right of the line. Heading `BIOSAFETY`. A lab over a buried drain pipe, with a crack and a tree root through it; a few dots seep out | The arm draws fast, then taps the crack twice | `Pirbright, UK, 2007 · foot-and-mouth` · *HSE: cracked, root-breached drains, most likely source* | VO 8c | Chalk animation | **render** |
| 21 | 2:18–2:21 | Heading `AEROSPACE`. A folded sunshield beside a big loudspeaker; small fasteners fall from it | One quick drawing | *JWST, 2018: fasteners loose in an acoustic test · 29-month delay, ~$1B* | VO 8c | Chalk animation | **render** |
| 22 | 2:21–2:25 | Heading `MECHANICAL DESIGN`. A stack of vacuum-cleaner prototypes, with a tally counting up to `5,127` | Camera tracks up the stack | *Dyson DC01: 5,127 prototypes, 15 years* | VO 8c | Chalk animation | **render** |
| 23 | 2:25–2:34 | Back to the technical look. Console B-roll: a run page with a force trace and its frame, Studies, Live, Design Analysis, the models page | Slow parallax pans, a cut every 2–3 s. Words drop over it | `lab instruments · appliances · assistive devices` · `12 appliances · 4 models · in simulation` | VO 9a | Console screen capture | **record** |
| 24 | 2:34–2:39 | A dark board with a faint grid. Typed lines appear: *Proofs → Lean*, *Software → CompCert · seL4*, *Hardware → ?*. The `?` becomes the yellow arm | Each line on its beat | | VO 9b–c. Music swells | Motion graphic | **render** |
| 25 | 2:39–2:45 | Title card: **RAAV · ROBOT AS A VERIFIER**. Under it, the innovations one per line, then the team and MakeCU 2026 | Lines fade in on the beat; the music resolves at 2:44 | the innovations, team | Music out | Motion graphic | **render** |

### Cold open notes (shot 1)

- **Measured:** `intro.MOV` runs 25.5 s (ffprobe: 25.50 s, 1920 × 1080, 59.94 fps, with audio). Draft 3 only said "needs trimming", which implied real time.
- **What's in it:** 0:00–0:02.5 the full board, static; 0:02.5–0:03 Karthik walks in; about 0:03–0:09 he erases the board in several strokes, left to right; 0:09–0:10.5 he steps off the right edge; 0:11–0:20 he comes back and writes `RAAV`; 0:20–0:25.5 he leaves and the camera pushes in on `RAAV`.
- **Speed and trim:** use source 0:00.0–0:10.5 at **1.75×**, which lands at **6.0 s on screen** (0:00–0:06). The last eraser stroke falls at about 0:05.1 on screen, where the music starts. The board is clean at the cut, so the eraser-wipe transition into shot 2 matches.
- **Don't re-encode the original.** Speed it up in the edit (for example ffmpeg `setpts=PTS/1.75` and `atempo=1.75`, or the editor's speed control) from a copy of the clip.
- **Unused material:** the `RAAV` writing (0:11–0:20) can open the turn (shot 5) for about a second at 3×.
- **Tag:** the `REAL FOOTAGE · N×` tag is for robot footage, which is evidence. The cold open is staged and carries no tag (see Questions).

## Freeze frames (shots 12, 14 and 15)

Six freezes. F0 documents the boundary between the systems; F1–F5 each document one stage of the centrifuge run. Holds are timed to read once; the footage between them runs at 2×. All of it is MuJoCo footage for now.

| # | Freezes on | Isolated | Overlay shows | Hold | From |
|---|---|---|---|---|---|
| F0 | The split frame, as System 2 starts a routine | The bus between the halves | The tool call as it crossed, from the run log: `routine_start · run_plan · 6 steps`. On System 1's side, its answer: each parameter checked against its own limits (for example a requested force beside the 14 N step limit, which is rejected rather than clamped if exceeded), then `accepted`. A dimmed `move joint` call sits beside it with `no such tool`. Tags: `System 2 asks` on the right, `System 1 decides how` on the left | 2.5 s | The run's `events.jsonl` |
| F1 | The wrist camera's first look at the panel, during the survey | The control panel | OWLv2 boxes, then SAM outlines tracing each control, each with its label and kind: `POWER · toggle`, `START · button`, `STOP · button`, `TIME+ · button`, `SPEED · dial`, `lid handle`. Corner note: `one $19 wrist camera` | 2.0 s | The run's perception frame and detections |
| F2 | The arm mid-scan, after a few nearby photos | The arm and the panel | The 3D map building: a point cloud from the shift between photos settles onto the panel, then a fingertip tap marks the touched plane with a small ring. Labels: `heights from nearby photos` · `plane from touch` | 2.0 s | The run's scene inventory and map |
| F3 | The moment before the first press | The plan, beside the arm | The model's plan line for this step, as it appears in the run log, for example `step 3 · press START · expect display to count down`, with a hairline to the START outline. A small tag: `planned by System 2` | 1.5 s | The run's plan events |
| F4 | START at full press | The fingertip on START | A force trace growing left to right, with a dashed line for the 15 N safety cap well above it, and the press's peak marked. Then the verdict rule's line types in green, for example `pressed · display changed → pass`, with the tag `decided by System 1` | 2.5 s | The step's trace and verdict |
| F5 | The jaw sliding off the lid fin | The jaw and the fin | A close-up inset of the fin with no lip; the force trace drops to zero as the jaw slips; the lid angle readout stays at `0°`. The retest rule fires: `failed · retested · failed again → fail`, in red, with `decided by System 1` | 2.5 s | The lid step's trace, frames and verdict |

Exact rule text, numbers and step numbers come from whichever sim run we film; the examples above show the shape, not values to retype. Shot 14 now has 12 s for F1–F4 (8 s of holds), so the freezes are less cramped than in Draft 4.

## Music

**Placeholder.** Karthik is bringing the voiceover (as an mp3) and the music. The brief and cues below are what we'd ask for; swap them for what he brings, and re-time the cues to his read.

**Brief:** soft, inspirational piano with light strings or felt marimba, about 90–100 BPM, and a low synth pad that enters only at the turn.

| Time | Cue |
|---|---|
| 0:05 | Piano enters on the last eraser stroke, sparse |
| 0:06–0:23 | Quiet under the voice, a small drop at "verification ends where software ends" (0:13) |
| 0:23 | The turn: strings and the synth pad come in, the beat steadies |
| 0:38–1:00 | Holds back under the VLA argument; a darker chord under "the model that acts would also be the judge" (about 0:57) |
| 1:14 and 1:28–1:46 | Thins out. Each freeze frame lands on a soft hit, and the music holds a note through it |
| 1:46 | Picks up for the fix |
| 1:59 | Drops back to piano alone for the chalk coda |
| 2:25 | The pad returns with the Console B-roll |
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

For now every robot shot (6, 7, 11, 12, 14, 15 and 17) is rendered in MuJoCo and tagged `SIMULATION`. The real arm hasn't run yet and Rev B hasn't been printed. We'll probably edit the cut and re-record real footage later: when the arm runs on the printed centrifuge, re-film shots 6, 7, 14, 15 and 17 (and the left half of 11 if it's worth it), speed them up, and change the tag to `REAL FOOTAGE · N×` with the true factor. The freeze frames carry over unchanged: they're built from the run's files, which look the same for sim and real. The cuts are timed so a real clip can replace a sim clip of the same length without re-editing anything else.

## How we'd make it, after your OK

- **Chalk scenes:** drawn in code. Each stroke is a path that the chalk arm's tip follows, with a chalk-texture brush, dust particles and a following camera. Rendered frame by frame, so the timing is exact.
- **The turn:** the same renderer, cross-fading the chalk arm into the Console's arm drawing.
- **VLA graphic (shots 8–10):** the same motion-graphic renderer as the closing lines, in the Console's style.
- **Sim clips and freeze frames:** recorded from the existing MuJoCo sim on the centrifuge (Rev A and Rev B), with overlays drawn from the run's files. This only runs System 1's code; we don't change it.
- **Console B-roll:** scripted browser captures at 1080p, so they can be re-shot after any UI change.
- **Cold open:** trimmed and sped to 1.75× in the edit from a copy of `intro.MOV`.
- **Voiceover and music:** Karthik records the voiceover as an mp3 and brings the music. Until then, a placeholder read keeps the timing honest; once his mp3 is in, every shot's in and out points are re-cut to it.
- **Assembly:** ffmpeg, from an edit list in this folder, so any shot can be swapped and the whole video rebuilt with one command.

## Claims on screen

Every number or source line on screen is from the script's [checks table](script.md#checks-before-recording) and [Sources](script.md#sources). Extra on-screen items:

| On screen | Holds because | Watch for |
|---|---|---|
| `a bound on solving hard problems` (shot 2) | ETH, Impagliazzo and Paturi 2001 (script source 3) | Plain-language gloss, not the formal statement |
| `no pinch · ADA §309.4` (shot 3) | Access Board guide to §309.4 (script source 9) | It's a US building standard. Use it as the reason the rule exists, not as a claim that appliances must meet it |
| `RT-2 · OpenVLA · π0` and `image + instruction` (shot 8) | Script sources 10, 27, 28 | They're examples of VLAs, not a survey |
| `~1M demos` and `new setups: 10–150 demos + fine-tuning` (shot 8) | OpenVLA abstract (970k) and §5.2 (10–150 demonstrations, full fine-tuning) (script source 10) | Keep the source line visible while the numbers are |
| `inverse kinematics · classical control` (shot 10) | System 1 uses IK and fixed policies (`system-1/README.md`) | Don't write MPC or LQR unless labelled as general classical control, not RAAV's stack |
| `reads the manual · no new training` (shot 10) | System 2 gets `manual.md` in its prompt; no fine-tuning (`docs/frontier-integration.md`) | |
| `14 N` step limit (F0) | `docs/decisions.md` D31: a step may ask for at most 14 N, rejected above that | Use the value from the filmed run |
| `15 N safety cap` (F4) | `docs/decisions.md` D34: "The 15 N cap is unchanged" | Re-check the value before rendering |
| CompCert plaque (shot 18) | Script sources 17–19 | The 2012 Airbus line is an evaluation, so write `evaluation`. The ATR line is a 2026 qualification "with guidance from Airbus" |
| seL4 plaque (shot 18) | Script sources 20–22 | The red team was given a partition and couldn't break out; write that, not "unhackable" |
| TLA+ plaque and the ledger (shot 19) | Script sources 4–6, 12–16, 20, 23 | AlphaProof's IMO problems were translated into Lean by hand first. "10 systems" was AWS's count at the time of writing. Never write that the fluid work solved Navier–Stokes |
| `Pirbright, UK, 2007` (shot 20) | HSE final report, via script source 24 | Keep "most likely source" |
| `JWST, 2018 … 29-month delay, ~$1B` (shot 21) | Script source 26 | Write "acoustic test" only with this source; others say vibration test |
| `Dyson DC01: 5,127 prototypes, 15 years` (shot 22) | Script source 25 | Other Dyson accounts say five years from a different start; keep "15 years" with this source |

## Sources

All claim sources are listed in [script.md](script.md#sources). The style reference for the chalk scenes is the RSA Animate series of whiteboard explainers (a hand drawing continuously, the camera following it); it is a visual reference only, not cited on screen.

## Questions for Karthik

1. **The cold open:** `intro.MOV` is in `video/real-world-assets/`. Is that the final take, or will you re-film it? And is 1.75× the speed you want, or faster still?
2. **Tag on the cold open:** it's real footage sped up 1.75×, but it's staged, not evidence. Leave it untagged, or add `REAL FOOTAGE · 1.75×` for consistency?
3. **The coda in chalk:** shots 18–22 bring the slate back for "why this matters". Keep that bookend, or keep everything after the turn in the technical look?
4. **How much text:** shots 18 and 19 carry a lot of small source lines. Keep them, or move the ledger to an end card after the title?
5. **The VLA graphic:** shots 8–10 are drawn in the technical style now, since they come after the turn. Fine, or would you rather they stay chalk?
6. **Your mp3:** when it's in, send it with any lines you changed while reading, and we'll re-cut every shot to it.
