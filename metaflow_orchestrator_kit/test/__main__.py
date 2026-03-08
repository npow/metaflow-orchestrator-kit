"""
One-command compliance test runner for Metaflow orchestrator extensions.

Writes a ux_test_config.yaml, discovers test flows, and runs the compliance
tests — all with a single command.

Usage:
    # Minimal
    python -m metaflow_orchestrator_kit.test \\
        --scheduler-type kestra \\
        --deploy-args kestra_host=http://localhost:8090

    # With metaflow source
    python -m metaflow_orchestrator_kit.test \\
        --scheduler-type windmill \\
        --deploy-args windmill_host=http://localhost:8000,windmill_token=abc123 \\
        --metaflow-src /path/to/metaflow

    # Run only specific test modules
    python -m metaflow_orchestrator_kit.test \\
        --scheduler-type my_scheduler \\
        --test-modules compliance  # or: basic config dag
"""

import argparse
import os
import subprocess
import sys
import tempfile
from typing import List, Optional

try:
    import requests as _requests
except ImportError:
    _requests = None


# ---------------------------------------------------------------------------
# Scheduler pre-flight checks
# ---------------------------------------------------------------------------


def _verify_scheduler_reachable(deploy_args: dict) -> None:
    """
    Warn if the scheduler does not respond to a simple HTTP probe.

    This catches the most common failure mode: tests start, every deploy or trigger
    call times out, and the error messages blame the plugin rather than the missing
    service.  A one-second check here surfaces the real problem immediately.

    The probe is best-effort: if requests is not installed, or the scheduler uses
    a non-HTTP protocol, we skip silently.
    """
    if _requests is None:
        return  # requests not installed — skip check

    # Gather candidate host from any of the common key names implementations use.
    host = (
        deploy_args.get("host")
        or deploy_args.get("windmill_host")
        or deploy_args.get("mage_host")
        or deploy_args.get("kestra_host")
        or deploy_args.get("prefect_host")
        or deploy_args.get("temporal_host")
        or deploy_args.get("dagster_host")
        or deploy_args.get("flyte_host")
    )
    if not host:
        return

    # Common health/status probe paths in rough priority order.
    probe_paths = ["/health", "/api/health", "/api/status", "/api/version", "/healthz"]

    reachable = False
    last_error = None
    for path in probe_paths:
        url = host.rstrip("/") + path
        try:
            resp = _requests.get(url, timeout=5)
            # Any HTTP response (even 404) means TCP connected — the host is up.
            reachable = True
            break
        except Exception as exc:
            last_error = exc

    if not reachable:
        print()
        print("=" * 60)
        print("WARNING: scheduler at %r may not be reachable." % host)
        print("         Last probe error: %s" % last_error)
        print()
        print("  All tests will fail with connection errors if the scheduler")
        print("  is not running.  Start it before running this command.")
        print("=" * 60)
        print()


def _warn_stale_state(scheduler_type: str) -> None:
    """
    Warn the user that pre-existing scheduler state can break tests.

    Tests assume a clean scheduler environment: no pre-existing pipelines,
    deployments, or runs from previous experiments.  If stale state is present,
    tests fail with confusing errors such as:
      - trigger() returns a run ID from a previous run
      - status polling hits a completed run and immediately returns SUCCEEDED
      - from_deployment() finds the wrong version of a workflow

    The fix is always to wipe the scheduler state before running compliance tests.
    This is scheduler-specific (e.g. delete all pipelines, reset the DB).
    """
    print()
    print("NOTE: Stale state warning")
    print(
        "  If %r has pipelines, deployments, or runs from previous test attempts,"
        % scheduler_type
    )
    print("  tests may fail with confusing errors unrelated to your code.")
    print("  Fix: wipe all existing pipelines/deployments in your scheduler before")
    print("  re-running these tests.  This is scheduler-specific — consult your")
    print("  scheduler's docs for how to reset its state (e.g. drop the DB, call")
    print("  a delete-all API, or restart the scheduler with an empty data dir).")
    print()


# ---------------------------------------------------------------------------
# Config file generation
# ---------------------------------------------------------------------------


