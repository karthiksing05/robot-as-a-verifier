# Demo video script

**Draft 6, Nov 8.** Target 2:45. About 395 spoken words, never faster than 2.55 words a second in any section, so it can be read at a natural pace. Numbers are written the way they're spoken, so the counts are honest. Shots, freeze frames and timing are in [storyboard.md](storyboard.md).

**What changed from Draft 5:** the stakes are back at the front. The verification examples (Lean, CompCert, seL4) and the field examples (biosafety, aerospace, mechanical design) now come right after the problem, so the opening carries the stakes again. The VLA beat is now one sentence inside "Two systems", with SmolVLA and NVIDIA's GR00T N1 as the examples. "Two systems" now spells out who owns what and why the split works. RAAV is named at 0:46 and the first robot footage is on screen at 0:49. It still fits 2:45, so the 3:00 option stays optional.

The voiceover carries the argument. The pictures move it along and show the evidence. During the freeze frames on robot footage the voice stays on the story; the overlays document what the robot is doing, and the voice doesn't read them out. Tool names and dates the voice can't fit go on screen as small source lines.

**Footage rule:** for now, every robot shot is rendered in MuJoCo (sim). Nothing has run on the real arm yet. We will probably edit the cut and re-record those shots with real footage later. Until then, sim footage carries a `SIMULATION` tag in the corner the whole time it's on screen. Real footage that's sped up carries `REAL FOOTAGE · N×` with its true speed.

**Audio:** Karthik will record the voiceover himself as an mp3, and the music is coming from him too. Until they arrive, every audio item here and in the storyboard is a placeholder. The timings below assume a natural read at these word rates; **the final cut will be re-timed to his recording**, so treat every timestamp as a target, not a lock.

**Look:** rustic chalk for the problem and the stakes (sections 1 to 3), a designed transition at 0:46 on "So we built RAAV", then the Console's crisp, technical look for the product (sections 4 to 8).

| § | Section | Time | Seconds | Words | Words/s |
|---|---|---|---|---|---|
| 1 | Cold open | 0:00–0:06 | 6 | 0 | – |
| 2 | Verification works, in software | 0:06–0:25 | 19 | 47 | 2.47 |
| 3 | Where it stops | 0:25–0:46 | 21 | 52 | 2.48 |
| 4 | Robot As A Verifier | 0:46–0:58 | 12 | 30 | 2.50 |
| 5 | Two systems | 0:58–1:54 | 56 | 142 | 2.54 |
| 6 | One centrifuge, end to end | 1:54–2:15 | 21 | 51 | 2.43 |
| 7 | Fixing the design | 2:15–2:28 | 13 | 33 | 2.54 |
| 8 | Where it goes, and the close | 2:28–2:45 | 17 | 40 | 2.35 |
| | **Total** | | 165 | **395** | 2.39 |

Word counts are spoken words: hyphenated words count once per part ("foot-and-mouth" is three, "vision-language-action" three), and "GR00T N1" ("groot en-one") and "System 1" count as two. Section 5 is long for one section, so the storyboard breaks it into six shots. To make room, "A model plans the tests, but never grades them" moved from section 4 into section 5, where the split explains it, and "Every verdict traces back to a force reading and a frame" left the close (the 3:00 option puts it back).

---

## 1. Cold open · 0:00–0:06

*No voiceover. A green chalkboard covered in buzzwords around one big question mark. Karthik walks in and erases it. The music starts on the last stroke. (Raw take: `video/real-world-assets/intro.MOV`, played at 1.75×; see storyboard shot 1.)*

---

## 2. Verification works, in software · 0:06–0:25

> Models now write proofs, and machines verify them. This October, Lean checked two claimed refutations of the Exponential Time Hypothesis. Verification already protects real systems: CompCert, a proven C compiler, is qualified for avionics, and seL4 kept a red team from taking over a helicopter in flight.

