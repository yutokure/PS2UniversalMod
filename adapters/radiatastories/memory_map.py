"""Radiata Stories Japanese SLPM-65800 / AC73005E; EE physical addresses.

2026-11-03: protected-state differences, live write watchpoints and Ghidra.
Do not confuse the audio listener at [[37EF88]+1390] with the render camera.
"""
GAME_ID = 'SLPM-65800'
DISC_CRC = 'AC73005E'
SCENE_PTR = 0x0037F734
ACTOR_MANAGER_PTR = 0x0037FC08
ACTOR_COUNT = 0x10
ACTOR_RECORDS = 0x14
ACTOR_STRIDE = 0x80
ACTOR_LIMIT = 196
ACTOR_ID = 0
ACTOR_OBJECT = 0x58
ACTOR_NODE = 0x5C
PLAYER_ID = 0x830  # scene u16, native alias 0x26AC resolver
NODE_VTABLE = 0x0014F970
NODE_POS = 0x20
FIELD_MANAGER_PTR = 0x0037FBF8
FIELD_OWNER = 0x1514
OWNER_CAMERA = 0x10
OWNER_TARGET = 0x14
RENDERER_PTR = 0x0037EFE8
RENDERER_CAMERA = 0x94
CAMERA_VTABLE = 0x0014E9A0
CAM_NATIVE_WORLD = 0x90  # row-major; temporarily substituted inside update only
CAM_VIEW = 0x2C0
CAM_FOV = 0x260
CAM_FOV_SCALE_X = 0x254
CAM_FOV_SCALE_Y = 0x258
CAM_FOCAL = 0x278
CAM_ASPECT = 0x27C
CAM_VIEWPORT_MIN_X = 0x290
CAM_VIEWPORT_MAX_X = 0x2A0
CAM_PROJECTION = 0x340
VIEW_HOOK = 0x001B4F84
VIEW_STOCK = (0x0C07AC5C, 0x27A400D0)
FOV_HOOK = 0x001B500C
FOV_STOCK = (0x0C04856E, 0)
FINISH_HOOK = 0x001B51FC
FINISH_STOCK = (0x0C06CFDC, 0x7FA200C0)
FUN_INVERSE = 0x001EB170
FUN_TAN = 0x001215B8
FUN_FRUSTUM = 0x001B3F70
# FUN_00387C10: player analog/D-pad direction -> camera forward -> movement yaw.
# This call alone is redirected; the shared getter stays native for other users.
MOVE_HOOK = 0x00388140
MOVE_STOCK = (0x0C06D1F0, 0x27A40160)
FUN_FORWARD = 0x001B47C0
# Below ELF min 0x100000, above populated kernel region ending near 0x95060.
# Zero in all supplied states. Runtime refuses occupied resources. This is a
# verified test-scene gap, not a guarantee about every future OS/game allocation.
VIEW_CAVE = 0x000F0000
FOV_CAVE = 0x000F0800
FINISH_CAVE = 0x000F0C00
MOD_BLOCK = 0x000F1000
BLOCK_SIZE = 0x300
MOVE_CAVE = 0x000F1400  # after the control block, within the surveyed 8 KiB gap
MAGIC = 0x52414431  # RAD1
MB_FLAGS = 0x04
MB_SLOT = 0x08
MB_HEARTBEAT = 0x0C
MB_CAMERA = 0x10
MB_APPLIED = 0x14
MB_PENDING = 0x18
MB_LATCH = 0x1C
MB_SAVED_WORLD = 0x40
MB_RENDER_WORLD = 0x80
MB_RENDER_TARGET = 0xC0
MB_SNAPSHOT = 0x200  # guest-owned immutable copy for one render transaction
SLOTS = (0x100, 0x180)
SLOT_WORLD = 0  # row-major orientation; translation is player-relative
SLOT_TARGET = 0x40
SLOT_HALF_FOV = 0x50
SLOT_ACTOR_INDEX = 0x54
SLOT_ACTOR_ID = 0x58
SLOT_SEQUENCE = 0x5C  # odd while host is writing, even when complete
SLOT_FLAGS = 0x60  # ownership travels with the immutable bank, not a later publish
FLAG_ORBIT = 1
FLAG_FOV = 2
STOCK_DISTANCE = 1500.0
STOCK_FOV_DEG = 28.84176
