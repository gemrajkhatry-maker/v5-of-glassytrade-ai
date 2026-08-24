"""Opt-in cross-process bridge for the reactive message bus.

The normal ``ReactiveBus`` remains in-process and synchronous. This module adds
only the transport boundary needed when a feed, API, or strategy worker lives
in another process: messages are serialized with the domain serializer, sent
through an authenticated local ``multiprocessing.connection`` socket, and
republished on the receiving process's local bus.

The bridge is deliberately transport-only. It does not create a second event
model, broker client, or process supervisor.
"""

from __future__ import annotations

import secrets
import threading
from multiprocessing.connection import Client, Connection, Listener
from multiprocessing.context import AuthenticationError
from pathlib import Path
from typing import Any

from tradex_domain import Depth, DomainEvent, Quote, from_dict, to_dict

from tradex_trading.reactive.bus import ReactiveBus
from tradex_trading.reactive.thread_safe_bus import ThreadSafeReactiveBus

Bus = ReactiveBus | ThreadSafeReactiveBus
TransportMessage = DomainEvent | Depth | Quote
_READY = {"__tradex_process_bus__": "ready"}
_TYPE_KEY = "__tradex_message_type__"


class ProcessBusServer:
    """Accept remote publishers and broadcast messages to local subscribers.

    ``address`` may be a Unix-domain socket path on POSIX or an address tuple
    accepted by ``multiprocessing.connection.Listener``. The generated or
    supplied ``authkey`` is required by every client.
    """

    def __init__(
        self,
        bus: Bus,
        address: str | tuple[str, int],
        *,
        authkey: bytes | None = None,
        backlog: int = 16,
    ) -> None:
        self._bus = bus
        self._address = address
        self._authkey = authkey or secrets.token_bytes(32)
        self._backlog = backlog
        self._listener: Listener | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._clients: set[Connection] = set()
        self._clients_lock = threading.Lock()
        self._subscription: Any | None = None
        self._remote_delivery = threading.local()
        self._origin = threading.local()

    @property
    def authkey(self) -> bytes:
        """Authentication key clients must use."""
        return self._authkey

    @property
    def address(self) -> Any:
        """Bound listener address, available after ``start()``."""
        return self._listener.address if self._listener is not None else self._address

    def start(self) -> ProcessBusServer:
        """Start accepting clients and forwarding local bus messages."""
        if self._listener is not None:
            raise RuntimeError("ProcessBusServer is already started")
        self._stop.clear()
        self._listener = Listener(
            self._address,
            family="AF_UNIX" if isinstance(self._address, str) else None,
            backlog=self._backlog,
            authkey=self._authkey,
        )
        self._subscription = self._bus.subscribe(self._broadcast)
        self._thread = threading.Thread(
            target=self._accept_loop,
            name="tradex-process-bus-accept",
            daemon=True,
        )
        self._thread.start()
        return self

    def _accept_loop(self) -> None:
        assert self._listener is not None
        while not self._stop.is_set():
            try:
                connection = self._listener.accept()
            except AuthenticationError:
                # A bad client must not take down the accept loop.
                continue
            except (OSError, EOFError):
                if not self._stop.is_set():
                    raise
                return
            with self._clients_lock:
                self._clients.add(connection)
            try:
                connection.send(_READY)
            except (BrokenPipeError, EOFError, OSError):
                with self._clients_lock:
                    self._clients.discard(connection)
                connection.close()
                continue
            threading.Thread(
                target=self._read_client,
                args=(connection,),
                name="tradex-process-bus-client",
                daemon=True,
            ).start()

    def _read_client(self, connection: Connection) -> None:
        try:
            while not self._stop.is_set():
                try:
                    payload = connection.recv()
                except (EOFError, OSError):
                    return
                message = _decode(payload)
                self._origin.connection = connection
                try:
                    self._bus.publish(message)
                finally:
                    self._origin.connection = None
        finally:
            with self._clients_lock:
                self._clients.discard(connection)
            try:
                connection.close()
            except OSError:
                pass

    def _broadcast(self, message: object) -> None:
        payload = _encode(message)
        dead: list[Connection] = []
        with self._clients_lock:
            clients = tuple(self._clients)
        origin = getattr(self._origin, "connection", None)
        for connection in clients:
            if connection is origin:
                continue
            try:
                connection.send(payload)
            except (BrokenPipeError, EOFError, OSError):
                dead.append(connection)
        if dead:
            with self._clients_lock:
                for connection in dead:
                    self._clients.discard(connection)
                    try:
                        connection.close()
                    except OSError:
                        pass

    def close(self) -> None:
        """Stop accepting clients and close all connections."""
        if self._listener is None:
            return
        self._stop.set()
        if self._subscription is not None:
            self._subscription.dispose()
            self._subscription = None
        try:
            self._listener.close()
        except OSError:
            pass
        with self._clients_lock:
            clients = tuple(self._clients)
            self._clients.clear()
        for connection in clients:
            try:
                connection.close()
            except OSError:
                pass
        if self._thread is not None:
            self._thread.join(timeout=1.0)
        address = self._address
        self._listener = None
        self._thread = None
        if isinstance(address, str):
            try:
                Path(address).unlink()
            except FileNotFoundError:
                pass

    def __enter__(self) -> ProcessBusServer:
        return self.start()

    def __exit__(self, *exc: object) -> None:
        self.close()