*The chalk arm draws as it talks: `ETH: 2^εn ?` with a Lean ✓, then two plaques, CompCert and seL4, each with where it's used. A ledger of the other tools and results runs along the bottom edge (TLA+ at AWS, Mathlib, the Liquid Tensor Experiment, AlphaProof, Rocq, Isabelle, the fluid-dynamics singularities, weight-space programming).*

*Say "seL4" as "ess-ee-ell-four".*

---

## 3. Where it stops · 0:25–0:46

> But verification ends where software ends. No proof says whether a lid drawn in CAD will open. So failures surface late. A lab's cracked drain likely let foot-and-mouth virus escape. Webb's fasteners shook loose in testing. Dyson needed over five thousand prototypes. And most products are still tested by hand.

*The arm draws a line down the board, `software | hardware`; the arrow from the plaques stops at it. On the right, a CAD box of the centrifuge; a pinch on its lid is drawn and crossed out. Then one vignette per field, each headed with its name: `BIOSAFETY` (a cracked drain with a root through it), `AEROSPACE` (a sunshield shedding fasteners), `MECHANICAL DESIGN` (a stack of prototypes counting to 5,127). Last, a hand pressing buttons beside a clipboard.*

---

## 4. Robot As A Verifier · 0:46–0:58

> So we built RAAV, Robot As A Verifier. Give it a prototype and its manual. A low-cost arm presses, turns and lifts each control and reports what it measured.

*The turn happens on "So we built RAAV": the chalk arm becomes the rendered SO-101 and the board becomes the Console's grid. Then the first sim footage: the arm at the centrifuge, the manual beside it, a press with its force trace.*

---

## 5. Two systems · 0:58–1:54

> Why not one end-to-end model? Vision-language-action models like SmolVLA and NVIDIA's GR00T N1 learn new tasks from fresh demonstrations, and the actor would judge itself.
>
> So RAAV splits the work. System 1 owns everything that must be exact, fast and safe: perception, inverse kinematics, control, force limits, and verdicts computed from sensor readings by fixed rules. System 2, a frontier model, owns everything that needs context and judgment: reading the manual and spec, choosing what to test and in what order, recovering when a step fails, and diagnosing the cause and proposing a CAD fix.
>
> Each does what it's good at. The model never sends a motor command and never grades its own work, so it can be swapped or upgraded, and System 1's guarantees hold whatever it says. A new device needs a manual, not new demonstrations.

*A brief motion graphic of one box, `perception + reasoning + control`, fed by demo reels, splits into `SYSTEM 1 · exact, fast, safe` and `SYSTEM 2 · context and judgment`. Each half fills with its jobs over sim footage and the model's Live reasoning, with seven tool lines between them. One freeze frame shows a plan crossing the line (storyboard F0). Then the model's name swaps between four frontier models while System 1's limits stay fixed, and a manual slides in where the demo reels were.*

---

## 6. One centrifuge, end to end · 1:54–2:15

> Here's a centrifuge we designed, and its manual. The model reads the manual and plans the tests. The arm's one nineteen-dollar wrist camera finds each control, and force readings decide each verdict.
>
> Then it finds the fault we planted: the lid handle is a thin fin, with nothing to hook.

*Robot footage (MuJoCo sim, tagged) with five freeze frames (storyboard F1–F5). The voice doesn't narrate the overlays.*

---

## 7. Fixing the design · 2:15–2:28

> The model traces the failure to the handle and proposes a CAD change: a hook lip. A person approves, and the same tests run again. It only counts if the score goes up.

*The handle morphs from Rev A's fin to Rev B's lip. A score ticks up.*

---

## 8. Where it goes, and the close · 2:28–2:45

