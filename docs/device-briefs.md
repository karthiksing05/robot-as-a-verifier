# Device briefs

Ten RAAV test devices, one per builder. Each brief gives the product, the theory pieces it must exercise ([device-theory.md](device-theory.md)), its planned faults by class, and its split. How to build one is in [device-authoring.md](device-authoring.md). The reference device is the centrifuge, at `appliances/centrifuge/`.

| Split | Devices | Used for |
|---|---|---|
| dev | label-printer, kettle-base, wall-thermostat, tube-sealer, interval-timer (and the centrifuge) | building and tuning |
| validation | vortex-mixer, incubator, cuvette-reader | checking that tuning generalises |
| held-out | coffee-grinder, hotplate-stirrer | final results only |

The held-out devices' fault plans are not in this file. They are in `appliances/HELDOUT_BRIEFS.md`, which is gitignored. Only those two builders read it.

**Freedom and limits.** A builder may substitute a fault, as long as the substitute keeps the same class and the same theory property, if the physics won't cooperate. Report every substitution. Controls are limited to the kinds the loader supports: button, dial, toggle, handle (hinged lid, cover or door), display, light, well, object.

**Firmware faults.** Faults marked ⚑ need firmware parameters, which wait on a one-line loader change requested from WS2 (device-authoring.md, section 4). Build and verify everything else first, and mark those faults "not verified: waiting on firmware params" until it lands.

## Dev

### 1. Thermal label printer (`label-printer`)

A desktop printer for 40 mm labels, with a hinged cover over the roll.

- **Controls:**
  - POWER toggle
  - FEED button: advances one blank label
  - PRINT button: prints a label, taking 3 s in the `running` state
  - DARKNESS dial: 1 to 9, clockwise darker
  - cover with a front lip
- **Display:** darkness and label count
- **Light:** white when ready, blue while printing, red on error
- **Message:** with the cover open, PRINT and FEED show `COVER`

**Pieces:** enables (power), interlocks (cover), drives (dial to darkness, PRINT to count), displays, momentary buttons, a hinge mechanism, a timed mode.

**Faults:**

| ID | Class | Fault | Property |
|---|---|---|---|
| F1 | mechanical | FEED's cap binds and never closes its switch | actuates |
| F2 | firmware ⚑ | PRINT runs with the cover open | interlock_holds |
| F3 | ergonomic | the cover's lip sits too close to the body for a fingertip to get under it | operable_under_rules |

F3 masks F2, because the cover can't be opened. Add a mixed revision M1 with only F3 fixed.

### 2. Kettle power base (`kettle-base`)

The base and lid unit of a temperature-controlled kettle.

- **Controls:**
  - POWER toggle
  - BOIL button: heats to the setpoint, taking 8 s in `running`, then holds if WARM is on
  - WARM button: toggles keep-warm
  - TEMP dial: 60 to 100 °C in steps of 5
  - hinged lid with a lip
- **Display:** the setpoint, then `BOILING` and `DONE`
- **Startup:** at power-on the setpoint is 100 °C
- **Message:** an open lid refuses BOIL with `LID`

**Pieces:** enables, interlocks (lid), drives (dial to setpoint), displays, a default on power, a latching variable (warm), a hinge mechanism, a timed mode.

**Faults:**

| ID | Class | Fault | Property |
|---|---|---|---|
| F1 | firmware ⚑ | power-on setpoint is 60 °C | default_on_power |
| F2 | electrical | BOIL and WARM are wired to each other's channels; express it as swapped body names | independent |
| F3 | mechanical | the lid won't seat, so the lid switch never closes and BOIL is always refused | interlock_releases |
| F4 | firmware ⚑ | keep-warm never engages after a boil | procedure_completes |

F3 masks F4. Add M1 with only F3 fixed.

### 3. Wall thermostat (`wall-thermostat`)

A wall-mounted room thermostat on a short pedestal. This is the one **vertical control face** in the set: the controls face the arm horizontally. Check reach early, and if the press can't reach, tilt the face back up to 20° and say so.

- **Controls:**
  - UP, DOWN and MODE buttons. The setpoint runs 10 to 30 °C in steps of 0.5, and MODE cycles OFF, HEAT, COOL.
  - no power switch: it is always on
