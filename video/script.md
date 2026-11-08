# Demo video script

**Draft 4, Nov 8.** Target 2:45. About 397 spoken words, never faster than 2.55 words a second in any section, so it can be read at a natural pace. Numbers are written the way they're spoken, so the counts are honest. Shots, freeze frames and timing are in [storyboard.md](storyboard.md).

The voiceover carries the argument. The pictures move it along and show the evidence. During the freeze frames on robot footage the voice stays on the story; the overlays document what the robot is doing, and the voice doesn't read them out. Tool names and dates the voice can't fit go on screen as small source lines.

**Footage rule:** for now, every robot shot is rendered in MuJoCo (sim). Nothing has run on the real arm yet. We will probably edit the cut and re-record those shots with real footage later. Until then, sim footage carries a `SIMULATION` tag in the corner the whole time it's on screen. Real footage that's sped up carries `REAL FOOTAGE · N×` with its true speed.

**Audio:** the voiceover and music are coming soon from Karthik. Until they arrive, every audio item here and in the storyboard (the read, the music cues, the sound effects) is a placeholder, and the timings assume a natural read at the word rates below.

**Look:** rustic chalk for the problem, for what RAAV is, and for why it isn't one model (sections 1 to 6), a designed transition at 1:31 on "System 1 is the robot", then the Console's crisp, technical look for the product (sections 7 to 10).

| § | Section | Time | Seconds | Words | Words/s |
|---|---|---|---|---|---|
| 1 | Cold open | 0:00–0:06 | 6 | 0 | – |
| 2 | Formal results are flying | 0:06–0:31 | 25 | 63 | 2.52 |
| 3 | Verification ends where software ends | 0:31–0:45 | 14 | 35 | 2.50 |
| 4 | Where physical verification is missing | 0:45–1:00 | 15 | 38 | 2.53 |
| 5 | Robot As A Verifier | 1:00–1:15 | 15 | 38 | 2.53 |
| 6 | Why not one model | 1:15–1:31 | 16 | 40 | 2.50 |
| 7 | Two systems | 1:31–1:51 | 20 | 50 | 2.50 |
| 8 | One centrifuge, end to end | 1:51–2:12 | 21 | 50 | 2.38 |
| 9 | Fixing the design | 2:12–2:25 | 13 | 33 | 2.54 |
| 10 | Where it goes, and the close | 2:25–2:45 | 20 | 50 | 2.50 |
| | **Total** | | 165 | **397** | 2.41 |

**It fits at 2:45, but only just.** Every section from 2 to 7 runs close to the limit. Moving RAAV's introduction ahead of the "one model" argument cost about 15 s, paid for by a faster cold open (1 s), a shorter "why not one model" (it no longer carries the RAAV name or the team line) and a slightly tighter section 2. Two lines from Draft 3 (the reproducibility survey and the robot chemist) no longer fit; the 3:00 option at the end puts the survey back.

---

## 1. Cold open · 0:00–0:06

*No voiceover. A green chalkboard covered in buzzwords around one big question mark. Karthik walks in and erases it. The music starts on the last stroke. (Raw take: `video/real-world-assets/intro.MOV`, played at 1.75×; see storyboard shot 1.)*

---

## 2. Formal results are flying · 0:06–0:31

> In October, OpenAI and Anthropic each posted a claimed refutation of the Exponential Time Hypothesis, a bound on solving hard problems. Lean checked the proofs; experts are still examining them.
>
> Neural networks found new unstable singularities in equations close to Navier–Stokes, a Millennium Prize problem. Models have started rewriting network weights directly.
>
> Each one has a verification loop. That's why they move fast.

*The chalk arm draws as it talks: `ETH: 2^εn ?` with a Lean ✓, a swirl of flow lines with a spike, a small grid of weights with one cell rewritten. Then a loop arrow: propose → verify → retry. Along the board's edge, a chalk ledger of the tools behind this: Lean (Mathlib, the Liquid Tensor Experiment, AlphaProof), Rocq, Isabelle, TLA+. The voice names only Lean.*

---

## 3. Verification ends where software ends · 0:31–0:45

> Formal verification protects real systems: the CompCert compiler, the seL4 kernel. But it ends where software ends. No proof says whether a lid drawn in CAD opens without the pinch grip accessibility standards rule out.

