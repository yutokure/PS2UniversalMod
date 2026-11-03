"""Shining Force Exa NTSC-J addresses, independently checked on 2026-11-03.

Four supplied states, EE watchpoints, Ghidra and live render/read-back establish
these values. See docs/games/shiningforceexa/CAMERA.md. No Neo address is used.
"""
GAME_ID = "SLPM-66646"
DISC_CRC = "8B383FDF"
REGION = "NTSC-J"

# FUN_001d9da0 dispatch / FUN_001daad0 party focus. Persistent camera allocation
# was identical in the four supplied states; refuse a different active pointer.
CAM_ACTIVE_PTR = 0x00451144
CAM_STRUCT = 0x010FE800
CAM_EYE = CAM_STRUCT
CAM_FOCUS = CAM_STRUCT + 0x10
CAM_VIEW = CAM_STRUCT + 0x20
CAM_VP = CAM_STRUCT + 0x60
CAM_FOV_OUTPUT = CAM_STRUCT + 0xA2
CAM_ASPECT = CAM_STRUCT + 0xAC
CAM_MODE = CAM_STRUCT + 0x140
CAM_FOCUS_MODE = CAM_STRUCT + 0x144
FIELD_CAMERA_MODES = (0, 1)
PARTY_FOCUS_MODE = 0
CAM_HEIGHT = CAM_STRUCT + 0x158
CAM_DISTANCE = CAM_STRUCT + 0x184
CAM_YAW = CAM_STRUCT + 0x188
CAM_PITCH = CAM_STRUCT + 0x18A
CAM_YAW_WORD = CAM_YAW
CAM_FOV = CAM_STRUCT + 0x18E       # vertical angle, 65536 units per turn
CAM_FOV_WORD = CAM_FOV & ~3       # preserve the roll halfword at +0x18C
PARTY_ACTOR_PTR = 0x00451140
PARTY_POS_OFFSET = 0x520          # Neo uses +0x510, NOT valid for Exa
PARTY_POS = 0x00C65DA0            # measured baseline only; read the pointer at runtime
ANGLE_UNITS_PER_DEG = 65536.0 / 360.0
YAW_FIELD_OFFSET_DEG = 180.0
STOCK_DISTANCE_GAME = 1000.0
STOCK_HEIGHT = 250.0
STOCK_PROJ_SX = 1.9234572649002075
PROJ_ASPECT = 640.0 / 448.0

# FUN_00295c80 gates FUN_00295cf0 -> FUN_00295ac0, which publishes all
# five camera parameters (including vertical FOV), not just yaw.
SMOOTH_GATE_BLOCK = 0x004D29C0
SMOOTH_GATE = SMOOTH_GATE_BLOCK + 0x16
SMOOTH_GATE_WORD = SMOOTH_GATE & ~3
SMOOTH_GATE_SHIFT = 8 * (SMOOTH_GATE - SMOOTH_GATE_WORD)
SMOOTH_GATE_STOCK = 1
SMOOTH_GATE_APPLIED = 0

# FUN_001ad240 copies only the right-stick axes into processed pad fields.
# Replace these two lbu instructions with li v0,127. Buttons / left stick and
# the raw packet stay untouched, for both pad slots through the shared function.
PAD_RX_LOAD = 0x001AD27C
PAD_RY_LOAD = 0x001AD290
PAD_RX_WORD = 0x92620166
PAD_RY_WORD = 0x92620167
PAD_NEUTRAL_WORD = 0x2402007F
PAD_CENTRE = 0x7F
PAD_ROOT = 0x00493600
PAD_SLOT_STRIDE = 0x180
PAD_RX_SOURCES = (PAD_ROOT + 0x1E, PAD_ROOT + 0x9E)
PAD_PROCESSED = PAD_ROOT + 0x148

# Analysis landmarks, never patched by this adapter. Projection is controlled
# at its original input instead of modifying this shared field/map VP call.
VP_LOAD_CALL = 0x001ABE98
VP_LOAD_WORD = 0x0C06B128
VP_LOAD_TARGET = 0x001AC4A0
PAD_CALL_SITE = 0x00123C6C
PAD_CALL_WORD = 0x90A20000
