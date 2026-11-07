### MI-45 mini incubator (`incubator`)
**Split:** validation. **Revisions:** A, B, M1, M2.

A small benchtop incubator with a windowed chamber door that lifts on a hinge at the back. You switch it on, set the temperature with TEMP+ and TEMP− in half degrees, and open the door by its front lip; leave it open 5 s and it shows `DOOR` with a red light.

**Controls:** POWER toggle; TEMP+ and TEMP− buttons; chamber door with a pull lip; display and status light.
**Theory pieces:** enables (power), drives (TEMP± to the set temperature, 25.0 to 45.0 in 0.5 steps), displays (set temperature; light colour by mode), default on power (37.0), momentary and latching returns, a hinge mechanism with a stated range (opens to 90° and rests open), an `after:` timed alarm (`DOOR` after 5 s open), a message vocabulary (`SET nn.nC`, `DOOR`).
**Faults:** F1 mechanical: the door's hinge check stops it at 40°, short of the 90° in the manual, and it falls shut. F2 firmware: the door alarm never fires. F3 manual: TEMP+ and TEMP− step 1.0 °C where the manual says 0.5. F4 ergonomic: the pull lip is on the hinge edge, so the door can't be hooked open. F4 masks F1 and F2, and F1 masks F2 (a door that falls shut can't stay open 5 s); M1 fixes F4 alone to unmask F1, and M2 fixes F4 and F1 to unmask F2.
