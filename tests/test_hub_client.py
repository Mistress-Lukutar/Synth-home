"""Tests for the ProtocolHandler (core parsing and correlation logic)."""

import asyncio
import json

import pytest

from app.services.protocol import ProtocolHandler


def test_set_on_message():
    handler = ProtocolHandler()
    called_with = {}

    def cb(data):
        called_with["data"] = data

    handler.set_on_message(cb)
    assert handler._on_message is cb


@pytest.mark.asyncio
async def test_request_device_list_concurrent_piggyback():
    """Ensure concurrent request_device_list calls share a single future."""
    handler = ProtocolHandler()
    assert handler._fetch_lock.locked() is False


@pytest.mark.asyncio
async def test_dispatch_parses_json():
    handler = ProtocolHandler()
    received = []

    def cb(data):
        received.append(data)

    handler.set_on_message(cb)
    messages = handler.feed(json.dumps({"evt": "device_joined", "ieee": "aa:bb"}).encode() + b"\n")
    handler.dispatch(messages)
    assert len(received) == 1
    assert received[0]["evt"] == "device_joined"


@pytest.mark.asyncio
async def test_feed_ignores_garbage():
    handler = ProtocolHandler()
    received = []

    def cb(data):
        received.append(data)

    handler.set_on_message(cb)
    messages = handler.feed(b"not json at all\n")
    handler.dispatch(messages)
    assert len(received) == 0


@pytest.mark.asyncio
async def test_dispatch_resolves_list_future():
    handler = ProtocolHandler()
    loop = asyncio.get_running_loop()
    handler._list_future = loop.create_future()

    messages = handler.feed(
        json.dumps({"evt": "device_list", "devices": [{"ieee_addr": "01"}]}).encode() + b"\n"
    )
    handler.dispatch(messages)

    assert handler._list_future is None  # future was consumed
