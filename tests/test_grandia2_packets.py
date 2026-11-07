"""Execute emitted stream reservation, with synthetic native DMA boundaries.

No game binary, socket or emulator. Native submit is a state-machine stub, not
an emulation of actual VIF/GIF/VU hardware; live visual tests are separate.
"""
import pytest

from adapters.grandia2 import packets as p, caves, memory_map as mm
from tests.test_grandia2 import FakeBackend, seed_field
from core import mips_asm as m

MASK64, MASK128 = (1 << 64) - 1, (1 << 128) - 1


class PacketMachine:
    def __init__(self, b, *, used=0x180000, bank=0):
        self.b = b
        self.regs = [((0x1234567890ABCDEF + i) << 64) | (0x10000 + i) for i in range(32)]
        self.regs[0] = 0
        self.regs[29] = 0x1FF0000
        self.regs[31] = 0x33330000
        self.fp = [0x3F800000 + i for i in range(32)]
        self.special = [0xABCDEF0012345678 + i for i in range(6)]
        self.calls, self.submitted = [], []
        self.pending_payloads, self.transmitted_payloads = [], []
        self.returned = False
        self.b.seed_u32(mm.MOD_BLOCK, mm.MAGIC)
        self.b.seed_u32(p.BANK_INDEX, bank)
        self.b.seed_u32(p.PUT, p.BANK_BASE + bank * p.BANK_SIZE + used)
        self.b.seed_u32(p.VU_INDEX, 137)
        self.b.seed_u32(0x2EA880, 0)  # DIRECT-only occupancy must still flush.
        for i, word in enumerate(p.WORDS):
            self.b.seed_u32(p.BASE + i * 4, word)

    def low(self, r):
        return self.regs[r] & MASK64

    def put(self, r, value):
        if r:
            self.regs[r] = (self.regs[r] & (MASK128 ^ MASK64)) | (value & MASK64)

    def execute(self, w):
        op, rs, rt, rd = w >> 26, w >> 21 & 31, w >> 16 & 31, w >> 11 & 31
        imm = w & 65535
        off = imm - 65536 if imm & 32768 else imm
        address = (self.low(rs) + off) & 0xFFFFFFFF
        special_reads = (0x00004010, 0x00004012, 0x70004010, 0x70004012, 0x00004028, 0x4448F800)
        special_writes = (0x01000011, 0x01000013, 0x71000011, 0x71000013, 0x01000029, 0x44C8F800)
        if w in special_reads:
            self.put(8, self.special[special_reads.index(w)]); return
        if w in special_writes:
            self.special[special_writes.index(w)] = self.low(8); return
        if w == 0:
            return
        if op == 0:
            fn = w & 63
            if fn == 0: value = self.low(rt) << (w >> 6 & 31)
            elif fn == 0x21: value = (self.low(rs) + self.low(rt)) & 0xFFFFFFFF
            elif fn == 0x23: value = (self.low(rs) - self.low(rt)) & 0xFFFFFFFF
            elif fn == 0x2B: value = int(self.low(rs) < self.low(rt))
            else: raise AssertionError(hex(w))
            self.put(rd, value)
        elif op == 0x0F: self.put(rt, imm << 16)
        elif op == 0x0D: self.put(rt, self.low(rs) | imm)
        elif op == 0x0B: self.put(rt, int(self.low(rs) < off))
        elif op == 9: self.put(rt, (self.low(rs) + off) & 0xFFFFFFFF)
        elif op == 0x23: self.put(rt, self.b.read_u32(address))
        elif op == 0x2B: self.b.write_u32(address, self.low(rt))
        elif op == 0x1E: self.regs[rt] = int.from_bytes(self.b.bytes_at(address, 16), 'little')
        elif op == 0x1F: self.b.seed(address, self.regs[rt].to_bytes(16, 'little'))
        elif op == 0x37: self.put(rt, int.from_bytes(self.b.bytes_at(address, 8), 'little'))
        elif op == 0x3F: self.b.seed(address, self.low(rt).to_bytes(8, 'little'))
        elif op == 0x31: self.fp[rt] = self.b.read_u32(address)
        elif op == 0x39: self.b.seed_u32(address, self.fp[rt])
        else: raise AssertionError(hex(w))

    def native(self, target):
        self.calls.append(target)
        bank = self.b.read_u32(p.BANK_INDEX)
        put = self.b.read_u32(p.PUT)
        if target in (0x2610D8, 0x261268):
            assert put + 31 <= p.BANK_BASE + (bank + 1) * p.BANK_SIZE
        if target == 0x261268:
            self.submitted.append((bank, put))
            self.transmitted_payloads.extend(self.pending_payloads)
            self.pending_payloads.clear()
            self.b.seed_u32(p.BANK_INDEX, bank ^ 1)
        elif target == 0x260F50:
            self.b.seed_u32(p.PUT, p.BANK_BASE + bank * p.BANK_SIZE)
        elif target == 0x261098:
            self.b.seed_u32(p.PUT, put + 16)
            self.b.seed_u32(p.VU_INDEX, 0)
        elif target == 0x260D90:
            self.b.seed_u32(p.PUT, (put + 15 & ~15) + 16)
        assert self.b.read_u32(mm.MOD_BLOCK + p.MB_STREAM_BUSY) == (target != 0x260D90)
        # Aggressively clobber every user GPR, both 128-bit arithmetic pipelines,
        # floating-point registers and FCSR. Kernel scratch and SP survive.
        for r in p.REGS:
            if r != 31:
                self.regs[r] = MASK128 - r
        self.fp = [0x7F000000 + i for i in range(32)]
        self.special = [0xDEADBEEF] * 6

    def run(self, entry):
        native, stock, cave, _size = next(row for row in p.SPECS if row[2] == entry)
        # Hook executes the original second instruction as its delay slot.
        self.execute(stock[1])
        before = (self.regs.copy(), self.fp.copy(), self.special.copy())
        pc = entry
        for _ in range(3000):
            if pc == native + 8:
                self.returned = True
                break
            w = self.b.read_u32(pc)
            op = w >> 26
            if op in (2, 3, 4, 5) or w == 0x03E00008:
                rs, rt = w >> 21 & 31, w >> 16 & 31
                signed = (w & 65535) - (65536 if w & 32768 else 0)
                dest = ((w & 0x3FFFFFF) << 2) if op in (2, 3) else pc + 4 + signed * 4
                if w == 0x03E00008: dest = self.low(31)
                take = op not in (4, 5) or ((self.low(rs) == self.low(rt)) == (op == 4))
                if op == 3: self.put(31, pc + 8)
                self.execute(self.b.read_u32(pc + 4))
                if take and not p.BASE <= dest < p.LIMIT and dest != native + 8:
                    assert op == 3
                    self.native(dest)
                    pc += 8
                else:
                    pc = dest if take else pc + 8
            else:
                self.execute(w); pc += 4
        assert self.returned
        return before


