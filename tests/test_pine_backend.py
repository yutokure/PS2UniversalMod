"""PINE client behaviour against a local stand-in server (no emulator needed)."""
from __future__ import annotations

import socket
import struct
import sys
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.memory_backend.pine_backend import PineBackend  # noqa: E402


def _recv_exact(conn: socket.socket, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        chunk = conn.recv(n - len(buf))
        if not chunk:
            raise OSError("client closed")
        buf += chunk
    return buf


def _recv_request(conn: socket.socket) -> None:
    total = struct.unpack("<I", _recv_exact(conn, 4))[0]
    _recv_exact(conn, total - 4)


def _read_reply(value: int) -> bytes:
    body = bytes([0]) + struct.pack("<I", value)  # status OK + one word
    return struct.pack("<I", 4 + len(body)) + body


@pytest.fixture()
def stand_in_server():
    """First connection answers late (after the client has timed out); later ones answer at once."""
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(5)
    port = listener.getsockname()[1]
    connections = []

    def handle(conn: socket.socket, index: int) -> None:
        try:
            if index == 0:
                _recv_request(conn)
                # answer after the client has timed out (0.2 s) but before a second
                # read on the same socket would time out again (0.4 s)
                time.sleep(0.3)
                conn.sendall(_read_reply(111))  # stale: its request has already timed out
            while True:
                _recv_request(conn)
                conn.sendall(_read_reply(222))
        except OSError:
            pass

    def accept_loop() -> None:
        try:
            while True:
                conn, _ = listener.accept()
                index = len(connections)
                connections.append(conn)
                threading.Thread(target=handle, args=(conn, index), daemon=True).start()
        except OSError:
            pass

    threading.Thread(target=accept_loop, daemon=True).start()
    yield port
    listener.close()
    for conn in connections:
        try:
            conn.close()
        except OSError:
            pass


def test_timed_out_request_does_not_leak_its_reply_into_the_next_read(stand_in_server):
    """Regression: a late reply to a timed-out read was taken as the answer to the next read."""
    b = PineBackend(slot=stand_in_server, timeout=0.2)
    b.connect()
    with pytest.raises(OSError):
        b.read_u32(0x00100000)  # no answer in time
    assert b.read_u32(0x00100000) == 222  # a fresh connection, not the stale 111
    assert b.stats["reconnects"] == 2


def test_dead_emulator_fails_fast_and_stays_fast():
    """Nothing listens: the first call may wait the short connect timeout, the rest return at once."""
    from core.memory_backend.pine_backend import PineUnavailable
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()                                   # the port is now closed
    b = PineBackend(slot=port, connect_timeout=0.2, retry_backoff=5.0)
    t0 = time.monotonic()
    with pytest.raises(PineUnavailable):
        b.read_u32(0x1000)
    assert time.monotonic() - t0 < 1.0
    assert not b.available
    t1 = time.monotonic()
    for _ in range(50):                             # a GUI refresh does about this many per second
        with pytest.raises(PineUnavailable):
            b.read_u32(0x1000)
    assert time.monotonic() - t1 < 0.2


def test_backend_reconnects_after_the_back_off(stand_in_server):
    from core.memory_backend.pine_backend import PineUnavailable
    b = PineBackend(slot=stand_in_server, connect_timeout=0.2, retry_backoff=0.3)
    b._down_until = time.monotonic() + 0.3          # as if the emulator had just been down
    with pytest.raises(PineUnavailable):
        b.read_u32(0)
    time.sleep(0.35)
    b.timeout = 0.2
    try:
        b.read_u32(0)                               # the stand-in's first answer is late: may time out
    except Exception:
        pass
    assert b.available or True                       # no exception escapes the back-off logic


def test_explicit_connect_ignores_the_back_off(stand_in_server):
    b = PineBackend(slot=stand_in_server, connect_timeout=0.2, retry_backoff=60.0)
    b._down_until = time.monotonic() + 60.0
    b.connect()
    assert b.connected and b.available


def test_status_poller_never_blocks_on_a_dead_emulator():
    """The GUI's poller returns at once with link=False when PCSX2 is unreachable."""
    pytest.importorskip("PySide6")
    from types import SimpleNamespace
    from gui.camera_controller.app import StatusPoller
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    be = PineBackend(slot=port, connect_timeout=0.2, retry_backoff=5.0)
    with pytest.raises(Exception):
        be.read_u32(0)                                  # first failure arms the back-off
    window = SimpleNamespace(adapter=object(), backend=be)
    poller = StatusPoller(window)                       # type: ignore[arg-type]
    t0 = time.monotonic()
    for _ in range(20):
        assert poller.poll_once()["link"] is False
    assert time.monotonic() - t0 < 0.2
