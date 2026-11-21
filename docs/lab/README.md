# PS2-CAM-00 — 親ラボの構成と検証記録

**GUI を起動する方は[公開ソースの README](../../README.md)へ。** 通常のカメラ操作は GUI から PCSX2 の PINE に接続します。GDB 対応フォーク、MCP、Ghidra、DeepSeek Harness は必要ありません。

ここは解析に使った Windows 環境の記録です（2026-11-02 に文書を移管）。`C:\PS2CameraLab` は当時の親ラボであり、このリポジトリの設置先ではありません。下記の `scripts/`、MCP のローカル修正、エミュレータ、BIOS・ISO・ステート、`reports/`・`shots/`・`logs/` の証跡一式は同梱していません。コマンドは当時何を実行したかを示すもので、チェックアウトだけからの再現手順ではありません。

当時のラボでは MCP 経由でゲームを操作・観測し、Ghidra で ELF を静的解析しました。次段階として掲げた研究課題は次のとおりです。

> 「FF10のカメラ制御処理を解析し、自由カメラ化に必要なプログラムとデータを特定してください」

## 親ラボで確認した項目

表のファイル名は当時の親ラボに保存した証跡を指します。PASS はその環境・対象ディスク・試験項目の結果で、公開ソースの全機能を今回再検証したという意味ではありません。

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

## 当時の親ラボの配置

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

## 親ラボで実行したコマンド例（公開 GUI の起動手順ではない）

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

## 資料の探し方

| 資料 | わかること |
|---|---|
| [構成](ARCHITECTURE.md)・[セットアップ](SETUP.md)・[ツールの版](TOOL_VERSIONS.md) | 当時の接続経路、依存ツールの版と選定理由、配布物の照合値 |
| [MCP 接続](MCP_SETUP.md)・[Web 調査](WEB_RESEARCH_SETUP.md) | Harness への登録・復旧、WEB-01〜05 の検証 |
| [自動復旧](AUTONOMOUS_TROUBLESHOOTING.md)・[障害 KB](TROUBLESHOOTING_KB.md) | 何を検知してどこまで復旧したか、24件の症状・原因・対処 |
| [CLI](CLI_REFERENCE.md)・[試験表](TEST_MATRIX.md) | 親ラボのコマンドと出力先、要件別の結果・証跡名 |
| [未解決事項と追記](BLOCKERS.md)・[研究準備状況](CAMERA_RESEARCH_READINESS.md) | 当時の未解決事項、その後の経過、次の調査に使えた機能 |

## 親ラボでのデータ保護・接続条件

* BIOS/ISO/save data of the user are never modified; the lab uses copies
  (`pcsx2\iso`, `pcsx2\fork-B056de99\bios`).
* GDB (10501/10502) and PINE (28011) bind to `127.0.0.1` only.
* Memory experiments write to a scratch page and restore the original bytes;
  savestates are addressed by explicit slots.
* No Windows security feature is disabled; no kernel driver is installed.
* Credentials are never written to reports or logs.

