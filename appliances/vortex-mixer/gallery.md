### VM-3 touch vortex mixer (`vortex-mixer`)
**Split:** validation. **Revisions:** A, B, M1.

A benchtop touch vortex mixer with a cup head on top and a sample cup in a holder on its side. You set the speed, move the cup into the head, and either press START (ON mode) or let the seated cup start the head itself (TOUCH mode); the display shows the mode and set speed, and the head's rpm while mixing.

**Controls:** MODE toggle; START button; SPEED dial; display; cup head (sensed well) and side holder; one sample cup.
**Theory pieces:** requires (START needs a seated cup, shown as `CUP`), drives (dial to speed, 500 to 3000 rpm clockwise), respects range (the speed's ends), a latching mode toggle (up TOUCH, down ON) that changes what starts a run, displays (mode and set speed; rpm while mixing), a momentary button, a sensed container and an object.
**Faults:** F1 mechanical: the cup head's bore is too tight, so the cup sits high and isn't sensed. F2 firmware: the head tops out at 2500 rpm while the dial sets and shows 3000. F3 manual: MODE up selects ON and down TOUCH, the reverse of the manual. F2 is masked by F1 (nothing runs without a sensed cup), and M1 fixes F1 alone to unmask it.