class ProcessBusClient:
    """Connect a local bus to a running :class:`ProcessBusServer`."""

    def __init__(
        self,
        bus: Bus,
        address: str | tuple[str, int],
        *,
        authkey: bytes,
    ) -> None:
        self._bus = bus
        self._address = address
        self._authkey = authkey
        self._connection: Connection | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._subscription: Any | None = None
        self._remote_delivery = threading.local()

    def connect(self) -> ProcessBusClient:
        """Connect and start forwarding both local and remote messages."""
        if self._connection is not None:
            raise RuntimeError("ProcessBusClient is already connected")
        self._stop.clear()
        try:
            connection = Client(self._address, authkey=self._authkey)
            if connection.recv() != _READY:
                connection.close()
                raise ConnectionError("process bus handshake failed")
        except Exception as exc:
            if isinstance(exc, (RuntimeError, ConnectionError)):
                raise
            raise ConnectionError("process bus authentication or connection failed") from exc
        self._connection = connection
        self._subscription = self._bus.subscribe(self._send_local)
        self._thread = threading.Thread(
            target=self._read_loop,
            name="tradex-process-bus-reader",
            daemon=True,
        )
        self._thread.start()
        return self

    def _send_local(self, message: object) -> None:
        # A message received from the server is local to this process only for
        # subscribers; do not send it back and create an echo loop.
        if getattr(self._remote_delivery, "active", False):
            return
        connection = self._connection
        if connection is None:
            return
        try:
            connection.send(_encode(message))
        except (BrokenPipeError, EOFError, OSError):
            # The owning session observes transport loss through its own
            # lifecycle; this adapter does not silently reconnect or reorder.
            self.close()

    def _read_loop(self) -> None:
        connection = self._connection
        if connection is None:
            return
        try:
            while not self._stop.is_set():
                try:
                    payload = connection.recv()
                except (EOFError, OSError):
                    return
                self._remote_delivery.active = True
                try:
                    self._bus.publish(_decode(payload))
                finally:
                    self._remote_delivery.active = False
        finally:
            if not self._stop.is_set():
                self._stop.set()

    def close(self) -> None:
        """Detach and close the client connection."""
        self._stop.set()
        if self._subscription is not None:
            self._subscription.dispose()
            self._subscription = None
        if self._connection is not None:
            try:
                self._connection.close()
            except OSError:
                pass
            self._connection = None
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(timeout=1.0)
        self._thread = None

    def __enter__(self) -> ProcessBusClient:
        return self.connect()

    def __exit__(self, *exc: object) -> None:
        self.close()


def _encode(message: object) -> dict[str, Any]:
    """Encode supported bus payloads and reject arbitrary object leakage."""
    if not isinstance(message, (DomainEvent, Depth, Quote)):
        raise TypeError(
            "ProcessBus transports DomainEvent, Depth, and Quote instances only; "
            f"got {type(message).__name__}"
        )
    encoded = to_dict(message)
    if not isinstance(encoded, dict):
        raise TypeError("message serializer returned a non-object payload")
    encoded[_TYPE_KEY] = f"{type(message).__module__}.{type(message).__qualname__}"
    return encoded


def _decode(payload: object) -> TransportMessage:
    """Decode and validate one supported bus payload."""
    if not isinstance(payload, dict):
        raise TypeError("process bus payload must be an object")
    marker = payload.get(_TYPE_KEY)
    if not isinstance(marker, str):
        raise TypeError("process bus payload has no type marker")
    target: type[TransportMessage]
    if marker == f"{Depth.__module__}.{Depth.__qualname__}":
        target = Depth
    elif marker == f"{Quote.__module__}.{Quote.__qualname__}":
        target = Quote
    else:
        target = DomainEvent
    event = from_dict(target, payload)
    if not isinstance(event, (DomainEvent, Depth, Quote)):
        raise TypeError("process bus payload is not a supported message")
    return event


__all__ = ["ProcessBusClient", "ProcessBusServer", "TransportMessage"]

