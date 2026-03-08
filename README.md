# metaflow-orchestrator-kit

Development kit for building Metaflow orchestrator extensions.

This package gives you three things:

1. **`OrchestratorCapabilities` (`Cap`)** — an enum of every Metaflow feature an orchestrator can or must support, with plain-English descriptions of each contract requirement.
2. **Compliance test suite** — parametrized pytest tests that verify your orchestrator implements the contract correctly.  Every test documents *why* the requirement exists, not just what it checks.
3. **Scaffold tool** — `metaflow-orchestrator-scaffold my_scheduler` generates a complete, annotated skeleton with all contract requirements pre-filled so they are hard to miss.

The design goal: a developer building a new Metaflow orchestrator installs this package, declares their capabilities, runs the compliance tests, and knows exactly what they need to implement.

---

## Quick start

### 1. Install

```bash
pip install metaflow-orchestrator-kit
```

### 2. Scaffold a new orchestrator

```bash
metaflow-orchestrator-scaffold my_scheduler
# or: python -m metaflow_orchestrator_kit.scaffold my_scheduler
```

This writes four files:

```
my_scheduler_deployer.py      DeployerImpl subclass with all required TODO annotations
my_scheduler_objects.py       DeployedFlow / TriggeredRun subclasses
my_scheduler_cli.py           CLI entry-point group (register in metaflow/plugins/__init__.py)
ux-tests-my_scheduler.yml     GitHub Actions workflow skeleton
```

### 3. Declare your capabilities

In your deployer module:

```python
from metaflow_orchestrator_kit import Cap, REQUIRED

# Start with all REQUIRED capabilities and add optional ones you implement.
SUPPORTED_CAPABILITIES = REQUIRED | {Cap.NESTED_FOREACH, Cap.SCHEDULE}
```

### 4. Run the compliance tests

Point the suite at your `ux_test_config.yaml`:

```bash
pytest metaflow_orchestrator_kit/compliance/ \
    --ux-config=path/to/ux_test_config.yaml \
    --only-backend my_scheduler \
    -v
```

REQUIRED capabilities fail if the orchestrator does not implement them correctly.
OPTIONAL capabilities are skipped if the scheduler is not in the supported set.

---

## Capabilities reference

### REQUIRED — every orchestrator must implement these

| Capability | What it means |
|---|---|
| `Cap.LINEAR_DAG` | start → one or more steps → end |
| `Cap.BRANCHING` | static split/join: steps in parallel branches, merged at a join step |
| `Cap.FOREACH` | dynamic fan-out: foreach produces N parallel tasks at runtime |
| `Cap.RETRY` | `@retry` with a real attempt count derived from the scheduler's native retry counter (not hardcoded to 0) |
| `Cap.CATCH` | `@catch` decorator: catch a step exception and continue the flow |
| `Cap.TIMEOUT` | `@timeout` decorator: abort a step that exceeds the time limit |
| `Cap.RESOURCES` | `@resources` passthrough: CPU/memory hints forwarded to the scheduler |
| `Cap.PROJECT_BRANCH` | `--branch` forwarded to ALL step subprocesses, not just the start step |
| `Cap.CONFIG_EXPR` | `METAFLOW_FLOW_CONFIG_VALUE` injected into every container/subprocess so `@config` and `@project` work at task runtime |
| `Cap.RUN_PARAMS` | `trigger()` run params must be a list, not a tuple (Click returns tuples; passing a tuple causes TypeError) |
| `Cap.FROM_DEPLOYMENT` | `from_deployment(identifier)` must handle dotted names (`project.branch.FlowName`); only the last component is the Python class name |

### OPTIONAL — implement or explicitly declare unsupported

| Capability | What it means |
|---|---|
| `Cap.NESTED_FOREACH` | foreach inside foreach |
| `Cap.CONDA` | `@conda` environment creation at task runtime |
| `Cap.RESUME` | `ORIGIN_RUN_ID` resume: re-run from a previously failed step |
| `Cap.SCHEDULE` | `@schedule` cron trigger |

---

## The five bugs every new orchestrator gets wrong

These are real bugs that have appeared in multiple orchestrator implementations.
The compliance suite has a dedicated test for each one.

**1. `run_params` tuple vs list (`Cap.RUN_PARAMS`)**

Click's multi-value options return tuples. If the orchestrator passes `run_params` directly to `trigger()` without converting, passing two or more params causes a `TypeError` inside the scheduler's client library. Fix: `run_params = list(run_params) if run_params else []`.

**2. `--branch` not forwarded to step subprocesses (`Cap.PROJECT_BRANCH`)**

`@project` reads `current.branch_name` from the `--branch` CLI flag at step runtime. Orchestrators that compile a step command but omit `--branch` produce an empty branch in all step tasks. Fix: include `--branch <branch>` in every step command the scheduler launches.

**3. `METAFLOW_FLOW_CONFIG_VALUE` missing from container env (`Cap.CONFIG_EXPR`)**

`@config` and `@project` use this env var to reconstruct the config dict at task runtime. Without it, tasks run with empty/default config and `@project` names are wrong. Fix: at compile time, read `flow._flow_state[FlowStateItems.CONFIGS]` and JSON-serialize it into the container environment.

**4. `retry_count` hardcoded to 0 (`Cap.RETRY`)**

Metaflow's `@retry` uses the attempt number to decide whether to retry. When hardcoded, the flow always sees attempt=0 and never retries. Fix: derive `retry_count` from the scheduler's native counter (`AWS_BATCH_JOB_ATTEMPT`, Kubernetes `restartCount`, Airflow `try_number - 1`, etc.).

**5. `from_deployment()` fails on dotted names (`Cap.FROM_DEPLOYMENT`)**

DAG IDs for `@project`-decorated flows are dotted: `project.branch.FlowName`. Using the full dotted string as a Python class name raises `SyntaxError`. Fix: `flow_name = identifier.split(".")[-1]`.

---

## Wiring compliance tests into an existing orchestrator's CI

Add `metaflow-orchestrator-kit` as a test dependency, then in your CI workflow:

```yaml
- name: Run compliance tests
  run: |
    pytest metaflow_orchestrator_kit/compliance/ \
      --ux-config=test/ux/ux_test_config.yaml \
      --only-backend my_scheduler \
      -v
```

The suite reads the same `ux_test_config.yaml` format used by Metaflow's own UX tests, so no additional config is required if you already have that file.

For backends that do not support a particular optional capability, add them to the `unsupported_schedulers` dict inside `test_nested_foreach_or_skip` (or contribute a PR to this repo).

---

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

---

## License

Apache 2.0
