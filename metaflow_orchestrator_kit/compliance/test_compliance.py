"""
Orchestrator compliance tests — verifies the contract every backend must satisfy.

These tests are not a re-test of basic functionality; they are targeted regression
tests for the specific bugs that every new orchestrator implementation gets wrong.
Each test documents WHY the requirement exists, not just WHAT it checks.

The tests are keyed to OrchestratorCapabilities (Cap).  REQUIRED capabilities
are always tested and fail if the orchestrator does not implement them.  OPTIONAL
capabilities are skipped if the orchestrator does not declare support.

Run all compliance tests across all backends defined in ux_test_config.yaml:
    pytest metaflow_orchestrator_kit/compliance/ --ux-config=ux_test_config.yaml -v

Run compliance tests for a specific backend only:
    pytest metaflow_orchestrator_kit/compliance/ \\
        --ux-config=ux_test_config.yaml \\
        --only-backend step-functions -v

Integrate into an existing orchestrator extension's CI by adding this package
as a test dependency and importing the compliance fixtures via conftest.py.
"""

import uuid
import pytest

pytestmark = [pytest.mark.compliance, pytest.mark.scheduler_only]

from metaflow_orchestrator_kit.capabilities import Cap

from .test_utils import (
    deploy_flow_to_scheduler,
    wait_for_deployed_run,
)


def _require_cap(scheduler_config, cap: Cap, unsupported_schedulers: dict = None):
    """
    Check whether the scheduler declares support for a capability.

    For REQUIRED capabilities this always passes (the test itself will fail if
    the implementation is broken).

    For OPTIONAL capabilities this skips the test when the scheduler is in the
    known-unsupported set.  Pass ``unsupported_schedulers`` as a dict mapping
    scheduler_type -> skip reason string.
    """
    from metaflow_orchestrator_kit.capabilities import OPTIONAL

    if cap not in OPTIONAL:
        return  # REQUIRED — never skip

    if unsupported_schedulers and scheduler_config.scheduler_type in unsupported_schedulers:
        pytest.skip(unsupported_schedulers[scheduler_config.scheduler_type])


# ---------------------------------------------------------------------------
# test_run_params_multiple_values
#
# WHY: Click's multi-value options return tuples.  If an orchestrator passes
# run_params directly to trigger() without converting to a list, passing two
# or more run params causes a TypeError deep inside the trigger implementation.
# This test forces the code path: deploy a flow with two params and trigger
# with both.  If run_params is a tuple the call fails; if it is a list it
# succeeds.
#
# Capability: Cap.RUN_PARAMS (REQUIRED)
# ---------------------------------------------------------------------------


@pytest.mark.compliance
@pytest.mark.scheduler_only
def test_run_params_multiple_values(
    exec_mode, decospecs, compute_env, tag, scheduler_config
):
    """Deployer trigger must accept a list for run_params, not a tuple."""
    if exec_mode != "deployer":
        pytest.skip("compliance test requires deployer mode")

    trigger_param = str(uuid.uuid4())[:8]
    test_unique_tag = f"test_compliance_run_params_{exec_mode}"
    combined_tags = tag + [test_unique_tag]

    tl_args = {
        "env": {
            "METAFLOW_CLICK_API_PROCESS_CONFIG": "1",
            **compute_env,
        },
        "decospecs": decospecs,
    }

    deployed_flow = deploy_flow_to_scheduler(
        flow_name="config/mutable_flow.py",
        tl_args=tl_args,
        scheduler_args={"cluster": scheduler_config.cluster},
        deploy_args={"tags": combined_tags, **(scheduler_config.deploy_args or {})},
        scheduler_type=scheduler_config.scheduler_type,
    )

    # Pass two run_params as a list.  If the orchestrator passes a tuple here,
    # the trigger() implementation raises TypeError before the run starts.
    run_kwargs = {"trigger_param": trigger_param, "param2": "48"}
    run = wait_for_deployed_run(deployed_flow, run_kwargs=run_kwargs)

    assert (
        run.successful
    ), "Run was not successful (check that run_params is a list, not a tuple)"
    assert (
        run["start"].task.data.trigger_param == trigger_param
    ), "trigger_param not propagated — run_params may have been dropped"
    assert (
        run["start"].task.data.param2 == "48"
    ), "param2 not propagated — only the first run_param was used (tuple vs list bug)"


