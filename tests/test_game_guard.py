"""A running adapter must never write to another game (review finding P1).

PCSX2 keeps the PINE socket open when the user boots another disc.  These tests change the game
under a live connection and check that the old adapter stops writing, that no restore reaches the
new game, and that the normal case (same game) is untouched.  No emulator: fake backends only.
"""
from __future__ import annotations

import socket
import struct
import threading
import time

import pytest

from adapters.shiningforceneo import memory_map as sf_mm
from adapters.suikoden5 import memory_map as su_mm
from adapters.suikoden5.adapter import Suikoden5Adapter
from core.camera_runtime.engine import MODE_ORBIT, CameraRuntime, CameraSettings
from core.memory_backend.guard import CHANGED, SAME, UNKNOWN, GuardedBackend, WriteBlocked
from core.memory_backend.pine_backend import PineBackend, PineStaleSession
from tests.test_suikoden5 import FakeBackend

GID, CRC = su_mm.GAME_ID, su_mm.DISC_CRC


class Inner(FakeBackend):
    """Fake backend that logs writes and can be told what game is "running"."""

    def __init__(self) -> None:
        super().__init__()
        self.writes: list[tuple[int, int]] = []
        self.on_write = None

    def write_u32(self, a: int, v: int) -> None:
        if self.on_write:
            self.on_write(a)
        self.writes.append((a, v & 0xFFFFFFFF))
        super().write_u32(a, v)

    def set_game(self, gid: str, crc: str) -> None:
        self.gid, self.crcv = gid, crc


def armed(inner: Inner | None = None, writable: bool = True) -> tuple[Inner, GuardedBackend]:
    inner = inner or Inner()
    guard = GuardedBackend(inner)
    guard.bind(inner.game_id(), inner.crc(), writable=writable)
    return inner, guard


# --- the guard itself ---------------------------------------------------------------------------
def test_same_game_keeps_writing_and_verifies_clean():
    inner, g = armed()
    assert g.verify() == SAME
    g.write_u32(0x100, 1)
    g.write_float_block(0x200, [1.0, 2.0])
    assert len(inner.writes) == 3 and not g.revoked


def test_identity_is_compared_case_and_space_insensitively():
    inner, g = armed()
    inner.set_game(f" {GID.lower()} ", CRC.upper())
    assert g.verify() == SAME


@pytest.mark.parametrize("gid, crc", [("SLPS-25250", CRC), (GID, "deadbeef"), ("SLPS-25250", "deadbeef")])
def test_serial_or_crc_mismatch_revokes_for_good(gid, crc):
    """TEST-P1-02: the connection stays, the game does not."""
    inner, g = armed()
    inner.set_game(gid, crc)
    assert g.verify() == CHANGED and g.revoked
    with pytest.raises(WriteBlocked):
        g.write_u32(0x100, 1)
    with pytest.raises(WriteBlocked):
        g.write_float_block(0x200, [1.0])
    assert inner.writes == []
    inner.set_game(GID, CRC)                       # switching back does not re-arm a discarded adapter
    assert g.verify() == CHANGED
    with pytest.raises(WriteBlocked):
        g.write_u32(0x100, 1)


