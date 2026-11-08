# Draft 11 plan

How the first real-footage cut will be built, once Karthik records [script.md](script.md) Draft 11. Nothing here is rendered yet.

## The footage

| Clip | What it is | Use |
|---|---|---|
| `initial-vids/IMG_9611.MOV` | Overhead phone, 1920 × 1080 at 60 fps, 3:03. The whole real run: tube pick from the rack, tube into well A, lid close, POWER, TIME+, SPEED, START (the ring lights), STOP. Started 11:18:39 | **The main arm view.** Left half of the split screen |
| `initial-vids/WhatsApp Video …mp4` | Screen recording of the Console's Live screen, 1600 × 954, 6:46. Terminal (0:00–1:00), then Live: the wrist feed with detection rings, the 3D arm, plan-1 and **Approve** (≈3:12), each step's verdict, the report and summary (≈6:12–6:40) | **The Console view.** Right half of the split screen, and the report close-ups |
| `initial-vids/IMG_5915.mov` | A second phone, portrait, only 224 × 128, 3:06, from an earlier attempt (11:04). Close side views of the lid and the ring light at the end | Small inset tiles only. It's too low-resolution to fill a frame |
| `real-world-assets/intro.MOV` | The chalkboard take | Cold open and close |

**Sync.** The run is `agent-centrifuge-111834`, which started at 11:18:34. The overhead clip started at 11:18:39. The screen recording joins the run at about 1:00. I'll line the two up on one visible event: the POWER flip, where the switch moves on camera and POWER's reading changes in the Console. Then I'll check with a second event, START lighting the ring.

## Section by section

### 1. Cold open (0:00–0:08)
- Erase at 1.75×, as now.
- **The zoom becomes a snap.** As Karthik steps up (source ≈ 9.5–11.5 s), the camera goes from the crop to the chalk tip in about 6 frames (0.2 s). Each frame is blended from several sub-frame positions, giving directional motion blur, so it reads as one jump.
- On landing, **RAAV appears in Michroma**, the Console's font, with a short scan-line build rather than handwriting. The board becomes the Console's grid.
- Bayan's handwritten logo moves to where handwriting fits: the chalkboard diagram in §2.

### 2. What RAAV is (0:08–0:21)
The chalkboard diagram from Draft 10, re-timed. The last line becomes "Here it is on our centrifuge", which leads straight into the real footage.

### 3. The real run (0:21–1:06): split screen and multiple views
- **Layout:**
  - Left 55%: the overhead phone clip, cropped to the arm and centrifuge.
  - Right 45%: the Console screen recording, cropped to the panel the voice is on: plan-1 for the plan, the wrist feed for the scan, the verdict list for the results.
  - Both sit in thin frames on the Console's dark grid, labelled `SO-101 · real` and `RAAV Console · live`.
- **A step strip** runs along the bottom: `load tube · close lid · POWER · TIME · SPEED · START · STOP`. Each item lights as the arm does it, and turns green or amber with its verdict.
- **Multiple views of the arm.** Three cut-aways, two or three seconds each, take over the left half:
  1. The wrist camera's feed with its detection rings, during "scans the panel".
  2. The Console's 3D arm, during "a model writes the plan".
  3. The second phone's close view of the ring light, after START.
- **The approval:** the Approve click in the screen recording, zoomed, on "a person approves it".
- **Speed:** the run is about 3 minutes, and this section is about 45 seconds. Each step gets its own speed so it lands on its spoken word, using the same time-warp the sim tour uses. The tube pick and lid close run 4–6×, and the presses 2–3×.
- **Cards** carry only what the voice doesn't say: `STOP · 19.5 N, 5.6 mm`, `display read “2800 RPM 0:30”`, `reward 0.83`, `5 passed · 1 untested`.
- The `SIMULATION` tag is off here: this is the real arm.

### 4. Fixing the design (1:06–1:28)
- **Centrifuge tube adapter (about 7 s):**
  - The well insert, Rev A (`well_insert_A_revA.stl`) beside the agent's patch.
  - A cut-away through the bore shows the 16 mm tube sitting high, then seated.
  - The bore wall and the 45° lead-in are highlighted.
  - Tags: `+0.4 mm · 45° lead-in`, `Opus 5.5 · 14 tool calls · $0.43`, `seated within 0.97 mm (sim)`.
  - The agent's patched mesh isn't in the repo, so I'll draw its geometry from the published numbers. **Ask Bayan whether the run's patch file can be shared**, and use the real one if so.
- **Microwave hinge (about 6 s):**
  - Rev A and Rev B hinges (`hinge_*_revA/B` meshes), side by side, slowly turning.
  - The knuckle gaps and the pin head are highlighted.
  - Tags: `0.025 mm → 0.25 mm clearance`, `0.4 mm knuckle gaps`, `pin: two heads → one`, `door swings to ~145°`.
  - **Labelled as the team's Rev B, not the agent's.**
- Renders: the STLs drawn in the browser (three.js) in the Console's colours, frame-stepped like everything else.

### 5. Two systems (1:28–2:00)
- The pre-filled panels, re-timed to the shorter text.
- System 1's force chart switches to the real run's peak forces where the run folder has them. Otherwise it stays on the sim run, labelled `sim`.

### 6. Why it matters, and the close (2:00–2:46)
- As in Draft 10: the Dyson centrepiece, then the globe pull-back.
- **The close mirrors the opening snap:** a motion-blurred jump out of the Console and into the take, landing on the chalk tip. Karthik writes RAAV as "That's RAAV." ends, then walks off, then fade to black.

## Audio
- Karthik's Draft 11 voiceover, with the placeholder score ducked under it.
- The take's room sound under §1 and the close.
- The overhead clip's own arm sound, low, under §3. It sells that the footage is real.

## Needed from you
1. The Draft 11 voiceover.
2. Whether "That's RAAV." is the closing line you want (see the note in my message).
3. Bayan's patched insert from the tube-seat fix, if it can be shared.
4. The run folder `system-2/runs/agent-centrifuge-111834`, if Joseph can commit or send it. It gives exact step times and forces for the step strip and the force chart. Without it I'll take them from the screen recording.