*Two chalk plaques, each with where it's used: CompCert in avionics and in engine control for nuclear emergency generators; seL4 in a DARPA helicopter that a red team attacked in flight. The arm draws a line down the board, `software | hardware`. The arrow from the plaques stops at the line. On the right, a CAD box of the centrifuge; a pinch on its lid is drawn and crossed out.*

*Say "seL4" as "ess-ee-ell-four".*

---

## 4. Where physical verification is missing · 0:45–1:00

> Without physical verification, failures surface late. In biosafety, a lab's cracked drain likely let a virus out. In mechanical design, flaws appear only in prototypes. In aerospace, Webb's fasteners shook loose in testing. And appliances? Tested by hand.

*Four chalk vignettes, one per field, each headed with the field's name: `BIOSAFETY` (a drain with a crack and a root through it), `MECHANICAL DESIGN` (a stack of prototypes counting up to 5,127), `AEROSPACE` (a folded sunshield, a loudspeaker, fasteners falling), `APPLIANCES` (a hand pressing buttons beside a clipboard). The examples and their sources are on screen.*

---

## 5. Robot As A Verifier · 1:00–1:15

> So we built RAAV, Robot As A Verifier. Give it a prototype and its manual. A low-cost arm presses, turns and lifts each control and reports what it measured. A model plans the tests, but never grades them.

*Still chalk. The arm writes `RAAV` large, the way Karthik wrote it in the cold-open take, then draws the loop: prototype + manual → arm → `measured` → report. A cloud labelled `model` feeds `plans tests` into the loop; an arrow from the cloud to `verdict` is struck out.*

---

## 6. Why not one model · 1:15–1:31

> Why not one end-to-end model? OpenVLA learned from nearly a million demonstrations, and the model that acts would also be the judge. In our experience, inverse kinematics and classical controllers already handle most of the motion. What's missing is context.

*Still chalk. The arm draws one big box, `see + decide + move + judge`, fed by a tall stack of demo reels, then circles `judge` and draws an arrow from the box back into itself. Then it wipes the box in half: on the left it draws its own skeleton with an IK triangle and a small control loop; on the right a speech bubble with a `?` inside: `context`, with `what to test?` and `what does this failure mean?` around it.*

---

## 7. Two systems · 1:31–1:51

> System 1 is the robot: perception, control, safety and the verdict rules. It never calls a language model. System 2 is a frontier model that plans, recovers and diagnoses. Seven named tools join them, and none moves a joint, so each side can be built and tested on its own.

*The transition happens on "System 1 is the robot": the chalk halves from section 6 become `SYSTEM 1 · the robot` and `SYSTEM 2 · the model`, with seven tool lines between them, and one freeze frame shows a plan crossing the line (storyboard F0).*

---

## 8. One centrifuge, end to end · 1:51–2:12

> Here's a centrifuge we designed, and its manual. The model reads the manual and plans the tests. The arm's one nineteen-dollar wrist camera finds each control, and force readings decide each verdict.
>
> Then it finds the fault we planted: the lid handle is a thin fin, with nothing to hook.

*Robot footage (MuJoCo sim, tagged) with five freeze frames (storyboard F1–F5). The voice doesn't narrate the overlays.*

---

## 9. Fixing the design · 2:12–2:25

> The model traces the failure to the handle and proposes a CAD change: a hook lip. A person approves, and the same tests run again. It only counts if the score goes up.

*The handle morphs from Rev A's fin to Rev B's lip. A score ticks up.*

---

