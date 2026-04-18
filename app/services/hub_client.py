"""USB Serial bridge client for talking to the ZigbeeHUB firmware."""

import asyncio
import json
from typing import Optional, Dict, Any, Callable

import serial
import structlog

from app.services.protocol import ProtocolHandler

logger = structlog.get_logger(__name__)


class HubClient:
    """Async wrapper around pyserial. Delegates framing/protocol to ProtocolHandler."""

    def __init__(self, protocol: ProtocolHandler, event_bus: Optional[Any] = None) -> None:
        self._ser: Optional[serial.Serial] = None
        self._reader_task: Optional[asyncio.Task] = None
        self._port: Optional[str] = None
        self._running = False
        self._protocol = protocol
        self._event_bus = event_bus

    def set_on_message(self, callback: Callable[[Dict[str, Any]], None]) -> None:
        self._protocol.set_on_message(callback)

    async def connect(self, port: str) -> bool:
        """Open the serial port and start the background reader."""
        try:
            self._ser = await asyncio.to_thread(
                serial.Serial, port, 115200, timeout=0.5
            )
            self._port = port
            self._running = True
            self._reader_task = asyncio.create_task(self._read_loop())
            return True
        except Exception as exc:
            print(f"[HubClient] Failed to open {port}: {exc}")
            return False

    async def disconnect(self) -> None:
        """Close the serial port and stop the reader task."""
        self._running = False
        if self._reader_task is not None:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass
            self._reader_task = None
        if self._ser is not None:
            await asyncio.to_thread(self._ser.close)
            self._ser = None
        self._port = None
        self._protocol.reset()

    async def _read_loop(self) -> None:
        """Background task that reads bytes and feeds the protocol handler."""
        while self._running and self._ser is not None and self._ser.is_open:
            try:
                chunk = await asyncio.to_thread(self._read_chunk)
                if chunk:
                    decoded = chunk.decode("utf-8", errors="replace")
                    logger.info("serial_chunk_received", byte_count=len(chunk), raw_preview=decoded[:400])
                    messages = self._protocol.feed(chunk)
                    logger.info("serial_parsed_result", message_count=len(messages), remaining_buffer_len=len(self._protocol._buffer))
                    if self._event_bus:
                        for msg in messages:
                            await self._event_bus.publish("hub_serial", {"direction": "rx", "payload": msg})
                    self._protocol.dispatch(messages)
                else:
                    await asyncio.sleep(0.01)
            except Exception as exc:
                logger.exception("serial_read_error")
                await asyncio.sleep(1)

    def _read_chunk(self) -> bytes:
        """Sync helper to read available bytes from serial."""
        if self._ser is not None and self._ser.is_open:
            return self._ser.read(max(1, self._ser.in_waiting))
        return b""

    async def send_raw(self, payload: Dict[str, Any]) -> None:
        """Send a JSON payload to the hub."""
        if self._ser is None or not self._ser.is_open:
            raise RuntimeError("Serial port is not open")
        line = json.dumps(payload) + "\n"
        logger.info("serial_raw_write", payload=payload)
        if self._event_bus:
            await self._event_bus.publish("hub_serial", {"direction": "tx", "payload": payload})
        await asyncio.to_thread(self._ser.write, line.encode())

    async def fetch_devices(self) -> list:
        """Request the device list from the hub and wait for the response."""
        return await self._protocol.request_device_list(
            lambda: asyncio.create_task(self.send_raw({"cmd": "list"}))
        )

    async def send_command(
        self, ieee: str, action: str, params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Send a device command to the hub. Returns correlation_id for async tracking."""
        import uuid

        correlation_id = f"corr-{uuid.uuid4().hex[:12]}"
        payload: Dict[str, Any] = {"cmd": action, "ieee": ieee, "correlation_id": correlation_id}
        if params:
            payload.update(params)
        await self.send_raw(payload)
        return {"correlation_id": correlation_id, "status": "pending"}

    async def permit_join(self, duration: int) -> Dict[str, Any]:
        """Open the Zigbee network for joining."""
        await self.send_raw({"cmd": "permit", "duration": duration})
        return {"success": True, "status": "sent"}

    def is_connected(self) -> bool:
        return self._ser is not None and self._ser.is_open

    def get_port(self) -> Optional[str]:
        return self._port
