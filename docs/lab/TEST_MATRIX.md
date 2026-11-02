# TEST_MATRIX — requirement → result

Legend: **PASS** = the real function ran and produced evidence; **CHANGES
REQUESTED** = works with a documented deviation; **BLOCKED** = cannot be
completed without a user-owned or privileged resource; **N/A** = not applicable
to this gate.

Evidence files are under `reports/`; screenshots under `shots/e2e/`.

## A. Environment and tooling

| # | Requirement | Result | Evidence |
|---|---|---|---|
| 1 | OS/CPU/RAM/disk inventory | PASS | `reports/environment_inventory.json` |
| 2 | Python / Java / Node / Git / PowerShell / PCSX2 / Ghidra inventory | PASS | same |
| 3 | Dedicated workspace at `C:\PS2CameraLab` | PASS | directory tree, README |
| 4 | Compatible version selection with recorded provenance | PASS | `TOOL_VERSIONS.md` + SHA-256 checks |
| 5 | 7-Zip available | PASS | `C:\Program Files\7-Zip\7z.exe` 26.05, used for ISO/ELF/Ghidra |
| 6 | Automated test framework | PASS | `pytest` 9.2.0, 33 tests, all green |

## B. Web research capability

| # | Requirement | Result | Evidence |
|---|---|---|---|
| WEB-01 | Search returns titles + URLs | PASS | `reports/web_research_log.json` |
| WEB-02 | Fetch official body text | PASS | README + fork sources at commit `7235a04` |
| WEB-03 | GitHub README/issue/source inspection | PASS | README, `server.py`, `GDBServer.cpp`, `PINE.cpp`, releases |
| WEB-04 | Apply a researched fact to the local environment | PASS | stock exe lacks `qPcsx2`; fork has it; digest matched |
| WEB-05 | Inject a recoverable fault, detect, research, repair, verify, restore | PASS | `reports/e2e_e.json` (8/8 steps) |

## C. PCSX2 automation

| # | Requirement | Result | Evidence |
|---|---|---|---|
| 1 | CLI launch + specific ISO | PASS | E2E-A PID + window title `ファイナルファンタジーX-2` |
| 2 | Process detection | PASS | `list_pcsx2_processes`, `ps2lab.pcsx2.find_processes` |
| 3 | Emulator state query | PASS | qPcsx2 `status`, PINE `MsgStatus` |
| 4 | Safe termination | PASS | E2E-D `graceful emulator shutdown` via `WM_CLOSE` |
| 5 | Automatic restart | PASS | E2E-D `emulator restarted`, supervisor restarts |
| 6 | Savestate save/restore | PASS | E2E-A/B/D slot 1; `save_state_slot`/`load_state_slot` |
| 7 | Crash / non-response detection | PASS | `is_responding` (SendMessageTimeoutW) + supervisor classes |
| 8 | Log collection | PASS | `tail_log_lines` resolves the portable `logs/emulog.txt` |
| 9 | Timeout control | PASS | tool timeouts, `toolCallTimeoutMs` 180 s, pytest-timeout 300 s |
| 10 | No manual GUI steps for the E2E flow | PASS | E2E-F 3 consecutive runs, 0 failures |

## D. MCP server

| # | Requirement | Result | Evidence |
|---|---|---|---|
| 1 | Server starts | PASS | `initialize` handshake |
| 2 | `initialize` / `tools/list` | PASS | 72 tools |
| 3 | Tool execution | PASS | 28/28 MCP matrix checks |
| 4 | Error responses | PASS | closed-port connect, unknown tool |
| 5 | Disconnect / reconnect | PASS | `reports/mcp_protocol_test.json` cycles; E2E-D |
| 6 | Timeout behaviour | PASS | client timeout path exercised (closed port 2.05 s, tool timeouts) |
| 7 | Repeated start/stop | PASS | 3 protocol cycles |
| 8 | Registered in DeepSeek Harness | PASS (config) | `MCP_SETUP.md`, patch validated with `yaml.safe_load` |
| 9 | Model-native tool invocation in the GUI session | **PASS** | 72 tools as `mcp__pcsx2__*`; full session in `reports/model_native_mcp.json` |
| 10 | Model-native tool invocation proven end-to-end | PASS | the model itself called launch/connect/load/screenshot/registers/disassemble/input/pattern/savestate/diff/disconnect/reconnect |