> Next: lab instruments, appliances, assistive devices. Twelve appliances so far, all in simulation, and four frontier models compared.
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
| "This October, Lean checked two claimed refutations of the Exponential Time Hypothesis" | Impagliazzo, Paturi and Williams' examination post (Oct 26); MathWorld's ETH entry lists both preprints (OpenAI and Anthropic) and says independent specialist confirmation hadn't been reported as of Nov 1 | Keep "claimed" until the community confirms. Re-check the day before recording. The Lean checks cover the formal statements; the step to the usual machine model is still informal |
| "CompCert, a proven C compiler, is qualified for avionics" | The core of CompCert is "proved correct in Coq". Qualified in 2026 for the ATR 42/72 Multi-Function Computer New Generation, "developed by AbsInt with guidance from Airbus". MTU Friedrichshafen qualified it in Nov 2017 (IEC 60880 cat. A, IEC 61508-3 SCL 3) for engine control software in emergency-generator diesel engines for civil nuclear plants. Airbus engineers evaluated it for DO-178 level A flight control software (ERTS 2012) (sources 17–19) | The 2012 Airbus paper is an evaluation, not production use. Say "avionics" for the ATR qualification, not "Airbus flight controls". The proof covers the compiler's core, not every part |
| "seL4 kept a red team from taking over a helicopter in flight" | DARPA HACMS: on Boeing's Unmanned Little Bird, a red team given the camera partition couldn't expand access or disrupt operations, also with the helicopter in flight and two pilots at the controls; seL4 "prevented the cyber attack from compromising the flight mission" (sources 20–22) | DARPA's own case study says "formal methods" and doesn't name seL4; the seL4 Foundation page names it. The red team was handed one partition, so don't say "unhackable" |
| On-screen ledger (shot 3) | TLA+ at AWS on 10 large systems, with a 35-step DynamoDB bug; Mathlib; the Liquid Tensor Experiment, completed July 14, 2022; AlphaProof, 28 of 42 at IMO 2024 in Lean; the Four Colour Theorem "fully checked by the Coq v7.3.1 proof assistant", 2005; Coq renamed Rocq in March 2025; seL4's proof in Isabelle/HOL, 2009; DeepMind's fluid singularities, Sept 2025; weight-space programming, MIT CSAIL, Nov 2026 (sources 4–6, 12–16, 20, 23) | AlphaProof's IMO problems were "manually translated" into formal language first. No Mathlib count on screen. Never write that the fluid work solved Navier–Stokes. The weight-space post is "very early results"; **Karthik to confirm that reading** |
| "But verification ends where software ends" | Our argument. seL4's proof itself assumes the hardware is correct (Klein et al., 2009) | Framing. Don't put a source on screen for it |
| "No proof says whether a lid drawn in CAD will open" | Our argument; the on-screen pinch cites ADA Standards §309.4 (one hand, no tight grasping, pinching or wrist twisting, 5 lbf at most) | §309.4 is a US rule for operable parts in buildings. On screen, use it as the reason the rule exists, not as "the law requires" for appliances |
| "So failures surface late" | Our framing for the three examples that follow | |
| "A lab's cracked drain likely let foot-and-mouth virus escape" | HSE final report on the 2007 outbreak at Pirbright, UK: "cracked pipes, tree roots breaching pipework, and unsealed manholes"; a breached effluent pipe was the most likely source (source 24) | Keep "likely": HSE named a most likely source and couldn't say which of the two labs was responsible |
| "Webb's fasteners shook loose in testing" | Spaceflight Now on the 2018 Independent Review Board: "The fasteners came loose during an acoustic test"; a 29-month delay costing about $1 billion (source 26) | Reports differ on acoustic vs vibration test; say "testing". The board blamed mainly human error |
| "Dyson needed over five thousand prototypes" | Dyson: 5,127 prototypes and 15 years before DC01 succeeded in 1993 (source 25) | One example of iteration, not a claim about all mechanical design |
| "And most products are still tested by hand" | `docs/product.md`: products are still tested by people pressing buttons and taking notes | Our claim. Don't add a statistic |
| "Give it a prototype and its manual. A low-cost arm presses, turns and lifts each control and reports what it measured" | `docs/product.md`; the SO-101 arm (`docs/journey.md`); the centrifuge run reads `manual.md` and logs force traces and frames | In today's runs the arm is in MuJoCo; the pictures are tagged |
| "Vision-language-action models like SmolVLA and NVIDIA's GR00T N1 learn new tasks from fresh demonstrations" | SmolVLA (Hugging Face, June 2025): takes "multiple images and a language instruction" and outputs actions; pre-trained on community data "focused on the SO100 robotic arm"; evaluated on SO-100 and SO-101; its real-world tasks used datasets of 50 demonstrations each; users fine-tune from the `smolvla_base` checkpoint on their own dataset. GR00T N1 (NVIDIA, March 2025): post-trained "on datasets corresponding to each single embodiment", with 30, 100 and 300 demonstrations per task in simulation (sources 29–31) | Don't say they can't generalize; they're built to adapt with little data. The claim is that new tasks come from new demonstrations, which both papers report. SmolVLA runs on our arm family, so a judge may ask "why not SmolVLA?": that's the point of this line |
| "and the actor would judge itself" | Our argument, from `docs/product.md`: "Whatever proposes a plan or a design has no say in how it's judged" | Framing, not a cited fact. GR00T N1 itself calls its two modules "System 2" (vision-language) and "System 1" (action), but they're "tightly coupled and jointly trained end-to-end" (source 30). Mention that on screen so our naming doesn't look borrowed or confused |
| "System 1 owns everything that must be exact, fast and safe: perception, inverse kinematics, control, force limits, and verdicts computed from sensor readings by fixed rules" | `docs/system-boundary.md`: System 1 holds detection, depth perception and 3D mapping, IK, control, skills, sensors, verdict rules, safety and local retries; a 50 Hz control loop; force caps live only in System 1; "Sensors decide. Verdict rules live in System 1" | Perception includes OWLv2 and SAM, which are learned models but don't generate; the doc calls this "almost no generative AI". Don't say "no AI". Don't say we use MPC or LQR |
| "System 2, a frontier model, owns everything that needs context and judgment: reading the manual and spec, choosing what to test and in what order, recovering when a step fails, and diagnosing the cause and proposing a CAD fix" | `docs/system-boundary.md`: System 2 holds LLM calls, the planner, plan revision and the CAD fix loop; a clean FAIL always wakes System 2 "because working out what it means and what to try next takes logic"; `docs/product.md`: a spec gives limits like "usable with no thumbs" | Small slips are retried by System 1 locally; System 2 handles the failures that need a new plan. Per `docs/frontier-integration.md` (Nov 7) the model loop is still being built and rules stand in for it, so show recorded runs, not a claim that every run is model-driven |
| "The model never sends a motor command" | `docs/system-boundary.md`: seven tools, "no motor, joint or jog tool, on purpose"; "no prompt, bug or bad plan can drive a joint directly" | The hardware E-stop is separate from all of this |
| "and never grades its own work" | `docs/system-boundary.md`: verdict rules live in System 1, and reward is plain code; "Plain code in System 2 assigns the level… so the model can't grade its own change" | |
| "so it can be swapped or upgraded" | The model sits behind the harness and the seven tools; four frontier models have been run through it (`docs/journey.md` §11–12) | Don't imply a ranking; round 1 didn't separate them |
| "and System 1's guarantees hold whatever it says" | System 1 clamps every parameter to its own limits, rejects steps above the force limit, and holds safe if System 2 is unreachable (`docs/system-boundary.md`; `docs/decisions.md` D31, D34) | "Guarantees" means these limits and rules, enforced in code. Not a formal proof |
| "A new device needs a manual, not new demonstrations" | System 1's skills are a fixed list with no training per device; the planner starts from the manual; twelve appliances run in the sim (`docs/product.md`, `docs/devices.md`) | True for devices whose controls fit the existing skills (press, turn, lift and so on). A new kind of control needs a new skill, written in code, not demonstrations. Say it this way if asked |
| "Here's a centrifuge we designed… force readings decide each verdict" | `appliances/centrifuge`; `docs/journey.md` §3 (the $19 wrist camera); `docs/product.md` | |
| "the fault we planted: … a thin fin, with nothing to hook" | Centrifuge F2, Rev A (`appliances/centrifuge/gallery.md`) | Show a sim run where the verdict is right |
| "proposes a CAD change: a hook lip" | Rev A and Rev B meshes exist in `appliances/centrifuge/build/` | Don't say it happened live, and don't say "printed": Rev B hasn't been printed |
| "the same tests run again… It only counts if the score goes up" | The fix loop's rule (`README.md`) | Show sim numbers only, tagged |
| "Next: lab instruments, appliances, assistive devices" | Where we want it to go (`docs/product.md`, pitch framings) | A direction, not a claim of what it does today |
| "Twelve appliances so far, all in simulation, and four frontier models compared" | `docs/devices.md` (12 in `appliances/`); `docs/journey.md` §11–12 (Haiku 5.5, Sonnet 5.5, GPT-5.4, Grok 4.7) | Round 1 didn't separate the models. Don't imply a ranking |
| "Proofs got Lean. Software got CompCert. Hardware gets a verifier." | Lean, CompCert: sources 11–14, 17–19 | A slogan. CompCert stands for verified software in general; seL4 sits beside it on screen |
| Real arm | Not run on the real arm yet. Every robot shot is MuJoCo for now | Until it is, every robot clip is sim and tagged so. Expect to re-record with real footage later |

