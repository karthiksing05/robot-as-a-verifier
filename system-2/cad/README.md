# cad

Takes a `CADPatch` from the analyst, checks it, and produces a new revision. Everything goes through `CadBackend`, so the harness doesn't care which CAD tool ran.

| Backend | State | Notes |
|---|---|---|
| [`ParamsBackend`](src/rav_cad/__init__.py) | Works | Edits a JSON parameter file. Checks the patch's expected value and the spec's limits |
| [`CadQueryBackend`](src/rav_cad/__init__.py) | Works | Rebuilds the appliance from [`appliance.rev_a.yaml`](../subjects/appliance/cad/appliance.rev_a.yaml), runs kernel checks, exports only the parts that changed. Needs `uv sync --extra cad` |
| [`OnshapeBackend`](src/rav_cad/onshape/backend.py) | Built, not yet run on the real document (R5) | The team's model. The analyst edits it on its own branch through the `rav-cad` MCP tools; the generic checks judge each branch. See [Onshape](#onshape) |
| [`LocalCadBackend`](src/rav_cad/local/backend.py) | Works offline | Any product as a STEP assembly (or our box). The analyst writes CadQuery code for new reprintable parts in a local workspace through the `rav-cad-local` MCP tools; the same generic checks judge it. See [Local CAD](#local-cad-new-geometry-offline) |

## Onshape

The analyst fixes the real model itself ([D29](../../docs/decisions.md)). Each finding gets a **branch** made from the version the robot tested, which is never edited. Through the [`rav-cad` MCP tools](src/rav_cad/onshape/mcp_server.py) the model reads the feature tree and variables, measures, renders, edits (update, add or delete features, set variables), and runs `check()` until it passes, then `submit_fix`. The patch points at that branch's microversion, so what a person approves is what was checked. `apply` makes the **Rev B version** and exports STLs of the changed parts only. Merging into main is a person's call in Onshape.

| Piece | File |
|---|---|
| Settings from `.env` at the repo root (`.env.example`) | [`onshape/settings.py`](src/rav_cad/onshape/settings.py) |
| REST client: branches, versions, features, variables, mates, FeatureScript, shaded views, STEP/STL/glTF export | [`onshape/client.py`](src/rav_cad/onshape/client.py) |
| The R5 spike: try every call on a copy of the document | [`tools/onshape_spike.py`](tools/onshape_spike.py) |
| Backend: branch, check, apply | [`onshape/backend.py`](src/rav_cad/onshape/backend.py) |
| CAD tools for the analyst | [`onshape/mcp_server.py`](src/rav_cad/onshape/mcp_server.py) |
| Generic robot-centred checks, on any STEP assembly of named parts | [`generic/checks.py`](src/rav_cad/generic/checks.py) |
| The product's tag file: controls, motion, contact, approach, what may be reprinted | [`generic/tags.py`](src/rav_cad/generic/tags.py), [`subjects/appliance/onshape.yaml`](../subjects/appliance/onshape.yaml) |

The checks ask what the robot needs, not what our parametric code built: changed parts are valid single solids that fit the bed; a fix stays within one control's reprintable parts and never touches the body; nothing overlaps at rest; moving parts clear everything through their travel or swing; sliding fits keep `min_clearance`; a 12 mm fingertip reaches every control; and a pull control catches the fingertip when it pulls, so nothing needs a pinch. Failures already present in the tested revision on other controls don't count against a fix. Not checked yet: wall thickness.

To use it:

1. Make Onshape API keys (Developer Portal) and put them in `.env` at the repo root, with the link to a **copy** of the appliance document.
2. Run the spike: `cd system-2 && .venv/bin/python cad/tools/onshape_spike.py`. It prints what worked and records fixtures.
3. Fill in `subjects/appliance/onshape.yaml`: the element and version ids the spike printed, and the real part names, contact points and approach directions.
4. `uv run rav mock --analyst onshape` runs the loop with the model editing the copy.

Offline, the same checks run on our CadQuery model ([`generic/bench.py`](src/rav_cad/generic/bench.py)), which is how the tests run them without a network.

The rules from the plan: smallest change that addresses the root cause, predicted effect stated, a teammate approves, and the patch stays only if the reward rises. Nothing prints automatically.

## Local CAD: new geometry offline

The same freedom as Onshape, with no network, quota or keys ([D33](../../docs/decisions.md)). Each finding gets a **workspace** (a folder) holding the tested parts. Through the [`rav-cad-local` tools](src/rav_cad/local/mcp_server.py) the model looks (`list_controls`, `get_part`, `list_faces`, `measure_gap`, `part_size`, `render`), replaces a reprintable part with `write_part(part, code)`, and runs `check()` until it passes, then `submit_fix`. The patch points at the workspace's state hash, so what a person approves is what was checked. `apply` writes `rev_<X>/` with the changed parts' STLs, the full `assembly.step`, the code that made each new part, and `edits.jsonl`.

`write_part` runs the code in a separate Python process ([`sandbox.py`](src/rav_cad/local/sandbox.py)) with `cq`, `math`, `np`, our `geom` helpers, `old` (the part as it is) and `parts` (the others, read-only). The code must set `result` to one valid solid. Other imports, `open`/`exec`/`eval` and sockets are refused, and it is killed after 60 s; errors go back to the model with the traceback. This guards against mistakes, not attacks: it is fine for our own model on our own machine, but it is not a security boundary.

| Piece | Where |
|---|---|
| Workspace: base parts, overrides, edit log, state hash | [`local/workspace.py`](src/rav_cad/local/workspace.py) |
| Sandbox for the model's code | [`local/sandbox.py`](src/rav_cad/local/sandbox.py), [`local/_runner.py`](src/rav_cad/local/_runner.py) |
| Backend: workspace, check, apply, faces, describe | [`local/backend.py`](src/rav_cad/local/backend.py) |
| CAD tools for the analyst | [`local/mcp_server.py`](src/rav_cad/local/mcp_server.py) |
| Shared by both tool servers: logging, measure, check, submit | [`cadtools.py`](src/rav_cad/cadtools.py) |
| Picture of any product's parts | `render_parts` in [`parametric/render.py`](src/rav_cad/parametric/render.py) |

Run it on a recorded run's findings (the centrifuge's Rev A is in the repo as [`revA.step`](../subjects/centrifuge/revA.step)):

