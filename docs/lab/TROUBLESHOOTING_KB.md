# TROUBLESHOOTING_KB — PS2-CAM-00

Every entry follows the same schema: **symptom → error text → root cause →
affected versions → sources → fix applied → rejected alternatives →
verification → recurrence prevention**.

Check this file first when a symptom repeats. Do **not** re-apply an old fix
blindly: the same error string can have a different cause (see KB-09).

Environment baseline: Windows 11 10.0.26300, PCSX2 compatible build
`v2.7.499-12-g7235a0446`, PCSX2 2.8.2 stock, PCSX2_MCP
`a5748ad6` + `compat/ps2cam00` patches, Python 3.12.3, MCP SDK 2.3.0,
Ghidra 12.1.4, Emotion Engine: Reloaded 2.1.38, JDK 21.0.12.1.

---

## KB-01 — Git cannot clone over HTTPS (schannel credential failure)

**Symptom** — `git clone https://github.com/...` fails before any data transfer.

**Error**

```
fatal: unable to access 'https://github.com/snowyegret23/PCSX2_MCP.git/':
schannel: AcquireCredentialsHandle failed: SEC_E_NO_CREDENTIALS (0x8009030e)
```

**Root cause** — the shell runs under a restricted token that cannot open the
Windows crypto/credential store, so the schannel TLS backend cannot acquire a
client credential handle. OpenSSL does not need that store.

**Affected** — Git for Windows 2.56.0.windows.3 with `http.sslBackend=schannel`
(the default).

**Sources** — Git for Windows TLS docs (`http.sslBackend`), reproduced locally.

**Fix** — `git config --global http.sslBackend openssl` (lab applies this in
`scripts/install_lab.ps1` / bootstrap). Verified by cloning PCSX2_MCP
successfully.

**Rejected** — `-c http.sslVerify=false` (masks nothing; the failure is not
verification), GCM credential manager changes (not the failing layer).

**Verification** — `git clone https://github.com/snowyegret23/PCSX2_MCP.git`
succeeds; `git config --global --get http.sslBackend` → `openssl`.

**Prevention** — the setting is global for this machine; re-check it if a future
shell resets the global config.

---

## KB-02 — PowerShell cannot download files (0x8009030e again)

**Symptom** — `Invoke-WebRequest` fails on any HTTPS URL.

**Error** — `Invoke-WebRequest: Authentication failed, see inner exception.`

**Root cause** — same restricted-token/schannel problem as KB-01: .NET's HTTP
stack uses schannel.

**Fix** — all lab downloads go through Python (`urllib`), which uses OpenSSL and
its own CA bundle: `scripts/download_resumable.py`, `scripts/install_ghidra.py`.

**Verification** — PCSX2 release (`43 473 995` bytes) and Ghidra
(`569 649 598` bytes) downloaded and SHA-256-verified.

**Prevention** — never use `Invoke-WebRequest` in scripts here; the lab helpers
are the supported path.

---

## KB-03 — Stock PCSX2 2.8.2 has no GDB server and no qPcsx2

**Symptom** — `connect` to 10501/10502 is refused; nothing listens even after
enabling debugger options.

**Evidence** — string scan of `G:\Software\EmuCR-Pcsx2-Git-20150515\pcsx2-qt.exe`
(FileVersion 2.8.2.0): no `GDB`, `qPcsx2`, `EEGDBServerPort`,
`EnableEEGDBServer` strings at all. The MCP expects
`EmuCore/EnableEEGDBServer`, `EnableIOPGDBServer`, `EEGDBServerPort`,
`IOPGDBServerPort` (see `src/pcsx2_mcp/server.py::configure_gdb_settings`).

**Root cause** — those keys and the `qPcsx2` packet family exist only in the
maintainer's fork. A release build cannot be configured into supporting them.

**Source/decision** — upstream fork release
`PCSX2_x64_B_056de99_C_7235a04.zip` (43 473 995 bytes, SHA-256
`75c4ece2…5afbe6dca`, GPL-3.0). Downloaded, digest verified, extracted to
`C:\PS2CameraLab\pcsx2\fork-B056de99`.

**Verification** — the fork binary contains `qPcsx2:`, `EnableEEGDBServer`,
`EEGDBServerPort`, `screenshot_file`; ports 10501/10502 listen while a game runs.

