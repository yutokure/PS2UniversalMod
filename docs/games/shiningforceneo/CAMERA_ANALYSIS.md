# Shining Force Neo (SLPM-65908 / CRC 64F241D2) — camera analysis and adapter

Written from the analysis notes of 2026-11-01 (they had only lived in the working notes and the
adapter source until now). Addresses are EE main-memory offsets. The adapter is
`adapters/shiningforceneo/` (`memory_map.py`, `adapter.py`, `fov_cave.py`, `pad_cave.py`).

## 1. Game behaviour

* The field camera follows the character when it walks (walking down moves the view a little).
* A long walk down-right (stick (0.7, −0.7) for about 5 s from `base.p2s`) ends on a bridge where the
  camera jumps into a **scripted (event) camera** that then stays fixed (the town-gate view: the
  `chara_and_cam_and_camFOV_bigger_changed_from_base` state). Stick (0, −1) for 16 s does not trigger it.
* Camera control is an engine/scripted camera, not user input; the right stick does not move it.
* Walking needs the **left stick**; the D-pad does not move the character (D-pad walk tests are invalid).

## 2. Camera chain

| item | where |
|---|---|
| camera controller | heap struct `CAM_STRUCT` 0x01104900; controller `FUN_001D6160` builds eye and focus every frame |
| eye / focus | `CAM_STRUCT+0x00` / `+0x10` |
| yaw / pitch / distance | short at `+0x188` (`yaw − 180`, 182.04 units per degree), short at `+0x18A`, float at `+0x184` (stock 2000) |
| focus height | float `+0x158` (stock 100, event 280); focus = party point + height; +Y is up |
| view-projection | `+0x60`; loaded by `FUN_001AA080` (called from `FUN_001A9990`) |
| yaw writers | `FUN_001D70E0` ← `FUN_0027D310` ← `FUN_0027D540` (every frame, only while the byte `0x00478376` is non-zero) |

`FUN_0027D540` eases the yaw towards a desired value (at most 0.8°/frame) **and** runs the scripted
gate camera. So a write to the yaw field reverts within a few frames, unless the gate byte is 0.

## 3. What the adapter does

* **Orbit**: clear the gate byte `0x00478376` once (compare-and-swap), then write the yaw+pitch word
  and the distance; the yaw persists, the focus stays at screen centre, the eye stays at the distance.
  With the gate off the scripted gate camera is suppressed as well (verified: the same walk ends at
  the field follow camera). Restoring the byte to 1 returns the game's own smoothing and the event camera.
* **FOV**: a cave at `0x00356780` (flag/ratio block `0x00356700`) scales the first two columns of the
  view-projection at the VP load (`0x001A9A28`), only for `CAM_VP` (without that test the minimap shrinks).
  Horizontal FOV = 2·atan(1/sx); stock sx 3.602 = 31.03°.
* **Right stick**: the game reads the pad packet at `0x0043FE9A` (buttons +2/+3, right stick X/Y +4/+5,
  left stick +6/+7, centre 0x7F). A cave at `0x00356820` (flag `0x0035670C`) holds the right stick
  at centre in both copies while the orbit is on, so the item bar and menus ignore it; the D-pad and the
  left stick are untouched.
* The caves must not overlap (`0x00356780..0x00356818` and `0x00356820..`); a test checks it.

## 4. Ruled out

| candidate | why not |
|---|---|
| `0x00410AD0` block | per-object world transform, last object drawn |
| `0x00410A90` block | rank-2 displacement accumulator (not a rotation) |
| `0x0042E140` vector | light/shadow direction |
| `0x0046C820` block | zero in every state |
| actor `+0x7D0/+0x7D4/+0x7D8` | colour inputs, not a camera offset |
| yaw/pitch/distance entry hook only | suppresses the event but does not reproduce its framing |

## 5. Moving Orbit and pitch fix (2026-11-03)

### Staircase freeze: cause and change

The supplied `jitter_bug_有り_キャラクター動かすと、カメラがカクツキ、飛ぶ.p2s`
was checked on SLPM-65908 / 64F241D2, PCSX2 fork-B056de99. The original state was read only;
traces, screenshots and a pre-investigation backup are local under
`<lab>/test_evidence/sfneo_orbit_20261103/` (not in Git).

The former scene guard required `abs(focus.y - party.y - height) < 1`. That equality is **not**
a field-camera invariant: `FUN_001D6ED0` passes the party-derived focus through
`FUN_001D7AF0` / `FUN_001D7BF0`, and mode 0 also blends the output in `FUN_001D7C60`.
The focus therefore lags during stair movement. The guard rejected a valid field, the runtime
kept integrating stick input without publishing it, and the accumulated angle appeared when
the focus caught up. This was not a 1-second PINE timeout or a periodic patch-check pause.

