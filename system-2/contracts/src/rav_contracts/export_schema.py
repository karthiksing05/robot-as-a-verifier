"""Write JSON Schemas for the Console and for model prompts: python -m rav_contracts.export_schema [out_dir]."""
import inspect
import json
import pathlib
import sys

from pydantic import BaseModel

from rav_interface import models as wire

from . import events, models


def export(out: pathlib.Path) -> list[pathlib.Path]:
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for module in (wire, models, events):
        for name, cls in inspect.getmembers(module, inspect.isclass):
            if issubclass(cls, BaseModel) and cls.__module__ == module.__name__ and name != "Contract":
                path = out / f"{name}.json"
                path.write_text(json.dumps(cls.model_json_schema(), indent=2, sort_keys=True) + "\n")
                written.append(path)
    return written


if __name__ == "__main__":
    target = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path(__file__).parents[2] / "schema"
    print(f"{len(export(target))} schemas in {target}")
