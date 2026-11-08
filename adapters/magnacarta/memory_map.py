"""SLPS-25401 / EB925207, six user states plus live watchpoints/Ghidra.

Native XY ground, Z up; the adapter exposes canonical (X,-Z,Y).
Addresses are specific to this Japanese executable, never shared through core.
"""
GAME_ID = 'SLPS-25401'
DISC_CRC = 'EB925207'
PLAYER_GLOBAL = 0x53B868
FIELD_OWNER_GLOBAL = 0x5527BC  # native manager registry 0x5527B0[3], DataManager
# 0x56DB1C is UObject's name-hash bucket[D53], NOT a GameMagi global.
# Reflection-confirmed ownership properties; follow the current pawn each time.
PLAYER_MAGI = 0x3E4
MAGI_OWNER = 0x220
OWNER_MAGI = 0x7D4
PLAYER_CONTROLLER = 0x1EC
FIELD_SCRIPT_NAMES = (0x31CC, 0x31D3)
PLAYER_POSITION = 0xD0
STATE_POINTER = 0x330
STATE_MODE = 0x91
FIELD_MODES = (1, 2)  # Sampled selector: running=1, walking=2; not script-state names.
CAMERA_EYE = 0x5808D0
VIEW_MATRIX = 0x57FC90
RENDER_HOOK = 0x2B3B7C
RENDER_STOCK = (0x0C0AF52C, 0x27A80BB8)
RENDER_NATIVE = 0x2BD4B0
BOOT_SITE = 0x505C84  # native render virtual method data pointer
BOOT_NATIVE = 0x2B3940
BOOT_CAVE = 0xF5000
RENDER_CAVE = 0xF6000
MOD_BLOCK = 0xFF000
BLOCK_SIZE = 0x400
MAGIC = 0x4D434131  # MCA1
FLAG_ORBIT = 1
FLAG_FOV = 2
FLAG_WIDE = 4
FLAG_NO_ENCOUNTERS = 8
MB_FLAGS = 4
MB_SLOT = 8
MB_HEARTBEAT = 12
MB_APPLIED = 16
MB_COMMAND = 20
MB_ACK_FLAGS = 24
MB_ACCEPTED = 28
MB_RENDER_EYE = 0x20
MB_RENDER_TARGET = 0x30
MB_NATIVE_EYE = 0x40
MB_NATIVE_ROTATION = 0x50
MB_NATIVE_FOV = 0x60
MB_RENDER_FOV = 0x64
MB_SNAPSHOT = 0x100
SLOTS = (0x200, 0x280)
SLOT_SEQUENCE = 0
SLOT_FLAGS = 4
SLOT_PLAYER = 12
SLOT_EYE = 0x10
SLOT_TARGET = 0x20
SLOT_PITCH = 0x30
SLOT_ROT_YAW = 0x34
SLOT_YAW = 0x38  # actual sight yaw, consumed only by movement
SLOT_FOV = 0x3C
CMD_SYNC = 1
CMD_ACK = 2
CMD_CONFLICT = 3