def _write_ux_test_config(
    scheduler_type: str,
    deploy_args: dict,
    config_path: str,
) -> None:
    """Write a minimal ux_test_config.yaml for the given backend."""
    deploy_args_str = ""
    if deploy_args:
        deploy_args_str = "\n    deploy_args:\n"
        for k, v in deploy_args.items():
            deploy_args_str += f"      {k}: {v}\n"
    else:
        deploy_args_str = "\n    deploy_args: {}\n"

    content = f"""\
# Generated by: python -m metaflow_orchestrator_kit.test
backends:
  - name: local
    scheduler_type: null
    cluster: null
    decospec: null
    deploy_args: {{}}
    enabled: true

  - name: {scheduler_type}
    scheduler_type: {scheduler_type}
    cluster: null
    decospec: null{deploy_args_str}    enabled: true
"""
    with open(config_path, "w") as f:
        f.write(content)
    print(f"  wrote {config_path}")


# ---------------------------------------------------------------------------
# Flow discovery
# ---------------------------------------------------------------------------


def _find_test_flows_dir(metaflow_src: Optional[str] = None) -> Optional[str]:
    """
    Find the directory containing Metaflow UX test flows.

    Search order:
    1. --metaflow-src argument
    2. PYTHONPATH entries
    3. Installed metaflow package location
    """
    candidates = []

    if metaflow_src:
        candidates.append(os.path.join(metaflow_src, "test", "ux"))
        candidates.append(os.path.join(metaflow_src, "test", "ux", "flows"))

    # Check PYTHONPATH
    pythonpath = os.environ.get("PYTHONPATH", "")
    for path in pythonpath.split(os.pathsep):
        if path:
            candidates.append(os.path.join(path, "test", "ux"))

    # Check installed metaflow
    try:
        import metaflow
        mf_dir = os.path.dirname(os.path.abspath(metaflow.__file__))
        mf_root = os.path.dirname(mf_dir)  # one level up from metaflow/
        candidates.append(os.path.join(mf_root, "test", "ux"))
    except Exception:
        pass

    for candidate in candidates:
        if os.path.isdir(candidate):
            return candidate

    return None


def _find_compliance_dir() -> Optional[str]:
    """Find the compliance test directory inside metaflow_orchestrator_kit."""
    try:
        import metaflow_orchestrator_kit
        kit_dir = os.path.dirname(os.path.abspath(metaflow_orchestrator_kit.__file__))
        compliance_dir = os.path.join(kit_dir, "compliance")
        if os.path.isdir(compliance_dir):
            return compliance_dir
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# pytest execution
# ---------------------------------------------------------------------------


def _build_pytest_args(
    scheduler_type: str,
    config_path: str,
    test_modules: List[str],
    flows_dir: Optional[str],
    extra_args: List[str],
    workers: int = 4,
) -> List[str]:
    """Build the pytest command arguments."""
    args = [sys.executable, "-m", "pytest"]

    # Test paths
    for module in test_modules:
        if module == "compliance":
            compliance_dir = _find_compliance_dir()
            if compliance_dir:
                args.append(compliance_dir)
            else:
                # Fall back to package path
                args.append("metaflow_orchestrator_kit/compliance/")
        elif module == "basic" and flows_dir:
            test_file = os.path.join(os.path.dirname(flows_dir), "core", "test_basic.py")
            if os.path.exists(test_file):
                args.append(test_file)
        elif module == "config" and flows_dir:
            test_file = os.path.join(os.path.dirname(flows_dir), "core", "test_config.py")
            if os.path.exists(test_file):
                args.append(test_file)
        elif module == "dag" and flows_dir:
            test_file = os.path.join(os.path.dirname(flows_dir), "core", "test_dag.py")
            if os.path.exists(test_file):
                args.append(test_file)

    args += [
        "--ux-config", config_path,
        "--only-backend", scheduler_type,
        "-v",
        "--tb=short",
        "-m", "not conda",
    ]

    if workers > 1:
        args += ["-n", str(workers)]

    args += extra_args

    return args


