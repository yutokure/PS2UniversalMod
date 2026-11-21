# Suikoden V (SLPM-66286 / CRC 7380A572) — camera analysis and adapter

Everything here was found on the Japanese disc image used by the lab and checked live in PCSX2.
Addresses are EE main-memory offsets (what PINE takes). Game code is not reproduced; only
addresses, function entry points and short descriptions are recorded.

## 1. What the game does

* The field camera is a fixed-angle follow camera. Yaw is a property of the **map**; the right
  stick does **not** rotate it. The camera is `focus T` plus an offset
  `distance * (cos p sin(yaw+180), sin p, cos p cos(yaw+180))`, with `+Y` up, angles in degrees.
* **Zoom** has three stages. `R1` steps 1 → 2 → 3 → 1 (distance 400 → 300 → 200 → 400). The
  right stick also steps the zoom: pushing it past ±100 on Y steps once (edge triggered).
  The zoom is a **pure distance change**; pitch, yaw and FOV do not change (S0 vs S2).
* **Area camera**: the pitch is a function of where the character stands. Walking up the slope
  from the base state eases the pitch from 13° to 40° (that is the S4 savestate). Yaw stays 244°
  in this map. Walking out of the map loads the next field, whose own camera is yaw 200° / pitch
  33°.

## 2. Savestate analysis (S0 base, S1 wait, S2 zoom, S3 moved, S4 camera)

Offline, from the extracted `eeMemory.bin` (`analysis/suikoden5/diff_states.py`,
`summarize.py`; table in `reports/SUIKODEN5_STATE_DIFF.md`):

| pair | changed words | outside the time-only noise |
|---|---|---|
| S0↔S1 | 40 671 | – |
| S0↔S2 | 43 140 | 3 331 |
| S0↔S4 | 68 109 | 27 766 |

S0↔S2 produced the zoom candidates directly: a float that is exactly 400 → 300
(`0x00673F34` in a parameter table, `0x0082DC00` the live distance) and a vector that moves by
(−50, −50, −100). S0↔S4 showed the pitch (13 → 40) with the yaw unchanged, which fixed the
direction formula. The formula reproduces the eye position of all five states exactly (table
in the report).

## 3. Camera chain (found with GDB write watchpoints and Ghidra)

```
FUN_00243E10  (per frame, field)   argument: camera control object  CAM_CTL (heap, 0x0129D7D8 here)
   CAM_CTL+0x10  focus (smoothed follow point)     +0x1C distance   +0x20 pitch   +0x24 yaw
   CAM_CTL+0x28  FOV (deg)  +0x2C near  +0x30 far  +0x34 height offset  +0x54 zoom stage (short)
   -> globals 0x0082DBDC focus T, 0x0082DBF4 pitch, 0x0082DBF8 yaw, 0x0082DC00 distance,
      FUN_00236F60(fov) sets 0x0082DC4C and the viewport object (0x00B3F790)
   -> camera position P at 0x0082DBE8 built from the globals, camera node 0x00B3CED0, view matrix
      cache 0x0099D220 (FUN_003FD1F0), frustum/viewport object 0x00B3F790 (FUN_001B7AE0)
FUN_00244150  zoom input: R1 (pad 0x82DA0A bit 0x800, "pressed") and right stick Y (0x82DA15)
FUN_00239240  pad update, writes 0x0082DA08..0x0082DA17 every frame
```

* Writing the **globals** from outside is useless (rewritten every frame). Writing the goal
  values in `CAM_CTL` (+0x1C/+0x20/+0x24) from outside does move the camera (tested), but the
  zoom animation and the area camera also write them, and the object is heap memory. The robust
  control point is the **store stretch inside FUN_00243E10** (hook `0x00243F88`): it runs after
  those writers in the same frame, and because the walk code reads the yaw *global*, overriding it
  there makes the left stick walk relative to the new camera (checked at two opposite yaws).
* The FOV argument is converted by the game to `sin(fov/2)` for its viewport object (its own
  formula, read back as `0xB3F790+0x68`). The rendering effect was checked by screenshot:
  FOV 20 (stock) and FOV 40 differ by mean pixel difference 21 while stock vs the orbit with
  stock values differs by 0.04.
* Debug camera functions (`FUN_00331C60`, `FUN_002F9380`) exist in the binary but are not used in
  normal play.

## 4. The hook design (adapters/suikoden5/caves.py)

| site | change | purpose |
|---|---|---|
| `0x00243F88/8C` | `j CAVE_CAMERA; nop` | the cave redoes the stretch up to `0x00243FD8` |
| `0x00244150` | `j CAVE_ZOOM` (delay slot = the entry's 2nd word) | right stick bytes → 0 while blocked |
| `0x004BDBA0` | 0x80-byte **mod block** | flags, overrides, heartbeat, CAM_CTL pointer, native values |
| `0x004BDC40`, `0x004BDD80` | cave code | zero in the ELF and in all five states |

The camera cave stores exactly what the game stored when no flag is set (verified live: globals
unchanged by the idle cave). With flags set, `pitch/yaw`, `distance`, `FOV` and a world offset of
the focus come from the mod block. It also publishes the game's own goal values, the CAM_CTL
pointer and a per-frame heartbeat, which the adapter uses to know when the field camera is not
running (loading, events, menus).

### Right stick vs the native zoom

* Mod on: the right stick turns the camera (host side) and the zoom cave presents a centred stick
  to `FUN_00244150`. With the orbit on, neither up nor down changed the zoom stage in the field test.
  The test used PCSX2's keyboard-to-pad mapping, not a physical stick ([input check](../../../tools/su5_input_check.py)).
* `R1` is untouched. In the GUI the *Native zoom* box shows the game's stage; with its checkbox
  on, every R1 step also sets the orbit distance to the stage's value (400/300/200). The three
  stage buttons do the same without R1.
* Mod off: both hooks are removed; the original stick zoom and R1 work again.

### Area camera and event cameras

* With the orbit on, the area pitch/yaw/distance are replaced (absolute values), while the game's
  own values keep changing underneath (`MB_NATIVE_*`). Verified over the slope (13 → 40 native,
  25.00 rendered) and across a map change.
* When the field-camera update stops, the heartbeat freezes; the adapter's guard
  returns "not a field" and the runtime stops writing. The hook stays in place and resumes by
  itself when the update runs again.
* Orbit off: the hook is removed completely (only when no FOV override remains).

## 5. Rejected or ruled-out candidates

| candidate | why not |
|---|---|
| `0x0082DBF8` etc. (globals) | rewritten each frame by FUN_00243E10 |
| `0x00673F34` parameter table | holds the zoom stage value, but writing it does not change the camera |
| `0x00683820`, `0x0099D250` | outputs (eye copy, view translation) |
| `CAM_CTL+0x70..0x7C` | stage preset table, not live |
| debug camera functions | not active in play |

## 6. Open items

* Only field play was tested. The heartbeat guard is not proof that every event, battle or menu is excluded. Use Original outside the field.
* Camera and target offsets shift the focus and move the whole rig; they do not move the eye and target independently. Free Camera is not supported.
* The hook addresses are for this disc (CRC 7380A572); other releases are refused by `identify()`.
* A second PINE client (GUI plus a script) makes PINE time out; run one at a time.
