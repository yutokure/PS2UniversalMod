"""Low-latency memory backend over PCSX2's PINE IPC.

PINE is a request/response TCP protocol (127.0.0.1:28011 by default).  Two
details matter for 30-60 Hz camera work:

* ``write_float_block`` pipelines all writes of one frame into a single TCP
  send, then drains the replies.  Round-trip latency therefore costs once per
  block instead of once per word.
* the socket is re-opened transparently when PCSX2 restarts, so the controller
  survives an emulator restart without restarting the GUI.
* when PCSX2 is gone (closed or killed) a connect attempt to the dead port takes the whole
  connect timeout on Windows.  Every caller, the GUI thread included, would then wait that long
  per request, so after a failed connect the backend refuses further requests *immediately* for
  ``retry_backoff`` seconds (``PineUnavailable``) and only then tries again.
* every new connection gets a number (``epoch``).  A caller that has verified which game is running
  can pin writes to that connection (``write_epoch``): once the socket has been re-opened, possibly
  against another PCSX2 process, writes are refused until the caller verifies the game again.
"""
from __future__ import annotations

import socket
import struct
import threading
import time

MSG_READ32 = 0x02
MSG_WRITE32 = 0x06
MSG_VERSION = 0x08
MSG_TITLE = 0x0B
MSG_ID = 0x0C
MSG_UUID = 0x0D
MSG_STATUS = 0x0F
MSG_LOADSTATE_SLOT = 0x11

IPC_OK = 0
DEFAULT_SLOT = 28011
#: requests that change the emulated machine (everything else only reads)
WRITE_OPCODES = frozenset({MSG_WRITE32, MSG_LOADSTATE_SLOT})


class PineError(RuntimeError):
    pass


class PineUnavailable(PineError):
    """PCSX2 cannot be reached right now; raised at once, without waiting for a timeout."""


class PineStaleSession(PineError):
    """A write was refused because the connection is not the one the caller verified the game on."""


