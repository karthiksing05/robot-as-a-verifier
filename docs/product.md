# Product

## In one paragraph

Our product is a verifier for autonomous hardware R&D. You give it an instruction manual, a CAD model if one exists, and the product itself, placed in front of a robot arm fitted with pressure and touch sensors. The arm runs an autonomous exploration routine. You can steer it at any point, to look at a particular output or prioritize a decision. All of this sits in a front end with a chat interface. At the end, the robot generates bug reports that you can follow back to the exact failure. As an option, a CAD integration edits the model to fix those bugs.

Software teams ship with test coverage. Hardware has nothing like it, and products are still tested by people pressing buttons and taking notes.

## What goes in and what comes out

| In | Required? | Used for |
|---|---|---|
| The physical product | Yes | Everything |
| Instruction manual | Expected | Gives the planner its first list of controls and expected behavior. A mismatch with the real product is itself a finding |
| CAD | Optional | Needed only for patching, or for the backup localization route. The headline route reads no CAD |
| Spec | Optional | Limits and rules such as "usable with no thumbs" |
| Steering from a person | Any time | Pause, prioritize a control, skip one, add a test, ask a question |

| Out | What it is |
|---|---|
| Bug reports | One `Finding` per fault: what happened, what the manual says, the evidence, and links back to the exact step |
| Coverage report | Each control: passed, failed, observed, skipped with a reason, or inconclusive |
| Reward | Control coverage × pass rate, recomputable from the logs |
| CAD patch (optional) | The smallest parameter change for each root cause, with a predicted effect |

## The rule that holds it together

**The model thinks, code moves, sensors decide.** Whatever proposes a plan or a design has no say in how it's judged. That is what makes the score a verifiable reward, and not a model's opinion of its own work.

## The demo

The test subject is our own printed appliance: a box of about 120 × 160 × 180 mm with three buttons, an LCD and a hinged door, designed at the event. Patchable parts are small inserts, so a patch reprints in 15 to 40 minutes. Rev A has two planted faults:

| Fault | CAD parameter | What the robot measures | Patch |
|---|---|---|---|
| Button 2 binds | `button_clearance[1] = 0.15 mm` | Force limit reached with about 0.3 mm of travel, while its siblings click at about 3 N | 0.15 → 0.40 mm |
| Door needs a pinch | `handle_style = "tab"` | A flat pad can't open it, and the spec bans pinching | tab → push latch |

The three-minute story:

1. Load the manual. The planner scaffolds a test plan from it, and a person approves.
2. The robot explores the appliance and tests each control, live on the Console. A judge steers it from the chat.
3. It finds both faults and shows the evidence. Reward 0.60.
4. The analyst names the root cause from the real logs and proposes a CAD patch. A teammate approves.
5. Rev B prints (about 40 minutes, so this part is prepared ahead of the slot) and takes the same tests. Reward 1.00.

A second product, a remote and receiver, is the reach goal. It shows the system isn't hand-tuned to one object.

## What we can claim

- Say: "test plans generated from the manual and run by a low-cost arm." Do not say "first robot product tester" or "first robot to read a manual": ApBot, CheckManual and UseAppliance exist.
- Sim results are sim results. No device tested so far had a broken control, so catching a real fault is still unproven. See [results](../system-1/sim/docs/results.md) and [sim vs real](../system-1/sim/docs/sim-vs-real.md).
- The other case studies in the mockup (brewer, toaster, and so on) are simulated design studies, not runs.

## Pitch framings

The same product supports two stories, in the [mockup's Impact page](https://claude.ai/artifact/2wY8eCvh5VkNb8QSE98Sum#impact): healthcare (products that work for weaker hands) and environmental (working products that don't get thrown away). Pick one when the tracks are confirmed. The long-term vision is the same verifier scoring AI-designed hardware, and the robot's own tools.
