# Test subjects

The products the robot tests. Owner: Max. One folder per product:

| Folder | Holds |
|---|---|
| `project.json` | The Console's record of this product: name, what it is, and the product names its runs use |
| `cad/` | The parametric model (`appliance.py`, CadQuery) and its parameters, one file per revision |
| `manual/` | The manual as a PDF for the demo and plain text for parsing |
| `firmware/` | The ground-truth Pico: reports switches and LCD text over serial, kept separate from the test rig. In [`system-1/subjects`](../../system-1/subjects/appliance/firmware), because it's a sensor System 1 reads |

## [`appliance/`](appliance): the main demo

A box of about 120 × 160 × 180 mm with three buttons, an LCD and a hinged door. [`params.rev_a.json`](appliance/cad/params.rev_a.json) has the two planted faults, `button_clearance[1]` and `handle_style`. The backup-fault parameters are at their good values; set one to its fault value to use it:

| Backup fault | Good | Fault |
|---|---|---|
| `latch_overlap` | 0.8 mm | 0.2 mm |
| `lcd_tilt` | 15° | 0° |
| `dome_preload[2]` (button 3) | 0.3 mm | 0 mm |

Design rules from the reach test: put the buttons and latch on a slope of about 45°, 0 to 15 cm above the arm base and 0.22 to 0.30 m in front of it. The shell prints once; button bezels, door handle and latch are inserts, so a patch reprints in 15 to 40 minutes.

Don't confuse `system-1/sim/appliance.py` with this: that's the sim's older parametric appliance, and it isn't printed.

## Manual format

Per control: name, where it is, how to operate it, what should happen (light, LCD text, click, part moves), and any limits. Write it the way a real appliance manual reads. Plant one deliberate mismatch, such as saying the door opens with a push, so the report can flag it. Ideally someone who doesn't know which button is rigged writes it.

## [`remote-receiver/`](remote-receiver): the reach goal

The same three folders, once its controls are decided.
