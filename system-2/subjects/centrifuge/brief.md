# MC-6 mini centrifuge: what the team knows going in

The design brief (v5) with everything about the planted faults removed: the fault table, the coupon, the swap sequence and every Rev B detail. This is what a team would have for any product it brings, and it is the only source the tag file (`onshape.yaml`) and the simulated run (`simulated_run.py`) may draw on. The CAD is the Rev A model in Onshape.

## Purpose

A mock benchtop mini centrifuge, a tube rack and printed test tubes. An SO-101 arm uses them like a lab tech: it opens doors, moves a tube from the rack into the centrifuge, presses buttons, flips the power switch, turns the speed dial, and reads the display and lights. Nothing spins and nothing holds liquid.

## Frames and units

- mm throughout.
- Product frame: origin at the centre of the centrifuge base's bottom face, +X toward the arm, +Z up.
- Arm frame: origin on the pan axis at riser height. Pan angle 0 = straight at the centrifuge; positive = toward product +Y.

## Hard rules

1. No two solids may share any volume (threshold 1e-6 mm³), including hinge pins and the placeholder electronics. No press fits anywhere.
2. Every motion and assembly path must be collision-free: lid and rack cover through 0–105°, dial through 270°, each bayonet through its 45° twist, each insert along its removal path, a tube lowered into well A (lid open) and lifted out of the rack (cover open).
3. Laser parts never change between revisions; only printed parts do.
4. Swap inserts are slip fits with positive retention, no tools: stop bezel and well inserts are quarter-turn bayonets; the lid handle is a keyhole slide-lock.

## How it is made

- Laser-cut where flat: 3 mm plywood or MDF (body, rack); clear 3 mm acrylic (lid, rotor plate, rack cover). Tab-and-slot joints.
- Printed only where 3D shape or fine tolerance is needed: PLA, 0.4 mm nozzle, 0.2 mm layers, 2 walls, 10–15 % infill, no supports. Minimum printed wall 1.2 mm; every printed part is one valid solid and fits a 220 × 220 bed.

## Centrifuge body

- 125 W × 120 D × 94 H. Wedge shape; open back.
- Control face: 45° plate, 131 mm wide. Five controls in one row at Y = −45 (power toggle), −22.86 (Start), 0 (Stop), +22.86 (Time+), +45 (speed dial). Engraved labels and an 11-tick dial scale.
- Front panel: OLED window ("MC-6 MINI CENTRIFUGE").
- Rotor plate: clear acrylic over a NeoPixel ring; bayonet holes for wells A (Y −13) and B (Y +13) at bowl centre X −21.
- Top panel: 60 mm opening over the rotor; pocket for the lid-sensor tab block.
- Lid: clear acrylic on a printed hinge block and leaf with a 1.75 mm filament pin. Closes under its own weight; opens to 105° onto a printed stop. A lid sensor tab at the front-left corner, arc-shaped about the hinge axis, interrupts a MOC7811 when closed.

## Buttons

12 mm tactile switches on the breadboard. Each has a printed cap captive in a printed bezel (16 mm sleeve, 20 mm × 2 mm flange, bayonet ears). Travel is the switch's own ~0.25 mm (no springs).

## Dial

WH148 pot with a D shaft. Printed knob 10 mm wide × 11 mm tall with a 3 mm fin to 9 mm radius. Sweep 270° = 1000–6000 rpm.

## Test tube (printed, 2 off)

16 mm OD, 55 mm from collar top to nub tip, 1.6 mm wall. Collar 22 mm OD with a 45° underside. 7 mm straight section, then a cone to an 8.5 mm long, 4 mm nub that passes through the tube sensor's beam. 8 mm-ID loop on top.

## Wells and rack

Well inserts: 20 mm OD sleeve, 22.5 mm flange, 1 mm top chamfer, quarter-turn bayonet. The same insert is used in the centrifuge and the rack (4 wells, 24 mm pitch, clear flip-up cover with a printed hook lip, opens onto a 105° stop).

## Electronics

| Part | Pico pin | Serial event |
|---|---|---|
| Start | GP2 | `btn_start` |
| Stop | GP3 | `btn_stop` |
| Time+ | GP4 | `btn_time` |
| Power toggle | GP5 (ON = LOW) | `power` |
| Pot wiper | GP26 / ADC0 | `speed` |
| OLED | I2C0 (0x3C) | shows state and errors (e.g. `LID`, `TUBE`) |
| MOC7811 lid | GP6 | `lid` |
| MOC7811 tube | GP7 | `tube` |

Serial: one JSON object per line at 115200 baud, e.g. `{"t":..,"ev":..,"v":..}`. Start refuses to run with the lid open (`LID`) or no tube in well A (`TUBE`).

## Arm and reach

Pan axis 274.5 mm in front of the centrifuge centre; riser 58 mm. Zones: pick-and-place 140–300 mm; 45° press 220–340 mm, −50 to +150 mm in height. Hook pull is checked against the 45° zone but has not been tested on the arm.
