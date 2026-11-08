# Demo video storyboard

**Draft 8, Nov 8.** Goes with [script.md](script.md). Runs 3:39, 1920 × 1080 at 30 fps.

**What changed from Draft 7:** the script's wording pass shortened the read from 3:55 to 3:39 with no shots or facts dropped, so every shot below is re-timed to it. Shot 2 now carries the line on why ETH matters, with its source. Shots 3 and 19 are tighter, so their text is read on pause more than in real time.

Draft 7's other changes (the walkthrough, the field names, the thesis sentence and the new ending) all stand.

**For now, every robot shot is rendered in MuJoCo (sim).** The real arm hasn't run yet. We'll probably edit the cut and re-record those shots with real footage later (see "Real footage, later"). The `SIMULATION` tag rule stays as it is.

**Audio is a placeholder.** Karthik will record the voiceover himself as an mp3, and the music is coming from him too. Until they arrive, the Sound column, the music cues and the licensing list are placeholders. **The final cut will be re-timed to his recording**: the timestamps below are targets for a natural read at the script's word rates, and each shot will stretch or shrink to match his actual lines.

## Look

### Act one: rustic chalk (0:00–1:01)

Act one carries the problem and the stakes. It's chalk because it's an argument, not the product.

- **Board:** green slate (about `#2e4a3c`), not flat. A faint texture of old, half-erased writing sits under everything, with eraser swirls, a dusty chalk tray along the bottom edge, and slight vignetting at the corners.
- **Chalk:** white for the argument, **chalk yellow** for anything about the robot. The yellow matches the SO-101 and the Console's accent (`#eebc24`), so the chalk world and the product read as one thing. Lines are imperfect: they vary in pressure, skip on the grain, overshoot corners, and leave a little dust that drifts down. Letters are hand-printed, not a font.
- **The sketcher is a robot.** Whiteboard-explainer videos (the RSA Animate style) show a hand drawing continuously while the camera follows it, so the argument builds up stroke by stroke. Here the hand is a **chalk-sprite SO-101 arm**, drawn in chalk-yellow line work after the Console's mock arm (`components/Field.tsx`: yellow base and links, dark servo blocks, the two-finger gripper) and holding a stub of chalk in its jaws.
  - **It is always drawing.** While the voice talks, the arm's tip is writing; it never sits still for more than about a second.
  - **The camera follows the tip,** framing about a third of the board, with a slight lag and ease so it feels hand-held. When an idea completes, the camera pulls back to show how it connects to what's already drawn, then pushes in to the next empty patch.
  - **Pace:** one new drawn element every 2–3 s, matched to the voice's nouns. Text draws at about speaking speed; diagrams are sped up so they finish on their noun.
  - **Its tics:** it blows chalk dust off a line (a puff), taps the chalk twice to make a point, and wipes a mistake with the side of its jaw. Use each once or twice, not more.
- **Eraser wipe:** the stroke from the cold open is the transition between chalk scenes. A swipe clears a patch and the arm starts drawing in it.
- **Source lines:** citations the voice can't fit are written small under each drawing, to be read on pause.

### The turn (1:01–1:04, on "So we built RAAV")

The board holds the whole argument: the Lean ✓ and the two plaques on the left, the `software | hardware` line, the crossed-out pinch, the three field panels and the hand at the buttons on the right. The arm taps the dividing line twice. Then, over about 3 s:
1. The dust lifts off every line on the board and hangs in the air.
2. The arm's chalk outline snaps clean, and fills in, link by link from the base up, with the Console's solid render: yellow plastic, dark servos, a metal horn.
3. The green slate darkens into the Console's dark background, and a faint measurement grid fades in where the old writing was.
4. The hanging dust settles into the grid as small points, which become the point cloud the arm will build later.
5. The title types in Michroma, crisp: **RAAV · ROBOT AS A VERIFIER**. Under it, in JetBrains Mono, the thesis types on as the voice says it: *RAAV tests a physical prototype against its manual and specification with a low-cost robot arm, and reports what it measured.*

A low synth pad enters under the piano on step 2 and the music lifts (placeholder until the music arrives).

### Act two: technical (1:04–3:39)

