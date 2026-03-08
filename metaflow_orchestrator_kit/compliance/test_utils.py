"""
Shared test utilities for compliance tests.

Ported from metaflow/test/ux/core/test_utils.py — adapted to be independent
of the metaflow core test tree.

These utilities are intentionally thin wrappers around the Metaflow
Runner/Deployer API so they stay in sync with the upstream API surface.
"""

import os
import time
from typing import Any, Dict, List, Optional

from metaflow import Deployer, Flow, Run, Runner, namespace
from metaflow.exception import MetaflowNotFound


def _resolve_flow_path(flow_name: str, flows_dir: Optional[str] = None) -> str:
    """
    Resolve a flow path.

    If flow_name is absolute it is returned as-is.  Otherwise it is resolved
    relative to flows_dir (if given) or the current working directory.
    """
    if os.path.isabs(flow_name):
        return flow_name
    if flows_dir:
        return os.path.join(flows_dir, flow_name.removeprefix("flows/"))
    return flow_name


def prepare_runner_deployer_args(tl_args: Dict[str, Any]) -> Dict[str, Any]:
    """Filter and set defaults for Runner/Deployer top-level arguments."""
    filtered = {k: v for k, v in tl_args.items() if v is not None and v != ""}
    filtered.setdefault("pylint", False)
    return filtered


def _evict_flow_module_cache(flow_path: str) -> None:
    """Remove a flow file from click_api's loaded_modules cache.

    This is needed for test isolation: when a flow uses FlowMutator/config_value,
    the module must be reloaded for each test so that the mutator sees fresh config.
    """
    try:
        from metaflow.runner import click_api

        click_api.loaded_modules.pop(flow_path, None)
    except Exception:
        pass


def deploy_flow_to_scheduler(
    flow_name: str,
    tl_args: Dict[str, Any],
    scheduler_args: Dict[str, Any],
    deploy_args: Dict[str, Any],
    scheduler_type: str,
    flows_dir: Optional[str] = None,
):
    """Deploy a flow to a scheduler (e.g. step-functions, argo-workflows)."""
    from metaflow import metaflow_version

    flow_path = _resolve_flow_path(flow_name, flows_dir=flows_dir)
    print(
        f"Deploying flow {flow_path} to scheduler {scheduler_type} "
        f"using metaflow: {metaflow_version.get_version()}"
    )

    _evict_flow_module_cache(flow_path)

    filtered_tl_args = prepare_runner_deployer_args(tl_args)
    deployer = Deployer(flow_file=flow_path, **filtered_tl_args)

    normalized_sched_type = scheduler_type.replace("-", "_")
    norm_sched_args = dict(scheduler_args)
    # Drop 'cluster' — it's the k8s namespace which comes from
    # METAFLOW_KUBERNETES_NAMESPACE in the global config, not a create() argument.
    norm_sched_args.pop("cluster", None)
    deployed_flow = getattr(deployer, normalized_sched_type)(**norm_sched_args).create(
        **deploy_args
    )
    print(f"Deployed workflow {deployed_flow.name}")
    return deployed_flow


def run_flow_with_env(
    flow_name: str,
    runner_args: Optional[Dict[str, Any]] = None,
    flows_dir: Optional[str] = None,
    **tl_args,
):
    """Run a flow locally using Runner."""
    from metaflow import metaflow_version

    flow_path = _resolve_flow_path(flow_name, flows_dir=flows_dir)
    print(f"Running flow {flow_path} with metaflow: {metaflow_version.get_version()}")

    _evict_flow_module_cache(flow_path)

    runner_args = runner_args or {}
    filtered_tl_args = prepare_runner_deployer_args(tl_args)
    print(f"Runner args: {runner_args}, TL args: {filtered_tl_args}")

    with Runner(flow_path, **filtered_tl_args).run(**runner_args) as running:
        return running.run


def _is_failed_status(status: Optional[str]) -> bool:
    """Return True if the status string indicates a terminal failure."""
    return status is not None and status.upper() in ("FAILED", "TIMED_OUT", "ABORTED")


def wait_for_deployed_run(
    deployed_flow,
    timeout: int = 3600,
    run_kwargs: Optional[Dict[str, Any]] = None,
    polling_interval: int = 3,
):
    """Trigger a deployed flow and wait for it to complete."""
    print(f"Deployed flow {deployed_flow.name}")
    run_kwargs = run_kwargs or {}
    triggered_run = deployed_flow.trigger(**run_kwargs)

    start_time = time.time()
    while triggered_run.run is None:
        if time.time() - start_time > timeout:
            raise RuntimeError(f"Run failed to start within {timeout} seconds")
        status = triggered_run.status
        if _is_failed_status(status):
            raise RuntimeError(
                f"Deployed run failed before starting (status: {status})"
            )
        print("Waiting for run to start...")
        time.sleep(polling_interval)

    print(f"Run {triggered_run.run.id} started")

    while not triggered_run.run.finished:
        if time.time() - start_time > timeout:
            raise RuntimeError(
                f"Run {triggered_run.run.id} failed to complete within {timeout} seconds"
            )
        status = triggered_run.status
        if _is_failed_status(status):
            raise RuntimeError(f"Run {triggered_run.run.id} failed (status: {status})")
        print(f"Waiting for run {triggered_run.run.id} to complete...")
        time.sleep(polling_interval)

    print(f"Run {triggered_run.run.id} completed")
    return triggered_run.run


def track_runs_by_tags(
    flow_name: str, tags: List[str], timeout: int = 10, polling_interval: int = 60
) -> List[str]:
    """Poll for runs matching flow_name and tags, returning their pathspecs."""
    start_time = time.time()
    namespace(None)
    runs = []
    flow_obj = None

    while time.time() - start_time < timeout * 60:
        if flow_obj is None:
            try:
                flow_obj = Flow(flow_name)
            except MetaflowNotFound:
                print(f"Flow {flow_name} not found, waiting...")
                time.sleep(polling_interval)
                continue

        runs = list(flow_obj.runs(*tags))
        if len(runs) > 0 and all(r.finished_at is not None for r in runs):
            break

        print(f"Found {len(runs)} runs, waiting for completion...")
        time.sleep(polling_interval)

    return [r.pathspec for r in runs]


def verify_single_run(flow_name: str, tags: List[str], timeout: int = 60) -> Run:
    """Verify exactly one run exists for the given flow and tags."""
    run_pathspecs = track_runs_by_tags(flow_name, tags, timeout)

    if len(run_pathspecs) != 1:
        raise RuntimeError(
            f"Expected 1 run for flow {flow_name} with tags {tags}, "
            f"got {len(run_pathspecs)}"
        )

    run = Run(run_pathspecs[0], _namespace_check=False)
    print(f"Found run {run.id} for flow {flow_name}")

    if not run.successful:
        raise RuntimeError(f"Run {run.id} failed")

    return run
