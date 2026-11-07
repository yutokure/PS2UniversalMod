"""Innocent Life Japanese SLPS-25763 / 9AC21F92, EE physical addresses.

Parent-supplied live/Ghidra findings, November 2026. The allocation below was
zero in four protected states and lies below the game's lowest ELF mapping.
It is still a conditional allocation: exact-code/empty preflight is mandatory.
"""
GAME_ID = "SLPS-25763"
DISC_CRC = "9AC21F92"

CAMERA = CAM_EYE = 0x1BA400
CAMERA_SIZE = 0xA0
CAM_PITCH = CAMERA + 0x10
CAM_YAW = CAMERA + 0x14
CAM_ROLL = CAMERA + 0x18
CAM_LOOK_HEIGHT = CAMERA + 0x54
CAM_FOCAL = CAMERA + 0x7C
CAM_FLAGS = CAMERA + 0x80
CAM_FORWARD = CAMERA + 0xA0
VIEW = 0x207210
PROJECTION = 0x2071D0  # screen-space perspective; m00=focal*X factor
PROJECTION_X_FACTOR = 0x236A30  # native builder argument, normally 0.79999995
PROJECTION_Y_FACTOR = 0x236A34
SCREEN_HALF_WIDTH = 256.0  # 512x448 render target / GS scissor, not display aspect
CAMERA_PTR = 0x2372C0
CAMERA_TARGET_PTR = 0x2372C4
PLAYER_PTR = 0x2372E8
ALTERNATE_PLAYER_PTR = 0x2372F0
PLAYER = 0x1BA640
PLAYER_RECORD = 0x2C
PLAYER_FLAGS = 0x30  # bit 2 is transient input: idle 0xBC, walking 0xBE; NOT a scene guard
RECORD_POSITION_PTR = 4
EVENT_GUARD = 0x1E1E8C
FIELD_OWNER = 0x21A348
NATIVE_FLAGS = 0x2382C0
NATIVE_REJECT_MASK = 0x28008
INPUT_GUARD_BYTE = 0x1BE6C8
INPUT_REJECT_MASK = 0x20
EXACT_GUARDS = ((CAMERA_PTR, CAMERA), (PLAYER_PTR, PLAYER), (CAM_FLAGS, 8),
                (EVENT_GUARD, 0), (CAMERA_TARGET_PTR, 0), (ALTERNATE_PLAYER_PTR, 0))

FUN_BUILD_VIEW = 0x1029E8
RENDER_HOOK = 0x1695F0
RENDER_STOCK = (0x0C040A7A, 0x8F8488D0)
# Hook the load pair BEFORE the jal, never put a jal in a jump delay slot.
MOVE_HOOK = 0x104E9C
MOVE_STOCK = (0x8F8288D0, 0xC44C0014)
MOVE_CONTINUE = 0x104EA4
MOVE_CONTINUE_STOCK = 0x0C05CC02
CAMERA_GP_OFFSET = -0x7730
CLOCK_HOOK = 0x121D84
CLOCK_STOCK = 0x00002012  # mflo a0: elapsed seconds, not the clock's baseline
CLOCK_PAUSED = 0x0000202D  # move a0, zero
CLOCK_HOURS = 0x1BE7DC
CLOCK_MINUTES = CLOCK_HOURS + 4
CLOCK_SECONDS = CLOCK_HOURS + 8

RENDER_CAVE = 0xA8000
MOVE_CAVE = 0xA9000
MOD_BLOCK = 0xAA000
BLOCK_SIZE = 0x800
RESERVED_END = 0xAC000
MAGIC = 0x494C4332  # ILC2: copied-camera FOV bank; old cave layouts are not adopted
FLAG_ORBIT = 1
FLAG_TIME = 2
ALL_FLAGS = FLAG_ORBIT | FLAG_TIME
FLAG_FOV = 4  # bank/render diagnostic only; never a standalone lifecycle lane
MB_FLAGS = 0x04  # desired mask, host publication
MB_ACK_FLAGS = 0x08  # last successful guest lifecycle mask
MB_SLOT = 0x0C
MB_COMMAND = 0x10
MB_APPLIED = 0x14  # this render used Orbit plus optional bank FLAG_FOV
MB_PENDING = 0x18  # guest-only render transaction latch
MB_HEARTBEAT = 0x1C
MB_RENDER_EYE = 0x20
MB_RENDER_TARGET = 0x30
MB_SAVED_FORWARD = 0x40
MB_SNAPSHOT = 0x80
CMD_IDLE = 0
CMD_SYNC = 1
CMD_ACK = 2
CMD_CONFLICT = 3
SLOTS = (0x200, 0x280)
SLOT_SIZE = 0x80
SLOT_SEQUENCE = 0x00
SLOT_FLAGS = 0x04
SLOT_PLAYER = 0x08
SLOT_POSITION = 0x0C
SLOT_EYE = 0x10
SLOT_TARGET = 0x20
SLOT_PITCH = 0x30  # native rotation: -core pitch for a plain Orbit
SLOT_YAW = 0x34  # atan2(actual target-eye X, Z), also consumed by movement
SLOT_FOCAL = 0x38  # native focal input, used only when bank FLAG_FOV is set
MB_CAMERA_SCRATCH = 0x400

STOCK_DISTANCE = 90.0
STOCK_LOOK_HEIGHT = -15.0  # Y down: negative raises the target
STOCK_PITCH_DEG = 35.0
STOCK_YAW_DEG = 180.0
STOCK_FOCAL = 443.40506
STOCK_FOV_DEG = 71.635051  # 2*atan(256/(443.40506*0.79999995)), horizontal
