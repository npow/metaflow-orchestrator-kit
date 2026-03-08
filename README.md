# metaflow-orchestrator-kit

[![CI](https://github.com/npow/metaflow-orchestrator-kit/actions/workflows/ci.yml/badge.svg)](https://github.com/npow/metaflow-orchestrator-kit/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/metaflow-orchestrator-kit)](https://pypi.org/project/metaflow-orchestrator-kit/)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache--2.0-blue.svg)](LICENSE)
[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)

Build a correct Metaflow orchestrator the first time — scaffold, declare capabilities, and prove compliance.

## The problem

You want to integrate a new scheduler with Metaflow. You know you need to implement a `DeployerImpl`, a `DeployedFlow`, and a `TriggeredRun`. But Metaflow's orchestrator contract is not written down anywhere. There is no spec listing what your deployer must handle, no test suite to run against your implementation, and no scaffold to get you started. You figure it out by reading existing orchestrator code and hitting a handful of non-obvious bugs that every new orchestrator author rediscovers independently: retry counts hardcoded to zero, `--branch` missing from step subprocesses, config env vars absent from containers. This kit is the missing artifact: a written contract, a compliance test suite you can run locally, and a scaffold that pre-fills every requirement so none of them are easy to skip.

## 5-minute quickstart

```bash
# 1. Install
pip install metaflow-orchestrator-kit

# 2. Scaffold
python -m metaflow_orchestrator_kit.scaffold my_scheduler
cd my_scheduler/

# 3. Fill in the scheduler-specific parts (all marked with # TODO: SCHEDULER API)
#    - my_scheduler_deployer.py: _compile_workflow(), _build_step_command()
#    - my_scheduler_objects.py:  trigger(), from_deployment(), status property
#    - my_scheduler_cli.py:      create(), trigger()

# 4. Validate (catches all known pitfalls without running tests)
python -m metaflow_orchestrator_kit.validate ./

# 5. Test (one command — writes config, finds flows, runs compliance suite)
python -m metaflow_orchestrator_kit.test \
  --scheduler-type my_scheduler \
  --deploy-args host=http://localhost:8000

# 6. If all green: set up GHA with the generated ux-tests-my_scheduler.yml
```

## What the scaffold generates

```bash
python -m metaflow_orchestrator_kit.scaffold my_scheduler
```

Creates `./my_scheduler/` containing:

```
my_scheduler_deployer.py    DeployerImpl subclass — all required plumbing pre-solved
my_scheduler_objects.py     DeployedFlow / TriggeredRun subclasses
my_scheduler_cli.py         CLI entry-point group
mfextinit_my_scheduler.py   Extension registration (auto-discovered by Metaflow)
ux-tests-my_scheduler.yml   GitHub Actions workflow skeleton
```

The generated `_build_step_command()` includes all pre-solved Metaflow plumbing. You fill in only the scheduler API calls:

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

## Install

```bash
pip install metaflow-orchestrator-kit
# with dev dependencies:
pip install "metaflow-orchestrator-kit[dev]"
```

## Usage

### 1. Scaffold

```bash
python -m metaflow_orchestrator_kit.scaffold my_scheduler [output_dir]
# equivalent short form:
metaflow-orchestrator-scaffold my_scheduler
```

### 2. Validate (static analysis — no scheduler needed)

```bash
python -m metaflow_orchestrator_kit.validate ./my_scheduler/
# equivalent:
metaflow-orchestrator-validate ./my_scheduler/
```

Example output:

```
Validating: /path/to/my_scheduler/

  PASS  mfextinit_<name>.py exists
  PASS  DEPLOYER_IMPL_PROVIDERS_DESC has correct structure
  PASS  run_params uses list() not tuple()
  FAIL  METAFLOW_FLOW_CONFIG_VALUE in step env
        Problem: METAFLOW_FLOW_CONFIG_VALUE not found in my_scheduler_deployer.py
        Fix: Extract at compile time: from metaflow.flowspec import FlowStateItems; ...
  PASS  --branch passed to step commands
  PASS  retry_count reads from attempt, not hardcoded to 0
  PASS  DATASTORE_SYSROOT captured at compile time
  PASS  ENVIRONMENT_TYPE passed to step command
  PASS  from_deployment handles dotted names

Results: 8 passed, 1 failed
```

### 3. Test (one-command compliance suite)

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
# equivalent:
metaflow-orchestrator-test --scheduler-type windmill --deploy-args ...
```

This command:
1. Writes `ux_test_config_generated.yaml` automatically
2. Finds the test flows (from installed metaflow or from `--metaflow-src`)
3. Runs the compliance tests
4. Reports a clear pass/fail summary

### 4. Declare capabilities

```python
from metaflow_orchestrator_kit import Cap, REQUIRED

# REQUIRED is the minimum set every orchestrator must pass.
# Add optional capabilities your scheduler actually supports.
SUPPORTED_CAPABILITIES = REQUIRED | {Cap.NESTED_FOREACH, Cap.SCHEDULE}
```

### 5. Wire compliance into CI

```yaml
- name: Run compliance tests
  run: |
    python -m metaflow_orchestrator_kit.test \
      --scheduler-type my_scheduler \
      --deploy-args host=${{ secrets.SCHEDULER_HOST }}
```

Or use the generated `ux-tests-my_scheduler.yml` as a starting point.

## Extension package layout

```
your_package/
  metaflow_extensions/
    my_scheduler/
      plugins/
        mfextinit_my_scheduler.py     <- extension registration
        my_scheduler/
          my_scheduler_deployer.py    <- DeployerImpl subclass
          my_scheduler_objects.py     <- DeployedFlow / TriggeredRun
          my_scheduler_cli.py         <- CLI group
```

After `pip install -e .`, `Deployer(flow_file).my_scheduler(...)` is available with no other registration needed. Metaflow discovers `mfextinit_*.py` automatically.

## Common pitfalls

Every new orchestrator implementation hits the same bugs. The scaffold pre-solves most of them; the validator catches the rest before CI.

**1. `run_params` tuple vs list (`Cap.RUN_PARAMS`)** — Click's multi-value options return tuples. Passing a tuple to `trigger()` causes `TypeError` when two or more params are given. Fix: `run_params = list(run_params) if run_params else []`.

**2. `--branch` not forwarded to step subprocesses (`Cap.PROJECT_BRANCH`)** — `@project` reads `current.branch_name` from the `--branch` flag at step runtime. Without it, all step tasks produce an empty branch name. Fix: include `--branch <branch>` in every step command the scheduler launches.

**3. `METAFLOW_FLOW_CONFIG_VALUE` missing from container env (`Cap.CONFIG_EXPR`)** — `@config` and `@project` use this env var to reconstruct the config dict at task runtime. Without it, tasks run with empty config. Fix: read `flow._flow_state[FlowStateItems.CONFIGS]` at compile time and JSON-serialize it into the container environment.

**4. `retry_count` hardcoded to 0 (`Cap.RETRY`)** — Metaflow's `@retry` uses the attempt number to decide whether to retry. Hardcoding 0 means the flow always sees attempt 0 and never retries. Fix: derive from the scheduler's native counter (`AWS_BATCH_JOB_ATTEMPT`, Kubernetes `restartCount`, Airflow `try_number - 1`, etc.).

**5. `from_deployment()` fails on dotted names (`Cap.FROM_DEPLOYMENT`)** — DAG IDs for `@project`-decorated flows are dotted: `project.branch.FlowName`. Using the full string as a Python class name raises `SyntaxError`. Fix: `flow_name = identifier.split(".")[-1]`.

**6. `@conda` broken for in-process executors (`Cap.CONDA`)** — `@conda` uses a class-level `_metaflow_home` that is only set in `runtime_init()`. For subprocess-based orchestrators this is called automatically when the step subprocess re-enters the Metaflow runtime. For **in-process executors** (Dagster `execute_job()`, Windmill sync functions) `runtime_init()` is never called, leaving conda packages absent from `PYTHONPATH` and steps failing with `ModuleNotFoundError`. Fix: wrap the step command with `["conda", "run", "--no-capture-output", "-n", conda_env_name, "python", ...]`. For subprocess-based orchestrators, pass `--environment conda` to the step command (already in the generated scaffold).

**7. Extension not auto-discovered (`Deployer` missing `.my_scheduler()`)** — `Deployer(flow_file).my_scheduler()` raises `AttributeError` with no indication why. Metaflow reads `DEPLOYER_IMPL_PROVIDERS_DESC` from `mfextinit_<name>.py`; if it's missing, misnamed, in the wrong directory, or the descriptor is malformed, the deployer is silently not registered. Fix: ensure `mfextinit_<name>.py` lives at `metaflow_extensions/<name>/plugins/` and `DEPLOYER_IMPL_PROVIDERS_DESC = [("<name>", ".<name>.<name>_deployer.<Class>DeployerImpl")]`. Run `python -m metaflow_orchestrator_kit.validate .` to catch this before CI.

**8. Docker-based workers cannot reach the local filesystem** — Schedulers that run workers in Docker containers (Windmill, Prefect, Argo) isolate the worker filesystem from the host. The step command uses the absolute host path to the flow file (e.g. `/Users/me/project/flow.py`), but that path does not exist inside the container. The same applies to `METAFLOW_DATASTORE_SYSROOT_LOCAL`: if the sysroot path is a host-local directory, the worker writes to a different directory than the deployer reads from, so `wait_for_deployed_run()` polls forever.

**Recommended fix (production):** Build a custom worker Docker image that has Metaflow installed via `pip install metaflow` and use a shared object store (S3/MinIO) as the datastore. This avoids all filesystem sharing problems.

**Quick fix (local devstack only):** Add volume mounts to your docker-compose worker service and set `PYTHONPATH`:
```yaml
volumes:
  - /Users:/Users   # macOS — use /home:/home on Linux
  - /tmp:/tmp
```
**Warning:** Volume mounts expose your entire host user directory to the container, including your conda `site-packages`. Python running inside the container will discover and load all Metaflow extensions installed on the host — including any internal/private extensions that depend on services not available inside the container (e.g. a `service` metadata provider that requires an internal API). This causes cryptic failures like `Cannot locate metadata_provider plugin 'service'`. Mitigation: set `PYTHONPATH` to only the OSS metaflow source, not your full site-packages path, and do NOT include the extension package itself in `PYTHONPATH`:
```bash
# In the bash script emitted by the compiler (wrong):
export PYTHONPATH=/path/to/metaflow:/path/to/metaflow-myscheduler

# Correct: only the core source, not extension packages
export PYTHONPATH=/path/to/metaflow
```
If you still see extension-loading failures, the container's Python may discover `metaflow_extensions/` directories within the mounted source tree. The safest solution for local testing is to install Metaflow inside the worker container's init script:
```bash
pip install metaflow requests  # in the step's bash preamble
```

**9. Scheduler auth tokens expire** — If your scheduler issues short-lived auth tokens (Windmill, Kestra), tests that start a long-running deploy+trigger sequence may fail with 401 on the trigger API call because the token used at `create()` time has expired by the time `trigger()` is called. Fix: either use long-lived tokens (service account tokens in Windmill: `Settings > Users & Tokens > Tokens > Add token` with no expiry), or fetch a fresh token at the start of each `trigger()` call rather than caching the token from `create()`.

**10. Scheduler internal indexing delay after workflow creation** — Some schedulers (Mage, Prefect, Windmill) index or cache newly-created pipelines/DAGs asynchronously. If you make a second API call immediately after the creation POST (e.g. creating a schedule, listing runs, or triggering), the scheduler may return 500 or `'NoneType' object has no attribute 'uuid'` because the pipeline is not yet in the cache. Fix: add a short delay between `_create_pipeline()` / `_compile_workflow()` and any subsequent API call that references the newly-created resource. A 1–2 second sleep is enough for most schedulers. If the second call is not strictly required for the trigger to work (e.g. schedule creation for Mage), make it optional and catch failures gracefully:
```python
try:
    schedule_id = _create_api_trigger(client, pipeline_uuid)
except Exception:
    schedule_id = None  # non-fatal: trigger works without a registered schedule
```

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

## Example `ux_test_config.yaml`

```yaml
backends:
  - name: my-scheduler
    scheduler_type: my_scheduler
    cluster: null
    decospec: null
    deploy_args:
      host: http://localhost:8080
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
