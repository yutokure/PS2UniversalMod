"""Shining Force Neo (SLPM-65908) field-camera memory map.

Found with a savestate diff (base.p2s), GDB write watchpoints and Ghidra
(functions FUN_001D6160, FUN_0027D540, FUN_0027D310, FUN_001D70E0).  Addresses are
EE main-memory (physical) offsets, as PINE takes them.  Evidence: see
work/sf_neo_analysis/*.py and the notes in the project memory.

The field camera is a heap structure at CAM_STRUCT.  Its controller (FUN_001D6160)
rebuilds the eye and focus every frame from the yaw, pitch and distance fields below,
so the orbit writes those three fields rather than the eye.  A smoothing routine
(FUN_0027D540) normally drags the yaw toward a desired value and also runs the
scripted gate camera; it runs only while SMOOTH_GATE is non-zero.
"""
from __future__ import annotations

# --- identity ---------------------------------------------------------------
GAME_ID = "SLPM-65908"          # Shining Force Neo (Japan)
DISC_CRC = "64F241D2"
REGION = "NTSC-J"

# --- field camera structure (heap) -------------------------------------------
CAM_STRUCT = 0x01104900
#: eye position (x, y, z, w), written by the controller every frame
CAM_EYE = CAM_STRUCT + 0x00
#: focus / look-at point (x, y, z, w) = the party point the camera circles
CAM_FOCUS = CAM_STRUCT + 0x10
#: view matrix the renderer uses (rows at +0x20, translation in row 3)
CAM_VIEW = CAM_STRUCT + 0x20
#: view-projection (row-vector convention, v x VP)
CAM_VP = CAM_STRUCT + 0x60
#: orbit distance from the focus, float.  Stock 2000.0 in the base savestate.
CAM_DISTANCE = CAM_STRUCT + 0x184
#: yaw, short: eye yaw in degrees = yaw / 182.04445 + 180 (stock field -50 deg)
CAM_YAW = CAM_STRUCT + 0x188
#: pitch, short, in units of 65536 per turn (stock -5093 = -28 deg).  Same
#: halfword pair as CAM_YAW, so one 32-bit write sets both (little-endian).
CAM_PITCH = CAM_STRUCT + 0x18A
#: 32-bit word covering CAM_YAW (low half) and CAM_PITCH (high half)
CAM_YAW_WORD = CAM_YAW

# --- smoothing gate ----------------------------------------------------------
#: state block of FUN_0027D540 (DAT_00478360).  Byte +0x16 enables the per-frame
#: yaw smoothing and the scripted gate camera.  Stock 1.  0 disables both: the
#: yaw written to CAM_YAW then persists, and the gate camera does not fire.
SMOOTH_GATE_BLOCK = 0x00478360
SMOOTH_GATE = SMOOTH_GATE_BLOCK + 0x16
SMOOTH_GATE_STOCK = 1
SMOOTH_GATE_APPLIED = 0
#: the word that contains SMOOTH_GATE (aligned), used for the read-modify-write
SMOOTH_GATE_WORD = SMOOTH_GATE & ~3
SMOOTH_GATE_SHIFT = 8 * (SMOOTH_GATE - SMOOTH_GATE_WORD)

# --- mod scratch -------------------------------------------------------------
#: The engine publishes eye offsets and aim points in its offset-injection path,
#: which this game does not use.  Those writes go to these slots, which the game
#: never reads (verified static and zero across frames in the base savestate).
SCRATCH_EYE = CAM_STRUCT + 0xE0          # 16 bytes
SCRATCH_EYE_OFFSET = CAM_STRUCT + 0xF0   # 16 bytes
SCRATCH_AIM = CAM_STRUCT + 0x100         # 16 bytes

# --- stock values (base savestate) -------------------------------------------
STOCK_DISTANCE = 2000.0
STOCK_YAW_FIELD_DEG = -49.981            # CAM_YAW as degrees (short / 182.04445)
STOCK_PITCH_DEG = -27.981
#: eye yaw = field yaw + 180 deg; the controller passes (yaw - 0x8000) to its rotation
YAW_FIELD_OFFSET_DEG = 180.0
#: engine yaw/pitch are atan2 of the eye offset; these convert to the 65536-per-turn units
ANGLE_UNITS_PER_DEG = 65536.0 / 360.0
#: the value at CAM_FOCUS is the party point plus 100 on Y (base: -666.35 vs party -766.35)
FOCUS_HEIGHT = 100.0
#: the focus height the controller uses: focus = party point + this float, every frame.
#: The scripted event camera also writes it (280 in the gate state), so it is a real field.
CAM_HEIGHT = CAM_STRUCT + 0x158
STOCK_HEIGHT = FOCUS_HEIGHT
#: the party point: x, y, z floats of the camera actor (slot 0 at 0x00BB7280, +0x510).
#: In every savestate checked, focus = this point + (0, CAM_HEIGHT, 0).  The orbit never
#: writes it, so it is the stable anchor for the orbit centre.
PARTY_POS = 0x00BB7280 + 0x510
#: field camera distance in the base savestate and the distance the orbit starts from
STOCK_DISTANCE_GAME = 2000.0

# --- projection (field of view) -----------------------------------------------
#: The view-projection at CAM_VP is built each frame by FUN_001A9900 and loaded into the
#: VU by FUN_001AA080, called at VP_LOAD_CALL (delay slot 0x001A9A2C is a store the cave
#: keeps).  Columns 0 and 1 carry the x and y projection scales.
VP_LOAD_CALL = 0x001A9A28
VP_LOAD_WORD = 0x0C06A820       # jal 0x001AA080
VP_LOAD_TARGET = 0x001AA080
VP_LOAD_RETURN = 0x001A9A30
#: the eight floats of columns 0 and 1 (row-major 4x4 at CAM_VP)
VP_COLUMN_OFFSETS = (0, 4, 16, 20, 32, 36, 48, 52)
#: column-0 norm in the base savestate: sx = 1 / tan(horizontal FOV / 2)
STOCK_PROJ_SX = 3.6020894
#: screen 640 x 448, so sy / sx = 640 / 448 (the base values 5.1458420 / 3.6020894)
PROJ_ASPECT = 640.0 / 448.0
#: mod-owned code cave and its parameter block (zero in the base savestate)
FOV_CAVE = 0x00356780
FOV_BLOCK = 0x00356700
FOV_BLOCK_RATIO = FOV_BLOCK            # f32: scale factor applied to columns 0 and 1
FOV_BLOCK_FLAG = FOV_BLOCK + 8         # u32: 1 while the cave applies the ratio

#: right-stick mask.  The game copies its pad packet byte by byte in a loop; the load at
#: PAD_CALL_SITE (``lbu v0,0(a1)``) reads the packet.  While PAD_BLOCK_FLAG is set (orbit on)
#: the cave at PAD_CAVE copies the centre value for the right-stick bytes (X, and Y at +1).
PAD_CALL_SITE = 0x0011EEDC
PAD_CALL_WORD = 0x90A20000            # lbu v0,0(a1)
PAD_RETURN = 0x0011EEE8               # sb v0,0(v1): the cave returns here
PAD_RX_SOURCES = (0x0043FE9E, 0x0043FF1E)   # right-stick X byte of the two packet copies
PAD_CENTRE = 0x7F
# The FOV cave is 38 words from FOV_CAVE, so it ends at 0x00356818.  The pad cave starts
# after it; overlapping the two made whichever was installed second refuse to install.
PAD_CAVE = 0x00356820
PAD_BLOCK_FLAG = FOV_BLOCK + 0x0C     # u32: 1 while the cave masks the right stick
