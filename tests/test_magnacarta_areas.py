"""Area-independent pawn ownership, guest render and exact legacy migration.

Synthetic native-builder stubs are not visual/PCSX2 verification. Optional private
ZIP checks read user states only and never save or extract game data into Git.
"""
from pathlib import Path
import struct
import zipfile
import hashlib

import pytest

from adapters.magnacarta import caves, memory_map as mm
from adapters.magnacarta.adapter import MagnaCartaAdapter
from core import mips_asm as m
from core.camera_math.orbit import Vec3
from tests.test_magnacarta import (seed_field, FakeBackend, ACTOR, OWNER, STATE,
                                  MAGI, SCRIPT_FRAME, SCRIPT_STATE)
from tests.test_radiata import CaveMachine

OLD_BUCKET = 0x56DB1C  # deliberately NOT a supported runtime root


class RenderMachine(CaveMachine):
    def execute(self, word):
        if word >> 26 == 0x24:  # lbu, absent from the shared interpreter
            rs, rt = word >> 21 & 31, word >> 16 & 31
            off = word & 65535
            off = off - 65536 if off & 32768 else off
            self.put(rt, self.b.bytes_at((self.regs[rs] + off) & 0xFFFFFFFF, 1)[0])
        else:
            super().execute(word)

    def native(self, target):
        assert target == mm.RENDER_NATIVE
        self.calls.append((self.regs.copy(), self.fpu.copy(),
                           self.b.read_floats(self.regs[m.A3], 3),
                           tuple(self.b.read_u32(self.regs[m.T0] + 4*i) for i in range(3))))


def render(b, *, actor=ACTOR):
    machine = RenderMachine(b)
    for r in range(1, 32):
        machine.regs[r] = (r << 120) | (r << 64) | r
    machine.regs[m.SP] = 0x1F00000
    machine.regs[m.A2] = actor
    machine.regs[m.A3] = 0x1E10000
    machine.regs[m.T0] = 0x1E20000
    machine.fpu = [f + .25 for f in range(32)]
    machine.fpu[12] = 55.0
    b.seed_floats(machine.regs[m.A3], (10, 20, 30))
    for i, value in enumerate((1, 2, 3)):
        b.seed_u32(machine.regs[m.T0] + 4*i, value)
    before_regs, before_fpu = machine.regs.copy(), machine.fpu.copy()
    machine.run(mm.RENDER_CAVE)
    # T0 is deliberately the native builder's copied rotator argument (caller
    # saved), not a wrapper-preserved return value. All other stub outputs stay.
    assert [v for r,v in enumerate(machine.regs) if r!=m.T0] == [v for r,v in enumerate(before_regs) if r!=m.T0]
    assert machine.fpu == before_fpu
    return machine.calls[0]


def test_area_reload_follows_new_pawn_owned_magi_not_hash_bucket():
    b = seed_field(); a = MagnaCartaAdapter(b)
    a.set_patch(True)
    actor, magi, owner, state, frame = 0x1901000, 0x1601000, 0x1801000, 0x1701000, 0x1501000
    for address, value in ((mm.PLAYER_GLOBAL, actor), (actor + mm.PLAYER_MAGI, magi),
                           (mm.FIELD_OWNER_GLOBAL, owner), (magi + mm.MAGI_OWNER, owner),
                           (owner + mm.OWNER_MAGI, magi), (owner + mm.STATE_POINTER, state),
                           (state + 0x90, 1 << 8), (magi + 12, frame),
                           (frame + 0x18, SCRIPT_STATE), (SCRIPT_STATE + 0x20, 0x31D3),
                           (OLD_BUCKET, 0x990000)):
        b.seed_u32(address, value)
    b.seed_floats(actor + mm.PLAYER_POSITION, (500, 600, 70))
    b.seed_u32(0x990000 + 12, 0)  # unrelated FinalBlend/primitive, as in user states
    assert a.read_player() == Vec3(500, -70, 600)
    a.write_orbit_params(a.read_player(), 45, 20, 1500, target_offset=Vec3(0, -100, 0))
    assert b.read_u32(mm.MOD_BLOCK + mm.SLOTS[b.read_u32(mm.MOD_BLOCK+mm.MB_SLOT)] + mm.SLOT_PLAYER) == actor
    call = render(b, actor=actor)
    assert call[0][m.A3] != 0x1E10000
    assert b.read_u32(mm.MOD_BLOCK + mm.MB_ACCEPTED) == actor
    assert not any(addr == OLD_BUCKET for addr, _ in b.reads)


