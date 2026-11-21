"""Offline map rig behaviour: never replace a loaded state's native camera with an old one."""
import math
import unittest

from adapters.rpgmaker5.adapter import RPGMaker5Adapter, RigConflict
from core.camera_math.orbit import Vec3
from core.camera_runtime.engine import CameraRuntime


PARENT, RIG, CHILD = 0x11458C0, 0x1145900, 0x18C0A00
YAW, PITCH, RADIUS = RIG + 8, RIG + 0x20, RIG + 0x14
LENS = 0x11D6E0


class MapBackend:
    """Independent, sparse memory example; an unexpected read fails rather than returning zero."""

    def __init__(self, mode=0):
        self.epoch = 1
        self.gid, self.disc = 'SLPS-20143', 'BB78C51D'
        self.words = {0x70C3E0: PARENT, 0x70C3E4: PARENT, PARENT: RIG, PARENT + 8: PARENT,
                      PARENT + 0x2C: 0x169C48, PARENT + 0x30: 0x1697C8, PARENT + 0x34: 0x169B20,
                      PARENT + 0x3C: 77, RIG + 4: 0x16A770, RIG + 0x68: mode,
                      RIG + 0x10: 0, RIG + 0x18: 0, RIG + 0x28: 0, RIG + 0x738: 0,
                      RIG + 0x60: 10, RIG + 0x64: 20, RIG: 32 if mode == 3 else 0x7FFFFFFF,
                      YAW: 0xFFFFE000, PITCH: 0x4000, RADIUS: 350 if mode == 3 else 1000,
                      LENS: 0x3C014400, LENS + 4: 0x44816000, LENS + 8: 0x3C014000,
                      LENS + 12: 0x44816800}
        self.draw_task(CHILD)
        self.floats = {0x6BC3E0: (168.0, 428.0, -220.0), 0x6BC4E0: (1024.0,)}
        self.writes = []

    def draw_task(self, child):
        self.words.update({0x70C190: child, 0x70C194: child, child + 4: PARENT,
                           child + 8: child, child + 0x2C: 0x11D950})

    def game_id(self): return self.gid
    def crc(self): return self.disc
    def title(self): return 'RPG Maker 5'
    def read_u32(self, addr): return self.words[addr]

    def read_floats(self, addr, count):
        vals = self.floats[addr]
        assert len(vals) == count
        return vals

    def write_u32(self, addr, value):
        self.writes.append((addr, value))
        self.words[addr] = value

    def params(self):
        return tuple(self.words[a] for a in (YAW, PITCH, RADIUS))


def identified(mode=0):
    b = MapBackend(mode)
    a = RPGMaker5Adapter(b)
    assert a.identify().matched
    return a, b