- **Background:** the Console's dark theme, with a fine grid and thin hairline rules. Labels in JetBrains Mono, as in the Console; titles in Michroma.
- **Colour:** the accent yellow for robot data and System 1, a cool grey-blue for System 2, Console pass green and fail red for verdicts, amber for a person's approval, everything else in greys.
- **Motion:** precise and quick, eased like the Console's UI. Nothing wobbles. Chalk appears in act two only as callout arrows on the CAD morph, a deliberate echo of act one.
- **Tags:** `SIMULATION` in a small yellow tag at bottom right on all sim footage, which today is every robot shot (MuJoCo). Later, `REAL FOOTAGE · N×` on sped-up real clips.
- **Walkthrough rail:** during shots 17–25 a thin step rail runs along the top: `survey · scan · segment · map · touch · plan · test · verdicts · report · CAD fix · Rev B`. The current step lights up, so the viewer always knows where the run is.

### Freeze frames on robot footage

The footage runs at its own speed (sped up and tagged when real). At each key moment it freezes:
- The frame drops to about 40% saturation and dims, except the isolated element, which keeps full colour.
- A thin yellow outline traces the element, and a hairline leads to an overlay panel in the Console's style.
- A mono timestamp sits top left (`t = 00:41.2 · step 6/14`), so it reads as a record of that instant.
- In the walkthrough, each overlay is split in two: **System 1** (yellow, left) says what it did and measured, **System 2** (grey-blue, right) says how it responded. A person's approval, when one is needed, appears as an amber card between them.
- Overlays build in about 0.4 s, hold, then the footage unfreezes with a short whoosh, never a hard cut.
- The voice keeps telling the story and never reads the overlay out. Each overlay is readable on pause, which is the point: it documents what the robot knew at that moment.

All overlay content comes from the run's own files (`events.jsonl`, traces and frames) or the device's verification output (`verify.stock.json`), never retyped by hand. Freeze IDs are `FR0`–`FR8`, so they don't clash with the centrifuge's fault IDs (F2, F3).

## Shots

Status: **have** means it exists now; **render** means we can make it ourselves from the repo; **film** means a camera is needed; **record** means voice or screen capture. Every **render (sim)** robot shot is MuJoCo for now. Every entry in the Sound column is a placeholder until Karthik's mp3 and music arrive, and every time will be re-cut to his read.

