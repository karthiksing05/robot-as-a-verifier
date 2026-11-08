# Demo video script

**Draft 10, Nov 8, for a re-record.** Karthik records this as a new voiceover, and the video is rebuilt to his recording. About 360 spoken words in roughly 2:45, never faster than about 2.5 words a second.

**What changed from Draft 9:**
- **The take is split in two.** It opens on the erasing and stops as the chalk touches the board; the drawn board opens out of that point. It comes back at the very end: the camera pulls out while he writes RAAV over the closing line, then he walks off and it fades to black.
- **Brought up to date with the software as it is now** (Joseph's real-arm work and the System 1 / System 2 interface):
  - On the real arm, System 1 doesn't touch parts to place them; it takes a last look before each step. The script says "pins down".
  - Real force limits aren't the sim's 15 N, so the script says "force-limited", not "capped".
  - A model reads the display photo in System 2, so the script no longer says every verdict comes "not from the model". It says fixed rules turn measurements into verdicts.
  - The CAD fix has now happened end to end in the sim (MC-6 tube seat, D36). It's said as done, not "built to".
  - The interface between the systems is a small set of tools with no motor command. Either side can be swapped: four models for System 2, the simulator or the real SO-101 for System 1, any appliance.
- **A pan-out before the close:** twelve appliance designs, the real centrifuge, the planner in the cloud, over a spinning globe.
- **Bayan's logo** (our handwriting, bolded) is the RAAV that writes itself on the drawn board.

**Footage rule:** every robot shot is MuJoCo (sim) and carries a `SIMULATION` tag until Joseph's real-arm footage arrives ([HANDOFF_JOSEPH.md](HANDOFF_JOSEPH.md)). The demo uses the Rev A run recorded from the Console on Nov 8 (`agent-centrifuge-043919`, Claude Sonnet 5.5) and the Rev B run (`agent-centrifuge-045535`).

| § | Section | Time | Words |
|---|---|---|---|
| 1 | Cold open | 0:00–0:11 | 0 |
| 2 | What RAAV is | 0:11–0:25 | 40 |
| 3 | The demo | 0:26–1:22 | 138 |
| 4 | Two systems | 1:22–2:05 | 106 |
| 5 | Why it matters, and the close | 2:06–2:44 | 77 |
| | **Total** | 2:44 | **361** |

Timings assume a natural read; the cut follows the recording.

---

## 1. Cold open · 0:00–0:11

*No voiceover. The take (`intro.MOV`), cropped on the question mark: Karthik erases the buzzwords (1.75×), steps up and puts the chalk to the board. It freezes there, and the camera pushes in on the chalk's tip. The drawn chalkboard opens out of that point, and RAAV (Bayan's logo, in our handwriting) writes itself on where he was about to write it. The music starts with the first letter.*

---

## 2. What RAAV is · 0:11–0:25

> This is RAAV, Robot As A Verifier. Give it a prototype and its manual, and a low-cost robot arm tests every control it can find, then reports what it measured. Here it is on a centrifuge it has never seen.

*The chalkboard: RAAV rises to the top. A prototype and a manual feed an arm, which feeds a report. The chalk SO-101 points at each as it's named. On "a centrifuge it has never seen", the board turns into the Console's look and the first sim footage.*

---

## 3. The demo · 0:26–1:22

> First it surveys the panel with one wrist camera, finds each control, and pins down exactly where it is. A model reads the manual and drafts a test plan, and a person approves it before anything moves.
>
> Then the arm runs the plan. Every press is force-limited, and fixed rules turn each measurement into a verdict. When the display didn't match the manual, the run stopped, and the plan was amended. When the lid handle needed a pinch grip the spec rules out, the robot refused to guess and reported it.
>
> From there, RAAV traces a fault to its part in CAD, proposes a fix for a person to approve, and tests the new revision with the same plan. A fix only counts if the score goes up.

*A tour of the Console, zooming where the cursor works: the run's stages, the plan and its approval, the test, the stopped step, the skipped lid, then Design Analysis and the Rev B run. On "proposes a fix", a small card adds what the voice doesn't: `MC-6 tube 8.15 mm high → Opus widened the bore → reseated within 0.97 mm (sim)`.*

---

## 4. Two systems · 1:22–2:05

> Under the hood, RAAV is two systems. System 1 is the robot: perception, inverse kinematics, control, force limits and the verdict rules. System 2 is a frontier model that reads the manual, plans, recovers from failed steps and diagnoses causes.
>
> Between them is a small set of tools, and none of them moves a motor or grades a step. So either side can be swapped: System 2 can be any of four models, and System 1 the simulator or a real arm, on any appliance.
>
> Vision-language-action models fold all of this into one network, so each new task needs new demonstrations. Our split needs a manual instead. Its limit: a new kind of control still needs a new skill in System 1.

*Two full-height panels already filled with the Rev A run's own data; each part lights up as it's named. The model's `move_joint` and `grade_own_step` bounce off the tool lane; a 40 N press goes through and stops at the cap. On "swapped", the model name flicks through four models, and System 1's header flips between `MuJoCo` and `SO-101 · real` while appliance names cycle. The VLA aside is a card over the dimmed panels.*

---

## 5. Why it matters, and the close · 2:06–2:44

> Why does this matter? Software already has verification, from AI-written proofs to flight code. Hardware has nothing like it, so failures surface late, in biosafety labs, spacecraft and prototypes.
>
> Today, RAAV runs on twelve appliance designs in simulation and a real centrifuge, with its planner in the cloud. Any lab with a low-cost arm could do the same.
>
> As AI starts designing hardware, every design should be measured like this before anyone relies on it.

*One shared screen for the examples, about ten seconds: the Console in a window on the right, six case cards filling in on the left. On "Today", the camera pulls back: the window shrinks away and a spinning globe fills the frame. The twelve appliance names ring it, a pin lands on New York for the real centrifuge, a small cloud marked System 2 orbits it, and on "any lab" pins light up around the world. On the last sentence it cuts back to the take, frozen on the chalk's tip, and pulls out while Karthik writes RAAV. He walks off, and it fades to black.*

---

## Checks before recording

| Line | Holds because | Watch for |
|---|---|---|
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
| "failures surface late, in biosafety labs, spacecraft and prototypes" | Pirbright 2007 (most likely a damaged drain), JWST fasteners in a 2018 acoustic test, Dyson's 5,127 prototypes (sources 24–26) | Chips carry the specifics |

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
