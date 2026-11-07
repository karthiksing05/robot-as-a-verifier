# contracts

The objects only System 2 uses: run events and steering ([`events.py`](src/rav_contracts/events.py)), requests, findings, fixes and reports ([`models.py`](src/rav_contracts/models.py)), and the seams inside this system ([`ports.py`](src/rav_contracts/ports.py)). It re-exports [`rav_interface`](../../system-1/interface/README.md), so harness code has one place to import from.

Pydantic models, so the JSON Schema given to the model is generated from the code and the two can't drift apart:

```bash
uv run python -m rav_contracts.export_schema   # writes contracts/schema/*.json
```

Units: millimetres, newtons, degrees. Frame: arm base, x forward, y left, z up.

Before changing something here, read [Changing a contract](../../CONTRIBUTING.md#changing-a-contract).