## 10. Where it goes, and the close · 2:25–2:45

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
| "OpenAI and Anthropic each posted a claimed refutation of the Exponential Time Hypothesis… Lean checked the proofs; experts are still examining them" | Impagliazzo, Paturi and Williams' examination post (Oct 26); MathWorld's ETH entry lists both preprints and says independent specialist confirmation hadn't been reported as of Nov 1 | Keep "claimed" and "still examining" until the community confirms. Re-check the day before recording. The Lean checks cover the formal statements; the step to the usual machine model is still informal |
| "a bound on solving hard problems" | ETH (Impagliazzo and Paturi, 2001): 3-SAT has no subexponential-time algorithm | Plain-language gloss, not the formal statement |
| "new unstable singularities in equations close to Navier–Stokes, a Millennium Prize problem" | Google DeepMind with Brown, NYU and Stanford, Sept 2025: Boussinesq, IPM and related equations. Clay lists Navier–Stokes existence and smoothness as a Millennium problem | Never say they solved Navier–Stokes or found a Navier–Stokes singularity. The page says the precision "enables" computer-assisted proofs, not that those proofs are done |
| "Models have started rewriting network weights directly" | "Sparks of Weight-Space Programming", Takehi, Teoh, Zhang and Khattab (MIT CSAIL), Nov 2, 2026 | A blog post, "very early results" in the authors' words, not peer reviewed. The line avoids numbers and stays true under the older "fast weight programmer" reading too. **Karthik to confirm this is what he meant** |
| "Each one has a verification loop" | Our framing: a Lean check for ETH, high-precision numerical validation for the singularities, evaluation for the weight edits | Framing, not a cited fact. Don't say all three are formally proved |
| On-screen ledger: Lean · Mathlib, Liquid Tensor Experiment, AlphaProof | Mathlib's stats page (hundreds of thousands of theorems); LTE completed July 14, 2022, a challenge Scholze posed in Dec 2020; AlphaProof proves statements in Lean, scored 28 of 42 at IMO 2024, silver level (sources 12–14) | AlphaProof's IMO problems were "manually translated" into formal language first. Its model was fine-tuned to autoformalize other problems for training; don't claim it autoformalized the IMO problems. Don't put a Mathlib count on screen without re-reading the page, as it grows daily |
| On-screen ledger: Rocq · Four Colour Theorem | Gonthier's report: the proof "was fully checked by the Coq v7.3.1 proof assistant"; completed 2005 (Gonthier and Werner). Coq was renamed Rocq with 9.0, March 12, 2025 (sources 15–17) | Write `Rocq (Coq)` so people who know the old name follow |
| On-screen ledger: Isabelle/HOL · seL4; TLA+ · AWS | seL4's functional-correctness proof is in Isabelle/HOL, completed 2009. AWS engineers used TLA+ on 10 large systems at the time of writing; on DynamoDB it found a data-loss bug whose shortest trace was 35 steps (sources 20, 23) | Say "design bugs found", not "AWS is formally verified" |
| "Formal verification protects real systems: the CompCert compiler" | The core of CompCert is "proved correct in Coq". MTU Friedrichshafen qualified it in Nov 2017 (IEC 60880 cat. A, IEC 61508-3 SCL 3) for engine control software in diesel engines that drive emergency generators in civil nuclear plants. Qualified in 2026 for the ATR 42/72 Multi-Function Computer New Generation, "developed by AbsInt with guidance from Airbus". Airbus engineers evaluated it for DO-178 level A flight control software (ERTS 2012) (sources 17–19) | The 2012 Airbus paper is an evaluation, not production use. Say "avionics" for the ATR qualification, not "Airbus flight controls". The proof covers the compiler's core, not every part |
| "the seL4 kernel" | DARPA HACMS: seL4 ran on Boeing's Unmanned Little Bird; a red team given the camera partition couldn't break out of it, also with the helicopter in flight and two pilots at the controls (sources 20–22) | DARPA's own case study says "formal methods" and doesn't name seL4; the seL4 Foundation page names it. On screen, say the red team "couldn't break out", not "couldn't hack it": they were handed one partition |
| "But it ends where software ends" | Our argument. seL4's proof itself assumes the hardware is correct (Klein et al., 2009) | Framing. Don't put a source on screen for it |
| "No proof says whether a lid drawn in CAD opens without the pinch grip accessibility standards rule out" | ADA Standards §309.4, per the Access Board guide: one hand, no tight grasping, pinching or wrist twisting, 5 lbf at most | US rule for operable parts in buildings. Say "accessibility standards", not "the law requires" for appliances. The repo's own spec rule is "usable with no thumbs" |
| "In biosafety, a lab's cracked drain likely let a virus out" | HSE final report on the 2007 foot-and-mouth outbreak at Pirbright, UK: "cracked pipes, tree roots breaching pipework, and unsealed manholes"; a breached effluent pipe was the most likely source (source 24) | Keep "likely": HSE named a most likely source and couldn't say which of the two labs was responsible |
| "In mechanical design, flaws appear only in prototypes" | Dyson: 5,127 prototypes and 15 years before DC01 succeeded in 1993 (source 25) | Our framing with one example. Don't claim prototypes are the only way to find flaws |
| "In aerospace, Webb's fasteners shook loose in testing" | Spaceflight Now on the 2018 Independent Review Board: "The fasteners came loose during an acoustic test"; tears in the sunshield after a deployment test; a 29-month delay costing about $1 billion (source 26) | Reports differ on acoustic vs vibration test; say "testing". The board blamed mainly human error, so don't claim analysis "passed" it |
| "And appliances? Tested by hand." | `docs/product.md`: products are still tested by people pressing buttons and taking notes | Our claim. Don't add a statistic |
| "Give it a prototype and its manual. A low-cost arm presses, turns and lifts each control and reports what it measured" | `docs/product.md`; the SO-101 arm (`docs/journey.md`); the centrifuge run reads `manual.md` and logs force traces and frames | In today's runs the arm is in MuJoCo; the pictures are tagged |
| "A model plans the tests, but never grades them" | `docs/product.md`: "the model thinks, code moves, sensors decide"; verdict rules live in System 1 (`docs/system-boundary.md`) | The model diagnoses failures in section 9; that isn't grading |
| "Why not one end-to-end model? OpenVLA learned from nearly a million demonstrations" | OpenVLA abstract: "a 7B-parameter open-source VLA trained on a diverse collection of 970k real-world robot demonstrations" | A question, not "everyone does this". Don't claim VLAs can't work; the argument is about data needs and who judges |
| "the model that acts would also be the judge" | Our argument, from `docs/product.md`: "Whatever proposes a plan or a design has no say in how it's judged" | Framing, not a cited fact. It applies to using one model as its own verifier |
| "In our experience, inverse kinematics and classical controllers already handle most of the motion" | The team's experience, stated as such. System 1 uses IK and fixed policies (`system-1/README.md`, `docs/system-boundary.md`) | **Don't say we use MPC or LQR**: they're part of the team's general experience, not this stack. If Karthik wants them named on screen, label them "classical control" in the chalk drawing, not as RAAV parts |
| "What's missing is context" | `docs/system-boundary.md`: System 2 holds planning, plan revision and diagnosis; "would it still have to work if the model's API went down mid-routine?" | |
| "System 1 is the robot: perception, control, safety and the verdict rules. It never calls a language model" | `docs/system-boundary.md`, `system-1/README.md` | |
| "System 2 is a frontier model that plans, recovers and diagnoses" | `docs/frontier-integration.md` | The model loop is being built; show recorded runs, not a claim that every run is model-driven |
| "Seven named tools join them, and none moves a joint" | `docs/system-boundary.md`: seven tools, "no motor, joint or jog tool, on purpose"; System 1 clamps every parameter (`docs/journey.md` §7) | |
| "so each side can be built and tested on its own" | Separate installs and lockfiles; boundary tests in `system-2/tests/test_repo.py` and `system-1/tests/test_boundary.py` | |
| "The arm's one nineteen-dollar wrist camera" | `docs/journey.md` §3 | |
| "force readings decide each verdict" | `docs/product.md`: "the model thinks, code moves, sensors decide" | |
| "the fault we planted: … a thin fin, with nothing to hook" | Centrifuge F2, Rev A (`appliances/centrifuge/gallery.md`) | Show a sim run where the verdict is right |
| "proposes a CAD change: a hook lip" | Rev A and Rev B meshes exist in `appliances/centrifuge/build/` | Don't say it happened live, and don't say "printed": Rev B hasn't been printed |
| "the same tests run again… It only counts if the score goes up" | The fix loop's rule (`README.md`) | Show sim numbers only, tagged |
| "Twelve appliances so far, all in simulation, and four frontier models compared" | `docs/devices.md` (12 in `appliances/`); `docs/journey.md` §11–12 (Haiku 5.5, Sonnet 5.5, GPT-5.4, Grok 4.7) | Round 1 didn't separate the models. Don't imply a ranking |
| "Proofs got Lean. Software got CompCert. Hardware gets a verifier." | Lean, CompCert: sources 11–14, 17–19 | A slogan. CompCert stands for verified software in general; seL4 sits beside it on screen |
| Real arm | Not run on the real arm yet. Every robot shot is MuJoCo for now | Until it is, every robot clip is sim and tagged so. Expect to re-record with real footage later |

