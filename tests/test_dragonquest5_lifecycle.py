"""Synthetic contracts for DQ5 guest-thread hook installation and removal.

The emitted R5900 render cave performs hook stores in the tiny runner. A
command-poll tick substitutes for an emulator scheduler; it is not a model of
PCSX2's JIT/cache invalidation or a live concurrency guarantee.
"""
from __future__ import annotations

import itertools

import pytest

from adapters.dragonquest5 import caves, memory_map as mm
from adapters.dragonquest5.adapter import DragonQuest5Adapter
from core import mips_asm as m
from tests.test_dragonquest5 import (
    BAD_GUARDS, PLAYER, CaveMachine, FakeBackend, active_bank, assert_stock, seed_field,
)

HOOKS = {address for address, _, _, _, _ in caves.RESOURCES}
DELAYS = {address + 4 for address in HOOKS}


class TracingBackend(FakeBackend):
    """Distinguish host requests from actual stores executed by the guest runner."""
    def __init__(self):
        super().__init__()
        self.origins = []

    def write_u32(self, address, value):
        self.origins.append(('guest' if self._in_guest_cleanup else 'host', address, value & 0xFFFFFFFF))
        super().write_u32(address, value)

    def clear_trace(self):
        self.writes.clear()
        self.origins.clear()


def active_backend():
    b = seed_field(TracingBackend())
    ad = DragonQuest5Adapter(b)
    ad.set_patch(True)
    ad.write_fov_deg(65)
    b.clear_trace()
    return b, ad


def pairs(b):
    return {address: caves.read_words(b, address, 2) for address in HOOKS}


def no_host_executable_writes(b):
    # Includes cave bytes, not only the four entry-point instructions.
    ranges = [(address, address + 8) for address in HOOKS]
    ranges += [(start, start + 4 * len(words)) for _, _, _, start, words in caves.RESOURCES]
    assert not any(origin == 'host' and any(start <= address < end for start, end in ranges)
                   for origin, address, _ in b.origins)


def guest_render(b, machine=None):
    previous = b._in_guest_cleanup
    b._in_guest_cleanup = True
    try:
        (machine or CaveMachine(b)).render()
    finally:
        b._in_guest_cleanup = previous


def command(b, value=mm.CMD_UNINSTALL):
    b.seed_u32(mm.MOD_BLOCK + mm.MB_COMMAND, value)


@pytest.fixture
def quick_timeout(monkeypatch):
    # Exercise timeout decisions without a real half-second wait or polling
    # any external process. Every call advances this invented monotonic clock.
    ticks = itertools.count()
    monkeypatch.setattr(caves.time, 'monotonic', lambda: next(ticks) * .3)
    monkeypatch.setattr(caves.time, 'sleep', lambda seconds: None)


def test_host_uninstall_requests_guest_ack_without_host_instruction_stores():
    b, _ = active_backend()
    native = {a: b.bytes_at(a, size) for a, size in
              ((mm.WORLD, 64), (mm.CAM_FOV, 4), (mm.CAM_YAW, 16),
               (mm.CAM_EYE, 16), (mm.CAM_TARGET, 16))}
    b.seed_u32(mm.MOD_BLOCK + mm.MB_APPLIED, mm.FLAG_ORBIT | mm.FLAG_FOV)
    b.seed_u32(mm.MOD_BLOCK + mm.MB_MOVE_SP, 0x01F00000)
    observed = []

    def before_guest(backend):
        observed.append((backend.read_u32(mm.MOD_BLOCK + mm.MB_FLAGS),
                         backend.read_u32(mm.MOD_BLOCK + mm.MB_COMMAND), pairs(backend)))

    b.before_guest_cleanup = before_guest
    caves.uninstall(b)
    assert b.guest_cleanup_count == 1
    assert observed[0][:2] == (0, mm.CMD_UNINSTALL)
    assert observed[0][2] == {a: hook for a, _, hook, _, _ in caves.RESOURCES}
    assert_stock(b)
    assert b.read_u32(mm.MOD_BLOCK + mm.MB_COMMAND) == mm.CMD_DONE
    assert b.read_u32(mm.MOD_BLOCK + mm.MB_APPLIED) == 0
    assert b.read_u32(mm.MOD_BLOCK + mm.MB_MOVE_SP) == 0
    assert b.read_u32(mm.MOD_BLOCK + mm.MB_PENDING) == 0
    no_host_executable_writes(b)
    assert not any(a in DELAYS for _, a, _ in b.origins)
    stores = [(a, value) for origin, a, value in b.origins if origin == 'guest' and a in HOOKS]
    assert set(a for a, _ in stores) == HOOKS
    assert stores[-1] == (mm.RENDER_HOOK, mm.RENDER_STOCK[0])
    ack = next(i for i, (_, a, value) in enumerate(b.origins)
               if a == mm.MOD_BLOCK + mm.MB_COMMAND and value == mm.CMD_DONE)
    assert max(i for i, (_, a, _) in enumerate(b.origins) if a in HOOKS) < ack
    assert all(b.bytes_at(a, len(data)) == data for a, data in native.items())


