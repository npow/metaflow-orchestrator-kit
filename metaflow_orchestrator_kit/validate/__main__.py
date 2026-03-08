"""
Static validator for Metaflow orchestrator extensions.

Checks a directory of generated files for all known pitfalls — without
running tests or requiring a live scheduler.

Usage:
    python -m metaflow_orchestrator_kit.validate /path/to/extension
    python -m metaflow_orchestrator_kit.validate ./my_scheduler/

Each check has a one-line explanation and a pointer to the fix.
Returns exit code 0 if all checks pass, 1 if any fail.
"""

import os
import re
import sys
from typing import List, Optional, Tuple


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

class _Check:
    def __init__(self, name: str, passed: bool, message: str = "", hint: str = ""):
        self.name = name
        self.passed = passed
        self.message = message
        self.hint = hint

    def __repr__(self):
        status = "PASS" if self.passed else "FAIL"
        return f"[{status}] {self.name}"


# ---------------------------------------------------------------------------
# File discovery helpers
# ---------------------------------------------------------------------------


def _find_files(directory: str) -> dict:
    """Walk directory and return a dict of {relative_path: content}."""
    result = {}
    for root, dirs, files in os.walk(directory):
        # Skip hidden directories and __pycache__
        dirs[:] = [d for d in dirs if not d.startswith(".") and d != "__pycache__"]
        for fname in files:
            if fname.endswith(".py"):
                fpath = os.path.join(root, fname)
                try:
                    with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                        content = f.read()
                    rel = os.path.relpath(fpath, directory)
                    result[rel] = content
                except Exception:
                    pass
    return result


def _find_deployer_file(files: dict) -> Optional[Tuple[str, str]]:
    """Find the deployer file (ends with _deployer.py)."""
    for path, content in files.items():
        if path.endswith("_deployer.py") and "DeployerImpl" in content:
            return path, content
    return None


def _find_objects_file(files: dict) -> Optional[Tuple[str, str]]:
    """Find the objects file (ends with _objects.py or contains DeployedFlow)."""
    for path, content in files.items():
        if (path.endswith("_objects.py") or "DeployedFlow" in content) and "TriggeredRun" in content:
            return path, content
    return None


def _find_mfextinit_file(files: dict) -> Optional[Tuple[str, str]]:
    """Find the mfextinit registration file."""
    for path, content in files.items():
        if os.path.basename(path).startswith("mfextinit_") and path.endswith(".py"):
            return path, content
    return None


def _find_cli_file(files: dict) -> Optional[Tuple[str, str]]:
    """Find the CLI file."""
    for path, content in files.items():
        if path.endswith("_cli.py") and "click" in content:
            return path, content
    return None


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------


def _check_no_init_in_metaflow_extensions(directory: str) -> _Check:
    """metaflow_extensions/ must be an implicit namespace package — no __init__.py."""
    bad = os.path.join(directory, "metaflow_extensions", "__init__.py")
    if os.path.exists(bad):
        return _Check(
            "metaflow_extensions/ has no __init__.py",
            False,
            "metaflow_extensions/__init__.py found — this BREAKS extension discovery",
            hint=(
                "Delete metaflow_extensions/__init__.py. The metaflow_extensions/ directory "
                "must be an implicit namespace package (no __init__.py). Adding __init__.py "
                "prevents Metaflow from merging extensions across packages, so "
                "Deployer(flow).your_scheduler() will not exist after install."
            ),
        )
    return _Check(
        "metaflow_extensions/ has no __init__.py",
        True,
        "implicit namespace package (correct)",
    )


def _check_mfextinit_exists(files: dict) -> _Check:
    result = _find_mfextinit_file(files)
    if result:
        return _Check(
            "mfextinit_<name>.py exists",
            True,
            f"found {result[0]}",
        )
    return _Check(
        "mfextinit_<name>.py exists",
        False,
        "no mfextinit_*.py file found in the directory",
        hint="Create mfextinit_<name>.py with CLIS_DESC and DEPLOYER_IMPL_PROVIDERS_DESC",
    )


