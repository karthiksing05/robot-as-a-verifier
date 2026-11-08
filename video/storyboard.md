# Demo video storyboard

**Draft 9, Nov 8.** Goes with [script.md](script.md). About 2:33, 1920 × 1080 at 30 fps, rebuilt to Karthik's re-recorded voiceover. The build is in [build/](build/): `node render.mjs video`, then `./mix.sh`.

## Rules for every shot

- **Visuals add; they don't repeat.** On-screen text never restates the spoken sentence. It carries what the voice leaves out: numbers, names, sources, the exact reason a step stopped. Captions carry the spoken words.
- **The chalk arm points.** In the chalk shots, drawings appear on their own (a quick chalk reveal), and the chalk SO-101 points its jaw at each part as it's named, with a small tap and a puff of dust. It doesn't write.
- **Sim is tagged.** Every robot shot is MuJoCo and carries `SIMULATION` at bottom right.
- **Colour:** chalk yellow and the Console's accent (`#eebc24`) for the robot and System 1, grey-blue (`#8fb3d9`) for System 2, amber for a person, pass green and fail red for verdicts.

## Shots

| # | Time | Picture | On screen (never the spoken words) | Source |
|---|---|---|---|---|
| 1 | 0:00–0:06 | The take, cropped to center the board's question mark: Karthik erases the buzzwords | — | `intro.MOV` 0–10.5 s at 1.75× |
| 2 | 0:06–0:10 | Same crop: he writes RAAV over the question mark | — | `intro.MOV` 10.5–19 s at 2× |
| 3 | 0:10–0:12 | Same crop: he walks out of frame | — | `intro.MOV` 19–21 s |
| 4 | 0:12–0:15 | The camera's own push-in on RAAV, the crop easing out to the full frame, then held. The real board fades to the drawn slate while his handwritten RAAV stays exactly where it is (a cutout from that frame, `build/raav_hand.png`), then rises to the top | — | `intro.MOV` 21–25.2 s, held |
| 4b | 0:15–0:28 | Chalkboard: his RAAV at the top. A prototype box, a manual, the chalk arm, a report, joined by arrows. The arm points at each as it's named | `MC-6 centrifuge · Rev A`, `manual.md`, `SO-101 · $19 wrist camera`, `findings · coverage · reward` | Drawn |
| 5 | 0:28–0:31 | On "never seen": the board's lines lift as dust and the slate darkens into the Console's grid; the chalk arm becomes the rendered arm, which becomes the first footage | `no device names in prompts or harness code` | Transition |
| 6 | 0:31–0:45 | Footage: survey, scan, segment, map, touch, with the step rail lit along the top. Freeze on the wrist camera at the failed scan, then on the rerun | Rail: `survey · scan · segment · map · touch · plan · test · verdicts · report · CAD fix · Rev B` | Rev A run, `clean_3d`, `wrist` |
| 7 | 0:45–0:52 | The Console's approval card, zoomed; Karthik clicks Approve | `plan check refused plan-0 · model fixed it` | `ui_plan_approval` |
| 8 | 0:52–1:00 | The test at 1x: presses, flips, the dial | `cap 15 N · steps ask ≤ 14 N`, `retries: 0 / 2 / 4` | `clean_3d_test_1x` |
| 9 | 1:00–1:07 | Freeze at step s1 | S1: `lcd “1000rpm  0:30” ≠ “1000 RPM 0:30”`; S2: `plan amended · level 0, set by code` | Rev A run, step s1 |
| 10 | 1:07–1:14 | Freeze at step s7, then the Console's skipped row, zoomed | S1: `SKIPPED · handle_1 needs a pinch grip · no-thumbs rule` | Rev A run, step s7 |
| 11 | 1:14–1:22 | Design Analysis: Rev A to Rev B, the F2 fix lighting up the lid handle | `hook lip · Rev B as drawn by the team`, a person's card: `approve` | `ui_design_analysis` |
| 12 | 1:22–1:27 | The Rev B run | `handle_1 swung to 100° (verification check)` | Rev B run, `verify.stock.json` |
| 13 | 1:27–1:55 | Two full-height panels, already filled with the Rev A run's own data and dim. System 1: the 9 controls OWLv2 + SAM mapped, its six skills, peak force per step against the 15 N cap, the s1 FAIL and s7 SKIPPED verdicts. System 2: manual lines, plan-1's steps, the amendment, the findings; the model name in its header. Between them, the 7 real tool names. Each part lights up with an underline as it's named. Cartoon beat: the model's `move_joint` and `grade_own_step` messages bounce off a red gate (“no such tool”); a `press button_3 at 40 N` request goes through and its bar stops at the cap. The model name flicks through four models and settles | Data, never the spoken list | Rev A run `events.jsonl` |
| 14 | 1:55–2:12 | A card over the dimmed panels: `one network`, demonstration reels filling in, `SmolVLA · 50 demos/task`, `GR00T N1 · 30–300 demos/task`. It leaves; `manual.md` glows. Last, an amber line under System 1: `new kind of control → a new skill, in code` | Sources in small mono | Diagram |
| 15 | 2:12–2:28 | One shared screen. Right: the Console in a window moving through Studies, a project's Story, Settings and Methodology, a feature label above each view. Left: six case cards, software (proven before use) then hardware (found after the fact), each filling in as it's named; the examples take under ten seconds | `Lean · ETH refutations checked, Oct 2026`, `CompCert · ATR 42/72`, `seL4 · DARPA HACMS`, `Pirbright 2007`, `JWST · 29-month delay`, `Dyson · 5,127 prototypes` | `tour/scenes` |
| 16 | 2:29–2:33 | Title card | **RAAV · ROBOT AS A VERIFIER**, `MakeCU 2026` | — |

## Audio

Karthik's re-recorded voiceover; the placeholder score from `build/music.py`, ducked under the voice (swap in a real track with `mix.sh`); the take's own eraser sound under shots 1–3.