@pytest.mark.parametrize('owned_magic', [False, True])
def test_already_stock_uninstall_needs_no_guest_command_or_executable_write(owned_magic):
    b = seed_field(TracingBackend())
    if owned_magic:
        b.seed_u32(mm.MOD_BLOCK, mm.MAGIC)
        b.seed_u32(mm.MOD_BLOCK + mm.MB_APPLIED, mm.FLAG_ORBIT)
    b.clear_trace()
    caves.uninstall(b)
    assert_stock(b)
    assert b.guest_cleanup_count == 0
    no_host_executable_writes(b)
    assert not any(a == mm.MOD_BLOCK + mm.MB_COMMAND and value == mm.CMD_UNINSTALL
                   for _, a, value in b.origins)
    if owned_magic:
        assert b.read_u32(mm.MOD_BLOCK + mm.MB_APPLIED) == 0


@pytest.mark.parametrize('stock_subset', list(itertools.product([False, True], repeat=3)))
def test_guest_accepts_mixed_stock_and_applied_pairs_but_render_is_removed_last(stock_subset):
    b, _ = active_backend()
    others = [r for r in caves.RESOURCES if r[0] != mm.RENDER_HOOK]
    for make_stock, (address, stock, _, _, _) in zip(stock_subset, others):
        if make_stock:
            b.seed_u32(address, stock[0])
    caves.uninstall(b)
    assert_stock(b)
    no_host_executable_writes(b)
    stores = [(a, value) for origin, a, value in b.origins if origin == 'guest' and a in HOOKS]
    assert stores[-1] == (mm.RENDER_HOOK, mm.RENDER_STOCK[0])
    assert b.read_u32(mm.MOD_BLOCK + mm.MB_COMMAND) == mm.CMD_DONE


@pytest.mark.parametrize('site', range(4))
@pytest.mark.parametrize('delay', [False, True])
def test_guest_revalidates_every_pair_after_host_preflight_without_partial_restore(site, delay):
    b, _ = active_backend()
    address, _, _, _, _ = caves.RESOURCES[site]
    damaged = address + (4 if delay else 0)
    expected = {}

    def mutate_after_request(backend):
        backend.seed_u32(damaged, 0xDEADBEEF)
        expected.update(pairs(backend))

    b.before_guest_cleanup = mutate_after_request
    with pytest.raises(caves.PatchConflict, match='conflict|changed|unknown'):
        caves.uninstall(b)
    assert pairs(b) == expected
    assert b.read_u32(mm.MOD_BLOCK + mm.MB_COMMAND) == mm.CMD_CONFLICT
    no_host_executable_writes(b)
    assert not any(a in HOOKS | DELAYS for _, a, _ in b.origins)