## Sources

Cited in the voiceover or on screen. Each was opened while writing this draft (new ones on Nov 8, for Draft 4).

1. Impagliazzo, Paturi and Williams, "ETH refutation: examination and discussion", Oct 26, 2026. https://ethdiscussion.blog/2026/10/26/eth-refutation-examination-and-discussion/
2. Weisstein, "Exponential Time Hypothesis", MathWorld (lists the OpenAI and Claude preprints and their verification status). https://mathworld.wolfram.com/ExponentialTimeHypothesis.html
3. Impagliazzo and Paturi, "On the Complexity of k-SAT", J. Comput. Syst. Sci. 62 (2001). https://doi.org/10.1006/jcss.2000.1727
4. Google DeepMind, "Discovering new solutions to century-old problems in fluid dynamics", Sept 18, 2025. https://deepmind.google/blog/discovering-new-solutions-to-century-old-problems-in-fluid-dynamics/
5. Clay Mathematics Institute, "Navier–Stokes Equation" (Millennium Prize problem). https://www.claymath.org/millennium/navier-stokes-equation/
6. Takehi, Teoh, Zhang and Khattab, "Sparks of Weight-Space Programming", MIT CSAIL, Nov 2, 2026. https://rikiyat.github.io/blog/weight-space-programming
7. Baker, "1,500 scientists lift the lid on reproducibility", Nature 533, 452–454 (2016). https://www.nature.com/articles/533452a (summary opened at https://www.statnews.com/pharmalot/2016/06/01/reproducibility-experiments-scientists/) *(3:00 option only)*
8. Burger et al., "A mobile robotic chemist", Nature 583, 237–241 (2020). https://doi.org/10.1038/s41586-020-2442-2 (details opened at https://www.liverpool.ac.uk/cooper-group/news/stories/title,1215738,en.php) *(no longer in the cut; kept for the Console's Background page)*
9. U.S. Access Board, Guide to the ADA Standards, Chapter 3: Operable Parts (§309.4). https://www.access-board.gov/ada/guides/chapter-3-operable-parts/
10. Kim et al., "OpenVLA: An Open-Source Vision-Language-Action Model", 2024 (970k robot demonstrations). https://arxiv.org/abs/2406.09246
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

