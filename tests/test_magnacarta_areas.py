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
                                  MAGI, SCRIPT_FRAME, SCRIPT_STATE, PC, VIEWPORT, LEVEL, GAME)
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


def render(b, *, actor=ACTOR, viewport=VIEWPORT):
    machine = RenderMachine(b)
    for r in range(1, 32):
        machine.regs[r] = (r << 120) | (r << 64) | r
    machine.regs[m.SP] = 0x1F00000
    machine.regs[m.A1] = viewport
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
    for address, value in ((magi+mm.ACTOR_LEVEL, LEVEL), (PC+mm.PC_PAWN, actor),
                           (actor+mm.PLAYER_CONTROLLER, PC), (actor + mm.PLAYER_MAGI, magi),
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
    assert not any(addr in (OLD_BUCKET, mm.PLAYER_GLOBAL) for addr, _ in b.reads)


@pytest.mark.parametrize('address,value', [
    (ACTOR + mm.PLAYER_MAGI, 0), (ACTOR + mm.PLAYER_MAGI, MAGI+1),
    (ACTOR + mm.PLAYER_MAGI, 0x1FFF000), (MAGI + mm.MAGI_OWNER, 0),
    (MAGI + mm.MAGI_OWNER, OWNER+1), (MAGI + mm.MAGI_OWNER, 0x1FFF000),
    (OWNER + mm.OWNER_MAGI, MAGI+16), (mm.FIELD_OWNER_GLOBAL, OWNER+16),
    (OWNER + mm.STATE_POINTER, STATE+1), (STATE+0x90, 3 << 8),
    (MAGI+mm.ACTOR_LEVEL, LEVEL+4), (LEVEL+mm.LEVEL_GAME, 0x1FFF000),
    (GAME+mm.GAME_LOCAL_PC, PC+16), (PC+mm.PC_PLAYER, VIEWPORT+16),
    (VIEWPORT+mm.VIEWPORT_ACTOR, PC+16), (PC+mm.PC_PAWN, ACTOR+16),
    (ACTOR+mm.PLAYER_CONTROLLER, PC+16), (STATE+0x90, 0), (SCRIPT_STATE+0x20, 0x3148),
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


@pytest.mark.parametrize('mode,name', [(1,0x31D3), (2,0x31CC), (0,0x3148)])
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
    # A different viewport/viewactor or stale bank must revoke acceptance.
    assert render(b,viewport=VIEWPORT+16)[2:] == ([10,20,30],(1,2,3))
    assert b.read_u32(mm.MOD_BLOCK+mm.MB_ACCEPTED) == 0
    slot=mm.MOD_BLOCK+mm.SLOTS[b.read_u32(mm.MOD_BLOCK+mm.MB_SLOT)]
    b.seed_u32(slot+mm.SLOT_PLAYER,ACTOR+16)
    assert render(b)[2:] == ([10,20,30],(1,2,3))
    b.seed_u32(slot+mm.SLOT_PLAYER,ACTOR)
    call = render(b, actor=ACTOR+16)
    assert call[2:] == ([10,20,30], (1,2,3))
    assert b.read_u32(mm.MOD_BLOCK+mm.MB_ACCEPTED) == 0


def test_slot_republished_before_first_sequence_read_checks_copied_owner():
    b=seed_field(); a=MagnaCartaAdapter(b); a.set_patch(True)
    slot=mm.MOD_BLOCK+mm.SLOTS[b.read_u32(mm.MOD_BLOCK+mm.MB_SLOT)]
    original=b.read_u32; changed=[]
    def republish(address):
        if not changed and address==slot+mm.SLOT_SEQUENCE:
            changed.append(True)
            b.seed_u32(slot+mm.SLOT_PLAYER,ACTOR+16)
            b.seed_u32(slot+mm.SLOT_SEQUENCE,original(slot)+2)
        return original(address)
    b.read_u32=republish
    assert render(b)[2:]==([10,20,30],(1,2,3))
    assert changed and a.heartbeat_word()==0 and b.read_u32(mm.MOD_BLOCK+mm.MB_ACCEPTED)==0


def test_native_fov_uses_real_pawn_controller_property():
    b = seed_field(); a = MagnaCartaAdapter(b)
    ai,ai_controller=0x1A00000,0x1A10000
    b.seed_u32(mm.PLAYER_GLOBAL,ai); b.seed_u32(ai+mm.PLAYER_CONTROLLER,ai_controller)
    b.seed_floats(ai_controller+0x1F4,(90.0,)); b.seed_floats(PC+0x1F4,(63.0,))
    assert a.capture_original_fov() == a.read_fov_deg() == 63
    a.set_patch(True); b.seed_u32(mm.MOD_BLOCK+mm.MB_ACCEPTED, ai)  # stale applied telemetry
    b.seed_u32(mm.MOD_BLOCK+mm.MB_APPLIED,1); b.seed_floats(mm.MOD_BLOCK+mm.MB_RENDER_FOV,(85.0,))
    assert a.read_fov_deg()==63
    assert a.read_game_pose().eye==Vec3(100,-700,-1000)


def legacy_backend(*, active=True, renderer=caves.LEGACY_RENDER_WORDS):
    b = seed_field()
    for address, words in caves.code_resources():
        if address == mm.RENDER_CAVE: words = renderer
        if address == caves.directions.CAVE: words = caves.directions.movement_words(released=True)
        for i,w in enumerate(words): b.seed_u32(address+4*i,w)
    for address, value in ((mm.MOD_BLOCK,mm.MAGIC), (mm.MOD_BLOCK+mm.MB_FLAGS,13 if active else 0),
                           (mm.MOD_BLOCK+mm.MB_ACK_FLAGS,13 if active else 0),
                           (mm.MOD_BLOCK+mm.MB_COMMAND,mm.CMD_ACK)):
        b.seed_u32(address,value)
    if active:
        for site,_,pair in caves.resources():
            for i,w in enumerate(pair): b.seed_u32(site+4*i,w)
    return b


@pytest.mark.parametrize('words,size,digest', [
    (caves.LEGACY_RENDER_WORDS,1116,'727816e9d3cce088882737170a011f9b4dab77e80195cc3b5ef2296dc0a9afe9'),
    (caves.PAWN_RENDER_WORDS,1160,'af9fb2fff58341f7e93e4e65d212c7ac6c298be539c2d5283bb6ef072ed9dc3d'),
    (caves.directions.movement_words(released=True),168,'6ea049868b0c03e51003f0bdffca831c573206333698007bd8e3bc9f94278a07'),
], ids=['hash renderer','pawn renderer','old movement'])
def test_legacy_allowlist_is_pinned_to_released_body_not_just_magic(words,size,digest):
    data=struct.pack(f'<{len(words)}I',*words)
    assert len(data)==size and hashlib.sha256(data).hexdigest()==digest


@pytest.mark.parametrize('active', [True, False])
@pytest.mark.parametrize('renderer',caves.RELEASED_RENDERERS,ids=['hash','pawn'])
def test_exact_legacy_state_is_drained_before_replacing_unreachable_body(active,renderer):
    b = legacy_backend(active=active,renderer=renderer)
    assert caves.preflight(b).legacy
    old_write = b.write_u32
    body_writes = []
    def checked_write(address, value):
        if (mm.RENDER_CAVE <= address < mm.RENDER_CAVE+4*len(caves.RENDER_WORDS)
                or caves.directions.CAVE <= address < caves.directions.CAVE+4*len(caves.directions.movement_words())):
            assert caves.matches(b,0)
            assert b.read_u32(mm.BOOT_SITE) == mm.BOOT_NATIVE
            assert b.read_u32(mm.MOD_BLOCK+mm.MB_COMMAND) == mm.CMD_ACK
            assert b.read_u32(mm.MOD_BLOCK+mm.MB_FLAGS) == 0
            body_writes.append(address)
        old_write(address,value)
    b.write_u32 = checked_write
    a = MagnaCartaAdapter(b); a.set_patch(True)
    assert len(body_writes) == len(caves.RENDER_WORDS)+len(caves.directions.movement_words())
    assert not caves.preflight(b).legacy
    assert caves.ready(b)
    a.restore()
    assert caves.matches(b,0)


@pytest.mark.parametrize('damage', ['legacy_body', 'legacy_tail', 'move_body', 'move_tail', 'other_cave', 'flags', 'ack', 'busy', 'hook'])
def test_unknown_or_incomplete_legacy_never_migrates(damage):
    b = legacy_backend()
    address = {'legacy_body':mm.RENDER_CAVE+4, 'legacy_tail':mm.RENDER_CAVE+4*len(caves.LEGACY_RENDER_WORDS),
               'move_body':caves.directions.CAVE+4,
               'move_tail':caves.directions.CAVE+4*len(caves.directions.movement_words(released=True)),
               'other_cave':mm.BOOT_CAVE+4, 'flags':mm.MOD_BLOCK+mm.MB_FLAGS,
               'ack':mm.MOD_BLOCK+mm.MB_ACK_FLAGS, 'busy':mm.MOD_BLOCK+mm.MB_COMMAND,
               'hook':mm.RENDER_HOOK+4}[damage]
    b.seed_u32(address,0xDEADBEEF)
    with pytest.raises(caves.PatchConflict): MagnaCartaAdapter(b).set_patch(True)
    assert b.host_writes == []


@pytest.mark.parametrize('stock_hook',[False, True])
@pytest.mark.parametrize('replacement',['render','move'])
def test_exact_but_mixed_release_sets_fail_without_any_writes(stock_hook,replacement):
    b=legacy_backend(active=not stock_hook,renderer=caves.PAWN_RENDER_WORDS)
    base,words=((mm.RENDER_CAVE,caves.RENDER_WORDS) if replacement=='render' else
                (caves.directions.CAVE,caves.directions.movement_words()))
    for i,w in enumerate(words): b.seed_u32(base+i*4,w)
    with pytest.raises(caves.PatchConflict,match='mixed'): MagnaCartaAdapter(b).set_patch(True)
    assert not b.host_writes


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
                                  'running_base','other_area','other_area_2','other_area_2-2',
                                  *(f'other_area_{i}' for i in range(3,12))])
def test_optional_private_zip_ownership_and_known_legacy(name):
    path=Path(__file__).resolve().parents[2]/'sstates/マグナカルタ'/(name+'.p2s')
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
    # Mutations are limited to this process's RAM copy, including bootstrap
    # and builder-stub execution; these are not rendered guest-frame results.
    class StateBackend(FakeBackend):
        def __init__(self): super().__init__(); self.ram=bytearray(ram)
        def bytes_at(self,address,length): return self.ram[address:address+length]
        def seed(self,address,data): self.ram[address:address+len(data)]=data
    b=StateBackend(); u=b.read_u32; a=MagnaCartaAdapter(b)
    assert a.read_scene().valid and a.capture_original_fov()==55.0
    actor,_,pc=a._field_view(); viewport=u(pc+mm.PC_PLAYER); alias=u(mm.PLAYER_GLOBAL)
    assert (alias!=actor)==(name in ('other_area_2-2','other_area_4','other_area_5',
                                     'other_area_7','other_area_8','other_area_9'))
    p=caves.preflight(b)
    assert p.legacy==('hash' if name in ('other_area','other_area_2') else
                      'pawn' if name.startswith('other_') else '')
    a.write_orbit_params(a.read_player(),75,20,450,target_offset=Vec3(0,-100,0))
    hb=a.heartbeat_word(); render(b,actor=actor,viewport=viewport)
    assert a.heartbeat_word()==(hb+1)&0xFFFFFFFF and u(mm.MOD_BLOCK+mm.MB_ACCEPTED)==actor
    if alias!=actor:
        assert render(b,actor=alias,viewport=viewport)[2:]==([10,20,30],(1,2,3))
        assert u(mm.MOD_BLOCK+mm.MB_ACCEPTED)==0
    a.restore(); assert caves.matches(b,0)
