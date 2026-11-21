# TOOL_VERSIONS — 親ラボで検証したツールの組み合わせ

以下は[親ラボ](README.md)の調査対象を識別する版・ハッシュ・配置で、公開 GUI の推奨版一覧ではありません。特に GDB／`qPcsx2` 用の PCSX2 フォークと MCP のローカル修正は解析専用です。通常利用の前提は[公開ソースの README](../../README.md)を参照してください。

All entries were installed and exercised on 2026-10-28 unless stated otherwise.
"Verified" means the exact artifact ran successfully in this lab.

## Core platform

| Component | Version | Source | Install path | Verified |
|---|---|---|---|---|
| Windows | 11 (10.0.26300, 26H2) | preinstalled | — | OS/CPU/RAM inventory |
| CPU | AMD64 Family 25 Model 116, 8C/16T | preinstalled | — | 16 logical CPUs |
| RAM | 15.2 GB | preinstalled | — | inventory |
| Disk | C: 475.6 GB (117 GB free), G: 1.86 TB | preinstalled | — | inventory |

## Emulation

| Component | Version | Source | Path | Why this one |
|---|---|---|---|---|
| PCSX2 (stock) | 2.8.2.0 (`EmuCR-Pcsx2-Git-20150515`) | user-provided `G:\Software\...` | `C:\PS2CameraLab\pcsx2\stock-2.8.2` | comparison artifact only — contains **no** GDB/qPcsx2 strings |
| PCSX2 (compatible) | `v2.7.499-12-g7235a0446`, asset `PCSX2_x64_B_056de99_C_7235a04.zip` (43 473 995 B, sha256 `75c4ece2…5afbe6dca`) | [snowyegret23/pcsx2 release](https://github.com/snowyegret23/pcsx2/releases/tag/PCSX2_x64_B_056de99_C_7235a04), GPL-3.0 | `C:\PS2CameraLab\pcsx2\fork-B056de99` | only build with `EnableEEGDBServer` + `qPcsx2` |
| BIOS | `SCPH-70000_BIOS_V12_JAP_200.BIN` (copied from the stock install) | user-provided | `...\fork-B056de99\bios` | JP console for the JP test disc |
| Test disc | Final Fantasy X-2 (Japan), 3 972 890 624 B, sha256 `4c1b997a…e1c1f4a3` | user-provided, working copy | `...\iso\Final Fantasy X-2 (Japan).iso` | required by the brief |
| Game ELF | `SLPS_252.50`, 3 700 636 B, sha256 `c3e8ba3c…772407ad` | extracted from the ISO with 7-Zip | `C:\PS2CameraLab\work\elf` | static analysis target |

## Tooling

| Component | Version | Source | Notes |
|---|---|---|---|
| Python (system) | 3.12.3 | `C:\Program Files\Python312` | interpreter for the lab venv |
| Python (lab venv) | 3.12.3 | `C:\PS2CameraLab\python\venv` | `mcp 2.3.0`, `psutil 7.2.2`, `capstone 5.0.9`, `Pillow 13.0.0`, `pytest 9.2.0`, `pytest-timeout 2.4.0`, `PyYAML 6.0.3` |
| PCSX2 MCP | commit `a5748ad6` + `compat/ps2cam00` | [snowyegret23/PCSX2_MCP](https://github.com/snowyegret23/PCSX2_MCP) (MIT) | 72 tools, stdio |
| MCP SDK | 2.3.0 | PyPI | required by the MCP server (`mcp[cli]>=2,<3`) |
| Git | 2.56.0.windows.3 | system | `http.sslBackend=openssl` (KB-01) |
| Node.js | 26.12.1 (system) / 24.21.0 (bundled with DSH) | system / `resources/runtime` | used for asar inspection only |
| 7-Zip | 26.05 (x64) | `C:\Program Files\7-Zip` | ISO/ELF extraction, archive handling |
| JDK (system PATH) | Oracle 1.8.0_511 shim + Temurin 17 `JAVA_HOME` | system | deliberately **not** used for Ghidra (KB-15) |
| JDK (lab) | Temurin 21.0.12.1+1 LTS | [Adoptium API](https://api.adoptium.net/v3/binary/latest/21/ga/windows/x64/jdk/hotspot/normal/eclipse) | `C:\PS2CameraLab\jdk` |
| Ghidra | 12.1.4 (2026-09-21), 569 649 598 B, sha256 `ddac49f9…d2d4db` | [NSA ghidra release](https://github.com/NationalSecurityAgency/ghidra/releases/tag/Ghidra_12.1.4_build) | headless analysis |
| Emotion Engine: Reloaded | v2.1.38 (2026-10-04), 917 780 B, sha256 `e389ff3e…09f240b` | [chaoticgd release](https://github.com/chaoticgd/ghidra-emotionengine-reloaded/releases/tag/v2.1.38) | language `r5900:LE:32:default` |
| DeepSeek Harness (desktop) | 0.2.1-rc.3 | installed application | MCP client `@deepseek-ai/dsh-mcp-client@0.2.1-rc.3` |
| Web tools | `@deepseek-ai/dsh-tool-web` / `dsh-web` 0.2.1-rc.3 | bundled | `web_search` + `web_fetch` |

## Deliberately rejected

| Candidate | Why rejected |
|---|---|
| Ghidra 12.2 | EE Reloaded v2.1.38 ships builds only up to 12.1.4 (KB-14) |
| Stock PCSX2 2.8.2 as the automation target | no GDB stub, no `qPcsx2` (KB-03) |
| ViGEmBus + `vgamepad` virtual XInput | kernel driver install requires administrator approval and a reboot; the keyboard backend covers the gate (see `BLOCKERS.md` B-03) |
| Patching the closed PCSX2 binary | no source-level change possible without a full MSVC/Qt rebuild; MCP-side shims verified instead (KB-04) |

## 当時のツールと版を確認したコマンド（親ラボのスクリプトが必要）

```powershell
# 1. bootstrap directories + stock copy + compatible build  (see SETUP.md)
# 2. python venv + MCP + compat patches
C:\PS2CameraLab\python\venv\Scripts\python.exe -m pip install -e C:\PS2CameraLab\vendor\PCSX2_MCP
C:\PS2CameraLab\python\venv\Scripts\python.exe C:\PS2CameraLab\scripts\apply_compat_patches.py
# 3. Ghidra + JDK 21 + EE Reloaded (SHA-256 pinned in the script)
C:\PS2CameraLab\python\venv\Scripts\python.exe C:\PS2CameraLab\scripts\install_ghidra.py
# 4. inventory snapshot
C:\PS2CameraLab\python\venv\Scripts\python.exe C:\PS2CameraLab\scripts\collect_inventory.py
```

The machine-readable version of this table is
`reports/environment_inventory.json`.
