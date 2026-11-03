"""FFX-2 (SLPS-25250) field-camera memory map.

Discovered by differential analysis of four user savestates plus live PINE /
GDB write+read watchpoints and an automated visual write sweep.  See
``docs/games/ffx2/CAMERA_MEMORY_MAP.md`` for the full evidence trail.

Addresses are EE main-memory (physical) offsets; PINE takes them verbatim.
"""
from __future__ import annotations

# --- identity ---------------------------------------------------------------
GAME_ID = "SLPS-25250"          # FINAL FANTASY X-2 (Japan)
DISC_CRC = "8A6D7F14"
REGION = "NTSC-J"

# --- camera ---------------------------------------------------------------
#: final render camera eye, 4 floats (x, y, z, w).  Written by the game once
#: per frame as  eye = CAM_EYE_BASE + CAM_EYE_OFFSET  (verified with Ghidra:
#: FUN_001b0008 is a VOPS add of the two source vectors).
CAM_EYE = 0x340360
#: the camera position the game's own controller produced this frame.
CAM_EYE_BASE = 0x340370
#: *additive* eye offset applied by the game every frame.  The game only ever
#: writes 0 here, so a value written from outside survives -> this is the
#: race-free injection point used by the runtime.
CAM_EYE_OFFSET = 0x3403E0
#: camera tracking point, NOT a stable actor anchor or the renderer's aim.
#: Its Y includes a scripted-camera height: measured actor Y +5 in base, +1
#: after a camera cut and +10 in other_area_base.  Do not orbit around it.
CAM_TARGET = 0x340380
#: THE look-at point the renderer actually consumes.
#:
#: FUN_001b07a0 is a look-at matrix builder that runs every frame:
#:
#:     FUN_001b07a0(out = 0x33F620, eye = 0x340360, target = 0x33FC10,
#:                  up = 0x33FBC0, roll = f12)
#:     forward = normalize(*0x33FC10 - *0x340360)
#:
#: Verified numerically: with eye = (-0.2669, -25.8528, 125.6269) and
#: 0x33FC10 = (0.3987, 0.0269, 59.5505) the normalised difference reproduces the
#: live render basis forward (0.0094, 0.3647, -0.9311) to five decimals.
#: Writing this address therefore aims the camera; writing CAM_TARGET does not.
CAM_AIM = 0x33FC10
#: dead 16-byte slot used by the main-only look-at cave, so the injected aim
#: survives the game's per-frame rewrite of CAM_AIM.  Verified untouched by
#: the game (a value written here is still there seconds later).
CAM_AIM_SLOT = 0x33FC40
#: up reference handed to the same look-at builder: (0, -1, 0) because FFX-2
#: world +Y points *down*.
CAM_UP_REF = 0x33FBC0
#: secondary copy of the eye used by the depth/shadow pass.
CAM_EYE_SHADOW = 0x3403A0
#: derived camera basis/state block (yaw-ish, pitch-ish, distance-ish).
CAM_STATE = 0x3403B0
#: master projection scale.  NOT rewritten every frame -> safe to poke.
CAM_PROJ_SCALE = 0x340B00
#: 1024.0 constant next to the projection scale (screen centre divisor).
CAM_PROJ_CENTRE = 0x340B30
#: projection centre of the field camera (measured: 1024.0 in the stock field
#: scenes; some areas switch it to 900.0 and the whole image moves off-centre)
STOCK_PROJ_CENTRE = 1024.0
#: the projection source load in the packet loop (EE 0x1A985C).  The stock
#: instruction ``lwc1 $f0,8($s0)`` takes the row's +8 slot, which is the centre
#: (900) in other_area_base, so the FOV scale never reaches the packet there.
#: ``lwc1 $f0,0xF40($s7)`` reads the current bank's scale instead (CAM_PROJ_SCALE
#: for the main bank).  This is bank-relative, not an absolute main-only load.
#: Only the runtime changes the instruction, while the orbit is active.
PROJ_SOURCE_LOAD = 0x001A985C
PROJ_SOURCE_STOCK = 0xC6000008      # lwc1 $f0,8($s0)
PROJ_SOURCE_REDIRECT = 0xC6E00F40   # lwc1 $f0,0xF40($s7)  (0x340B00)

