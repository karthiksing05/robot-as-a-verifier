# CAD folder: MC-6 mini centrifuge + MC-R4 tube rack (Rev A and Rev B)

Units: mm. Product frame: origin at the centre of the centrifuge base's bottom face, +X toward the arm, +Z up.
Checked before export: no two parts share any volume in Rev A, Rev B, or any mix of the two. Every motion and swap path is collision-free (`05_reference/feasibility.json`).

## Folders
| Folder | What | Use |
|---|---|---|
| `01_assemblies/` | `centrifuge_revA`, `centrifuge_revB`, `tube_rack`, `full_rig_revA`, `full_rig_revB` (centrifuge and rack placed where the arm expects them) | Import into Onshape as assemblies |
| `02_part_studios/` | Parts grouped by how they're made: `PS1` centrifuge laser panels; `PS2` fixed parts (printed hinge, laser cap stacks, knob, sensor fin, risers, pin); `PS3a` Rev A fault parts; `PS3b` Rev B fixes; `PS4` rack laser panels; `PS5` rack hinge, lip and tube; `PS6` electronics placeholders | One Part Studio each, all in installed position |
| `03_parts/laser_flat/` | Every laser part and every ply of the glued stacks, flat (`__xN` = cut N) | Edit, then re-export DXF |
| `03_parts/printed_revA_revB/` | The 12 printed parts in their own frames (Stop bezels 0.05 / 0.15 / 0.40, Stop cap, well A inserts A and B, hinge base and leaf, tube) | Single parts |
| `03_parts/printed_in_place/` | Each non-flat part where it sits in the assembly | Single parts |
| `04_laser_sketches_dxf/` | One DXF per laser part or ply, nominal size (no kerf), real arcs | Import into a sketch, extrude 3 mm |
| `05_reference/` | `appliance.py` (the parametric source), `PARAMS.csv`, `features.json` (robot targets), `patch_revB.yaml`, `MATES.md`, cut and print list, wiring, manual text, check reports | Reading |

## Fault parts (Rev A orange, Rev B green)
- **F1 Stop button:** printed bayonet bezel and captive printed cap (Rev A 0.05 or 0.15 mm/side, Rev B 0.40).
- **F2 Lid handle:** laser 3-ply laminate with J-tabs. Rev A has a pinch fin, Rev B a hook lip.
- **F3 Well A:** printed bayonet insert, ID 15.6 vs 16.8.

## In Onshape
1. Import `01_assemblies/full_rig_revA.step` (as found).
2. Import `02_part_studios/PS3b_fixed_inserts_revB.step` and place the three green parts on the same mounts. Suppress Rev A or Rev B to flip between them.
3. Add the moving mates in `05_reference/MATES.md`.

STEP brings in solids and positions, not feature history or mates. For edits that touch many parts (sheet thickness, body height, tube size), change `PARAMS` in `appliance.py` and rerun `make_all.py` + `export_onshape.py`.
