# CAMERA_RESEARCH_READINESS — PS2-CAM-00 完了時の研究準備状況

以下の YES は[親ラボ](README.md)を使った当時の判定です。次の課題として挙げた FFX と、機器の動作確認に使った FFX-2 は別タイトルです。これは現行 GUI の対応タイトル一覧でも、公開チェックアウトに同じ実験環境があるという意味でもありません。

This gate did **not** modify any game camera code. It built and proved the
instrumentation needed for the next instruction:

> 「FF10のカメラ制御処理を解析し、自由カメラ化に必要なプログラムとデータを特定してください」

## 1. Ready capabilities

| Need for camera work | Ready | How to use it |
|---|---|---|
| Boot a specific game and reach a known state | YES | `Supervisor.ensure_emulator()`, `ensure_game_ready()` (loads baseline slot 1) |
| Capture the screen at any moment | YES | `take_screenshot` (framebuffer) or `capture_pcsx2_window`; validate with `vision.looks_rendered` |
| Move the camera inputs (both sticks) | YES (digital) | `input_analog_send(stick="right", x=±0.9, y=±0.9)`; see B-02 for analog fidelity |
| Observe camera state in RAM | YES | `read_memory`, `find_pattern`, `memory_diff`, PINE fast reads |
| Find a variable that changes with the camera | YES | `analysis.find_changing_word()` + `memory_diff` snapshots |
| Catch the code that writes it | YES | `analysis.capture_write_source()` (GDB `Z2`, returns PC + instruction + registers) |
| Identify the containing function statically | YES | `reports/ghidra_functions.json` + `analysis.lookup_function()` |
| Step through and inspect registers/stack | YES | `pause`/`step`/`get_registers`/`read_memory` (`sp` based stack walk) |
| Restore the scene after an experiment | YES | `save_state_slot`/`load_state_slot`, `Supervisor.restore_baseline()` |
| Recover from crashes mid-experiment | YES | supervisor restart + baseline restore (E2E-D) |
| Repeat an experiment unattended | YES | `scripts/e2e_run.py` pattern, 3/3 clean runs |

## 2. Recommended procedure for the next gate

1. **Baseline** — boot FFX, play to the first controllable field area, then
   `save_state_slot(1)`; this becomes the experiment origin.
2. **Differential capture** — load the baseline, take a screenshot, push the
   right stick fully right for ~1 s, take another screenshot, and record
   `vision.diff` (expect a changed_ratio well above 0.01 for a real camera move).
3. **Memory sweep** — with the supervisor, snapshot a RAM window
   (`memory_diff` over EE RAM in 64 KB windows) before and after the stick push;
   keep addresses whose values change monotonically with the camera motion
   (float32 near ±π for yaw, or a matrix basis).
4. **Watchpoint** — arm `capture_write_source(addr)` on the best candidate; the
   stop packet returns the writing PC and a disassembly window.
5. **Static linkage** — look the PC up in `ghidra_functions.json`, then decompile
   that function on demand (see B-05) and follow its callers.
6. **Patch hypothesis** — the camera update function typically reads the pad
   right-stick axes, applies a rotation to a view matrix, and clamps a pitch
   limit. Prepare the patch as a code cave or an in-place branch, verify with a
   savestate delta and screenshots.
7. **FOV / first-person / collision** — reuse the same matrix and clamp
   constants; collision is usually a raycast against level geometry, so expect
   to trace the caller that supplies the camera target position.

## 3. Known instrumentation limits (plan around them)

| Limit | Impact | Mitigation |
|---|---|---|
| qPcsx2 `debug_disasm` broken (KB-04) | no emulator-native disassembly | Capstone in the lab and Ghidra statically — both verified |
| qPcsx2 breakpoints broken (KB-04) | no conditional breakpoints | GDB `Z0/Z1/Z2`; conditions can be emulated by repeated stop-and-check |
| Native analog input broken (B-02) | no 8-bit stick values | keyboard full-deflection now; ViGEmBus or input recording later |
| EE register file stale after attach (KB-08) | wrong first observation | always use `snapshot_registers(fresh=True)` |
| Single GDB client (KB-09) | MCP + raw RSP cannot coexist | lab serialises: raw RSP for watchpoints, MCP otherwise |
| 1 MB/s PINE reads | slow full-RAM dumps | use GDB chunked reads (0x800) for bulk, PINE for spot checks |
| FFX-2 title screen runs the EE idle (PC `0x00081FC0`) | watchpoints on the stack never fire there | run gameplay or use `find_changing_word` discovery |

## 4. Concrete assets produced by this gate

* `reports/ghidra_functions.json` — 5 843 functions from `SLPS_252.50`
  (ELF entry `0x00100008`, matching the emulator's boot log).
* `reports/write_source_*.json` — worked examples of "who wrote this address"
  with registers, stack pointer and disassembly.
* `shots/e2e/**` — reproducible visual states incl. the FFX-2 title screen.
* `logs/supervisor.jsonl` — every recovery the supervisor performed, useful to
  distinguish "the game did that" from "the harness did that".

## 5. What would make the next gate easier (optional)

1. A second savestate deeper in gameplay (slot 2) so experiments can start
   where the camera is actually active.
2. Approve one of the analog-input options (B-02) if sub-degree camera moves
   must be tested.
3. Allow a longer Ghidra pass that also exports decompiled C for the top ~200
   functions (B-05), which speeds up reading the camera update routine.
