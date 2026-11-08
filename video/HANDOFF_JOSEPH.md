# Footage handoff: what we need from the real arm

For Joseph, and for the Claude Code agent you run it with. Nov 8, 2026.

The pitch video ([script.md](script.md), [storyboard.md](storyboard.md)) is built and previewed, but **every robot shot in it is MuJoCo** and carries a `SIMULATION` tag. This file lists the footage that would let us show the real SO-101 on the real MC-6. It also says how to run each shot, how to record it, and how to hand it back. Karthik cuts the video. You and your agent only capture.

Your calls on the arm come first. If anything here conflicts with how you run the real rig, or with a rule in [the server README](../system-1/server/README.md) or [the real test plan](../system-1/docs/real-s1-s2-test-plan.md), do it your way and tell us what changed.

## 1. Ground rules

- **No code changes for footage.** Don't touch verdict rules, the torque gate, force limits, skills or the harness to make a shot work. If a shot needs a change, skip it and write down why. That note is useful to us as well.
- **Nothing staged.** Every result on screen must come from a real run. If a step fails, keep it: a real failure is better footage than a faked pass.
- **Safety as you run it.** Torque goes on only after your yes at the terminal. Don't pass `--enable-torque`. Keep a hand near the power switch. Stop from System 1's terminal (Ctrl+C) or the switch. The agent must never answer the torque prompt, approve a plan or run the arm unattended.
- **Real and sim stay labelled.** Every file name says `real` or `sim` (section 6).

## 2. What to capture, by priority

| # | Shot | Why we need it | Who | Priority |
|---|---|---|---|---|
| A | The real arm scanning the MC-6, then pressing its controls, filmed from a tripod | Replaces the sim in the demo section (0:31–1:27). The single biggest gain | Joseph films; agent runs the commands | **Must** |
| B | The Console's Prod Live during that run: the annotated wrist feed and the 3D tile, screen-recorded | The demo section is a tour of the Console. Today there are no images of OWLv2 boxes or SAM masks at all | Agent | **Must** |
| C | A model-driven real run started from the Console: start form, plan approval card, someone clicks Approve, steps, report | The "a person approves it before anything moves" beat, on the real arm | Agent records; a person approves | **Must** |
| D | Close-ups: the jaws landing on a button, the LCD changing after a press | Cutaways that prove it's real hardware | Joseph films | **Should** |
| E | The D32 scale test: a press on a kitchen scale beside the force estimate | Shows the force limit with a real number. You wanted this test run anyway | Joseph films; agent logs | **Should** |
| F | Lid and tube on the real arm, if they work today; otherwise the sim versions recorded clean | Rev B's lid fix is the payoff of the CAD story. In the sim, the tube drop and lid close now pass 10/10 (`fce8af7`) | Either | **Should** |
| G | The CAD fix loop on a recorded run, with Change Review and Revision History populated | Those two Console screens were empty in our recordings, so the video doesn't show them. A patch proposed from a run hasn't been shown yet | Agent | **Nice** |
| H | Bench B-roll: you typing yes, a hand on the power switch, the rig wide | Short cutaways for pacing | Joseph films | **Nice** |

## 3. Setup

### Cameras

- **Phone on a tripod (A, D, E, H).** Landscape, 4K or 1080p, **30 fps**. Lock exposure and focus before the run. Most phones do this with a long press on the subject. Turn off stabilisation zoom and HDR flicker. Use no music and keep the room sound.
- **Angles for A.** Do two passes if you can:
  1. Three-quarter front: arm and MC-6 both in frame, panel readable, about 45° off the panel's normal.
  2. Side: the arm's reach towards the panel, jaws visible.
- **Close-ups for D.** Fill the frame with the panel; the LCD must be readable.
- **Clean background.** No laptops showing unrelated screens and no faces of people who haven't agreed to be filmed.

### Screen recording (B, C, G)

