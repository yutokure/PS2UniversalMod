# ARCHITECTURE — 親ラボの解析環境

この図は [PS2-CAM-00](README.md) の研究用構成です。MCP、GDB、`qPcsx2`、Ghidra、ローカルの監視スクリプトは、公開 GUI の依存関係や自動復旧機能ではありません。通常は GUI → PINE → PCSX2 の経路を使います（[起動方法](../../README.md)）。

## 1. Component view

```
┌──────────────────────────────────────────────────────────────────────────┐
│ DeepSeek Harness (desktop 0.2.1-rc.3, GUI at 127.0.0.1:56634)            │
│  · model + tool runtime                                                  │
│  · @deepseek-ai/dsh-mcp-client  ── stdio JSON-RPC ──┐                    │
│  · web_search / web_fetch (dsh-tool-web)            │                    │
└─────────────────────────────────────────────────────┼────────────────────┘
                                                      │
                            ┌─────────────────────────▼───────────────────┐
                            │ PCSX2 MCP server (Python 3.12, mcp 2.3.0)   │
                            │  72 tools: connect/registers/memory/…       │
                            │  compat/ps2cam00 patches (KB-04…KB-09)      │
                            └───────────┬───────────────────┬─────────────┘
                                        │ GDB RSP           │ Win32 / qPcsx2
                        ┌───────────────▼───────┐   ┌───────▼──────────────┐
                        │ EE GDB :10501         │   │ PrintWindow capture  │
                        │ IOP GDB :10502        │   │ PostMessage keyboard │
                        └───────────┬───────────┘   └───────┬──────────────┘
                                    │                       │
                    ┌───────────────▼───────────────────────▼──────────────┐
                    │ PCSX2 compatible build v2.7.499 (GDB + qPcsx2)       │
                    │  portable: inis/, bios/, sstates/, logs/, snaps/     │
                    │  PINE TCP :28011                                     │
                    └───────────────┬──────────────────────────────────────┘
                                    │ reads
                        ┌───────────▼───────────┐
                        │ FF X-2 ISO + BIOS     │
                        └───────────────────────┘

Static side:  SLPS_252.50 (extracted from the ISO)
                    │
                    ▼
              Ghidra 12.1.4 headless + EE Reloaded 2.1.38 (r5900:LE:32:default)
                    │
                    ▼
              reports/ghidra_functions.json  (function/symbol index)
                    │
                    ▼
              address ⇄ function cross-check with live PCs
```

## 2. Transport selection (and why)

| Need | Transport | Rationale |
|---|---|---|
| Registers, memory, breakpoints, stepping, watchpoints | **GDB RSP** (EE/IOP) | native, complete, already implemented by the emulator |
| Emulator-level commands (savestates, frame advance, cheats, patch reload, framebuffer screenshot) | **qPcsx2** over the same GDB socket | no extra port, works while paused, returns structured text |
| Fast memory reads without pausing | **PINE** (TCP 28011) | does not disturb the VM; used for status/title/memory cross-checks |
| Input | **Win32 `PostMessageW`** to the render child window + PCSX2 keyboard bindings | no kernel driver, works unfocused; the native qPcsx2 `input_set` verb is broken in this build (KB-04) |
| Screenshots | qPcsx2 `screenshot_file` (framebuffer) with `PrintWindow` fallback | verified pixel content in both modes (KB-07) |
| Static analysis | **Ghidra headless** | reproducible, scriptable, JSON output |

## 3. Data flow of one experiment

```
Harness tool call
   → MCP tool (e.g. read_memory)
      → GDBClient (RSP framing, stop-packet skipping)
         → PCSX2 EE GDB stub
            → emulated EE memory
   ← structured JSON  ← parsed payload
```

For timing-sensitive work (watchpoints) the lab bypasses the MCP on purpose:
`ps2lab.analysis.capture_write_source()` opens a raw RSP session, pauses, flushes
registers, arms a write watchpoint, resumes, waits for the asynchronous stop,
and disassembles around the faulting PC. The MCP session is re-established
afterwards.

## 4. Self-healing layers

| Layer | Detects | Repairs |
|---|---|---|
| MCP client (`reconnect`) | transport loss, failed negotiation | respawn + re-list tools (500 ms → 30 s backoff, 10 attempts) |
| `ps2lab.recovery.Supervisor` | process missing, GDB port closed, unresponsive window, PINE down, low disk | restart emulator, reconnect GDB, reload baseline savestate |
| E2E harness | phase-level exceptions | retries, phase isolation, baseline restore, JSON evidence |
| Model (this session) | unexpected behaviour | web research → hypothesis → patch → re-verify (KB-04…KB-16 are the results) |

## 5. Directory contract

* `config/` — regenerable configuration (`PCSX2.ini` seed, `mcp_patch.yml`, `ghidra.json`)
* `reports/` — machine-readable evidence, one JSON per concern; **the source of truth for PASS/FAIL**
* `shots/` — PNGs produced by E2E runs, named `<tag>_<step>.png`
* `logs/` — emulator log, `supervisor.jsonl`
* `work/` — scratch: extracted ELF, Ghidra projects, PCAP-free research notes

Nothing in `reports/` is hand-edited: every file is written by a script that
also wrote the corresponding log lines.

## 6. Ports and isolation

| Port | Owner | Binding |
|---|---|---|
| 10501 | PCSX2 EE GDB | 127.0.0.1 |
| 10502 | PCSX2 IOP GDB | 127.0.0.1 |
| 28011 | PCSX2 PINE | 127.0.0.1 |
| 56634 | DeepSeek Harness GUI | 127.0.0.1 |

No emulator control port is reachable from another host, and no external
service is exposed by the lab.