@pytest.mark.parametrize("expected, other", [
    ((sf_mm.GAME_ID, sf_mm.DISC_CRC), ("SLPM-66646", "8B383FDF")),
    (("SLPM-66646", "8B383FDF"), (sf_mm.GAME_ID, sf_mm.DISC_CRC)),
    (("SLPM-66646", "8B383FDF"), ("SLPM-66646", sf_mm.DISC_CRC)),
    ((sf_mm.GAME_ID, sf_mm.DISC_CRC), (sf_mm.GAME_ID, "8B383FDF")),
])
def test_neo_and_exa_identity_leases_cannot_be_reused_for_each_other(expected, other):
    inner = Inner()
    inner.set_game(*expected)
    _, guard = armed(inner)
    assert guard.expected == expected and guard.verify() == SAME
    guard.write_u32(0x100, 1)
    before = list(inner.writes)
    inner.set_game(*other)
    assert guard.verify() == CHANGED and guard.revoked
    with pytest.raises(WriteBlocked):
        guard.write_u32(0x104, 2)
    with pytest.raises(WriteBlocked):
        guard.write_float_block(0x108, [1.0, 2.0, 3.0])
    assert inner.writes == before
    inner.set_game(*expected)
    assert guard.verify() == CHANGED  # returning to the disc needs a fresh adapter/guard
    with pytest.raises(WriteBlocked):
        guard.write_u32(0x10C, 3)
    assert inner.writes == before


def test_empty_identity_suspends_writes_until_the_same_game_answers():
    inner, g = armed()
    inner.set_game("", "")
    assert g.verify() == UNKNOWN and not g.revoked
    with pytest.raises(WriteBlocked):
        g.write_u32(0x100, 1)
    inner.set_game(GID, CRC)
    assert g.verify() == SAME
    g.write_u32(0x100, 1)
    assert inner.writes == [(0x100, 1)]


def test_unreadable_identity_changes_nothing():
    inner, g = armed()

    def boom():
        raise OSError("PCSX2 gone")
    inner.game_id = boom
    assert g.verify() == UNKNOWN and not g.revoked
    g.write_u32(0x100, 1)                          # still inside the lease of the last good check
    assert inner.writes == [(0x100, 1)]
    g._verified_at -= 5.0                          # lease over and the game cannot be identified: refuse
    with pytest.raises(WriteBlocked):
        g.write_u32(0x100, 2)
    assert len(inner.writes) == 1


def test_a_writer_renews_an_expired_lease_itself_and_notices_the_change():
    """The poller may be stalled: the writing thread must not rely on it."""
    inner, g = armed()
    g.lease_s = 0.05
    g.write_u32(0x100, 1)
    time.sleep(0.08)
    g.write_u32(0x104, 2)                          # lease expired, same game: renewed, written
    assert len(inner.writes) == 2 and not g.revoked
    time.sleep(0.08)
    inner.set_game("SLPS-25250", "8A6D7F14")
    with pytest.raises(WriteBlocked):
        g.write_u32(0x108, 3)
    assert g.revoked and len(inner.writes) == 2


def test_the_lease_costs_two_identity_reads_per_expiry_not_per_write():
    inner, g = armed()
    reads = {"n": 0}
    orig = inner.game_id
    inner.game_id = lambda: (reads.__setitem__("n", reads["n"] + 1), orig())[1]
    g.lease_s = 0.2
    end = time.monotonic() + 0.5
    n = 0
    while time.monotonic() < end:
        g.write_u32(0x100, n)
        n += 1
    assert n > 1000 and reads["n"] <= 6        # about one check per 0.12 s, whatever the write rate


def test_unsupported_game_is_read_only_but_still_watched():
    inner2, g2 = armed(writable=False)
    with pytest.raises(WriteBlocked):
        g2.write_u32(0x100, 1)
    assert inner2.read_u32(0x100) == 0             # reads pass
    inner2.set_game("SLPM-65908", "64F241D2")      # a supported game starts: noticed
    assert g2.verify() == CHANGED and g2.revoked


def test_unbound_guard_writes_nothing():
    inner = Inner()
    g = GuardedBackend(inner)
    with pytest.raises(WriteBlocked):
        g.write_u32(0x100, 1)
    assert g.verify() == UNKNOWN


def test_a_block_in_flight_stops_at_the_next_word_after_revoke():
    inner, g = armed()
    seen = []

    def on_write(addr):
        seen.append(addr)
        if len(seen) == 2:
            g._revoked = True                      # what revoke() sets first
    inner.on_write = on_write
    with pytest.raises(WriteBlocked):
        g.write_float_block(0x200, [1.0, 2.0, 3.0, 4.0])
    assert len(inner.writes) == 2


