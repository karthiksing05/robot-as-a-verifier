### LP-40 thermal label printer (`label-printer`)
**Split:** dev. **Revisions:** A, B, M1.

A desktop printer for 40 mm direct-thermal labels, with the roll under a cover hinged at its back. You lift the cover by the lip on its front tab to load a roll, set the darkness on the dial, and press FEED or PRINT; the display shows the darkness and the labels printed, and the status light shows ready, printing or an error.

**Controls:** POWER toggle; FEED and PRINT buttons; DARKNESS dial; cover lip; display and status light.
**Theory pieces:** enables (power), interlocks (open cover blocks FEED and PRINT, shown as `COVER`), drives (dial to darkness 1 to 9, PRINT to the label count), displays (darkness and count; light colour by mode), momentary buttons, latching toggle, continuous dial, a hinged cover mechanism with a sensor, a power-on default (count 000), and a timed `running` mode.
**Faults:** F1 mechanical: FEED binds in its bezel and never closes its switch. F2 firmware: PRINT prints with the cover open instead of refusing with `COVER`. F3 ergonomic: the cover's lift tab sits 2 mm above the deck, too close to the body for a fingertip to get under it. F2 is masked by F3 (the cover can't be opened), and M1 fixes F3 alone to unmask it.
