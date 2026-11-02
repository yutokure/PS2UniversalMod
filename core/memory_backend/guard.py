"""Write guard: an adapter may only write to the game it was made for.

PCSX2's PINE connection outlives the game: the emulator can boot another disc while the socket
stays open.  An adapter that keeps writing then pokes its own addresses into the new game, and
``CameraRuntime.restore()`` would "hand the camera back" by writing stock values there as well.

``GuardedBackend`` sits between the adapters and the PINE backend.  Reads pass through; every write
asks the guard first.  The guard is armed for one ``(serial, CRC)`` pair and stops writing when

* the live game no longer matches (``verify`` finds a different pair): this is final, the guard is
  *revoked* and the adapter behind it must be discarded without a restore;
* the live game cannot be read right now (PCSX2 between two games reports no serial): writes are
  *suspended* until the same game answers again;
* PINE was reconnected since the game was last verified (PineBackend.epoch): refused by the backend
  itself, under its request lock, until ``verify`` sees the same game on the new connection.

Identity is a *lease*: a write is allowed only while the game was verified within the last
``lease_s`` seconds.  The GUI's status poller renews it about every 0.4 s; if nobody has (the poller
is stalled, PCSX2 does not answer) the writing thread renews it itself, which costs two PINE reads
a few times per second and nothing on the other writes.  A game that cannot be identified is
treated as a different game: the write is refused.

Revoking sets the flag first (no new write starts) and then waits for the write in flight, so when
``revoke`` returns nothing more reaches the old game.  The only unguarded time is the one before a
change is seen: at most ``lease_s`` while the camera is writing.
"""
from __future__ import annotations

import struct
import threading
import time

SAME = "same"
CHANGED = "changed"
UNKNOWN = "unknown"
#: how long one successful identity check lets writes go on
LEASE_S = 0.25
#: the writing thread renews the lease once it is this fraction used up
RENEW_AT = 0.6


class WriteBlocked(RuntimeError):
    """A write was refused because the game it is aimed at is not (verifiably) the running one."""


class GuardedBackend:
    def __init__(self, inner) -> None:
        self._inner = inner
        self._lock = threading.Lock()          # held for the duration of one write (or one block)
        self._verify_lock = threading.Lock()   # one verify at a time (GUI thread and poller)
        self._expected: tuple[str, str] | None = None
        self._writable = False
        self._revoked = False
        self._suspended = False
        self.revoke_reason = ""
        self.lease_s = LEASE_S
        self._verified_at = 0.0

    # --- arming ---------------------------------------------------------------------------
    def bind(self, game_id: str, crc: str, writable: bool = True) -> None:
        """Arm the guard for this game.  ``writable`` False keeps every write refused (unsupported game)."""
        with self._verify_lock:
            self._expected = (self._norm(game_id), self._norm(crc))
            self._writable = bool(writable)
            self._revoked = False
            self._suspended = False
            self.revoke_reason = ""
            self._pin(self._epoch())
            self._verified_at = time.monotonic()     # the caller has just identified the game

    @staticmethod
    def _norm(text: str) -> str:
        return (text or "").strip().upper()

    @property
    def expected(self) -> tuple[str, str] | None:
        return self._expected

    @property
    def revoked(self) -> bool:
        return self._revoked

    @property
    def writes_allowed(self) -> bool:
        return self._writable and not self._revoked and not self._suspended

    def _epoch(self):
        return getattr(self._inner, "epoch", None)

    def _pin(self, epoch) -> None:
        """Let the backend send writes only on the connection with this epoch."""
        if epoch is not None and hasattr(self._inner, "write_epoch"):
            self._inner.write_epoch = epoch

    # --- identity check ----------------------------------------------------------------------
    def verify(self) -> str:
        """Compare the running game with the one this guard was armed for.

        Returns ``SAME`` (writes allowed again, if they were suspended or the connection changed),
        ``CHANGED`` (a different serial or CRC: the guard is revoked for good) or ``UNKNOWN`` (could
        not be read; nothing is changed except that an empty answer suspends writes).
        """
        if self._revoked:
            return CHANGED
        if self._expected is None:
            return UNKNOWN
        with self._verify_lock:
            return self._verify_locked()

    def _verify_locked(self) -> str:
        if self._revoked:
            return CHANGED
        before = self._epoch()
        try:
            gid = self._norm(self._inner.game_id())
            crc = self._norm(self._inner.crc())
        except Exception:  # noqa: BLE001 - PCSX2 gone or busy; the link logic reports that
            return UNKNOWN
        if not gid or not crc:
            # a VM that is shutting down or booting has no disc serial yet: do not write meanwhile
            self._suspended = True
            return UNKNOWN
        if (gid, crc) != self._expected:
            self.revoke(f"game changed: {self._expected[0]}/{self._expected[1]} -> {gid}/{crc}")
            return CHANGED
        # Pin to the connection the answer was read on.  If PINE was reconnected meanwhile
        # the pin is already stale, writes stay refused and the next verify settles it.
        self._pin(before)
        if self._epoch() != before:
            return UNKNOWN
        self._suspended = False
        self._verified_at = time.monotonic()
        return SAME

    def _renew(self) -> None:
        """Renew an ageing lease from the writing thread (never called with the write lock held).

        It renews at 60 % of the lease, not at expiry: a lease that ran out between this check and
        ``_check`` would refuse a perfectly good write.
        """
        renew_after = self.lease_s * RENEW_AT
        if time.monotonic() - self._verified_at <= renew_after:
            return
        if self._revoked or not self._writable or self._expected is None:
            return                          # _check refuses these anyway
        with self._verify_lock:
            if time.monotonic() - self._verified_at > renew_after:
                self._verify_locked()

    def revoke(self, reason: str = "revoked") -> None:
        """Refuse every further write, then wait until the write in flight (if any) has finished."""
        self._revoked = True
        self.revoke_reason = self.revoke_reason or reason
        with self._lock:
            pass

    # --- guarded writes ----------------------------------------------------------------------
    def _check(self, lease: bool = True) -> None:
        if self._revoked:
            raise WriteBlocked(f"write blocked: {self.revoke_reason or 'the game has changed'}")
        if not self._writable:
            raise WriteBlocked("write blocked: unsupported game")
        if self._suspended:
            raise WriteBlocked("write blocked: waiting for the game to be identified")
        if lease and time.monotonic() - self._verified_at > self.lease_s:
            raise WriteBlocked("write blocked: the running game could not be identified")

    def write_u32(self, addr: int, value: int) -> None:
        self._renew()
        with self._lock:
            self._check()
            self._inner.write_u32(addr, value)

    def write_float_block(self, addr: int, values) -> None:
        values = list(values)
        self._renew()
        with self._lock:
            self._check()
            for i, v in enumerate(values):
                self._check(lease=False)    # a revoke during a block stops it at the next word
                self._inner.write_u32(addr + 4 * i, struct.unpack("<I", struct.pack("<f", float(v)))[0])

    write_floats = write_float_block

    def load_state_slot(self, slot: int) -> None:
        self._renew()
        with self._lock:
            self._check()
            self._inner.load_state_slot(slot)

    # --- everything else (reads, identity strings, availability) goes straight through ----------
    def __getattr__(self, name):
        return getattr(self._inner, name)