@pytest.mark.parametrize('entry,reserve', [(p.CONTROL, p.CONTROL_RESERVE),
                                         (p.DIRECT, p.DIRECT_RESERVE), (p.UNPACK, p.UNPACK_RESERVE)])
@pytest.mark.parametrize('bank', [0, 1])
@pytest.mark.parametrize('extra,flush', [(0, False), (4, True)])
def test_reserve_checks_raw_bank_usage_before_payload_and_keeps_state(entry, reserve, bank, extra, flush):
    machine = PacketMachine(seed_field(FakeBackend()), used=p.BANK_SIZE-reserve+extra, bank=bank)
    before_regs, before_fp, before_special = machine.run(entry)
    # Only the displaced first native instruction changes its destination.
    original_first = next(row[1][0] for row in p.SPECS if row[2] == entry)
    dest = original_first >> 16 & 31
    expected = before_regs.copy()
    expected[dest] = (expected[dest] & (MASK128 ^ MASK64)) | ((original_first & 65535) << 16)
    assert machine.regs == expected
    assert machine.fp == before_fp
    assert machine.special == before_special
    assert len(machine.submitted) == int(flush)
    assert machine.b.read_u32(p.VU_INDEX) == 137
    assert machine.b.read_u32(mm.MOD_BLOCK+p.MB_STREAM_BUSY) == 0
    assert machine.b.read_u32(mm.MOD_BLOCK+p.MB_FLUSHES) == int(flush)
    expected_calls = ([0x2610D8, 0x261268, 0x2A5820, 0x261358, 0x260F50, 0x261098] if flush else [])
    if entry == p.DIRECT: expected_calls.append(0x260D90)
    assert machine.calls == expected_calls


