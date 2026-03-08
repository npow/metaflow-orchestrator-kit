"""
OrchestratorCapabilities — the complete list of Metaflow features an orchestrator
can or must support.

Usage
-----
Declare which capabilities your orchestrator supports in its deployer module:

    from metaflow_orchestrator_kit import Cap, REQUIRED

    SUPPORTED_CAPABILITIES = REQUIRED | {Cap.NESTED_FOREACH, Cap.SCHEDULE}

The compliance test suite reads this set and:
  - Fails the test if a REQUIRED capability is absent.
  - Skips the test if an OPTIONAL capability is absent.

Reference
---------
Each capability maps to a concrete contract requirement.  The descriptions
below are intentionally short; the full rationale for each requirement lives
in the compliance test that exercises it.
"""

from enum import Enum, auto


class Cap(Enum):
    # ------------------------------------------------------------------
    # REQUIRED — every orchestrator must implement these.
    # The compliance suite will FAIL for any backend that does not declare
    # and correctly implement all of the following.
    # ------------------------------------------------------------------

    LINEAR_DAG = auto()
    """start → one or more steps → end (the minimum viable DAG)."""

    BRANCHING = auto()
    """Static split/join: steps in parallel branches, merged at a join step."""

    FOREACH = auto()
    """Dynamic fan-out: foreach produces N parallel tasks at runtime."""

    RETRY = auto()
    """
    @retry with a real attempt count derived from the scheduler.

    The attempt number MUST come from the scheduler's native retry counter
    (e.g. AWS_BATCH_JOB_ATTEMPT, Kubernetes restartCount, Airflow try_number).
    Hardcoding retry_count=0 causes @retry to always see attempt=0 and never
    actually retry.
    """

    CATCH = auto()
    """@catch decorator: catch a step exception and continue the flow."""

    TIMEOUT = auto()
    """@timeout decorator: abort a step that exceeds the time limit."""

    RESOURCES = auto()
    """@resources passthrough: CPU/memory hints forwarded to the scheduler."""

    PROJECT_BRANCH = auto()
    """
    @project --branch propagation to ALL step subprocesses.

    The --branch flag must be included in the command the scheduler uses to
    launch every step subprocess, not just the start step.  Omitting it causes
    current.branch_name to be empty inside task code.
    """

    CONFIG_EXPR = auto()
    """
    METAFLOW_FLOW_CONFIG_VALUE propagation.

    The serialized config dict must be injected as an environment variable into
    every container/subprocess the scheduler launches.  Without it, @config and
    @project decorators use default/empty config at task runtime.
    """

    RUN_PARAMS = auto()
    """
    Multi-value trigger params as a list, not a tuple.

    Click returns tuples for multi-value options.  The trigger() method must
    convert run_params to list() before passing it to the scheduler API.
    Passing a tuple raises TypeError inside most scheduler client libraries.
    """

    FROM_DEPLOYMENT = auto()
    """
    Recover a deployed flow by its name string.

    DeployedFlow.from_deployment(identifier) must work correctly when
    identifier is a dotted name (project.branch.FlowName).  Only the last
    component should be used as the Python class name; using the full dotted
    string raises SyntaxError.
    """

    # ------------------------------------------------------------------
    # OPTIONAL — implement or explicitly declare unsupported.
    # The compliance suite will SKIP tests for capabilities not in the
    # declared set, rather than failing.
    # ------------------------------------------------------------------

    NESTED_FOREACH = auto()
    """foreach inside foreach — not supported by all orchestrators."""

    CONDA = auto()
    """@conda environment creation at task runtime."""

    RESUME = auto()
    """ORIGIN_RUN_ID resume: re-run from a previously failed step."""

    SCHEDULE = auto()
    """@schedule cron trigger: start a run on a time-based schedule."""


REQUIRED: frozenset = frozenset(
    {
        Cap.LINEAR_DAG,
        Cap.BRANCHING,
        Cap.FOREACH,
        Cap.RETRY,
        Cap.CATCH,
        Cap.TIMEOUT,
        Cap.RESOURCES,
        Cap.PROJECT_BRANCH,
        Cap.CONFIG_EXPR,
        Cap.RUN_PARAMS,
        Cap.FROM_DEPLOYMENT,
    }
)

OPTIONAL: frozenset = frozenset(
    {
        Cap.NESTED_FOREACH,
        Cap.CONDA,
        Cap.RESUME,
        Cap.SCHEDULE,
    }
)
