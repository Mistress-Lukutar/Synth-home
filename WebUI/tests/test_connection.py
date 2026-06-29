"""Tests for the connection router."""

from unittest.mock import patch


def test_list_ports_returns_list(client):
    with patch("serial.tools.list_ports.comports", return_value=[]):
        response = client.get("/api/ports")
    assert response.status_code == 200
    data = response.json()
    assert "ports" in data
    assert isinstance(data["ports"], list)


def test_status_when_disconnected(client):
    response = client.get("/api/status")
    assert response.status_code == 200
    data = response.json()
    assert data["connected"] is False
    assert data["port"] is None
