# interface

The wire contract between the systems: what crosses, in millimetres, newtons and degrees. System 2 imports this and nothing else from System 1, so it depends only on pydantic and must stay that way.

| File | Holds |
|---|---|
| [`models.py`](src/rav_interface/models.py) | Controls, scenes, plans, steps, traces, verdicts, and the skill and failure vocabularies |
| [`routines.py`](src/rav_interface/routines.py) | Tool names, routines, stops, escalation codes, policies and decisions |

Before changing something here, read [Changing a contract](../../CONTRIBUTING.md#changing-a-contract). A new tool or escalation code [needs a reason](../../docs/system-boundary.md#where-to-add-your-code).
