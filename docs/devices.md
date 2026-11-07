# Test devices

The simulated appliances RAAV is tested on. Each is its own CadQuery design with a manual, planted faults (Rev A) and
their fixes (Rev B), described in the vocabulary of [device-theory.md](device-theory.md). How they're built:
[device-authoring.md](device-authoring.md). This page is assembled from each device's `gallery.md` by
`system-1/sim/tools/build.py`; edit those (`appliances/<id>/gallery.md`), not this.

Splits: **dev** devices are for building and tuning, **validation** for checking that tuning generalises, and
**held-out** devices are only run for final results, so their faults are not described anywhere a model or a tuner reads.


## Dev

### MC-6 mini centrifuge (`centrifuge`), the reference device
**Split:** dev. **Revisions:** A, B, M1.

A benchtop mini centrifuge with a separate tube rack. You load a tube from the rack into well A, close the lid, set the time and speed, and run it. The display counts down, and the light ring shows the state.

**Controls:** POWER toggle; START, STOP and TIME+ buttons; SPEED dial; lid handle; rack cover lip; display and light ring; wells A and B; one tube.
**Theory pieces:** enables (power), interlocks (open lid blocks START, shown as `LID`), requires (a seated tube, shown as `TUBE`), drives (dial to speed, TIME+ to time), displays (speed and time; ring colour by mode), momentary and latching returns, two hinge mechanisms, a sensed container and an object, and a timed `running` mode.
**Faults:** F1 mechanical: STOP binds in its bezel and never closes its switch. F2 ergonomic: the lid handle is a pinch fin with no lip to hook. F3 mechanical: well A is too tight, so the tube sits high and isn't sensed. F3 is masked by F2 (the lid can't be opened), and M1 fixes F2 alone to unmask it.

### IT-90 lab interval timer (`interval-timer`)
**Split:** dev. **Revisions:** A, B, M1.

A benchtop lab countdown timer in a printed wedge case, with its controls on a sloped front panel and an `MM:SS` display below them. You switch it on, add minutes and seconds with +MIN and +SEC, then start, pause and resume with START/STOP until it shows `DONE` and the status light turns green.

**Controls:** POWER toggle; +MIN, +SEC and START/STOP buttons; display; status light.
**Theory pieces:** enables (power), drives (+MIN and +SEC to the set time), a mode state (ready, running, paused, done), displays (`MM:SS` and `DONE`; light colour by mode), a default on power (`00:00`), momentary and latching returns, a timed `running` mode, and a procedure (set, start, pause, resume, clear).
**Faults:** F1 manual: +SEC adds 10 s where the manual says 1 s. F2 firmware: START/STOP while counting resets to `00:00` instead of pausing. F3 mechanical: +MIN's cap bottoms out on its bezel before its switch closes. F4 firmware: times of 10 minutes and over drop the minutes' tens digit (`10:00` shows `00:00`). F4 is masked by F3 (10 minutes can't be set without +MIN), and M1 fixes F3 alone to unmask it.

### KB-1 temperature kettle (`kettle-base`)
**Split:** dev. **Revisions:** A, B, M1.

The power base and lid of a temperature-controlled kettle: a round jug with a back-hinged lid on a base whose sloped front panel holds the controls. You switch it on, lift the lid by its lip to fill and close it, set the temperature with the dial, optionally turn on keep-warm, and press BOIL; the display and heater ring show the setting, the heat, and the hold.

**Controls:** POWER toggle; BOIL and WARM buttons; TEMP dial (encoder); lid with a hook lip; display and heater ring light.
**Theory pieces:** enables (power), interlocks (open lid refuses BOIL, shown as `LID`), drives (dial to set temperature, 60 to 100 °C in 5 °C clicks; WARM to keep-warm), displays (setting, `BOILING`, `DONE`, `WARM 85C`; ring colour by mode), a default on power (100 °C, keep-warm off), a latching variable (keep-warm), momentary, latching and continuous returns, a hinge mechanism, and a timed `running` mode.
**Faults:** F1 firmware: powers on at 60 °C instead of 100 °C. F2 electrical: BOIL and WARM are wired to each other's inputs. F3 mechanical: the lid's hinge leaf bottoms early, so the lid won't seat, its switch never closes and BOIL is always refused with `LID`. F4 firmware: keep-warm never engages after a heat (it checks the WARM button, not the setting). F4 is masked by F3 (nothing heats), and M1 fixes F3 alone to unmask it.

### LP-40 thermal label printer (`label-printer`)
**Split:** dev. **Revisions:** A, B, M1.

A desktop printer for 40 mm direct-thermal labels, with the roll under a cover hinged at its back. You lift the cover by the lip on its front tab to load a roll, set the darkness on the dial, and press FEED or PRINT; the display shows the darkness and the labels printed, and the status light shows ready, printing or an error.

**Controls:** POWER toggle; FEED and PRINT buttons; DARKNESS dial; cover lip; display and status light.
**Theory pieces:** enables (power), interlocks (open cover blocks FEED and PRINT, shown as `COVER`), drives (dial to darkness 1 to 9, PRINT to the label count), displays (darkness and count; light colour by mode), momentary buttons, latching toggle, continuous dial, a hinged cover mechanism with a sensor, a power-on default (count 000), and a timed `running` mode.
**Faults:** F1 mechanical: FEED binds in its bezel and never closes its switch. F2 firmware: PRINT prints with the cover open instead of refusing with `COVER`. F3 ergonomic: the cover's lift tab sits 2 mm above the deck, too close to the body for a fingertip to get under it. F2 is masked by F3 (the cover can't be opened), and M1 fixes F3 alone to unmask it.