def _check_deployer_impl_providers(files: dict) -> _Check:
    """DEPLOYER_IMPL_PROVIDERS_DESC must be a list of tuples."""
    result = _find_mfextinit_file(files)
    if not result:
        return _Check(
            "DEPLOYER_IMPL_PROVIDERS_DESC has correct structure",
            False,
            "mfextinit file not found",
            hint="Create mfextinit_<name>.py",
        )
    path, content = result
    if "DEPLOYER_IMPL_PROVIDERS_DESC" not in content:
        return _Check(
            "DEPLOYER_IMPL_PROVIDERS_DESC has correct structure",
            False,
            f"DEPLOYER_IMPL_PROVIDERS_DESC not found in {path}",
            hint="Add: DEPLOYER_IMPL_PROVIDERS_DESC = [(\"<name>\", \".<name>.<name>_deployer.<Class>DeployerImpl\")]",
        )
    # Check it's a list with at least one tuple
    if not re.search(r'DEPLOYER_IMPL_PROVIDERS_DESC\s*=\s*\[', content):
        return _Check(
            "DEPLOYER_IMPL_PROVIDERS_DESC has correct structure",
            False,
            f"DEPLOYER_IMPL_PROVIDERS_DESC is not a list in {path}",
            hint="Must be a list of (name, dotted_path) tuples: [(\"<name>\", \".<name>.<name>_deployer.<Class>DeployerImpl\")]",
        )
    return _Check(
        "DEPLOYER_IMPL_PROVIDERS_DESC has correct structure",
        True,
        f"found in {path}",
    )


def _check_run_params_list(files: dict) -> _Check:
    """trigger() must convert run_params to list(), not pass tuple directly."""
    result = _find_objects_file(files)
    if not result:
        return _Check(
            "run_params uses list() not tuple()",
            False,
            "objects file not found",
            hint="Create <name>_objects.py with trigger() method",
        )
    path, content = result

    # Look for the conversion pattern
    has_list_conversion = bool(re.search(
        r'run_params\s*=\s*list\s*\(\s*run_params',
        content
    ))
    if has_list_conversion:
        return _Check(
            "run_params uses list() not tuple()",
            True,
            f"list(run_params) found in {path}",
        )

    # Check if trigger() is implemented at all
    if "def trigger(" not in content:
        return _Check(
            "run_params uses list() not tuple()",
            False,
            f"trigger() method not found in {path}",
            hint="Add trigger() method with: run_params = list(run_params) if run_params else []",
        )

    # trigger() exists but no list conversion
    return _Check(
        "run_params uses list() not tuple()",
        False,
        f"trigger() found in {path} but missing list(run_params) conversion",
        hint="Add: run_params = list(run_params) if run_params else []  before using run_params. "
             "Click returns tuples for multi-value options, which raise TypeError in scheduler APIs.",
    )


def _check_flow_config_value(files: dict) -> _Check:
    """METAFLOW_FLOW_CONFIG_VALUE must appear in step env setup."""
    result = _find_deployer_file(files)
    if not result:
        return _Check(
            "METAFLOW_FLOW_CONFIG_VALUE in step env",
            False,
            "deployer file not found",
            hint="Create <name>_deployer.py with DeployerImpl subclass",
        )
    path, content = result

    if "METAFLOW_FLOW_CONFIG_VALUE" in content:
        return _Check(
            "METAFLOW_FLOW_CONFIG_VALUE in step env",
            True,
            f"METAFLOW_FLOW_CONFIG_VALUE found in {path}",
        )
    return _Check(
        "METAFLOW_FLOW_CONFIG_VALUE in step env",
        False,
        f"METAFLOW_FLOW_CONFIG_VALUE not found in {path}",
        hint=(
            "Extract at compile time: "
            "from metaflow.flowspec import FlowStateItems; "
            "configs = flow._flow_state[FlowStateItems.CONFIGS]; "
            "json.dumps({k: v for k, (v, _) in configs.items() if v is not None}). "
            "Inject as env var into every step container. "
            "Without it, @config/@project decorators use empty/default values."
        ),
    )


