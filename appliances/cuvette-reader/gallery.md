### CR-600 cuvette photometer (`cuvette-reader`)
**Split:** validation. **Revisions:** A, B, M1.

A single-wavelength (600 nm) photometer for square cuvettes. You move the cuvette from its side holder into a slot in a well under a hinged lid, close the lid, press BLANK once per session, then READ for the absorbance on the display.

**Controls:** POWER toggle; BLANK and READ buttons; lid with a hook lip; display and status light; a sensed sample slot and an unsensed side holder; one square cuvette.
**Theory pieces:** enables (power), interlocks (open lid blocks BLANK and READ, shown as `LID`), requires (a seated cuvette, shown as `NO SAMPLE`; a blank earlier in the session, shown as `BLANK FIRST`), a precondition held in state (blanked, a session variable that defaults to 0 at power-on and clears at power-off), displays (messages and the absorbance; light colour by mode), momentary and latching returns, a hinge mechanism, a sensed container and a square object, timed `after:` modes, and the blank-then-read procedure.
**Faults:** F1 firmware: READ gives a reading without a BLANK. F2 mechanical: the lid stands proud on an oversized hinge leaf, so its switch never closes and BLANK and READ always show `LID`. F3 mechanical: the slot is too tight, so the cuvette stands high and isn't sensed. F4 electrical: BLANK and READ are wired to each other's inputs. F1 is masked by F2 (nothing measures with the lid reading open), and M1 fixes F2 alone to unmask it.
