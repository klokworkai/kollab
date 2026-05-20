from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient

from kollab.config import Config
from kollab.server import app


def _client_with_key(api_key: str) -> TestClient:
    with patch("kollab.server._cfg", Config(api_key=api_key)):
        return TestClient(app, raise_server_exceptions=False)


def test_no_auth_required_when_key_empty() -> None:
    with patch("kollab.server._cfg", Config(api_key="")):
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/api/config")
    assert response.status_code == 200


def test_401_when_key_set_and_header_missing() -> None:
    with patch("kollab.server._cfg", Config(api_key="secret")):
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/api/config")
    assert response.status_code == 401


def test_401_when_key_set_and_wrong_value() -> None:
    with patch("kollab.server._cfg", Config(api_key="secret")):
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/api/config", headers={"Authorization": "Bearer wrong"})
    assert response.status_code == 401


def test_200_when_key_set_and_correct() -> None:
    with patch("kollab.server._cfg", Config(api_key="secret")):
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/api/config", headers={"Authorization": "Bearer secret"})
    assert response.status_code == 200