```bash
uv run rav analyze --analyst local --run subjects/centrifuge/sim_run/centrifuge-revA/events.jsonl --tags subjects/centrifuge/onshape.yaml --step subjects/centrifuge/revA.step
```

`uv run rav mock --analyst local` runs the whole loop on our box, with each feature's CadQuery shown to the model as a reference.

**From a real run, and back to the sim** ([D36](../../docs/decisions.md)). `rav fix --run <run>` takes any run's findings to this analyst. On an authored sim appliance, [`appliance.py`](src/rav_cad/appliance.py) writes its tag file from the device file and Rev A, and `patched_device` swaps the approved parts into the tested revision for a retest: new meshes, and each button's travel from its geometry (under 0.3 mm of clearance per side binds at 0.1 mm). On a real product, pass `--step`, `--tags` and `--approve NAME`; the retest is printing rev_<X>/.

## The CadQuery model

The appliance is a YAML spec: the box, an optional sloped panel, and a list of controls placed on faces. Every control is a small keyed **insert** that drops into a pocket, so a fix reprints a 5 to 15 minute part, not the box.

```bash
cd system-2
uv sync --extra cad
uv run python -m rav_cad.parametric build subjects/appliance/cad/appliance.rev_a.yaml --out cad/out/rev_a
uv run python -m rav_cad.parametric patch subjects/appliance/cad/appliance.rev_a.yaml \
    subjects/appliance/cad/patch_button_2.json --out cad/out/rev_b
uv run python -m rav_cad.parametric gauge --spec subjects/appliance/cad/appliance.rev_a.yaml --feature button_2 \
    --out cad/out/gauge
uv run pytest tests/test_cad_parametric.py      # about a minute
```

