### IT-90 lab interval timer (`interval-timer`)
**Split:** dev. **Revisions:** A, B, M1.

A benchtop lab countdown timer in a printed wedge case, with its controls on a sloped front panel and an `MM:SS` display below them. You switch it on, add minutes and seconds with +MIN and +SEC, then start, pause and resume with START/STOP until it shows `DONE` and the status light turns green.

**Controls:** POWER toggle; +MIN, +SEC and START/STOP buttons; display; status light.
**Theory pieces:** enables (power), drives (+MIN and +SEC to the set time), a mode state (ready, running, paused, done), displays (`MM:SS` and `DONE`; light colour by mode), a default on power (`00:00`), momentary and latching returns, a timed `running` mode, and a procedure (set, start, pause, resume, clear).
**Faults:** F1 manual: +SEC adds 10 s where the manual says 1 s. F2 firmware: START/STOP while counting resets to `00:00` instead of pausing. F3 mechanical: +MIN's cap bottoms out on its bezel before its switch closes. F4 firmware: times of 10 minutes and over drop the minutes' tens digit (`10:00` shows `00:00`). F4 is masked by F3 (10 minutes can't be set without +MIN), and M1 fixes F3 alone to unmask it.
