"""Loaded through pytest addopts, before pytest-django imports settings."""
import pytest
from test_support.isolation import install, validate_settings_choice


@pytest.hookimpl(tryfirst=True)
def pytest_load_initial_conftests(early_config, parser, args):
    try:
        # pytest-django's parsed --ds includes both CLI and PYTEST_ADDOPTS.
        if any("test_strava_connection.py" in arg for arg in args):
            raise RuntimeError("test_strava_connection.py is a manual API script, not an isolated test")
        namespace = parser.parse_known_args(args)
        validate_settings_choice(getattr(namespace, "ds", None))
        validate_settings_choice(early_config.getini("DJANGO_SETTINGS_MODULE"))
        install()
    except RuntimeError as exc:
        raise pytest.UsageError(str(exc)) from exc