| # | Time | Picture | Motion | On screen | Sound | Source | Status |
|---|---|---|---|---|---|---|---|
| 1 | 0:00–0:06 | Real chalkboard full of buzzwords (*autoformalization, agents, VLA, world models, scaling laws, self-driving labs, end-to-end, AGI, foundation models, verification*) around a big **?** | Static wide shot. Karthik walks in from the left and erases the board. **Play source 0:00.0–0:10.5 at 1.75×**, so 10.5 s of footage fills the 6.0 s slot; the erase finishes at about 0:05 on screen | | Chalk dust, eraser (sped up with the picture). Music starts on the last stroke | `video/real-world-assets/intro.MOV` (measured 25.5 s, 1920 × 1080, 59.94 fps) | **have** (trim and speed in the edit; the file itself stays untouched) |
| 2 | 0:06–0:20 | The cleared board. The chalk arm enters from the right edge and writes `ETH: 3-SAT in 2^εn ?`, draws a short stack of books under it labelled `lower bounds`, crosses out the `?`, writes `claimed false · Oct 2026`, and puts a Lean ✓ beside it | Camera follows the tip; the stack wobbles when the `?` is crossed out; the arm taps the ✓ twice | `ETH: some problems stay exponentially hard` · `lower bounds rest on it` · *Impagliazzo, Paturi & Williams, Oct 26 2026* · *Lokshtanov, Marx & Saurabh, 2011: a survey of lower bounds assuming ETH* | VO 2a | Chalk animation | **render** |
| 3 | 0:20–0:31 | Two chalk plaques under the ✓. **CompCert** · `verified C compiler` · `ATR 42/72 avionics, 2026` · `MTU: nuclear emergency-generator engines, 2017` · `Airbus: flight-control evaluation, 2012`. **seL4** · `verified kernel` · `DARPA HACMS · Boeing Little Bird` · `red team couldn't break out, in flight`. Along the bottom edge, a ledger writes on: `TLA+ · AWS, 10 systems` · `Lean · Mathlib` · `Liquid Tensor Experiment, 2022` · `AlphaProof · IMO 2024 silver, 28/42` · `Rocq (Coq) · Four Colour Theorem, 2005` · `Isabelle/HOL · seL4, 2009` · `fluid singularities · DeepMind 2025` · `weight-space programming · 2026` | Camera follows the tip from plaque to plaque, then pulls back as the ledger writes on fast | Small source lines: *compcert.org; AbsInt/MTU 2017; Bedin França et al., ERTS 2012* · *DARPA HACMS; seL4 Foundation* · *Newcombe et al., CACM 2015* | VO 2b | Chalk animation | **render** |
| 4 | 0:31–0:37 | A vertical line down the middle, `software \| hardware`. The arrow from the plaques stops at it, dotted and broken. Right of it, a clean CAD box of the centrifuge (✓), then a finger-and-thumb pinch on the lid fin, crossed out; the ✓ smudges into a `?` | Camera pans right with the arm; it wipes the ✓ with the side of its jaw | `no pinch · ADA §309.4` | VO 3a | Chalk animation | **render** |
| 5 | 0:37–0:44 | Heading `BIOSAFETY & BIOSECURITY`. A lab building over a buried drain pipe, with a crack and a tree root through it; a few dots seep out and follow a truck's tyre track off the edge | The arm draws fast, then taps the crack twice | `Pirbright, Surrey, 2007 · foot-and-mouth outbreak` · *HSE: cracked, root-breached drains, the most likely source; long-term damage* | VO 3b | Chalk animation | **render** |
| 6 | 0:44–0:52 | Heading `AEROSPACE ENGINEERING`. A folded sunshield beside a big loudspeaker; small fasteners fall from it. A calendar beside it flips forward 29 months | One quick drawing, then the calendar flips | *JWST, 2018: fasteners loose in an acoustic test · review board: 29-month delay, ~$1B, five causes* | VO 3c | Chalk animation | **render** |
| 7 | 0:52–0:58 | Heading `MECHANICAL & PRODUCT DESIGN`. A stack of vacuum-cleaner prototypes, with a tally counting up to `5,127` | Camera tracks up the stack | *Dyson DC01: 5,127 prototypes over 15 years, succeeded 1993* | VO 3d | Chalk animation | **render** |
| 8 | 0:58–1:01 | A row of appliance buttons, a hand pressing them, a clipboard | One quick drawing; camera pulls back to the whole board | `tested by hand` | VO 3e | Chalk animation | **render** |
| 9 | 1:01–1:04 | **The turn** (see Look). The chalk arm becomes the rendered SO-101; the board becomes the Console's grid; the title appears | One continuous move, about 3 s | **RAAV · ROBOT AS A VERIFIER** | VO 4a. Music lifts, synth pad enters | Chalk animation into the Console arm render (optional: open on 1 s of intro.MOV's `RAAV` writing at about 3×) | **render** |
| 10 | 1:04–1:13 | The thesis sentence types under the title, then slides up as the first footage fades in: the arm in front of the centrifuge, its manual open beside it as a flat card | Type-on, then a slow push in | the thesis · `prototype + manual + spec in · measurements out` · `SIMULATION` | VO 4b | MuJoCo sim run on the centrifuge | **render** (sim) |
| 11 | 1:13–1:21 | **Why not one VLA.** One box, `perception + reasoning + control`, labelled `SmolVLA · GR00T N1 · π0`. Its input reads `images + instruction`. A stack of demo reels feeds it. A new device slides in; the box flashes `+ new demos · fine-tune`. An arrow from its output loops back in as `judge` | The reel stack grows; the loop arrow draws, then pulses once | *SmolVLA, Hugging Face 2025: built on SO-100/SO-101 data; 50 demos per real-world task* · *GR00T N1, NVIDIA 2025: post-trained per embodiment; its own "System 1/2" are trained end-to-end as one model* | VO 5a | Motion graphic | **render** |
| 12 | 1:21–1:23 | The box splits down the middle. Left, in yellow: `SYSTEM 1 · exact, fast, safe`. Right, in grey-blue: `SYSTEM 2 · context and judgment` | One clean split, then the headings type on | | VO 5b | Motion graphic | **render** |
| 13 | 1:23–1:32 | Left half fills: sim footage of the arm, with labels ticking on as the voice names them: `perception` · `inverse kinematics` · `control · 50 Hz` · `force limits · 15 N` · `verdicts: sensors + fixed rules`. A `no LLM` badge | Labels tick on one per beat; the right half stays dim | `SIMULATION` | VO 5b | MuJoCo sim footage | **render** (sim) |
| 14 | 1:32–1:46 | Right half fills: the model's reasoning streaming in Live. The manual and a spec card slide in; a plan list orders itself; a failed step turns red and the plan re-routes; a `root cause → CAD fix` card appears. Between the halves, seven tool lines run like a bus | Each job appears on its beat; the bus draws in last | `reads manual + spec · what to test, in what order · recovers · diagnoses → CAD fix` | VO 5b | Console Live replay (`#/live?replay=…`) | **record** |
| 15 | 1:46–1:54 | **FR0** on the split: a routine request crossing the line (table below). A ghost `move joint` line is struck out at the boundary; a `grade` arrow from System 2 to the verdict is struck out too | Freeze, overlay, unfreeze | `no motor commands · no self-grading` | VO 5c | A run's `events.jsonl` | **render** (sim) |
| 16 | 1:54–2:02 | System 2's header cycles through four model names while System 1's panel stays locked: `14 N step limit · 15 N cap · verdict rules`, with a small padlock. Then the demo reels fade and a manual slides in | Names flip like a split-flap board; the padlock doesn't move | `swap the model · System 1's limits hold` · `new device: a manual, not new demos` | VO 5c | Motion graphic over a still of the split | **render** |
| 17 | 2:02–2:06 | **Walkthrough starts.** The step rail appears. The centrifuge on its base, labelled `Rev A`, and its manual | Pages fan open once | `MC-6 centrifuge · Rev A · manual.md` | VO 6a | `appliances/centrifuge` render and `manual.md` | **have** plus **render** |
| 18 | 2:06–2:13 | Rail: survey → touch. The arm surveys, takes photo pairs, then **FR1** (segment) and **FR2** (map and touch). Between them, a red stop card flashes: `explore · pipeline_error` and System 2's answer `run explore again`; the second pass completes | Footage at 2× between freezes; the stop card drops in and is dismissed | `SIMULATION` | VO 6b | MuJoCo sim run; the stop and rerun from the recorded Sonnet 5.5 run (`eval-1107-232000/002…`, seq 16–23) | **render** (sim) |
| 19 | 2:13–2:16 | Rail: plan. **FR3**: the manual's lines become plan steps; the amber approval card appears and is approved | Freeze, overlay, unfreeze | `planned by System 2 · approved by a person` · `SIMULATION` | VO 6c | The run's `plan_ready` and `approval_needed` events; the Console's approval card from a live run | **render** (sim) plus **record** |
| 20 | 2:16–2:30 | Rail: test → verdicts. **FR4**: a press under the cap, its force trace, and the verdict rule's line; a badge shows the retry budget by setting (`Tethered 0 · Balanced 2 · Autonomous 4`). Then **FR5**: the first flip's force spikes past the dashed 15 N line, the arm stops, and the amber card reads `resume after a safety stop: a person` | Footage at 2× between freezes; at FR5 the footage cuts to still on the spike | `SIMULATION` | VO 6d | The run's traces and verdicts; the safety stop from the recorded run (seq 49–57: 16.4 N over 15.0 N) | **render** (sim) |
| 21 | 2:30–2:38 | Rail: verdicts. **FR6**: the display reads `1000rpm  0:30`, the manual says `1000 RPM 0:30`. System 1 escalates `unexpected_response`; System 2 amends the plan; a small ladder of approval levels lights `1 · notify`, labelled `set by code` | Freeze, overlay, unfreeze | `SIMULATION` | VO 6e | The recorded run, seq 85–94 | **render** (sim) |
| 22 | 2:38–2:47 | Rail: verdicts → report. The jaw at the lid's thin fin. **FR7**: System 1's line `REFUSED · handle_1 needs a pinch grip; the no-thumbs rule allows only the fingertip pad`; System 2's line `reported, not guessed`; a finding card slides into the report | Freeze, overlay; the finding card slides in as it unfreezes | `Lid · can't open without a pinch` · `SIMULATION` | VO 6f | The F2 check in `verify.stock.json`, re-rendered as a run; the Console's finding card | **render** (sim) plus **record** |
| 23 | 2:47–2:54 | Rail: CAD fix. The lid in CAD, close up. The fin morphs into a hook lip. Chalk callout arrows point to the lip. A check line ticks: `fingertip catches it · no pinch needed ✓`; then the amber approval card | A slow orbit while the geometry morphs | `Rev B` · `checked by code · approved by a person` | VO 6g | `appliances/centrifuge/build/meshes_revA` and `meshes_revB`; the CAD check from `system-2/cad` | **render** |
| 24 | 2:54–2:59 | **FR8** on M1 (lid fixed, well still tight): with the lid open, the tube sits high in well A; an inset shows the 11.1 mm gap over the tube sensor. The lid closes; START; the display shows `TUBE` | Freeze on the gap, then unfreeze for the press | `masked until the lid opens` · `SIMULATION` | VO 6g | The F3s check in `verify.stock.json` (M1). The tube is set in the well by the check, not by the arm | **render** (sim) |
| 25 | 2:59–3:07 | Rail: Rev B. Two-up: Rev A's lid refuses on the left, Rev B's lid swings to 100° on the right. The score ticks up between them | Both clips start together; the right one's verdict turns green | `same tests · score ↑` · `SIMULATION` | VO 6h | The F2 checks on Rev A and Rev B (`verify.stock.json`) | **render** (sim) |
| 26 | 3:07–3:26 | **The ending.** Console B-roll, slow. As the voice names each piece, it lights up: the run log with no device names in its prompts (`nothing written for this device`), the seven-tool bus with a second arm outline ghosted onto System 1's side (`another arm could take its place`), a manual feeding a plan, the approval-level ladder, a CAD check on a STEP assembly, the model picker | Slow parallax pans, one piece per beat | `built to extend` | VO 7a | Console screen capture | **record** |
| 27 | 3:26–3:31 | A short roadmap on the grid, all in outline (not filled), labelled `next`: `real arm → lab instruments → assistive devices` | Draws on left to right | `next` | VO 7b | Motion graphic | **render** |
| 28 | 3:31–3:39 | A quiet title card: **RAAV · ROBOT AS A VERIFIER**, the team, MakeCU 2026 | Holds; the music resolves at 3:38 | | VO 7c. Music out | Motion graphic | **render** |

