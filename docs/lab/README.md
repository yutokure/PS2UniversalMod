# README — PS2-CAM-00 Autonomous PS2 Analysis Environment

> Moved into the repository on 2026-11-02 (`PS2UniversalMod/docs/lab/`). Start from [`../README.md`](../README.md)
> for the index. Evidence files named below (`reports/`, `shots/`, `logs/`) are local lab files and are
> not versioned.

`C:\PS2CameraLab` is a self-contained Windows lab in which **DeepSeek Harness
can start, drive, observe, analyse, break into, restore and repair a running
PlayStation 2 game** through the PCSX2 MCP server, plus a headless Ghidra
pipeline for static analysis.

It exists to make the next gate possible:

> 「FF10のカメラ制御処理を解析し、自由カメラ化に必要なプログラムとデータを特定してください」

Everything in this repository is executed and verified — no dry-run stubs. The
evidence lives in `reports/`.

## What works (verified)

| Capability | Evidence |
|---|---|
| Launch a specific ISO, detect the process/window, safe shutdown, restart | `reports/e2e_results.json` A/D, `logs/supervisor.jsonl` |
| EE + IOP GDB servers, registers, memory, breakpoints, watchpoints, stepping | `reports/feature_matrix.json` (`gdb` 10/10 PASS) |
| qPcsx2 extensions (status, savestates, frame advance, cheats, patch reload, screenshot) | `reports/feature_matrix.json` (`qpcsx2` 16 PASS / 13 documented limitations) |
| MCP server over real stdio JSON-RPC (initialize, tools/list, tools/call, errors, reconnect) | `reports/mcp_protocol_test.json`, `reports/feature_matrix.json` (`mcp` 28/28 PASS) |
| Model-native MCP driving of the emulator (72 tools as `mcp__pcsx2__*`) | `reports/model_native_mcp.json` |
| Controller input — buttons and both sticks — reaching the guest | `reports/e2e_results.json` B (7/7 steps changed the frame) |
| Screenshots with real pixel validation (framebuffer, or inactive-window fallback) | `shots/e2e/**`, `reports/e2e_results.json` |
| PINE IPC (memory/status/title) cross-checked against GDB | `reports/pine_probe.json` |
| Ghidra 12.1.4 + Emotion Engine: Reloaded headless analysis of the game ELF | `reports/ghidra_summary.json` |
| Autonomous recovery: MCP disconnect, GDB listener death, emulator restart, baseline restore | `reports/e2e_results.json` D, `logs/supervisor.jsonl` |
| Autonomous fault repair (config fault → detection → repair → verification) | `reports/e2e_results.json` E |
| Web research (search, fetch, GitHub primary sources) | `WEB_RESEARCH_SETUP.md`, `reports/web_research_log.json` |

## Layout

```
C:\PS2CameraLab
├─ pcsx2\            compatible build (GDB+qPcsx2), stock build, ISO, BIOS
├─ vendor\PCSX2_MCP  MCP server checkout (branch compat/ps2cam00)
├─ python\venv       lab interpreter (mcp 2.3.0, capstone, pytest…)
├─ ghidra\ + jdk\    Ghidra 12.1.4, EE Reloaded 2.1.38, Temurin 21
├─ scripts\          automation (ps2lab package + CLIs)
├─ tests\            pytest suite (unit + integration)
├─ ghidra_scripts\   ExportAnalysis.java (headless export)
├─ reports\          machine-readable evidence (JSON)
├─ shots\            screenshots produced by E2E runs
├─ logs\             supervisor log, emulator logs
├─ config\           PCSX2.ini seed, MCP patches, ghidra.json
└─ docs\             long-form notes (KB, research notes)
```

## Quick start

```powershell
# 1. health snapshot
C:\PS2CameraLab\python\venv\Scripts\python.exe C:\PS2CameraLab\scripts\collect_inventory.py

# 2. bring the stack up (idempotent) and verify the protocol
C:\PS2CameraLab\python\venv\Scripts\python.exe C:\PS2CameraLab\scripts\mcp_probe.py

# 3. full end-to-end (startup, input, analysis, recovery)
C:\PS2CameraLab\python\venv\Scripts\python.exe C:\PS2CameraLab\scripts\e2e_run.py --phases A,B,C,D

# 4. tests
C:\PS2CameraLab\python\venv\Scripts\python.exe -m pytest -q C:\PS2CameraLab\tests

# 5. static analysis refresh
C:\PS2CameraLab\python\venv\Scripts\python.exe C:\PS2CameraLab\scripts\ghidra_analyze.py
```

## Documentation map

| File | Contents |
|---|---|
| `ARCHITECTURE.md` | component diagram, data flows, transport choices |
| `SETUP.md` | reproducible installation from a bare Windows machine |
| `TOOL_VERSIONS.md` | pinned versions, sources, digests, rejected alternatives |
| `MCP_SETUP.md` | MCP registration in DeepSeek Harness, verification, rollback |
| `WEB_RESEARCH_SETUP.md` | web search/fetch providers and the WEB-01…05 tests |
| `AUTONOMOUS_TROUBLESHOOTING.md` | the self-healing loop and its guardrails |
| `TROUBLESHOOTING_KB.md` | 24 solved problems with root causes and proofs |
| `CLI_REFERENCE.md` | every script, argument and output file |
| `TEST_MATRIX.md` | per-requirement PASS/FAIL table |
| `BLOCKERS.md` | what is not solved and why |
| `CAMERA_RESEARCH_READINESS.md` | what the next gate can rely on |

## Safety

* BIOS/ISO/save data of the user are never modified; the lab uses copies
  (`pcsx2\iso`, `pcsx2\fork-B056de99\bios`).
* GDB (10501/10502) and PINE (28011) bind to `127.0.0.1` only.
* Memory experiments write to a scratch page and restore the original bytes;
  savestates are addressed by explicit slots.
* No Windows security feature is disabled; no kernel driver is installed.
* Credentials are never written to reports or logs.

