### MW-1 mock microwave (`microwave`)
**Split:** dev. **Revisions:** A, B.

A mock countertop microwave (Arduino Uno, Grove LCD and buzzer, plywood and acrylic box) with a door hinged on its left and a D-handle, on an 80 mm riser for the arm. You pull the door open past its snap latch, close it to a click, set the time with TIME or +30s and the power with POWER, and press START; the display counts down in amber and shows `DONE` in green.

**Controls:** TIME, POWER, STOP, +30s and START buttons; door handle (vertical hinge, about 130-145°); 16 x 2 display with a coloured backlight. No power switch.
**Theory pieces:** interlocks (an open door refuses START and +30s, shown as `CLOSE DOOR`, and pauses a cook, shown as `DOOR OPEN`), requires (a set time, shown as `SET TIME`), drives (TIME and +30s to the time, POWER to the level), displays (time and level; backlight by mode), a mode state (ready, set, cooking, paused, door open, done), a timed `running` mode and a timed return from `done`, momentary buttons, a door on a vertical hinge with a snap latch and a sensor, and a buzzer.
**Faults:** F1 mechanical: the door hinges are printed with 0.025 mm clearances, so they fuse and the door is seized.
