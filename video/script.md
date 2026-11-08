# Demo video script

**Draft 12, Nov 8, for a re-record.** Built around the second real run on the SO-101 (Nov 8, 11:34, `agent-centrifuge-113400`, Claude Haiku 5.5), filmed overhead (`initial-vids/IMG_5920.MOV`), handheld from the side (`initial-vids/WhatsApp Video … 11.37.21.mp4`) and screen-recorded in the Console (`initial-vids/WhatsApp Video … 11.41.33.mp4`). About 395 spoken words, roughly 2:50 with the cold open. The plan for the cut is in [draft-plan.md](draft-plan.md).

**What changed from Draft 11:** §3 and §4 follow the new run: every control it pressed responded, but TIME didn't add time and START showed LID, which the model tied to the tube being let go 56 mm above its seat. That leads straight into the CAD section, where the tube seat is the fault the agent has fixed before.

**From Draft 10:**
- **The demo is the real run**, in the order the arm ran it: load a test tube, close the lid, switch on, press TIME, turn the speed dial, START, STOP. It says what the run actually found.
- **A new CAD section:** the centrifuge's tube adapter (the CAD agent's fix, in the sim) and the microwave's two hinges (Rev A and Rev B).
- **Two systems is shorter.**
- **The opening:** a fast, motion-blurred push-in as Karthik steps up to the board, then RAAV in the Console's technical font (Michroma). The close mirrors it.

| § | Section | Time | Words |
|---|---|---|---|
| 1 | Cold open | 0:00–0:08 | 0 |
| 2 | What RAAV is | 0:08–0:21 | 37 |
| 3 | The real run | 0:21–1:08 | 118 |
| 4 | Fixing the design | 1:08–1:28 | 54 |
| 5 | Two systems | 1:28–2:00 | 82 |
| 6 | Why it matters, and the close | 2:00–2:46 | 101 |
| | **Total** | 2:46 | **390** |

Timings assume a natural read; the cut follows the recording.

---

## 1. Cold open · 0:00–0:08

*No voiceover. The take (`intro.MOV`), cropped on the question mark: Karthik erases the buzzwords (1.75×). As he steps up to the board, the camera snaps in on the chalk's tip in a few frames, motion-blurred so it reads as one jump. RAAV appears in the Console's technical font (Michroma), and the board becomes the Console's grid.*

---

## 2. What RAAV is · 0:08–0:21

> This is RAAV, Robot As A Verifier. Give it a prototype and its manual, and a low-cost robot arm tests every control it can find, then reports what it measured. Here it is on our centrifuge.

*The chalkboard diagram (prototype → manual → arm → report), with the arm pointing at each, as in Draft 10.*

---

## 3. The real run · 0:21–1:08

> It scans the panel with one wrist camera and finds six controls. We give it the order of steps; a model writes the plan, quoting the manual for what each step should do, and a person approves it before anything moves.
>
> Then the arm works through it. It loads a test tube, closes the lid, switches the power on, presses TIME, turns the speed dial, and presses START, then STOP. A board inside the centrifuge reports what each control actually did, and fixed rules turn that into a verdict.
>
> All five controls it pressed responded, but two results didn't add up. TIME didn't add any time. And after START, the display read LID instead of running. RAAV suspected the tube, which it had let go well above its seat, and flagged both for a person to check instead of guessing.

*Split screen: the overhead footage on the left, the Console's Live screen on the right, in sync. A step strip along the bottom lights each step as the arm does it. Other views cut in: the wrist camera's feed with its detection rings, the Console's 3D arm, and the handheld side camera's close-ups of the buttons and of the display reading `LID`. Cards carry what the voice doesn't say: `released 56.2 mm above the seat`, `time stayed 0:40`, `TIME+ · 22.5 N, 7.2 mm`, `reward 0.83 · 5 passed · 1 untested`.*

---

## 4. Fixing the design · 1:08–1:28

> A tube that won't seat is a fault our CAD agent has fixed before, in simulation: it widened the adapter's bore and added a lead-in, and on retest the tube seated. Our microwave's hinge fused shut when printed; its second revision opens the clearances, and hinges are next for the agent.

