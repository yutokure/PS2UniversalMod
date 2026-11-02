# Suikoden V adapter — test results (2026-11-02)

Disc: `suikoden5.iso`, reported by PCSX2 as SLPM-66286 / CRC 7380A572. PCSX2 build: the lab fork
(`pcsx2/fork-B056de99`). Savestates (first 16 hex digits of the SHA-256 of the `.p2s`):

| file | sha256 (prefix) |
|---|---|
| base.p2s | BE5F0771D0DC99D5 |
| base_only_wait.p2s | 1B524B6EB0AF19B6 |
| base_no_move_and_cam_zoom_only.p2s | DEFF8CE77C6479E3 |
| chara_and_cam_moved_from_base.p2s | A5F710DA205C9B65 |
| chara_little_moved_and_cam_bigger_moved_from_base.p2s | 0CA5C354290D5BE5 |

Only items that ran and passed are marked PASS. Every number below was read back from the game's
memory (or from a screenshot, for the FOV) — never from the GUI alone. Screenshots, the 150 s sample
log and the extracted RAM stay in the git-ignored local evidence folder (`test_evidence/suikoden5/`).

## Results

| ID | Result | How it was checked | Script |
|---|---|---|---|
| TEST-01 identify | PASS | serial + CRC read through PINE; other disc ids refused (unit test) | `su5_live_check`, `test_suikoden5` |
| TEST-02 five states | PASS | all five loaded in PCSX2; S1/S2 probed live (S2: distance 300, stage 1); offline analysis reproduces the eye position of all five exactly | `su5_state_probe`, `analysis/suikoden5/summarize.py` |
| TEST-03 native zoom | PASS | R1 cycles 400 → 300 → 200 → 400; pitch/yaw/FOV constant; the game's right stick also steps it (mod off) | `su5_zoom_check` |
| TEST-04 horizontal rotation | PASS | right stick (runtime): yaw +150° in 1 s, eye stays at constant distance from the focus, focus unchanged | `su5_engine_check` |
| TEST-05 vertical rotation | PASS | pitch 13 → 85 (limit) and holds when the stick is released | `su5_engine_check` |
| TEST-06 follow | PASS | walking 116 units: focus equals the character; walking direction relative to the camera is the same at two opposite yaws (diff 4–10°) | `su5_zone_check`, `su5_input_check` |
| TEST-07 input conflict | PASS | with the orbit on, a physical right stick up/down never changes the zoom stage; R1 still steps it; with the orbit off the game's stick zoom works again | `su5_input_check` |
| TEST-08 GUI distance | PASS | GUI spin box 300 → game distance 300; stage buttons 200/400 | `su5_gui_check` |
| TEST-09 GUI position | PASS | look height ±, camera X/Y/Z, target X move the focus by exactly the entered amounts; zero returns it | `su5_gui_check` |
| TEST-10 GUI FOV | PASS | game FOV 20 → 60, viewport extent = sin(30°); screenshots: FOV 20 vs 40 mean pixel difference 21, stock vs orbit-with-stock-values 0.04 | `su5_gui_check`, evidence screenshots |
| TEST-11 area camera | PASS (see limits) | walking up the slope the game's own pitch goes 13 → 40 while the rendered pitch stays 25.00; across the map exit the orbit values are applied again in the next map (its own camera is yaw 200 / pitch 33) | `su5_zone_check`, `su5_transition_check` |
| TEST-12 restore | PASS | hooks removed, flags cleared, the game's own distance/pitch/yaw/FOV back; right stick zoom and R1 work | `su5_engine_check`, `su5_gui_check`, `su5_input_check` |
| TEST-13 GUI standalone | PASS | the GUI check uses PINE only; DeepSeek Harness and the MCP server are not involved (the MCP was used only by the tester to load savestates) | `su5_gui_check` |
| TEST-14 regression | PASS for FFX-2; SF Neo 5/6 = baseline | engine regression on both games after the PCSX2 restart. SF Neo's "direction after restore" differs (-50° → 4°) **identically on the baseline commit**; it is the known open item (the game sets its own yaw after restore) | `regression_check` |
| TEST-15 restart | PASS | PCSX2 restarted for each of the three games and again for Suikoden V; adapter identified and ran 20/20 + 6/6 + 16/16 on the fresh process | `su5_live_check`, `regression_check` |
| TEST-16 long run | PASS | 150 s mixed input (stick sweeps, left-stick walks, distance/FOV/offset changes, 18 R1 presses): 2821 samples, 0 jumps, 0 errors, clean exit. With external savestate loads during the run the hook was repaired within 0.05–0.16 s each time | `su5_soak` |

Unit tests: 106 pass (`pytest tests`), 25 of them for this adapter (cave layout, branch targets,
compare-and-swap install, coordinate mapping, seeding, heartbeat guard, zoom helpers).

## Things seen during testing

* **Map change**: for ~0.7 s the game shows its own camera init (yaw 180, distance 30) while the
  next field loads; the mod is not involved (the camera update is not running). The orbit values are
  back as soon as the update runs again.
* **Savestate load**: RAM reverts and the hooks vanish. The engine looks every 0.2 s and reinstalls,
  starting from the last orbit values (no jump). Before this was fixed the camera jumped back from
  the game's camera (recorded in the commit history of `adapter.py`).
* **User report, "using the game's zoom moves the aim point off the character"**: not reproduced
  with zero offsets — with the orbit on and no offsets, three R1 steps left the focus identical to
  the game's own focus (`G_FOCUS` = native focus, measured). The soak test applies random world
  offsets (±20) on purpose, and a world-space offset looks larger at a closer zoom stage. If the
  drift also appears with all offsets at zero, please send the steps; the next thing to check
  would be the look-height slider.
* PCSX2 exited by itself twice while switching between games (right after a state load on a freshly
  booted game). A relaunch fixed it; no crash dump was written. Not related to the hooks (no hook
  was installed at that moment).

## Not done / limits

* Event cut-scenes, battles and menus were not exercised; the heartbeat guard simply leaves them alone.
* A physical XInput pad was not used; the right stick reached the engine through the runtime and the
  GUI's scripted source (the XInput/keyboard source classes are shared and unchanged).
* No free (detached) camera for this game: the GUI disables that radio button.
* Camera X/Y/Z and target offsets are world-space; they move the whole rig.
* Only the Japanese disc (CRC 7380A572) is supported.
* The two other games' full end-to-end suites (`tools/e2e.py` etc.) were not rerun; only the
  engine-level regression above.