**Prevention** — `TOOL_VERSIONS.md` pins the combination; the stock build stays
in the lab only as a comparison artifact.

---

## KB-04 — qPcsx2 multi-argument commands return "ERR usage" on the compatible build

**Symptom** — `debug_set_breakpoint`, `debug_disasm`, `input_set` always answer
`ERR usage …` even with correctly formatted arguments; single-argument commands
(`debug_remove_breakpoint`, `input_reset`, `debug_eval`, `save_slot`,
`frameadvance`) work.

**Error (examples)**

```
ERR usage debug_set_breakpoint <address> [temporary] [enabled] [hex_condition] [hex_description]
ERR usage debug_disasm <address> [count]
ERR usage input_set <controller> <binding> <0..1000>
```

**Investigation** — sentinel-aligned probe (each command followed by
`debug_eval <unique>`): replies stay aligned, so this is *not* stream
desynchronisation. The source of the fork build
(`pcsx2/DebugTools/GDBServer.cpp` at commit `7235a04`) parses these three
handlers through `split_args()`, and the deployed binary behaves as if that list
is empty. `debug_set_watchpoint` (also `split_args`) works, so the defect is
per-command in the shipped build.

**Root cause** — argument parsing defect in the custom build for those three
verbs; unfixable from configuration, and no matching point release is published.

**Fix (MCP-side compatibility layer, branch `compat/ps2cam00`)** — patch script
`scripts/apply_compat_patches.py`:
* `disassemble` falls back to local Capstone (MIPS64, little endian) over GDB
  memory reads → `method="capstone-gdb"`.
* `set_debug_breakpoint` falls back to GDB `Z1` packets → `method="gdb-Z1"`.
* `set_watchpoint` falls back to GDB `Z2` packets → `method="gdb-Z2"`.
* controller input uses the keyboard backend (`PostMessageW` to the render
  child) with PCSX2 keyboard bindings written by
  `configure_background_input`.

**Rejected** — patching the closed-source binary; rebuilding PCSX2 from source
(possible but a multi-GB MSVC/Qt build with no functional gain over the
fallbacks, and higher risk than the shims).

**Verification** — see `reports/feature_matrix.json` (`mcp` block: 28/28 PASS)
and `reports/e2e_results.json` phase C (`sd $ra, 0x40($sp)` captured through
the GDB `Z2` path).

**Prevention** — the patch script is idempotent and re-applied after any
`pip install -e .` refresh; the quirks are pinned in `CAMERA_RESEARCH_READINESS.md`.

---

## KB-05 — `debug_registers` without a category returns `E00`

**Symptom** — `get_debug_registers(target="ee")` fails while
`get_debug_registers(category=0)` succeeds.

**Error** — `qPcsx2 error 'E00' for 'debug_registers'`

**Root cause** — the full dump (all categories, 128-bit values as text) exceeds
the GDB packet buffer; the emulator answers with an error instead of chunking.

**Fix** — MCP fallback merges per-category replies
(`_debug_registers_per_category`, max 16 categories) and labels the result
`note="merged per category…"`.

**Verification** — `reports/feature_matrix.json` shows the empty-category call
still erroring on the emulator side (recorded as a known limitation) while the
merged MCP tool returns pc/cycles/HI/LO and every register.

**Prevention** — always request registers per category.

---

## KB-06 — `cycles=25,165,294` breaks register parsing

**Symptom** — `get_debug_registers` raises
`invalid literal for int() with base 10: '25,165,294'`.

**Root cause** — the emulator formats the cycle counter with thousands
separators; the MCP parser assumed a bare integer.

**Fix** — parser strips separators: `int(str(header.get("cycles","0")).replace(",","") or 0)`.

**Verification** — `reports/feature_matrix.json` MCP block;
`reports/pine_probe.json` shows the matching PINE/GDB memory cross-check.

**Prevention** — numeric parsing in the lab always tolerates separators.

---

## KB-07 — qPcsx2 screenshot fails with "failed to capture current frame"

**Symptom** — `take_screenshot` returns
`ERR failed to capture current frame` (and no PNG).

**Root cause (two causes, distinguished by evidence)**
1. **VM paused** — `MTGS::SaveMemorySnapshot` has no current frame to read.
   Connecting GDB pauses the VM; the earlier feature runs captured while
   paused. Resuming first makes the same command succeed
   (`method="qPcsx2 screenshot_file"`, 554×416 RGBA).
