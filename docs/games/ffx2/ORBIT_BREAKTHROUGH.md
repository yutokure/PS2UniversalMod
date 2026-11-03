# Yuna-centred orbit — root cause and fix (2026-10-31)

Status at the recorded date: **working**. Right-stick / GUI orbit around Yuna
with the camera aimed at her, no flicker, no per-frame writes in the idle hold test.

**2026-11-02 update:** the shared-builder `.pnach` described below is historical,
not the current installation method. The runtime now redirects only the main
camera call at `0x001AE0F0` through a conditional cave, leaving `0x001B07FC`
stock so minimap/auxiliary cameras retain their own targets. Orbit uses the actor
anchor plus a fixed Y calibration, not the scripted camera's tracking height.
See the [current correction and validation](<CAMERA_MEMORY_MAP.md#2026-11-02-訂正-演出カメラ切替時の-orbit-高さ>).

## 1. Why every earlier attempt failed

The field camera looks like it stores its orientation in several places
(`0x53AD80` basis, `0x33F620` view matrix, `0x3403B0` yaw/pitch, `0x3312F0`
auxiliary orbit solver). Writing any of them changed nothing, because all of them
are *outputs*: mirrors recomputed from other values, and the real renderer never
reads them back.

Two measurements explain the dead ends:

* `0x1A9610` (`jal FUN_001b0388`, the yaw/pitch -> position conversion) is
  **unreachable in field state**. `0x1A9568` loads `puVar16[1]` (= 0) and branches
  to `0x1A95F4`, skipping the load of `$s5` at `0x1A9570`; the guard at
  `0x1A95F8` then compares the stale `$s5` against 1 and always branches away.
  NOP-ing it makes the call run, but the function is a one-shot "dolly the eye
  back by `dist`" initialiser: each call moves the eye by exactly `dist`
  (measured |delta| = 70.9669 = `dist`, direction = `-forward`), so it must stay
  disabled.
* The orbit solver at `FUN_0011c3d8` (`0x3312F0/0x3312F4` + `0x480EC4`,
  centre `0x3312D0`) is **live and reacts** to writes (eye = centre + dir*dist,
  verified |eye-centre| = 50.003), but its output `0x3312C0` is not what the
  renderer consumes.

## 2. What the renderer actually consumes

Read watchpoint on `0x340360` landed on `0x001B07F8`, inside `FUN_001b07a0`,
which is a **look-at matrix builder called every frame**:

```
0x1B07F8  lqc2 vf4, 0x00($s2)    ; s2 = 0x340360  eye
0x1B07FC  lqc2 vf5, 0x00($s1)    ; s1 = 0x33FC10  look-at point
0x1B0800  lqc2 vf8, 0x00($s0)    ; s0 = 0x33FBC0  up = (0, -1, 0)
```

so

```
forward = normalize(*0x33FC10 - *0x340360)
```

Verified numerically to five decimals:

| quantity | value |
|---|---|
| eye `0x340360` | (-0.266901, -25.852787, 125.626915) |
| aim `0x33FC10` | (0.398717, 0.026899, 59.550465) |
| normalize(aim - eye) | (0.00938, 0.36467, -0.93109) |
| live render basis `0x53ADA0` | (0.00938, 0.36467, -0.93109) |

`0x33FBC0` is `(0, -1, 0)`: FFX-2 world **+Y points down**.

Writing `0x33FC10` alone rotates the view (`reports/hook/05_aim_player.png`);
writing `0x340360` alone moves it (`reports/hook/07_eye_only.png`).

## 3. Why it flickered, and the fix

Both words are rewritten by the game **every frame** — a value written from
outside is gone within 50 ms (`tools/probe_revert.py`). Blind overwriting at
~800 Hz therefore loses the race on some frames and the screen alternates
between the stock camera and the injected one (measured: two consecutive frames
differed by mean 46.4 / frac>40 = 0.328).

The fix removes the race entirely instead of trying to win it:

1. **Eye — the engine writes it for us.** `0x340360 = 0x340370 + 0x3403E0` every
   frame and the game never touches `0x3403E0`, so publishing the *offset*
   `target_eye - base` makes the engine place the eye exactly where we want.
2. **Aim — move the read.** `.pnach` patch
   `patch=1,EE,001B07FC,word,DA250030` changes the 16-bit offset of the look-at
   load from `0x00` to `0x30`, i.e. from `0x33FC10` (rewritten each frame) to
   `0x33FC40` (a dead slot the game never writes — verified to survive intact
   for seconds).

With both in place nothing needs rewriting per frame: a write happens only when
the pose changes or when the player walks and the base position moves.

## 4. Evidence

| file | content |
|---|---|
| `hook/05_aim_player.png` | eye unchanged, aim = Yuna -> she is centred |
| `hook/07_eye_only.png` | aim unchanged, eye moved -> viewpoint moves |
| `hook/30_static_aim.png` | static injection, Yuna dead centre |
| `hook/31_static_orbit50_a.png` | +50 deg orbit, one write total |
| `hook/40_product_a.png` | same through `CameraRuntime` (the shipped path) |

Flicker metric (mean abs pixel difference between two consecutive captures):

| state | mean | frac > 40 |
|---|---|---|
| stock camera, idle | 1.07 - 1.45 | 0.005 - 0.007 |
| 800 Hz overwrite (old) | **46.4** | **0.328** |
| static injection (new) | **0.50 - 0.56** | **0.002** |

Runtime write rate during a 35 s hold: **1 write** (`writes/sec=1`), against
~800/s before.

## 5. Operation (current, updated 2026-11-02)

Use the GUI's Orbit / Free Camera modes. The runtime installs and removes the
look-at and stock-camera hooks through the guarded PINE backend; an external
`.pnach` and `EnableCheats` are not required. Remove any old external global
look-at or stock-hook definitions before using this version, since reapplying
them conflicts with runtime ownership. See the [usage guide](<../../../README.md#51-ffx-2>).

Original mode and normal shutdown restore stock call sites and clear the eye
offset. `CameraRuntime.restore()` also mirrors the game's current aim into
`0x33FC40` and releases projection overrides. Forced process termination cannot
perform this restoration.

## 6. Address summary

| address | meaning |
|---|---|
| `0x340360` | render eye (`= 0x340370 + 0x3403E0`) |
| `0x340370` | base eye produced by the game's controller |
| `0x340380` | camera tracking point; Y includes a variable scripted height (corrected 2026-11-02) |
| `0x3312D0` | actor anchor; current Orbit uses this + fixed `(0,5,0)` to preserve normal-field settings |
| `0x33FC10` | look-at point the engine rewrites every frame |
| `0x33FC40` | **dead slot used by the patched load** |
| `0x33FBC0` | up reference `(0, -1, 0)` |
| `0x3403E0` | additive eye offset (never written by the game) |
| `0x340B00` | projection scale (619.0 = 54.68 deg) |
| `0x001B07A0` | shared look-at matrix builder (stock; old global patch retired) |
| `0x001AE0F0` / `0x00080000` | runtime-owned main call redirect / conditional look-at cave |