### HS-20 tube heat sealer (`tube-sealer`)
**Split:** dev. **Revisions:** A, B, M1, M2.

A benchtop sealer that heat-seals the cap of one sample tube, with a one-tube stand beside it. You lift the tube from the stand into the sealing slot, flip the CLAMP lever up, and press SEAL; the display counts down 5 seconds and shows `DONE`, and the status light goes white, amber, green (red on a refusal).

**Controls:** CLAMP lever (toggle), SEAL button, sealing slot (sensed), tube stand, one tube, display and status light. No power switch.
**Theory pieces:** requires (SEAL needs a seated tube, shown as `NO TUBE`, and the clamp closed, shown as `CLAMP`), a sensed container and an object (pick and place), a latching toggle that isn't power, a momentary button, displays (message and countdown; light colour by mode), a timed `running` mode, and two roots.
**Faults:** F1 firmware: SEAL runs with no tube in the slot (the tube check is missing). F2 mechanical: the slot's bore is too tight, so a tube stops high and isn't sensed. F3 ergonomic: the CLAMP lever's spring is too stiff for a fingertip push to throw. F1 is masked by F3: with the clamp stuck open, SEAL on an empty slot is refused with `CLAMP`, which the manual allows, so the missing tube check never shows. M1 fixes F3 alone to unmask it (the clamp closes, and SEAL then seals an empty slot); M2 has F1 alone.

### HT-20 room thermostat (`wall-thermostat`)
**Split:** dev. **Revisions:** A, B, M1.

A wall-mounted room thermostat on a desk stand, its face vertical and looking straight at the arm. You press MODE to step through OFF, HEAT and COOL, and UP and DOWN to set the temperature from 10.0 to 30.0 °C in half degrees; the display shows the mode and setpoint, and the status light shows orange for heat and blue for cool.

**Controls:** MODE, DOWN and UP buttons in a row along the top of a vertical face; display; status light. No power switch.
**Theory pieces:** drives (UP and DOWN to the setpoint, MODE to the mode), respects range (setpoint clamped at 10.0 and 30.0), displays (mode and setpoint; light colour by mode), a mode state, default on power (OFF, 20.0 °C), momentary buttons, and a vertical control face pressed with a level tool.
**Faults:** F1 mechanical: DOWN binds in its bezel and never closes its switch. F2 firmware: UP at 30.0 wraps the setpoint to 10.0. F3 firmware: MODE goes from HEAT straight to OFF, skipping COOL. F4 manual: in COOL the display shows the setpoint in Fahrenheit. F4 is masked by F3 (COOL is never reached), and M1 fixes F3 alone to unmask it.


## Validation

### CR-600 cuvette photometer (`cuvette-reader`)
**Split:** validation. **Revisions:** A, B, M1.

A single-wavelength (600 nm) photometer for square cuvettes. You move the cuvette from its side holder into a slot in a well under a hinged lid, close the lid, press BLANK once per session, then READ for the absorbance on the display.

**Controls:** POWER toggle; BLANK and READ buttons; lid with a hook lip; display and status light; a sensed sample slot and an unsensed side holder; one square cuvette.
**Theory pieces:** enables (power), interlocks (open lid blocks BLANK and READ, shown as `LID`), requires (a seated cuvette, shown as `NO SAMPLE`; a blank earlier in the session, shown as `BLANK FIRST`), a precondition held in state (blanked, a session variable that defaults to 0 at power-on and clears at power-off), displays (messages and the absorbance; light colour by mode), momentary and latching returns, a hinge mechanism, a sensed container and a square object, timed `after:` modes, and the blank-then-read procedure.
**Faults:** F1 firmware: READ gives a reading without a BLANK. F2 mechanical: the lid stands proud on an oversized hinge leaf, so its switch never closes and BLANK and READ always show `LID`. F3 mechanical: the slot is too tight, so the cuvette stands high and isn't sensed. F4 electrical: BLANK and READ are wired to each other's inputs. F1 is masked by F2 (nothing measures with the lid reading open), and M1 fixes F2 alone to unmask it.

