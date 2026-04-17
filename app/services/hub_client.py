"""USB Serial bridge client for talking to the ZigbeeHUB firmware."""

import asyncio
import json
from typing import Optional, Dict, Any, Callable

import serial


class HubClient:
    """Async wrapper around pyserial for JSON-over-serial communication."""

    def __init__(self) -> None:
        self._ser: Optional[serial.Serial] = None
        self._reader_task: Optional[asyncio.Task] = None
        self._port: Optional[str] = None
        self._running = False
        self._on_message: Optional[Callable[[Dict[str, Any]], None]] = None
        self._list_future: Optional[asyncio.Future] = None
        self._fetch_lock = asyncio.Lock()

    def set_on_message(self, callback: Callable[[Dict[str, Any]], None]) -> None:
        """Set callback for incoming JSON messages."""
        self._on_message = callback

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

    async def _read_loop(self) -> None:
        """Background task that reads JSON lines from the serial port."""
        buffer = ""
        while self._running and self._ser is not None and self._ser.is_open:
            try:
                chunk = await asyncio.to_thread(self._read_chunk)
                if chunk:
                    buffer += chunk.decode("utf-8", errors="ignore")
                    while "\n" in buffer:
                        line, buffer = buffer.split("\n", 1)
                        line = line.strip()
                        if line:
                            await self._handle_line(line)
                else:
                    await asyncio.sleep(0.01)
            except Exception as exc:
                print(f"[HubClient] Read error: {exc}")
                await asyncio.sleep(1)

    def _read_chunk(self) -> bytes:
        """Sync helper to read available bytes from serial."""
        if self._ser is not None and self._ser.is_open:
            return self._ser.read(max(1, self._ser.in_waiting))
        return b""

    async def _handle_line(self, line: str) -> None:
        """Parse an incoming JSON line and dispatch to callback."""
        try:
            data = json.loads(line)
        except Exception:
            return
        evt = data.get("evt") or data.get("event")
        if self._list_future is not None and not self._list_future.done():
            if evt == "device_list":
                self._list_future.set_result(data.get("devices", []))
                self._list_future = None
        if self._on_message is not None:
            try:
                self._on_message(data)
            except Exception:
                pass

    async def send_raw(self, payload: Dict[str, Any]) -> None:
        """Send a JSON payload to the hub."""
        if self._ser is None or not self._ser.is_open:
            raise RuntimeError("Serial port is not open")
        line = json.dumps(payload) + "\n"
        await asyncio.to_thread(self._ser.write, line.encode())

    async def fetch_devices(self) -> list:
        """Request the device list from the hub and wait for the response."""
        async with self._fetch_lock:
            # If another call is already waiting, piggy-back on its future.
            if self._list_future is not None and not self._list_future.done():
                try:
                    return await asyncio.wait_for(
                        asyncio.shield(self._list_future), timeout=3.0
                    )
                except asyncio.TimeoutError:
                    return []

            await self.send_raw({"cmd": "list"})
            loop = asyncio.get_running_loop()
            self._list_future = loop.create_future()
            try:
                return await asyncio.wait_for(self._list_future, timeout=3.0)
            except asyncio.TimeoutError:
                return []
            finally:
                if self._list_future is not None and self._list_future.done():
                    self._list_future = None

    async def send_command(
        self, ieee: str, action: str, params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Send a device command to the hub."""
        payload: Dict[str, Any] = {"cmd": action, "ieee": ieee}
        if params:
            payload.update(params)
        await self.send_raw(payload)
        return {"success": True, "status": "sent"}

    async def permit_join(self, duration: int) -> Dict[str, Any]:
        """Open the Zigbee network for joining."""
        await self.send_raw({"cmd": "permit", "duration": duration})
        return {"success": True, "status": "sent"}

    def is_connected(self) -> bool:
        return self._ser is not None and self._ser.is_open

    def get_port(self) -> Optional[str]:
        return self._port
