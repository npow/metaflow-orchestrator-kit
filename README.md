# metaflow-orchestrator-kit

[![CI](https://github.com/npow/metaflow-orchestrator-kit/actions/workflows/ci.yml/badge.svg)](https://github.com/npow/metaflow-orchestrator-kit/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/metaflow-orchestrator-kit)](https://pypi.org/project/metaflow-orchestrator-kit/)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache--2.0-blue.svg)](LICENSE)
[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)

Build a correct Metaflow orchestrator extension the first time — scaffold, validate, and prove compliance.

## Table of Contents

- [The problem](#the-problem)
- [Install](#install)
- [5-minute quickstart](#5-minute-quickstart)
- [What the scaffold generates](#what-the-scaffold-generates)
- [Extension package layout](#extension-package-layout)
- [Capabilities](#capabilities)
- [Usage](#usage)
  - [Validate](#validate-static-analysis--no-scheduler-needed)
  - [Test](#test-one-command-compliance-suite)
  - [Wire into CI](#wire-compliance-into-ci)
- [Common pitfalls](#common-pitfalls)
- [Development](#development)

---

## The problem

You want to integrate a new scheduler with Metaflow. You know you need a `DeployerImpl`, a `DeployedFlow`, and a `TriggeredRun` — but the contract is nowhere written down. No spec lists what your deployer must handle. No test suite validates your implementation. You figure it out by reading existing orchestrators and rediscovering the same handful of non-obvious bugs every author hits: retry counts hardcoded to zero, `--branch` missing from step subprocesses, config env vars absent from containers, `run_params` passed as a tuple.

This kit is the missing artifact: a written contract, a scaffold that pre-fills every requirement, a static validator that catches mistakes before CI, and a compliance test suite you can run against a live scheduler.

## Install

```bash
pip install metaflow-orchestrator-kit
# with dev dependencies:
pip install "metaflow-orchestrator-kit[dev]"
```

## 5-minute quickstart

```bash
# 1. Scaffold
python -m metaflow_orchestrator_kit.scaffold my_scheduler
cd my_scheduler/

# 2. Fill in the scheduler-specific parts (all marked # TODO: SCHEDULER API)
#    - my_scheduler_deployer.py: _compile_workflow(), _build_step_command()
#    - my_scheduler_objects.py:  trigger(), from_deployment(), status property
#    - my_scheduler_cli.py:      create(), trigger()

# 3. Validate (static analysis — no scheduler needed)
python -m metaflow_orchestrator_kit.validate ./

# 4. Test (one command — writes config, finds flows, runs compliance suite)
python -m metaflow_orchestrator_kit.test \
  --scheduler-type my_scheduler \
  --deploy-args host=http://localhost:8000

# 5. If all green: commit the generated ux-tests-my_scheduler.yml to your repo
```

## What the scaffold generates

```bash
python -m metaflow_orchestrator_kit.scaffold my_scheduler
```

Creates `./my_scheduler/` containing:

```
my_scheduler_deployer.py    DeployerImpl subclass — all required plumbing pre-solved
my_scheduler_objects.py     DeployedFlow / TriggeredRun subclasses
my_scheduler_cli.py         CLI entry-point group (create, trigger)
mfextinit_my_scheduler.py   Extension registration (auto-discovered by Metaflow)
ux-tests-my_scheduler.yml   GitHub Actions workflow skeleton
```

The generated `_build_step_command()` has all Metaflow plumbing pre-solved. You fill in only the scheduler API calls:

```python
# Generated deployer — pre-solved (do not change these)
required_env = {
    "METAFLOW_FLOW_CONFIG_VALUE": flow_config_value or "",   # Cap.CONFIG_EXPR
    "METAFLOW_DATASTORE_SYSROOT_LOCAL": datastore_sysroot,
    "METAFLOW_SERVICE_URL": os.environ.get("METAFLOW_SERVICE_URL", ""),
    "PATH": os.environ.get("PATH", ""),
}

def _build_step_command(self, step_name, run_id, task_id, input_paths,
                         branch=None, retry_count=0, environment_type="local"):
    cmd = [sys.executable, flow_file, "--no-pylint", "--environment", environment_type]
    if branch:
        cmd += ["--branch", branch]   # Cap.PROJECT_BRANCH
    cmd += ["step", step_name, "--run-id", run_id, "--task-id", task_id,
            "--retry-count", str(retry_count),   # TODO: SCHEDULER API — replace 0
            "--input-paths", input_paths]
    return cmd
```

## Extension package layout

Once you're ready to publish, place the generated files in the proper namespace package structure:

```
your_package/
  metaflow_extensions/         ← NO __init__.py here (implicit namespace package)
    my_scheduler/
      plugins/
        mfextinit_my_scheduler.py     ← extension registration
        my_scheduler/
          my_scheduler_deployer.py    ← DeployerImpl subclass
          my_scheduler_objects.py     ← DeployedFlow / TriggeredRun
          my_scheduler_cli.py         ← CLI group
```

After `pip install -e .`, `Deployer(flow_file).my_scheduler(...)` is available with no other registration needed. Metaflow discovers `mfextinit_*.py` automatically.

> **CRITICAL:** `metaflow_extensions/` must NOT have `__init__.py`. It is an implicit namespace package. Adding `__init__.py` breaks extension discovery — `Deployer(flow).my_scheduler()` will silently not exist after install.

## Capabilities

### Required — every orchestrator must pass these

| Capability | What it means |
|---|---|
| `Cap.LINEAR_DAG` | start → one or more steps → end |
| `Cap.BRANCHING` | static split/join: parallel branches merged at a join step |
| `Cap.FOREACH` | dynamic fan-out: `foreach` produces N tasks at runtime |
| `Cap.RETRY` | real attempt count from scheduler's native counter (not hardcoded 0) |
| `Cap.CATCH` | `@catch` decorator: catch step exception and continue the flow |
| `Cap.TIMEOUT` | `@timeout` decorator: abort a step that exceeds the time limit |
| `Cap.RESOURCES` | `@resources` passthrough: CPU/memory hints forwarded to scheduler |
| `Cap.PROJECT_BRANCH` | `--branch` forwarded to every step subprocess, not just start |
| `Cap.CONFIG_EXPR` | `METAFLOW_FLOW_CONFIG_VALUE` injected into every container/subprocess |
| `Cap.RUN_PARAMS` | `trigger()` run params as list, not tuple |
| `Cap.FROM_DEPLOYMENT` | `from_deployment(identifier)` handles dotted names (`project.branch.FlowName`) |
| `Cap.CONDA` | `@conda` environment creation at task runtime; passes `--environment conda` to step subprocesses |

### Optional — implement or explicitly declare unsupported

| Capability | What it means |
|---|---|
| `Cap.NESTED_FOREACH` | `foreach` inside `foreach` |
| `Cap.RESUME` | `ORIGIN_RUN_ID` resume: re-run from a previously failed step |
| `Cap.SCHEDULE` | `@schedule` cron trigger |

Declare your supported capabilities in the deployer:

```python
from metaflow_orchestrator_kit import Cap, REQUIRED

SUPPORTED_CAPABILITIES = REQUIRED | {Cap.NESTED_FOREACH, Cap.SCHEDULE}
```

## Usage

### Validate (static analysis — no scheduler needed)

```bash
python -m metaflow_orchestrator_kit.validate ./my_scheduler/
# equivalent:
metaflow-orchestrator-validate ./my_scheduler/
```

Example output:

```
Validating: /path/to/my_scheduler/

  PASS  metaflow_extensions/ has no __init__.py
  PASS  mfextinit_<name>.py exists
  PASS  DEPLOYER_IMPL_PROVIDERS_DESC has correct structure
  PASS  run_params uses list() not tuple()
  FAIL  METAFLOW_FLOW_CONFIG_VALUE in step env
        Problem: METAFLOW_FLOW_CONFIG_VALUE not found in any extension file
        Fix: Extract at compile time: from metaflow.flowspec import FlowStateItems; ...
  PASS  --branch passed to step commands
  PASS  retry_count reads from attempt, not hardcoded to 0
  PASS  DATASTORE_SYSROOT captured at compile time
  PASS  ENVIRONMENT_TYPE passed to step command

Results: 8 passed, 1 failed
```

### Test (one-command compliance suite)

```bash
python -m metaflow_orchestrator_kit.test \
  --scheduler-type my_scheduler \
  --deploy-args host=http://localhost:8000,token=abc123

# Full options:
python -m metaflow_orchestrator_kit.test \
  --scheduler-type windmill \
  --deploy-args windmill_host=http://localhost:8000,windmill_token=abc123 \
  --metaflow-src /path/to/metaflow \
  --test-modules compliance,basic,config,dag \
  --workers 4
```

This command:
1. Writes `ux_test_config_windmill.yaml` automatically (scheduler-specific name avoids conflicts)
2. Creates an isolated `METAFLOW_DATASTORE_SYSROOT_LOCAL` per run (prevents contamination between concurrent test runs)
3. Verifies scheduler reachability before starting tests
4. Runs the compliance tests and reports pass/fail per capability

### Wire compliance into CI

```yaml
- name: Run compliance tests
  run: |
    python -m metaflow_orchestrator_kit.test \
      --scheduler-type my_scheduler \
      --deploy-args host=${{ secrets.SCHEDULER_HOST }}
```

Or use the generated `ux-tests-my_scheduler.yml` as a starting point.

## Common pitfalls

Every new orchestrator implementation hits the same bugs. The scaffold pre-solves most of them; the validator catches the rest before CI. 33 pitfalls have been documented from the full histories of kestra, prefect, temporal, dagster, flyte, windmill, and mage.

The top 5 pitfalls that every implementation hits:

1. **`run_params` tuple vs list** — Click returns tuples; the deployer API requires a list. `run_params = list(run_params) if run_params else []`
2. **`METAFLOW_FLOW_CONFIG_VALUE` missing** — must be baked into every step container env at compile time
3. **`--branch` not forwarded** — must be in every step command, not just the start step
4. **`retry_count` wrong** — derive from scheduler's native counter; most are 1-indexed, so use `max(0, counter - 1)`
5. **Docker worker filesystem isolation** — step scripts reference host paths that don't exist inside worker containers; add volume mounts

Full pitfall documentation, grouped by topic:
- [Contract & API pitfalls](docs/pitfalls/contract.md) — deployer protocol, `from_deployment`, `init`, cancellation
- [Environment variable pitfalls](docs/pitfalls/env-vars.md) — `METAFLOW_FLOW_CONFIG_VALUE`, `--branch`, sysroot, `--input-paths`
- [Docker & CI pitfalls](docs/pitfalls/docker-ci.md) — volume mounts, root-owned files, GHA env vars, conda PATH
- [Scheduler API pitfalls](docs/pitfalls/scheduler-api.md) — auth, async indexing, `--tag` placement, coverage artifacts

## Development

```bash
git clone https://github.com/npow/metaflow-orchestrator-kit
cd metaflow-orchestrator-kit
pip install -e ".[dev]"
pytest
```

## License

[Apache 2.0](LICENSE)
