"""Tests for DeviceStateManager - the single source of truth for device state."""

import pytest
from sqlalchemy import delete

from app.db import async_session
from app.models.db_models import Device, DeviceAlias
from app.repositories.device import DeviceRepository
from app.services.device_state_manager import DeviceStateManager


async def _seed_device(ieee: str = "00:11:22:33:44:55:66:77"):
    async with async_session() as session:
        await session.execute(
            delete(DeviceAlias).where(DeviceAlias.ieee_addr == ieee)
        )
        await session.execute(delete(Device).where(Device.ieee_addr == ieee))
        device = Device(
            ieee_addr=ieee,
            network_addr="0x1234",
            online=True,
            endpoints=[{"id": 1}],
        )
        session.add(device)
        alias = DeviceAlias(ieee_addr=ieee, name="Lamp")
        session.add(alias)
        await session.commit()


@pytest.mark.asyncio
async def test_apply_state_change_persists_on_off():
    await _seed_device()
    manager = DeviceStateManager()

    await manager.apply_state_change("00:11:22:33:44:55:66:77", 1, 0x0006, 0x0000, True)

    async with async_session() as session:
        repo = DeviceRepository(session)
        device = await repo.get_by_ieee("00:11:22:33:44:55:66:77")
        assert device is not None
        assert device.state == {"1": {"on": True}}


@pytest.mark.asyncio
async def test_apply_state_change_persists_level():
    await _seed_device()
    manager = DeviceStateManager()

    await manager.apply_state_change("00:11:22:33:44:55:66:77", 1, 0x0008, 0x0000, 128)

    async with async_session() as session:
        repo = DeviceRepository(session)
        device = await repo.get_by_ieee("00:11:22:33:44:55:66:77")
        assert device is not None
        assert device.state == {"1": {"level": 128}}


@pytest.mark.asyncio
async def test_apply_state_change_caches_static_attrs_in_endpoints():
    await _seed_device()
    manager = DeviceStateManager()

    await manager.apply_state_change("00:11:22:33:44:55:66:77", 1, 0x0008, 0x0002, 10)
    await manager.apply_state_change("00:11:22:33:44:55:66:77", 1, 0x0008, 0x0003, 254)
    await manager.apply_state_change("00:11:22:33:44:55:66:77", 1, 0x0300, 0x400A, 0x1F)
    await manager.apply_state_change("00:11:22:33:44:55:66:77", 1, 0x0300, 0x400B, 250)
    await manager.apply_state_change("00:11:22:33:44:55:66:77", 1, 0x0300, 0x400C, 454)

    async with async_session() as session:
        repo = DeviceRepository(session)
        device = await repo.get_by_ieee("00:11:22:33:44:55:66:77")
        assert device is not None
        ep = device.endpoints[0]
        assert ep["level_min"] == 10
        assert ep["level_max"] == 254
        # 0x400A bitmap 0x1F: hs | enhanced_hue | color_loop | xy | ct
        assert ep["color_caps"] == {
            "hs": True,
            "enhanced_hue": True,
            "color_loop": True,
            "xy": True,
            "ct": True,
        }
        assert ep["ct_min"] == 250
        assert ep["ct_max"] == 454


@pytest.mark.asyncio
async def test_apply_state_change_color_caps_zero_read_is_ignored():
    """A zero/unreadable ColorCapabilities read means unknown, not 'no caps'."""
    await _seed_device()
    manager = DeviceStateManager()

    await manager.apply_state_change("00:11:22:33:44:55:66:77", 1, 0x0300, 0x400A, 0)

    async with async_session() as session:
        repo = DeviceRepository(session)
        device = await repo.get_by_ieee("00:11:22:33:44:55:66:77")
        assert device is not None
        assert "color_caps" not in (device.state or {}).get("1", {})
        assert "color_caps" not in device.endpoints[0]


@pytest.mark.asyncio
async def test_apply_state_change_color_loop_active_does_not_set_caps():
    """0x4002 is ColorLoopActive (not ColorCapabilities) and must not poison caps."""
    await _seed_device()
    manager = DeviceStateManager()

    await manager.apply_state_change("00:11:22:33:44:55:66:77", 1, 0x0300, 0x4002, 0)

    async with async_session() as session:
        repo = DeviceRepository(session)
        device = await repo.get_by_ieee("00:11:22:33:44:55:66:77")
        assert device is not None
        assert "color_caps" not in (device.state or {}).get("1", {})
        assert "color_caps" not in device.endpoints[0]


@pytest.mark.asyncio
async def test_sanitize_color_caps_drops_degenerate_caps():
    await _seed_device()
    bad_caps = {"hs": False, "xy": False, "ct": False, "color_loop": False}
    async with async_session() as session:
        device = await session.get(Device, "00:11:22:33:44:55:66:77")
        device.state = {"1": {"on": True, "color_caps": dict(bad_caps)}}
        device.endpoints = [{"id": 1, "clusters": [768], "color_caps": dict(bad_caps)}]
        await session.commit()

    manager = DeviceStateManager()
    assert await manager.sanitize_color_caps() == 1

    async with async_session() as session:
        device = await session.get(Device, "00:11:22:33:44:55:66:77")
        assert device.state == {"1": {"on": True}}
        assert device.endpoints == [{"id": 1, "clusters": [768]}]

    # Idempotent: a second run finds nothing left to fix.
    assert await manager.sanitize_color_caps() == 0