# ---------------------------------------------------------------------------
# test_branch_propagated_to_steps
#
# WHY: @project derives branch_name from the --branch CLI flag.  Orchestrators
# that compile a step command for the scheduler but forget to forward --branch
# to each step subprocess produce an empty or wrong branch in step tasks.
# The HelloProjectFlow stores current.branch_name in self.branch at the end
# step, so we can verify it matches the branch we passed at deploy time.
#
# Capability: Cap.PROJECT_BRANCH (REQUIRED)
# ---------------------------------------------------------------------------


@pytest.mark.compliance
@pytest.mark.scheduler_only
def test_branch_propagated_to_steps(
    exec_mode, decospecs, compute_env, tag, scheduler_config
):
    """--branch must be forwarded to each step subprocess, not just the start command."""
    if exec_mode != "deployer":
        pytest.skip("compliance test requires deployer mode")

    branch = str(uuid.uuid4())[:8]
    test_unique_tag = f"test_compliance_branch_{exec_mode}"
    combined_tags = tag + [test_unique_tag]

    tl_args = {
        "env": compute_env,
        "decospecs": decospecs,
        "branch": branch,
    }

    deployed_flow = deploy_flow_to_scheduler(
        flow_name="basic/helloproject.py",
        tl_args=tl_args,
        scheduler_args={"cluster": scheduler_config.cluster},
        deploy_args={"tags": combined_tags, **(scheduler_config.deploy_args or {})},
        scheduler_type=scheduler_config.scheduler_type,
    )

    run = wait_for_deployed_run(deployed_flow)

    assert run.successful, "Run was not successful"
    rbranch = run["end"].task.data.branch
    expected = "test." + branch
    assert rbranch == expected, (
        f"Branch name mismatch: got {rbranch!r}, expected {expected!r}. "
        "This usually means --branch was not forwarded to step subprocesses."
    )


# ---------------------------------------------------------------------------
# test_retry_count_from_scheduler
#
# WHY: Metaflow's @retry decorator uses the attempt number to decide whether
# to retry.  The attempt number must be derived from the scheduler's native
# attempt/retry counter, NOT hardcoded to 0.  When hardcoded, the flow always
# sees attempt=0 and thinks the task succeeded on the first try even when the
# scheduler is actually executing a retry.
#
# retry_flow.py has a step that deliberately fails on attempt 0 and succeeds
# on attempt 1.  If attempt is always 0, the step always fails.
#
# Capability: Cap.RETRY (REQUIRED)
# ---------------------------------------------------------------------------


@pytest.mark.compliance
@pytest.mark.scheduler_only
def test_retry_count_from_scheduler(
    exec_mode, decospecs, compute_env, tag, scheduler_config
):
    """Retry attempt number must come from the scheduler, not hardcoded to 0."""
    if exec_mode != "deployer":
        pytest.skip("compliance test requires deployer mode")

    test_unique_tag = f"test_compliance_retry_{exec_mode}"
    combined_tags = tag + [test_unique_tag]

    tl_args = {
        "env": compute_env,
        "decospecs": decospecs,
    }

    deployed_flow = deploy_flow_to_scheduler(
        flow_name="basic/retry_flow.py",
        tl_args=tl_args,
        scheduler_args={"cluster": scheduler_config.cluster},
        deploy_args={"tags": combined_tags, **(scheduler_config.deploy_args or {})},
        scheduler_type=scheduler_config.scheduler_type,
    )

    run = wait_for_deployed_run(deployed_flow)

    assert run.successful, (
        "Run was not successful — if @retry fails, the scheduler may be "
        "passing retry_count=0 instead of deriving it from the native attempt number."
    )
    attempts = run["flaky"].task.data.attempts
    assert attempts == 1, (
        f"Expected flaky step to succeed on attempt 1, but got attempts={attempts}. "
        "This means retry_count is hardcoded to 0 instead of reading the scheduler attempt."
    )


# ---------------------------------------------------------------------------
# test_config_value_propagated
#
# WHY: @config and @project use METAFLOW_FLOW_CONFIG_VALUE to carry the
# serialized config dict from the deployer into each step subprocess.  Without
# this env var, tasks run with empty/default config and @project name is wrong.
#
# config_simple.py reads a config that sets project_name; the project tag on
# the run reflects whether config was properly propagated at task runtime.
#
# Capability: Cap.CONFIG_EXPR (REQUIRED)
# ---------------------------------------------------------------------------