### Cold open notes (shot 1)

- **Measured:** `intro.MOV` runs 25.5 s (ffprobe: 25.50 s, 1920 × 1080, 59.94 fps, with audio). Draft 3 only said "needs trimming", which implied real time.
- **What's in it:** 0:00–0:02.5 the full board, static; 0:02.5–0:03 Karthik walks in; about 0:03–0:09 he erases the board in several strokes, left to right; 0:09–0:10.5 he steps off the right edge; 0:11–0:20 he comes back and writes `RAAV`; 0:20–0:25.5 he leaves and the camera pushes in on `RAAV`.
- **Speed and trim:** use source 0:00.0–0:10.5 at **1.75×**, which lands at **6.0 s on screen** (0:00–0:06). The last eraser stroke falls at about 0:05.1 on screen, where the music starts. The board is clean at the cut, so the eraser-wipe transition into shot 2 matches.
- **Don't re-encode the original.** Speed it up in the edit (for example ffmpeg `setpts=PTS/1.75` and `atempo=1.75`, or the editor's speed control) from a copy of the clip.
- **Unused material:** the `RAAV` writing (0:11–0:20) can open the turn (shot 9) for about a second at 3×.
- **Tag:** the `REAL FOOTAGE · N×` tag is for robot footage, which is evidence. The cold open is staged and carries no tag (see Questions).