2. **Any remaining failure** (e.g. renderer edge cases) — the MCP now falls back
   to the inactive-window `PrintWindow` capture and reports
   `method="inactive-window"` plus `qpcsx2_error`.

**Fix** — lab scripts resume before capturing (`vision.capture_via_mcp` through
the supervisor) and the MCP fallback was added in the compatibility patch.

**Verification** — `reports/e2e_results.json` phase B/D screenshot steps;
`shots/e2e/**` contain the PNGs (e.g. 554×416, 5 000–11 000 unique colours).

**Prevention** — treat "paused" as a distinct pre-condition, not as a failure
of the screenshot path.

---

## KB-08 — The first GDB register read after `connect` is zeroed

**Symptom** — `get_registers` returns `pc=0x00081FC0, sp=0, ra=0, …` although
the game is running; a second read after a resume/pause cycle returns real
values (`pc=0x0032383C, sp=0x005FFB10`).

**Root cause** — with the EE recompiler the register file is only flushed at a
stop; the first read after attaching to a *running* VM observes stale values.

**Fix** — `ps2lab.analysis.refresh_registers()` resumes for ~0.35 s, pauses and
then reads; `snapshot_registers(fresh=True)` and `capture_write_source()` both
use it (with up to five retries until `sp` lies in EE RAM).

**Verification** — `reports/e2e_results.json` phase C (registers + watchpoint),
`reports/write_source_probe.json`.

**Prevention** — never trust a register read that immediately follows a
connect; always sample after a stop.

---

## KB-09 — PCSX2's GDB stub serves one client; probes and disconnects can kill the listener

**Symptom** — after phase B the EE listener is gone (`port 10501 closed`, IOP
still open), so phase C fails with `connect refused`; or a diagnostic probe
silently evicts the MCP connection.

**Root cause** — each connection pauses/resumes the VM and the server accepts a
single client; rapid connect/disconnect cycles plus a competing probe leave the
EE listener down. Emulog evidence:

```
[43.1652] DebugNetworkServer: EE GDB client connected on port 10501.
[43.1652] (VMManager) Resuming...
[57.0892] DebugNetworkServer: EE GDB client connected on port 10501.
```

**Fix**
* `Supervisor.probe_gdb()` is only called when the bridge is **not** connected
  (probing while connected evicted the MCP session — this was a real regression,
  fixed in `patch_stability.py`).
* `Supervisor.ensure_connected()` restarts the emulator when the listener is
  confirmed dead and then reconnects.

**Verification** — `reports/e2e_results.json` phase D (`reconnected without
manual repair`, `GDB reconnected after restart`), plus `logs/supervisor.jsonl`.

**Prevention** — hold one connection per phase; never run a second GDB client
while the MCP is attached; treat a closed port as a restart condition.

---

## KB-10 — PINE: not a named pipe here, and the framing is length-prefixed

**Symptom** — `\\.\pipe\pcsx2-pine` does not exist although `EnablePINE=true`.

**Investigation**
* `psutil` shows `pcsx2-qt.exe` listening on **TCP 127.0.0.1:28011**; no PINE
  pipe exists among the 311 system pipes.
* Sending `05 00 00 00 08` returns the version string; sending the opcode alone
  (no length prefix) hangs the server until the socket closes.

**Root cause** — this Windows build exposes PINE as a TCP socket whose port is
the configured slot, and the protocol is `u32 total_size | u8 opcode | args`
with a reply of `u32 total_size | u8 result | payload` (see
`pcsx2/PINE.cpp::ClientLoop`/`ParseCommand`).

**Fix** — `ps2lab/pine.py` connects over TCP (pipe fallback kept), frames with
the 4-byte length, parses length-prefixed strings for `MsgVersion`/`MsgTitle`/
`MsgID`.

**Verification** — `reports/pine_probe.json`: version
`PCSX2 v2.7.499-12-g7235a0446`, title `ファイナルファンタジーX-2`, id
`SLPS-25250`, `read32` matches GDB byte-for-byte, write+restore verified.

**Prevention** — one PINE client at a time (single-client server); close it in a
`finally` block.

---