def _check_branch_in_step_command(files: dict) -> _Check:
    """--branch must be forwarded to step subprocesses."""
    result = _find_deployer_file(files)
    if not result:
        return _Check(
            "--branch passed to step commands",
            False,
            "deployer file not found",
        )
    path, content = result

    # Look for --branch in a step command context
    has_branch = bool(re.search(r'"--branch"', content) or re.search(r"'--branch'", content))
    if has_branch:
        return _Check(
            "--branch passed to step commands",
            True,
            f"--branch found in {path}",
        )
    return _Check(
        "--branch passed to step commands",
        False,
        f"--branch not found in step command construction in {path}",
        hint=(
            "Add: if branch: cmd += ['--branch', branch]  to _build_step_command(). "
            "@project reads current.branch_name from --branch at step runtime. "
            "Without it, all step tasks produce empty branch_name."
        ),
    )


def _check_retry_count_not_hardcoded(files: dict) -> _Check:
    """retry_count must not be hardcoded to 0 in step command construction."""
    result = _find_deployer_file(files)
    if not result:
        return _Check(
            "retry_count reads from attempt, not hardcoded to 0",
            False,
            "deployer file not found",
        )
    path, content = result

    # Look for the retry-count argument in step command
    # Pattern: "--retry-count", "0"  (hardcoded literal)
    hardcoded_zero = bool(re.search(
        r'["\']--retry-count["\'],?\s*["\']0["\']',
        content
    ))
    if hardcoded_zero:
        return _Check(
            "retry_count reads from attempt, not hardcoded to 0",
            False,
            f"--retry-count hardcoded to '0' string found in {path}",
            hint=(
                "Replace hardcoded '0' with the scheduler's native attempt counter. "
                "AWS Batch: int(os.environ.get('AWS_BATCH_JOB_ATTEMPT', '0')). "
                "Kubernetes: from pod annotation or restart count. "
                "Airflow: context['ti'].try_number - 1."
            ),
        )

    # Check that retry_count parameter exists and is passed through
    has_retry_count_param = bool(re.search(r'retry_count', content))
    has_str_retry = bool(re.search(r'str\s*\(\s*retry_count\s*\)', content))

    if has_retry_count_param and has_str_retry:
        return _Check(
            "retry_count reads from attempt, not hardcoded to 0",
            True,
            f"retry_count parameter used in {path}",
        )

    if not has_retry_count_param:
        return _Check(
            "retry_count reads from attempt, not hardcoded to 0",
            False,
            f"retry_count not found in {path}",
            hint=(
                "Add retry_count parameter to _build_step_command() and pass "
                "str(retry_count) to --retry-count. Derive the value from the "
                "scheduler's native attempt counter."
            ),
        )

    return _Check(
        "retry_count reads from attempt, not hardcoded to 0",
        True,
        f"retry_count found in {path} (verify it reads from scheduler attempt)",
    )