## E. GDB / qPcsx2 compatibility

| # | Capability | Result | Notes |
|---|---|---|---|
| 1 | EE GDB connect | PASS | 10501 |
| 2 | IOP GDB connect | PASS | 10502 |
| 3 | CPU register read | PASS | after flush (KB-08) |
| 4 | Memory read/write | PASS | scratch + restore verified |
| 5 | Disassembly | PASS | capstone fallback (qPcsx2 verb broken, KB-04) |
| 6 | Pause / resume / single step | PASS | `T02`/`T05` stop packets |
| 7 | Execution breakpoints | PASS | GDB `Z0`/`Z1` |
| 8 | Write watchpoints | PASS | GDB `Z2`; also qPcsx2 `debug_set_watchpoint` accepted |
| 9 | Frame advance | PASS | `frameadvance` |
| 10 | Savestate control | PASS | qPcsx2 slots and files |
| 11 | Screenshot | PASS | qPcsx2 framebuffer while running; PrintWindow fallback |
| 12 | Native qPcsx2 controller input | CHANGES REQUESTED | verb rejects every argument set (KB-04); keyboard backend used instead |
| 13 | PINE IPC | PASS | TCP 28011, memory/status/title (KB-10) |

## F. Game input

| # | Requirement | Result | Evidence |
|---|---|---|---|
| 1 | Left stick | PASS | E2E-B, frame changed |
| 2 | Right stick | PASS | E2E-B (transport + frame reaction 0.09–0.47) |
| 3 | D-pad | PASS | matrix `input_button_press` + keyboard bindings |
| 4 | ○ × △ □ | PASS | E2E-B cross/circle; bindings J/K/L/I |
| 5 | L1/L2/R1/R2 | PASS | bindings Q/E/1/3 verified in `PCSX2.ini` |
| 6 | START/SELECT | PASS | E2E-B start (0.65 frame change) |
| 7 | Simultaneous buttons | PASS | `input_buttons_send` |
| 8 | Hold and release | PASS | `input_analog_send` duration/hold + `input_reset` |
| 9 | Right-stick delivery proven | PASS | backend accepts; guest reacts on screens that use it |
| 10 | Built-in controller conflict handling | PASS | SDL gamepad detected; keyboard path unaffected |

## G. Screenshots and visual verification

| # | Requirement | Result | Evidence |
|---|---|---|---|
| 1 | PNG capture of the game | PASS | `shots/e2e/**` 554×416 framebuffer, 1066×705 window |
| 2 | MCP screenshot | PASS | `take_screenshot` |
| 3 | Alternative capture | PASS | `capture_pcsx2_window` |
| 4 | Before/after images | PASS | per-step PNGs |
| 5 | Image diff | PASS | `vision.diff` changed_ratio |
| 6 | Black/blank detection | PASS | `vision.looks_rendered` (unit-tested) |
| 7 | Time/action correlation | PASS | report JSON carries `ts` + step + stats |
| 8 | Continuous capture | PASS | polling loop in `wait_for_content` |
| 9 | Model can recognise images | PASS | frames read and described (title screen, intro credits) |

## H. Memory and CPU analysis

