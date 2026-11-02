# CLI_REFERENCE — every script, argument and artifact

All commands assume `C:\PS2CameraLab` and use
`C:\PS2CameraLab\python\venv\Scripts\python.exe` (abbreviated `$PY` below).

```powershell
$PY = "C:\PS2CameraLab\python\venv\Scripts\python.exe"
$env:PS2LAB_PCSX2_DIR = "C:\PS2CameraLab\pcsx2\fork-B056de99"   # portable install hint
```

## Bootstrap / installation

| Command | Purpose | Output |
|---|---|---|
| `$PY scripts\install_ghidra.py` | download + verify + extract JDK 21, Ghidra 12.1.4, EE Reloaded 2.1.38 | `config\ghidra.json`, `reports\ghidra_install.json` |
| `$PY scripts\download_resumable.py <url> <dest> [sha256]` | resumable download with digest gate | file |
| `$PY scripts\apply_compat_patches.py [--check]` | apply the MCP compatibility patches (idempotent) | git diff on `vendor\PCSX2_MCP` |
| `$PY scripts\collect_inventory.py` | environment snapshot | `reports\environment_inventory.json` |
| `$PY scripts\savestate_extract.py --slot N --region ee_ram --out FILE` | load a savestate and dump RAM (RSP/PINE) with a manifest | `work/*.bin` + `*.json` |
| `$PY scripts\show_pcsx2_window.py` | reveal a hidden PCSX2 window without activating it (KB-20) | window visible |
| `pwsh -File scripts\activate_mcp.ps1` | restart DeepSeek Harness to load a profile patch (KB-19) | `mcp__pcsx2__*` tools |

## Service / protocol checks

| Command | Purpose | Output |
|---|---|---|
| `$PY scripts\mcp_probe.py [--cycles N] [--out FILE]` | real stdio MCP session: initialize, tools/list, calls, errors, restarts | `reports\mcp_protocol_test.json` |
| `$PY scripts\feature_matrix.py` | wire GDB + qPcsx2 + MCP capability matrix | `reports\feature_matrix.json` |
| `$PY scripts\pine_probe.py` | PINE protocol checks + GDB cross-check | `reports\pine_probe.json` |
| `$PY scripts\input_verify.py [--tag T]` | button/stick delivery + frame diffs | `reports\input_verify_<tag>.json`, `shots\input_e2e\` |

## Emulator control (library + CLI)

| Command | Purpose |
|---|---|
| `$PY -c "from ps2lab import pcsx2; print(pcsx2.status())"` | process/port/window snapshot |
| `$PY -c "from ps2lab import pcsx2, config; pcsx2.launch(game=config.TEST_ISO)"` | launch the configured ISO |
| `$PY -c "from ps2lab import pcsx2; pcsx2.close_gracefully(pid)"` | safe WM_CLOSE shutdown |
| `$PY -c "from ps2lab import pcsx2; pcsx2.terminate_all()"` | hard stop all PCSX2 processes |
| `$PY -c "from ps2lab import recovery; s=recovery.Supervisor(); print(s.health())"` | health report |
| `$PY -c "from ps2lab import recovery; recovery.Supervisor().ensure_emulator()"` | start or repair the emulator |
| `$PY -c "from ps2lab import pine; c=pine.PineClient().connect(); print(c.title(), c.game_id(), c.status())"` | PINE spot check |

## Analysis helpers

| Command | Purpose |
|---|---|
| `$PY -c "from ps2lab import analysis; print(analysis.disassemble(bridge, 0x00100008, 16))"` | disassemble (qPcsx2 or capstone) |
| `$PY -c "from ps2lab import analysis; print(analysis.capture_write_source(None, target='ee'))"` | find the instruction that writes a live stack/global |
| `$PY -c "from ps2lab import analysis; print(analysis.find_changing_word())"` | discover a live variable by diffing RAM |
| `$PY -c "from ps2lab import analysis; idx=analysis.load_ghidra_index(); print(analysis.lookup_function(idx, '0x0027e58c'))"` | address → function |
| `$PY -c "from ps2lab import vision; print(vision.stats(r'shots\\e2e\\...png'))"` | pixel statistics |
| `$PY -c "from ps2lab import vision; print(vision.diff(a, b))"` | image difference |

## End-to-end runner

```
$PY scripts\e2e_run.py [--phases A,B,C,D] [--repeat N] [--full] [--out FILE]
```

| Phase | Meaning |
|---|---|
| A | startup: emulator, MCP, EE/IOP GDB, PINE, game-ready gate |
| B | input + visual verification (baseline save, sticks, buttons, diffs, registers) |
| C | analysis: registers, memory, disassembly, pattern search, `Z2` write source, Ghidra cross-check |
| D | recovery: disconnect → reconnect → graceful shutdown → restart → baseline restore → re-verify |
| E | fault injection + self repair (destructive; run separately) |
| F | repeat the selected phases (`--repeat 3` = unattended loop) |

Artifacts: `reports\e2e_results.json` (or `--out`), screenshots under
`shots\e2e\<tag>\`, supervisor history inside the report.

## Static analysis

| Command | Purpose | Output |
|---|---|---|
| `$PY scripts\ghidra_analyze.py [--elf PATH] [--no-analyze] [--timeout S]` | headless Ghidra import + export + cross-check | `reports\ghidra_functions.json`, `reports\ghidra_summary.json` |
| `7z x "<iso>" -o work\elf -y` | extract the game ELF from the ISO | `work\elf\SLPS_252.50` |
| `ghidra_scripts\ExportAnalysis.java` | post-script used by headless to dump functions/symbols | JSON |

## Tests

| Command | Purpose |
|---|---|
| `$PY -m pytest -q` (from `C:\PS2CameraLab`) | 33 tests (unit + integration; integration auto-skips without GDB) |
| `$PY -m pytest -q -m integration` | only live-emulator tests |
| `$PY -m pytest -q tests/test_unit.py` | no-emulator logic tests |

## Environment variables

| Variable | Effect |
|---|---|
| `PS2LAB_ROOT` | override the lab root (default `C:\PS2CameraLab`) |
| `PS2LAB_PCSX2_DIR` | portable PCSX2 directory used by MCP log/config discovery |
| `JAVA_HOME` | only used for the Ghidra subprocess (`ghidra_analyze.py` sets it) |

## Reports produced by a full pass

```
reports\environment_inventory.json
reports\mcp_protocol_test.json
reports\feature_matrix.json
reports\pine_probe.json
reports\e2e_results.json | e2e_abcd.json | e2e_e.json | e2e_f.json
reports\ghidra_functions.json
reports\ghidra_summary.json
reports\web_research_log.json
reports\troubleshooting_history.json
logs\supervisor.jsonl
```
