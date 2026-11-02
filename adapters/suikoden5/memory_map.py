"""Suikoden V (SLPM-66286, Japan) field-camera memory map.

Found with the five savestates (analysis/suikoden5/diff_states.py), GDB write
watchpoints and Ghidra.  Addresses are EE main-memory offsets, as PINE takes them.
The evidence and the function notes are in ``docs/games/suikoden5/CAMERA.md``.

Camera chain (per frame, field):

* ``FUN_00243E10`` is the field camera update.  Its argument is the camera control
  object (``CAM_CTL``).  The object holds the *goal* values: distance (+0x1C), pitch
  (+0x20), yaw (+0x24), FOV (+0x28), near (+0x2C), far (+0x30) and the focus (+0x10).
  The function copies them into the camera globals ``G_*`` and the engine builds the
  camera position from those, so overriding the globals moves the camera, and the
  game's walk code, which reads ``G_YAW``, follows.
* The zoom (R1, or right stick up/down past +-100) is ``FUN_00244150``; the stage is a
  short at CAM_CTL+0x54 (0, 1, 2 -> distance 400, 300, 200).
"""
from __future__ import annotations

# --- identity ---------------------------------------------------------------
GAME_ID = "SLPM-66286"          # Suikoden V (Japan)
DISC_CRC = "7380A572"
REGION = "NTSC-J"

# --- camera globals, rewritten by FUN_00243E10 every frame -------------------
G_BASE = 0x0082DBD0
#: camera focus T = followed actor + offsets (x, y, z); +Y is up in this game
G_FOCUS = 0x0082DBDC
#: camera position P = T - F * distance (x, y, z)
G_EYE = 0x0082DBE8
#: pitch in degrees (stock 13 in the base state; positive = camera above)
G_PITCH = 0x0082DBF4
#: yaw in degrees (stock 244).  The eye offset from T is
#: distance * (cos(p) sin(yaw+180), sin(p), cos(p) cos(yaw+180))
G_YAW = 0x0082DBF8
G_DISTANCE = 0x0082DC00
#: field of view in degrees as last given to FUN_00236F60 (horizontal, 4:3 screen)
G_FOV = 0x0082DC4C

# --- camera control object field offsets (CAM_CTL = argument of FUN_00243E10) ---
CTL_FOCUS = 0x10
CTL_DISTANCE = 0x1C
CTL_PITCH = 0x20
CTL_YAW = 0x24
CTL_FOV = 0x28
CTL_ZOOM_STAGE = 0x54          # short, 0..2
#: R1 / right stick zoom stages: distance and the table the game keeps at +0x7C
ZOOM_DISTANCES = (400.0, 300.0, 200.0)

# --- pad (port 0), written by FUN_00239240 ------------------------------------
PAD_BUTTONS = 0x0082DA08       # u16 held
PAD_PRESSED = 0x0082DA0A       # u16 newly pressed
PAD_LEFT_X, PAD_LEFT_Y = 0x0082DA12, 0x0082DA13   # signed bytes
PAD_RIGHT_X, PAD_RIGHT_Y = 0x0082DA14, 0x0082DA15
PAD_BTN_R1 = 0x0800

# --- stock framing in the base savestate --------------------------------------
STOCK_DISTANCE = 400.0
STOCK_PITCH = 13.0
STOCK_YAW = 244.0
STOCK_FOV = 20.0

# --- hooks (code patches) ------------------------------------------------------
#: ``add.s f2,f3,f2`` followed by the T.x store: replaced by ``j CAVE_CAMERA; nop``
CAM_HOOK = 0x00243F88
CAM_HOOK_WORDS = (0x46021880, 0xE502DBDC)
CAM_RETURN = 0x00243FD8
FUN_FOV = 0x00236F60
FUN_NEARFAR = 0x00236F10

#: ``addiu sp,sp,-0x70`` and ``sll v0,a2,2`` at the entry of the zoom input FUN_00244150
ZOOM_HOOK = 0x00244150
ZOOM_HOOK_WORDS = (0x27BDFF90, 0x00061080)
ZOOM_RETURN = 0x00244158

# --- mod block and caves (zero in the ELF and in all five savestates) -----------
MOD_BLOCK = 0x004BDBA0          # 0x80 bytes of data
CAVE_CAMERA = 0x004BDC40
CAVE_ZOOM = 0x004BDD80
CAVE_END = 0x004BDDC0

# mod block layout (offsets)
MB_MAGIC = 0x00                 # u32 'SU5M'
MB_FLAGS = 0x04                 # u32 bit mask, see FLAG_*
MB_HEARTBEAT = 0x08             # u32, +1 per camera update (cave writes it)
MB_CTL_PTR = 0x0C               # u32, the camera control object (cave writes it)
MB_DISTANCE = 0x10              # f32 overrides, used when the FLAG bit is set
MB_PITCH = 0x14
MB_YAW = 0x18
MB_FOV = 0x1C
MB_OFF_X = 0x20                 # f32 world offsets added to the focus
MB_OFF_Y = 0x24
MB_OFF_Z = 0x28
MB_NATIVE_DISTANCE = 0x2C       # f32 the game's own goal values (cave writes them)
MB_NATIVE_PITCH = 0x30
MB_NATIVE_YAW = 0x34
MB_NATIVE_FOV = 0x38
MB_NATIVE_FOCUS = 0x40          # f32 x3, focus before the mod offset

MAGIC = 0x4D355553              # "SU5M"
FLAG_ANGLES = 0x01              # use MB_PITCH / MB_YAW
FLAG_DISTANCE = 0x02            # use MB_DISTANCE
FLAG_FOV = 0x04                 # use MB_FOV
FLAG_OFFSET = 0x08              # add MB_OFF_* to the focus
FLAG_BLOCK_RSTICK = 0x10        # the zoom input sees the right stick at centre
FLAGS_ORBIT = FLAG_ANGLES | FLAG_DISTANCE | FLAG_OFFSET
