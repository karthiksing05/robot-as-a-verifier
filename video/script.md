# Demo video script

**Draft 7, Nov 8.** About 579 spoken words, never faster than 2.55 words a second in any section, so it can be read at a natural pace. Numbers are written the way they're spoken, so the counts are honest. Shots, freeze frames and timing are in [storyboard.md](storyboard.md).

**Length: 3:55.** That's past the 3:30 we aimed for. The step-by-step centrifuge walkthrough needs about 74 s, the field examples now get a sentence each, and the new ending argues its case in full sentences. A cut to about 3:32, made by dropping four lines, is at the end of this file. Nothing shorter than that keeps the walkthrough's alternative paths.

**What changed from Draft 6:**
- The centrifuge section is now a walkthrough of one run, in order, from survey to the Rev B re-test. Each step says what System 1 does and how System 2 responds. It covers the happy path and the paths the system really handled in a recorded sim run: a failed scan, a safety stop, a plan amendment, a refused step, and a fault that only appears once another is fixed. The old "Fixing the design" section is folded into it.
- Section 3 names each example's field, in the voice and as headings, and says what happened.
- Section 4 opens with a plain thesis sentence.
- The ending argues that the run is valid and general, says where it scales next, and closes in full sentences. The slogan is gone.

The voiceover carries the argument. The pictures move it along and show the evidence. During the freeze frames on robot footage the voice stays on the story; the overlays document what the robot is doing, and the voice doesn't read them out. Tool names and dates the voice can't fit go on screen as small source lines.

**Footage rule:** for now, every robot shot is rendered in MuJoCo (sim). Nothing has run on the real arm yet. We will probably edit the cut and re-record those shots with real footage later. Until then, sim footage carries a `SIMULATION` tag in the corner the whole time it's on screen. Real footage that's sped up carries `REAL FOOTAGE · N×` with its true speed.

**Audio:** Karthik will record the voiceover himself as an mp3, and the music is coming from him too. Until they arrive, every audio item here and in the storyboard is a placeholder. The timings below assume a natural read at these word rates; **the final cut will be re-timed to his recording**, so treat every timestamp as a target, not a lock.

**Look:** rustic chalk for the problem and the stakes (sections 1 to 3), a designed transition at 0:58 on "So we built RAAV", then the Console's crisp, technical look for the product and the ending (sections 4 to 7).

| § | Section | Time | Seconds | Words | Words/s |
|---|---|---|---|---|---|
| 1 | Cold open | 0:00–0:06 | 6 | 0 | – |
| 2 | Verification works, in software | 0:06–0:25 | 19 | 47 | 2.47 |
| 3 | Where verification stops | 0:25–0:58 | 33 | 83 | 2.52 |
| 4 | Robot As A Verifier | 0:58–1:10 | 12 | 29 | 2.42 |
| 5 | Two systems | 1:10–2:03 | 53 | 135 | 2.55 |
| 6 | One centrifuge, step by step | 2:03–3:17 | 74 | 188 | 2.54 |
| 7 | What it shows, and where it scales | 3:17–3:55 | 38 | 97 | 2.55 |
| | **Total** | | 235 | **579** | 2.46 |

Word counts are spoken words. Hyphenated words count once per part ("foot-and-mouth" is three), numbers count as said ("twenty-nine-month" is three), and "GR00T N1" ("groot en-one") and "System 1" count as two. RAAV is named at 0:58, and the first robot footage is on screen at 1:01.

---

## 1. Cold open · 0:00–0:06

*No voiceover. A green chalkboard covered in buzzwords around one big question mark. Karthik walks in and erases it. The music starts on the last stroke. (Raw take: `video/real-world-assets/intro.MOV`, played at 1.75×; see storyboard shot 1.)*

---

## 2. Verification works, in software · 0:06–0:25

> Models now write proofs, and machines verify them. This October, Lean checked two claimed refutations of the Exponential Time Hypothesis. Verification already protects real systems: CompCert, a proven C compiler, is qualified for avionics, and seL4 kept a red team from taking over a helicopter in flight.