@pytest.mark.parametrize('address,value', BAD_GUARDS)
def test_cleanup_is_available_after_scene_guards_fail(address, value):
    b, _ = active_backend()
    b.seed_u32(address, value)
    caves.uninstall(b)
    assert_stock(b)
    assert b.read_u32(mm.MOD_BLOCK + mm.MB_COMMAND) == mm.CMD_DONE
    no_host_executable_writes(b)


@pytest.mark.parametrize('pending', [0, mm.FLAG_ORBIT | mm.FLAG_FOV])
def test_no_guest_progress_times_out_with_cleanup_hook_attached(pending, quick_timeout):
    b, _ = active_backend()
    b.auto_guest_cleanup = False
    b.seed_u32(mm.MOD_BLOCK + mm.MB_PENDING, pending)
    expected = pairs(b)
    with pytest.raises(caves.PatchConflict, match='paused|unavailable|resume|timed'):
        caves.uninstall(b)
    assert pairs(b) == expected
    assert b.read_u32(mm.MOD_BLOCK + mm.MB_FLAGS) == 0
    assert b.read_u32(mm.MOD_BLOCK + mm.MB_COMMAND) == mm.CMD_UNINSTALL
    assert b.read_u32(mm.MOD_BLOCK + mm.MB_PENDING) == pending
    no_host_executable_writes(b)


def test_request_left_pending_is_completed_when_guest_resumes(quick_timeout):
    b, _ = active_backend()
    b.auto_guest_cleanup = False
    with pytest.raises(caves.PatchConflict):
        caves.uninstall(b)
    guest_render(b)
    assert_stock(b)
    assert b.read_u32(mm.MOD_BLOCK + mm.MB_COMMAND) == mm.CMD_DONE
    no_host_executable_writes(b)


def test_missing_render_cleanup_hook_refuses_without_host_fallback_instruction_writes():
    b, _ = active_backend()
    b.seed_u32(mm.RENDER_HOOK, mm.RENDER_STOCK[0])
    expected = pairs(b)
    with pytest.raises(caves.PatchConflict, match='cleanup|render'):
        caves.uninstall(b)
    assert pairs(b) == expected
    assert b.guest_cleanup_count == 0
    no_host_executable_writes(b)


@pytest.mark.parametrize('command_value', [0, mm.CMD_DONE, mm.CMD_CONFLICT, mm.CMD_INSTALLED, 0xDEADBEEF])
def test_render_does_not_remove_hooks_without_current_uninstall_request(command_value):
    b, _ = active_backend()
    b.auto_guest_cleanup = False
    command(b, command_value)
    before = pairs(b)
    guest_render(b)
    assert pairs(b) == before
    assert b.read_u32(mm.MOD_BLOCK + mm.MB_COMMAND) == command_value
    assert not any(a in HOOKS | DELAYS for _, a, _ in b.origins)


@pytest.mark.parametrize('magic', [0, 0xDEADBEEF])
def test_render_cleanup_does_not_write_unknown_control_block_or_hook_ownership(magic):
    b, _ = active_backend()
    b.auto_guest_cleanup = False
    command(b)
    b.seed_u32(mm.MOD_BLOCK, magic)
    before = b.bytes_at(mm.MOD_BLOCK, mm.BLOCK_SIZE)
    before_hooks = pairs(b)
    guest_render(b)
    assert pairs(b) == before_hooks
    assert b.bytes_at(mm.MOD_BLOCK, mm.BLOCK_SIZE) == before
    assert not any(a in HOOKS | DELAYS for _, a, _ in b.origins)