@pytest.mark.parametrize('address,value', [
    (ACTOR + mm.PLAYER_MAGI, 0), (ACTOR + mm.PLAYER_MAGI, MAGI+1),
    (ACTOR + mm.PLAYER_MAGI, 0x1FFF000), (MAGI + mm.MAGI_OWNER, 0),
    (MAGI + mm.MAGI_OWNER, OWNER+1), (MAGI + mm.MAGI_OWNER, 0x1FFF000),
    (OWNER + mm.OWNER_MAGI, MAGI+16), (mm.FIELD_OWNER_GLOBAL, OWNER+16),
    (OWNER + mm.STATE_POINTER, STATE+1), (STATE+0x90, 3 << 8),
    (MAGI + 12, 0), (SCRIPT_FRAME+0x18, 0), (SCRIPT_STATE+0x20, 0x131D3),
    (SCRIPT_STATE+0x20, 0x1234),
])
def test_host_and_guest_reject_broken_area_ownership(address, value):
    b = seed_field(); a = MagnaCartaAdapter(b)
    a.set_patch(True)
    b.seed_u32(mm.MOD_BLOCK+mm.MB_ACCEPTED, ACTOR)
    b.seed_u32(address, value)
    before = b.writes.copy()
    assert not a.read_scene().valid
    with pytest.raises(caves.PatchConflict): a.set_patch(True)
    assert b.writes == before
    call = render(b)
    assert call[2:] == ([10, 20, 30], (1, 2, 3))
    assert b.read_u32(mm.MOD_BLOCK+mm.MB_ACCEPTED) == 0
    assert a.heartbeat_word() == 0


@pytest.mark.parametrize('mode,name', [(1,0x31D3), (2,0x31CC)])
def test_guest_render_uses_owned_live_pawn_and_preserves_abi(mode, name):
    b = seed_field(); a = MagnaCartaAdapter(b)
    b.seed_u32(STATE+0x90, mode << 8); b.seed_u32(SCRIPT_STATE+0x20, name)
    a.write_orbit_params(a.read_player(), 90, 25, 1600, target_offset=Vec3(0,-100,0))
    a.write_fov_deg(80)
    call = render(b)
    assert call[1][12] == 80
    assert call[2] == pytest.approx(b.read_floats(mm.MOD_BLOCK+mm.MB_RENDER_EYE,3))
    assert b.read_u32(mm.MOD_BLOCK+mm.MB_ACCEPTED) == ACTOR
    assert a.heartbeat_word() == 1
    # A different script viewactor must revoke acceptance, even with a valid pawn.
    call = render(b, actor=ACTOR+16)
    assert call[2:] == ([10,20,30], (1,2,3))
    assert b.read_u32(mm.MOD_BLOCK+mm.MB_ACCEPTED) == 0


def test_native_fov_uses_real_pawn_controller_property():
    b = seed_field(); a = MagnaCartaAdapter(b)
    controller = 0x1300000
    b.seed_u32(ACTOR+mm.PLAYER_CONTROLLER, controller)
    b.seed_u32(ACTOR+0x1F4, 0x3A04)  # not a controller in all six user states
    b.seed_floats(controller+0x1F4, (63.0,))
    assert a.capture_original_fov() == 63


def legacy_backend(*, active=True):
    b = seed_field()
    for address, words in caves.code_resources():
        if address == mm.RENDER_CAVE: words = caves.LEGACY_RENDER_WORDS
        for i,w in enumerate(words): b.seed_u32(address+4*i,w)
    for address, value in ((mm.MOD_BLOCK,mm.MAGIC), (mm.MOD_BLOCK+mm.MB_FLAGS,13 if active else 0),
                           (mm.MOD_BLOCK+mm.MB_ACK_FLAGS,13 if active else 0),
                           (mm.MOD_BLOCK+mm.MB_COMMAND,mm.CMD_ACK)):
        b.seed_u32(address,value)
    if active:
        for site,_,pair in caves.resources():
            for i,w in enumerate(pair): b.seed_u32(site+4*i,w)
    return b


def test_legacy_allowlist_is_pinned_to_released_body_not_just_magic():
    data=struct.pack('<'+'I'*len(caves.LEGACY_RENDER_WORDS),*caves.LEGACY_RENDER_WORDS)
    assert len(data)==1116
    assert hashlib.sha256(data).hexdigest()=='727816e9d3cce088882737170a011f9b4dab77e80195cc3b5ef2296dc0a9afe9'


@pytest.mark.parametrize('active', [True, False])
def test_exact_legacy_state_is_drained_before_replacing_unreachable_body(active):
    b = legacy_backend(active=active)
    assert caves.preflight(b).legacy
    old_write = b.write_u32
    body_writes = []
    def checked_write(address, value):
        if mm.RENDER_CAVE <= address < mm.RENDER_CAVE+4*len(caves.RENDER_WORDS):
            assert caves.matches(b,0)
            assert b.read_u32(mm.BOOT_SITE) == mm.BOOT_NATIVE
            assert b.read_u32(mm.MOD_BLOCK+mm.MB_COMMAND) == mm.CMD_ACK
            assert b.read_u32(mm.MOD_BLOCK+mm.MB_FLAGS) == 0
            body_writes.append(address)
        old_write(address,value)
    b.write_u32 = checked_write
    a = MagnaCartaAdapter(b); a.set_patch(True)
    assert len(body_writes) == len(caves.RENDER_WORDS)
    assert not caves.preflight(b).legacy
    assert caves.ready(b)
    a.restore()
    assert caves.matches(b,0)


