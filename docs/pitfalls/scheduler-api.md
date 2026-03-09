# Pitfalls: Scheduler-Specific API

These pitfalls relate to scheduler API behavior: auth, async indexing,
CLI option placement, and extension registration.

---

**#7 Extension not auto-discovered (`Deployer` missing `.my_scheduler()`)**

`Deployer(flow_file).my_scheduler()` raises `AttributeError` with no indication why. Two common causes:

1. `metaflow_extensions/__init__.py` exists — must NOT (implicit namespace package)
2. `DEPLOYER_IMPL_PROVIDERS_DESC` missing, misnamed, or malformed in `mfextinit_<name>.py`

Fix: `mfextinit_<name>.py` must be at `metaflow_extensions/<name>/plugins/` with the correct descriptor. Run `python -m metaflow_orchestrator_kit.validate .` to catch before CI.

---

**#12 `--run-param` is not an OSS Metaflow option**

Some internal forks added `--run-param "name=value"` to `init`. OSS Metaflow does not have this — it causes `Error: no such option: --run-param`. Use `--param-name value` CLI flags instead (see pitfall #30 in [contract.md](contract.md)).

---

**#14 `--tag` must come after the subcommand, not before**

`--tag` is a **step-level** option, not a global option. Placing it before `step` or `init` causes `Error: no such option: --tag`.

```bash
# WRONG:
python flow.py --tag my_tag step start ...
# CORRECT:
python flow.py step start --tag my_tag ...
```

---

**#15 Scheduler auth tokens expire**

Short-lived tokens (Windmill, Kestra) may expire between `create()` and `trigger()` in long-running tests or low-traffic schedulers. Fix: use long-lived service account tokens, or fetch a fresh token at the start of each `trigger()` call rather than reusing the one from deploy time.

---

**#17 Scheduler async indexing delay after creation**

Some schedulers (Mage, Prefect, Windmill) index newly-created pipelines asynchronously. Secondary API calls immediately after creation (schedule creation, run listing) may return 500 or `NoneType`. Fix: 1–2 second sleep after creation, or make secondary calls non-fatal:

```python
try:
    schedule_id = _create_api_trigger(client, pipeline_uuid)
except Exception:
    schedule_id = None  # look up at trigger time instead
```

---

**#22 GHA matrix jobs produce conflicting coverage artifact names**

When matrix jobs upload coverage artifacts with the same name, GitHub returns HTTP 409. Fix: append the matrix key as a suffix:

```yaml
- uses: actions/upload-artifact@v4
  with:
    name: coverage-${{ matrix.test }}   # unique per matrix cell
    path: coverage.xml
    if-no-files-found: ignore
```
