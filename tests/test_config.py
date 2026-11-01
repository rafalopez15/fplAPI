import importlib.util
from unittest.mock import Mock

import pytest
from src.util import config


def load_fresh_config(monkeypatch, load_dotenv=None):
    """Execute config.py as a new module so import-time logic can be tested
    without disturbing the real src.util.config used by the rest of the suite."""
    monkeypatch.setattr("dotenv.load_dotenv", load_dotenv or (lambda *a, **k: None))
    spec = importlib.util.spec_from_file_location("config_under_test", config.__file__)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_get_env_returns_value(monkeypatch):
    monkeypatch.setenv("SOME_KEY", "some-value")
    assert config._get_env("SOME_KEY") == "some-value"


def test_get_env_raises_when_missing(monkeypatch):
    monkeypatch.delenv("SOME_KEY", raising=False)
    with pytest.raises(RuntimeError, match="SOME_KEY"):
        config._get_env("SOME_KEY")


def test_get_env_raises_when_empty(monkeypatch):
    monkeypatch.setenv("SOME_KEY", "")
    with pytest.raises(RuntimeError, match="SOME_KEY"):
        config._get_env("SOME_KEY")


def test_builds_bootstrap_url(monkeypatch):
    monkeypatch.setenv("FPL_BASE_URL", "https://example.com/api")
    monkeypatch.setenv("FPL_BOOTSTRAP_STATIC_PATH", "/bootstrap-static/")
    module = load_fresh_config(monkeypatch)
    assert module.FPL_BASE_URL == "https://example.com/api"
    assert module.FPL_BOOTSTRAP_STATIC_URL == "https://example.com/api/bootstrap-static/"


def test_strips_trailing_slash_from_base_url(monkeypatch):
    monkeypatch.setenv("FPL_BASE_URL", "https://example.com/api/")
    monkeypatch.setenv("FPL_BOOTSTRAP_STATIC_PATH", "/bootstrap-static/")
    module = load_fresh_config(monkeypatch)
    assert module.FPL_BOOTSTRAP_STATIC_URL == "https://example.com/api/bootstrap-static/"


@pytest.mark.parametrize("missing", ["FPL_BASE_URL", "FPL_BOOTSTRAP_STATIC_PATH"])
def test_import_fails_when_variable_missing(monkeypatch, missing):
    monkeypatch.setenv("FPL_BASE_URL", "https://example.com/api")
    monkeypatch.setenv("FPL_BOOTSTRAP_STATIC_PATH", "/bootstrap-static/")
    monkeypatch.delenv(missing)
    with pytest.raises(RuntimeError, match=missing):
        load_fresh_config(monkeypatch)


def test_loads_dotenv_on_import(monkeypatch):
    load_dotenv = Mock()
    load_fresh_config(monkeypatch, load_dotenv=load_dotenv)
    load_dotenv.assert_called_once_with()


def test_request_timeout_from_env(monkeypatch):
    monkeypatch.setenv("FPL_REQUEST_TIMEOUT", "2.5")
    assert load_fresh_config(monkeypatch).FPL_REQUEST_TIMEOUT == 2.5


def test_request_timeout_defaults_to_10(monkeypatch):
    monkeypatch.delenv("FPL_REQUEST_TIMEOUT", raising=False)
    assert load_fresh_config(monkeypatch).FPL_REQUEST_TIMEOUT == 10.0
