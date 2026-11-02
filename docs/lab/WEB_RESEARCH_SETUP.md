# WEB_RESEARCH_SETUP — Web capability of DeepSeek Harness

## 1. Providers in use

| Capability | Tool (model-facing) | Implementation | Auth |
|---|---|---|---|
| Web search | `web_search` | `@deepseek-ai/dsh-tool-web` → `@deepseek-ai/dsh-web` with the DeepSeek account search provider | Account session of DeepSeek Harness (no API key handled by the lab) |
| Page fetch | `web_fetch` | `@deepseek-ai/dsh-tool-web` fetch providers (`dsh-web-fetch-http` family) | none (public HTTP/HTTPS) |

The tools were already registered in the `desktop` profile
(`@deepseek-ai/dsh-base` + `@deepseek-ai/dsh-web-app` bundles); nothing was
duplicated or re-implemented. `session_search`/`session_fetch` were **not**
added.

Verification that the wiring exists in the installed runtime:

* `app.asar` (Electron package, 182 434 783 bytes) contains
  `@deepseek-ai/dsh-web@0.2.1-rc.3`, `dsh-tool-web@0.2.1-rc.3`,
  `dsh-web-deepseek-api@0.2.1-rc.3` and `dsh-mcp-client@0.2.1-rc.3`
  (enumerated from the asar header index; see `scripts/../vendor/dsh_src`).

## 2. Search test (WEB-01)

Query: `PCSX2 MCP snowyegret23`, `PCSX2 MCP server qPcsx2 GDB`.
Result: titles + URLs returned, e.g.

* `https://glama.ai/mcp/servers/snowyegret23/PCSX2_MCP`
* `https://github.com/hkmodd/PCSX2-MCP`
* `https://glama.ai/mcp/servers/snowyegret23/PCSX2_MCP/tools/connect`

Logged in `reports/web_research_log.json` (`WEB-01`).

## 3. Page fetch test (WEB-02)

* `https://github.com/snowyegret23/PCSX2_MCP` — HTTP 200, README body retrieved
  (124 lines) including the "IMPORTANT" compatibility note that `qPcsx2` needs a
  compatible PCSX2 build.
* Raw source fetch of `pcsx2/DebugTools/GDBServer.cpp`, `PINE.cpp`,
  `DebugInterface.h` at commit `7235a0446954b98f4ecb1476d8050d7fb3256e7e`
  (58 087 / 20 593 bytes) — full text inspected, not summaries.
* GitHub REST API used for release metadata
  (`/repos/snowyegret23/pcsx2/releases`, `/repos/NationalSecurityAgency/ghidra/releases`,
  `/repos/chaoticgd/ghidra-emotionengine-reloaded/releases`).

## 4. GitHub investigation test (WEB-03)

Facts confirmed from primary sources (not summaries):

1. `PCSX2_MCP` README + `src/pcsx2_mcp/server.py` show EE/IOP GDB targets on
   10501/10502 and that emulator commands need `qPcsx2`.
2. The maintainer publishes a **PCSX2 fork** (`snowyegret23/pcsx2`, GPL-3.0) and
   a release asset `PCSX2_x64_B_056de99_C_7235a04.zip`; the `dsh`-side
   compatibility keys (`EnableEEGDBServer`, `EEGDBServerPort`) appear only
   there.
3. `GDBServer.cpp` defines the `qPcsx2:` packet and the command family
   (`status`, `debug_*`, `save_slot`, `screenshot_file`, `input_set`, …).

## 5. Use of researched facts (WEB-04)

| Source | Version | Fact | Local comparison |
|---|---|---|---|
| PCSX2_MCP README | `a5748ad6` | "Extended tools … require a compatible PCSX2 build that implements the `qPcsx2` commands" | Stock 2.8.2 binary has no `qPcsx2` string; the fork binary does |
| PCSX2 fork release notes | `PCSX2_x64_B_056de99_C_7235a04` | shipped asset size 43 473 995 bytes, sha256 `75c4ece2…` | downloaded file matches the digest exactly |
| EE Reloaded release `v2.1.38` | 2026-10-04 | supports Ghidra up to 12.1.4 | installed Ghidra 12.1.4, language `r5900:LE:32:default` |
| Ghidra 12.2 release | 2026-10-22 | newer than the extension's support matrix | rejected 12.2, pinned 12.1.4 |

## 6. Failure-handling test (WEB-05)

Performed as part of `E2E-E` (`D:` + `E:` phases in `reports/e2e_results.json`):

1. Injected fault: `EEGDBServerPort = 10501 → 10599` in the portable
   `PCSX2.ini` (backup taken first to `backups/PCSX2.ini.e2e-backup`).
2. Detected: `connect` failed, `port 10501` closed while 10502 stayed open.
3. Diagnosed against the documented key semantics
   (`server.py::configure_gdb_settings` and KB-03) instead of guessing.
4. Repaired the key, restarted the emulator.
5. Re-verified: EE connect, memory read, savestate restore.
6. Restored the pristine configuration and confirmed the file hash.

The lab never needed instructions from the user to complete this loop; the
research trail is in `reports/web_research_log.json` and
`reports/troubleshooting_history.json`.

## 7. Reliability rules applied

* Primary sources only for design decisions (official docs → repo source →
  issues/PRs → release notes), and the *source* was preferred over prose.
* Publication dates and supported-version ranges checked before adopting a
  version (KB-14 rejected Ghidra 12.2).
* Third-party binaries accepted only with a published SHA-256 that was verified
  locally (PCSX2 fork, Ghidra, EE Reloaded, JDK).
* Web content treated as data: no instruction from a fetched page was executed.
* Credentials were never printed or committed; the account session stays inside
  DeepSeek Harness.