*Two before-and-after diffs, about five seconds each. First, the centrifuge's well insert: Rev A against the agent's patch, with the bore and lead-in highlighted and the tags `+0.4 mm · 45° lead-in · Opus 5.5 · $0.43`, `seated within 0.97 mm (sim)`. Then the microwave hinge: Rev A against Rev B, with the knuckles and pin highlighted and the tags `0.025 mm → 0.25 mm clearance`, `pin: two heads → one`, `Rev B · team`.*

---

## 5. Two systems · 1:28–2:00

> Under the hood, RAAV is two systems. System 1 is the robot: perception, motion, force limits and the verdict rules. System 2 is a frontier model that plans, recovers from failed steps and diagnoses causes. Between them is a small set of tools, none of which moves a motor or grades a step, so either side can be swapped: any of four models, the simulator or the real arm. Vision-language-action models fold all of this into one network and need new demonstrations for every task. Our split needs a manual.

*The two pre-filled panels from Draft 10, now with the real run's data where we have it.*

---

## 6. Why it matters, and the close · 2:00–2:46

> Why does this matter? Software already has verification, from AI-written proofs to flight code. Hardware has nothing like it. In James Dyson's words, "I made 5,127 prototypes of my vacuum before I got it right. There were 5,126 failures." Biosafety labs and spacecraft tell the same story: in hardware, failures surface late.
>
> Today, RAAV runs on twelve appliance designs in simulation and a real centrifuge, with its planner in the cloud. Any lab with a low-cost arm could do the same.
>
> As AI starts designing hardware, every design should be measured before anyone relies on it. That's RAAV.

*As in Draft 10: the case cards with Dyson at the centre, then the pull-back to the globe. On the last sentence, the same fast motion-blurred jump in reverse lands on the take, and Karthik writes RAAV as the line ends. He walks off; fade to black.*

---

## Checks before recording