def _run_pytest(
    pytest_args: List[str],
    env: Optional[dict] = None,
    flows_dir: Optional[str] = None,
) -> int:
    """Run pytest with the given args and return exit code."""
    run_env = os.environ.copy()
    if env:
        run_env.update(env)

    # Prevent boto3 from picking up real AWS credentials
    run_env.setdefault("AWS_SHARED_CREDENTIALS_FILE", "")

    # Add flows_dir to environment so conftest.py can locate test flows
    if flows_dir:
        run_env["METAFLOW_UX_FLOWS_DIR"] = flows_dir

    print()
    print("Running: " + " ".join(pytest_args))
    print()

    result = subprocess.run(pytest_args, env=run_env)
    return result.returncode


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def _print_summary(scheduler_type: str, exit_code: int) -> None:
    print()
    print("=" * 60)
    if exit_code == 0:
        print(f"PASS  All compliance tests passed for {scheduler_type!r}")
        print()
        print("Your orchestrator passes the compliance suite.")
        print("Next step: set up GHA with the generated ux-tests.yml workflow.")
    else:
        print(f"FAIL  Some compliance tests failed for {scheduler_type!r}")
        print()
        print("Review the failures above. Common causes:")
        print("  - METAFLOW_FLOW_CONFIG_VALUE not injected into step env  [Cap.CONFIG_EXPR]")
        print("  - --branch not forwarded to step subprocesses            [Cap.PROJECT_BRANCH]")
        print("  - run_params passed as tuple instead of list             [Cap.RUN_PARAMS]")
        print("  - retry_count hardcoded to 0                             [Cap.RETRY]")
        print("  - from_deployment fails on dotted names                  [Cap.FROM_DEPLOYMENT]")
        print()
        print("Run the static validator first:")
        print("  python -m metaflow_orchestrator_kit.validate ./")
    print("=" * 60)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="One-command compliance test runner for Metaflow orchestrator extensions.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--scheduler-type",
        required=True,
        help="Scheduler type identifier (e.g. kestra, windmill, my_scheduler)",
    )
    parser.add_argument(
        "--deploy-args",
        default="",
        help=(
            "Comma-separated key=value pairs passed as deploy_args to the scheduler. "
            "Example: host=http://localhost:8000,token=abc123"
        ),
    )
    parser.add_argument(
        "--metaflow-src",
        default=None,
        help=(
            "Path to the metaflow source tree (for finding test flows). "
            "Auto-discovered from PYTHONPATH or installed package if not set."
        ),
    )
    parser.add_argument(
        "--test-modules",
        default="compliance,basic,config,dag",
        help=(
            "Comma-separated list of test modules to run. "
            "Options: compliance, basic, config, dag. Default: all."
        ),
    )
    parser.add_argument(
        "--config-path",
        default=None,
        help=(
            "Path to write the generated ux_test_config.yaml. "
            "Defaults to a temporary file."
        ),
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=4,
        help="Number of parallel pytest workers (default: 4, requires pytest-xdist).",
    )
    parser.add_argument(
        "extra_pytest_args",
        nargs=argparse.REMAINDER,
        help="Extra arguments passed directly to pytest.",
    )

    args = parser.parse_args()

    # Parse deploy_args
    deploy_args = {}
    if args.deploy_args:
        for pair in args.deploy_args.split(","):
            pair = pair.strip()
            if "=" in pair:
                k, v = pair.split("=", 1)
                deploy_args[k.strip()] = v.strip()

    # Parse test modules
    test_modules = [m.strip() for m in args.test_modules.split(",") if m.strip()]

    # Discover flows dir
    flows_dir = _find_test_flows_dir(args.metaflow_src)
    if flows_dir:
        print(f"Found test flows directory: {flows_dir}")
    else:
        print("Warning: test flows directory not found. Compliance tests only.")
        print("Pass --metaflow-src /path/to/metaflow to include basic/config/dag tests.")
        # Remove non-compliance modules if no flows dir
        test_modules = [m for m in test_modules if m == "compliance"]

    # Pre-flight checks — run before writing the config or starting pytest so that
    # problems are surfaced immediately rather than buried in test output.
    _warn_stale_state(args.scheduler_type)
    _verify_scheduler_reachable(deploy_args)

    # Write config file
    if args.config_path:
        config_path = args.config_path
        _write_ux_test_config(args.scheduler_type, deploy_args, config_path)
    else:
        # Use a temp file in cwd so it's easy to inspect
        config_path = "ux_test_config_generated.yaml"
        _write_ux_test_config(args.scheduler_type, deploy_args, config_path)

    # Build and run pytest
    pytest_args = _build_pytest_args(
        scheduler_type=args.scheduler_type,
        config_path=config_path,
        test_modules=test_modules,
        flows_dir=flows_dir,
        extra_args=args.extra_pytest_args or [],
        workers=args.workers,
    )

    exit_code = _run_pytest(pytest_args, flows_dir=flows_dir)

    _print_summary(args.scheduler_type, exit_code)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
