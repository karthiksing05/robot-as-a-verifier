# Building a test device

How to build one RAAV test device on your own: a simulated appliance with its own CadQuery model, device file, manual, planted faults and fixed revision, which the arm can run in the sim and the Console can start.

Read [device-theory.md](device-theory.md) first. Every device is a composition in that vocabulary.

The reference device is [`appliances/centrifuge/`](../appliances/centrifuge). Every file named here has a working example there. Your brief is in [device-briefs.md](device-briefs.md). Held-out briefs are in `appliances/HELDOUT_BRIEFS.md`, which is gitignored.

## Ground rules

- **Stay in your lane.** Work only in:
  - `appliances/<id>/`
  - `system-2/subjects/<id>/project.json`
  Don't edit the loader (`system-1/sim/cad_device.py`), the core skills, `system-2` code, or any prompt. If the loader can't express something, write it down under "Gaps" in your report. Don't work around it in someone else's file.
- **No device-specific code outside your folder.** The loader reads your YAML. Nothing else may know your device exists.
- **Don't commit, push, stash, reset or switch branches.** Other agents share the tree.
- **Stop anything you start.** Don't use the Google API key, and never print `.env`.
- **Use the name RAAV** in all text.
- **No microwave**, and no near-copy of the centrifuge.

## 1. Folder layout

```
appliances/<id>/                    committed: what we designed
  source/                           optional: vendor CAD and manual the design started from, as the centrifuge has
  cad/model.py                      CadQuery: assemblies() and CONCAVE (section 2)
  cad/*.py                          any helpers model.py imports
  device.yaml                       the loader's file: geometry, joints, controls, firmware, faults, revisions (sim truth)
  manual.md                         the product manual: the only file a model reads (section 6)
  wiring.md                         pins and serial channel names, as on the centrifuge (sim truth)
  verify.yaml                       how verify.py checks the device (sim truth)
  gallery.md                        the device's entry in docs/devices.md (section 7)
  build/                            gitignored, rebuilt by build.py:
    revA.step, revB.step
    meshes_revA/, meshes_revB/      one STL per part plus manifest.json, plus convex pieces
    answer_key.json                 the faults and what each revision contains (section 5)
    verify.json                     verify.py's last report
system-2/subjects/<id>/project.json the Console's record, so the device can be started from Live (section 7)
```

`<id>` is short kebab-case, such as `label-printer`. It is the same in both places.

## 2. CadQuery source

`cad/model.py` must define:

```python
def assemblies() -> dict[str, cq.Assembly]:   # exactly {"A": ..., "B": ...}
    ...
CONCAVE = ["lid_handle_revA", ...]            # parts to split into convex pieces (may be empty)
```

Build each revision as a full `cq.Assembly` of named solids. build.py saves each one as STEP, then `tools/cad_to_meshes.py` writes one STL per leaf part, named after it, with a manifest entry for its colour, bounding box and volume.

### Frame and units

Use millimetres in the **product frame**:

- the origin is on the bottom face of the base, centred
- **+X points toward the arm**
- **+Z is up**

The loader places this frame with `placement` and `stand_mm`.

### Part names

Part names are the mesh names the device file refers to, and they must be unique across the assembly. Use these suffixes:

- A part that differs between revisions gets the suffix `_revA` or `_revB`, for example `bezel_feed_revA`.
- A part that is the same in both keeps one plain name.
- Placeholders for electronics are `ref_*`. Put them in `visual_only` in the device file.

### Colours

Give every part a `cq.Color`. A revision-dependent part may be tinted, since the real kits print Rev A orange and Rev B green. Say in the manual what colour the product is, not what colour its fault parts are.

### Collision

MuJoCo collides a mesh as its convex hull, so check each part:

- **Convex parts:** use them as they are (plates, caps, knobs).
- **Parts whose holes, lips or hooks matter:** list them in `CONCAVE` (handles with a lip, rings, rotor plates with wells, U-shaped brackets). build.py splits them with CoACD into `<part>__c<i>.stl`, and the manifest lists those pieces.
- **Small or moving bodies:** often simpler as primitives in the device file's `geoms` (as `dial_knob` is) than as a mesh.

### Reach

The arm's pan axis sits at product `(274.5, 0, 58)` when you use the centrifuge's placement. Start from that placement:

```yaml
placement: {x: 313.3, y: 0.0, yaw: 180.0}
stand_mm: 82
```

Put the controls where the centrifuge's are:

- on a face tilted about 45° toward the arm, normal about `(0.7071, 0, 0.7071)`
- at product x 40 to 60, |y| up to 55, z 75 to 110

Lids with a hook handle can sit higher, up to z of about 120. This envelope is for a face sloped toward the arm. A vertical face facing the arm can't be reached here with a level tool: the wall-thermostat puts its buttons at product z 116 and the device at x 423.3 instead of 313.3, so they sit about 330 mm out and 58 mm above the pan axis. A taller stand board hits the wrist camera. During hook_pull the wrist camera passes about 14 mm over the control face for y between about -25 and +15, so put only low caps there on a device with a lid. Anything outside this envelope must be checked with `verify.py --only reach` before you build around it. A control that's meant to be out of reach is a fault or a reposition case, and you must say so in `verify.yaml`.

### Size

Keep the device within about 160 × 140 × 130 mm, so it fits on the sim's stand board, and keep the mass under 1 kg. Use the device's real-world proportions and sensible wall thicknesses: 3 mm plywood or acrylic panels, and printed caps and bezels.

## 3. The device file

[`centrifuge/device.yaml`](../appliances/centrifuge/device.yaml) shows every section. The loader is `system-1/sim/cad_device.py`, and the robot-side reader is `system-1/core/inventory.py`. Each section in order:

| Section | What it holds |
|---|---|
| `name` | short, no spaces. Used in generated file names |
| `meta` | `{title, split, project}`. `split` is `dev`, `validation` or `held_out`. The loader ignores this section. build.py and the registry read it |
| `placement`, `stand_mm`, `mounts` | where it stands. Mounts are `clamped` (default) or `free` |
| `meshes` | `build/meshes_rev{rev}` |
| `faults`, `revs` | section 4 |
| `roots` | each separate thing on the bench (the device, a rack): `mass_kg`, `parts` (mesh names, or `$param` for a revision-dependent one), `visual_only`, `arm_only` (parts only the arm collides with, like a plate with holes for objects to pass), `rings` (a bore an object sits in: `{centre: [x, y], id, z: [z0, z1]}`) |
| `bodies` | every moving part: `{name, root, parts, geoms, joint, snap}` |
| `objects` | loose things: `{name, part, root, mass_kg, collar, collar_top, stack, boxes}` (copy the centrifuge's tube) |
| `display` | at most one text display: `{root, centre, normal, up, size}` |
| `light` | at most one status light: `{root, centre, radius, colours}`. It only lights if there is a `display` |
| `controls` | the registered inventory. Each kind's keys are in the next table |
| `registration` | per root, three or more probe-touch faces whose normals pin x, y and yaw |
| `firmware` | channels, sensors, states, transitions (below) |

### Joints

A joint is `{type: slide | hinge, axis, anchor, range, stiffness, preload_n, damping, frictionloss, armature, mass}`.

- Slide ranges are in mm and hinge ranges in degrees, both in the product frame.
- A button is a slide along `-normal` with range `[0, travel]`. Use `stiffness: 2000` and `preload_n: 2.0`, the values the centrifuge's caps use.
- A toggle is a hinge with range `[0, 30]` and `snap: {nm: 0.012, centre_deg: 15}`. The 0 to 30° range and the switch at 15° are fixed in the loader and in `inventory.py`, so don't change them.
- A dial is a hinge about its normal. Make it `one_sided` with a fin, as the centrifuge's is, or the turn skill has nothing to push.

### Control kinds

The robot can only use these control kinds. The loader's `parts_from` supports nothing else (there is no slider, door, keypad or drawer kind yet).

| Kind | Skill | Required keys |
|---|---|---|
| `button` | press | `body, top, normal, x, size, radius, travel, switch_at` |
| `dial` | turn | `body, top, normal, x, size, knob_radius, knob_height, fin_length, fin_width, fin_height, floor_gap, one_sided, range_deg` |
| `toggle` | flip | `body, hinge, normal, lean, tip, size, lever_len, lever_radius, base_size` |
| `handle` | hook_pull | `body, pos, normal, grip (tip or pinch), pull, under, clear, hinge, axis, open_deg, size`, and `reads: true` if a sensor watches it |
| `display` | observe | `root, pos, normal, x, size` |
| `well` | place (into) | `root, pos, normal, x, size, collar`, and `reads: true` if sensed |
| `object` | pick | `object, collar_top, jaw_axis, flats, grips` |

Control ids are generic and numbered by kind: `button_1`, `dial_1`, `handle_1`. The manual's names (FEED, BOIL) never appear in the device file's ids. That way the model has to match the manual to the scan itself.

### Firmware

```yaml
firmware:
  channels: {power: 0, btn_feed: 0, ...}        # every serial channel and its power-up value
  sensors:                                       # joint -> channel, every physics step
    - {channel: btn_feed, joint: cap_feed, when: "q >= 0.0002"}       # q: m for a slide, rad for a hinge
    - {channel: level, joint: dial_knob, value: "1 + round(-q / radians(270) * 8)"}
    - {channel: cup, object: cup_1, root: mixer, near: [x, y, z], radius_mm: 3, height_mm: 2.5}
  states: {name: {show: {lcd: "{level} {mode}", ring: white}}}
  start: dark
  transitions:                                   # checked in order; the first match fires
    - {any: true, when: "power == 0", to: dark}
    - {from: [ready], event: btn_feed, when: "btn_feed == 1", to: ready, do: {count: "count + 1"}}
    - {from: running, when: "left <= 0", to: done, do: {run: done}}
```

Things the loader fixes:

- **Expressions** allow arithmetic, comparisons, `and`/`or`/`not`, and `round radians abs min max`. Nothing else.
- **`do` values:** a bare word like `start` is a string, and so is text that doesn't parse as an expression, such as `reason: "NO TUBE"`. To be explicit, quote it: `reason: "'NO TUBE'"`. Anything else is an expression.
- **Variables:** a `do` key that isn't a channel becomes a variable. The LCD template can use it, but nothing outside sees it.
- **LCD templates** are `{expr:format}`. Keep them to about 16 characters per line. A float with no precision in its format is rounded up to a whole number (a countdown's seconds); give a precision to keep decimals: `{absorb:.2f}`.
- **Reserved names:** the loader's own bodies start with `_` (the stand board is `_stand_board`). Don't start a root or body name with `_`.
- **Countdown:** only a state named `running` counts the variable `left` down, once a second. Use that name for any timed state, and end it with `when: "left <= 0"`. Don't use `after: "left"`: `left` is already counting down, so the state ends at half the set time.
- **`after: "expr"`** waits that many seconds since the state was entered. Use it only with a fixed expression.
- **Toggle hysteresis** is hard-coded about 15°. A toggle's `base_size` takes three values, `[x, y, z]`. Make a toggle's nut or bushing visual-only, as the centrifuge does: a collidable one blocks flip's approach.
- **Fault parameters in firmware.** `$param` works in `firmware` too, filled in from the revision's fault `params`:
  - A whole value `"$name"` takes the param's value with its own type.
  - Inside a longer string it's substituted as text, as in `when: "q >= $start_thresh"`. Parenthesise compound expressions yourself: `when: "btn_start == 1 and ($interlock)"`.
  - Map keys are substituted too: `channels: {"$start_channel": 0}`.
  - An undefined `$name` fails at load.
  - In a `do:` value, a param that resolves to a bare word such as `left` becomes a string, because bare words are strings there. Make it an expression instead: `left: "left * $pause_keeps"`.

### Check that it loads

From `system-1/`:

```
uv run --extra sim python sim/tools/verify.py <id> --only load,reach
```

The `load` check builds every revision in `revs` and starts its firmware. The `reach` check solves the arm's IK to every control listed in `verify.yaml`.

## 4. Faults and revisions

A fault is **one broken property on one piece** (device-theory.md, section 4). Rev A has all the faults, Rev B fixes each one, and mixes choose per fault.

```yaml
faults:
  F1: {what: "FEED cap binds in its bezel", class: mechanical, piece: button_1, property: actuates,
       A: {parts: {bezel_feed: bezel_feed_revA}, params: {feed_travel: 0.1}},
       B: {parts: {bezel_feed: bezel_feed_revB}, params: {feed_travel: 0.3}}}
  F2: {..., masked_by: [F1]}           # can't be seen while F1 is in
revs:
  A: {F1: A, F2: A}
  B: {F1: B, F2: B}
  M1: {F1: B, F2: A}                   # a mixed revision: each name is something the Console can start
```

- **`parts`** maps a `$name` used in `roots.parts`, `bodies.parts` or a part name, to a mesh.
- **`params`** maps a `$name` used anywhere in `bodies`, `controls`, `rings` or `firmware` to a value.
- **`class`** is one of the following:

  | Class | What it is | Example |
  |---|---|---|
  | `mechanical` | geometry or a joint is wrong | a binding cap, a short hinge range, a tight bore |
  | `electrical` | a sensor or wire is wrong | a dead switch, swapped wires, an inverted sensor |
  | `firmware` | the state machine is wrong | a wrong default, a missing guard, a wrong mapping |
  | `manual` | the device does one thing and the manual says another | a direction, a step size, a message |
  | `ergonomic` | the arm can't operate it under the rules, or can't reach it | a pinch-only handle, a control out of reach |

- **Every fault must fail by physics or by firmware.** The robot's skills must run unmodified, and the failure must come out of the sim. Examples:
  - a reading that never changes
  - a state the firmware enters
  - an object that stops high
  - a refusal the skill makes from the geometry, as with the pinch handle
  - an IK failure

  Never plant a verdict.
- **Mixed revisions.** Give each device at least one fault masked by another: for example, a dead power switch hides everything behind it, or a lid that can't be opened hides a bad well. Add a mixed revision that unmasks it.

### Electrical faults

An electrical fault can be a firmware parameter, such as a sensor's channel name, or geometry. As geometry, name the swapped bodies through parameters:

```yaml
bodies:
  - {name: $cap_left_name, ...}
  - {name: $cap_right_name, ...}
controls:
  - {..., body: $cap_left_name}
  - {..., body: $cap_right_name}
```

The firmware's sensors read joints `cap_feed` and `cap_print`, and each choice decides which physical cap carries which name. Two more patterns work the same way:

- **A dead switch:** a travel that ends before `switch_at`.
- **An inverted sensor:** a sensor fin moved to the other side, so the reading flips.

### Firmware faults

Put the revision's difference in a param and use it in `firmware` (see the rules in section 3). For example, `when: "btn_print == 1 and ($print_guard)"` with `A: {params: {print_guard: "1 == 1"}}` and `B: {params: {print_guard: "cover == 1"}}`.

## 5. Answer key

build.py writes `build/answer_key.json` from the device file's `faults` and `revs`. It is gitignored and never read by anything a model sees:

```json
{"device": "<id>", "name": "...", "split": "dev",
 "faults": [{"id": "F1", "what": "...", "class": "mechanical", "piece": "button_1", "property": "actuates", "masked_by": null, "expect": null}],
 "revs": {"A": {"choices": {...}, "faults": ["F1", "F2"], "observable": ["F1"], "masked": ["F2"]}, ...}}
```

The `what` text should say what a good report would say: the symptom and the part, not the parameter name.

`rav-server --answer-key` writes its own per-run key, which is a different thing. This one is the device's.

## 6. The manual

`manual.md` is the only file the model under test reads, so it needs care.

### Write it blind to the faults

Write the manual first, from the composition, as the designer of the product means it to work, which is Rev B. Write it before you design any fault, and don't edit it to suit one afterwards. If a later fix is needed, it may only correct how intended behaviour is described.

The manual never mentions:

- revisions or faults
- part colours that mark a revision
- part ids, channel names or anything else from the device file

A `manual`-class fault is the device disagreeing with this text. Rev B makes the device agree, and the manual stays unchanged.

### Style

Write it like a real product manual, as [the centrifuge's](../appliances/centrifuge/manual.md) is:

- a one-line product name and model number
- a numbered **Parts** list in the panel's words (FEED, PRINT, DARKNESS)
- one section per task (Power, Loading, Setting, Running), with numbered steps that give directions ("turn clockwise to raise"), ranges, step sizes, defaults and what the display or light shows
- a **Display messages** table with message, meaning and what to do
- **Care**

Keep it to about one page. Plain Markdown, no images. The Console reads `.md` directly.

## 7. Making it available: project, registry, gallery

### `system-2/subjects/<id>/project.json`

The Console lists these, and AgentLive's start form runs them:

```json
{
  "id": "<id>",
  "name": "<Product name>",
  "summary": "<one sentence a user would write: what it is and what it has>",
  "kind": "sim",
  "sim": {"path": "appliances/<id>/device.yaml", "rev": "A", "revs": ["A", "B", "M1"]},
  "manual": "appliances/<id>/manual.md",
  "products": ["<Product name> (sim)"],
  "rules": ["Usable with no thumbs"],
  "split": "dev",
  "created": "2026-11-07"
}
```

The summary must not hint at the faults.

### Registry

build.py writes `appliances/registry.json` (gitignored) from every `device.yaml`'s `meta`. It lists the id, title, split, revisions and paths. Eval scripts read it. You don't edit it by hand.

### `gallery.md`

This is your device's entry in [devices.md](devices.md). build.py assembles that page from every device's `gallery.md`, so devices never edit the same file. Use this format:

```markdown
### <Product name> (`<id>`)
**Split:** dev. **Revisions:** A, B, M1.

<Two sentences: what it is and how a person uses it.>

**Controls:** POWER toggle, FEED and PRINT buttons, DARKNESS dial, cover handle, display.
**Theory pieces:** enables (power), interlocks (cover blocks print), drives (dial to darkness), displays, momentary returns, hinge mechanism.
**Faults:** F1 mechanical: FEED binds. F2 firmware: ... (dev and validation only)
```

For a `held_out` device, write `**Faults:** held out.` and nothing more.

## 8. Build and verify

Build from the repo root. This needs CadQuery and CoACD, so it uses a throwaway environment:

```
uv run --no-project --python 3.12 --with cadquery --with coacd --with trimesh --with shapely --with pyyaml \
    python system-1/sim/tools/build.py <id>
```

Verify from `system-1/`:

```
uv run --extra sim python sim/tools/verify.py <id>            # everything
uv run --extra sim python sim/tools/verify.py <id> --only F2  # one check
uv run --extra sim python sim/tools/verify.py <id> --effector stock  # every check on the stock gripper, over verify.yaml's
```

### `verify.yaml`

```yaml
effector: stock                 # stock (the real arm's only effector, and the default) or probe (sim-only reference)
reach: {reachable: [button_1, ...], unreachable: [dial_1]}
# a revision whose geometry differs gets its own lists, checked on that revision:
# reach: {reachable: [...], unreachable: [...], revs: {A: {reachable: [button_1], unreachable: [dial_1]}}}
workflow:                       # the manual's main procedure, on Rev B
  rev: B
  steps:
    - {skill: flip, target: toggle_1, expect: {readings: {power: 1}, state: ready, lcd: "READY"}}
    - {skill: turn, target: dial_1, params: {angle: -60}, expect: {changed: [level]}}
    - {wait_s: 5, expect: {state: done}}
faults:
  F1:
    rev: "F1=A,F2=B"            # optional: the default is this fault A and every other B
    steps: [...]                # the same steps run on Rev B, where every expect must hold...
    fails_at: 1                 # ...and on the fault's revision, where the first miss must be at this step
```

**Steps.** Each step is one of these:

- a skill: `{skill, target, params}`, with skills `press turn flip hook_pull pick place observe`. Turn takes `angle` (degrees, right-handed about the control's normal). hook_pull takes `angle` (to open, or `0` to close). place takes `into`.
- `{wait_s: N}`, which lets the sim run
- `{set_joint: {name, deg | mm}}`, the operator setting a part by hand, for fixtures only
- `{drop_object: {name, into, lift_mm, settle_s}}`, the operator lowering an object over a well and letting go, so that gravity and the bore decide where it stops. Use it to check a container fault on its own. A second variant of the same fault can check it again with `pick` and `place`.
- `{move_device: {dx_mm, dy_mm, yaw_deg}}`, the operator moving the device
- `{reach: [ids]}`

**Effectors.** The real arm is a stock SO-101 with its own gripper and nothing else, so `stock` is the default and the effector that matters. The fingertip probe stays in the sim only as a reference. A fault entry may set its own `effector`, and `verify.py --effector` overrides them all. `pick` and `place` need `stock`. On the centrifuge, `hook_pull` only works with `probe`, because the stock gripper hits the lid. Make each fault's steps test that fault alone, with the effector its skills need. Switch sensors read with the power off, so a button fault doesn't need the power switch.

**Fault names.** A fault key that isn't in `device.yaml`, such as `F3p`, is a second check of a fault. Give it an explicit `rev`.

**Expectations** (all optional): `verdict` (`PASS FAIL MISSED REFUSED OBSERVED SAFETY_STOP`, or a list), `readings` (a subset, each a value or a list), `lcd` (a regex), `ring`, `state`, `changed` (channels that must change during the step), `unchanged`, and `reach`.

**What counts as verified:**

- `load` and `reach` pass.
- `workflow` passes, meaning Rev B does what the manual says with System 1's skills.
- For each fault, its steps pass on Rev B, and on its revision first fail at `fails_at`.

The rule behind this: a step's expectations describe correct behaviour, and the fault breaks them by itself. The verdict PASS only means a reading changed. A firmware fault, such as a swapped channel or a wrong default, is caught by `readings`, `lcd` or `state`, not by `verdict`.

### Out of reach and repositioning

`reposition` is not a System 1 skill yet: manipulate.py lists it, but it isn't implemented. Express a "needs reposition" case in two parts:

1. List the control in `reach.unreachable`.
2. In the fault's steps, add a `move_device` step (the operator moving the device), after which it reaches.

## 9. Definition of done

Report each of these:

- [ ] `build.py <id>` runs clean. `verify.py <id>` prints `verified` for load, reach, workflow and every fault, or each line that isn't is listed with the reason.
- [ ] The manual was written before the faults, and it says nothing about revisions or faults.
- [ ] There are at least 3 faults, from at least 3 classes, with at least one masked fault and a mixed revision that unmasks it.
- [ ] `project.json` is in place, and the device shows in the Console's project list.
- [ ] `gallery.md` is written. For held-out devices, the faults are left out.
- [ ] The report gives the files, verification per check, the theory pieces exercised, and the gaps found in the loader or skills.