- **Headed Chrome with the GPU on.** Our old Live clips were recorded headless, and the 3D view came out aliased.
- **Window size.** Set the browser window so the page viewport is exactly 1920 × 1080 at 100% zoom: no bookmarks bar, no extensions bar, no other tabs. The Console's dark theme.
- **Recording.** Use OBS, or Playwright's `recordVideo` at 1920 × 1080 if the agent drives the browser. Record at 30 fps.
- **Our tour script.** It's in [video/build/tour.mjs](build/tour.mjs). It drives the Console with Playwright and logs every move and click with a timestamp to a JSON file. Reuse it for B and C if it fits. The click log lets us time the cut to the voiceover.

### The real stack

Your usual setup, from [the real test plan](../system-1/docs/real-s1-s2-test-plan.md). `COM11` and `CAL.json` stand for your port and calibration file. Add the MC-6 readout flags you use (see [appliance-sensor-setup.md](../docs/appliance-sensor-setup.md)) so verdicts come from the board.

```bash
# terminal A, system-1: the real arm. Type yes yourself.
uv run rav-server --robot real --arm-port COM11 --calibration CAL.json   # plus your readout flags

# terminal B, system-2: rav-agent on that System 1, for the Console's Prod Live
uv run rav up --system1 http://127.0.0.1:8780/mcp --reuse-scan

# terminal C, system-2/console/web: the Console
npm run dev        # http://127.0.0.1:5173, choose Prod, press GO
```

Before the first take, run `python hardware/tools/scan_check.py COM11 CAL.json` as the test plan says, so you know the rig is intact.

## 4. Shot by shot

### A and B: the real scan and presses (must)

This covers the demo's first half: survey, scan, segment, map, touch, then the test.

1. Start the stack (section 3). In the Console, choose **Prod** and open **Live**.
2. Start both phone and screen recording, then clap once in view of the phone with the Console visible. The clap lets us sync the two.
3. Run the scan. You can start it from the Console, or from terminal B with `uv run rav explore --url http://127.0.0.1:8780/mcp --id real-scan-1`.
4. Then the presses: `uv run rav run --url http://127.0.0.1:8780/mcp --id real-press-1 --only button_1`, then a full plan (`--id real-full-1`).
5. Use whatever skills work on the real arm today: presses for certain, and flips and turns only if you've cleared them. Don't add skills for the video.

**In the screen recording:** Prod Live's big wrist panel with its annotated frame (boxes and masks) through the scan, then the 3D tile (click to swap) during the touches and presses. Hold on each for a few seconds. Fast cursor moves are fine, because the edit zooms in on them.

**Keep:** the run folders `system-2/runs/real-scan-1`, `real-press-1`, `real-full-1` (`events.jsonl`, `report.json`, any `cameras.mp4`).

### C: a model-driven real run from the Console (must)