## Sources

Cited in the voiceover or on screen. Each was opened while writing this draft (new ones on Nov 8, for Drafts 4 to 6).

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

Background only, not cited in the voiceover: Long et al., "CheckManual", CVPR 2025, robots reading appliance manuals (https://arxiv.org/abs/2506.09343). It's why we say "test plans from the manual", not "the first robot to read a manual".

## Questions for Karthik

1. **"Weight space programming":** I took it to mean the MIT CSAIL "Sparks of Weight-Space Programming" post (Nov 2, 2026), where a frontier model edits a network's weights directly. It's an on-screen ledger line only. Is that what you meant?
2. **ETH:** the refutation claims are two weeks old and still under examination. Keep it with "claimed", or swap in AlphaProof's IMO silver, which is settled?
3. **SmolVLA:** it's trained mostly on SO-100 data and evaluated on the SO-101, our arm. Naming it is a strong contrast, but it invites "why not just fine-tune SmolVLA?". The answer is in the next lines (new demonstrations per task, and it would judge itself). Happy with that, or name it on screen only?
4. **Unmasking:** with the lid fixed, the centrifuge reveals F3: well A is too tight for the tube. Want that beat? At 2:45 there's no room; at 3:00 it fits.
5. **Length:** 2:45 still works with the stakes restored. Stay there, or take the 3:00 option for more air?
6. **Your read:** section 5 is 56 s of one voice. If it feels long to say, tell us which lines and we'll cut them rather than speed you up. Every shot gets re-cut to your mp3.

## The 3:00 option

Same sections, with more room. Spoken words: about 426.

| § | Section | Time | Seconds | Adds back | Words/s (about) |
|---|---|---|---|---|---|
| 1 | Cold open | 0:00–0:06 | 6 | | – |
| 2 | Verification works, in software | 0:06–0:28 | 22 | "Amazon found design bugs with TLA+." | 2.41 |
| 3 | Where it stops | 0:28–0:49 | 21 | | 2.48 |
| 4 | Robot As A Verifier | 0:49–1:01 | 12 | | 2.50 |
| 5 | Two systems | 1:01–1:57 | 56 | | 2.54 |
| 6 | One centrifuge, end to end | 1:57–2:20 | 23 | More air around the five freeze frames | 2.22 |
| 7 | Fixing the design | 2:20–2:39 | 19 | The F3 unmasking beat: "With the lid fixed, it finds the next fault: well A is too tight." | 2.47 |
| 8 | Where it goes, and the close | 2:39–3:00 | 21 | "Every verdict traces back to a force reading and a frame." | 2.43 |