### MI-45 mini incubator (`incubator`)
**Split:** validation. **Revisions:** A, B, M1, M2.

A small benchtop incubator with a windowed chamber door that lifts on a hinge at the back. You switch it on, set the temperature with TEMP+ and TEMP− in half degrees, and open the door by its front lip; leave it open 5 s and it shows `DOOR` with a red light.

**Controls:** POWER toggle; TEMP+ and TEMP− buttons; chamber door with a pull lip; display and status light.
**Theory pieces:** enables (power), drives (TEMP± to the set temperature, 25.0 to 45.0 in 0.5 steps), displays (set temperature; light colour by mode), default on power (37.0), momentary and latching returns, a hinge mechanism with a stated range (opens to 90° and rests open), an `after:` timed alarm (`DOOR` after 5 s open), a message vocabulary (`SET nn.nC`, `DOOR`).
**Faults:** F1 mechanical: the door's hinge check stops it at 40°, short of the 90° in the manual, and it falls shut. F2 firmware: the door alarm never fires. F3 manual: TEMP+ and TEMP− step 1.0 °C where the manual says 0.5. F4 ergonomic: the pull lip is on the hinge edge, so the door can't be hooked open. F4 masks F1 and F2, and F1 masks F2 (a door that falls shut can't stay open 5 s); M1 fixes F4 alone to unmask F1, and M2 fixes F4 and F1 to unmask F2.

### VM-3 touch vortex mixer (`vortex-mixer`)
**Split:** validation. **Revisions:** A, B, M1.

A benchtop touch vortex mixer with a cup head on top and a sample cup in a holder on its side. You set the speed, move the cup into the head, and either press START (ON mode) or let the seated cup start the head itself (TOUCH mode); the display shows the mode and set speed, and the head's rpm while mixing.

**Controls:** MODE toggle; START button; SPEED dial; display; cup head (sensed well) and side holder; one sample cup.
**Theory pieces:** requires (START needs a seated cup, shown as `CUP`), drives (dial to speed, 500 to 3000 rpm clockwise), respects range (the speed's ends), a latching mode toggle (up TOUCH, down ON) that changes what starts a run, displays (mode and set speed; rpm while mixing), a momentary button, a sensed container and an object.
**Faults:** F1 mechanical: the cup head's bore is too tight, so the cup sits high and isn't sensed. F2 firmware: the head tops out at 2500 rpm while the dial sets and shows 3000. F3 manual: MODE up selects ON and down TOUCH, the reverse of the manual. F2 is masked by F1 (nothing runs without a sensed cup), and M1 fixes F1 alone to unmask it.


## Held-out

### BG-12 burr coffee grinder (`coffee-grinder`)
**Split:** held-out. **Revisions:** A, B, M1.

A compact countertop burr grinder with a bean hopper under a hinged lid. You fill the hopper, close the lid, set the grind and the time on two dials, and press START. The display counts down the grind.

**Controls:** POWER toggle; START button; GRIND and TIME dials; hopper lid with a front lip; display.
**Theory pieces:** enables (power), interlocks (an open lid blocks START and stops a grind, shown as `LID`), drives (GRIND dial to grind setting, TIME dial to grind time), displays (setting and time, then a countdown), momentary and latching returns, continuous dials, a hinge mechanism, a timed `running` mode, and reach and repositioning.
**Faults:** held out.

### HPS-300 hotplate stirrer (`hotplate-stirrer`)
**Split:** held-out. **Revisions:** A, B, M1.

A benchtop hotplate stirrer with a raised control console and a beaker rest beside it. You seat the beaker in the cradle in the centre of the plate, then set the temperature and the stirring speed with two dials; a red HOT light warns while the plate is hot, even after switching off.

**Controls:** POWER toggle; HEAT and STIR dials; plate cradle (sensed) and beaker rest; one beaker; display and HOT light.
**Theory pieces:** enables (power), requires (a seated beaker for heating and stirring, shown as `NO VESSEL`), two drives side by side (HEAT to set temperature, STIR to set speed), displays (both settings; HOT light), state that outlives power (HOT stays lit through a power cycle until the plate cools), a timed `after:` cooling mode, latching and continuous returns, a sensed container and an object.
**Faults:** held out.
