from unittest.mock import Mock

import pytest
import requests
from src.util import fpl_service
from src.util.config import FPL_BOOTSTRAP_STATIC_URL, FPL_REQUEST_TIMEOUT


def mock_get(monkeypatch, response=None, side_effect=None):
    get = Mock(return_value=response, side_effect=side_effect)
    monkeypatch.setattr(fpl_service.requests, "get", get)
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

    assert fpl_service.fetch_bootstrap_static() == {"teams": []}
    get.assert_called_once_with(FPL_BOOTSTRAP_STATIC_URL, timeout=FPL_REQUEST_TIMEOUT)


def test_fetch_bootstrap_static_raises_on_error_status(monkeypatch):
    mock_get(monkeypatch, error_response(503, "Service Unavailable"))

    with pytest.raises(requests.exceptions.HTTPError):
        fpl_service.fetch_bootstrap_static()


def test_fetch_bootstrap_static_raises_on_network_error(monkeypatch):
    mock_get(monkeypatch, side_effect=requests.exceptions.Timeout("timed out"))

    with pytest.raises(requests.exceptions.Timeout):
        fpl_service.fetch_bootstrap_static()


def test_fetch_bootstrap_static_raises_on_invalid_json(monkeypatch):
    response = Mock(status_code=200)
    response.json.side_effect = requests.exceptions.JSONDecodeError("bad", "doc", 0)
    mock_get(monkeypatch, response)

    with pytest.raises(requests.exceptions.JSONDecodeError):
        fpl_service.fetch_bootstrap_static()
