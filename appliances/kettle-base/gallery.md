### KB-1 temperature kettle (`kettle-base`)
**Split:** dev. **Revisions:** A, B, M1.

The power base and lid of a temperature-controlled kettle: a round jug with a back-hinged lid on a base whose sloped front panel holds the controls. You switch it on, lift the lid by its lip to fill and close it, set the temperature with the dial, optionally turn on keep-warm, and press BOIL; the display and heater ring show the setting, the heat, and the hold.

**Controls:** POWER toggle; BOIL and WARM buttons; TEMP dial (encoder); lid with a hook lip; display and heater ring light.
**Theory pieces:** enables (power), interlocks (open lid refuses BOIL, shown as `LID`), drives (dial to set temperature, 60 to 100 °C in 5 °C clicks; WARM to keep-warm), displays (setting, `BOILING`, `DONE`, `WARM 85C`; ring colour by mode), a default on power (100 °C, keep-warm off), a latching variable (keep-warm), momentary, latching and continuous returns, a hinge mechanism, and a timed `running` mode.
**Faults:** F1 firmware: powers on at 60 °C instead of 100 °C. F2 electrical: BOIL and WARM are wired to each other's inputs. F3 mechanical: the lid's hinge leaf bottoms early, so the lid won't seat, its switch never closes and BOIL is always refused with `LID`. F4 firmware: keep-warm never engages after a heat (it checks the WARM button, not the setting). F4 is masked by F3 (nothing heats), and M1 fixes F3 alone to unmask it.