class PineBackend:
    def __init__(self, slot: int = DEFAULT_SLOT, timeout: float = 2.0,
                 connect_timeout: float = 0.3, retry_backoff: float = 1.0) -> None:
        self.slot = slot
        self.timeout = timeout
        #: a PINE server on this machine answers a connect in well under a millisecond
        self.connect_timeout = connect_timeout
        self.retry_backoff = retry_backoff
        self._down_until = 0.0
        self._sock: socket.socket | None = None
        self._lock = threading.Lock()
        #: number of the current connection (0 = never connected); +1 on every (re)connect
        self.epoch = 0
        #: when set, a write is only sent on the connection with this epoch (see PineStaleSession)
        self.write_epoch: int | None = None
        self.stats = {"reads": 0, "writes": 0, "reconnects": 0, "errors": 0}

    # --- lifecycle ----------------------------------------------------
    def connect(self) -> None:
        """Open the connection now (an explicit request ignores the retry back-off)."""
        with self._lock:
            self._down_until = 0.0
            self._connect_locked()

    def _connect_locked(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None
        try:
            s = socket.create_connection(("127.0.0.1", self.slot), timeout=self.connect_timeout)
        except OSError as exc:
            self._down_until = time.monotonic() + self.retry_backoff
            raise PineUnavailable(f"PCSX2 is not reachable on port {self.slot}: {exc}") from exc
        self._down_until = 0.0
        s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        s.settimeout(self.timeout)
        self._sock = s
        self.epoch += 1
        self.stats["reconnects"] += 1

    def close(self) -> None:
        with self._lock:
            self._drop_locked()

    def _drop_locked(self) -> None:
        """Close the socket.  Callers hold the lock; the next request reconnects."""
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None

    @property
    def connected(self) -> bool:
        return self._sock is not None

    @property
    def available(self) -> bool:
        """False while PCSX2 is known to be unreachable (no request is sent then)."""
        return self._sock is not None or time.monotonic() >= self._down_until

    def _ensure(self) -> socket.socket:
        if self._sock is None:
            wait = self._down_until - time.monotonic()
            if wait > 0:
                raise PineUnavailable(f"PCSX2 is not reachable (next attempt in {wait:.1f}s)")
            self._connect_locked()
        return self._sock

    # --- raw ----------------------------------------------------------
    def _recv_exact(self, sock: socket.socket, n: int) -> bytes:
        buf = b""
        while len(buf) < n:
            chunk = sock.recv(n - len(buf))
            if not chunk:
                raise PineError("connection closed by PCSX2")
            buf += chunk
        return buf

    def _drain(self, sock: socket.socket, count: int) -> None:
        for _ in range(count):
            total = struct.unpack("<I", self._recv_exact(sock, 4))[0]
            if total < 5 or total > 0x10000:
                raise PineError(f"bad reply size {total}")
            body = self._recv_exact(sock, total - 4)
            if body[0] != IPC_OK:
                raise PineError(f"PINE op failed: 0x{body[0]:02x}")

    def _request(self, opcode: int, payload: bytes, reply_len: int) -> bytes:
        data = self._request_raw(opcode, payload)
        return data.ljust(reply_len, b"\0")[:reply_len]

    def _request_raw(self, opcode: int, payload: bytes) -> bytes:
        with self._lock:
            try:
                sock = self._ensure()
                # checked under the lock and after any reconnect, so no write can slip onto a
                # new connection between the caller's check and the send
                if (opcode in WRITE_OPCODES and self.write_epoch is not None
                        and self.write_epoch != self.epoch):
                    raise PineStaleSession(
                        f"write refused: PCSX2 was reconnected (connection {self.epoch}, "
                        f"game verified on {self.write_epoch})")
                sock.sendall(struct.pack("<I", 5 + len(payload)) + bytes([opcode]) + payload)
                total = struct.unpack("<I", self._recv_exact(sock, 4))[0]
                body = self._recv_exact(sock, total - 4)
            except PineStaleSession:
                raise                   # nothing was sent: the connection is fine
            except (OSError, PineError):
                self.stats["errors"] += 1
                # A request that timed out may still be answered later.  Keeping the
                # socket would hand that stale reply to the next request, and every
                # read after it would be off by one, so start again on a new connection.
                self._drop_locked()
                raise
        if body[0] != IPC_OK:
            raise PineError(f"PINE op 0x{opcode:02x} failed")
        return body[1:]

    # --- typed helpers -------------------------------------------------
    def read_u32(self, addr: int) -> int:
        self.stats["reads"] += 1
        return struct.unpack("<I", self._request(MSG_READ32, struct.pack("<I", addr & 0xFFFFFFFF), 4))[0]

    def read_f32(self, addr: int) -> float:
        return struct.unpack("<f", self._request(MSG_READ32, struct.pack("<I", addr & 0xFFFFFFFF), 4))[0]

    def read_floats(self, addr: int, count: int) -> list[float]:
        """Read ``count`` consecutive floats.

        PCSX2's PINE server processes exactly one packet per read() and has no
        request queue (see PINE.cpp ClientLoop), so requests must stay strictly
        sequential.  A round trip measures ~0.06 ms on loopback, which is fast
        enough that a 9-request camera frame costs well under 1 ms.
        """
        return [self.read_f32(addr + 4 * i) for i in range(count)]

    def write_u32(self, addr: int, value: int) -> None:
        self.stats["writes"] += 1
        self._request(MSG_WRITE32, struct.pack("<II", addr & 0xFFFFFFFF, value & 0xFFFFFFFF), 0)

    def write_float_block(self, addr: int, values) -> None:
        """Write consecutive float32 values.

        Requests are issued strictly one at a time because the PINE server has
        no pipelining (it reads a single packet, replies, then loops).  Ten
        words still complete in ~0.6 ms.
        """
        values = list(values)
        for i, v in enumerate(values):
            self.write_u32(addr + 4 * i, struct.unpack("<I", struct.pack("<f", float(v)))[0])

    def write_floats(self, addr: int, values) -> None:
        self.write_float_block(addr, values)

    # --- identity -------------------------------------------------------
    def _string(self, opcode: int) -> str:
        data = self._request_raw(opcode, b"")
        if len(data) >= 4:
            n = struct.unpack("<I", data[:4])[0]
            if 0 < n <= len(data) - 4:
                return data[4:4 + n].split(b"\0")[0].decode("utf-8", "replace")
        return data.split(b"\0")[0].decode("utf-8", "replace")

    def version(self) -> str:
        return self._string(MSG_VERSION)

    def title(self) -> str:
        return self._string(MSG_TITLE)

    def game_id(self) -> str:
        return self._string(MSG_ID)

    def crc(self) -> str:
        return self._string(MSG_UUID)

    def status(self) -> int:
        return struct.unpack("<I", self._request(MSG_STATUS, b"", 4))[0]

    def load_state_slot(self, slot: int) -> None:
        """Load a PCSX2 savestate slot through PINE (no GDB session needed)."""
        self._request(MSG_LOADSTATE_SLOT, struct.pack("<I", slot & 0xFFFFFFFF), 0)

    def wait_ready(self, timeout: float = 90.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                self.connect()
                self.version()
                return True
            except (OSError, PineError):
                time.sleep(1.0)
        return False
