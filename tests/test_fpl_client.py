from unittest.mock import Mock

import pytest
import requests
from src.util import fpl_client
from src.util.config import FPL_BASE_URL, FPL_PROXY_TIMEOUT, FPL_REQUEST_TIMEOUT
from src.util.fpl_client import (
    BOOTSTRAP_STATIC_URL,
    ENTRY_URL,
    FIXTURES_URL,
    HEADERS,
    FplNotFoundError,
    FplUnavailableError,
)


def mock_get(monkeypatch, response=None, side_effect=None):
    get = Mock(return_value=response, side_effect=side_effect)
    monkeypatch.setattr(fpl_client.requests, "get", get)
    return get


def ok_response(payload):
    return Mock(status_code=200, json=Mock(return_value=payload))


def error_response(status_code, text):
    response = Mock(status_code=status_code, text=text)
    response.raise_for_status.side_effect = requests.exceptions.HTTPError(
        f"{status_code} Server Error: {text}", response=response
    )
    return response


# --- fetch_bootstrap_static -----------------------------------------------

def test_fetch_bootstrap_static_returns_data(monkeypatch):
    get = mock_get(monkeypatch, ok_response({"teams": []}))

    assert fpl_client.fetch_bootstrap_static() == {"teams": []}
    get.assert_called_once_with(
        BOOTSTRAP_STATIC_URL, timeout=FPL_REQUEST_TIMEOUT, headers=HEADERS
    )


def test_fetch_bootstrap_static_raises_on_error_status(monkeypatch):
    mock_get(monkeypatch, error_response(503, "Service Unavailable"))

    with pytest.raises(requests.exceptions.HTTPError):
        fpl_client.fetch_bootstrap_static()


def test_fetch_bootstrap_static_raises_on_network_error(monkeypatch):
    mock_get(monkeypatch, side_effect=requests.exceptions.Timeout("timed out"))

    with pytest.raises(requests.exceptions.Timeout):
        fpl_client.fetch_bootstrap_static()


def test_fetch_bootstrap_static_raises_on_invalid_json(monkeypatch):
    response = Mock(status_code=200)
    response.json.side_effect = requests.exceptions.JSONDecodeError("bad", "doc", 0)
    mock_get(monkeypatch, response)

    with pytest.raises(requests.exceptions.JSONDecodeError):
        fpl_client.fetch_bootstrap_static()


def test_fetch_fixtures_returns_list(monkeypatch):
    get = mock_get(monkeypatch, ok_response([{"id": 1}]))

    assert fpl_client.fetch_fixtures() == [{"id": 1}]
    get.assert_called_once_with(FIXTURES_URL, timeout=FPL_REQUEST_TIMEOUT, headers=HEADERS)


def test_fetch_fixtures_raises_on_error_status(monkeypatch):
    mock_get(monkeypatch, error_response(503, "Service Unavailable"))

    with pytest.raises(requests.exceptions.HTTPError):
        fpl_client.fetch_fixtures()


def test_fpl_urls_are_built_from_the_base_url():
    assert BOOTSTRAP_STATIC_URL == f"{FPL_BASE_URL}/bootstrap-static/"
    assert FIXTURES_URL == f"{FPL_BASE_URL}/fixtures/"
    assert ENTRY_URL == f"{FPL_BASE_URL}/entry/"


def test_requests_identify_fplapi():
    assert HEADERS["User-Agent"].startswith("fplAPI/")


# --- manager endpoints (called live by the API) ---------------------------

@pytest.mark.parametrize(
    "fetch, path",
    [
        (fpl_client.fetch_manager, "1/"),
        (fpl_client.fetch_manager_transfers, "1/transfers/"),
        (fpl_client.fetch_manager_history, "1/history/"),
        (lambda manager_id: fpl_client.fetch_manager_picks(manager_id, 9),
         "1/event/9/picks/"),
    ],
)
def test_manager_fetches_use_the_proxy_timeout(monkeypatch, fetch, path):
    get = mock_get(monkeypatch, ok_response({"ok": True}))

    assert fetch(1) == {"ok": True}
    get.assert_called_once_with(ENTRY_URL + path, timeout=FPL_PROXY_TIMEOUT, headers=HEADERS)


def test_unknown_manager_raises_not_found(monkeypatch):
    mock_get(monkeypatch, error_response(404, "Not Found"))

    with pytest.raises(FplNotFoundError):
        fpl_client.fetch_manager(999999999)


@pytest.mark.parametrize("status", [429, 500, 503])
def test_fpl_error_status_raises_unavailable(monkeypatch, caplog, status):
    mock_get(monkeypatch, error_response(status, "Server Error"))

    with pytest.raises(FplUnavailableError):
        fpl_client.fetch_manager(1)
    assert "FPL error for" in caplog.text


@pytest.mark.parametrize(
    "error",
    [
        requests.exceptions.Timeout("timed out"),
        requests.exceptions.ConnectionError("connection refused"),
    ],
)
def test_fpl_unreachable_raises_unavailable(monkeypatch, caplog, error):
    mock_get(monkeypatch, side_effect=error)

    with pytest.raises(FplUnavailableError):
        fpl_client.fetch_manager_transfers(1)
    assert "FPL request failed" in caplog.text


def test_fpl_maintenance_page_raises_unavailable(monkeypatch):
    # During updates FPL serves an HTML "The game is being updated" page.
    response = Mock(status_code=200)
    response.json.side_effect = requests.exceptions.JSONDecodeError("Expecting value", "<html>", 0)
    mock_get(monkeypatch, response)

    with pytest.raises(FplUnavailableError):
        fpl_client.fetch_manager_history(1)


def test_http_error_without_response_raises_unavailable(monkeypatch):
    mock_get(monkeypatch, side_effect=requests.exceptions.HTTPError("no response"))

    with pytest.raises(FplUnavailableError):
        fpl_client.fetch_manager(1)
