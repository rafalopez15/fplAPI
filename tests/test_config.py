# _get_env is private but tested directly.
# pylint: disable=protected-access
import importlib.util
import os
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


def test_get_env_strips_whitespace(monkeypatch):
    monkeypatch.setenv("SOME_KEY", " some-value\n")
    assert config._get_env("SOME_KEY") == "some-value"


def test_get_env_raises_when_only_whitespace(monkeypatch):
    monkeypatch.setenv("SOME_KEY", "  ")
    with pytest.raises(RuntimeError, match="SOME_KEY"):
        config._get_env("SOME_KEY")


def test_get_env_raises_when_empty(monkeypatch):
    monkeypatch.setenv("SOME_KEY", "")
    with pytest.raises(RuntimeError, match="SOME_KEY"):
        config._get_env("SOME_KEY")


def test_base_url_defaults_to_fpl(monkeypatch):
    monkeypatch.delenv("FPL_BASE_URL", raising=False)
    assert load_fresh_config(monkeypatch).FPL_BASE_URL == "https://fantasy.premierleague.com/api"


def test_base_url_from_env(monkeypatch):
    monkeypatch.setenv("FPL_BASE_URL", "http://localhost:9000/api")
    assert load_fresh_config(monkeypatch).FPL_BASE_URL == "http://localhost:9000/api"


@pytest.mark.parametrize("value", ["", "  "])
def test_empty_base_url_falls_back_to_fpl(monkeypatch, value):
    monkeypatch.setenv("FPL_BASE_URL", value)
    assert load_fresh_config(monkeypatch).FPL_BASE_URL == "https://fantasy.premierleague.com/api"


def test_strips_trailing_slash_from_base_url(monkeypatch):
    monkeypatch.setenv("FPL_BASE_URL", " https://example.com/api/ ")
    assert load_fresh_config(monkeypatch).FPL_BASE_URL == "https://example.com/api"


def test_database_url_is_the_only_required_setting(monkeypatch):
    for name in [n for n in os.environ if n.startswith("FPL_")]:
        monkeypatch.delenv(name)
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@localhost/db")
    load_fresh_config(monkeypatch)  # doesn't raise

    monkeypatch.delenv("DATABASE_URL")
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
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


def test_database_url_from_env(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@db.example.com/db")
    module = load_fresh_config(monkeypatch)
    assert module.DATABASE_URL == "postgresql+psycopg://u:p@db.example.com/db"


def test_database_connect_timeout_from_env(monkeypatch):
    monkeypatch.setenv("DATABASE_CONNECT_TIMEOUT", "2")
    assert load_fresh_config(monkeypatch).DATABASE_CONNECT_TIMEOUT == 2


def test_database_connect_timeout_defaults_to_5(monkeypatch):
    monkeypatch.delenv("DATABASE_CONNECT_TIMEOUT", raising=False)
    assert load_fresh_config(monkeypatch).DATABASE_CONNECT_TIMEOUT == 5


@pytest.mark.parametrize(
    "name, default", [("DATABASE_POOL_SIZE", 3), ("DATABASE_MAX_OVERFLOW", 2)]
)
def test_pool_settings_default(monkeypatch, name, default):
    monkeypatch.delenv(name, raising=False)
    assert getattr(load_fresh_config(monkeypatch), name) == default


@pytest.mark.parametrize("name", ["DATABASE_POOL_SIZE", "DATABASE_MAX_OVERFLOW"])
def test_pool_settings_from_env(monkeypatch, name):
    monkeypatch.setenv(name, "7")
    assert getattr(load_fresh_config(monkeypatch), name) == 7


def test_proxy_timeout_defaults_to_5(monkeypatch):
    monkeypatch.delenv("FPL_PROXY_TIMEOUT", raising=False)
    assert load_fresh_config(monkeypatch).FPL_PROXY_TIMEOUT == 5.0


def test_proxy_timeout_from_env(monkeypatch):
    monkeypatch.setenv("FPL_PROXY_TIMEOUT", "2.5")
    assert load_fresh_config(monkeypatch).FPL_PROXY_TIMEOUT == 2.5