| Line | Holds because | Watch for |
|---|---|---|
| "finds six controls" | Run `agent-centrifuge-113400`: plan coverage START, STOP, TIME+, POWER_switch, SPEED_dial, DISPLAY (Console recording 11.41, ≈1:13) | |
| "We give it the order of steps; a model writes the plan, quoting the manual" | The project's instruction gives the eight demo steps (`system-2/subjects/centrifuge/project.json`); plan-1's WHY column quotes the manual ("press TIME+ to add 10 s", "Clockwise raises the speed") | Don't say the model chose the steps |
| "loads a test tube, closes the lid, switches the power on, presses TIME, turns the speed dial, and presses START, then STOP" | plan-1: tube_pick, tube_place, lid_close, flip POWER_switch, press TIME+, turn SPEED_dial −60°, press START, press STOP; all eight ran in order | |
| "A board inside the centrifuge reports what each control actually did" | Arduino R4 readout; report lines like `START drives START (0 -> 1 -> 0)` | |
| "All five controls it pressed responded" | `finish_run`: STOP, POWER_switch, TIME+, SPEED_dial, START passed; display untested; reward 0.83 | |
| "TIME didn't add any time" | TIME+: "Press drove the button (0 to 1 to 0), but the time stayed 0:40 and SPEED changed from 2700/2800" | |
| "after START, the display read LID instead of running. RAAV suspected the tube, which it had let go well above its seat, and flagged both" | START: "the display showed 'LID' after it, not a run. Possibly the lid or tube seating blocked the start, which would fit the place step being 56 mm above the seat. Not confirmed." Place: "released 56.2 mm above the seat, so the tube may not have seated fully". The handheld clip shows LID on the display (≈2:05) | "Suspected", not "found": the model says not confirmed |
| "A tube that won't seat is a fault our CAD agent has fixed before, in simulation" | See the next row | Don't say the agent fixed this real tube |
| "In simulation, a tube stopped eight millimetres above its seat; the agent widened the adapter's bore and added a lead-in, and on retest it seated" | `docs/devpost.md`, README: 8.15 mm high; Opus 5.5 analyst, 14 tool calls, 102 s, $0.43; bore 0.4 mm too narrow, widened, 45° lead-in; reseated within 0.97 mm, within 0.2 mm of the designer's fix | Sim only, not printed |
| "Our microwave's hinge fused shut when printed; its second revision opens the clearances, and hinges are next for the agent" | `appliances/microwave/source/faults.md` F1: Rev A (Onshape `Hinge.step`) has 0.025 mm clearances and a pin headed at both ends; Rev B: 0.25 mm, 0.4 mm knuckle gaps, one head. The CAD loop handles sliding buttons only so far (D36) | **Rev B was made by the team, not the agent.** Don't say the agent made it |
| "tests every control it can find, then reports what it measured" | `docs/product.md`: inputs are the product, its manual, an optional spec and CAD; outputs are findings with evidence, coverage and a reward | |
| "a centrifuge it has never seen" | `docs/journey.md` §10: no device names, layouts or fault types in prompts or harness code | The sim needs the device's own data files; that's the world, not the tester |
| "surveys … finds each control, and pins down exactly where it is" | Survey, Scan, Segment (OWLv2, SAM 2.1), Map run in System 1; the sim Rev A run also touched each part. On the real arm touches are off (`real_backend.py`, `touches = False`): it takes a last look before each step, triangulating the cap from two views | Don't say "touches" |
| "a person approves it before anything moves" | The Rev A run: the plan check refused the first plan, the model fixed it, and Karthik clicked Approve in the Console | |
| "Every press is force-limited, and fixed rules turn each measurement into a verdict" | Sim: 15 N hard cap, steps ask ≤ 14 N (D31). Real arm: 70 N on the force estimate (`real_arm.py`), plus stall detection, press depth and the servos' own torque limit. Verdicts are System 1's rules on readings; the display photo is read by a model in System 2 (`toolbelt._read_display`) | Don't say "15 N" over real footage, or "not from the model" |
| "When the display didn't match the manual, the run stopped, and the plan was amended" | The Rev A run: step s1 stopped on `unexpected_response` (display read `1000rpm  0:30`, manual says `1000 RPM 0:30`), then a plan amendment at level 0 | The model itself calls it a wording mismatch, not a fault |
| "When the lid handle needed a pinch grip the spec rules out, the robot refused to guess and reported it" | The Rev A run, step s7: skipped by System 1 before the arm moved, "handle_1 needs a pinch grip; the no-thumbs rule allows only the fingertip pad"; the model's summary has a no-thumbs finding | The rule reached the model only because it was typed into the Console's message box: the harness doesn't pass a project's rules yet (`service.py`, Joseph's code) |
| "RAAV traces a fault to its part in CAD, proposes a fix …" | D36 / PR #14: MC-6 tube stopped 8.15 mm high; the Opus analyst widened the bore and added a lead-in; on retest it seated within 0.97 mm (README) | Sim retest only; printed plastic not yet. The Rev B shown in the tour was drawn by the team |
| "test the new revision with the same plan" | The Rev B run (`agent-centrifuge-045535`) | In that run the lid was skipped for another reason ("no skill is known for this kind of part"). Show Rev B's lid opening from the verification check |
| "A fix only counts if the score goes up" | The fix loop keeps a patch only if the reward rises (`system-2/cad/README.md`) | |
| System 1 / System 2 lines | `docs/system-boundary.md` | "Limits" means limits enforced in code, not a proof |
| "a small set of tools, and none of them moves a motor or grades a step" | System 1's MCP server has 7 tools (`system_status`, `scene_get`, `evidence_get`, `routine_start/wait/resume/stop`), plus `appliance_readout` when appliances are registered; routines are only explore, run_plan and home (`mcp_server.py`). The model works through a 12-tool harness toolbelt on top | Don't give a number in the voice |
| "System 2 can be any of four models, and System 1 the simulator or a real arm, on any appliance" | `MODELS`: Haiku 5.5, Sonnet 5.5, GPT-5.4, Grok 4.7 on Snowflake Cortex (`model.py`); `Robot` has `SimBackend` and `RealBackend` over `SimArm` / `RealArm` | "Any appliance" in the sim: the real arm's centrifuge skills are hardware code (`centrifuge_skills.py`) |
| "twelve appliance designs in simulation and a real centrifuge, with its planner in the cloud" | 12 in `appliances/registry.json`; the real MC-6 on an Arduino R4 WiFi board (PRs #15, #17); System 2 on Vultr with System 1 tunnelling out (`deploy/vultr/README.md`, PR #18) | The globe's world pins are illustrative, not deployments |
| "each new task needs new demonstrations" | SmolVLA: 50 demonstrations per real task; GR00T N1: 30–300 per task in sim (sources 29–31) | Don't say VLAs can't generalize |
| "a new kind of control still needs a new skill in System 1" | Skills are code in System 1; the Rev B run skipped the lid because no skill fit it | |
| "from AI-written proofs to flight code" | The two claimed ETH refutations were checked in Lean (sources 1–2); CompCert qualified for the ATR 42/72 avionics computer (2026); seL4 on the HACMS Little Bird helicopter (sources 17–22) | The Lean card says "claimed": community confirmation pending |
| Dyson: "I made 5,127 prototypes of my vacuum before I got it right. There were 5,126 failures." | Dyson to Fast Company, May 2007 ("Failure Doesn't Suck"; source 33); the 15 years and the DC01 in 1993 (source 25) | Quote it word for word; the interview goes on "But I learned from each one" |
| "Biosafety labs and spacecraft tell the same story: in hardware, failures surface late" | Pirbright 2007 (most likely a damaged drain), JWST fasteners in a 2018 acoustic test (sources 24, 26) | Cards carry the specifics |

## Sources

Cited in the voiceover or on screen. Each was opened while writing this draft (new ones on Nov 8, for Drafts 4 to 8).

1. Impagliazzo, Paturi and Williams, "ETH refutation: examination and discussion", Oct 26, 2026. https://ethdiscussion.blog/2026/10/26/eth-refutation-examination-and-discussion/
2. Weisstein, "Exponential Time Hypothesis", MathWorld (lists the OpenAI and Claude preprints and their verification status). https://mathworld.wolfram.com/ExponentialTimeHypothesis.html
3. Impagliazzo and Paturi, "On the Complexity of k-SAT", J. Comput. Syst. Sci. 62 (2001). https://doi.org/10.1006/jcss.2000.1727
4. Google DeepMind, "Discovering new solutions to century-old problems in fluid dynamics", Sept 18, 2025. https://deepmind.google/blog/discovering-new-solutions-to-century-old-problems-in-fluid-dynamics/
5. Clay Mathematics Institute, "Navier–Stokes Equation" (Millennium Prize problem). https://www.claymath.org/millennium/navier-stokes-equation/
6. Takehi, Teoh, Zhang and Khattab, "Sparks of Weight-Space Programming", MIT CSAIL, Nov 2, 2026. https://rikiyat.github.io/blog/weight-space-programming
7. Baker, "1,500 scientists lift the lid on reproducibility", Nature 533, 452–454 (2016). https://www.nature.com/articles/533452a (summary opened at https://www.statnews.com/pharmalot/2016/06/01/reproducibility-experiments-scientists/) *(not in the cut since Draft 4)*
8. Burger et al., "A mobile robotic chemist", Nature 583, 237–241 (2020). https://doi.org/10.1038/s41586-020-2442-2 (details opened at https://www.liverpool.ac.uk/cooper-group/news/stories/title,1215738,en.php) *(not in the cut; kept for the Console's Background page)*
9. U.S. Access Board, Guide to the ADA Standards, Chapter 3: Operable Parts (§309.4). https://www.access-board.gov/ada/guides/chapter-3-operable-parts/
10. Kim et al., "OpenVLA: An Open-Source Vision-Language-Action Model", 2024 (970k robot demonstrations; image plus language instruction in, robot actions out; §5.2 adapts to new Franka setups with "10–150 demonstrations of a target task" and full fine-tuning). https://arxiv.org/abs/2406.09246 (full text opened at https://arxiv.org/html/2406.09246) *(not in the cut since Draft 6; background for the VLA line)*
11. Hales, guest post on Terence Tao's blog, on Lean and the Fermat's Last Theorem autoformalization (already on the Console's Background page; optional on-screen source for the Lean ✓). https://terrytao.wordpress.com/2026/10/09/what-mathematicians-should-know-about-the-lean-theorem-proverquestions-of-reliability-and-ai/
12. Google DeepMind, "AI achieves silver-medal standard solving International Mathematical Olympiad problems", July 25, 2024 (AlphaProof proves statements in Lean; 28 of 42 points; problems manually translated into formal language first). https://deepmind.google/blog/ai-solves-imo-problems-at-silver-medal-level/
13. Lean community, "Completion of the Liquid Tensor Experiment", July 14, 2022. https://leanprover-community.github.io/blog/posts/lte-final
14. Mathlib statistics (counts of definitions, theorems and contributors). https://mathlib.org/mathlib_stats.html
15. Gonthier, "A computer-checked proof of the Four Colour Theorem", Microsoft Research ("fully checked by the Coq v7.3.1 proof assistant"). https://www.cl.cam.ac.uk/~lp15/Pages/4colproof.pdf (2005 completion date from Microsoft Research, "Theorem Proof Gains Acclaim": https://www.microsoft.com/en-us/research/blog/theorem-proof-gains-acclaim/)
16. The Rocq Prover 9.0 release, March 12, 2025 ("the completion of the renaming from The Coq Proof Assistant to The Rocq Prover"). https://rocq-prover.org/releases/9.0
17. CompCert project page and news (core "proved correct in Coq"; March 2026 qualification for the ATR 42/72 Multi-Function Computer New Generation, "developed by AbsInt with guidance from Airbus"). https://compcert.org/ and https://compcert.org/compcert-C.html
18. Bedin França, Blazy, Favre-Felix, Leroy, Pantel and Souyris (Airbus Operations SAS, IRIT, IRISA, INRIA), "Formally verified optimizing compilation in ACG-based flight control software", ERTS 2012 (an evaluation for DO-178 level A flight control software). https://projects.laas.fr/IFSE/FAC/papers/2012/I-3.pdf
19. AbsInt, "User story: MTU Friedrichshafen" (CompCert qualified Nov 2017 to IEC 60880 cat. A and IEC 61508-3 SCL 3 for engine control software in emergency-generator diesel engines for civil nuclear plants); paper: Kästner et al., ERTS 2018. http://www.absint.com/mtu_fh.htm and https://www.absint.com/compcert/mtu_compcert_erts_2018.pdf
20. Trustworthy Systems, "The seL4 verification project" (functional correctness, Isabelle/HOL, completed 2009); paper: Klein et al., "seL4: Formal Verification of an OS Kernel", SOSP 2009. https://trustworthy.systems/projects/seL4-verification/ and https://trustworthy.systems/publications/papers/Klein_EHACDEEKNSTW_09.pdf
21. DARPA, "HACMS" case study (Boeing Unmanned Little Bird; red team couldn't break out of its partition, also in flight with two test pilots). https://www.darpa.mil/news/resources/case-studies/hacms
22. seL4 Foundation, "seL4 is used across a wide range of sectors" (seL4 in HACMS vehicles, including the Little Bird). https://sel4.systems/use.html
23. Newcombe, Rath, Zhang, Munteanu, Brooker and Deardeuff, "How Amazon Web Services Uses Formal Methods", CACM 58(4), April 2015 (TLA+ on 10 large systems; a 35-step DynamoDB bug). https://cacm.acm.org/magazines/2015/4/184701-how-amazon-web-services-uses-formal-methods/fulltext (abridged version opened at https://lamport.azurewebsites.net/tla/amazon-excerpt.html)
24. Health and Safety Executive, final report on the 2007 foot-and-mouth outbreak at Pirbright, Sept 7, 2007 (report: https://www.hse.gov.uk/news/archive/07aug/finalreport.pdf). Opened via VetClick, "Leaky drain led to foot and mouth outbreak", https://www.vetclick.com/news/leaky-drain-led-to-foot-and-mouth-outbreak-p379.php and CIDRAP, https://www.cidrap.umn.edu/british-blame-leaky-drain-foot-and-mouth-outbreak
25. Gizmodo, "Praising Failure: James Dyson Talks Vacuums, 5,127 Prototypes" ("the 15 years and 5,127 prototypes it took before the first model, DC01, would ultimately prove successful in 1993"). https://gizmodo.com/praising-failure-james-dyson-talks-vacuums-5-127-proto-5790556
26. Spaceflight Now, "Webb's launch delayed to 2021 at an extra cost of nearly $1 billion", June 27, 2018 (fasteners loose in an acoustic test; sunshield tears; the review board's 29-month delay). https://spaceflightnow.com/2018/06/27/webbs-launch-delayed-to-2021-at-a-cost-of-nearly-1-billion/
27. Brohan et al. (Google DeepMind), "RT-2: Vision-Language-Action Models Transfer Web Knowledge to Robotic Control", July 2023 (actions expressed "as text tokens"; co-fine-tuned on robot trajectories and web vision-language data). https://arxiv.org/abs/2307.15818 *(not in the cut since Draft 6)*
28. Black et al. (Physical Intelligence), "π0: A Vision-Language-Action Flow Model for General Robot Control", Oct 2024 ("built on top of a pre-trained vision-language model"; "its ability to acquire new skills via fine-tuning"). https://arxiv.org/abs/2410.24164 *(on screen only, as a third VLA example)*
29. Shukor, Aubakirova, Capuano et al. (Hugging Face), "SmolVLA: A Vision-Language-Action Model for Affordable and Efficient Robotics", June 2, 2025 ("Given multiple images and a language instruction describing the task, the model outputs a chunk of actions"; real-world datasets collected with the SO-100 and SO-101 arms, 50 demonstrations each). https://arxiv.org/abs/2506.01844 (full text opened at https://arxiv.org/html/2506.01844)
30. Bjorck et al. (NVIDIA), "GR00T N1: An Open Foundation Model for Generalist Humanoid Robots", March 18, 2025 (a "dual-system" VLA whose vision-language "System 2" and diffusion-transformer "System 1" are "tightly coupled and jointly trained end-to-end"; post-trained "on datasets corresponding to each single embodiment"; 30, 100 and 300 demonstrations per task in simulation). https://arxiv.org/abs/2503.14734 (full text opened at https://arxiv.org/html/2503.14734)
31. Hugging Face, "SmolVLA: Efficient Vision-Language-Action Model trained on Lerobot Community Data", June 3, 2025 (pre-training data "focused on the SO100 robotic arm"; evaluated on SO100 and SO101; deployable on "very affordable hardware (SO-100, SO-101, LeKiwi, etc.)"; fine-tune from `lerobot/smolvla_base` on your own dataset). https://huggingface.co/blog/smolvla
32. Lokshtanov, Marx and Saurabh, "Lower bounds based on the Exponential Time Hypothesis", Bulletin of the EATCS 105, 41–72 (2011) ("we survey algorithmic lower bound results that have been obtained… under certain assumptions on the running time of algorithms solving CNF-Sat, namely Exponential time hypothesis (ETH) and Strong Exponential time hypothesis (SETH)"). https://sites.cs.ucsb.edu/~daniello/papers/surveyETH.pdf (also https://arxiv.org/abs/1007.5450 per DBLP; not opened)

Repo sources for the walkthrough are named in the checks table: `docs/product.md`, `docs/system-boundary.md`, `docs/journey.md`, `docs/decisions.md`, `system-2/cad/README.md`, the Methodology page (`system-2/console/web/src/screens/Wiki.tsx`), `appliances/centrifuge/` (`gallery.md`, `source/faults.md`, `verify.yaml`, `build/verify.stock.json`) and the recorded run `system-2/runs/eval-1107-232000/`.

Background only, not cited in the voiceover: Long et al., "CheckManual", CVPR 2025, robots reading appliance manuals (https://arxiv.org/abs/2506.09343). It's why we say "test plans from the manual", not "the first robot to read a manual".
33. Fast Company, "Failure Doesn't Suck", interview with James Dyson, May 2007 ("I made 5,127 prototypes of my vacuum before I got it right. There were 5,126 failures. But I learned from each one."). https://www.fastcompany.com/59549/failure-doesnt-suck (text as reproduced by Leading Blog: https://www.leadershipnow.com/leadingblog/2007/04/fast_company_interview_with_si.html)