*The chalk arm draws as it talks: `ETH: 2^εn ?` with a Lean ✓, then two plaques, CompCert and seL4, each with where it's used. A ledger of the other tools and results runs along the bottom edge.*

*Say "seL4" as "ess-ee-ell-four".*

---

## 3. Where verification stops · 0:25–0:58

> But verification ends where software ends. No proof says whether a lid drawn in CAD will open.
>
> In biosafety and biosecurity, foot-and-mouth virus most likely escaped England's Pirbright labs through drains damaged over years.
>
> In aerospace engineering, an acoustic test shook fasteners loose from the James Webb telescope's sunshield, part of a twenty-nine-month delay.
>
> In mechanical and product design, Dyson built over five thousand prototypes before the first Dyson vacuum succeeded.
>
> And most products are still tested by hand.

*The arm draws the `software | hardware` line, then a CAD box of the centrifuge with a crossed-out pinch on its lid. Then one panel per field, each headed with its field's name, `BIOSAFETY & BIOSECURITY`, `AEROSPACE ENGINEERING`, `MECHANICAL & PRODUCT DESIGN`, with what happened and the source in small chalk under each. Last, a hand pressing buttons beside a clipboard.*

---

## 4. Robot As A Verifier · 0:58–1:10

> So we built RAAV, Robot As A Verifier. RAAV tests a physical prototype against its manual and specification with a low-cost robot arm, and reports what it measured.

*The turn happens on "So we built RAAV": the chalk arm becomes the rendered SO-101 and the board becomes the Console's grid. The thesis sentence types under the title. Then the first sim footage: the arm at the centrifuge, the manual beside it.*

---

## 5. Two systems · 1:10–2:03

> Vision-language-action models like SmolVLA and NVIDIA's GR00T N1 learn new tasks from fresh demonstrations, and the actor would judge itself.
>
> So RAAV splits the work. System 1 owns everything that must be exact, fast and safe: perception, inverse kinematics, control, force limits, and verdicts computed from sensor readings by fixed rules. System 2, a frontier model, owns everything that needs context and judgment: reading the manual and spec, choosing what to test and in what order, recovering when a step fails, and diagnosing the cause and proposing a CAD fix.
>
> Each does what it's good at. The model never sends a motor command and never grades its own work, so it can be swapped or upgraded, and System 1's guarantees hold whatever it says. A new device needs a manual, not new demonstrations.

*A brief motion graphic of one box, `perception + reasoning + control`, fed by demo reels, splits into `SYSTEM 1 · exact, fast, safe` and `SYSTEM 2 · context and judgment`. Each half fills with its jobs, with seven tool lines between them. One freeze frame shows a plan crossing the line. Then the model's name swaps between four frontier models while System 1's limits stay fixed.*

---

## 6. One centrifuge, step by step · 2:03–3:17

> Here's Rev A of a centrifuge we designed, and its manual.
>
> System 1 surveys the panel, scans it, segments each control, maps it, and touches it. A failed scan stops and reports, and System 2 reruns it.
>
> System 2 reads the manual and proposes a plan, and a person approves it.
>
> System 1 runs each step under a fifteen-newton cap, retries small misses within its autonomy setting, and judges each step by fixed rules. When the first flip hit sixteen newtons, it stopped first, and resuming took a person.
>
> When the display didn't match the manual, System 2 amended the plan, and code, not the model, rated the change.
>
> Then the lid. Its thin fin needs a pinch, which the spec forbids, so System 1 refuses and System 2 reports it, instead of guessing.
>
> System 2 traces it to the handle and drafts a hook lip; code checks it, and a person approves. That unmasks a second fault: the tube sits high in a tight well, so START shows TUBE. Rev B fixes both, the tests run again, and it only counts if the score goes up.

*Robot footage (MuJoCo sim, tagged) with a freeze frame at each step (storyboard FR1–FR9). The voice tells the story; the overlays carry the numbers.*