@pytest.mark.compliance
@pytest.mark.scheduler_only
def test_config_value_propagated(
    exec_mode, decospecs, compute_env, tag, scheduler_config
):
    """METAFLOW_FLOW_CONFIG_VALUE must be injected so @config/@project work in tasks."""
    if exec_mode != "deployer":
        pytest.skip("compliance test requires deployer mode")

    trigger_param = str(uuid.uuid4())[:8]
    test_unique_tag = f"test_compliance_config_{exec_mode}"
    combined_tags = tag + [test_unique_tag]

    # Override the config so project_name differs from the default.
    config_value = [
        ("cfg_default_value", {"a": {"project_name": "compliance_project", "b": "99"}})
    ]

    tl_args = {
        "env": {
            "METAFLOW_CLICK_API_PROCESS_CONFIG": "1",
            **compute_env,
        },
        "package_suffixes": ".py,.json",
        "config_value": config_value,
        "decospecs": decospecs,
    }

    deployed_flow = deploy_flow_to_scheduler(
        flow_name="config/config_simple.py",
        tl_args=tl_args,
        scheduler_args={"cluster": scheduler_config.cluster},
        deploy_args={"tags": combined_tags, **(scheduler_config.deploy_args or {})},
        scheduler_type=scheduler_config.scheduler_type,
    )

    run = wait_for_deployed_run(
        deployed_flow, run_kwargs={"trigger_param": trigger_param}
    )

    assert run.successful, "Run was not successful"

    # The project tag is set by @project using the config-derived project_name.
    # If METAFLOW_FLOW_CONFIG_VALUE was not injected, the project tag will use
    # the default project_name ("config_project") instead of "compliance_project".
    expected_project_tag = "project:compliance_project"
    assert expected_project_tag in run.tags, (
        f"Expected tag {expected_project_tag!r} not found in {sorted(run.tags)}. "
        "METAFLOW_FLOW_CONFIG_VALUE was likely not injected into step subprocesses."
    )

    end_task = run["end"].task
    assert end_task.data.trigger_param == trigger_param, "trigger_param not propagated"
    assert end_task.data.config_val_2 == "99", (
        f"config_val_2 should be '99' (from override), got {end_task.data.config_val_2!r}. "
        "Config was not propagated to tasks."
    )


# ---------------------------------------------------------------------------
# test_nested_foreach_or_skip
#
# WHY: Nested foreach (foreach inside foreach) is not universally supported.
# Orchestrators that do not support it MUST call pytest.skip() with a clear
# reason string rather than silently producing a wrong or partial result.
# This test verifies that if the scheduler runs nested foreach, the result is
# correct; if it does not support it, it must say so explicitly.
#
# Capability: Cap.NESTED_FOREACH (OPTIONAL)
# ---------------------------------------------------------------------------


@pytest.mark.compliance
@pytest.mark.scheduler_only
def test_nested_foreach_or_skip(
    exec_mode, decospecs, compute_env, tag, scheduler_config
):
    """
    Nested foreach must either work correctly or skip with a clear reason string
    containing 'not supported'.
    """
    if exec_mode != "deployer":
        pytest.skip("compliance test requires deployer mode")

    _require_cap(
        scheduler_config,
        Cap.NESTED_FOREACH,
        unsupported_schedulers={
            "airflow": (
                "Nested foreach is not supported by the Airflow deployer: the DAG codegen "
                "cannot represent dynamic fan-out inside a foreach body step."
            ),
            "flyte": (
                "Nested foreach is not supported by the Flyte deployer: the codegen wires "
                "foreach-body steps as fixed tasks inside a @dynamic expander and cannot "
                "recurse to produce a second level of @dynamic fan-out."
            ),
        },
    )

    test_unique_tag = f"test_compliance_nested_foreach_{exec_mode}"
    combined_tags = tag + [test_unique_tag]

    tl_args = {
        "env": compute_env,
        "decospecs": decospecs,
    }

    deployed_flow = deploy_flow_to_scheduler(
        flow_name="dag/nested_foreach_flow.py",
        tl_args=tl_args,
        scheduler_args={"cluster": scheduler_config.cluster},
        deploy_args={"tags": combined_tags, **(scheduler_config.deploy_args or {})},
        scheduler_type=scheduler_config.scheduler_type,
    )

    run = wait_for_deployed_run(deployed_flow)

    assert run.successful, "Nested foreach run was not successful"
    all_results = run["outer_join"].task.data.all_results
    assert all_results == ["x-1", "y-1"], (
        f"Nested foreach produced wrong results: {all_results!r}. "
        "Expected ['x-1', 'y-1']."
    )


