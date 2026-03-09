# Pitfalls: Environment Variables

These pitfalls relate to environment variables that must be captured at compile time and
injected into every step subprocess. Missing any one of them causes silent correctness bugs.

---

**#2 `--branch` not forwarded to step subprocesses (`Cap.PROJECT_BRANCH`)**

`@project` reads `current.branch_name` from the `--branch` flag at step runtime. Without it, all step tasks produce an empty branch name and `@project`-aware flows behave as if running in the default branch.

Fix: include `--branch <branch>` in **every** step command the scheduler launches, not just the start step.

---

**#3 `METAFLOW_FLOW_CONFIG_VALUE` missing from container env (`Cap.CONFIG_EXPR`)**

`@config` and `@project` use this env var to reconstruct the config dict at task runtime. Without it, tasks run with empty config — `config_expr()` returns `None`, decorators use defaults.

```python
# Capture at compile time:
from metaflow.flowspec import FlowStateItems
flow_configs = flow._flow_state[FlowStateItems.CONFIGS]
config_env = {name: value for name, (value, _) in flow_configs.items() if value is not None}
if config_env:
    env["METAFLOW_FLOW_CONFIG_VALUE"] = json.dumps(config_env)
```

---

**#4 `retry_count` hardcoded to 0 (`Cap.RETRY`)**

Hardcoding 0 means the flow always sees attempt 0 and never retries. Derive from the scheduler's native counter. Note: most scheduler counters are 1-indexed — see pitfall #27.

Scheduler examples:
- AWS Batch: `AWS_BATCH_JOB_ATTEMPT` (0-indexed — no subtraction needed)
- Kubernetes: `restartCount` (0-indexed)
- Airflow: `context["ti"].try_number - 1` (1-indexed)
- Prefect: `max(0, task_run.run_count - 1)` (1-indexed)
- Temporal: `max(0, workflow_info.attempt - 1)` (1-indexed)

---

**#10 `METAFLOW_DATASTORE_SYSROOT_LOCAL` vs `--datastore-root` use different formats**

`METAFLOW_DATASTORE_SYSROOT_LOCAL` is the **parent** directory (no `.metaflow` suffix). `--datastore-root` includes the `.metaflow` subdirectory. Using the same value for both causes double-nesting and `MetaflowNotFound` on every artifact read.

```bash
# CORRECT:
METAFLOW_DATASTORE_SYSROOT_LOCAL=/tmp/mytest
--datastore-root /tmp/mytest/.metaflow
```

---

**#19 `--branch` must receive the raw user string, not the formatted project branch name**

`@project`'s `format_name()` converts a raw branch input (e.g. `abc123`) into a formatted name (e.g. `test.abc123`). Metaflow's `--branch` CLI option applies `format_name()` internally. If you pass the already-formatted string, format_name rejects it:

```
format_name: 'branch' must contain only lowercase alphanumeric characters and underscores
```

Fix: use `self.branch` (the raw input), not `self._project_info["branch"]` or `branch_name`.

---

**#20 `@Config` params must not be passed to the `init` command**

`flow._get_parameters()` returns both `@Parameter` and `@Config` objects. Passing a `@Config` name to `init` causes `Error: no such option: --cfg`.

```python
from metaflow.parameters import Config
params = [p for p in flow._get_parameters() if not isinstance(p, Config)]
```

---

**#23 Compile-time sysroot must not be overridden at runtime**

For Docker-worker schedulers, the container may inherit `METAFLOW_DATASTORE_SYSROOT_LOCAL` from its own environment, overriding the compile-time value baked into the step script. This causes metadata to be written to a different path than the deployer reads from.

```python
# WRONG — lets container env override compile-time sysroot:
sysroot = os.environ.get("METAFLOW_DATASTORE_SYSROOT_LOCAL") or COMPILED_SYSROOT
# CORRECT — use compile-time value and set it explicitly for the subprocess:
env["METAFLOW_DATASTORE_SYSROOT_LOCAL"] = COMPILED_SYSROOT
```

---

**#24 Template engines process `{` in env values**

Schedulers with template engines (Kestra/Pebble, Jinja2, Mustache) interpret `{{ ... }}` inside env var values. `METAFLOW_FLOW_CONFIG_VALUE` is JSON which contains `{` characters.

Fix: base64-encode the value at compile time and decode at runtime, or pass through a scheduler variable/secret rather than inlining the JSON directly:

```python
# Kestra pattern:
import base64
env["METAFLOW_FLOW_CONFIG_VALUE_B64"] = base64.b64encode(config_json.encode()).decode()
# In the task script: base64.b64decode(os.environ["METAFLOW_FLOW_CONFIG_VALUE_B64"]).decode()
```

---

**#11 Every step including `start` requires `--input-paths`**

Without it, the step subprocess fails with `UnboundLocalError`. Never pass an empty string for `--input-paths` — omit the flag entirely if there's nothing to pass.

```bash
--input-paths "${run_id}/_parameters/1"                             # start step
--input-paths "${run_id}/{parent_step}/1"                           # linear steps
--input-paths "${run_id}/branch_a/1,${run_id}/branch_b/1"          # join steps (comma-sep)
```