@pytest.mark.parametrize('damage', ['legacy_body', 'legacy_tail', 'other_cave', 'flags', 'ack', 'busy', 'hook'])
def test_unknown_or_incomplete_legacy_never_migrates(damage):
    b = legacy_backend()
    address = {'legacy_body':mm.RENDER_CAVE+4, 'legacy_tail':mm.RENDER_CAVE+4*len(caves.LEGACY_RENDER_WORDS),
               'other_cave':mm.BOOT_CAVE+4, 'flags':mm.MOD_BLOCK+mm.MB_FLAGS,
               'ack':mm.MOD_BLOCK+mm.MB_ACK_FLAGS, 'busy':mm.MOD_BLOCK+mm.MB_COMMAND,
               'hook':mm.RENDER_HOOK+4}[damage]
    b.seed_u32(address,0xDEADBEEF)
    with pytest.raises(caves.PatchConflict): MagnaCartaAdapter(b).set_patch(True)
    assert b.host_writes == []


@pytest.mark.parametrize('kind',['callback','hook','cave'])
def test_legacy_rechecks_all_resources_after_guest_release(kind):
    b=legacy_backend()
    original=b.write_u32
    def race(address,value):
        original(address,value)
        if address==mm.BOOT_SITE and value==mm.BOOT_CAVE:
            damaged={'callback':mm.BOOT_SITE,'hook':mm.RENDER_HOOK+4,'cave':mm.BOOT_CAVE+4}[kind]
            b.seed_u32(damaged,0xDEADBEEF)
    b.write_u32=race
    before=caves.read_words(b,mm.RENDER_CAVE,len(caves.RENDER_WORDS))
    with pytest.raises(caves.PatchConflict): MagnaCartaAdapter(b).set_patch(True)
    assert caves.read_words(b,mm.RENDER_CAVE,len(caves.RENDER_WORDS))==before


def test_paused_legacy_does_not_overwrite_reachable_body(monkeypatch):
    b = legacy_backend(); b.auto_guest=False
    old = caves.read_words(b,mm.RENDER_CAVE,len(caves.RENDER_WORDS))
    def paused(*args): raise caves.PatchConflict('paused')
    monkeypatch.setattr(caves,'wait_ack',paused)
    with pytest.raises(caves.PatchConflict,match='paused'): MagnaCartaAdapter(b).set_patch(True)
    assert caves.read_words(b,mm.RENDER_CAVE,len(caves.RENDER_WORDS)) == old
    assert not any(mm.RENDER_CAVE<=addr<mm.RENDER_CAVE+len(old)*4 for addr,_ in b.host_writes)


@pytest.mark.parametrize('name', ['walking_base','walking_base_only_wait','walking_base_chara_and_camera_move',
                                  'running_base','other_area','other_area_2'])
def test_optional_private_zip_ownership_and_known_legacy(name):
    path=Path('C:/PS2CameraLab/sstates/マグナカルタ')/(name+'.p2s')
    if not path.is_file(): pytest.skip('private local user state unavailable')
    with zipfile.ZipFile(path) as z:
        info=z.getinfo('eeMemory.bin')
        if info.compress_type==93:
            zstd=pytest.importorskip('zstandard')
            z.fp.seek(info.header_offset)
            header=z.fp.read(30); n,x=struct.unpack_from('<HH',header,26)
            z.fp.seek(info.header_offset+30+n+x)
            ram=zstd.ZstdDecompressor().decompress(z.fp.read(info.compress_size),max_output_size=info.file_size)
            import zlib
            assert len(ram)==info.file_size and zlib.crc32(ram)==info.CRC
        else:
            ram=z.read(info)
    def u(a): return struct.unpack_from('<I',ram,a)[0]
    actor=u(mm.PLAYER_GLOBAL); magi=u(actor+mm.PLAYER_MAGI); owner=u(magi+mm.MAGI_OWNER)
    assert owner==u(mm.FIELD_OWNER_GLOBAL) and u(owner+mm.OWNER_MAGI)==magi
    assert u(u(u(magi+12)+0x18)+0x20) in mm.FIELD_SCRIPT_NAMES
    assert u(actor+mm.PLAYER_CONTROLLER) == u(0xE90DB0+0x30)
    assert u(u(actor+mm.PLAYER_CONTROLLER)+0x1EC) == actor
    if name.startswith('other'):
        assert u(OLD_BUCKET) != magi
        assert struct.unpack_from('<'+str(len(caves.LEGACY_RENDER_WORDS))+'I',ram,mm.RENDER_CAVE) == caves.LEGACY_RENDER_WORDS
        assert not any(ram[mm.RENDER_CAVE+4*len(caves.LEGACY_RENDER_WORDS):mm.RENDER_CAVE+4*len(caves.RENDER_WORDS)])
