# Pitfalls: Foreach Artifact Reading

These pitfalls relate to reading internal Metaflow artifacts (`_foreach_num_splits`, `_transition`) from the datastore at runtime.

---

**#38 Reading `_foreach_num_splits` by cracking open pickle blobs**

Orchestrators need to read `_foreach_num_splits` after a foreach step to know how many items to fan out. A common but fragile approach is to manually navigate the local datastore directory structure, parse `data.json` to find the blob SHA, then `pickle.load(gzip.decompress(...))` the blob.

This breaks when:
- The datastore format changes (encoding, compression)
- The datastore is remote (S3, Azure, GCS) rather than local
- The blob is stored with a different compression scheme

Fix: use the FlowDataStore API, which handles all encoding/compression transparently:

```python
from metaflow.datastore import FlowDataStore
from metaflow.plugins import DATASTORES

_impl = next(d for d in DATASTORES if d.TYPE == DATASTORE_TYPE)
_root = _impl.get_datastore_root_from_config(lambda *a: None)
_fds = FlowDataStore(FLOW_NAME, None, storage_impl=_impl, ds_root=_root)
_tds = _fds.get_task_datastore(run_id, step_name, task_id, attempt=0, mode='r')
num_splits = int(_tds['_foreach_num_splits'])
```

Reference: Flyte's `_read_condition_branch()` in `_codegen.py` is the canonical pattern.

---

**#39 Reading `_transition` by cracking open pickle blobs**

Same as #38 but for the `_transition` artifact used by split-switch (conditional) steps. Use FlowDataStore API instead of manual pickle deserialization.

```python
_tds = _fds.get_task_datastore(run_id, step_name, task_id, attempt=0, mode='r')
_transition = _tds['_transition']
branch = _transition[0][0] if _transition and _transition[0] else 'unknown'
```

---

**#40 Spawning a subprocess just to read one artifact**

Some orchestrators (Mage) spawn an entire Python subprocess to read `_foreach_num_splits` from disk. This adds latency, creates error-handling complexity, and introduces hardcoded path candidates. The FlowDataStore API can be called directly in the same process.
