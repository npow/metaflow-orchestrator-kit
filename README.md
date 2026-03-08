# metaflow-orchestrator-kit

[![CI](https://github.com/npow/metaflow-orchestrator-kit/actions/workflows/ci.yml/badge.svg)](https://github.com/npow/metaflow-orchestrator-kit/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/metaflow-orchestrator-kit)](https://pypi.org/project/metaflow-orchestrator-kit/)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache--2.0-blue.svg)](LICENSE)
[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)

Build a correct Metaflow orchestrator the first time — scaffold, declare capabilities, and prove compliance.

## The problem

Every new Metaflow orchestrator hits the same five subtle bugs: run params passed as tuples instead of lists, `--branch` missing from step subprocesses, config env vars absent from containers, retry counts hardcoded to zero, and dotted project names crashing `from_deployment()`. There is no official contract document or compliance test suite — each bug is discovered by running real flows against the scheduler. This kit gives you the contract, the compliance tests, and the scaffold so none of them reach production.

## Quick start

```bash
pip install metaflow-orchestrator-kit
metaflow-orchestrator-scaffold my_scheduler
```

Declare what your scheduler supports, then prove it:

```python
from metaflow_orchestrator_kit import Cap, REQUIRED

SUPPORTED_CAPABILITIES = REQUIRED | {Cap.NESTED_FOREACH, Cap.SCHEDULE}
```

```bash
pytest metaflow_orchestrator_kit/compliance/ \
    --ux-config=path/to/ux_test_config.yaml \
    --only-backend my_scheduler -v
```

## Install

```bash
pip install metaflow-orchestrator-kit
# with dev dependencies:
pip install "metaflow-orchestrator-kit[dev]"
```

## Usage

### Scaffold a new orchestrator

```bash
metaflow-orchestrator-scaffold my_scheduler
# equivalent: python -m metaflow_orchestrator_kit.scaffold my_scheduler
```

Generates four files:

```
my_scheduler_deployer.py      DeployerImpl subclass — all required TODOs annotated
my_scheduler_objects.py       DeployedFlow / TriggeredRun subclasses
my_scheduler_cli.py           CLI entry-point group (register in metaflow/plugins/__init__.py)
ux-tests-my_scheduler.yml     GitHub Actions workflow skeleton
```

### Declare capabilities

```python
from metaflow_orchestrator_kit import Cap, REQUIRED

# REQUIRED is the minimum set every orchestrator must pass.
# Add optional capabilities your scheduler actually supports.
SUPPORTED_CAPABILITIES = REQUIRED | {Cap.NESTED_FOREACH, Cap.SCHEDULE}
```

### Run compliance tests

```bash
pytest metaflow_orchestrator_kit/compliance/ \
    --ux-config=path/to/ux_test_config.yaml \
    --only-backend my_scheduler \
    -v
```

REQUIRED capabilities fail if unimplemented. OPTIONAL capabilities skip if not in the supported set.

### Wire compliance into CI

```yaml
- name: Run compliance tests
  run: |
    pytest metaflow_orchestrator_kit/compliance/ \
      --ux-config=test/ux/ux_test_config.yaml \
      --only-backend my_scheduler \
      -v
```

The suite reads the same `ux_test_config.yaml` format used by Metaflow's own UX tests, so no additional config is needed if you already have that file.

## How it works

`OrchestratorCapabilities` (`Cap`) is an enum of every Metaflow feature an orchestrator can or must support. The compliance suite runs one parametrized pytest test per capability against a live backend. Required capabilities fail hard; optional ones skip if the scheduler is not in the supported set. The scaffold generates a fully annotated skeleton with every contract requirement pre-filled so they're hard to miss.

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

### Optional — implement or explicitly declare unsupported

| Capability | What it means |
|---|---|
| `Cap.NESTED_FOREACH` | `foreach` inside `foreach` |
| `Cap.CONDA` | `@conda` environment creation at task runtime |
| `Cap.RESUME` | `ORIGIN_RUN_ID` resume: re-run from a previously failed step |
| `Cap.SCHEDULE` | `@schedule` cron trigger |

## The five bugs every new orchestrator gets wrong

Each compliance test documents *why* the requirement exists. Here are the bugs they catch:

**1. `run_params` tuple vs list (`Cap.RUN_PARAMS`)** — Click's multi-value options return tuples. Passing a tuple to `trigger()` causes `TypeError` when two or more params are given. Fix: `run_params = list(run_params) if run_params else []`.

**2. `--branch` not forwarded to step subprocesses (`Cap.PROJECT_BRANCH`)** — `@project` reads `current.branch_name` from the `--branch` flag at step runtime. Without it, all step tasks produce an empty branch name. Fix: include `--branch <branch>` in every step command the scheduler launches.

**3. `METAFLOW_FLOW_CONFIG_VALUE` missing from container env (`Cap.CONFIG_EXPR`)** — `@config` and `@project` use this env var to reconstruct the config dict at task runtime. Without it, tasks run with empty config. Fix: read `flow._flow_state[FlowStateItems.CONFIGS]` at compile time and JSON-serialize it into the container environment.

**4. `retry_count` hardcoded to 0 (`Cap.RETRY`)** — Metaflow's `@retry` uses the attempt number to decide whether to retry. Hardcoding 0 means the flow always sees attempt 0 and never retries. Fix: derive from the scheduler's native counter (`AWS_BATCH_JOB_ATTEMPT`, Kubernetes `restartCount`, Airflow `try_number - 1`, etc.).

**5. `from_deployment()` fails on dotted names (`Cap.FROM_DEPLOYMENT`)** — DAG IDs for `@project`-decorated flows are dotted: `project.branch.FlowName`. Using the full string as a Python class name raises `SyntaxError`. Fix: `flow_name = identifier.split(".")[-1]`.

## Example `ux_test_config.yaml`

```yaml
backends:
  - name: my-scheduler
    scheduler_type: my_scheduler
    cluster: null
    decospec: null
    deploy_args: {}
    enabled: true
```

## Development

```bash
git clone https://github.com/npow/metaflow-orchestrator-kit
cd metaflow-orchestrator-kit
pip install -e ".[dev]"
pytest
```

## License

[Apache 2.0](LICENSE)