## KB-11 — PINE savestate command returns 0xFF

**Symptom** — `save_state_slot` over PINE fails with
`opcode 0x10 failed (result=0xff)` while `MsgStatus`/reads work.

**Root cause** — the slot-savestate opcode is rejected by this build even while
the VM is running; the emulator-side precondition is not documented.

**Workaround** — use the qPcsx2 path (`save_slot`/`load_slot`/`save_file`),
which is verified working, and keep PINE for memory/status queries.

**Verification** — `reports/pine_probe.json` records the failure;
`reports/e2e_results.json` shows baseline save/restore through qPcsx2.

**Prevention** — `CAMERA_RESEARCH_READINESS.md` marks PINE savestates
unsupported.

---

## KB-12 — MCP log helpers look in `Documents\PCSX2` (portable install ignored)

**Symptom** — `get_log_path`/`tail_log_lines` return
`C:\Users\<user>\Documents\PCSX2\logs\emulog.txt` with `exists:false`, while the
real log is beside the executable.

**Root cause** — `_config_candidates()`/`log_reader.DEFAULT_CANDIDATES` assume a
non-portable install.

**Fix** — portable detection: `PS2LAB_PCSX2_DIR` env var plus the running
`pcsx2-qt.exe` directory are prepended to the candidate list
(`server.py`, `log_reader.py`).

**Verification** — `tail_log_lines` now returns real emulog lines from
`C:\PS2CameraLab\pcsx2\fork-B056de99\logs\emulog.txt`.

**Prevention** — the MCP registration sets `PS2LAB_PCSX2_DIR` explicitly.

---

## KB-13 — Japanese path breaks `python script.py` from the workspace

**Symptom** — `python C:\Users\…\ドキュメント\…\tools\dl.py` →
`can't open file '…\�h�L�������g\…'`.

**Root cause** — the workspace path contains non-ASCII characters and the
subprocess argument encoding is CP932; the interpreter cannot resolve the path.

**Fix** — all lab code, data and scripts live under the ASCII root
`C:\PS2CameraLab`. The workspace only holds the vendor checkout used for
reference.

**Verification** — every script in `scripts/` runs from the lab root.

**Prevention** — never add non-ASCII paths to `PATH`-fan-out tooling; pass
PowerShell `-LiteralPath` for the few reads that stay in the workspace.

---

## KB-14 — Ghidra 12.2 is incompatible with Emotion Engine: Reloaded

**Symptom** — the extension does not load / the R5900 language is missing.

**Root cause** — the release notes of `ghidra-emotionengine-reloaded v2.1.38`
(the latest at build time) list builds up to **Ghidra 12.1.4**; Ghidra 12.2 was
published later.

**Fix** — pin Ghidra 12.1.4 (`ddac49f9…` SHA-256) + EE Reloaded 2.1.38
(`e389ff3e…`), language id `r5900:LE:32:default`, JDK 21.

**Rejected** — building the extension from source against 12.2 (needs the full
Ghidra SDK and yields no benefit for the gate).

**Verification** — `reports/ghidra_summary.json` records the detected
`r5900:LE:32:default` language and the exported function index.

**Prevention** — `TOOL_VERSIONS.md` pins the pair; `install_ghidra.py` refuses
other combinations by construction.

---

## KB-15 — `java -version` reports 1.8 (Oracle shim) although JDK 17 is installed

**Symptom** — Ghidra's launcher aborts or runs on the wrong JDK.

**Root cause** — `C:\Program Files (x86)\Common Files\Oracle\Java\java8path`
precedes the JDK on `PATH`.

**Fix** — the lab sets `JAVA_HOME`/`PATH` for the Ghidra subprocess only
(`ghidra_analyze.run_headless`), pointing at `C:\PS2CameraLab\jdk` (Temurin
21.0.12.1). The system PATH is left untouched.

**Verification** — headless run reports OpenJDK 21 in
`reports/ghidra_summary.json`.

**Prevention** — never rely on ambient `java`; always pass the lab JDK.

---

## KB-16 — Large GitHub downloads stall silently

**Symptom** — the Ghidra ZIP stops at ~250 MiB and never finishes; no error.

**Root cause** — the CDN connection goes quiet without RST; a plain
`urllib.request.urlopen(...).read()` blocks forever.