@pytest.mark.asyncio
async def test_sanitize_color_caps_keeps_valid_caps():
    await _seed_device()
    good_caps = {
        "hs": True,
        "enhanced_hue": True,
        "color_loop": True,
        "xy": True,
        "ct": True,
    }
    async with async_session() as session:
        device = await session.get(Device, "00:11:22:33:44:55:66:77")
        device.state = {"1": {"color_caps": dict(good_caps)}}
        device.endpoints = [{"id": 1, "clusters": [768], "color_caps": dict(good_caps)}]
        await session.commit()

    manager = DeviceStateManager()
    assert await manager.sanitize_color_caps() == 0

    async with async_session() as session:
        device = await session.get(Device, "00:11:22:33:44:55:66:77")
        assert device.state["1"]["color_caps"] == good_caps
        assert device.endpoints[0]["color_caps"] == good_caps


@pytest.mark.asyncio
async def test_on_ack_does_not_change_device_state():
    await _seed_device()
    manager = DeviceStateManager()
    manager.register_command("corr-1", "00:11:22:33:44:55:66:77", 1, "on")

    await manager.on_ack("corr-1", ok=True, error=None)

    async with async_session() as session:
        repo = DeviceRepository(session)
        device = await repo.get_by_ieee("00:11:22:33:44:55:66:77")
        assert device is not None
        assert device.state is None


@pytest.mark.asyncio
async def test_on_ack_failed_removes_pending_command():
    manager = DeviceStateManager()
    manager.register_command("corr-1", "00:11:22:33:44:55:66:77", 1, "on")

    await manager.on_ack("corr-1", ok=False, error="ESP_FAIL")

    assert manager.get_pending_command("corr-1") is None


@pytest.mark.asyncio
async def test_on_command_status_updates_online_only():
    await _seed_device()
    manager = DeviceStateManager()

    await manager.on_command_status(
        "corr-1", "completed", "00:11:22:33:44:55:66:77", "0x0006"
    )

    async with async_session() as session:
        repo = DeviceRepository(session)
        device = await repo.get_by_ieee("00:11:22:33:44:55:66:77")
        assert device is not None
        assert device.online is True
        assert device.state is None


@pytest.mark.asyncio
async def test_on_command_status_timeout_marks_offline():
    await _seed_device()
    manager = DeviceStateManager()

    await manager.on_command_status(
        "corr-1", "timeout", "00:11:22:33:44:55:66:77", "0x0006"
    )

    async with async_session() as session:
        repo = DeviceRepository(session)
        device = await repo.get_by_ieee("00:11:22:33:44:55:66:77")
        assert device is not None
        assert device.online is False


@pytest.mark.asyncio
async def test_set_device_online():
    await _seed_device()
    manager = DeviceStateManager()

    await manager.set_device_online("00:11:22:33:44:55:66:77", False)

    async with async_session() as session:
        repo = DeviceRepository(session)
        device = await repo.get_by_ieee("00:11:22:33:44:55:66:77")
        assert device is not None
        assert device.online is False


@pytest.mark.asyncio
async def test_register_command_tracks_pending():
    manager = DeviceStateManager()
    manager.register_command("corr-1", "00:11:22:33:44:55:66:77", 1, "on")

    pending = manager.get_pending_command("corr-1")
    assert pending is not None
    assert pending["ieee"] == "00:11:22:33:44:55:66:77"
    assert pending["endpoint"] == 1
    assert pending["action"] == "on"


@pytest.mark.asyncio
async def test_state_change_resolves_matching_pending_command():
    manager = DeviceStateManager()
    manager.register_command("corr-1", "00:11:22:33:44:55:66:77", 1, "on")

    await manager.apply_state_change("00:11:22:33:44:55:66:77", 1, 0x0006, 0x0000, True)

    assert manager.get_pending_command("corr-1") is None


@pytest.mark.asyncio
async def test_state_change_false_overwrites_true_in_db():
    """Regression: a state_change with false must persist and be returned by the API."""
    await _seed_device()
    # Simulate an earlier incorrect/true state left in the DB.
    async with async_session() as session:
        device = await session.get(Device, "00:11:22:33:44:55:66:77")
        device.state = {"1": {"on": True}}
        await session.commit()

    manager = DeviceStateManager()
    await manager.apply_state_change("00:11:22:33:44:55:66:77", 1, 0x0006, 0x0000, False)

    async with async_session() as session:
        repo = DeviceRepository(session)
        device = await repo.get_by_ieee("00:11:22:33:44:55:66:77")
        assert device is not None
        assert device.state == {"1": {"on": False}}
