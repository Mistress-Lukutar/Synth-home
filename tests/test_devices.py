"""Tests for the devices router with mocked HubService."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.hub_service import HubService, set_hub_service, reset_hub_service


@pytest.fixture
def mock_hub():
    hub = MagicMock(spec=HubService)
    hub.is_connected.return_value = True
    hub.fetch_devices = AsyncMock(return_value=[
        {"ieee": "00:11:22:33:44:55:66:77", "name": "Lamp", "endpoint": 1, "online": True}
    ])
    hub.send_command = AsyncMock(return_value={"success": True})
    return hub


@pytest.fixture(autouse=True)
def hub_teardown():
    yield
    reset_hub_service()


def test_list_devices(mock_hub, client):
    set_hub_service(mock_hub)
    response = client.get("/api/devices")
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert len(data["devices"]) == 1
    assert data["devices"][0]["ieee"] == "00:11:22:33:44:55:66:77"


def test_send_command(mock_hub, client):
    set_hub_service(mock_hub)
    response = client.post(
        "/api/devices/00:11:22:33:44:55:66:77/command",
        json={"action": "on", "params": {}},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True


def test_rename_device(client):
    response = client.patch(
        "/api/devices/00:11:22:33:44:55:66:77/rename",
        json={"name": "Living Room Lamp"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["name"] == "Living Room Lamp"
