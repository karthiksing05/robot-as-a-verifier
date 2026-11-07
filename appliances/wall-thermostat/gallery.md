### HT-20 room thermostat (`wall-thermostat`)
**Split:** dev. **Revisions:** A, B, M1.

A wall-mounted room thermostat on a desk stand, its face vertical and looking straight at the arm. You press MODE to step through OFF, HEAT and COOL, and UP and DOWN to set the temperature from 10.0 to 30.0 °C in half degrees; the display shows the mode and setpoint, and the status light shows orange for heat and blue for cool.

**Controls:** MODE, DOWN and UP buttons in a row along the top of a vertical face; display; status light. No power switch.
**Theory pieces:** drives (UP and DOWN to the setpoint, MODE to the mode), respects range (setpoint clamped at 10.0 and 30.0), displays (mode and setpoint; light colour by mode), a mode state, default on power (OFF, 20.0 °C), momentary buttons, and a vertical control face pressed with a level tool.
**Faults:** F1 mechanical: DOWN binds in its bezel and never closes its switch. F2 firmware: UP at 30.0 wraps the setpoint to 10.0. F3 firmware: MODE goes from HEAT straight to OFF, skipping COOL. F4 manual: in COOL the display shows the setpoint in Fahrenheit. F4 is masked by F3 (COOL is never reached), and M1 fixes F3 alone to unmask it.