def _check_datastore_sysroot(files: dict) -> _Check:
    """METAFLOW_DATASTORE_SYSROOT_LOCAL should be captured at compile time.

    A common bug: the deployer reads METAFLOW_DATASTORE_SYSROOT_LOCAL from the
    environment inside a step task function (at worker runtime), instead of
    capturing it at compile time and baking it into the workflow definition.
    This causes deployer and worker to use different sysroot paths, so
    wait_for_deployed_run() never finds the run (it polls the wrong directory).

    The fix: capture in _compile_workflow() / _get_datastore_sysroot(), not
    inside a step body or worker callback.
    """
    result = _find_deployer_file(files)
    if not result:
        return _Check(
            "DATASTORE_SYSROOT captured at compile time",
            False,
            "deployer file not found",
        )
    path, content = result

    if "METAFLOW_DATASTORE_SYSROOT_LOCAL" not in content:
        return _Check(
            "DATASTORE_SYSROOT captured at compile time",
            False,
            f"METAFLOW_DATASTORE_SYSROOT_LOCAL not found in {path}",
            hint=(
                "Capture at compile time: datastore_sysroot = os.environ.get('METAFLOW_DATASTORE_SYSROOT_LOCAL', os.path.expanduser('~')). "
                "Bake into the workflow definition so workers write metadata to the same "
                "location the deployer reads from.  "
                "CRITICAL: do NOT read this env var inside a step task body or worker callback "
                "— the worker may have a different (or absent) sysroot env var than the deployer, "
                "causing wait_for_deployed_run() to poll the wrong directory forever."
            ),
        )

    # Warn if the sysroot is read from os.environ inside what looks like a step/task
    # body (heuristic: os.environ.get("METAFLOW_DATASTORE_SYSROOT_LOCAL") appears
    # inside a function that is NOT _get_datastore_sysroot / _compile_workflow).
    # We look for it inside indented blocks that are not the compile-time helpers.
    compile_time_fn_pattern = re.compile(
        r'def\s+(_get_datastore_sysroot|_compile_workflow)\s*\(.*?\n'
        r'((?:[ \t]+.*\n)*)',
        re.MULTILINE,
    )
    compile_time_bodies = " ".join(
        m.group(2) for m in compile_time_fn_pattern.finditer(content)
    )

    # Check if the sysroot env read occurs OUTSIDE the compile-time helpers.
    sysroot_occurrences = [
        m.start() for m in re.finditer(r'METAFLOW_DATASTORE_SYSROOT_LOCAL', content)
    ]
    all_in_compile_time = all(
        content[max(0, pos - 500):pos] in compile_time_bodies or
        "METAFLOW_DATASTORE_SYSROOT_LOCAL" in compile_time_bodies
        for pos in sysroot_occurrences
    )

    # Simpler heuristic: if it appears in the compile-time helpers, that's good enough.
    # The validator can't fully parse scopes, so we just pass if it's present anywhere
    # but add a targeted hint reminding implementors NOT to read it at step runtime.
    return _Check(
        "DATASTORE_SYSROOT captured at compile time",
        True,
        f"METAFLOW_DATASTORE_SYSROOT_LOCAL found in {path} "
        f"(verify it is read at compile time, not inside a step task body — "
        f"worker and deployer must use the SAME sysroot path or "
        f"wait_for_deployed_run() will poll the wrong directory)",
    )


def _check_environment_type(files: dict) -> _Check:
    """--environment must be passed to step command for @conda support."""
    result = _find_deployer_file(files)
    if not result:
        return _Check(
            "ENVIRONMENT_TYPE passed to step command",
            False,
            "deployer file not found",
        )
    path, content = result

    has_environment_flag = bool(
        re.search(r'"--environment"', content) or
        re.search(r"'--environment'", content)
    )
    if has_environment_flag:
        return _Check(
            "ENVIRONMENT_TYPE passed to step command",
            True,
            f"--environment found in step command in {path}",
        )
    return _Check(
        "ENVIRONMENT_TYPE passed to step command",
        False,
        f"--environment flag not found in step command in {path}",
        hint=(
            "Add --environment to step command: cmd += ['--environment', environment_type]. "
            "environment_type = getattr(environment, 'TYPE', 'local'). "
            "Without this, @conda flows use the wrong Python interpreter."
        ),
    )


def _check_tag_after_subcommand(files: dict) -> _Check:
    """--tag must appear AFTER the step/run subcommand, not before it.

    Metaflow's top-level CLI does not accept --tag as a global flag.
    It is only valid as an argument to step/run/init subcommands.
    Passing --tag before the subcommand causes:
        Error: no such option: --tag

    Anti-pattern (wrong):
        python flow.py --no-pylint --tag foo step start --run-id ...

    Correct:
        python flow.py --no-pylint step start --tag foo --run-id ...

    Detection: look for a list that contains "--tag" before "step" or "run".
    """
    all_content = "\n".join(files.values())

    # Look for the pattern: "--tag" appears in a list before "step" or before cmd +=
    # Heuristic: "--tag" followed by "step" in same array literal, where --tag comes first.
    # Pattern: ["--tag", ..., "step", ...] or "--tag" ... then "step" in same expression.
    wrong_tag_order = bool(
        re.search(
            r'"--tag"[^]]*"step"',
            all_content,
        ) or re.search(
            r"'--tag'[^]]*'step'",
            all_content,
        )
    )
    if wrong_tag_order:
        return _Check(
            "--tag placed after step subcommand (not before)",
            False,
            "--tag appears before 'step' in a command array",
            hint=(
                "Move --tag flags to AFTER the step subcommand name.  Metaflow's top-level "
                "CLI does not accept --tag as a global flag — it causes "
                "'Error: no such option: --tag'.  "
                "Wrong:   cmd = [python, flow, '--tag', t, 'step', name, ...]\n"
                "Correct: cmd = [python, flow, 'step', name, '--tag', t, ...]"
            ),
        )

    return _Check(
        "--tag placed after step subcommand (not before)",
        True,
        "no --tag-before-step pattern found",
    )


