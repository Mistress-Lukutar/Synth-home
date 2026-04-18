"""Protocol layer: JSON framing and request/response correlation."""

import asyncio
import json
from typing import Optional, Dict, Any, Callable

import structlog

logger = structlog.get_logger(__name__)


class ProtocolHandler:
    """Handles newline-delimited JSON framing and correlates responses."""

    def __init__(self) -> None:
        self._buffer = ""
        self._list_future: Optional[asyncio.Future[list]] = None
        self._on_message: Optional[Callable[[Dict[str, Any]], None]] = None
        self._fetch_lock = asyncio.Lock()

    def set_on_message(self, callback: Callable[[Dict[str, Any]], None]) -> None:
        self._on_message = callback

    def feed(self, chunk: bytes) -> list[Dict[str, Any]]:
        """Feed raw bytes into the parser and return complete messages."""
        messages: list[Dict[str, Any]] = []
        self._buffer += chunk.decode("utf-8", errors="ignore")
        logger.info("protocol_buffer_state", buffer_len=len(self._buffer), has_newline="\n" in self._buffer)
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            line = line.strip()
            if not line:
                logger.debug("protocol_empty_line_skipped")
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError as exc:
                logger.warning("protocol_json_parse_failed", line=line[:400], error=str(exc))
                continue
            messages.append(data)
        return messages

    def dispatch(self, messages: list[Dict[str, Any]]) -> None:
        """Dispatch parsed messages to correlation logic and user callback."""
        for data in messages:
            self._handle_single(data)

    def _handle_single(self, data: Dict[str, Any]) -> None:
        evt = data.get("evt") or data.get("event")
        ieee = data.get("ieee_addr") or data.get("ieee")
        endpoints = data.get("endpoints")
        devices = data.get("devices")
        correlation_id = data.get("correlation_id")
        status = data.get("status")

        # Verbose raw logging for debugging firmware compatibility
        if evt == "device_list":
            logger.info(
                "hub_raw_device_list",
                device_count=len(devices) if isinstance(devices, list) else None,
                first_device_summary=str(devices[0])[:300] if isinstance(devices, list) and devices else None,
                raw_keys=list(data.keys()),
            )
        elif evt in ("command_status", "state_change", "device_joined", "device_left"):
            logger.info(
                "hub_raw_event",
                hub_event=evt,
                ieee=ieee,
                correlation_id=correlation_id,
                status=status,
                raw_keys=list(data.keys()),
                raw_summary=str(data)[:400],
            )
        else:
            logger.debug(
                "hub_raw_message",
                hub_event=evt,
                ieee=ieee,
                raw_keys=list(data.keys()),
                raw_summary=str(data)[:300],
            )

        if self._list_future is not None and not self._list_future.done():
            if evt == "device_list":
                self._list_future.set_result(data.get("devices", []))
                self._list_future = None
        if self._on_message is not None:
            try:
                self._on_message(data)
            except Exception:
                logger.exception("protocol_on_message_failed")

    async def request_device_list(
        self, send_fn: Callable[[], None]
    ) -> list[Dict[str, Any]]:
        """Send a list request and wait for the correlated response."""
        async with self._fetch_lock:
            if self._list_future is not None and not self._list_future.done():
                try:
                    return await asyncio.wait_for(
                        asyncio.shield(self._list_future), timeout=3.0
                    )
                except asyncio.TimeoutError:
                    return []

            loop = asyncio.get_running_loop()
            self._list_future = loop.create_future()
            try:
                send_fn()
            except Exception as exc:
                if self._list_future is not None and not self._list_future.done():
                    self._list_future.set_exception(exc)
                self._list_future = None
                raise

            try:
                return await asyncio.wait_for(self._list_future, timeout=3.0)
            except asyncio.TimeoutError:
                if self._list_future is not None and not self._list_future.done():
                    self._list_future.cancel()
                return []
            finally:
                self._list_future = None

    def reset(self) -> None:
        """Cancel any pending futures (e.g. on disconnect)."""
        if self._list_future is not None and not self._list_future.done():
            try:
                self._list_future.cancel()
            except Exception:
                pass
        self._list_future = None
        self._buffer = ""