**Fix** — `scripts/download_resumable.py`: 45 s socket timeout, HTTP `Range`
resume, SHA-256 check, up to 40 attempts. The Ghidra download completed on
attempt 2 (`569 649 598` bytes, digest verified).

**Verification** — digest equals the published SHA-256.

**Prevention** — every large fetch in the lab uses the resumable downloader.

---

## KB-17 — DeepSeek Harness profile edits need an application restart

**Symptom** — adding `@deepseek-ai/dsh-mcp-client` to
`~/.dsh/profiles/desktop/cordis.patch.yml` does not register new tools in the
running GUI session.

**Root cause** — the desktop profile is composed at app start
(`cordis.yml` + bundles + patch layers). The CLI refuses to boot it
(`profile "desktop" is managed exclusively by the Electron application`), and
the running app does not watch the patch file.

**Fix / operational note** — the patch is applied and validated
(`yaml.safe_load` → 5 entries), the MCP server definition is identical in
`config/mcp_patch.yml` for CLI profiles; activation in the GUI happens on the
next app start. `dsh headless` was used to prove the model-facing MCP flow but
cannot use the desktop account provider
(`ACCOUNT_SIGN_IN_REQUIRED` / `MISSING_CREDENTIAL`).

**Verification** — see `MCP_SETUP.md` and
`reports/feature_matrix.json` (the MCP server itself is verified through a real
JSON-RPC stdio session).

**Prevention** — `MCP_SETUP.md` documents the restart requirement and the
backup/restore procedure (`cordis.patch.yml.bak-*`).

---

## KB-18 — Ghidra headless rejects the R5900 language

**Symptom** — `analyzeHeadless -processor r5900:LE:32:default` aborts immediately.

**Error**

```
ghidra.util.exception.InvalidInputException: Unsupported language: r5900:LE:32:default
```

and, after the language files were placed on the core module path:

```
SleighException: Errors compiling ...\r5900.slaspec
```

**Root cause** — the Emotion Engine extension ships `r5900.slaspec` but **no
compiled `r5900.sla`**, and headless mode does not build extension modules;
after compiling the SLA manually, the language was still not on the module path
used by the headless launcher.

**Fix**
1. `support/sleigh.bat r5900.slaspec` in the extension's `data/languages`
   (produces `r5900.sla`; 8 benign "NOP constructor" warnings).
2. Copy the language set (`emotionengine.ldefs`, `r5900.{sla,slaspec,pspec,cspec,opinion,dwarf}`,
   `*.sinc`) into `Ghidra/Processors/MIPS/data/languages`, and `data/manuals`
   into `Ghidra/Processors/MIPS/data/` (removes the `eecore.idx` warning).
3. Re-run `analyzeHeadless ... -processor r5900:LE:32:default`.

**Verification** — `rc=0`, 5 843 functions exported in 76.8 s, live PC
`0x0032383C` resolves to `FUN_00323838` and `0x0027E58C` to `FUN_0027E578`
(`reports/ghidra_summary.json`).

**Rejected** — using the generic `MIPS:LE:64:64-32R6addr` language: it imports
(9 419 functions) but loses R5900/MMI semantics, which defeats the purpose.

**Prevention** — `SETUP.md` step 5 and `TOOL_VERSIONS.md` record the procedure;
`install_ghidra.py` intentionally stops before this manual step so the
divergence from stock Ghidra stays explicit.

**KB-04 addendum (watchpoints):** once the reply stream is aligned with
sentinels, `debug_set_watchpoint 0x… 0x… write break` also answers
`ERR invalid watchpoint type` — the same argument-parsing defect family. An
earlier "OK start=… end=…" observation was a *desynchronised* reply from a
previous command; that is why the lab always interleaves `debug_eval <unique>`
sentinels when characterising this packet family. GDB `Z2` is the working
watchpoint path (used by `analysis.capture_write_source`).

---

## KB-19 — A new plugin in `cordis.patch.yml` is silently ignored

**Symptom** — the MCP entry is written to the desktop profile, the application
restarts, but no `mcp__pcsx2__*` tool appears and no server process spawns.

**Error** — visible only with the offline composer:

```
dsh: [...\cordis.patch.yml] patch: entry "mcp-pcsx2" not found
```