*What each line rests on (details in the checks table):*
- *Survey to touch, the failed scan and its rerun, the 16.4 N safety stop, and the amendment after the display mismatch all happened in a recorded sim run of Claude Sonnet 5.5 on Rev A (`system-2/runs/eval-1107-232000/002-claude-sonnet-5-5-centrifuge-A`). That run auto-approved its plan and its safety resume, since it was sim-only.*
- *The lid refusal, the tube sitting high with START showing `TUBE`, and Rev B's lid opening come from the device's verification checks in the sim (`appliances/centrifuge/build/verify.stock.json`).*
- *The hook lip in Rev B was drawn by the team. The analyst and the CAD checks are built, but proposing a patch from a run on this device hasn't been shown yet.*

---

## 7. What it shows, and where it scales · 3:17–3:55

> Nothing in this run was written for the centrifuge. Each piece is built to extend. System 1 sits behind seven tools, so another arm could take its place. Plans come from whatever manual a team already has, approval levels set how much a person reviews, the CAD checks take any STEP assembly, and better models can drop in as they arrive.
>
> Next, we will run it on the real arm, then on lab instruments and assistive devices.
>
> As AI begins to design hardware, we think every design should be measured like this before anyone relies on it.

*Console B-roll under the first paragraph, each named piece highlighted as it's said: the seven-tool bus, the manual feeding a plan, the approval-level ladder, a CAD check on a STEP assembly, the model picker. Then a quiet title card, **RAAV · ROBOT AS A VERIFIER**, with the team and MakeCU 2026 under it. No slogan.*

---

## Checks before recording

