"""Tests for the devices router with mocked HubService."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import delete

from app.db import async_session
from app.models.db_models import Device, DeviceAlias
from app.services.hub_service import HubService


@pytest.fixture
def mock_hub():
    hub = MagicMock(spec=HubService)
    hub.is_connected.return_value = True
    hub.fetch_devices = AsyncMock(return_value=[
        {"ieee": "00:11:22:33:44:55:66:77", "name": "Lamp", "endpoint": 1, "online": True}
    ])
    hub.send_command = AsyncMock(return_value={"correlation_id": "abc-123", "status": "queued"})
    return hub


async def _seed_device():
    async with async_session() as session:
        await session.execute(
            delete(DeviceAlias).where(DeviceAlias.ieee_addr == "00:11:22:33:44:55:66:77")
        )
        await session.execute(
            delete(Device).where(Device.ieee_addr == "00:11:22:33:44:55:66:77")
        )
        device = Device(
            ieee_addr="00:11:22:33:44:55:66:77",
            network_addr="0x1234",
            online=True,
            endpoints=[{"id": 1}],
        )
        session.add(device)
        alias = DeviceAlias(ieee_addr="00:11:22:33:44:55:66:77", name="Lamp")
        session.add(alias)
        await session.commit()


def test_list_devices(mock_hub, client):
    asyncio = pytest.importorskip("asyncio")
    asyncio.run(_seed_device())
    client.app.state.hub_service = mock_hub
    response = client.get("/api/devices")
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert len(data["devices"]) == 1
    assert data["devices"][0]["ieee"] == "00:11:22:33:44:55:66:77"
    assert data["devices"][0]["name"] == "Lamp"


def test_send_command(mock_hub, client):
    client.app.state.hub_service = mock_hub
    response = client.post(
        "/api/devices/00:11:22:33:44:55:66:77/command",
        json={"action": "on", "params": {}},
    )
    assert response.status_code == 202
    data = response.json()
    assert data["correlation_id"] == "abc-123"


def test_rename_device(client):
    asyncio = pytest.importorskip("asyncio")
    asyncio.run(_seed_device())
    response = client.patch(
        "/api/devices/00:11:22:33:44:55:66:77/rename",
        json={"name": "Living Room Lamp"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["name"] == "Living Room Lamp"