#: the camera basis the renderer is actually using: right, up, forward, eye.
#: Rows of a rotation-only view matrix followed by the eye position.
CAM_BASIS = 0x53AD80
CAM_BASIS_RIGHT = 0x53AD80
CAM_BASIS_UP = 0x53AD90
CAM_BASIS_FWD = 0x53ADA0
CAM_BASIS_EYE = 0x53ADB0
#: render look-at derived from the basis (kept for reference).
CAM_BASIS_LOOK = 0x53ADD0

# --- player ---------------------------------------------------------------
#: actor/party anchor: x, y, z, w, also used by the auxiliary depth camera.
#: Unlike CAM_TARGET, its Y stays fixed when only the scripted camera changes.
PLAYER_ANCHOR = 0x3312D0
#: Fixed calibration to preserve the old normal-field framing and saved
#: look_height values: the former anchor CAM_TARGET was actor Y +5 in base.
#: Never derive this from the live camera, which changes it at camera cuts.
ORBIT_ANCHOR_Y_OFFSET = 5.0

# --- compatibility name for the formerly auxiliary read-only probe ---------
PLAYER_ANCHOR_ALT = PLAYER_ANCHOR


# --- internals discovered along the way ------------------------------------
#: function that rebuilds the depth/auxiliary camera (yaw/pitch at +0x30).
FN_DEPTH_CAMERA = 0x0011C3D8
#: code that stores the depth-camera matrix rows (sq to +0x30).
FN_DEPTH_CAMERA_MATRIX = 0x001B08A8
#: code that builds the projection packet from CAM_PROJ_SCALE.
FN_PROJECTION_PACKET = 0x001B0908
#: shared look-at matrix builder.  It reads eye, look-at point and up and stores
#: a world->view matrix at the supplied output (0x33F620 for the main camera).
FN_LOOKAT_BUILD = 0x001B07A0
#: Legacy global load redirection.  This shared builder also serves the minimap
#: and stack-local cameras; adding 0x30 here corrupted their targets.  Always
#: restore this known legacy patch to stock, never apply it in new runtimes.
LOOKAT_LOAD_SITE = 0x001B07FC
LOOKAT_LOAD_STOCK = 0xDA250000
LOOKAT_LOAD_PATCHED = 0xDA250030
#: Main field call site.  Keep its argument-building delay slot unchanged and
#: route through a conditional cave instead of modifying the shared builder.
CAM_VIEW_MATRIX = 0x33F620
LOOKAT_CALL = 0x001AE0F0
LOOKAT_CALL_STOCK = 0x0C06C1E8       # jal FUN_001B07A0
LOOKAT_CALL_DELAY = 0x24C60050       # addiu a2,a2,0x50
LOOKAT_CAVE = 0x00080000            # zero in four ship-state dumps and live Luka
LOOKAT_CALL_PATCHED = 0x0C020000    # jal LOOKAT_CAVE