**Root cause** — the patch layer only *overrides existing entries* by id. A new
plugin must be supplied through an `insert` list
(`dsh-app-boot/lib/index.js::applyEntryPatches`: `const { id, insert, name, ...overrides }`
→ branch `if (insert) … else data.push(...insert)`). A bare
`- id: mcp-pcsx2` row is treated as an override and skipped with a warning.

**Fix** — wrap the entry:

```yaml
- insert:
    - id: mcp-pcsx2
      name: "@deepseek-ai/dsh-mcp-client"
      config: { ... }
```

**Verification** — `dsh --profile <copy-of-desktop> --dump-config` composes
`- id: mcp-pcsx2 … serverName: pcsx2` with no warning; the desktop application
then exposes 72 tools as `mcp__pcsx2__*`, and the model called them successfully
(`reports/model_native_mcp.json`).

**Prevention** — validate every profile patch with a copy + `--dump-config`
before restarting the application; the lab keeps the known-good block in
`config/mcp_patch.yml`.

---

## KB-20 — Tools fail with "no visible PCSX2 window found" after `launch_pcsx2`

**Symptom** — `input_button_press` / `input_analog_send` / window capture return
`no visible PCSX2 window found` although the emulator runs.

**Root cause** — the MCP launcher starts PCSX2 detached with
`STARTF_USESHOWWINDOW` + `SW_HIDE` on purpose (background operation). Every Qt
window of that process is then `IsWindowVisible == 0`, so the Win32 input and
capture paths refuse to target it.

**Fix** — show the window without activating it:

```powershell
C:\PS2CameraLab\python\venv\Scripts\python.exe C:\PS2CameraLab\scripts\show_pcsx2_window.py
# ShowWindow(hwnd, SW_SHOWNA) on the Qt render window for the PCSX2 pid
```

`mcp__pcsx2__list_pcsx2_windows` then reports the window and both input
backends work (verified: `backend=keyboard/PostMessageW`, no foreground
activation).

**Rejected** — activating the window with `SetForegroundWindow` (steals focus
and changes emulator behaviour).

**Prevention** — after `launch_pcsx2`, call the helper once before using
input/capture tools; alternative is to start PCSX2 normally and attach.



---

## KB-21 — The window freezes when the emulator is killed (2026-11-02)

**Symptom** — the camera controller stops responding after PCSX2 is closed; closing the window takes
many seconds.

**Root cause** — a TCP connect to a closed localhost port takes the full timeout on Windows (2.03 s
measured), and the GUI made PINE calls on its UI thread at the 80 ms timer.

**Fix** — `PineBackend` raises `PineUnavailable` immediately for `retry_backoff` (1 s) after a failed
connect and uses a 0.3 s connect timeout; the GUI polls on `StatusPoller`; an explicit `connect()` ignores
the back-off. **Proof** — `tools/gui_freeze_check.py --kill --relaunch`; unit tests in
`tests/test_pine_backend.py`.

## KB-22 — PINE calls time out: a second PINE client is attached (2026-11-02)

**Symptom** — every PINE read times out although PCSX2 runs.

**Root cause** — PCSX2's PINE server serves one client at a time. A leftover script (for example a soak
test started with `&` inside a foreground shell call, which the tool does not kill) or the GUI holds it.

**Fix** — one PINE client at a time; start long scripts as background tasks of the tool, never poll PINE
meanwhile, and list stragglers with `Get-Process python*`.

## KB-23 — "The value reverts at once": the VM was paused (2026-11-02)

**Symptom** — a write to a game address appears to be undone within 20 ms, or does not stick at all.

**Root cause** — after any MCP debugger call (`connect`, watchpoint, backtrace) the VM may be paused or
stopped at a hit; the first experiments compared a running and a paused VM.

**Fix** — call `resume` after `load_state_file` and after debugger calls, wait about a second, and check
`pcsx2_status` (`state=running`) before judging a write.

## KB-24 — A PCSX2 started from a test inherits the offscreen Qt platform (2026-11-02)

**Symptom** — PCSX2 launched by a GUI test script never shows PINE and vanishes.

**Root cause** — the script sets `QT_QPA_PLATFORM=offscreen` for the test GUI and the child process inherits it.

**Fix** — start the emulator with the `QT_*` variables removed from the environment (`tools/gui_freeze_check.py`).