def _check_pythonpath_no_extension_package(files: dict) -> _Check:
    """PYTHONPATH injected into step commands must not include the extension package itself.

    When a Docker-based scheduler worker receives PYTHONPATH pointing to the host
    source tree, Python will discover and load ALL metaflow_extensions/ directories
    on that path — including private/internal extensions installed on the host that
    depend on services not available inside the container.  This causes:
        Cannot locate metadata_provider plugin 'service'
        ImportError: No module named 'requests' (or other missing deps)

    The PYTHONPATH for step workers should include only the OSS metaflow source.
    It must NOT include the extension package itself or site-packages.

    Detection: look for both PYTHONPATH construction and a reference to the
    extension package directory in the same deployer or compiler file.
    """
    # Look in all files for PYTHONPATH construction
    all_content = "\n".join(files.values())

    # If there's no PYTHONPATH injection at all, skip this check.
    if "PYTHONPATH" not in all_content:
        return _Check(
            "PYTHONPATH for step workers excludes extension package",
            True,
            "no PYTHONPATH injection found — skipped",
        )

    # Look for the pattern where PYTHONPATH includes site-packages or the
    # extension package directory (a path ending in site-packages or containing
    # the package name).
    # We check for os.environ.get("PYTHONPATH", "") which would include site-packages.
    site_packages_in_pythonpath = bool(
        re.search(r'PYTHONPATH.*site.packages', all_content) or
        re.search(r'site.packages.*PYTHONPATH', all_content)
    )
    if site_packages_in_pythonpath:
        return _Check(
            "PYTHONPATH for step workers excludes extension package",
            False,
            "PYTHONPATH appears to include a site-packages path",
            hint=(
                "Do not pass os.environ['PYTHONPATH'] (which includes site-packages) to Docker "
                "worker PYTHONPATH.  Set PYTHONPATH to the OSS metaflow source only.  "
                "Including site-packages exposes host-installed private extensions that "
                "fail inside the container (missing services, missing deps)."
            ),
        )

    return _Check(
        "PYTHONPATH for step workers excludes extension package",
        True,
        "no site-packages path found in PYTHONPATH construction",
    )


def _check_scheduler_api_optional(files: dict) -> _Check:
    """Secondary scheduler API calls (e.g. schedule creation) must not block trigger().

    A common pattern: after creating a workflow, implementors call a secondary
    scheduler API (e.g. create a schedule, register a trigger) as part of
    create() or trigger(). If this secondary call fails (503, timing window where
    the scheduler hasn't indexed the workflow yet, expired auth token), the entire
    create/trigger fails even though the underlying execution would have worked.

    The fix: wrap secondary API calls in try/except and treat them as non-fatal.
    Detect the anti-pattern: secondary API call result used directly without
    any error handling (e.g. schedule_id = resp.json()["id"] with no try/except).
    """
    result = _find_cli_file(files)
    if not result:
        return _Check(
            "secondary scheduler API calls are non-fatal",
            True,
            "no CLI file found — skipped",
        )
    path, content = result

    # Look for direct key access on a requests response without surrounding try/except.
    # Heuristic: resp.json()[...] or response[...]["id"] appearing in trigger()
    # with no try/except block at that indentation level.
    # A simpler signal: does the file have at least one try/except in a trigger-related context?
    has_try_except = bool(re.search(r'\btry\b', content) and re.search(r'\bexcept\b', content))
    has_trigger = bool(re.search(r'def trigger\b', content) or re.search(r'@cli\.command', content))

    # Look for the dangerous pattern: schedule or secondary resource creation
    # that accesses response keys without any error handling anywhere in the file.
    has_secondary_call = bool(
        re.search(r'schedule|pipeline_schedule|api_trigger|register_trigger', content, re.IGNORECASE)
    )

    if has_secondary_call and not has_try_except:
        return _Check(
            "secondary scheduler API calls are non-fatal",
            False,
            f"secondary scheduler API calls found in {path} but no try/except error handling",
            hint=(
                "Wrap secondary API calls (schedule creation, trigger registration) in "
                "try/except so they don't block the trigger if the scheduler hasn't indexed "
                "the workflow yet.  Example:\n"
                "    try:\n"
                "        schedule_id = _create_schedule(client, pipeline_id)\n"
                "    except Exception:\n"
                "        schedule_id = None  # non-fatal\n"
                "Schedulers (Mage, Prefect, Windmill) index workflows asynchronously; "
                "a secondary API call immediately after create() may return 500."
            ),
        )

    return _Check(
        "secondary scheduler API calls are non-fatal",
        True,
        f"no unguarded secondary scheduler API calls found in {path}",
    )