Background only, not cited in the voiceover: Long et al., "CheckManual", CVPR 2025, robots reading appliance manuals (https://arxiv.org/abs/2506.09343). It's why we say "test plans from the manual", not "the first robot to read a manual".

## Questions for Karthik

1. **"Weight space programming":** I took it to mean the MIT CSAIL "Sparks of Weight-Space Programming" post (Nov 2, 2026), where a frontier model edits a network's weights directly. Is that what you meant? The line is written to stay true if you meant the older fast-weight-programmer work instead.
2. **ETH:** the refutation claims are two weeks old and still under examination. Keep it as the lead example with "claimed", or lead with Navier–Stokes and make ETH the second beat?
3. **Whose voice:** yours, or the team's in turns?
4. **Unmasking:** with the lid fixed, the centrifuge reveals F3: well A is too tight for the tube. Want that beat? At 2:45 there's no room; at 3:00 it fits.
5. **MPC and LQR:** the script says "inverse kinematics and classical controllers" because only IK is in our stack. Want MPC and LQR named in the chalk drawing as examples of classical control?
6. **Length:** stay at 2:45 or take the 3:00 option below? The new RAAV section and the named fields push hard on 2:45.
7. **Section 4:** the reproducibility survey and the robot chemist were cut to make room for the three named fields. Bring the survey back (3:00 option), or is the field list enough?

## The 3:00 option

Same sections, with more room. Spoken words: about 434.

| § | Section | Time | Seconds | Adds back | Words/s (about) |
|---|---|---|---|---|---|
| 1 | Cold open | 0:00–0:06 | 6 | | – |
| 2 | Formal results are flying | 0:06–0:34 | 28 | "Lean accepts a proof or it doesn't." | 2.50 |
| 3 | Verification ends where software ends | 0:34–0:48 | 14 | | 2.50 |
| 4 | Where physical verification is missing | 0:48–1:10 | 22 | "In a Nature survey, over seventy percent of researchers had failed to reproduce another lab's work." | 2.45 |
| 5 | Robot As A Verifier | 1:10–1:25 | 15 | | 2.53 |
| 6 | Why not one model | 1:25–1:41 | 16 | | 2.50 |
| 7 | Two systems | 1:41–2:01 | 20 | | 2.50 |
| 8 | One centrifuge, end to end | 2:01–2:21 | 20 | | 2.50 |
| 9 | Fixing the design | 2:21–2:40 | 19 | The F3 unmasking beat: "With the lid fixed, it finds the next fault: well A is too tight." | 2.47 |
| 10 | Where it goes, and the close | 2:40–3:00 | 20 | | 2.50 |
