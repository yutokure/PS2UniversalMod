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
