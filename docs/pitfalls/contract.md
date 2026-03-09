# Pitfalls: Contract & API (Deployer Protocol)

These pitfalls relate to the `DeployerImpl` / `DeployedFlow` / `TriggeredRun` contract.
Every orchestrator implementation hits at least one of these.

---

**#1 `run_params` tuple vs list (`Cap.RUN_PARAMS`)**

Click's multi-value options return tuples. Passing a tuple to `trigger()` causes `TypeError` when two or more params are given.

```python
# WRONG:
run_params = tuple(f"{k}={v}" for k, v in kwargs.items())
# CORRECT:
run_params = list(run_params) if run_params else []
```

---

**#5 `from_deployment()` fails on dotted names (`Cap.FROM_DEPLOYMENT`)**

DAG IDs for `@project`-decorated flows are dotted: `project.branch.FlowName`. Using the full string as a Python class name raises `SyntaxError`.

```python
flow_name = identifier.split(".")[-1]
```

---

**#13 `init` command requires `--task-id`**

OSS Metaflow's `init` requires `--task-id`. Always include `--task-id 1` (init always runs as task 1). Some internal forks made it optional — OSS does not.

---

**#16 `trigger` CLI must write `deployer_attribute_file` BEFORE executing steps**

The Metaflow `Deployer` blocks waiting for `deployer_attribute_file` to appear. For orchestrators that execute steps synchronously in the trigger subprocess, writing the file after all steps complete causes the entire flow execution to happen inside the `trigger()` call.

```python
# CORRECT: write file FIRST, then execute
if deployer_attribute_file:
    with open(deployer_attribute_file, "w") as f:
        json.dump({"pathspec": pathspec}, f)
_execute_flow_steps(run_id, ...)
```

---

**#21 `deployer_kwargs` must be stored in `_deployer_kwargs` backing field**

`DeployerImpl` exposes `deployer_kwargs` as a read-only property. Assigning `self.deployer_kwargs = deployer_kwargs` in `__init__` raises `AttributeError`. The scaffold pre-solves this.

---

**#27 Scheduler attempt counters are 1-indexed; Metaflow's `--retry-count` is 0-indexed**

Prefect `run_count`, Temporal `attempt`, Airflow `try_number` all start at 1 for the first execution. Metaflow's `--retry-count` is 0-indexed.

```python
# WRONG — passes 1 for the first attempt:
retry_count = scheduler_attempt_counter
# CORRECT:
retry_count = max(0, scheduler_attempt_counter - 1)
```

This is separate from pitfall #4 (hardcoding 0): both are wrong. The correct value is `max(0, native_counter - 1)`.

---

**#28 Use `Popen` + `communicate()` instead of `subprocess.run()` for step subprocesses**

`subprocess.run()` blocks and does not propagate cancellation signals. When a scheduler cancels an activity (timeout, SIGTERM, user cancel), the Metaflow step subprocess becomes an orphan.

```python
proc = subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
try:
    stdout, stderr = proc.communicate()
except BaseException:          # catches SIGTERM, KeyboardInterrupt, threading cancel
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
    raise
if proc.returncode != 0:
    raise RuntimeError("Step %r failed (exit %d): %s" % (step_name, proc.returncode, stderr[-500:]))
```

---

**#30 `init` parameters must be CLI flags (`--name value`), not env vars**

`METAFLOW_PARAMETERS` does not exist in OSS Metaflow. Parameters must be passed as `--param-name value` CLI flags. Also filter out `@Config` params (pitfall #20).

```python
from metaflow.parameters import Config
params_for_init = [(n, p) for n, p in flow._get_parameters() if not isinstance(p, Config)]
init_cmd = ["python", flow_file, "--no-pylint", "init", "--run-id", run_id, "--task-id", "1"]
for name, param in params_for_init:
    if name in run_kwargs:
        init_cmd += ["--%s" % name, str(run_kwargs[name])]
```

---

**#18 `NotSupportedException` must document an architectural reason**

The validator checks that all `NotSupportedException` and `pytest.skip` calls include an explanation (≥50 chars, with a keyword such as `because`, `requires`, `cannot`, `static`, `runtime`, or `model`).

```python
# CORRECT:
raise NotSupportedException(
    "Nested foreach requires dynamic task creation at runtime. "
    "MyScheduler's graph is defined statically at compile time "
    "and cannot express a foreach body that is itself a foreach."
)
# WRONG — too vague:
raise NotSupportedException("Nested foreach not supported")
```