def test_revoke_waits_for_the_write_in_flight_and_nothing_follows():
    """The race named in the review: a PINE write is already running when the switch is seen."""
    inner, g = armed()
    entered, release = threading.Event(), threading.Event()

    def slow(addr):
        entered.set()
        release.wait(2.0)
    inner.on_write = slow
    errors = []

    def writer(n):
        try:
            g.write_u32(0x100 + 4 * n, n)
        except WriteBlocked as exc:
            errors.append(exc)

    first = threading.Thread(target=writer, args=(0,))
    first.start()
    assert entered.wait(1.0)
    queued = threading.Thread(target=writer, args=(1,))      # waits for the lock behind the first
    queued.start()
    done = threading.Event()
    threading.Thread(target=lambda: (g.revoke("test"), done.set())).start()
    time.sleep(0.1)
    assert not done.is_set(), "revoke returned while a write was still in flight"
    release.set()
    assert done.wait(2.0)
    first.join(1.0)
    queued.join(1.0)
    assert [a for a, _ in inner.writes] == [0x100]           # the in-flight one finished, the queued one did not
    assert len(errors) == 1


def test_epoch_pin_refuses_writes_on_a_new_connection():
    """PCSX2 restarted (maybe with another game): no write until the game is verified again."""
    port = _free_port()
    srv = _echo_server(port)
    try:
        b = PineBackend(slot=port, connect_timeout=0.3, timeout=0.5)
        b.connect()
        b.write_epoch = b.epoch
        b.write_u32(0x100, 1)                                # same connection: fine
        b._drop_locked()                                     # socket lost; the next request reconnects
        with pytest.raises(PineStaleSession):
            b.write_u32(0x100, 2)
        assert b.epoch == 2 and b.connected                  # the refusal did not tear the new socket down
        assert b.read_u32(0x100) == 0x2222                   # reads are never refused
        b.write_epoch = b.epoch
        b.write_u32(0x100, 3)
    finally:
        srv.close()


def test_guard_verify_rearms_the_pin_only_for_the_same_game():
    port = _free_port()
    srv = _echo_server(port, game=(GID, CRC))
    try:
        b = PineBackend(slot=port, connect_timeout=0.3, timeout=0.5)
        b.connect()
        g = GuardedBackend(b)
        g.bind(GID, CRC)
        g.write_u32(0x100, 1)
        b._drop_locked()
        b.read_u32(0)                                        # reconnect -> epoch 2
        with pytest.raises(PineStaleSession):
            g.write_u32(0x100, 2)
        assert g.verify() == SAME
        g.write_u32(0x100, 3)                                # re-armed
        b._drop_locked()
        b.read_u32(0)
        srv.game = ("SLPS-25250", "8A6D7F14")                # "another PCSX2 process" answered
        assert g.verify() == CHANGED
        with pytest.raises(WriteBlocked):
            g.write_u32(0x100, 4)
    finally:
        srv.close()


# --- a live runtime ----------------------------------------------------------------------------------
def su_memory(inner: Inner) -> None:
    inner.stock()
    inner.write_floats(su_mm.G_FOCUS, [65.6, 14.4, 5.1])
    inner.write_floats(su_mm.G_EYE, [415.9, 104.4, 176.0])
    inner.write_floats(su_mm.G_PITCH, [13.0])
    inner.write_floats(su_mm.G_YAW, [244.0])
    inner.write_floats(su_mm.G_DISTANCE, [400.0])
    inner.write_floats(su_mm.G_FOV, [20.0])