# ---------------------------------------------------------------------------
# test_conda_packages_available
#
# WHY: @conda uses a class-level _metaflow_home attribute that is only set by
# runtime_init().  For subprocess-based orchestrators runtime_init() is called
# automatically when the step subprocess re-enters the Metaflow runtime.  But
# for in-process executors (Dagster execute_job(), Windmill sync functions,
# Mage) runtime_init() is never called, so:
#   - _metaflow_home is None
#   - the code package is never extracted
#   - conda-installed packages are not on PYTHONPATH
#   - steps fail with ModuleNotFoundError for any conda package
#
# helloconda.py has a @conda step that imports 'regex' (a conda-only package)
# and stores the version in self.lib_version.  If the conda environment was not
# set up correctly, the step fails before setting that artifact.
#
# The test verifies the exact version string, not just that the step succeeded,
# because a step could succeed while silently importing the system regex instead
# of the conda-env regex (e.g. if the system also has regex installed).
#
# Capability: Cap.CONDA (REQUIRED)
# ---------------------------------------------------------------------------


@pytest.mark.compliance
@pytest.mark.scheduler_only
def test_conda_packages_available(
    exec_mode, decospecs, compute_env, tag, scheduler_config
):
    """
    @conda steps must be able to import conda-installed packages.

    Verifies that the conda environment is properly activated for step tasks,
    not just that the step completes.  Checks the exact package version to catch
    cases where the system package is imported instead of the conda-env package.
    """
    if exec_mode != "deployer":
        pytest.skip("compliance test requires deployer mode")

    test_unique_tag = f"test_compliance_conda_{exec_mode}"
    combined_tags = tag + [test_unique_tag]

    tl_args = {
        "env": compute_env,
        "decospecs": decospecs,
    }

    deployed_flow = deploy_flow_to_scheduler(
        flow_name="basic/helloconda.py",
        tl_args=tl_args,
        scheduler_args={"cluster": scheduler_config.cluster},
        deploy_args={"tags": combined_tags, **(scheduler_config.deploy_args or {})},
        scheduler_type=scheduler_config.scheduler_type,
    )

    run = wait_for_deployed_run(deployed_flow)

    assert run.successful, (
        "helloconda.py run failed. This usually means the conda environment was not "
        "set up correctly: check that runtime_init() was called (subprocess-based "
        "orchestrators) or that 'conda run -n <env>' wraps the step command "
        "(in-process executors like Dagster)."
    )

    # Verify the exact conda-installed package version, not just task success.
    # If the system regex is imported instead of the conda-env one, versions
    # would differ and reveal the environment setup bug.
    lib_version = run["v1"].task.data.lib_version
    assert lib_version is not None, (
        "lib_version artifact is None — the conda step may have succeeded without "
        "actually running the conda-installed package."
    )
    assert isinstance(lib_version, str) and len(lib_version) > 0, (
        f"lib_version is not a non-empty string: {lib_version!r}"
    )
    # The version string should look like a semver (digits and dots).
    # We do not pin the exact version to avoid breaking when the flow is updated,
    # but we verify it came from the conda env, not a missing/None value.
    import re as _re
    assert _re.match(r"^\d+\.\d+", lib_version), (
        f"lib_version {lib_version!r} does not look like a package version. "
        "The @conda step may not have imported from the conda environment."
    )


# ---------------------------------------------------------------------------
# test_from_deployment_dotted_name
#
# WHY: DAG IDs in @project-decorated flows are dotted: project.branch.FlowName.
# Orchestrators that pass this entire string as the Python class name hit a
# SyntaxError because dotted identifiers are not valid class names.
# from_deployment() must use only the last component (split(".")[-1]).
#
# Capability: Cap.FROM_DEPLOYMENT (REQUIRED)
# ---------------------------------------------------------------------------