`build` writes one STL per printable part, `features.json` (each control's pose and the robot's approach, contact and press points), `checks.json`, `render.png` and `assembly.glb`. To look around a build in 3D, serve the repo (`python -m http.server 8765`) and open `system-2/cad/viewer.html?run=out/rev_b` from `system-2/cad/`.

**Rev A** ([spec](../subjects/appliance/cad/appliance.rev_a.yaml)) is a placeholder for the team's appliance: 160 × 120 × 180 mm, three buttons on a 45° panel, a 16×2 LCD, a hinged door. It has both planted faults: button 2's clearance is 0.15 mm (the others 0.40), and the door has a pinch tab. The panel angle, the LCD and the switches are guesses until the team confirms them; change the numbers, keep the structure.

| Control type | What gets printed | Patchable fit |
|---|---|---|
| `button` | insert with a guide sleeve, cap, stem, and a holder for a 6×6 mm tactile switch (tells the Pico, pushes the button back) | `clearance`, stem to bore |
| `push_latch`, `dial` | insert, cap, stem | `clearance` |
| `slider`, `toggle` | insert with a slot, knob, stem (the toggle slides; it doesn't pivot) | `clearance` |
| `window` | insert with screw posts for `module: lcd1602` or `oled096` | — |
| `door` | door with hinge knuckles (1.75 mm filament pin), magnet catch, reed-switch slot, and a handle insert | `handle_style`: `tab`, `bar` or `push_latch` |
| `handle` | insert on a face | `style` |

The shell also gets a **base** with posts for a Raspberry Pi Pico, and two **desk corner pieces** with pegs, so every revision sits in the same spot.

### Checks, before anything prints

Valid solids; size and walls within limits; each insert on its face; inserts spaced apart; **room for the 12 mm fingertip** around what it touches; a **bare patch** on each control face for the touch taps; **clearance measured from the geometry** (it must match the parameter to 0.02 mm); no interference between any parts, switches or the base; and **the door swings open** to 90° without hitting the box.

### Patches

`CadQueryBackend` takes the team's `CADPatch`. Parameters are dotted paths (`features.button_2.clearance`), the names `read_params()` lists; the harness hands that list to the analyst, so patches use them. The names in `params.rev_a.json` still work (`button_clearance[1]`, `handle_style`) for old patches. A patch is refused when its `from_value` is stale, it changes more than one parameter or more than the posture allows (0.25 mm for a clearance), or the new revision fails a check. Each refusal says why. `apply` writes `appliance.rev_b.yaml` and exports only the parts whose geometry changed; patches with the same `revision_to` batch into one revision.

On Rev A, the button fix reprints `button_2__insert` (about 7 min) and the door fix reprints `door__handle` (about 10 min). A `push_latch` handle also needs a bought push-to-open latch in the frame; the `bar` handle needs nothing else.

### At the event

1. Print the clearance gauge first, flat, on the event printer, and press the peg through each hole with the scale. Pick the clearance that binds (about 8 N) and the one that works, and put both into the spec and the patch.
2. Write the real appliance into the spec and build until every check passes.
3. Print the shell, base and parts. Print inserts flat, as exported: orientation changes a fit more than a 0.25 mm patch does.

### Known gaps

- Nothing has been printed: every fit is untested until the gauge is.
- The harness approves patches through `approve()` but doesn't fill `CADPatch.approved_by` yet, so it drives this backend with `require_approval=False`.
- Print times and grams are rough estimates from volume, not from a slicer.
- One sloped face at most, flat faces only, no rounded corners.
