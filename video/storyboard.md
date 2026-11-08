# Demo video storyboard

**Draft 10, Nov 8.** Goes with [script.md](script.md). About 2:39, 1920 × 1080 at 30 fps, rebuilt to Karthik's re-recorded voiceover. The build is in [build/](build/): `node render.mjs video`, then `./mix.sh`.

## Rules for every shot

- **Visuals add; they don't repeat.** On-screen text never restates the spoken sentence. It carries what the voice leaves out: numbers, names, sources, the exact reason a step stopped. Captions carry the spoken words.
- **The chalk arm points.** In the chalk shots, drawings appear on their own (a quick chalk reveal), and the chalk SO-101 points its jaw at each part as it's named, with a small tap and a puff of dust. It doesn't write.
- **Sim is tagged.** Every robot shot is MuJoCo and carries `SIMULATION` at bottom right.
- **Colour:** chalk yellow and the Console's accent (`#eebc24`) for the robot and System 1, grey-blue (`#8fb3d9`) for System 2, amber for a person, pass green and fail red for verdicts.

## Shots

| # | Time | Picture | On screen (never the spoken words) | Source |
|---|---|---|---|---|
| 1 | 0:00–0:06 | The take, cropped on the board's question mark: Karthik erases the buzzwords | — | `intro.MOV` 0–10.5 s at 1.75× |
| 2 | 0:06–0:09 | He steps up and puts the chalk to the board. It freezes as the chalk touches, and the camera pushes in on its tip | — | `intro.MOV` 10.5–11.5 s, then held |
| 3 | 0:08–0:11 | The drawn chalkboard opens out of the chalk's tip in a soft circle, and RAAV writes itself on, left to right | Bayan's logo (`docs/assets/logo.png`, our handwriting) | Drawn |
| 4 | 0:11–0:24 | Chalkboard: RAAV rises to the top. A prototype box, a manual, the chalk arm, a report, joined by arrows. The arm points at each as it's named | `MC-6 centrifuge · Rev A`, `manual.md`, `SO-101 · one $19 wrist camera`, `findings · coverage · reward` | Drawn |
| 5 | 0:24–0:26 | On "never seen": the board's lines lift and the slate darkens into the Console's grid | — | Transition |
| 6 | 0:26–1:22 | A tour of the Console with a cursor and a dynamic zoom: the Rev A run's stages, the plan and its approval, the test, the stopped step s1, the skipped lid (s7), Design Analysis, then the Rev B run | On "proposes a fix": `the full loop, in the sim · D36` — `MC-6 tube stopped 8.15 mm high`, `Opus 5.5 widened the bore`, `retest: seated within 0.97 mm` | `tour/demo` (Rev A and Rev B runs) |
| 7 | 1:22–1:52 | Two full-height panels, already filled with the Rev A run's data and dim; each part lights up as it's named. The model's `move_joint` and `grade_own_step` bounce off the tool lane ("no such tool"); a 40 N press goes through and stops at the cap. On "four models" the model name flicks through four; on "simulator or a real arm" System 1's header flips between `MuJoCo · simulator` and `SO-101 · real arm`, and the appliance names cycle | Data, never the spoken list | Rev A run `events.jsonl` |
| 8 | 1:52–2:05 | The VLA card over the dimmed panels, demonstration reels filling in; then `manual.md` glows; then an amber line under System 1 | `SmolVLA · 50 demos/task`, `GR00T N1 · 30–300 demos/task`, `new kind of control → a new skill, in code` | Diagram |
| 9 | 2:06–2:19 | One shared screen: the Console in a window on the right moving through Studies, Story, Settings and Methodology, a feature label above each; six case cards on the left, each filling in as it's named | `Lean · ETH refutations checked, Oct 2026`, `CompCert · ATR 42/72`, `seL4 · DARPA HACMS`, `Pirbright 2007`, `JWST · 29-month delay`, `Dyson · 5,127 prototypes` | `tour/scenes` |
| 10 | 2:19–2:30 | **The pan-out.** On "Today", the cards slide away and the Console window shrinks onto New York as a spinning globe comes in. The twelve appliance names flank it; a pin lands on New York; a cloud marked System 2 links to it by a dashed tunnel; on "any lab", pins light up around the world | `centrifuge · sim + real`, `MC-6 · real arm`, `System 2` | Drawn |
| 11 | 2:30–2:39 | **The close.** Back to the take, frozen on the chalk's tip, pulling out to the full frame while Karthik writes RAAV over the last line. He walks off | — | `intro.MOV` 11.5–21 s |
| 12 | 2:37–2:39 | Fade to black on the empty board with RAAV | — | — |

## Audio

Karthik's re-recorded voiceover; the placeholder score from `build/music.py`, ducked under the voice (swap in a real track with `mix.sh`); the take's own room sound under shots 1–2 and 11.
