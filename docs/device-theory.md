# A theory of devices

A small vocabulary that every RAAV test device is written in, and that a model can use to describe a device it has never seen. The device files, manuals and gallery follow from it. So do the tests: each piece of the vocabulary comes with the properties worth testing for it.

The schema is [`theory.py`](../system-2/harness/src/rav_harness/theory.py): plain pydantic types and property templates, with no device names in it.

Its job is to scaffold a model, not to replace one:

1. The model reads the manual and the scan.
2. It writes its own hypothesis of the device in this vocabulary.
3. It derives tests from the properties.

The theory describes devices in general. It never holds what is wrong with a particular one.

## 1. Pieces

A device is a set of pieces. Each piece has an `id`, a `label` (what the manual or the panel calls it), and `sources` (`manual`, `scan`, `cad` or `observed`, meaning where the model learned of it).

### Controls

A control is something a person operates. It is classified by the **affordance primitive** it needs, because that is what decides whether the arm can test it at all.

| Primitive | Operated by | System 1 skill | Typical controls |
|---|---|---|---|
| `press` | a push along its normal, then letting go | `press` | buttons, keys |
| `turn` | rotation about its normal | `turn` | dials, knobs, selectors |
| `flip` | a lever thrown past centre | `flip` | toggle switches |
| `slide` | a push along its slot | `slide` | sliders |
| `push_latch` | a push that latches, and a push that releases | `push_latch` | push-to-open doors |
| `hook_pull` | a pull on a lip or handle about a hinge | `hook_pull` | lids, doors, covers |
| `pick` / `place` | lifting an object and seating it in a container | `pick`, `place` | tubes, cups, cartridges |

Every control also has a **return** behaviour:

- `momentary` controls spring back, like a button.
- `latching` controls stay where they are put until operated again, like a toggle or a latch.
- `continuous` controls stay at any value in a range, like a dial.

A control can also have a **range**, with ends, a unit and a direction. For example, "clockwise raises".

### Indicators

An indicator is something a person reads: a text display, a light, a beeper, or a mechanical flag. It has `shows`, the state it reports, and for text displays a `vocabulary` of the messages the manual documents. Its primitive is `observe`.

### Mechanisms

A mechanism is a part that moves but isn't itself a control:

- a lid on a `hinge`
- a drawer on a `slide`
- a `latch`
- a `spring`

It has a range (an opening angle or a travel) and a rest position, which is where gravity or a spring leaves it. Most mechanisms are operated through a control, such as a handle on a lid.

### Containers and objects

A container is where an object goes: a `well`, `slot`, `tray`, `cradle` or `hopper`. It has the objects it `accepts`, and whether it is `sensed`, meaning the device knows when something is seated.

An object is a loose thing the device works with: a tube, a cup or a cartridge. It has the containers it `fits`.

### State

A state variable is something the device remembers. It has:

- a `domain`, which is a set of values or a numeric range with a unit
- a `default`, its value at power-on
- `persists`, whether it survives a power cycle

The device's **mode** is a state variable too, for example dark, ready, running or done. Modes are what procedures move between.

## 2. Relations

Relations say how pieces affect each other. There are five kinds, and each reads as a sentence.

| Relation | Reads as | Example |
|---|---|---|
| `enables` | A must be in a state for B to do anything | the power switch enables every button |
| `requires` | B refuses unless A holds | starting requires an object seated in the well |
| `interlocks` | while A is in a state, B is blocked, and the device says so | an open lid blocks start and shows a message |
| `drives` | operating A changes state variable B, by a mapping | the dial drives the speed, 1000 to 6000 over its sweep |
| `displays` | indicator A shows state B | the display shows the speed and the time left |

`requires` and `interlocks` differ in feedback. An interlock is a guard the device announces. A requirement may fail silently.

## 3. Procedures

A procedure is a sequence of steps from the manual: power on, load a tube, set the time, start. Each step is a primitive on a target, with:

- **preconditions**: conditions on state that must hold first, such as the lid being closed
- **effects**: conditions that hold after, such as the mode being running and the display counting down

A condition is a triple of `subject`, `op` and `value`, such as `("lid", "==", "closed")`.

Procedures are where the manual makes promises. Each effect is a claim the device can break.

## 4. Properties worth testing

