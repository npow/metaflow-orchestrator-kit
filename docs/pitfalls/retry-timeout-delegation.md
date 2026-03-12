# Pitfalls: Retry and Timeout Delegation

These pitfalls relate to retry and timeout handling across orchestrators.

---

**#41 Manual retry loops instead of orchestrator-native retry**

Implementing retry as a Python `for` loop inside generated step code:

```python
# WRONG — manual retry loop in generated code
for retry_count in range(max_retries + 1):
    result = subprocess.run(cmd + ["--retry-count", str(retry_count)], ...)
    if result.returncode == 0:
        break
```

Problems:
- Hides retry state from the orchestrator's UI (no retry counter visible)
- Cannot be configured/overridden from the orchestrator's dashboard
- If the orchestrator's own retry triggers, you get retries-of-retries
- No exponential backoff or jitter without manual implementation

Fix: delegate to the orchestrator's native retry mechanism and derive `--retry-count` from its attempt counter:
- **Flyte**: `@task(retries=N)` — derive count from Flyte's execution context
- **Dagster**: `RetryPolicy(max_retries=N)` on the `@op`
- **Prefect**: `@task(retries=N)` — derive from `task_run.run_count - 1`
- **Kestra**: `retry:` block in YAML
- **Windmill**: `retry:` config on module — derive from `WM_FLOW_RETRY_COUNT`
- **Temporal**: activity retry policy
- **Mage**: `retry_config` on block — derive from `kwargs.get('retry')`

---

**#42 Missing `@timeout` support**

Every orchestrator should extract Metaflow's `@timeout(seconds=N)` decorator and map it to the orchestrator's native timeout mechanism. Without it, hung steps run forever.

Orchestrator-native timeout mapping:
- **Flyte**: `timeout=timedelta(seconds=N)` in `@task` decorator
- **Dagster**: `dagster/op_execution_timeout` tag
- **Prefect**: `timeout_seconds=N` in `@task` decorator
- **Kestra**: ISO 8601 duration in YAML (`timeout: PT300S`)
- **Windmill**: `timeout` field on module dict
- **Temporal**: `start_to_close_timeout` in activity options
- **Mage**: `timeout=N` on `subprocess.run()` in generated block code

For subprocess-based orchestrators, also pass `timeout=N` to `subprocess.run()` as a safety net.
