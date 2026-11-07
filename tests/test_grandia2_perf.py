"""Grandia II bounded-read publication checks; synthetic memory, never PCSX2.

Hot checks deliberately inspect hook/control ownership, not every cave word.
Cave-body conflicts are checked on initial preparation, state/reconnect loss,
periodic set_patch audits and release. Read counts below exclude guest callbacks
so they model host backend round trips rather than the synthetic interpreter.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from adapters.grandia2 import Grandia2Adapter, caves, memory_map as mm
from core.camera_math.orbit import Vec3
from core.memory_backend.guard import CHANGED, GuardedBackend, WriteBlocked
from tests.test_grandia2 import FakeBackend, PLAYER, active_bank, seed_field


def warm_backend():
    backend = seed_field(FakeBackend())
    adapter = Grandia2Adapter(backend)
    adapter.set_patch(True)
    backend.auto_guest = False
    backend.reads.clear()
    backend.writes.clear()
    backend.host_writes.clear()
    return backend, adapter


def publish(adapter, yaw=55):
    adapter.write_orbit_params(PLAYER, yaw, -30, 2400,
                               target_offset=Vec3(0, 180, 0))


def cave_body_reads(backend):
    return [(address, size) for address, size in backend.reads
            if any(start <= address < start + 4 * len(words)
                   for start, words in caves.RESOURCES)]


def test_hot_pose_and_fov_have_constant_small_read_budgets_without_cave_scans():
    backend, adapter = warm_backend()
    counts = []
    for yaw in (55, 56, 57):
        backend.reads.clear()
        backend.writes.clear()
        publish(adapter, yaw)
        counts.append(len(backend.reads))
        assert 0 < counts[-1] < 100
        assert len(backend.writes) == 19
        assert not cave_body_reads(backend)
        assert backend.read_u32(active_bank(backend) + mm.SLOT_SEQUENCE) % 2 == 0
    assert len(set(counts)) == 1
    for operation in (lambda: adapter.write_fov_deg(45), adapter.restore_fov):
        backend.reads.clear()
        operation()
        assert 0 < len(backend.reads) < 100
        assert not cave_body_reads(backend)


def test_periodic_enable_audits_every_cave_once_and_republishes():
    backend, adapter = warm_backend()
    with patch.object(caves, 'preflight', wraps=caves.preflight) as audit:
        adapter.set_patch(True)
    assert audit.call_count == 1
    assert len(backend.reads) > 1000
    body_reads = cave_body_reads(backend)
    assert len(body_reads) == sum(len(words) for _, words in caves.RESOURCES)
    assert len(backend.writes) == 19


def test_steady_lifecycle_sync_uses_only_exact_sites_magic_flags_and_ack():
    backend, _adapter = warm_backend()
    with patch.object(caves, 'preflight', wraps=caves.preflight) as audit:
        caves.synchronize(backend, mm.FLAG_ORBIT)
    assert audit.call_count == 0
    assert 0 < len(backend.reads) < 20
    assert not cave_body_reads(backend)
    assert not backend.writes


@pytest.mark.parametrize('address', [
    *(site + off for site, _stock, _hook in caves.SITES for off in (0, 4)),
    mm.MOD_BLOCK,
])
def test_hot_unknown_hook_or_magic_rejects_before_first_bank_write(address):
    backend, adapter = warm_backend()
    backend.seed_u32(address, 0xDEADBEEF)
    with pytest.raises(caves.PatchConflict):
        publish(adapter)
    assert not backend.writes
    assert not cave_body_reads(backend)


def test_cave_only_change_is_detected_by_periodic_audit_then_cache_is_invalidated():
    backend, adapter = warm_backend()
    address, words = caves.RESOURCES[-1]
    backend.seed_u32(address + (len(words) - 1) * 4, 0xDEADBEEF)
    # This is the explicit hot-path tradeoff: site ownership remains intact,
    # so only the periodic body audit detects this kind of external change.
    publish(adapter)
    assert len(backend.reads) < 100
    assert not cave_body_reads(backend)
    backend.reads.clear()
    backend.writes.clear()
    with pytest.raises(caves.PatchConflict):
        adapter.set_patch(True)
    assert not backend.writes
    assert cave_body_reads(backend)
    backend.reads.clear()
    with pytest.raises(caves.PatchConflict):
        publish(adapter)
    assert not backend.writes  # failed audit cannot authorize later hot writes
    assert cave_body_reads(backend)


@pytest.mark.parametrize('operation', ['enable', 'pose', 'fov', 'restore'])
def test_fresh_adapter_does_not_inherit_another_adapters_prepared_authorization(operation):
    backend, _previous = warm_backend()
    backend.seed_u32(mm.TAIL_CAVE + 4, 0xDEADBEEF)
    fresh = Grandia2Adapter(backend)
    with pytest.raises(caves.PatchConflict):
        if operation == 'enable': fresh.set_patch(True)
        elif operation == 'pose': publish(fresh)
        elif operation == 'fov': fresh.write_fov_deg(45)
        else: fresh.restore()
    assert not backend.writes
    assert cave_body_reads(backend)


def test_backend_replacement_and_guarded_epoch_change_require_full_preparation():
    backend, adapter = warm_backend()
    replacement, _other_adapter = warm_backend()
    replacement.seed_u32(mm.RENDER_CAVE, 0xDEADBEEF)
    adapter.backend = replacement
    with pytest.raises(caves.PatchConflict):
        publish(adapter)
    assert not replacement.writes
    assert cave_body_reads(replacement)
    # Use the same public guard object but a changed transport epoch. The
    # adapter must not look through GuardedBackend or keep its old audit lease.
    backend.epoch = 1
    guard = GuardedBackend(backend)
    guard.bind(mm.GAME_ID, mm.DISC_CRC)
    adapter = Grandia2Adapter(guard)
    adapter.set_patch(True)
    backend.seed_u32(mm.MOVE_CAVE, 0xDEADBEEF)
    backend.epoch = 2
    backend.reads.clear()
    backend.writes.clear()
    with pytest.raises(caves.PatchConflict):
        publish(adapter)
    assert not backend.writes
    assert cave_body_reads(backend)


def test_hot_stock_reload_rechecks_complete_ownership_then_recovers():
    backend, adapter = warm_backend()
    replacement = seed_field(FakeBackend())
    backend.mem, backend.cache = replacement.mem, replacement.cache
    backend.auto_guest = True
    with patch.object(caves, 'preflight', wraps=caves.preflight) as audit:
        publish(adapter, 75)
    assert audit.call_count >= 1
    assert cave_body_reads(backend)
    assert adapter.patch_active()
    backend.auto_guest = False
    backend.reads.clear()
    publish(adapter, 76)
    assert len(backend.reads) < 100
    assert not cave_body_reads(backend)


def test_release_audits_once_and_does_not_overwrite_unknown_cave():
    backend, adapter = warm_backend()
    backend.auto_guest = True
    with patch.object(caves, 'preflight', wraps=caves.preflight) as audit:
        adapter.restore()
    assert audit.call_count == 1
    assert caves.site_state(backend) == 'stock'
    assert cave_body_reads(backend)
    adapter.set_patch(True)
    backend.seed_u32(mm.TAIL_CAVE, 0xDEADBEEF)
    backend.writes.clear()
    with pytest.raises(caves.PatchConflict):
        adapter.restore()
    assert not backend.writes


def test_guard_revocation_still_blocks_hot_bank_writes():
    backend = seed_field(FakeBackend())
    guard = GuardedBackend(backend)
    guard.bind(mm.GAME_ID, mm.DISC_CRC)
    adapter = Grandia2Adapter(guard)
    adapter.set_patch(True)
    backend.serial = 'SLPS-00000'
    assert guard.verify() == CHANGED
    backend.writes.clear()
    with pytest.raises(WriteBlocked):
        publish(adapter)
    assert not backend.writes