## Freeze frames (shots 15 and 18–24)

Nine freezes. FR0 documents the boundary between the systems; FR1–FR8 walk through one centrifuge run in order. Each walkthrough overlay is split: System 1's action and numbers on the left, System 2's response on the right. Holds are timed to read once; the footage between them runs at 2×. All of it is MuJoCo footage for now.

| # | Step | Freezes on | System 1 (left) | System 2 (right) | Hold | From |
|---|---|---|---|---|---|---|
| FR0 | Boundary | The split frame, as System 2 starts a routine | Each parameter checked against its own limits (a requested force beside the 14 N step limit, rejected rather than clamped if exceeded), then `accepted`. A dimmed `move joint` call with `no such tool` | `routine_start · run_plan · 6 steps` | 2.5 s | A run's `events.jsonl` |
| FR1 | Segment | The wrist camera's first look at the panel | OWLv2 boxes, then SAM outlines on each control with its label and kind: `POWER · toggle`, `START · button`, `STOP · button`, `TIME+ · button`, `SPEED · dial`, `lid handle`. Corner note: `one $19 wrist camera` | (dim: System 2 waits) | 2.0 s | The run's perception frame and detections |
| FR2 | Map and touch | The arm mid-scan, then a fingertip tap | A point cloud from the shift between photos settles onto the panel; the tap marks the touched plane. Labels: `heights from nearby photos` · `plane from touch` | `scene ready · N controls`, with N from the run's scene inventory | 2.0 s | The run's scene inventory and map |
| FR3 | Plan | The plan beside the arm | (dim) | Manual lines quoted beside plan steps, for example `s5 · press START · expect TUBE (no tube seated)`. Amber card: `plan · approve?` → `approved` | 2.0 s | The run's `read_manual`, `propose_plan`, `plan_ready`, `approval_needed` events |
| FR4 | Test and verdict | A press at full travel | A force trace with the dashed 15 N cap well above it, the peak marked, and the rule's line in green, for example `pressed · display changed → pass`. Badge: `retries: Tethered 0 · Balanced 2 · Autonomous 4` | (dim: the model doesn't judge) | 2.5 s | The step's trace and verdict |
| FR5 | Safety stop | The first flip, at the spike | `safety_abort · tip force 16.4 N over hard cap 15.0 N` · `stopped first` | `re-explore: device may have moved`. Amber card: `resume after a safety stop · a person (level 3)` | 2.5 s | The recorded run, seq 49–65 |
| FR6 | Amendment | The display after the power flip | `escalation · unexpected_response` · display `1000rpm  0:30` vs manual `1000 RPM 0:30` | `plan amended` · ladder lights `level 1 · notify` with `assigned by code` | 2.0 s | The recorded run, seq 85–94 |
| FR7 | Refusal and report | The jaw at the lid fin | `REFUSED · handle_1 needs a pinch grip; the no-thumbs rule allows only the fingertip pad` · lid sensor `closed` | `finding: lid can't be opened without a pinch` · `reported, not guessed` | 2.5 s | The F2 check (`verify.stock.json`) |
| FR8 | Unmasked fault | The tube in well A, M1 | `tube sits 11.1 mm above the sensor (seated: 3.2 mm)` · START → `TUBE` | `second fault, masked by the lid until now` | 2.5 s | The F3s check on M1 (`verify.stock.json`); geometry from `source/faults.md` |

