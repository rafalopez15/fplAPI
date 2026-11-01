# pytest fixtures are injected as same-named arguments.
# pylint: disable=redefined-outer-name
import asyncio
import logging
import threading
from unittest.mock import Mock

import pytest
import requests
from src.util import fpl_service as fpl_service_module
from src.util.config import FPL_BOOTSTRAP_STATIC_URL, FPL_REQUEST_TIMEOUT
from src.util.fpl_service import FplDataUnavailableError, FplService


@pytest.fixture
def service():
    instance = FplService()
    instance.fpl_data = None
    yield instance
    instance.fpl_data = None


def mock_get(monkeypatch, response=None, side_effect=None):
    get = Mock(return_value=response, side_effect=side_effect)
    monkeypatch.setattr(fpl_service_module.requests, "get", get)
    return get


def ok_response(payload):
    return Mock(status_code=200, json=Mock(return_value=payload))


def error_response(status_code, text):
    response = Mock(status_code=status_code, text=text)
    response.raise_for_status.side_effect = requests.exceptions.HTTPError(
        f"{status_code} Server Error: {text}", response=response
    )
    return response


def test_is_singleton():
    assert FplService() is FplService()


def test_singleton_shares_data(service):
    service.fpl_data = {"teams": []}
    assert FplService().fpl_data == {"teams": []}


# --- get_data -------------------------------------------------------------

def test_get_data_returns_key(service):
    service.fpl_data = {"teams": [{"id": 1}]}
    assert service.get_data("teams") == [{"id": 1}]


def test_get_data_missing_key_returns_empty_list(service):
    service.fpl_data = {}
    assert service.get_data("teams") == []


def test_get_data_raises_when_not_loaded(service):
    with pytest.raises(FplDataUnavailableError):
        service.get_data("teams")


# --- get_fpl_api_data -----------------------------------------------------

def test_fetch_success_stores_data(monkeypatch, service, caplog):
    payload = {"events": [], "teams": []}
    get = mock_get(monkeypatch, ok_response(payload))

    with caplog.at_level(logging.INFO, logger=fpl_service_module.__name__):
        asyncio.run(service.get_fpl_api_data())

    get.assert_called_once_with(FPL_BOOTSTRAP_STATIC_URL, timeout=FPL_REQUEST_TIMEOUT)
    assert service.fpl_data == payload
    assert "200" in caplog.records[0].getMessage()


def test_fetch_runs_off_the_event_loop_thread(monkeypatch, service):
    calling_threads = []

    def fake_get(*_args, **_kwargs):
        calling_threads.append(threading.current_thread())
        return ok_response({})

    monkeypatch.setattr(fpl_service_module.requests, "get", fake_get)
    asyncio.run(service.get_fpl_api_data())

    assert calling_threads[0] is not threading.main_thread()


def test_fetch_error_status_keeps_existing_data(monkeypatch, service, caplog):
    service.fpl_data = {"cached": True}
    response = error_response(503, "Service Unavailable")
    mock_get(monkeypatch, response)

    with caplog.at_level(logging.ERROR, logger=fpl_service_module.__name__):
        asyncio.run(service.get_fpl_api_data())

    assert service.fpl_data == {"cached": True}
    response.json.assert_not_called()
    assert "Service Unavailable" in caplog.records[0].getMessage()


@pytest.mark.parametrize(
    "error",
    [
        requests.exceptions.ConnectionError("connection refused"),
        requests.exceptions.Timeout("timed out"),
    ],
)
def test_fetch_network_error_is_logged_not_raised(monkeypatch, service, caplog, error):
    mock_get(monkeypatch, side_effect=error)

    with caplog.at_level(logging.ERROR, logger=fpl_service_module.__name__):
        asyncio.run(service.get_fpl_api_data())

    assert service.fpl_data is None
    assert str(error) in caplog.records[0].getMessage()


def test_fetch_invalid_json_keeps_existing_data(monkeypatch, service):
    service.fpl_data = {"cached": True}
    response = Mock(status_code=200)
    response.json.side_effect = requests.exceptions.JSONDecodeError("bad", "doc", 0)
    mock_get(monkeypatch, response)

    asyncio.run(service.get_fpl_api_data())

    assert service.fpl_data == {"cached": True}