# --- runtime-owned stock camera hook (formerly an external cheat) -----------
# The field camera routine FUN_001B0388 builds the eye as
#   centre + (sin yaw cos p, -sin p, cos yaw cos p) * dist
# and takes yaw, -pitch, dist and the centre from the camera struct at
# CAM_STRUCT.  PATCH_WORDS retargets those loads to the slots below, which the
# mod owns; the game never writes them.  The stock blend keeps writing
# CAM_STRUCT+0x60.. and the runtime copies those values into the slots whenever
# the orbit is off, so the stock camera is unchanged in that case.
CAM_STRUCT = 0x340350
STOCK_YAW_OUT = CAM_STRUCT + 0x60        # blend output: yaw (rad)
STOCK_NPITCH_OUT = CAM_STRUCT + 0x64     # blend output: -pitch (rad)
STOCK_DIST_OUT = CAM_STRUCT + 0x68       # blend output: distance
STOCK_CENTRE_PTR = CAM_STRUCT + 0x8C     # pointer to the stock look-at vec4
ORBIT_YAW_SLOT = CAM_STRUCT + 0x70       # 0x3403C0
ORBIT_NPITCH_SLOT = CAM_STRUCT + 0x74    # 0x3403C4
ORBIT_DIST_SLOT = CAM_STRUCT + 0x78      # 0x3403C8
ORBIT_CENTRE = CAM_STRUCT + 0xA0         # 0x3403F0, vec4 (x, y, z, w)
#: look-at target the stock walk is aimed by.  The walk direction is
#: normalize(target - eye) in the horizontal plane (measured: a target rotated
#: 90 deg moved the walk heading by about 60 deg straight away).  The game copies
#: it from the lerped centre each frame, so the runtime re-writes it every tick
#: while the orbit is active and the game's own value returns once it stops.
WALK_TARGET = 0x0033FC20
#: yaw slot = ORBIT_YAW_OFFSET_DEG - orbit yaw.  Measured with the stock eye:
#: slot 90.65 deg gave an eye angle of -0.8 deg, so the constant is 89.85 deg.
ORBIT_YAW_OFFSET_DEG = 89.85
#: (address, expected word) of the patched loads; all must match for the hook
HOOK_CHECK = ((0x001A9604, 0xC62C0070), (0x001A960C, 0xC62D0074),
              (0x001A9614, 0xC62E0078), (0x001AC7C8, 0xC60C0070))

#: every word the look-at redirection and the stock-camera hook change, as
#: (address, stock word, applied word).  The stock words were read from
#: sstates/base.p2s before any patch was applied.  The mod writes these itself:
#: the applied form while the orbit or free camera is in use, the stock form in
#: the original camera mode (see engine.CameraRuntime._sync_patch).  The old
#: implementation used external cheats with a global look-at patch instead.
PATCH_WORDS = (
    (LOOKAT_CALL, LOOKAT_CALL_STOCK, LOOKAT_CALL_PATCHED),  # main-only look-at cave
    (0x001A9600, 0x8E25008C, 0x262500A0),   # centre pointer -> ORBIT_CENTRE
    (0x001A9604, 0xC62C0060, 0xC62C0070),   # yaw slot
    (0x001A960C, 0xC62D0064, 0xC62D0074),   # -pitch slot
    (0x001A9614, 0xC62E0068, 0xC62E0078),   # distance slot
    (0x001A967C, 0x8E25008C, 0x262500A0),   # centre pointer (second call site)
    (0x001A9684, 0xC62C0060, 0xC62C0070),   # yaw slot (second call site)
    (0x001A9688, 0xC62D0064, 0xC62D0074),   # -pitch slot (second call site)
    (0x001A9690, 0xC62E0068, 0xC62E0078),   # distance slot (second call site)
    (0x001AC7C0, 0x8E05008C, 0x260500A0),   # centre pointer (third call site)
    (0x001AC7C8, 0xC60C0060, 0xC60C0070),   # yaw slot (third call site)
    (0x001AC7CC, 0xC60D0064, 0xC60D0074),   # -pitch slot (third call site)
    (0x001AC7D4, 0xC60E0068, 0xC60E0078),   # distance slot (third call site)
)


def describe() -> dict:
    return {
        "game_id": GAME_ID,
        "disc_crc": DISC_CRC,
        "region": REGION,
        "camera": {
            "eye": hex(CAM_EYE),
            "aim": hex(CAM_AIM),
            "target": hex(CAM_TARGET),
            "proj_scale": hex(CAM_PROJ_SCALE),
        },
        "player": {"anchor": hex(PLAYER_ANCHOR)},
    }
