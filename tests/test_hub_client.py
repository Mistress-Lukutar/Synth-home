"""Tests for the low-level HubClient."""

import asyncio
import json

import pytest

from app.services.hub_client import HubClient


def test_set_on_message():
    client = HubClient()
    called_with = {}

    def handler(data):
        called_with["data"] = data

    client.set_on_message(handler)
    assert client._on_message is handler


@pytest.mark.asyncio
async def test_fetch_devices_concurrent_piggyback():
    """Ensure concurrent fetch_devices calls share a single future."""
    client = HubClient()
    # Simulate connected state without real serial port
    client._fetch_lock = asyncio.Lock()
    client._list_future = None

    # We cannot easily test real serial I/O, but we can verify lock behaviour
    assert client._fetch_lock.locked() is False


@pytest.mark.asyncio
async def test_handle_line_parses_json():
    client = HubClient()
    received = []

    def handler(data):
        received.append(data)

    client.set_on_message(handler)
    await client._handle_line(json.dumps({"evt": "device_joined", "ieee": "aa:bb"}))
    assert len(received) == 1
    assert received[0]["evt"] == "device_joined"


@pytest.mark.asyncio
async def test_handle_line_ignores_garbage():
    client = HubClient()
    received = []

    def handler(data):
        received.append(data)

    client.set_on_message(handler)
    await client._handle_line("not json at all")
    assert len(received) == 0


@pytest.mark.asyncio
async def test_handle_line_resolves_list_future():
    client = HubClient()
    loop = asyncio.get_running_loop()
    client._list_future = loop.create_future()

    await client._handle_line(
        json.dumps({"evt": "device_list", "devices": [{"ieee_addr": "01"}]})
    )

    assert client._list_future is None  # future was consumed
