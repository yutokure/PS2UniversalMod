"""Execute the isolated movement cave on synthetic memory; no emulator access."""
from __future__ import annotations

from types import SimpleNamespace
import struct

import pytest

from adapters.magnacarta import directions as d
from core import mips_asm as m
from tests.test_druaga import FakeBackend
from tests.test_radiata import CaveMachine as BaseMachine

# Public bank contract supplied by the adapter owner. Tests intentionally pin
# these values independently, so changing shared-map layout needs review here.
MAP = SimpleNamespace(MOD_BLOCK=0xFF000, MAGIC=0x4D434131, MB_FLAGS=4,
                      FLAG_ORBIT=1, MB_ACCEPTED=28, MB_SNAPSHOT=0x100,
                      SLOT_PLAYER=12, SLOT_YAW=0x38, PLAYER_GLOBAL=0x53B868,
                      PC_PAWN=0x1EC, PLAYER_CONTROLLER=0x1EC)
PLAYER, CONTROLLER = 0x01928320, 0x01680BC0
ROTATOR = 0x01F000C8


class MovementMachine(BaseMachine):
    def native(self, target):
        assert target == d.NATIVE_AXES
        self.calls.append((target, tuple(self.regs), tuple(self.fpu),
                           tuple(self.b.read_u32(self.regs[m.A2] + i * 4) for i in range(3))))


@pytest.fixture
def movement(monkeypatch):
    monkeypatch.setattr(d, '_map', lambda: MAP)
    be = FakeBackend()
    for address, words in d.code_resources():
        for i, word in enumerate(words):
            be.seed_u32(address + i * 4, word)
    for address, value in (
        (MAP.MOD_BLOCK, MAP.MAGIC), (MAP.MOD_BLOCK + MAP.MB_FLAGS, MAP.FLAG_ORBIT),
        (MAP.PLAYER_GLOBAL, PLAYER+0x100), (MAP.MOD_BLOCK + MAP.MB_ACCEPTED, PLAYER),
        (PLAYER + MAP.PLAYER_CONTROLLER, CONTROLLER),
        (MAP.MOD_BLOCK + MAP.MB_SNAPSHOT + MAP.SLOT_PLAYER, PLAYER),
        (MAP.MOD_BLOCK + MAP.MB_SNAPSHOT + MAP.SLOT_YAW, 0xC123),
        (CONTROLLER + 0x1EC, PLAYER),
    ):
        be.seed_u32(address, value)
    for i, value in enumerate((0xFFFFF123, 0x1234, 0x55)):
        be.seed_u32(ROTATOR + i * 4, value)
    machine = MovementMachine(be)
    # All untouched GPRs have meaningful upper bits; this catches 64-bit saves
    # masquerading as R5900's required full 128-bit scratch preservation.
    for reg in range(1, 32):
        machine.regs[reg] = (1 << 120) | (reg << 64) | reg
    machine.regs[m.SP] = 0x01F00000
    machine.regs[m.S1] = CONTROLLER
    machine.regs[m.A2] = ROTATOR
    machine.regs[31] = d.HOOK + 8
    machine.fpu = [reg + .25 for reg in range(32)]
    return be, machine


def test_resource_pair_and_reserved_cave_size(monkeypatch):
    monkeypatch.setattr(d, '_map', lambda: MAP)
    assert d.STOCK_PAIR == (m.jal(0x192080), m.addiu(m.A2, m.SP, 0xC8))
    assert d.resources() == ((0x446314, d.STOCK_PAIR, (m.jal(0xF8000), d.STOCK_PAIR[1])),)
    assert d.CAVE + len(d.movement_words()) * 4 < 0xFF000


def test_active_uses_accepted_snapshot_yaw_only_and_preserves_abi(movement):
    be, machine = movement
    before_regs, before_fpu = tuple(machine.regs), tuple(machine.fpu)
    machine.run(d.CAVE)
    assert len(machine.calls) == 1
    target, regs, fpu, rotator = machine.calls[0]
    assert rotator == (0xFFFFF123, 0xC123, 0x55)
    assert regs == before_regs
    assert fpu == before_fpu
    assert be.read_u32(MAP.MOD_BLOCK + MAP.MB_SNAPSHOT + MAP.SLOT_YAW) == 0xC123
    # No native camera/actor/controller cache writes; just the local yaw.
    assert be.writes == [(ROTATOR + 4, struct.pack('<I', 0xC123))]


@pytest.mark.parametrize('address,value', [
    (MAP.MOD_BLOCK, 0), (MAP.MOD_BLOCK + MAP.MB_FLAGS, 0),
    (MAP.MOD_BLOCK + MAP.MB_FLAGS, 2), (PLAYER + MAP.PLAYER_CONTROLLER, 0),
    (PLAYER + MAP.PLAYER_CONTROLLER, CONTROLLER + 16), (CONTROLLER + MAP.PC_PAWN, PLAYER + 1),
    (MAP.MOD_BLOCK + MAP.MB_ACCEPTED, PLAYER + 16),
    (MAP.MOD_BLOCK + MAP.MB_SNAPSHOT + MAP.SLOT_PLAYER, PLAYER + 16),
    (CONTROLLER + 0x1EC, PLAYER + 16),
])
def test_invalid_ownership_runs_original_builder_without_mutation(movement, address, value):
    be, machine = movement
    be.seed_u32(address, value)
    before_regs = tuple(machine.regs)
    machine.run(d.CAVE)
    assert machine.calls[0][3] == (0xFFFFF123, 0x1234, 0x55)
    assert machine.calls[0][1] == before_regs
    assert be.writes == []


@pytest.mark.parametrize('yaw', [0, 0x4000, 0x8000, 0xFFFF])
def test_all_native_turn_quadrants_pass_without_float_conversion(movement, yaw):
    be, machine = movement
    be.seed_u32(MAP.MOD_BLOCK + MAP.MB_SNAPSHOT + MAP.SLOT_YAW, yaw)
    machine.run(d.CAVE)
    assert machine.calls[0][3][1] == yaw