class RpgMaker5RigTest(unittest.TestCase):
    def test_identification_requires_both_serial_and_crc_before_acquiring(self):
        for gid, crc in [('SLPS-20143', 'BB78C51E'), ('SLPS-20144', 'BB78C51D'), ('', '')]:
            with self.subTest(gid=gid, crc=crc):
                b = MapBackend()
                b.gid, b.disc = gid, crc
                a = RPGMaker5Adapter(b)
                self.assertFalse(a.identify().matched)
                self.assertFalse(a.is_field_like(a.read_scene()))
                with self.assertRaises(RigConflict):
                    a.set_patch(True)
                self.assertEqual(b.writes, [])

    def test_center_uses_native_angles_radius_and_live_target_without_writes(self):
        for mode, height, radius in [(0, 0, 1000), (3, -32, 350)]:
            with self.subTest(mode=mode):
                a, b = identified(mode)
                scene = a.read_scene()
                self.assertTrue(a.is_field_like(scene))
                self.assertEqual(scene.game_pose.eye, Vec3(168, -220, 428))
                self.assertEqual(scene.player, Vec3(168, height, 328))
                pose = a.center_on_target(1234, 0)
                self.assertEqual(pose.target, scene.player)
                self.assertAlmostEqual(pose.distance(), radius)
                yaw, pitch = map(math.degrees, pose.yaw_pitch())
                self.assertAlmostEqual(yaw, 45)
                self.assertAlmostEqual(pitch, 45)
                self.assertEqual(b.writes, [])

    def test_native_scroll_and_tile_commit_remain_game_owned_during_orbit(self):
        for mode in (0, 3):
            with self.subTest(mode=mode):
                a, b = identified(mode)
                a.set_patch(True)
                old = a.read_player()
                b.words[RIG + 0x738] = 1  # sub-tile motion, truncate XY toward zero
                b.floats[RIG + 0x810] = (-14.8, 332.9, 35.25)
                self.assertEqual(a.read_player(), Vec3(-14, -35.25 if mode else 0, 332))
                a.write_orbit_params(old, 90, 35, 600)  # a stale host centre must NOT pin the tile
                b.words.update({RIG + 0x738: 0, RIG + 0x60: 0xFFFFFFFF, RIG + 0x64: 21})
                self.assertEqual(a.read_player(), Vec3(-8, -32 if mode else 0, 344))
                self.assertEqual({k for k, v in b.writes}, {YAW, PITCH, RADIUS})

    def test_normal_release_restores_original_words_not_default_angles_or_radius(self):
        for mode in (0, 3):
            with self.subTest(mode=mode):
                a, b = identified(mode)
                native = dict(b.words)
                a.set_patch(True)
                self.assertEqual(b.writes, [])
                self.assertEqual(a.patch_state(), 'applied')
                a.write_orbit_params(a.read_player(), 90, 30, 620)
                self.assertEqual(b.params(), (0xFFFFC000, 21845, 620))
                a.write_fov_deg(60)
                self.assertEqual(b.words[LENS], 0x3C01435E)
                a.set_patch(True)  # idempotent, don't recapture our own values as original
                writes_before = list(b.writes)
                a.write_orbit_params(a.read_player(), 90, 30, 620)
                self.assertEqual(b.writes, writes_before)
                a.set_patch(False)
                self.assertEqual(b.words, native)
                self.assertEqual(a.patch_state(), 'stock')
                self.assertEqual({addr for addr, _ in b.writes}, {YAW, PITCH, RADIUS, LENS})

    def test_invalid_task_links_and_transitions_never_arm(self):
        for address, value in ((0x70C3E0, 0), (0x70C3E4, 0), (0x70C190, 0), (0x70C194, 0),
                               (CHILD + 4, 0), (CHILD + 8, 0), (CHILD + 0x2C, 0x11D954),
                               (PARENT + 0x3C, 76), (RIG + 0x68, 2), (RIG + 0x10, 1),
                               (RIG + 0x18, 1), (RIG + 0x28, 1)):
            with self.subTest(address=hex(address)):
                a, b = identified()
                b.words[address] = value
                self.assertFalse(a.is_field_like(a.read_scene()))
                with self.assertRaises(RigConflict):
                    a.set_patch(True)
                self.assertEqual(b.writes, [])

    def test_loaded_camera_is_not_overwritten_even_if_other_parameters_match(self):
        def epoch(b): b.epoch += 1
        changes = {'other scene': lambda b: b.words.update({RIG + 0x68: 3}),
                   'same scene, different angles': lambda b: b.words.update({PITCH: 0x6000}),
                   'different valid draw task': lambda b: b.draw_task(CHILD + 0x200),
                   'new connection': epoch,
                   'native transition': lambda b: b.words.update({RIG + 0x10: 1})}
        for name, change in changes.items():
            with self.subTest(name=name):
                a, b = identified()
                a.set_patch(True)
                a.write_orbit_params(a.read_player(), 90, 30, 620)
                change(b)
                loaded = dict(b.words)
                b.writes.clear()
                with self.assertRaises(RigConflict):
                    a.write_orbit_params(Vec3(0, 0, 0), 60, 50, 500)
                with self.assertRaises(RigConflict):
                    a.set_patch(True)  # no silent reacquire inside Orbit
                a.set_patch(False)  # cannot restore a dead lease
                self.assertEqual(b.words, loaded)
                self.assertEqual(b.writes, [])

    def test_first_post_load_action_can_be_original_without_stale_restore(self):
        a, b = identified(3)
        a.set_patch(True)
        a.write_orbit_params(a.read_player(), -90, 30, 800)
        b.words[YAW] = 0x2000
        loaded = dict(b.words)
        b.writes.clear()
        with self.assertRaises(RigConflict):
            a.set_patch(False)
        self.assertEqual(b.words, loaded)
        self.assertEqual(b.writes, [])

    def test_runtime_abandon_does_not_restore_into_the_next_game(self):
        a, b = identified()
        runtime = CameraRuntime(a)
        a.set_patch(True)
        a.write_orbit_params(a.read_player(), 90, 30, 620)
        a.write_fov_deg(40)
        b.gid, b.disc = 'OTHER-GAME', '12345678'
        b.writes.clear()
        runtime.abandon()
        runtime.restore()
        self.assertEqual(b.writes, [])


if __name__ == '__main__':
    unittest.main()