| Line | Holds because | Watch for |
|---|---|---|
| "Models now write proofs, and machines verify them" | Our framing, backed by the ETH line that follows and by AlphaProof (source 12) | Framing. Don't claim models write all proofs |
| "This October, Lean checked two claimed refutations of the Exponential Time Hypothesis" | Impagliazzo, Paturi and Williams' examination post (Oct 26); MathWorld's ETH entry lists both preprints (OpenAI and Anthropic) and says independent specialist confirmation hadn't been reported as of Nov 1 | Keep "claimed" until the community confirms. Re-check the day before recording. The Lean checks cover the formal statements; the step to the usual machine model is still informal |
| "CompCert, a proven C compiler, is qualified for avionics" | The core of CompCert is "proved correct in Coq". Qualified in 2026 for the ATR 42/72 Multi-Function Computer New Generation, "developed by AbsInt with guidance from Airbus". MTU qualified it in Nov 2017 for engine control software in emergency-generator diesel engines for civil nuclear plants. Airbus engineers evaluated it for DO-178 level A flight control software (ERTS 2012) (sources 17–19) | The 2012 Airbus paper is an evaluation, not production use. Say "avionics" for the ATR qualification |
| "seL4 kept a red team from taking over a helicopter in flight" | DARPA HACMS: on Boeing's Unmanned Little Bird, a red team given the camera partition couldn't expand access or disrupt operations, also in flight with two pilots at the controls; seL4 "prevented the cyber attack from compromising the flight mission" (sources 20–22) | DARPA's case study doesn't name seL4; the seL4 Foundation page does. The red team was handed one partition, so don't say "unhackable" |
| On-screen ledger (shot 3) | TLA+ at AWS (10 systems, a 35-step DynamoDB bug); Mathlib; the Liquid Tensor Experiment (July 14, 2022); AlphaProof (28 of 42 at IMO 2024, in Lean); the Four Colour Theorem in Coq (2005); Coq renamed Rocq (March 2025); seL4's proof in Isabelle/HOL (2009); DeepMind's fluid singularities (Sept 2025); weight-space programming (MIT CSAIL, Nov 2026) (sources 4–6, 12–16, 20, 23) | AlphaProof's IMO problems were "manually translated" into formal language first. No Mathlib count on screen. Never write that the fluid work solved Navier–Stokes. **Karthik to confirm the weight-space reading** |
| "But verification ends where software ends" | Our argument. seL4's proof itself assumes the hardware is correct (Klein et al., 2009) | Framing |
| "No proof says whether a lid drawn in CAD will open" | Our argument; the on-screen pinch cites ADA Standards §309.4 (one hand, no tight grasping, pinching or wrist twisting, 5 lbf at most) | §309.4 is a US rule for operable parts in buildings. Use it as the reason the rule exists, not as "the law requires" |
| "In biosafety and biosecurity, foot-and-mouth virus most likely escaped England's Pirbright labs through drains damaged over years" | HSE final report on the 2007 outbreak at Pirbright, Surrey: "evidence of long term damage and leakage, including cracked pipes, tree roots breaching pipework, and unsealed manholes"; a breached effluent pipe was the most likely source (source 24) | Keep "most likely": HSE couldn't say which of the two labs on the site was responsible. Contaminated soil reached the farms on contractors' vehicles. The year is on screen, not in the voice |
| "In aerospace engineering, an acoustic test shook fasteners loose from the James Webb telescope's sunshield, part of a twenty-nine-month delay" | Spaceflight Now on the 2018 Independent Review Board: "The fasteners came loose during an acoustic test"; the board's 29-month delay had "five factors: human errors, embedded problems, lack of experience in areas such as the sunshield…", costing about $1 billion (source 26) | "Part of" is deliberate: the fasteners were one of several problems behind the delay. Other reports call it a vibration test; this wording follows source 26 |
| "In mechanical and product design, Dyson built over five thousand prototypes before the first Dyson vacuum succeeded" | Dyson: "the 15 years and 5,127 prototypes it took before the first model, DC01, would ultimately prove successful in 1993" (source 25) | Earlier licensed designs (the G-Force, 1986) were sold first. "The first Dyson vacuum" means DC01, the first under the Dyson brand |
| "And most products are still tested by hand" | `docs/product.md`: products are still tested by people pressing buttons and taking notes | Our claim. Don't add a statistic |
| "RAAV tests a physical prototype against its manual and specification with a low-cost robot arm, and reports what it measured" | `docs/product.md`: the inputs are the product, its manual, an optional spec and CAD; the outputs are bug reports with evidence, a coverage report and a reward | The thesis sentence. "Specification" covers the optional spec (rules like "usable with no thumbs"). Today the arm is in MuJoCo |
| "Vision-language-action models like SmolVLA and NVIDIA's GR00T N1 learn new tasks from fresh demonstrations" | SmolVLA: real-world tasks on SO-100 and SO-101 used 50 demonstrations each; users fine-tune from `smolvla_base` on their own data. GR00T N1: post-trained "on datasets corresponding to each single embodiment", 30 to 300 demonstrations per task in simulation (sources 29–31) | Don't say they can't generalize. SmolVLA runs on our arm family, so expect "why not SmolVLA?" |
| "and the actor would judge itself" | Our argument, from `docs/product.md`: "Whatever proposes a plan or a design has no say in how it's judged" | GR00T N1 names its own modules "System 2" and "System 1", but they're "jointly trained end-to-end" (source 30); say so on screen |
| System 1 and System 2 lines (section 5) | `docs/system-boundary.md`: the split table, no motor tool, verdict rules in System 1, approval levels set by plain code, parameters clamped, holds safe if System 2 is unreachable; `docs/journey.md` §11–12 for the four models | OWLv2 and SAM are learned models that don't generate; the doc calls System 1 "almost no generative AI". "Guarantees" means limits enforced in code, not a formal proof. "A manual, not new demonstrations" holds while a device's controls fit the existing skills |
| "Here's Rev A of a centrifuge we designed, and its manual" | `appliances/centrifuge/` (`manual.md`, `gallery.md`): Rev A carries F2 and F3 | |
| "System 1 surveys the panel, scans it, segments each control, maps it, and touches it" | The pipeline on the Methodology page (`Wiki.tsx`): Survey, Scan, Segment (OWLv2 boxes, SAM outlines), Map, Touch; `docs/system-boundary.md` puts all of it in System 1 | |
| "A failed scan stops and reports, and System 2 reruns it" | The Sonnet 5.5 run on Rev A: the first `explore` ended in a `pipeline_error` stop, and the second completed (`events.jsonl`, seq 16 and 23) | That run had injected errors on. The rerun was started by the harness after the model looked at the stop; say "System 2", not "the model decided" |
| "System 2 reads the manual and proposes a plan, and a person approves it" | Same run: `read_manual` pages 1 and 2, `record_hypothesis` with 35 properties, `propose_plan`, `approval_needed` for the plan. Rule: "A person approves a plan before it runs" (`docs/system-boundary.md`) | In that run the approval was "auto (sim)": eval runs auto-approve, and only mocks and sim may. Show the Console's approval card from a live run, not that log line |
| "System 1 runs each step under a fifteen-newton cap, retries small misses within its autonomy setting, and judges each step by fixed rules" | 15 N hard cap (`docs/decisions.md` D34; Methodology page); retries per step: Tethered 0, Balanced 2, Autonomous 4 (`docs/system-boundary.md`); verdict rules in System 1 | Steps may ask for at most 14 N (D31) |
| "When the first flip hit sixteen newtons, it stopped first, and resuming took a person" | Same run, seq 49–57: `safety_abort`, "SafetyStop: tip force 16.4 N over hard cap 15.0 N"; "resuming after a safety stop needs a person" (level 3) | The resume was auto-approved in sim. The model then re-explored ("device may have moved") |
| "When the display didn't match the manual, System 2 amended the plan, and code, not the model, rated the change" | Same run, seq 85–94: an `unexpected_response` escalation on the power step, the display read `1000rpm  0:30` where the manual says `1000 RPM 0:30`; then `plan_amended` at level 1 (notify). Levels are assigned by plain code (`docs/system-boundary.md`) | The mismatch is real: the firmware's display format differs from the manual (`gallery.md`). The product doc counts a manual mismatch as a finding in itself |
| "Then the lid. Its thin fin needs a pinch, which the spec forbids, so System 1 refuses and System 2 reports it, instead of guessing" | F2. `verify.stock.json`: on Rev A, `hook_pull` on the lid handle is REFUSED, "handle_1 needs a pinch grip; the no-thumbs rule allows only the fingertip pad". Refused parts are reported, never escalated (`docs/system-boundary.md`); "refused and reported, never guessed at" (Methodology page) | **Neither recorded model run on the centrifuge tested the lid**: Haiku 5.5 skipped `handle_1` and missed F2, and Sonnet 5.5's plan had no lid step. Until a model run plans it, show the verification check (tagged), or prompt the run with the spec's no-thumbs rule |
| "System 2 traces it to the handle and drafts a hook lip; code checks it, and a person approves" | The analyst (`system-2/harness/.../analyst.py`) goes from a finding to a root cause and one CAD patch; the generic CAD checks include "a pull control catches the fingertip when it pulls, so nothing needs a pinch"; a person approves (`system-2/cad/README.md`) | **Not shown on this device yet**: the Methodology page lists "Proposing real CAD patches from a run" under "Not done yet". Rev B's hook lip was drawn by the team. On screen, label the morph as Rev B, not as the model's output |
| "That unmasks a second fault: the tube sits high in a tight well, so START shows TUBE" | F3, masked by F2. `verify.stock.json`, check F3s on M1 (lid fixed, well still tight): START is refused and the display shows `TUBE` | In the sim the tube is set in the well by the check itself. The stock gripper's `pick` misses the tube so far (F3p, and the Rev B workflow fails at `pick`). Don't show the arm loading the tube |
| "Rev B fixes both, the tests run again, and it only counts if the score goes up" | `verify.stock.json`: on Rev B the lid's `hook_pull` passes ("handle_1 swung to 100 deg") and well A seats the tube; the fix loop keeps a patch only if the reward rises (`README.md`, `system-2/cad/README.md`) | Rev B hasn't been printed. Rev B's full manual workflow doesn't pass yet in the sim, because of the tube pick. Show the lid re-test, not a full green run |
| "Nothing in this run was written for the centrifuge" | `docs/journey.md` §10: no device names, layouts or fault types in prompts or harness code, a test fails on a match, and devices differ only by data | The sim needs the device's own data files (`device.yaml`) to simulate it; that's the world, not the tester |
| "System 1 sits behind seven tools, so another arm could take its place" | `docs/system-boundary.md`: System 2 reaches System 1 only through seven tools; `rig.Rig` makes sim and real interchangeable (`docs/frontier-integration.md`) | "Could": no second arm has been run |
| "Plans come from whatever manual a team already has" | `docs/product.md`: the manual is the expected input, and the planner scaffolds a test plan from it | |
| "approval levels set how much a person reviews" | `docs/system-boundary.md`: levels 0 to 3 and the Tethered / Balanced / Autonomous presets | |
| "the CAD checks take any STEP assembly" | `system-2/cad/README.md`: "Generic robot-centred checks, on any STEP assembly of named parts"; `LocalCadBackend` works offline on any product as a STEP assembly | The parts need names. The Onshape backend hasn't run on the real document yet |
| "and better models can drop in as they arrive" | The model is a config value; four models ran through the same harness (`docs/journey.md` §11) | |
| "Next, we will run it on the real arm, then on lab instruments and assistive devices" | `docs/journey.md` "Next": the real arm; `docs/product.md` pitch framings | Stated as next steps, not done |
| "As AI begins to design hardware, we think every design should be measured like this before anyone relies on it" | Our view, stated as one | |
| Real arm | Not run on the real arm yet. Every robot shot is MuJoCo for now | Until it is, every robot clip is sim and tagged so |


