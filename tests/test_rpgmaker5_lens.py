"""Projection readback, scene ownership and safe release without a running emulator."""
import math
import unittest

from adapters.rpgmaker5.lens import (
    Lens, LensConflict, NATIVE_DEG, SIGNATURE, SITE, STOCK, VIEW_SCREEN,
)


class Backend:
    def __init__(self):
        self.epoch = 1
        self.mem = {SITE + 4 * i: word for i, word in enumerate((STOCK, *SIGNATURE))}
        self.scale = 1024.0
        self.writes = []

    def read_floats(self, addr, count):
        assert (addr, count) == (VIEW_SCREEN, 1)
        return [self.scale]

    def read_u32(self, addr):
        return self.mem[addr]

    def write_u32(self, addr, word):
        self.writes.append((addr, word))
        self.mem[addr] = word


class RpgMaker5LensTest(unittest.TestCase):
    def setUp(self):
        self.b = Backend()
        self.lens = Lens(self.b)

    def test_horizontal_fov_uses_projected_scale_not_command_cache(self):
        self.assertAlmostEqual(self.lens.read_deg(), 28.07248694)
        self.lens.write('editor', 60)
        self.assertAlmostEqual(self.lens.read_deg(), NATIVE_DEG)  # renderer not run yet
        self.b.scale = 444.0
        self.assertAlmostEqual(self.lens.read_deg(), 59.93348374)
        for bad in (0.0, -2.0, math.inf, math.nan):
            self.b.scale = bad
            with self.assertRaises(LensConflict):
                self.lens.read_deg()

    def test_closest_half_immediates_shared_between_both_scenes(self):
        for mode, deg, word in [('editor', 20, 0x3C014435), ('test', 40, 0x3C0143B0),
                                ('editor', 60, 0x3C01435E)]:
            self.lens.write(mode, deg)
            self.assertEqual(self.b.mem[SITE], word)
            self.assertTrue(self.lens.in_sync('test', deg))
        self.lens.write('test', 60)
        self.lens.restore()
        self.assertEqual(self.b.writes, [(SITE, x) for x in (0x3C014435, 0x3C0143B0, 0x3C01435E, STOCK)])
        self.lens.restore()
        self.assertTrue(self.lens.in_sync('editor', NATIVE_DEG))
        self.assertTrue(self.lens.in_sync('test', None))
        self.assertEqual(len(self.b.writes), 4)

    def test_reject_preexisting_match_without_acquiring_it(self):
        self.b.mem[SITE] = 0x3C01435E  # already matches requested 60, but not ours
        for action in (self.lens.write, self.lens.in_sync):
            with self.assertRaises(LensConflict):
                action('editor', 60)
        self.lens.restore()
        self.assertEqual(self.b.writes, [])
        self.assertEqual(self.b.mem[SITE], 0x3C01435E)

    def test_owned_or_stock_does_not_override_corrupt_neighbors(self):
        for offset in (4, 8, 12):
            for owned in (False, True):
                b = Backend()
                lens = Lens(b)
                if owned:
                    lens.write('editor', 20)
                b.mem[SITE + offset] ^= 1
                old = dict(b.mem)
                with self.assertRaises(LensConflict):
                    lens.restore() if owned else lens.write('test', 40)
                self.assertEqual(b.mem, old)
                self.assertEqual(len(b.writes), int(owned))

    def test_stock_state_load_can_reacquire_but_has_nothing_to_restore(self):
        self.lens.write('editor', 40)
        self.b.mem[SITE] = STOCK
        self.assertFalse(self.lens.in_sync('test', 40))
        self.lens.restore()
        self.assertEqual(len(self.b.writes), 1)
        self.lens.write('test', 40)
        self.assertTrue(self.lens.in_sync('test', 40))
        self.b.mem[SITE] = STOCK
        self.lens.restore()
        self.assertEqual(len(self.b.writes), 2)

    def test_modified_owned_word_is_not_an_implicit_restore_target(self):
        self.lens.write('editor', 20)
        self.b.mem[SITE] = 0x3C0143B0  # plausible, from elsewhere/a different savestate
        with self.assertRaises(LensConflict):
            self.lens.restore()
        with self.assertRaises(LensConflict):
            self.lens.write('test', 40)
        self.assertEqual(self.b.mem[SITE], 0x3C0143B0)
        self.assertEqual(len(self.b.writes), 1)

    def test_reconnect_invalidates_even_a_matching_previous_write(self):
        self.lens.write('editor', 20)
        self.b.epoch += 1
        self.lens.restore()
        self.assertEqual(len(self.b.writes), 1)
        with self.assertRaises(LensConflict):
            self.lens.write('editor', 20)

    def test_bad_values_or_scene_cannot_write(self):
        for mode, deg in [('title', 40), ('test', math.nan), ('test', math.inf),
                          ('editor', 19.99), ('test', 61.0)]:
            with self.assertRaises(ValueError):
                self.lens.write(mode, deg)
        self.assertEqual(self.b.writes, [])


if __name__ == '__main__':
    unittest.main()
