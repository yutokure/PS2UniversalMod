"""Code cave that holds the right stick at centre while the orbit is on.

The game copies its pad packet into a struct with a byte loop.  The load at
``PAD_CALL_SITE`` (``lbu v0,0(a1)``) reads one packet byte; the right stick is packet bytes
X (+4) and Y (+5), and the copy then stores v0.  The call site becomes ``j PAD_CAVE``.  The
cave repeats the load, and when ``PAD_BLOCK_FLAG`` is set and the source byte is a
right-stick byte it sets v0 to the centre value.  Every other byte (left stick, buttons)
is copied unchanged.  The delay slot of the call site is the loop's own ``addiu a2`` and
the cave's delay slot is the loop's ``addiu a1``, so the loop runs in the original order.

k0 and k1 are the only scratch registers.  They are reserved for the kernel, but the
kernel restores the user context on return from an interrupt.

Installed with compare-and-swap, like ``fov_cave``: ``uninstall_call_site`` puts the
original load back and leaves the cave words in place (they do nothing without the call).
"""
from __future__ import annotations

from . import memory_map as mm

ZERO, V0, A1, K0, K1 = 0, 2, 5, 26, 27


class CavePatchError(RuntimeError):
    """The call site or the cave area holds something this module did not write."""


def _j(target: int) -> int:
    return 0x08000000 | ((target >> 2) & 0x03FFFFFF)


def _lui(rt: int, imm: int) -> int:
    return 0x3C000000 | (rt << 16) | ((imm >> 16) & 0xFFFF)


def _ori(rt: int, rs: int, imm: int) -> int:
    return 0x34000000 | (rs << 21) | (rt << 16) | (imm & 0xFFFF)


def _addiu(rt: int, rs: int, imm: int) -> int:
    return 0x24000000 | (rs << 21) | (rt << 16) | (imm & 0xFFFF)


def _lw(rt: int, base: int, off: int) -> int:
    return 0x8C000000 | (base << 21) | (rt << 16) | (off & 0xFFFF)


def _beq(rs: int, rt: int, off: int) -> int:
    return 0x10000000 | (rs << 21) | (rt << 16) | (off & 0xFFFF)


def _bne(rs: int, rt: int, off: int) -> int:
    return 0x14000000 | (rs << 21) | (rt << 16) | (off & 0xFFFF)


def _subu(rd: int, rs: int, rt: int) -> int:
    return (rs << 21) | (rt << 16) | (rd << 11) | 0x23


def _sltiu(rt: int, rs: int, imm: int) -> int:
    return 0x2C000000 | (rs << 21) | (rt << 16) | (imm & 0xFFFF)


NOP = 0x00000000


def cave_words() -> list[int]:
    """The cave as 32-bit instructions, starting at ``PAD_CAVE``.

    Each right-stick source is checked as ``a1 - source`` in [0, 1] (unsigned): the X and
    the Y byte of one packet copy.
    """
    flag = mm.PAD_BLOCK_FLAG
    words = [
        0x90A20000,                                              # 0  lbu v0,0(a1) (the original load)
        _lui(K0, flag),                                          # 1  lui  k0,hi(flag)
        _lw(K0, K0, flag),                                       # 2  lw   k0,lo(flag)(k0)
        None,                                                    # 3  beq  k0,zero,-> done
        NOP,                                                     # 4
    ]
    rx0, rx1 = mm.PAD_RX_SOURCES
    words += [
        _lui(K1, rx0),                                           # 5  lui  k1,hi(rx0)
        _ori(K1, K1, rx0),                                       # 6  ori  k1,k1,lo(rx0)
        _subu(K1, A1, K1),                                       # 7  subu k1,a1,k1
        _sltiu(K0, K1, 2),                                       # 8  sltiu k0,k1,2
        None,                                                    # 9  bne  k0,zero,-> mask
        NOP,                                                     # 10
        _lui(K1, rx1),                                           # 11 lui  k1,hi(rx1)
        _ori(K1, K1, rx1),                                       # 12 ori  k1,k1,lo(rx1)
        _subu(K1, A1, K1),                                       # 13 subu k1,a1,k1
        _sltiu(K0, K1, 2),                                       # 14 sltiu k0,k1,2
        None,                                                    # 15 beq  k0,zero,-> done
        NOP,                                                     # 16
        _ori(V0, ZERO, mm.PAD_CENTRE),                           # 17 mask: ori v0,zero,centre
        _j(mm.PAD_RETURN),                                       # 18 done: j PAD_RETURN
        _addiu(A1, A1, 1),                                       # 19 delay: addiu a1,a1,1
    ]
    done, mask = 18, 17
    words[3] = _beq(K0, ZERO, done - 3 - 1)
    words[9] = _bne(K0, ZERO, mask - 9 - 1)
    words[15] = _beq(K0, ZERO, done - 15 - 1)
    return words


def _read_words(backend, addr: int, count: int) -> list[int]:
    return [backend.read_u32(addr + 4 * i) for i in range(count)]


def call_site_state(backend) -> str:
    """'original', 'patched' or 'unknown' for the load at PAD_CALL_SITE."""
    word = backend.read_u32(mm.PAD_CALL_SITE)
    if word == mm.PAD_CALL_WORD:
        return "original"
    if word == _j(mm.PAD_CAVE):
        return "patched"
    return "unknown"


def install(backend) -> None:
    """Write the cave (if absent) and point the call site at it.  Idempotent."""
    words = cave_words()
    have = _read_words(backend, mm.PAD_CAVE, len(words))
    if have != words:
        if any(have):
            raise CavePatchError(f"cave area 0x{mm.PAD_CAVE:08X} is not free")
        for i, w in enumerate(words):
            backend.write_u32(mm.PAD_CAVE + 4 * i, w)
    state = call_site_state(backend)
    if state == "patched":
        return
    if state != "original":
        raise CavePatchError(f"call site 0x{mm.PAD_CALL_SITE:08X} holds an unexpected word")
    backend.write_u32(mm.PAD_CALL_SITE, _j(mm.PAD_CAVE))


def uninstall_call_site(backend) -> None:
    """Put the original load back.  Does nothing when the call site is not ours."""
    if call_site_state(backend) == "patched":
        backend.write_u32(mm.PAD_CALL_SITE, mm.PAD_CALL_WORD)


def set_flag(backend, on: bool) -> None:
    backend.write_u32(mm.PAD_BLOCK_FLAG, 1 if on else 0)


def read_flag(backend) -> bool:
    return backend.read_u32(mm.PAD_BLOCK_FLAG) != 0