## Sources

Cited in the voiceover or on screen. Each was opened while writing this draft (new ones on Nov 8, for Drafts 4 to 7).

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

Repo sources for the walkthrough are named in the checks table: `docs/product.md`, `docs/system-boundary.md`, `docs/journey.md`, `docs/decisions.md`, `system-2/cad/README.md`, the Methodology page (`system-2/console/web/src/screens/Wiki.tsx`), `appliances/centrifuge/` (`gallery.md`, `source/faults.md`, `verify.yaml`, `build/verify.stock.json`) and the recorded run `system-2/runs/eval-1107-232000/`.

Background only, not cited in the voiceover: Long et al., "CheckManual", CVPR 2025, robots reading appliance manuals (https://arxiv.org/abs/2506.09343). It's why we say "test plans from the manual", not "the first robot to read a manual".

## Questions for Karthik

1. **Length:** 3:55 as written. Keep it, or take the 3:30 cut below?
2. **The lid in a model run:** neither recorded model run planned a lid test, so the lid beat currently rests on the device's verification check. Do you want a fresh run (with the spec's no-thumbs rule in the request) before filming?
3. **The CAD step:** the analyst and CAD checks are built, but a patch proposed from a run on the centrifuge hasn't been shown. Keep "System 2 traces it to the handle and drafts a hook lip" with Rev B labelled as the team's drawing, or soften it to "is built to draft a fix"?
4. **"Weight space programming":** I took it to mean the MIT CSAIL "Sparks of Weight-Space Programming" post (Nov 2, 2026). It's an on-screen ledger line only. Is that what you meant?
5. **ETH:** the refutation claims are still under examination. Keep it with "claimed", or swap in AlphaProof's IMO silver, which is settled?
6. **SmolVLA:** naming it invites "why not just fine-tune SmolVLA?". The next lines answer it. Happy with that, or on screen only?
7. **Your read:** every shot gets re-cut to your mp3. If a line feels long to say, tell us which and we'll cut it rather than speed you up.

## The 3:30 cut

Drop these four lines and the video runs about 3:32, with every section still at or under 2.55 words a second. The walkthrough keeps its alternative paths.

| Drop | From | Saves |
|---|---|---|
| "Vision-language-action models like SmolVLA and NVIDIA's GR00T N1 learn new tasks from fresh demonstrations, and the actor would judge itself." | § 5 | 9 s |
| "When the display didn't match the manual, System 2 amended the plan, and code, not the model, rated the change." (the safety stop already shows a person being pulled in) | § 6 | 8 s |
| "and it only counts if the score goes up" | § 6 | 4 s |
| "Models now write proofs, and machines verify them." | § 2 | 3 s |

For 3:00, also drop the Dyson line (7 s), "A failed scan stops and reports, and System 2 reruns it." (4 s), the safety-stop sentence (6 s) and "Each does what it's good at." (2 s), and tighten the ending's list to three pieces (about 6 s). That keeps the problem, the thesis, the split and the lid story, but loses most of what makes the walkthrough show the system's range.