- **Display:** mode and setpoint in °C
- **Light:** off, orange (heat) or blue (cool)

**Pieces:** drives (buttons to setpoint and mode), respects range (clamped ends), displays, a mode state, a default on power, momentary buttons.

**Faults:**

| ID | Class | Fault | Property |
|---|---|---|---|
| F1 | mechanical | DOWN binds | actuates |
| F2 | firmware ⚑ | UP past 30 wraps to 10 | respects_range |
| F3 | firmware ⚑ | MODE skips COOL | matches_manual |
| F4 | manual ⚑ | in COOL the display shows °F | displays_matches |

F3 masks F4. Add M1 with only F3 fixed.

### 4. Tube heat sealer (`tube-sealer`)

Seals the cap of a sample tube.

- **Two roots:**
  - the sealer: a sensed sealing slot, a CLAMP lever (toggle) that closes the jaws, a SEAL button, a display and a light
  - a small stand holding one tube
- **SEAL** requires a seated tube and the clamp closed, then runs 5 s. The messages are `NO TUBE`, `CLAMP`, `SEALING` and `DONE`.

**Pieces:** requires (tube, clamp), a sensed container, an object, a latching toggle that isn't power, displays, a timed mode, pick and place.

**Faults:**

| ID | Class | Fault | Property |
|---|---|---|---|
| F1 | firmware ⚑ | SEAL runs with no tube | requirement_holds |
| F2 | mechanical | the slot bore is too tight: the tube stops high and isn't sensed | accepts_object |
| F3 | ergonomic | the clamp's snap is too stiff for the arm to throw | actuates |

F2 masks F1. Add M1 with only F2 fixed. A test with no tube still shows F1, so also add M2 = F1 only, and note in the gallery that F1 is visible without a tube.

### 5. Interval timer (`interval-timer`)

A lab countdown timer. It is a **state-machine** device: there are no mechanisms beyond buttons.

- **Controls:**
  - POWER toggle
  - +MIN and +SEC buttons
  - START/STOP button: start, pause, resume
- **Display:** `MM:SS`, then `DONE`
- **Light:** blue while running, green when done

**Pieces:** enables, drives (buttons to time), a mode state with run, pause and done, displays, a timed `running` mode, procedure.

**Faults:**

| ID | Class | Fault | Property |
|---|---|---|---|
| F1 | manual ⚑ | +SEC adds 10 s, where the manual says 1 s | mapping_matches |
| F2 | firmware ⚑ | STOP while running resets to 0:00 instead of pausing | procedure_completes |
| F3 | mechanical | +MIN's travel ends before its switch | actuates |
| F4 | firmware ⚑ | times of 10 minutes and over display wrong | displays_matches |

F3 masks F4, because 10 minutes is out of practical reach without +MIN. Add M1 with only F3 fixed.

## Validation

### 6. Vortex mixer (`vortex-mixer`)

A touch vortex mixer.

- **Controls:**
  - a sensed cup cradle (well) on top, with one sample cup (object) in a side holder
  - SPEED dial: 500 to 3000 rpm
  - MODE toggle: up is TOUCH, down is ON
  - START button
- **Display:** rpm while running. START with no cup shows `CUP`.

**Pieces:** requires (cup), drives (dial), respects range, a latching mode toggle, a sensed container, an object, displays.

**Faults:**

| ID | Class | Fault | Property |
|---|---|---|---|
| F1 | mechanical | the cradle is too tight, so the cup sits high and isn't sensed | accepts_object |
| F2 | firmware ⚑ | speed tops out at 2500 | respects_range |
| F3 | manual ⚑ | toggle up is ON | matches_manual |

F1 masks F2, because nothing runs without a cup. Add M1 with only F1 fixed.

### 7. Mini incubator (`incubator`)

A small benchtop incubator. Its front door is on a **vertical hinge**, which is new for hook_pull. If hook_pull can't swing a vertical-hinge door in the sim, change it to a top-hinged flap and report that as a skill gap.

- **Controls:**
  - POWER toggle
  - TEMP+ and TEMP− buttons: 25 to 45 °C in steps of 0.5
  - the door, with a lip handle