Each piece and relation carries the properties worth checking on it. A property template names what it applies to, what to do, and what evidence decides it.

| Property | Applies to | Holds when |
|---|---|---|
| `actuates` | control | operating it changes its reading or the state it drives |
| `gives_feedback` | control with a `displays` path | the effect shows on an indicator, as the manual says |
| `respects_range` | control or mechanism with a range | it reaches both ends, and the values at the ends are the manual's |
| `direction_matches` | `drives` relation | moving the control the manual's way moves the value the manual's way |
| `mapping_matches` | `drives` relation | sampled positions give the manual's values |
| `returns_to_default` | momentary control | it springs back and its reading clears |
| `default_on_power` | state variable | after power-on it holds its documented default |
| `independent` | pair of controls | operating one doesn't change what the other drives (this catches a swapped or shorted channel) |
| `enable_holds` | `enables` relation | with the enabler off, the enabled control does nothing |
| `requirement_holds` | `requires` relation | without the requirement, the action is refused |
| `interlock_holds` | `interlocks` relation | with the guard open, the action is blocked and the message shows |
| `interlock_releases` | `interlocks` relation | with the guard satisfied, the action goes ahead |
| `displays_matches` | `displays` relation | the indicator shows the state's value in the manual's format |
| `message_documented` | indicator vocabulary | every message the device shows is in the manual, and the reverse |
| `accepts_object` | container and object | the object seats fully, and a sensed container reports it |
| `mechanism_range` | mechanism | it opens to its stated range, and rests where the manual says |
| `procedure_completes` | procedure | following the steps in order gives every stated effect |
| `matches_manual` | any claim | what the device does agrees with what the manual says it does |
| `reachable` | control | the arm can reach and operate it where the device stands |
| `needs_reposition` | control | it is out of reach where the device stands, and in reach after a stated move |
| `operable_under_rules` | control | it can be operated within the test's rules (for example a fingertip only, no pinch grip) |

Two rules apply across all of them:

- **Untested is not passed.** When a precondition fails, the properties behind it are blocked, not passed. For example, a dead power switch blocks every property of every control it enables. Once the blocking fault is fixed, they come back as tests to run. This is how mixed revisions are read: a fault masked in Rev A shows in a revision that fixes only the fault masking it.
- **Every verdict cites evidence:** a reading, a display text, a force trace, or an image. The manual is a claim, not evidence.

## 5. How a device is written in it

Every RAAV test device is a composition of these pieces, and [devices.md](devices.md) lists which pieces each one exercises. The same composition yields three things:

- **The device file** (`appliances/<id>/device.yaml`). Controls become `controls` and `bodies`, indicators become `display` and `light`, containers become wells with `rings`, state and relations become `firmware`, and mechanisms become hinged or sliding `bodies`.
- **The manual**, written from the pieces, relations and procedures as the designer intended them. It is written without knowing the faults.
- **The faults**, each a single break of one property on one piece. Rev B restores the property. [device-authoring.md](device-authoring.md) has the rules.

## 6. Integration note for WS3, to apply after round 2

This has not been wired in. When round 2 is done:

1. **Hypothesis stage.** After `read_manual` and the scan, have the model emit a `DeviceHypothesis`. Expose `theory.DeviceHypothesis.model_json_schema()` as a structured-output schema, or as a tool `record_hypothesis(hypothesis)` that validates with `DeviceHypothesis.model_validate`. Have the model record the source of each piece. A piece the manual names but the scan didn't find, or the reverse, is already a candidate `matches_manual` finding.
2. **Test derivation.** `theory.derive_tests(h)` turns a hypothesis into `TestIntent`s, one per property per applicable piece, relation or procedure, each with its preconditions and oracle. Give them to the model as a checklist to plan from, not as a plan. The model still writes the steps, and is free to add tests the templates don't suggest.
3. **Coverage.** `theory.coverage(intents, done)` takes the property ids the run has evidence for. It returns what was tested, what was blocked (and by which failed precondition) and what was untested. Put it in the report beside the existing coverage, and use it to decide whether to re-test after a fix.
4. **Prompts.** Add one paragraph naming the five relation kinds and the "untested is not passed" rule. The schema carries the rest.
5. **Boundaries.** Nothing in the theory may name a device or a fault. The answer keys stay in `build/` and are never imported by the harness.

None of this changes System 1 or the MCP tools.