def live_orbit():
    inner = Inner()
    su_memory(inner)
    guard = GuardedBackend(inner)
    adapter = Suikoden5Adapter(guard)
    info = adapter.identify()
    assert info.matched
    guard.bind(info.game_id, info.crc, writable=True)
    rt = CameraRuntime(adapter, CameraSettings(mode=MODE_ORBIT, distance=300.0))
    rt.start()
    deadline = time.time() + 3.0
    while time.time() < deadline and not any(a in (su_mm.CAM_HOOK, su_mm.CAM_HOOK + 4) for a, _ in inner.writes):
        time.sleep(0.02)
    assert any(a == su_mm.CAM_HOOK for a, _ in inner.writes), "the orbit never patched the game"
    return inner, guard, rt


def test_old_runtime_writes_nothing_after_the_game_changes_and_restore_is_inert():
    """TEST-P1-02 / P1-03: orbit running, another game boots under the same connection."""
    inner, guard, rt = live_orbit()
    try:
        inner.set_game(sf_mm.GAME_ID, sf_mm.DISC_CRC.lower())
        assert guard.verify() == CHANGED
        n = len(inner.writes)
        mem = dict(inner.mem)
        time.sleep(0.4)                                       # the 1.2 kHz loop keeps trying
        rt.restore()                                          # what _teardown used to do
        rt.set_stick(1.0, 0.0)
        time.sleep(0.2)
        assert len(inner.writes) == n and inner.mem == mem
        rt.abandon()
        assert not rt.running
        assert len(inner.writes) == n
    finally:
        rt.abandon()


def test_abandon_writes_nothing_even_without_a_guard():
    inner, guard, rt = live_orbit()
    n = len(inner.writes)
    rt.abandon()
    assert not rt.running and len(inner.writes) <= n + 20    # at most the ticks that were already running
    after = len(inner.writes)
    time.sleep(0.2)
    assert len(inner.writes) == after


def test_runtime_stats_do_not_keep_the_guard_refusal_as_an_error():
    inner, guard, rt = live_orbit()
    try:
        inner.set_game("", "")
        guard.verify()                                        # suspended
        time.sleep(0.3)
        inner.set_game(GID, CRC)
        assert guard.verify() == SAME
        time.sleep(1.5)                                       # patch re-check runs about once a second
        assert "write blocked" not in rt.stats.last_error
    finally:
        rt.abandon()


# --- helpers ----------------------------------------------------------------------------------------------
def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class _echo_server:
    """Minimal PINE stand-in: OK replies, 0x2222 for a read, the configured game for ID / UUID."""

    def __init__(self, port: int, game=("", "")) -> None:
        self.game = game
        self.sock = socket.socket()
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", port))
        self.sock.listen(5)
        self.conns: list[socket.socket] = []
        threading.Thread(target=self._accept, daemon=True).start()

    def _accept(self) -> None:
        try:
            while True:
                conn, _ = self.sock.accept()
                self.conns.append(conn)
                threading.Thread(target=self._serve, args=(conn,), daemon=True).start()
        except OSError:
            pass

    def _serve(self, conn: socket.socket) -> None:
        try:
            while True:
                head = self._exact(conn, 4)
                total = struct.unpack("<I", head)[0]
                body = self._exact(conn, total - 4)
                op = body[0]
                if op in (0x0C, 0x0D):                        # MSG_ID / MSG_UUID
                    text = (self.game[0] if op == 0x0C else self.game[1]).encode() + b"\0"
                    data = struct.pack("<I", len(text)) + text
                elif op == 0x02:
                    data = struct.pack("<I", 0x2222)
                else:
                    data = b""
                reply = bytes([0]) + data
                conn.sendall(struct.pack("<I", 4 + len(reply)) + reply)
        except OSError:
            pass

    @staticmethod
    def _exact(conn, n):
        buf = b""
        while len(buf) < n:
            chunk = conn.recv(n - len(buf))
            if not chunk:
                raise OSError("closed")
            buf += chunk
        return buf

    def close(self) -> None:
        self.sock.close()
        for c in self.conns:
            try:
                c.close()
            except OSError:
                pass