@pytest.mark.compliance
@pytest.mark.scheduler_only
def test_config_params_excluded_from_init(
    exec_mode, decospecs, compute_env, tag, scheduler_config
):
    """@Config params must not be passed to the init command.

    WHY: flow._get_parameters() returns both @Parameter and @Config objects.
    Only @Parameter values belong in the init command CLI args; @Config values
    are baked into METAFLOW_FLOW_CONFIG_VALUE at compile time.  If the deployer
    passes @Config names to init, Metaflow rejects them:
        Error: no such option: --cfg

    config_simple.py has two @Config params (cfg, cfg_default_value) and one
    @Parameter (trigger_param).  If the init command receives --cfg or
    --cfg_default_value, it fails immediately with an unrecognised option error,
    and the entire run never starts.

    Capability: Cap.CONFIG_EXPR (REQUIRED)
    """
    if exec_mode != "deployer":
        pytest.skip("compliance test requires deployer mode")

    trigger_param = str(uuid.uuid4())[:8]
    test_unique_tag = f"test_compliance_config_init_{exec_mode}"
    combined_tags = tag + [test_unique_tag]

    # Use a @Config override so flow._get_parameters() has both @Config and @Parameter
    config_value = [
        ("cfg_default_value", {"a": {"project_name": "init_test_project", "b": "77"}})
    ]

    tl_args = {
        "env": {
            "METAFLOW_CLICK_API_PROCESS_CONFIG": "1",
            **compute_env,
        },
        "package_suffixes": ".py,.json",
        "config_value": config_value,
        "decospecs": decospecs,
    }

    # If init receives --cfg or --cfg_default_value, it fails with:
    #   Error: no such option: --cfg
    # causing deploy_flow_to_scheduler to raise immediately.
    deployed_flow = deploy_flow_to_scheduler(
        flow_name="config/config_simple.py",
        tl_args=tl_args,
        scheduler_args={"cluster": scheduler_config.cluster},
        deploy_args={"tags": combined_tags, **(scheduler_config.deploy_args or {})},
        scheduler_type=scheduler_config.scheduler_type,
    )

    run = wait_for_deployed_run(
        deployed_flow, run_kwargs={"trigger_param": trigger_param}
    )

    assert run.successful, (
        "Run was not successful.  If the failure occurred at init, the deployer may have "
        "passed @Config parameter names (--cfg, --cfg_default_value) to the init command. "
        "Filter them out: from metaflow.parameters import Config; "
        "params = [p for p in flow._get_parameters() if not isinstance(p, Config)]"
    )
    end_task = run["end"].task
    assert end_task.data.config_val_2 == "77", (
        f"config_val_2 should be '77' (from @Config override), got {end_task.data.config_val_2!r}. "
        "METAFLOW_FLOW_CONFIG_VALUE may not have been propagated."
    )


@pytest.mark.compliance
@pytest.mark.scheduler_only
def test_from_deployment_dotted_name(
    exec_mode, decospecs, compute_env, tag, scheduler_config
):
    """from_deployment() must handle dotted identifiers (project.branch.FlowName)."""
    if exec_mode != "deployer":
        pytest.skip("compliance test requires deployer mode")

    branch = str(uuid.uuid4())[:8]
    test_unique_tag = f"test_compliance_from_deployment_{exec_mode}"
    combined_tags = tag + [test_unique_tag]

    tl_args = {
        "env": compute_env,
        "decospecs": decospecs,
        "branch": branch,
    }

    deployed_flow = deploy_flow_to_scheduler(
        flow_name="basic/helloproject.py",
        tl_args=tl_args,
        scheduler_args={"cluster": scheduler_config.cluster},
        deploy_args={"tags": combined_tags, **(scheduler_config.deploy_args or {})},
        scheduler_type=scheduler_config.scheduler_type,
    )

    # The name returned by create() may be dotted (project.branch.FlowName).
    # from_deployment() must not fail on it.
    from metaflow import Deployer

    try:
        recovered = Deployer.__class__  # trigger import
        sched_type = scheduler_config.scheduler_type.replace("-", "_")
        deployer = Deployer(flow_file="basic/helloproject.py")
        sched = getattr(deployer, sched_type)()
        recovered_flow = sched.from_deployment(deployed_flow.name)
    except SyntaxError as exc:
        pytest.fail(
            f"from_deployment({deployed_flow.name!r}) raised SyntaxError: {exc}. "
            "Use identifier.split('.')[-1] as the flow class name."
        )
    except NotImplementedError:
        pytest.skip("from_deployment() is not yet implemented")

    assert recovered_flow is not None, "from_deployment() returned None"