def test_request_during_active_transaction_restores_world_and_lens_before_hook_removal():
    b, _ = active_backend()
    b.auto_guest_cleanup = False
    native_world = b.bytes_at(mm.WORLD, 64)
    native_lens = b.bytes_at(mm.CAM_FOV, 4)
    observed = []
    machine = CaveMachine(b)

    def request_during_native(runner):
        assert b.read_u32(mm.MOD_BLOCK + mm.MB_PENDING)
        assert b.bytes_at(mm.WORLD, 64) != native_world
        assert b.bytes_at(mm.CAM_FOV, 4) != native_lens
        command(b)
        b.seed_u32(mm.MOD_BLOCK + mm.MB_FLAGS, 0)

    def check_hook_store(address, data):
        if address in HOOKS:
            observed.append((address, b.bytes_at(mm.WORLD, 64), b.bytes_at(mm.CAM_FOV, 4),
                             b.read_u32(mm.MOD_BLOCK + mm.MB_PENDING)))

    machine.on_render = request_during_native
    b.on_write = check_hook_store
    guest_render(b, machine)
    assert_stock(b)
    assert observed and observed[-1][0] == mm.RENDER_HOOK
    assert all(world == native_world and lens == native_lens and pending == 0
               for _, world, lens, pending in observed)
    assert b.read_u32(mm.MOD_BLOCK + mm.MB_COMMAND) == mm.CMD_DONE


def test_nested_render_with_existing_transaction_does_not_detach_outer_cleanup():
    b, _ = active_backend()
    b.auto_guest_cleanup = False
    native_world = b.bytes_at(mm.WORLD, 64)
    outer = CaveMachine(b)
    nested_states = []

    def nested_native(runner):
        command(b)
        nested = CaveMachine(b)
        nested.regs[m.SP] = runner.regs[m.SP]
        guest_render(b, nested)
        nested_states.append((pairs(b), b.read_u32(mm.MOD_BLOCK + mm.MB_PENDING),
                              b.read_u32(mm.MOD_BLOCK + mm.MB_COMMAND)))

    outer.on_render = nested_native
    guest_render(b, outer)
    assert nested_states[0][0] == {a: hook for a, _, hook, _, _ in caves.RESOURCES}
    assert nested_states[0][1] != 0
    assert nested_states[0][2] == mm.CMD_UNINSTALL
    assert_stock(b)
    assert b.bytes_at(mm.WORLD, 64) == native_world
    assert b.read_u32(mm.MOD_BLOCK + mm.MB_COMMAND) == mm.CMD_DONE


def test_guest_cleanup_preserves_native_return_values_and_callee_saved_state():
    b, _ = active_backend()
    b.auto_guest_cleanup = False
    command(b)
    returns = {m.V0: (1 << 100) | 0x12345678, m.V1: (1 << 110) | 0x87654321}

    class ReturningMachine(CaveMachine):
        def native(self, target):
            super().native(target)
            for reg, value in returns.items():
                self.regs[reg] = value

    machine = ReturningMachine(b)
    for reg in (28, *range(16, 24)):
        machine.regs[reg] = (1 << 100) | (0xABC00000 + reg)
    saved = {reg: machine.regs[reg] for reg in (m.SP, 31, 28, *range(16, 24))}
    guest_render(b, machine)
    assert {reg: machine.regs[reg] for reg in returns} == returns
    assert {reg: machine.regs[reg] for reg in saved} == saved
    assert_stock(b)


def test_host_does_not_trust_done_ack_without_stock_hook_readback(quick_timeout):
    b, _ = active_backend()
    b.auto_guest_cleanup = False

    def forged_ack(address, data):
        if address == mm.MOD_BLOCK + mm.MB_COMMAND and int.from_bytes(data, 'little') == mm.CMD_UNINSTALL:
            b.seed_u32(address, mm.CMD_DONE)

    b.on_write = forged_ack
    with pytest.raises(caves.PatchConflict):
        caves.uninstall(b)
    assert caves.site_state(b) == 'applied'
    no_host_executable_writes(b)


def test_pending_cleanup_blocks_reenable_until_guest_services_request(quick_timeout):
    b, ad = active_backend()
    b.auto_guest_cleanup = False
    with pytest.raises(caves.PatchConflict):
        caves.uninstall(b)
    b.clear_trace()
    expected = pairs(b)
    with pytest.raises(caves.PatchConflict, match='pending|cleanup|uninstall'):
        ad.set_patch(True)
    assert pairs(b) == expected
    assert not b.writes
    guest_render(b)
    assert_stock(b)
    b.auto_guest_cleanup = True
    ad.set_patch(True)
    assert caves.site_state(b) == 'applied'
    assert b.read_u32(mm.MOD_BLOCK + mm.MB_FLAGS) == mm.FLAG_ORBIT | mm.FLAG_FOV