1. With `rav up --system1 …` running, in Prod Live use the start form. Pick the model: `claude-sonnet-5-5` matches the sim demo. Pick the turn limit, then start.
2. Type the project's rule into **Message the model** about 10 s in: `This project's rule: usable with no thumbs.` The harness doesn't pass project rules to the model yet (`service.py`); that's how we delivered it in the sim run as well.
3. When the **plan approval card** appears, a person (you or Karthik) clicks **Approve** on camera. The agent must not.
4. Let it run to the report. Record the whole session. If a step stops with an escalation, keep it; the video tells that story ("the run stopped, and the plan was amended").

### D: close-ups (should)

During A or C, film the jaws landing on a button cap and the LCD as it changes. Shoot 3 to 5 presses with 2 s of stillness before and after each.

### E: the D32 scale test (should)

[The System 1 handoff](../system-1/HANDOFF.md#3-what-needs-you), item 1:

1. Tip about 250 mm out and 20–30 mm up, tool 45° down.
2. Move 15 mm in free air and log the estimate.
3. Press a kitchen scale with about 3 N and log the estimate.

Film the scale's display and the arm in one frame, and have the agent print the estimate in a large terminal font beside it, or log it with timestamps. Write both numbers in the manifest. Whatever it shows is useful, to you and to the video.

### F: lid and tube (should)

- **Real arm:** only if `hook_pull` and the gripper (motor 6) work on the real arm today. Film the lid close or the tube drop as in A.
- **Otherwise, the sim:** run Rev B with both covers up (the `verify.yaml` workflow from `fce8af7`). Record the Console's 3D replay full-frame, the way `clean_3d.mp4` was made: canvas only, UI hidden, frame-stepped at 1/15 sim s per frame, 30 fps. Name it `sim_…`.

### G: the CAD fix loop (nice)

Run `rav fix` on a recorded run so a patch is proposed from findings. Leave out `--approve` so it stops at the proposal and a person approves in the Console. Then screen-record the Console in Demo:

- **Design Analysis:** the finding traced to its part
- **Change Review:** the proposed patch, with a person approving
- **Revision History:** the new revision

Two passes over each screen, slow scrolls. If `rav fix` needs anything that isn't set up, write that down and skip it.

### H: bench B-roll (nice)

Ten-second clips: the rig wide, a hand on the power switch, typing yes in terminal A, the MC-6's panel lit.

## 5. What the agent can and can't do

**It can:**
- start the servers and the Console;
- run `rav explore`, `rav run`, `rav agent` and `rav fix`;
- drive and record the Console with Playwright;
- copy the run folders;
- write the manifest (section 6).

**It can't, and a person must:**
- answer the torque prompt;
- approve plans or patches;
- answer System 1's "what changed" prompts at terminal A;
- operate the phone camera;
- stop the arm in an emergency.

The agent should stop and ask you if a command fails, rather than change code to get past it.

## 6. Hand-back

Put everything in **`video/footage/joseph/`** (git-ignored, because the files are large), or in a shared Drive folder linked from the PR. Use these names:

```
real_A_scan_threequarter.mov        real_A_scan_side.mov
real_B_prodlive_scan.mp4            real_C_console_modelrun.mp4    (+ real_C_console_modelrun.json click log)
real_D_closeup_press_01.mov ...     real_E_scale_test.mov
real_F_lid_close.mov  or  sim_F_revB_lid_tube_3d.mp4
sim_G_fix_loop_console.mp4          real_H_bench_01.mov ...
runs/real-scan-1/  runs/real-press-1/  runs/real-full-1/  runs/<model run id>/
```

Add a `manifest.json`, shaped like this (our sim footage has one):

```json
{
  "files": [
    {
      "path": "real_A_scan_threequarter.mov",
      "shows": "Real SO-101 scanning the MC-6, then pressing button_1",
      "run_id": "real-scan-1",
      "clap_t": 3.4,
      "clip_t_of_event": { "survey": 5.0, "scan": 31.2, "touch": 88.0, "press_button_1": 140.5 },
      "skills_used": ["press"],
      "notes": "Second press missed by 4 mm and retried"
    }
  ],
  "did_not_happen": ["Flips refused on this arm today"],
  "scale_test": { "free_air_n": null, "scale_n": null, "estimate_n": null }
}
```

- **`clip_t_of_event`** is the clip time of each event in the run's `events.jsonl`. The agent can compute it from the clap or a visible on-screen change.
- **`did_not_happen`** lists what you tried and couldn't get. It keeps the script honest.

## 7. Done when

- [ ] A and B recorded, with their run folders.
- [ ] C recorded through to the report, with Approve clicked by a person.
- [ ] Whatever of D–H was possible, recorded or noted in `did_not_happen`.
- [ ] `manifest.json` written. The files sit in `video/footage/joseph/` or on Drive, and the PR names where.

## 8. Your calls

- Which skills are cleared on the real arm today (press only, or flip and turn too)?
- Whether the gripper (motor 6) is driven yet, which decides F on the real arm.
- Which MC-6 readout path to use for verdicts (the Arduino R4's HTTP readout or serial).
- Anything here you'd rather not run on the real arm. Skip it and say so.