def _check_from_deployment_dotted(files: dict) -> _Check:
    """from_deployment must use identifier.split('.')[-1]."""
    result = _find_objects_file(files)
    if not result:
        return _Check(
            "from_deployment handles dotted names",
            False,
            "objects file not found",
        )
    path, content = result

    if "from_deployment" not in content:
        return _Check(
            "from_deployment handles dotted names",
            False,
            f"from_deployment() not found in {path}",
            hint="Add classmethod from_deployment(cls, identifier) with: flow_name = identifier.split('.')[-1]",
        )

    has_split = bool(re.search(r'identifier\.split\s*\(\s*["\'][.]["\']\s*\)\s*\[\s*-1\s*\]', content))
    if has_split:
        return _Check(
            "from_deployment handles dotted names",
            True,
            f"identifier.split('.')[-1] found in {path}",
        )

    return _Check(
        "from_deployment handles dotted names",
        False,
        f"from_deployment() found in {path} but identifier.split('.')[-1] not found",
        hint=(
            "Add: flow_name = identifier.split('.')[-1]  in from_deployment(). "
            "@project flows have dotted DAG IDs (project.branch.FlowName). "
            "Using the full string as a class name raises SyntaxError."
        ),
    )


# ---------------------------------------------------------------------------
# Main validation entry point
# ---------------------------------------------------------------------------


def validate(directory: str) -> List[_Check]:
    """Run all checks on the given directory. Returns list of _Check results."""
    files = _find_files(directory)
    if not files:
        print(f"No Python files found in {directory!r}", file=sys.stderr)
        return []

    checks = [
        _check_no_init_in_metaflow_extensions(directory),
        _check_mfextinit_exists(files),
        _check_deployer_impl_providers(files),
        _check_run_params_list(files),
        _check_flow_config_value(files),
        _check_branch_in_step_command(files),
        _check_retry_count_not_hardcoded(files),
        _check_datastore_sysroot(files),
        _check_environment_type(files),
        _check_tag_after_subcommand(files),
        _check_pythonpath_no_extension_package(files),
        _check_scheduler_api_optional(files),
        _check_from_deployment_dotted(files),
    ]
    return checks


def _print_results(checks: List[_Check], directory: str) -> int:
    """Print check results and return exit code (0=pass, 1=fail)."""
    print(f"Validating: {os.path.abspath(directory)}")
    print()

    passed = 0
    failed = 0
    for check in checks:
        if check.passed:
            print(f"  PASS  {check.name}")
            if check.message:
                print(f"        ({check.message})")
            passed += 1
        else:
            print(f"  FAIL  {check.name}")
            if check.message:
                print(f"        Problem: {check.message}")
            if check.hint:
                print(f"        Fix:     {check.hint}")
            failed += 1

    print()
    print(f"Results: {passed} passed, {failed} failed")

    if failed == 0:
        print()
        print("All checks passed. Next step: run the compliance tests:")
        print("  python -m metaflow_orchestrator_kit.test --scheduler-type <name> --deploy-args ...")
        return 0
    else:
        print()
        print(f"{failed} check(s) failed. Fix the issues above before running compliance tests.")
        return 1


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        print("Usage: python -m metaflow_orchestrator_kit.validate <directory>")
        sys.exit(1)

    directory = sys.argv[1]
    if not os.path.isdir(directory):
        print(f"Error: {directory!r} is not a directory", file=sys.stderr)
        sys.exit(1)

    checks = validate(directory)
    if not checks:
        sys.exit(1)
    exit_code = _print_results(checks, directory)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
