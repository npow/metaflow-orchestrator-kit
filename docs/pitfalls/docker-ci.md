# Pitfalls: Docker Workers & CI

These pitfalls apply specifically to schedulers that run step subprocesses inside Docker
containers (Windmill, Mage, Kestra, Argo, Prefect with Docker workers) and to GHA CI setup.

---

**#8 Docker workers do not share `/tmp` between steps**

Each step runs in a separate container. Files written to `/tmp` in the init step are NOT visible to subsequent step containers. Options:
- Use `same_worker: true` if the scheduler supports it (Windmill)
- Use a shared external store (Redis, S3)
- Use the scheduler's native return-value mechanism to pass the run_id

---

**#9 Docker workers cannot reach host filesystem (flow file path, sysroot)**

Step scripts reference the absolute host path to `flow_file` and `METAFLOW_DATASTORE_SYSROOT_LOCAL`. These paths don't exist inside worker containers.

For **production**: build a custom worker image with Metaflow installed and use S3/MinIO as datastore.

For **local/CI testing**: add volume mounts so the same paths are accessible inside containers:
```bash
docker run -v /Users:/Users ...         # macOS
docker run -v /home:/home ...           # Linux
```
Set `PYTHONPATH` only to OSS metaflow source to avoid loading private extensions from host site-packages.

---

**#25 GHA Docker-worker schedulers need workspace and `/tmp` volume mounts**

In GHA CI, the workspace path (e.g. `/home/runner/work/...`) is baked into step scripts at compile time but doesn't exist inside worker containers.

```yaml
docker run -d \
  --name my_scheduler_worker \
  --network host \
  -v "${{ github.workspace }}":"${{ github.workspace }}" \   # flow file + PYTHONPATH
  -v /tmp:/tmp \                                             # sysroot if in /tmp
  -e MODE=worker \
  my_scheduler_image:latest
```

Without these mounts, every step subprocess fails with `FileNotFoundError` or writes artifacts the test process can never find.

---

**#26 Root-owned artifact files from Docker workers are unreadable by the test process**

Docker workers run as root. Metaflow's local datastore calls `os.chmod(path, 0o600)` on every artifact file regardless of umask. Root-owned 600 files are unreadable by the GHA `runner` user → all artifact assertions fail with `PermissionError`.

A `sitecustomize.py` umask trick only affects directory creation, not Metaflow's explicit `chmod` calls.

Fix: run pytest as root (GHA runners have passwordless sudo):
```yaml
- name: Run deployer tests
  run: |
    sudo -E env "PATH=$PATH" "HOME=$HOME" \
      "METAFLOW_DATASTORE_SYSROOT_LOCAL=$HOME" \
      python -m pytest ...
```

---

**#29 GHA `${{ env.HOME }}` is invalid in job-level `env:` blocks**

GHA expressions are only evaluated inside `run:` steps, not in job-level `env:` blocks. `${{ env.HOME }}` in a job `env:` block causes "context access of 'HOME' is not allowed here".

```yaml
# WRONG — job-level env: block:
env:
  METAFLOW_DATASTORE_SYSROOT_LOCAL: ${{ env.HOME }}   # error

# CORRECT — use $GITHUB_ENV:
- name: Set sysroot
  run: echo "METAFLOW_DATASTORE_SYSROOT_LOCAL=$HOME" >> "$GITHUB_ENV"
```

---

**#31 GHA `setup-miniconda` adds `condabin/` to PATH, not the full conda `bin/`**

`actions/setup-miniconda@v3` adds `/usr/share/miniconda/condabin` to `$PATH`. Metaflow's `@conda`/`@pypi` resolver (micromamba) is in the full `bin/` directory. Subprocess-based orchestrators (Dagster, Temporal) spawn workers that inherit `os.environ`, so micromamba is not found.

```yaml
- name: Add conda bin to PATH for subprocess access
  run: echo "/usr/share/miniconda/bin" >> $GITHUB_PATH
```

---

**#32 Parallel `@conda` tests share micromamba's repodata cache → SOLV corruption**

Concurrent `micromamba install` calls write to `~/.mamba/pkgs/cache/` simultaneously, corrupting SOLV files and causing `libsolv` errors.

Fix: use `--dist=loadfile` to keep tests from the same file on one worker:
```yaml
# In ux-tests.yml pytest args:
--dist=loadfile   # @conda tests run sequentially, preventing SOLV file races
```

---

**#33 K8s task pod sysroot path differs from host path**

When Flyte, Argo, or K8s-based orchestrators mount a shared volume (PVC) into task pods, the in-pod mount path (e.g. `/var/lib/flyte/metaflow_meta`) differs from the host-side Docker volume path (e.g. `/var/lib/docker/volumes/flyte-sandbox/_data/metaflow_meta`). The deployer and test process use the host path; task containers use the pod path. Configure them independently:

```yaml
# GHA: resolve host-side path dynamically
- name: Set sysroot from Docker volume
  run: |
    DOCKER_VOL=$(docker volume inspect flyte-sandbox --format '{{ .Mountpoint }}')
    echo "METAFLOW_DATASTORE_SYSROOT_LOCAL=${DOCKER_VOL}/metaflow_meta" >> "$GITHUB_ENV"
    sudo chmod -R 777 "${DOCKER_VOL}/metaflow_meta"   # needed: /var/lib/docker/ is root-owned

# In the task pod (PodTemplate or --envvars):
# METAFLOW_DATASTORE_SYSROOT_LOCAL=/var/lib/flyte/metaflow_meta
```

---

**#6 `@conda` broken for in-process executors (`Cap.CONDA`)**

`@conda` uses a class-level `_metaflow_home` set only in `runtime_init()`. For **in-process executors** (Dagster `execute_job()`), `runtime_init()` is never called — conda packages are absent from `PYTHONPATH`.

For subprocess-based orchestrators: pass `--environment conda` to the step command. Metaflow's `runtime_init()` runs automatically.

For in-process executors: wrap the step command:
```python
["conda", "run", "--no-capture-output", "-n", conda_env_name, "python", flow_file, "step", ...]
```

---

**#38 Docker container HOME differs from host HOME — datastore file search must check both**

When running Mage (or similar) in Docker with `docker run -v "$HOME:$HOME"`, the container's HOME is `/root` but GHA's HOME is `/home/runner`. The step subprocess writes artifacts to `METAFLOW_DATASTORE_SYSROOT_LOCAL` (set to `$HOME=/home/runner`), but the data may end up at either path depending on container configuration.

When reading datastore files (e.g., `_foreach_num_splits` for foreach), search multiple candidate directories:

```python
candidates = [
    env.get("METAFLOW_DATASTORE_SYSROOT_LOCAL", ""),
    "/home/runner",
    "/root",
    os.environ.get("HOME", ""),
]
for cand in candidates:
    path = os.path.join(cand, ".metaflow", flow, run_id, step, task_id)
    if os.path.isdir(path):
        break
```

Without this, foreach_count defaults to 1 and the foreach body only processes one item.