def test_stale_done_ack_is_replaced_by_fresh_uninstall_request():
    b, _ = active_backend()
    command(b, mm.CMD_DONE)
    caves.uninstall(b)
    assert b.guest_cleanup_count == 1
    assert_stock(b)
    requests = [value for origin, a, value in b.origins
                if origin == 'host' and a == mm.MOD_BLOCK + mm.MB_COMMAND]
    assert mm.CMD_UNINSTALL in requests


# Installation uses only the host render JAL as a bootstrap. The remaining
# native entrypoint stores execute on the EE thread, after native rendering.
def prepared_backend():
    b = seed_field(TracingBackend())
    caves.prepare(b)
    b.seed_u32(mm.MOD_BLOCK + mm.MB_FLAGS, mm.FLAG_ORBIT | mm.FLAG_FOV)
    b.clear_trace()
    return b


def assert_applied(b):
    assert pairs(b) == {a: hook for a, _, hook, _, _ in caves.RESOURCES}


def assert_host_bootstrap_only(b):
    host_code = [(a, value) for origin, a, value in b.origins if origin == 'host' and a in HOOKS | DELAYS]
    assert host_code == [(mm.RENDER_HOOK, m.jal(mm.RENDER_CAVE))]
    assert not any(a in DELAYS for _, a, _ in b.origins)


def test_install_host_bootstraps_render_only_and_guest_installs_other_three_before_ack():
    b = prepared_backend()
    observed = []

    def before_guest(backend):
        observed.append((backend.read_u32(mm.MOD_BLOCK + mm.MB_COMMAND), pairs(backend)))

    b.before_guest_cleanup = before_guest
    caves.install(b)
    assert b.guest_install_count == 1
    assert observed == [(mm.CMD_INSTALL, {a: hook if a == mm.RENDER_HOOK else stock
                                        for a, stock, hook, _, _ in caves.RESOURCES})]
    assert_applied(b)
    assert b.read_u32(mm.MOD_BLOCK + mm.MB_COMMAND) == mm.CMD_INSTALLED
    assert_host_bootstrap_only(b)
    stores = [(a, value) for origin, a, value in b.origins if origin == 'guest' and a in HOOKS]
    assert dict(stores) == {a: hook[0] for a, _, hook, _, _ in caves.RESOURCES if a != mm.RENDER_HOOK}
    request = next(i for i, (_, a, value) in enumerate(b.origins)
                   if a == mm.MOD_BLOCK + mm.MB_COMMAND and value == mm.CMD_INSTALL)
    bootstrap = next(i for i, (origin, a, _) in enumerate(b.origins) if origin == 'host' and a == mm.RENDER_HOOK)
    ack = next(i for i, (_, a, value) in enumerate(b.origins)
               if a == mm.MOD_BLOCK + mm.MB_COMMAND and value == mm.CMD_INSTALLED)
    assert request < bootstrap < ack
    assert max(i for i, (origin, a, _) in enumerate(b.origins) if origin == 'guest' and a in HOOKS) < ack


def test_install_is_idempotent_when_all_four_hooks_are_applied():
    b = prepared_backend()
    caves.install(b)
    b.clear_trace()
    initial_ticks = b.guest_install_count
    caves.install(b)
    assert not b.writes
    assert b.guest_install_count == initial_ticks
    assert_applied(b)


@pytest.mark.parametrize('already_applied', list(itertools.product([False, True], repeat=3))[:-1])
def test_install_guest_accepts_mixed_native_and_owned_hooks(already_applied):
    b = prepared_backend()
    for applied, (address, _, hook, _, _) in zip(already_applied, caves.RESOURCES[1:]):
        if applied:
            b.seed_u32(address, hook[0])
    caves.install(b)
    assert_applied(b)
    assert_host_bootstrap_only(b)
    stores = {a for origin, a, _ in b.origins if origin == 'guest' and a in HOOKS}
    assert stores == {r[0] for applied, r in zip(already_applied, caves.RESOURCES[1:]) if not applied}


