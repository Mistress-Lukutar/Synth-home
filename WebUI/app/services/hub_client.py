"""USB Serial bridge client for talking to the ZigbeeHUB firmware."""

import asyncio
import json
from typing import Optional, Dict, Any, Callable

import serial
import structlog

from app.services.protocol import ProtocolHandler

logger = structlog.get_logger(__name__)

# Hard upper bound for a single serial read/write. pyserial has its own
# 0.5 s timeout, but a wedged USB-CDC driver can ignore it and block the
# worker thread forever; asyncio.wait_for turns that into a recoverable error.
SERIAL_IO_TIMEOUT = 5.0
SERIAL_REOPEN_RETRY_SECONDS = 3.0


class HubClient:
    """Async wrapper around pyserial. Delegates framing/protocol to ProtocolHandler.

    Serial I/O is failure-isolated: a read or write that hangs or raises closes
    the broken port object and reopens it (same port name) so the reader loop
    survives a wedged USB connection without process restart.
    """

    def __init__(self, protocol: ProtocolHandler, event_bus: Optional[Any] = None) -> None:
        self._ser: Optional[serial.Serial] = None
        self._reader_task: Optional[asyncio.Task] = None
        self._port: Optional[str] = None
        self._running = False
        self._protocol = protocol
        self._event_bus = event_bus
        self._recover_lock = asyncio.Lock()
        # Bumped on every successful reopen; lets stale failure reports detect
        # that someone else already recovered the connection.
        self._serial_gen = 0

    def set_on_message(self, callback: Callable[[Dict[str, Any]], None]) -> None:
        self._protocol.set_on_message(callback)

    def _open_port(self, port: str) -> serial.Serial:
        # Preset DTR/RTS before open: the ESP32-C6 USB-Serial-JTAG peripheral
        # resets the chip when the line states pass through an active
        # combination while the port is being configured. Asserting neither
        # line keeps the coordinator (and its Zigbee network) alive across
        # server restarts and serial recovery.
        ser = serial.Serial()
        ser.port = port
        ser.baudrate = 115200
        ser.timeout = 0.5
        ser.dtr = False
        ser.rts = False
        ser.open()
        return ser

    async def connect(self, port: str) -> bool:
        """Open the serial port and start the background reader."""
        try:
            self._ser = await asyncio.to_thread(self._open_port, port)
            # Discard stale boot-log bytes so the parser starts on a fresh line.
            await asyncio.to_thread(self._ser.reset_input_buffer)
            self._port = port
            self._running = True
            self._reader_task = asyncio.create_task(self._read_loop())
            return True
        except Exception as exc:
            logger.error("hub_client_open_failed", port=port, error=str(exc))
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
        old = self._ser
        self._ser = None
        if old is not None:
            try:
                await asyncio.wait_for(asyncio.to_thread(old.close), timeout=3.0)
            except Exception:
                logger.warning("serial_close_failed_on_disconnect")
        self._port = None
        self._protocol.reset()

    async def _read_loop(self) -> None:
        """Background task that reads bytes and feeds the protocol handler.

        Runs for the whole lifetime of the connection: a missing/closed port
        (recovery in progress) only pauses the loop instead of ending it.
        """
        while self._running:
            ser = self._ser
            if ser is None or not ser.is_open:
                await asyncio.sleep(0.2)
                continue
            try:
                chunk = await asyncio.wait_for(
                    asyncio.to_thread(self._read_chunk), timeout=SERIAL_IO_TIMEOUT
                )
            except asyncio.TimeoutError:
                logger.error("serial_read_timeout", port=self._port)
                await self._recover_serial("read_timeout")
                continue
            except Exception:
                logger.exception("serial_read_error")
                await self._recover_serial("read_error")
                continue
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

    def _read_chunk(self) -> bytes:
        """Sync helper to read available bytes from serial."""
        ser = self._ser
        if ser is not None and ser.is_open:
            return ser.read(max(1, ser.in_waiting))
        return b""

    async def _recover_serial(self, reason: str) -> None:
        """Close a wedged port and reopen it, retrying until it comes back.

        Never marks hub devices offline and never stops the reader: once the
        port reopens, traffic (pings, polls) resumes and re-establishes truth.
        """
        gen = self._serial_gen
        async with self._recover_lock:
            if self._serial_gen != gen or not self._running or not self._port:
                return
            logger.warning("serial_recovering", reason=reason, port=self._port)
            old = self._ser
            self._ser = None
            self._serial_gen += 1
            self._protocol.reset()
            if old is not None:
                try:
                    await asyncio.wait_for(asyncio.to_thread(old.close), timeout=3.0)
                except Exception:
                    logger.warning("serial_close_failed_during_recovery")
            while self._running:
                try:
                    self._ser = await asyncio.to_thread(self._open_port, self._port)
                    await asyncio.to_thread(self._ser.reset_input_buffer)
                    logger.warning("serial_reconnected", port=self._port)
                    if self._event_bus:
                        await self._event_bus.publish(
                            "hub_serial_recovered", {"port": self._port}
                        )
                    return
                except Exception as exc:
                    logger.warning(
                        "serial_reopen_failed",
                        port=self._port,
                        error=str(exc),
                        retry_seconds=SERIAL_REOPEN_RETRY_SECONDS,
                    )
                    await asyncio.sleep(SERIAL_REOPEN_RETRY_SECONDS)

    async def send_raw(self, payload: Dict[str, Any]) -> None:
        """Send a JSON payload to the hub."""
        ser = self._ser
        if ser is None or not ser.is_open:
            raise RuntimeError("Serial port is not open")
        line = json.dumps(payload) + "\n"
        logger.info("serial_raw_write", payload=payload)
        if self._event_bus:
            await self._event_bus.publish("hub_serial", {"direction": "tx", "payload": payload})
        try:
            await asyncio.wait_for(
                asyncio.to_thread(ser.write, line.encode()), timeout=SERIAL_IO_TIMEOUT
            )
        except asyncio.TimeoutError as exc:
            logger.error("serial_write_timeout", port=self._port)
            await self._recover_serial("write_timeout")
            raise RuntimeError("Serial write timed out") from exc
        except Exception as exc:
            logger.error("serial_write_failed", port=self._port, error=str(exc))
            await self._recover_serial("write_error")
            raise

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

    async def read_attr(
        self, ieee: str, endpoint: Optional[int], cluster: str, attribute: str
    ) -> Dict[str, Any]:
        """Send a read_attr command to the hub."""
        import uuid

        correlation_id = f"corr-{uuid.uuid4().hex[:12]}"
        payload: Dict[str, Any] = {
            "cmd": "read_attr",
            "ieee": ieee,
            "cluster": cluster,
            "attribute": attribute,
            "correlation_id": correlation_id,
        }
        if endpoint:
            payload["endpoint"] = endpoint
        await self.send_raw(payload)
        return {"correlation_id": correlation_id, "status": "pending"}

    async def read_attr_and_wait(
        self,
        ieee: str,
        endpoint: Optional[int],
        cluster: str,
        attribute: str,
        timeout: float = 5.0,
    ) -> Dict[str, Any]:
        """Send a read_attr command and block until the ack arrives."""
        import uuid

        correlation_id = f"corr-{uuid.uuid4().hex[:12]}"
        payload: Dict[str, Any] = {
            "cmd": "read_attr",
            "ieee": ieee,
            "cluster": cluster,
            "attribute": attribute,
            "correlation_id": correlation_id,
        }
        if endpoint:
            payload["endpoint"] = endpoint

        loop = asyncio.get_running_loop()
        fut = loop.create_future()
        self._protocol.register_future(correlation_id, fut)
        try:
            await self.send_raw(payload)
            return await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError:
            return {"correlation_id": correlation_id, "status": "timeout"}
        finally:
            self._protocol._resolve_future(correlation_id, {})

    async def ping(self, ieee: str, correlation_id: str) -> Dict[str, Any]:
        """Send a liveness ping to a Zigbee device."""
        payload: Dict[str, Any] = {
            "cmd": "ping",
            "ieee": ieee,
            "correlation_id": correlation_id,
        }
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
