"""
Compliance test suite for Metaflow orchestrator extensions.

Run standalone:
    pytest metaflow_orchestrator_kit/compliance/ --ux-config=ux_test_config.yaml

Or from an orchestrator extension's test suite:
    pytest --ux-config=path/to/ux_test_config.yaml

See conftest.py for fixture definitions and parametrization logic.
See test_compliance.py for the individual compliance tests.
"""
