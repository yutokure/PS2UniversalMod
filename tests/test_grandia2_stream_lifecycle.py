"""Additional seven-site frame-boundary ownership regressions (synthetic only)."""
import pytest

from adapters.grandia2 import caves, memory_map as mm
from tests.test_grandia2 import CaveMachine, FakeBackend, seed_field


def test_cancelled_first_bootstrap_can_detach_without_finish_hook_or_orbit_queue():
    b = seed_field(FakeBackend())
    b.auto_guest = False
    caves.prepare(b)
    b.seed_u32(mm.RENDER_HOOK, caves.RENDER_PAIR[0])
    b.seed_u32(mm.MOD_BLOCK + mm.MB_FLAGS, 0)
    b.seed_u32(mm.MOD_BLOCK + mm.MB_ACK, 0)
    b.seed_u32(mm.MOD_BLOCK + mm.MB_COMMAND, mm.CMD_SYNC)
    machine = CaveMachine(b)
    machine.render()
    assert all(caves.read_words(b, a, 2) == stock for a, stock, hook in caves.SITES)
    assert b.read_u32(mm.MOD_BLOCK + mm.MB_COMMAND) == mm.CMD_ACK
    assert machine.calls[0][0] == 'native'
    assert not any(call[0] == 'nj' for call in machine.calls)


@pytest.mark.parametrize('operation', [caves.prepare, lambda b: caves.synchronize(b, 0)])
def test_old_three_site_control_version_is_not_adopted_or_overwritten(operation):
    b = seed_field(FakeBackend())
    b.seed_u32(mm.MOD_BLOCK, 0x47324331)
    b.writes.clear()
    with pytest.raises(caves.PatchConflict):
        operation(b)
    assert not b.writes