Shot 19 (FR3) now has 3 s, so its 2.0 s hold is nearly the whole shot; if it feels rushed, let FR3 overlap the start of shot 20. Exact rule text, numbers and step numbers come from whichever runs we film; the examples above show the shape, not values to retype. FR5 and FR6 come from the recorded Sonnet 5.5 run on Rev A, where approvals were automatic because it was sim; the amber cards should come from a Console run where a person actually approves. FR7 and FR8 come from the device's verification checks until a model run plans a lid test (see Questions).

## Music

**Placeholder.** Karthik is bringing the voiceover (as an mp3) and the music. The brief and cues below are what we'd ask for; swap them for what he brings, and re-time the cues to his read.

**Brief:** soft, inspirational piano with light strings or felt marimba, about 90–100 BPM, and a low synth pad that enters only at the turn.

| Time | Cue |
|---|---|
| 0:05 | Piano enters on the last eraser stroke, sparse |
| 0:06–0:31 | Quiet under the voice; a small lift as the plaques draw on |
| 0:31–1:01 | Drops at "verification ends where software ends", and stays low and steady under the three field panels |
| 1:01 | The turn: strings and the synth pad come in, the beat steadies |
| 1:13–1:23 | Holds back under the VLA line, then lifts on "RAAV splits the work" |
| 2:02–3:07 | The walkthrough: a steady pulse, thinned out. Each freeze lands on a soft hit and holds a note. A low swell under the safety stop (about 2:25) and a brighter turn when Rev B's lid opens (about 3:03) |
| 3:07–3:31 | Calm and open under the ending, no build |
| 3:31 | Settles for the title card |
| 3:38 | Resolves within the last second |

