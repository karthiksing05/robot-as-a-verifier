# Working in this repo

## The flow

1. Pull a task from the [Kanban](https://claude.ai/artifact/9Dm3x26boTyvHhrqAyEpaV) and move it to In progress.
2. Work in your folder on a short branch named `yourname/what-it-does`.
3. Run `uv run pytest` in the system you changed. It needs no hardware and takes seconds.
4. Merge to `main` as soon as it works. Small and often beats big and late: nobody has time for a painful merge at hour 20.
5. Move the Kanban card.

For a change inside a folder you own, merging directly is fine. If it touches someone else's folder, tell them first.

## The rules that keep this easy

- **Know which system you're in.** The robot is System 1, and the harness, LLM and Console are System 2. [System 1 and System 2](docs/system-boundary.md) says where code goes and what may cross between them.
- **System 2 imports only `rav_interface` from System 1, and System 1 imports nothing from System 2.** If you need a number from the other side, add it to the contract. Don't reach across, even when both run on your laptop. `system-1/core`, `sim` and `hardware` stay flat modules, with no dependency on the rest of the repo, and `core` imports nothing from the other two.
- **The model thinks, code moves, sensors decide.** The model picks routines and proposes plans and patches. It never commands a joint, and it never decides a verdict or the reward.
- **Steering takes effect between steps**, never inside a motion. The E-stop is separate and always available.
- **A person approves a plan before it runs, and a patch before it prints.** Amended plans go by [priority level](docs/system-boundary.md#approving-an-amended-plan). Only mocks may auto-approve.
- **No fail verdict without evidence in the log.** The reward must be recomputable from `events.jsonl` alone.
- **Don't commit run outputs or large films.** `.gitignore` handles the usual ones.

## Changing a contract

The contracts are the only thing that can break someone else's work, so:

1. Add new fields as optional, if you can. Old code keeps working.
2. For anything that renames or removes, say so in the team chat first.
3. Change `system-1/interface` or `system-2/contracts`, then fix every use in the same commit. `uv run pytest` shows you what broke. A change to the interface can break both systems, so run both.
4. If it changes what the Console shows, regenerate the fixture: `uv run python fixtures/make_fixture.py` in `system-2`.

## Recording a decision

When the team decides something that changes the architecture or the stack, add a row to [`docs/decisions.md`](docs/decisions.md) and update any page that now disagrees. If it overrides a tab in the Google Doc, add a note at the top of that tab.

## If you have work from before the restructure

The old folders moved, and [the map](docs/system-boundary.md#where-the-old-folders-went) has them all. Your commits can stay as they are: rebase them, and git moves them into the new layout. A plain rebase stops on every new file, so turn on directory renames:

```bash
git fetch origin
git -c merge.directoryRenames=true rebase origin/main
```

Then check three things:

1. **Nothing is left in the old folders.** Run `ls packages apps subjects`. A file in a brand-new subfolder can stay behind, so `git mv` it to its new home. `uv run pytest` in `system-2` fails while any of those folders exist.
2. **Dependencies went to the right system.** Edits to the old root `pyproject.toml` land in `system-1/pyproject.toml`. Move any that belong to System 2.
3. **The lockfiles match.** Don't resolve `uv.lock` by hand: take either side, then run `uv lock` inside `system-1` and `system-2`.

Delete the old `.venv` at the root, run `uv sync` inside the system you work on, and run the tests in both systems. If your work imports across the line, go through [the tools](docs/system-boundary.md#control-what-system-2-can-call) instead.