@pytest.mark.parametrize('site', range(4))
@pytest.mark.parametrize('delay', [False, True])
def test_install_guest_rechecks_all_pairs_after_host_preflight_without_partial_code_stores(site, delay):
    b = prepared_backend()
    address, _, _, _, _ = caves.RESOURCES[site]
    expected = {}

    def corrupt_after_bootstrap(backend):
        backend.seed_u32(address + (4 if delay else 0), 0xDEADBEEF)
        expected.update(pairs(backend))

    b.before_guest_cleanup = corrupt_after_bootstrap
    with pytest.raises(caves.PatchConflict, match='conflict|changed|unknown'):
        caves.install(b)
    assert pairs(b) == expected
    assert b.read_u32(mm.MOD_BLOCK + mm.MB_COMMAND) == mm.CMD_CONFLICT
    assert not any(origin == 'guest' and a in HOOKS | DELAYS for origin, a, _ in b.origins)
    assert_host_bootstrap_only(b)


def test_pending_install_render_calls_native_before_install_without_applying_orbit_transaction():
    b = prepared_backend()
    b.auto_guest_cleanup = False
    b.seed_u32(mm.RENDER_HOOK, m.jal(mm.RENDER_CAVE))
    command(b, mm.CMD_INSTALL)
    native_world, native_lens = b.bytes_at(mm.WORLD, 64), b.bytes_at(mm.CAM_FOV, 4)
    seen = []
    machine = CaveMachine(b)
    machine.on_render = lambda runner: seen.append((b.bytes_at(mm.WORLD, 64), b.bytes_at(mm.CAM_FOV, 4),
                                                   b.read_u32(mm.MOD_BLOCK + mm.MB_PENDING), pairs(b)))
    guest_render(b, machine)
    assert seen[0][:3] == (native_world, native_lens, 0)
    assert seen[0][3] == {a: hook if a == mm.RENDER_HOOK else stock
                           for a, stock, hook, _, _ in caves.RESOURCES}
    assert b.bytes_at(mm.WORLD, 64) == native_world
    assert b.bytes_at(mm.CAM_FOV, 4) == native_lens
    assert_applied(b)
    assert b.read_u32(mm.MOD_BLOCK + mm.MB_COMMAND) == mm.CMD_INSTALLED


def test_install_timeout_leaves_only_bootstrap_and_disables_flags_until_retry(quick_timeout):
    b = prepared_backend()
    b.auto_guest_cleanup = False
    with pytest.raises(caves.PatchConflict, match='paused|unavailable|resume|timed'):
        caves.install(b)
    assert_host_bootstrap_only(b)
    assert pairs(b) == {a: hook if a == mm.RENDER_HOOK else stock for a, stock, hook, _, _ in caves.RESOURCES}
    assert b.read_u32(mm.MOD_BLOCK + mm.MB_FLAGS) == 0
    assert b.read_u32(mm.MOD_BLOCK + mm.MB_COMMAND) == mm.CMD_INSTALL
    guest_render(b)
    assert_applied(b)
    assert b.read_u32(mm.MOD_BLOCK + mm.MB_FLAGS) == 0
    assert b.read_u32(mm.MOD_BLOCK + mm.MB_COMMAND) == mm.CMD_INSTALLED
    b.clear_trace()
    b.auto_guest_cleanup = True
    DragonQuest5Adapter(b).set_patch(True)
    assert_applied(b)
    assert b.read_u32(mm.MOD_BLOCK + mm.MB_FLAGS) == mm.FLAG_ORBIT
    assert not any(a in HOOKS | DELAYS for _, a, _ in b.origins)