def test_many_mesh_chunks_stream_without_discarding_or_reordering_payloads():
    machine = PacketMachine(seed_field(FakeBackend()), used=16)
    for index in range(1600):
        machine.run(p.UNPACK)
        put = machine.b.read_u32(p.PUT)
        bank = machine.b.read_u32(p.BANK_INDEX)
        # Largest native strip chunk fits even with its control/end padding.
        assert put + 213*16 + 64 < p.BANK_BASE + (bank+1)*p.BANK_SIZE
        machine.pending_payloads.append(index)
        machine.b.seed_u32(p.PUT, put + 213*16 + 12)
    assert machine.transmitted_payloads + machine.pending_payloads == list(range(1600))
    assert len(machine.submitted) >= 2
    assert machine.b.read_u32(mm.MOD_BLOCK+p.MB_HIGH_WATER) < p.BANK_SIZE


def test_streaming_resources_never_patch_original_fatal_or_bank_configuration():
    addresses = {address for address, _stock, _hook in caves.SITES}
    assert not addresses.intersection({0x26112C, 0x261130, 0x261134, 0x261150,
                                       0x2612C4, 0x2612E4, p.BANK_INDEX})
    assert p.DIRECT_RESERVE > 65535*16 + 31
    assert p.UNPACK_RESERVE > 256*16 + 31
    assert p.GPR_OFFSET + len(p.REGS)*16 <= p.FPU_OFFSET
    assert p.SPECIAL_OFFSET + 6*8 <= p.FRAME - 24
    assert p.BASE + len(p.WORDS)*4 < mm.FINISH_CAVE


@pytest.mark.parametrize('entry', [p.CONTROL, p.DIRECT, p.UNPACK])
@pytest.mark.parametrize('invalid', ['magic', 'busy', 'bank'])
def test_unknown_or_nested_stream_state_does_not_submit_or_change_ownership(entry, invalid):
    machine = PacketMachine(seed_field(FakeBackend()), used=0x1FFFF0)
    if invalid == 'magic': machine.b.seed_u32(mm.MOD_BLOCK, 0x47324331)  # old G2C1 is not owned
    elif invalid == 'busy': machine.b.seed_u32(mm.MOD_BLOCK+p.MB_STREAM_BUSY, 1)
    else: machine.b.seed_u32(p.BANK_INDEX, 2)
    before_fp, before_special = machine.fp.copy(), machine.special.copy()
    machine.run(entry)
    assert not machine.calls
    assert machine.fp == before_fp and machine.special == before_special
    assert machine.b.read_u32(p.PUT) == p.BANK_BASE + 0x1FFFF0


def test_direct_gets_separate_cnt_without_resetting_vu_index_or_caches():
    b = seed_field(FakeBackend())
    machine = PacketMachine(b, used=0xC7000)
    queue = b.bytes_at(0x84D348, 0x120)
    machine.run(p.DIRECT)
    assert machine.calls == [0x260D90]
    assert b.read_u32(p.VU_INDEX) == 137
    assert b.bytes_at(0x84D348, 0x120) == queue
    assert not machine.submitted
