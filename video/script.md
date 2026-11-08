# Demo video script

**Draft 5, Nov 8.** Target 2:45. About 387 spoken words, never faster than 2.55 words a second in any section, so it can be read at a natural pace. Numbers are written the way they're spoken, so the counts are honest. Shots, freeze frames and timing are in [storyboard.md](storyboard.md).

**What changed from Draft 4:** the opening gets to the point. The problem is now one 17 s section, RAAV is named at 0:23, and the first robot footage is on screen at 0:26 (it was 1:34). The detail that used to open the video (the verification tools and where they're used, the other formal results, the field examples) now sits in a "why this matters" coda before the close. The OpenVLA beat is now about vision-language-action models in general.

The voiceover carries the argument. The pictures move it along and show the evidence. During the freeze frames on robot footage the voice stays on the story; the overlays document what the robot is doing, and the voice doesn't read them out. Tool names and dates the voice can't fit go on screen as small source lines.

**Footage rule:** for now, every robot shot is rendered in MuJoCo (sim). Nothing has run on the real arm yet. We will probably edit the cut and re-record those shots with real footage later. Until then, sim footage carries a `SIMULATION` tag in the corner the whole time it's on screen. Real footage that's sped up carries `REAL FOOTAGE · N×` with its true speed.

**Audio:** Karthik will record the voiceover himself as an mp3, and the music is coming from him too. Until they arrive, every audio item here and in the storyboard is a placeholder. The timings below assume a natural read at these word rates; **the final cut will be re-timed to his recording**, so treat every timestamp as a target, not a lock.

**Look:** rustic chalk for the problem (sections 1 and 2), a designed transition at 0:23 on "So we built RAAV", then the Console's crisp, technical look for the product (sections 3 to 7). Chalk comes back once for the "why this matters" coda (section 8), as a bookend, before the technical close.

| § | Section | Time | Seconds | Words | Words/s |
|---|---|---|---|---|---|
| 1 | Cold open | 0:00–0:06 | 6 | 0 | – |
| 2 | The problem | 0:06–0:23 | 17 | 43 | 2.53 |
| 3 | Robot As A Verifier | 0:23–0:38 | 15 | 38 | 2.53 |
| 4 | Why not one VLA | 0:38–1:00 | 22 | 53 | 2.41 |
| 5 | Two systems | 1:00–1:22 | 22 | 54 | 2.45 |
| 6 | One centrifuge, end to end | 1:22–1:46 | 24 | 50 | 2.08 |
| 7 | Fixing the design | 1:46–1:59 | 13 | 33 | 2.54 |
| 8 | Why this matters | 1:59–2:25 | 26 | 66 | 2.54 |
| 9 | Where it goes, and the close | 2:25–2:45 | 20 | 50 | 2.50 |
| | **Total** | | 165 | **387** | 2.35 |

Section 4 says "RT-2" and "pi zero", which take longer to say than their word count suggests; it has a little slack for that. The centrifuge section got 3 extra seconds so the freeze frames can breathe.

---

## 1. Cold open · 0:00–0:06

*No voiceover. A green chalkboard covered in buzzwords around one big question mark. Karthik walks in and erases it. The music starts on the last stroke. (Raw take: `video/real-world-assets/intro.MOV`, played at 1.75×; see storyboard shot 1.)*

---

## 2. The problem · 0:06–0:23

> Models now write proofs, and machines verify them. This October, Lean checked two claimed refutations of the Exponential Time Hypothesis. But verification ends where software ends. No proof says whether a lid drawn in CAD will open. Prototypes are still tested by hand.

*The chalk arm draws as it talks: `ETH: 2^εn ?` with a Lean ✓. Then a line down the board, `software | hardware`; the arrow from the ✓ stops at it. On the right, a CAD box of the centrifuge; a pinch on its lid is drawn and crossed out. Last, a hand pressing buttons beside a clipboard.*

---

## 3. Robot As A Verifier · 0:23–0:38

> So we built RAAV, Robot As A Verifier. Give it a prototype and its manual. A low-cost arm presses, turns and lifts each control and reports what it measured. A model plans the tests, but never grades them.

*The turn happens on "So we built RAAV": the chalk arm becomes the rendered SO-101 and the board becomes the Console's grid. Then the first sim footage: the arm at the centrifuge, the manual beside it, a press with its force trace, and the model's plan streaming in.*

---

## 4. Why not one VLA · 0:38–1:00

> Why not one vision-language-action model? RT-2, OpenVLA and pi zero put perception, reasoning and control in one model. OpenVLA learned from nearly a million demonstrations, and a new robot setup still needed fresh demonstrations and fine-tuning. They take a short instruction, not a manual. The model that acts would also be the judge.

*A motion graphic in the technical style: one box, `perception + reasoning + control`, fed by a tall stack of demo reels. A new device arrives and the box asks for more reels and a fine-tune. A thick manual bounces off its narrow `instruction` input. An arrow from the box's output loops back into it as `judge`.*

---

## 5. Two systems · 1:00–1:22

> RAAV splits the work. System 1 is the robot: perception, inverse kinematics and classical control, safety, and the verdict rules. It never calls a language model. System 2 is a frontier model that reads the manual with no new training, then plans, recovers and diagnoses. Seven tools join them, and none moves a joint.

*The box from section 4 splits in two: `SYSTEM 1 · the robot` and `SYSTEM 2 · the model`, with seven tool lines between them, and one freeze frame shows a plan crossing the line (storyboard F0).*

---

## 6. One centrifuge, end to end · 1:22–1:46

> Here's a centrifuge we designed, and its manual. The model reads the manual and plans the tests. The arm's one nineteen-dollar wrist camera finds each control, and force readings decide each verdict.
>
> Then it finds the fault we planted: the lid handle is a thin fin, with nothing to hook.

*Robot footage (MuJoCo sim, tagged) with five freeze frames (storyboard F1–F5). The voice doesn't narrate the overlays.*

---

## 7. Fixing the design · 1:46–1:59

> The model traces the failure to the handle and proposes a CAD change: a hook lip. A person approves, and the same tests run again. It only counts if the score goes up.

*The handle morphs from Rev A's fin to Rev B's lip. A score ticks up.*

---

## 8. Why this matters · 1:59–2:25

> Verification already protects real systems. CompCert, a proven C compiler, is qualified for avionics. seL4 kept a red team from taking over a helicopter in flight. Amazon found design bugs with TLA+. Physical behavior has nothing like it. In biosafety, a lab's cracked drain likely let a virus out. In aerospace, Webb's fasteners shook loose in testing. In mechanical design, Dyson built over five thousand prototypes.

*Chalk returns for the coda, as a bookend to the opening: plaques for CompCert, seL4 and TLA+ with where each is used, a ledger of the other tools and results (Lean, Mathlib, the Liquid Tensor Experiment, AlphaProof, Rocq, Isabelle, the fluid-dynamics singularities, weight-space programming), then the `software | hardware` line, and one vignette per field headed with its name: `BIOSAFETY`, `AEROSPACE`, `MECHANICAL DESIGN`. Sources on screen.*

*Say "seL4" as "ess-ee-ell-four" and "TLA+" as "T-L-A plus".*

---

## 9. Where it goes, and the close · 2:25–2:45

> Every verdict traces back to a force reading and a frame. Lab instruments, appliances, assistive devices. Twelve appliances so far, all in simulation, and four frontier models compared.
>
> As AI learns to design, the physical world has to answer back.
>
> Proofs got Lean. Software got CompCert. Hardware gets a verifier.

*Console B-roll, then the title card: **RAAV · ROBOT AS A VERIFIER**. Below it, what we packaged, one line at a time: one-camera exploration · sensor-decided verdicts · a frontier model that can't move a joint · seven tools over MCP · CAD repair loop · tested under injected errors. Then the team and MakeCU 2026.*

---

## Checks before recording

| Line | Holds because | Watch for |
|---|---|---|
| "Models now write proofs, and machines verify them" | Our framing, backed by the ETH line that follows and by AlphaProof (source 12) | Framing. Don't claim models write all proofs |
| "This October, Lean checked two claimed refutations of the Exponential Time Hypothesis" | Impagliazzo, Paturi and Williams' examination post (Oct 26); MathWorld's ETH entry lists both preprints (OpenAI and Anthropic) and says independent specialist confirmation hadn't been reported as of Nov 1 | Keep "claimed" until the community confirms. Re-check the day before recording. The Lean checks cover the formal statements; the step to the usual machine model is still informal. The ETH gloss ("a bound on solving hard problems", Impagliazzo and Paturi 2001) moved to the on-screen line |
| "But verification ends where software ends" | Our argument. seL4's proof itself assumes the hardware is correct (Klein et al., 2009) | Framing. Don't put a source on screen for it |
| "No proof says whether a lid drawn in CAD will open" | Our argument; the on-screen pinch cites ADA Standards §309.4 (one hand, no tight grasping, pinching or wrist twisting, 5 lbf at most) | §309.4 is a US rule for operable parts in buildings. On screen, use it as the reason the rule exists, not as "the law requires" for appliances. The repo's own spec rule is "usable with no thumbs" |
| "Prototypes are still tested by hand" | `docs/product.md`: products are still tested by people pressing buttons and taking notes | Our claim. Don't add a statistic |
| "Give it a prototype and its manual. A low-cost arm presses, turns and lifts each control and reports what it measured" | `docs/product.md`; the SO-101 arm (`docs/journey.md`); the centrifuge run reads `manual.md` and logs force traces and frames | In today's runs the arm is in MuJoCo; the pictures are tagged |
| "A model plans the tests, but never grades them" | `docs/product.md`: "the model thinks, code moves, sensors decide"; verdict rules live in System 1 (`docs/system-boundary.md`) | The model diagnoses failures in section 7; that isn't grading |
| "RT-2, OpenVLA and pi zero put perception, reasoning and control in one model" | RT-2 is a VLA that expresses "actions as text tokens" and is co-fine-tuned on robot trajectories and web vision-language data; OpenVLA takes an image and a language instruction and predicts robot actions; π0 is "built on top of a pre-trained vision-language model" (sources 10, 27, 28) | "One model" is a fair summary of all three. π0 adds a separate action expert inside the same model; don't say "one transformer layer stack" |
| "OpenVLA learned from nearly a million demonstrations" | OpenVLA abstract: "trained on a diverse collection of 970k real-world robot demonstrations" (source 10) | Keep "nearly a million" |
| "a new robot setup still needed fresh demonstrations and fine-tuning" | OpenVLA §5.2: adapting to new Franka setups used "small datasets with 10–150 demonstrations of a target task" and "full fine-tuning of all model parameters"; the abstract says efficient fine-tuning "for new tasks" is "a key component for adoption". π0's abstract cites "its ability to acquire new skills via fine-tuning" (sources 10, 28) | Don't say VLAs can't generalize at all; they're built to. The claim is that new setups and skills are learned from new demonstrations, which is what the papers report. One of the two Franka setups (DROID) was in OpenVLA's pre-training mix, so don't call both "unseen" |
| "They take a short instruction, not a manual" | OpenVLA: "Given an image observation and a language instruction, the model predicts 7-dimensional robot control actions". RT-2 and π0 are likewise prompted with a task instruction (sources 10, 27, 28) | Our reading of their published interfaces. Don't claim a VLA can't ever be given a longer prompt |
| "The model that acts would also be the judge" | Our argument, from `docs/product.md`: "Whatever proposes a plan or a design has no say in how it's judged" | Framing, not a cited fact. It applies to using one model as its own verifier |
| "System 1 is the robot: perception, inverse kinematics and classical control, safety, and the verdict rules. It never calls a language model" | `docs/system-boundary.md`, `system-1/README.md`: IK and fixed policies; perception is OWLv2 and SAM | **Don't say we use MPC or LQR**: they're part of the team's general experience, not this stack |
| "System 2 is a frontier model that reads the manual with no new training, then plans, recovers and diagnoses" | `docs/frontier-integration.md`; the model gets `manual.md` in its prompt, with no fine-tuning | The model loop is being built; show recorded runs, not a claim that every run is model-driven |
| "Seven tools join them, and none moves a joint" | `docs/system-boundary.md`: seven tools, "no motor, joint or jog tool, on purpose"; System 1 clamps every parameter (`docs/journey.md` §7) | "Each side can be built and tested on its own" moved to an on-screen badge (shot 12): separate installs and lockfiles; boundary tests in `system-2/tests/test_repo.py` and `system-1/tests/test_boundary.py` |
| "The arm's one nineteen-dollar wrist camera" | `docs/journey.md` §3 | |
| "force readings decide each verdict" | `docs/product.md`: "the model thinks, code moves, sensors decide" | |
| "the fault we planted: … a thin fin, with nothing to hook" | Centrifuge F2, Rev A (`appliances/centrifuge/gallery.md`) | Show a sim run where the verdict is right |
| "proposes a CAD change: a hook lip" | Rev A and Rev B meshes exist in `appliances/centrifuge/build/` | Don't say it happened live, and don't say "printed": Rev B hasn't been printed |
| "the same tests run again… It only counts if the score goes up" | The fix loop's rule (`README.md`) | Show sim numbers only, tagged |
| "CompCert, a proven C compiler, is qualified for avionics" | The core of CompCert is "proved correct in Coq". Qualified in 2026 for the ATR 42/72 Multi-Function Computer New Generation, "developed by AbsInt with guidance from Airbus". MTU Friedrichshafen qualified it in Nov 2017 (IEC 60880 cat. A, IEC 61508-3 SCL 3) for engine control software in emergency-generator diesel engines for civil nuclear plants. Airbus engineers evaluated it for DO-178 level A flight control software (ERTS 2012) (sources 17–19) | The 2012 Airbus paper is an evaluation, not production use. Say "avionics" for the ATR qualification, not "Airbus flight controls". The proof covers the compiler's core, not every part |
| "seL4 kept a red team from taking over a helicopter in flight" | DARPA HACMS: on Boeing's Unmanned Little Bird, a red team given the camera partition couldn't expand access or disrupt operations, also with the helicopter in flight and two pilots at the controls; seL4 "prevented the cyber attack from compromising the flight mission" (sources 20–22) | DARPA's own case study says "formal methods" and doesn't name seL4; the seL4 Foundation page names it. The red team was handed one partition, so don't say "unhackable" |
| "Amazon found design bugs with TLA+" | Newcombe et al., CACM 2015: TLA+ on 10 large systems; on DynamoDB it found a data-loss bug whose shortest trace was 35 steps (source 23) | Say "design bugs found", not "AWS is formally verified" |
| "Physical behavior has nothing like it" | Our argument, the same as "verification ends where software ends" | Framing |
| "In biosafety, a lab's cracked drain likely let a virus out" | HSE final report on the 2007 foot-and-mouth outbreak at Pirbright, UK: "cracked pipes, tree roots breaching pipework, and unsealed manholes"; a breached effluent pipe was the most likely source (source 24) | Keep "likely": HSE named a most likely source and couldn't say which of the two labs was responsible |
| "In aerospace, Webb's fasteners shook loose in testing" | Spaceflight Now on the 2018 Independent Review Board: "The fasteners came loose during an acoustic test"; tears in the sunshield after a deployment test; a 29-month delay costing about $1 billion (source 26) | Reports differ on acoustic vs vibration test; say "testing". The board blamed mainly human error |
| "In mechanical design, Dyson built over five thousand prototypes" | Dyson: 5,127 prototypes and 15 years before DC01 succeeded in 1993 (source 25) | One example of iteration, not a claim about all mechanical design |
| On-screen ledger (shot 18): Lean · Mathlib, Liquid Tensor Experiment, AlphaProof, Rocq, Isabelle | Mathlib's stats page; LTE completed July 14, 2022, a challenge Scholze posed in Dec 2020; AlphaProof proves statements in Lean, 28 of 42 at IMO 2024, silver level; the Four Colour Theorem "fully checked by the Coq v7.3.1 proof assistant", 2005; Coq renamed Rocq with 9.0, March 2025; seL4's proof in Isabelle/HOL, 2009 (sources 12–16, 20) | AlphaProof's IMO problems were "manually translated" into formal language first; its model was fine-tuned to autoformalize other problems for training. Don't claim it autoformalized the IMO problems. No Mathlib count on screen |
| On-screen ledger (shot 18): fluid-dynamics singularities, weight-space programming | Google DeepMind with Brown, NYU and Stanford, Sept 2025: new unstable singularities in Boussinesq, IPM and related equations, close to Navier–Stokes (a Clay Millennium problem). "Sparks of Weight-Space Programming", MIT CSAIL, Nov 2, 2026 (sources 4–6) | Never write that they solved Navier–Stokes. The weight-space post is "very early results", not peer reviewed. **Karthik to confirm the weight-space reading** |
| "Twelve appliances so far, all in simulation, and four frontier models compared" | `docs/devices.md` (12 in `appliances/`); `docs/journey.md` §11–12 (Haiku 5.5, Sonnet 5.5, GPT-5.4, Grok 4.7) | Round 1 didn't separate the models. Don't imply a ranking |
| "Proofs got Lean. Software got CompCert. Hardware gets a verifier." | Lean, CompCert: sources 11–14, 17–19 | A slogan. CompCert stands for verified software in general; seL4 sits beside it on screen |
| Real arm | Not run on the real arm yet. Every robot shot is MuJoCo for now | Until it is, every robot clip is sim and tagged so. Expect to re-record with real footage later |

## Sources

Cited in the voiceover or on screen. Each was opened while writing this draft (new ones on Nov 8, for Drafts 4 and 5).

1. Impagliazzo, Paturi and Williams, "ETH refutation: examination and discussion", Oct 26, 2026. https://ethdiscussion.blog/2026/10/26/eth-refutation-examination-and-discussion/
2. Weisstein, "Exponential Time Hypothesis", MathWorld (lists the OpenAI and Claude preprints and their verification status). https://mathworld.wolfram.com/ExponentialTimeHypothesis.html
3. Impagliazzo and Paturi, "On the Complexity of k-SAT", J. Comput. Syst. Sci. 62 (2001). https://doi.org/10.1006/jcss.2000.1727
4. Google DeepMind, "Discovering new solutions to century-old problems in fluid dynamics", Sept 18, 2025. https://deepmind.google/blog/discovering-new-solutions-to-century-old-problems-in-fluid-dynamics/
5. Clay Mathematics Institute, "Navier–Stokes Equation" (Millennium Prize problem). https://www.claymath.org/millennium/navier-stokes-equation/
6. Takehi, Teoh, Zhang and Khattab, "Sparks of Weight-Space Programming", MIT CSAIL, Nov 2, 2026. https://rikiyat.github.io/blog/weight-space-programming
7. Baker, "1,500 scientists lift the lid on reproducibility", Nature 533, 452–454 (2016). https://www.nature.com/articles/533452a (summary opened at https://www.statnews.com/pharmalot/2016/06/01/reproducibility-experiments-scientists/) *(not in the cut since Draft 4)*
8. Burger et al., "A mobile robotic chemist", Nature 583, 237–241 (2020). https://doi.org/10.1038/s41586-020-2442-2 (details opened at https://www.liverpool.ac.uk/cooper-group/news/stories/title,1215738,en.php) *(not in the cut; kept for the Console's Background page)*
9. U.S. Access Board, Guide to the ADA Standards, Chapter 3: Operable Parts (§309.4). https://www.access-board.gov/ada/guides/chapter-3-operable-parts/
10. Kim et al., "OpenVLA: An Open-Source Vision-Language-Action Model", 2024 (970k robot demonstrations; image plus language instruction in, robot actions out; §5.2 adapts to new Franka setups with "10–150 demonstrations of a target task" and full fine-tuning). https://arxiv.org/abs/2406.09246 (full text opened at https://arxiv.org/html/2406.09246)
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
27. Brohan et al. (Google DeepMind), "RT-2: Vision-Language-Action Models Transfer Web Knowledge to Robotic Control", July 2023 (actions expressed "as text tokens"; co-fine-tuned on robot trajectories and web vision-language data). https://arxiv.org/abs/2307.15818
28. Black et al. (Physical Intelligence), "π0: A Vision-Language-Action Flow Model for General Robot Control", Oct 2024 ("built on top of a pre-trained vision-language model"; "its ability to acquire new skills via fine-tuning"). https://arxiv.org/abs/2410.24164

Background only, not cited in the voiceover: Long et al., "CheckManual", CVPR 2025, robots reading appliance manuals (https://arxiv.org/abs/2506.09343). It's why we say "test plans from the manual", not "the first robot to read a manual".

## Questions for Karthik

1. **"Weight space programming":** I took it to mean the MIT CSAIL "Sparks of Weight-Space Programming" post (Nov 2, 2026), where a frontier model edits a network's weights directly. It's now only an on-screen line in the coda. Is that what you meant?
2. **ETH:** the refutation claims are two weeks old and still under examination. It's now the only formal result in the voiceover. Keep it with "claimed", or swap in AlphaProof's IMO silver, which is settled?
3. **Unmasking:** with the lid fixed, the centrifuge reveals F3: well A is too tight for the tube. Want that beat? At 2:45 there's no room; at 3:00 it fits.
4. **MPC and LQR:** the script says "inverse kinematics and classical control" because only IK is in our stack. Want MPC and LQR named on screen as examples of classical control?
5. **Length:** stay at 2:45 or take the 3:00 option below?
6. **The coda:** the tools and field examples now sit at 1:59–2:25, just before the close. Keep them spoken, or make the coda shorter and let the on-screen text carry more, so the close comes sooner?
7. **Your read:** once your mp3 is in, we'll re-time every section to it. If any line feels long to say, tell us which and we'll cut it rather than speed you up.

## The 3:00 option

Same sections, with more room. Spoken words: about 412.

| § | Section | Time | Seconds | Adds back | Words/s (about) |
|---|---|---|---|---|---|
| 1 | Cold open | 0:00–0:06 | 6 | | – |
| 2 | The problem | 0:06–0:28 | 22 | "Neural networks found new unstable singularities in equations close to Navier–Stokes." | 2.45 |
| 3 | Robot As A Verifier | 0:28–0:43 | 15 | | 2.53 |
| 4 | Why not one VLA | 0:43–1:05 | 22 | | 2.45 |
| 5 | Two systems | 1:05–1:27 | 22 | | 2.45 |
| 6 | One centrifuge, end to end | 1:27–1:55 | 28 | More air around the five freeze frames | 1.79 |
| 7 | Fixing the design | 1:55–2:14 | 19 | The F3 unmasking beat: "With the lid fixed, it finds the next fault: well A is too tight." | 2.47 |
| 8 | Why this matters | 2:14–2:40 | 26 | | 2.54 |
| 9 | Where it goes, and the close | 2:40–3:00 | 20 | | 2.50 |
