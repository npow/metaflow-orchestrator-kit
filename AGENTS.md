# AGENTS.md — metaflow-orchestrator-kit

Quick orientation for coding agents working in this repo.

## What this repo is

A developer kit for building Metaflow orchestrator extensions. It provides:
- `scaffold` — generates a skeleton orchestrator implementation
- `validate` — static analysis checks on an orchestrator directory
- `compliance/` — pytest tests run against a live scheduler
- `capabilities.py` — the canonical `Cap` enum and `REQUIRED` / `OPTIONAL` frozensets
- `docs/pitfalls/` — 33 known bugs documented from 7 real implementations

## Key files

| Task | Read |
|---|---|
| Understand the Deployer contract | `metaflow_orchestrator_kit/capabilities.py` |
| Add a validator check | `metaflow_orchestrator_kit/validate/__main__.py` |
| Add a pitfall (contract/API) | `docs/pitfalls/contract.md` |
| Add a pitfall (env vars) | `docs/pitfalls/env-vars.md` |
| Add a pitfall (Docker/CI) | `docs/pitfalls/docker-ci.md` |
| Add a pitfall (scheduler API) | `docs/pitfalls/scheduler-api.md` |
| Update the scaffold template | `metaflow_orchestrator_kit/scaffold/__main__.py` |
| Update the compliance tests | `metaflow_orchestrator_kit/compliance/` |
| User-facing overview | `README.md` |

## How pitfalls are numbered

Pitfalls are numbered globally (#1–#33). When adding a new one:
1. Pick the next available number
2. Add it to the appropriate topic file in `docs/pitfalls/`
3. Update the summary list in `README.md` → "Common pitfalls" section
4. If statically checkable, add a `_check_*` function in `validate/__main__.py` and register it in the `validate()` function

## Validator check conventions

Each `_check_*` function:
- Returns a `_Check(name, passed, message, hint=None)` namedtuple
- Must not import from the package under test (all checks use regex on file content)
- Uses `_find_in_any_file(files, pattern)` for cross-file searches
- Registered in `validate()` at the bottom of `validate/__main__.py`

## Do not

- Add `__init__.py` to `metaflow_extensions/` in any orchestrator (breaks namespace package)
- Hardcode retry_count to 0 (pitfall #4)
- Pass run_params as a tuple (pitfall #1)
- Skip from_deployment testing (pitfall #5)