No lyrics, and nothing that fights the voiceover in the 1–4 kHz range.

**Licensing:** the video will be public, so the track needs a licence that covers that, ideally with no attribution required and no Content ID claims. These candidates need auditioning (only if Karthik's track doesn't cover it):

| Source | Why | Check |
|---|---|---|
| YouTube Studio Audio Library | Free, filterable by mood (Inspirational) and by "no attribution required" | Each track's own credit line |
| Pixabay Music | Free under its content licence; many soft piano tracks | The licence page, and whether the track is registered for Content ID |
| [BudgetPixel](https://budgetpixel.com/background-music/uplifting-cinematic-piano-led-orchestral-6401f38b) | Lists uplifting piano tracks as royalty-free with no attribution | AI-generated; read the exact terms |
| [Silverman Sound, "Spark of Inspiration"](https://www.silvermansound.com/free-music/spark-of-inspiration) | Close to the brief | The free version appears to need a credit line |

## Real footage, later

For now every robot shot (10, 13, 15, 18–22, 24 and 25) is rendered in MuJoCo and tagged `SIMULATION`. The real arm hasn't run yet and Rev B hasn't been printed. We'll probably edit the cut and re-record real footage later: when the arm runs on the printed centrifuge, re-film the walkthrough shots (18–22, 24 and 25), speed them up, and change the tag to `REAL FOOTAGE · N×` with the true factor. The freeze frames carry over unchanged: they're built from the run's files, which look the same for sim and real. The cuts are timed so a real clip can replace a sim clip of the same length without re-editing anything else.

## How we'd make it, after your OK

- **Chalk scenes:** drawn in code. Each stroke is a path that the chalk arm's tip follows, with a chalk-texture brush, dust particles and a following camera. Rendered frame by frame, so the timing is exact.
- **The turn:** the same renderer, cross-fading the chalk arm into the Console's arm drawing.
- **Two-systems graphics (shots 11, 12 and 16) and the roadmap (27):** the same motion-graphic renderer, in the Console's style.
- **The walkthrough (shots 17–25):** one fresh MuJoCo run on Rev A with a model planning it, recorded with the run's files, plus the device's verification checks for the lid refusal, the M1 tube and the Rev B lid until a model run covers them. The safety stop and the amendment can come from the recorded Sonnet 5.5 run. This only runs System 1's code; we don't change it.
- **Console B-roll and Live replays:** scripted browser captures at 1080p, so they can be re-shot after any UI change.
- **Cold open:** trimmed and sped to 1.75× in the edit from a copy of `intro.MOV`.
- **Voiceover and music:** Karthik records the voiceover as an mp3 and brings the music. Until then, a placeholder read keeps the timing honest; once his mp3 is in, every shot's in and out points are re-cut to it.
- **Assembly:** ffmpeg, from an edit list in this folder, so any shot can be swapped and the whole video rebuilt with one command.

## Claims on screen

Every number or source line on screen is from the script's [checks table](script.md#checks-before-recording) and [Sources](script.md#sources). Extra on-screen items:

| On screen | Holds because | Watch for |
|---|---|---|
| `ETH: some problems stay exponentially hard` · `lower bounds rest on it` (shot 2) | ETH, Impagliazzo and Paturi 2001 (script source 3); the survey of lower bounds assuming ETH (script source 32) | Plain-language gloss. The stack of books is "lower bounds", not "complexity theory": refuting ETH wouldn't settle P vs NP |
| CompCert and seL4 plaques, the ledger (shot 3) | Script sources 4–6, 12–23 | The 2012 Airbus line is an evaluation. The red team was given a partition and couldn't break out; not "unhackable". AlphaProof's IMO problems were translated into Lean by hand first |
| `no pinch · ADA §309.4` (shot 4) | Access Board guide to §309.4 (script source 9) | A US building standard, used as the reason the rule exists |
| Pirbright panel (shot 5) | HSE final report, via script source 24 | Keep "most likely source". The tyre track stands for the contractors' vehicles HSE named |
| JWST panel (shot 6) | Script source 26 | "Five causes" keeps the delay from being pinned on the fasteners alone |
| Dyson panel (shot 7) | Script source 25 | Keep "15 years" with this source |
| VLA box (shot 11) | Script sources 28–31 | Don't write "made for the SO-101": pre-trained mostly on SO-100 data, evaluated on both |
| System 1 and System 2 labels (shots 13–16) | `docs/system-boundary.md`; `docs/decisions.md` D31 (14 N), D34 (15 N) | Show a recorded run; the model loop is still being built |
| `pipeline_error` and rerun (shot 18) | Recorded Sonnet 5.5 run, seq 16–23 | Injected errors were on in that run |
| Approval cards (shots 19, 20, 23) | Approval rules and levels in `docs/system-boundary.md` | The recorded run's approvals were automatic (sim). Use a Console run with a person approving |
| `16.4 N over hard cap 15.0 N` (shot 20) | Recorded run, seq 49–57 | Use this run's numbers or the filmed run's, never retyped |
| Retry budgets by setting (shot 20) | `docs/system-boundary.md`; Methodology page | |
| `1000rpm  0:30` vs `1000 RPM 0:30`, `level 1 · notify` (shot 21) | Recorded run, seq 85–94; levels assigned by plain code | The firmware's format differs from the manual (`gallery.md`) |
| `REFUSED · handle_1 needs a pinch grip…` (shot 22) | `verify.stock.json`, F2 on Rev A | From the verification check, not a model run, until a model run tests the lid |
| `Rev B` morph and `fingertip catches it · no pinch needed ✓` (shot 23) | Rev A and Rev B meshes; the generic CAD check "a pull control catches the fingertip when it pulls, so nothing needs a pinch" (`system-2/cad/README.md`) | Rev B was drawn by the team. Don't label the morph "proposed by the model": the analyst hasn't proposed a patch from a run on this device yet |
| `11.1 mm` gap and `TUBE` (shot 24) | `source/faults.md` (11.1 mm vs 3.2 mm); `verify.stock.json` F3s on M1 | The tube is placed by the check; the arm's pick doesn't work on the stock gripper in sim yet |
| Rev B lid at 100° (shot 25) | `verify.stock.json`: "handle_1 swung to 100 deg" on Rev B | Rev B's full workflow doesn't pass yet in sim (tube pick); show the lid re-test only |
| `another arm could take its place` (shot 26) | Seven tools are the only crossing; `rig.Rig` swaps sim and real | "Could": no second arm has been run. Ghost the second arm in outline |
| `next: real arm → lab instruments → assistive devices` (shot 27) | `docs/journey.md` "Next"; `docs/product.md` pitch framings | Drawn in outline and labelled `next`, so it doesn't read as done |

## Sources

All claim sources are listed in [script.md](script.md#sources). The style reference for the chalk scenes is the RSA Animate series of whiteboard explainers (a hand drawing continuously, the camera following it); it is a visual reference only, not cited on screen.

## Questions for Karthik

1. **The cold open:** `intro.MOV` is in `video/real-world-assets/`. Is that the final take, or will you re-film it? And is 1.75× the speed you want, or faster still?
2. **Tag on the cold open:** it's real footage sped up 1.75×, but it's staged, not evidence. Leave it untagged, or add `REAL FOOTAGE · 1.75×` for consistency?
3. **A fresh run for the walkthrough:** neither recorded model run on the centrifuge planned a lid test. Should we record one (with the no-thumbs rule in the request) so FR7 comes from a model run instead of the verification check?
4. **The step rail (shots 17–25):** helpful, or too much on screen with the split overlays?
5. **The ending's B-roll (shot 26):** one highlighted piece per beat for 19 s. Fine, or cut to the title sooner?
6. **Your mp3:** when it's in, send it with any lines you changed while reading, and we'll re-cut every shot to it.