`read_scene()` now checks the actual dispatch: `CAM_STRUCT+0x140` is 0 (smoothed follow)
or 1 (direct follow), and `+0x144` is 0 (party focus). Modes 2..5 (fixed-eye / transition /
scripted paths) and non-party focus are rejected, as are implausible geometry, zero anchors
and distances outside the existing field range. This is not a claim that all events are classified.

The runtime also passes the relative look height directly to this adapter. Subtracting a newly
read party Y from an earlier cached orbit centre used to turn party movement into a false height
command. Legacy direct `write_orbit_params()` callers can still omit the optional keyword.
No code cave or patch ownership rules were changed.

### Pitch display / input

Internal pose math, the game's pitch halfword and saved `pitch_deg` retain **negative = camera above**.
The GUI boundary uses `PITCH_DISPLAY_SIGN=-1`, so the user sees **positive = camera above**, matching
the other games. `PITCH_INPUT_SIGN=-1` makes stick up raise the camera by default; `invert_y` remains
an additional, preserved user preference. The common geometry formula is unchanged.

The former GUI range was ±90 but input used the generic −25..85 (GUI) / −20..85 (runtime) limits.
This blocked the overhead side and even clamped the stock ≈−28° angle during horizontal input.
Both paths now use the adapter's internal −89.5..25° range, displayed as **−25..89.5°**. Overhead is
0.5° short of the pole (a deliberate look-at singularity precaution, not an observed 90° crash);
the underside pole is unavailable. Existing in-range saved/preset angles are not negated or
reinterpreted. Out-of-range values are clamped when loaded in the GUI, including old presets;
preset files themselves are not rewritten on load. Other adapters keep their original sign/limits.

### Verification on the supplied state

* 10-second stair walk with ±12° horizontal camera oscillation about the saved direction,
  distance 673.4, look height 39.64, FOV 71.25. Character Y rose from −775.58 to −631.57.
  A local old-guard/old-height compatibility path reproduced the fault: maximum observed yaw
  update gap **0.838 s**, longest guard rejection **0.813 s**, 90 rejected trace samples.
* The same state/input with the fix: **0 rejected samples**, maximum observed yaw update gap
  **0.076 s**, normal runtime error string empty. The focus/party height difference still reached
  about 29 units while smoothing, correctly without stopping Orbit. The normal ~30 Hz camera
  cadence remains; this is not a claim of frame-perfect 60 Hz rotation.
* Actual `MainWindow` + guarded PINE with an isolated copy of user settings: saved internal −25
  displayed +25; GUI +40 yielded measured internal −40.001°; scripted right-stick-equivalent up
  reached display +89.5 / measured −89.500° and a render screenshot showed the overhead view.
  Down stopped at display −25 / measured +24.999°; inversion reversed direction.
* FOV read back 71.250°, right-stick masking stayed active in Orbit, and Original returned the
  smoothing gate and both FOV/pad call sites to stock. Physical XInput hardware was not driven;
  the real runtime's scripted input path was used. User settings and source state were untouched.
* Automated adapter/runtime, input-sign, guard, memory-backend and offscreen GUI regressions
  cover stair lag, non-field dispatch rejection, relative-height sampling, saved/preset sign and
  limit handling, and unchanged FFX-2 / Suikoden V conventions. See tests in `tests/test_sfneo.py`
  and `tests/test_gui.py`. Final focused run: **209 passed** across `test_sfneo`, `test_core`,
  `test_suikoden5`, `test_game_guard`, `test_pine_backend`, and `test_gui` (51.64 s).
  FFX-2 / Suikoden V live play, arbitrary event/menu scenes and long-duration play were not rerun.

## 6. Open items

* The yaw after `restore()` is set by the game: it read −9098 in one run and −758 in another after
  1.5 s, so the return to the stock yaw is not characterised. `tools/regression_check.py` reports this
  (−50° → ≈ 4°); it is identical on the baseline commit, i.e. not a regression.
* Orbit cadence: with no load the game's eye updates about every 35 ms and rotates 3.6–4.1° per update
  at stick 0.8; a busy GUI thread widened the spread to 1.1–6.6°. Per-tick PINE requests were cut from
  about 20 to about 3 without changing it.
* A running GUI keeps writing (gate, FOV, orbit) while a harness runs; close the GUI before live checks
  (and use one PINE client at a time).