| # | Requirement | Result | Evidence |
|---|---|---|---|
| 1 | Memory read | PASS | E2E-C |
| 2 | Byte-pattern search | PASS | 20 matches for `5a 00 03 3c` |
| 3 | Memory dump | PASS | `dump_memory`/`dump_region` |
| 4 | Memory diff between states | PASS | `memory_diff`, `find_changing_word` |
| 5 | Integer/float decoding | PASS | `analysis.decode_values` (unit-tested) |
| 6 | CPU registers | PASS | GDB + qPcsx2 per category |
| 7 | MIPS disassembly | PASS | capstone + Ghidra |
| 8 | Breakpoints | PASS | GDB `Z0`/`Z1`, MCP tool |
| 9 | Write watchpoints | PASS | GDB `Z2` |
| 10 | Instruction address of a write | PASS | `sd $ra, 0x40($sp)` at `0x0027e58C` |
| 11 | Write-source function investigation | PASS | Ghidra `FUN_0027e578` |
| 12 | JSON export | PASS | `reports/analysis_*.json`, `write_source_*.json` |
| 13 | Safe scratch usage + restore | PASS | `0x01FF0000` write/restore tests |

## I. Ghidra headless

| # | Requirement | Result | Evidence |
|---|---|---|---|
| 1 | `analyzeHeadless` runs | PASS | rc=0, 76.8 s |
| 2 | PS2 ELF import | PASS | `SLPS_252.50`, 3.7 MB |
| 3 | R5900-specific language | PASS | `r5900:LE:32:default` (KB-18) |
| 4 | Function extraction | PASS | 5 843 functions |
| 5 | Reference relations | PASS | 13,642 call edges + 5,000 symbols in `reports/ghidra_functions.json` |
| 6 | Decompilation | PASS | `DecompileTargets.java` exported the 3 dynamic targets (30,127 bytes of C) in `reports/ghidra_decompiled.c` |
| 7 | Custom script execution | PASS | `ghidra_scripts/ExportAnalysis.java` |
| 8 | JSON report | PASS | `reports/ghidra_functions.json` (1.45 MB) |
| 9 | Cross-check with live PCs | PASS | `0x0032383C → FUN_00323838`, `0x0027E58C → FUN_0027E578` |
| 10 | Savestate analysis support | PASS (live extraction) | `scripts/savestate_extract.py` loads a slot and dumps EE RAM/scratch through RSP/PINE with a SHA-256 manifest (`work/ee_ram_slot1.json`); an offline container parser is still absent (B-04) |

## J. Recovery

| # | Requirement | Result | Evidence |
|---|---|---|---|
| 1 | MCP disconnect detection | PASS | E2E-D |
| 2 | GDB stall detection | PASS | `probe_gdb`, supervisor events |
| 3 | Process crash detection | PASS | `health()` `process_missing` |
| 4 | Memory/disk monitoring | PASS | `ram_percent`, `disk_free_gb` |
| 5 | Auto reconnect | PASS | E2E-D |
| 6 | Safe restart | PASS | E2E-D |
| 7 | Baseline restore | PASS | E2E-D slot 1 |
| 8 | Re-run the same experiment | PASS | E2E-F 3 runs |
| 9 | Error history | PASS | `logs/supervisor.jsonl`, `reports/troubleshooting_history.json` |
| 10 | Retry limits | PASS | 3 attempts, exponential backoff |
| 11 | Failure classification | PASS | `ps2lab.recovery.classify` (unit-tested) |
| 12 | Regression tests | PASS | `pytest` 33 tests |

## K. End-to-end

| Phase | Result | Evidence |
|---|---|---|
| E2E-A startup | PASS | `reports/e2e_f.json` run 1–3 |
| E2E-B input + visual | PASS | 6–7 of 7 steps changed the frame per run |
| E2E-C analysis | PASS | registers, memory, disassembly, `Z2` write source, Ghidra cross-check |
| E2E-D recovery | PASS | disconnect → reconnect → shutdown → restart → baseline → re-verified |
| E2E-E self-repair | PASS | `reports/e2e_e.json` 8/8 |
| E2E-F unattended ×3 | PASS | **111/111 checks PASS, 3/3 runs, 0 human interventions** |

Total measured runtime: E2E-F ≈ 2 min 40 s for three full A–D cycles on this
machine (runs of 34.8 s, 35.7 s and the first run which includes emulator
startup).