- **Display:** the setpoint
- **Light:** green normally, red with `DOOR` once the door has been open 5 s

**Pieces:** enables, drives, displays, an `after:` timed alarm, a hinge mechanism with a stated range, a message vocabulary.

**Faults:**

| ID | Class | Fault | Property |
|---|---|---|---|
| F1 | mechanical | the door stops at 40°, where the manual says 90° | mechanism_range |
| F2 | firmware ⚑ | the door alarm never fires | message_documented |
| F3 | manual ⚑ | TEMP steps are 1.0 | mapping_matches |
| F4 | ergonomic | the handle is on the hinge side, so the door can't be pulled open | operable_under_rules |

F4 masks F1 and F2. Add M1 with only F4 fixed.

### 8. Cuvette photometer (`cuvette-reader`)

A single-wavelength photometer.

- **Controls:**
  - POWER toggle
  - a square cuvette (object) in a side holder
  - a sensed sample slot under a hinged lid
  - BLANK and READ buttons
- **READ** needs a BLANK earlier in the session, a cuvette in the slot, and the lid shut. The messages are `BLANK FIRST`, `LID`, `NO SAMPLE` and `A=0.42`.

**Pieces:** a precondition held in state (blanked), requires, interlocks, a session variable with a default, a sensed container, a square object, a hinge, a procedure.

**Faults:**

| ID | Class | Fault | Property |
|---|---|---|---|
| F1 | firmware ⚑ | READ works without a BLANK | requirement_holds |
| F2 | mechanical | the lid stands proud on an oversized hinge leaf, so the lid switch never closes | interlock_releases |
| F3 | mechanical | the slot is too tight for the cuvette | accepts_object |

F2 masks F1. Add M1 with only F2 fixed.

## Held-out

### 9. Burr coffee grinder (`coffee-grinder`)

A countertop burr grinder.

- **Controls:**
  - POWER toggle
  - START button
  - a GRIND dial (fine to coarse)
  - a TIME dial (5 to 30 s)
  - a hinged hopper lid with a lip
- **Display:** grind setting and time, then a countdown

**Pieces:** enables, interlocks, drives (two dials), displays, a hinge, a timed mode, and at least one control placed to test reach and repositioning.

**Faults:** held out. Three or four of them, with a masked one and a mixed revision.

### 10. Hotplate stirrer (`hotplate-stirrer`)

A hotplate with a magnetic stirrer.

- **Controls:**
  - POWER toggle
  - HEAT dial and STIR dial
  - a sensed plate cradle (well), with one beaker (object) beside it
- **HEAT** refuses with no vessel (`NO VESSEL`).
- **Display:** alternates temperature and rpm
- **Light:** a `HOT` warning stays lit after power-off until the plate cools

**Pieces:** two drives relations side by side, requires, a sensed container, an object, displays, state that outlives power, a timed or `after:` mode.

**Faults:** held out. Three or four of them, with a masked one and a mixed revision.

## Coverage

Columns 1 to 10 are the briefs above in order: 1 label-printer, 2 kettle-base, 3 wall-thermostat, 4 tube-sealer, 5 interval-timer, 6 vortex-mixer, 7 incubator, 8 cuvette-reader, 9 coffee-grinder, 10 hotplate-stirrer. C is the centrifuge.

| Theory piece | C | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| press | x | x | x | x | x | x | x | x | x | x | |
| turn | x | x | x | | | | x | | | x | x |
| flip | x | x | x | | x | x | x | x | x | x | x |
| hook_pull | x | x | x | | | | | x | x | x | |
| pick / place | x | | | | x | | x | | x | | x |
| text display / light | x | x | x | x | x | x | x | x | x | x | x |
| enables | x | x | x | | | x | | x | x | x | x |
| requires | x | | | | x | | x | | x | | x |
| interlocks | x | x | x | | | | | | x | x | |
| drives | x | x | x | x | | x | x | x | | x | x |
| default on power | | | x | x | | | | | x | | x |
| timed mode | x | x | x | | x | x | | x | | x | x |
| vertical face or hinge | | | | x | | | | x | | | |
| reach or reposition | | | | | | | | | | x | |

Every device has at least one masked fault and a mixed revision. Across the set, every fault class appears at least twice.