def test_pending_install_can_be_retried_with_same_owned_bootstrap(quick_timeout):
    b = prepared_backend()
    b.auto_guest_cleanup = False
    with pytest.raises(caves.PatchConflict):
        caves.install(b)
    b.clear_trace()
    b.auto_guest_cleanup = True
    caves.prepare(b)
    caves.install(b)
    assert_applied(b)
    assert b.read_u32(mm.MOD_BLOCK + mm.MB_COMMAND) == mm.CMD_INSTALLED
    assert not any(origin == 'host' and a in HOOKS | DELAYS for origin, a, _ in b.origins)


def test_install_rejects_forged_ack_without_full_hook_readback(quick_timeout):
    b = prepared_backend()
    b.auto_guest_cleanup = False

    def forged_install_ack(address, data):
        if address == mm.RENDER_HOOK:
            b.seed_u32(mm.MOD_BLOCK + mm.MB_COMMAND, mm.CMD_INSTALLED)

    b.on_write = forged_install_ack
    with pytest.raises(caves.PatchConflict):
        caves.install(b)
    assert pairs(b) != {a: hook for a, _, hook, _, _ in caves.RESOURCES}
    assert_host_bootstrap_only(b)


def test_real_publication_enables_flags_only_after_native_bootstrap_and_all_guest_hooks_ack():
    b = seed_field(TracingBackend())
    ad = DragonQuest5Adapter(b)
    native_world, native_lens = b.bytes_at(mm.WORLD, 64), b.bytes_at(mm.CAM_FOV, 4)
    b.clear_trace()
    native_calls = []
    original_tick = b.before_guest_cleanup

    def inspect_bootstrap(backend):
        assert backend.read_u32(mm.MOD_BLOCK + mm.MB_COMMAND) == mm.CMD_INSTALL
        assert backend.read_u32(active_bank(backend) + mm.SLOT_FLAGS) == mm.FLAG_ORBIT
        assert backend.read_u32(mm.MOD_BLOCK + mm.MB_FLAGS) == 0
        machine = CaveMachine(backend)
        machine.on_render = lambda runner: native_calls.append((backend.bytes_at(mm.WORLD, 64),
                                                                backend.bytes_at(mm.CAM_FOV, 4),
                                                                backend.read_u32(mm.MOD_BLOCK + mm.MB_PENDING)))
        guest_render(backend, machine)
        if original_tick is not None:
            original_tick(backend)

    b.before_guest_cleanup = inspect_bootstrap
    ad.write_orbit_params(PLAYER, 90, -40, 180)
    assert native_calls == [(native_world, native_lens, 0)]
    assert_applied(b)
    assert b.read_u32(mm.MOD_BLOCK + mm.MB_FLAGS) == mm.FLAG_ORBIT
    ack = next(i for i, (_, a, value) in enumerate(b.origins)
               if a == mm.MOD_BLOCK + mm.MB_COMMAND and value == mm.CMD_INSTALLED)
    flags_on = [i for i, (_, a, value) in enumerate(b.origins)
                if a == mm.MOD_BLOCK + mm.MB_FLAGS and value]
    assert flags_on and min(flags_on) > ack
    assert_host_bootstrap_only(b)


@pytest.mark.parametrize('command_value', [mm.CMD_UNINSTALL, mm.CMD_CONFLICT])
def test_install_does_not_shortcut_pending_or_conflict_even_if_hooks_applied(command_value):
    b, _ = active_backend()
    b.auto_guest_cleanup = False
    command(b, command_value)
    b.clear_trace()
    with pytest.raises(caves.PatchConflict, match='pending|conflict|restore'):
        caves.install(b)
    assert not b.writes
    assert_applied(b)


@pytest.mark.parametrize('address,value', BAD_GUARDS)
def test_guest_install_lifecycle_is_independent_of_current_scene_guards(address, value):
    b = prepared_backend()
    b.seed_u32(address, value)
    caves.install(b)
    assert_applied(b)
    assert b.read_u32(mm.MOD_BLOCK + mm.MB_COMMAND) == mm.CMD_INSTALLED
    assert_host_bootstrap_only(b)
