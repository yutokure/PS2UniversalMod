# MCP_SETUP — PCSX2 MCP × DeepSeek Harness

This document records exactly how the PCSX2 MCP server is built, registered in
DeepSeek Harness, verified, and recovered.

## 1. Server implementation

| Item | Value |
|---|---|
| Repository | https://github.com/snowyegret23/PCSX2_MCP |
| Commit | `a5748ad6944ccb9bbb9529a4a9d63aa5b9ff48f7` ("Update for MCP SDK 2.x compatibility", 2026-08-09) |
| Local path | `C:\PS2CameraLab\vendor\PCSX2_MCP` |
| Branch with lab patches | `compat/ps2cam00` (see `scripts/apply_compat_patches.py`) |
| Interpreter | `C:\PS2CameraLab\python\venv\Scripts\python.exe` |
| SDK | `mcp 2.3.0` (+ `psutil 7.2.2`) |
| Transport | stdio (JSON-RPC over the child process's stdin/stdout) |
| Tools exposed | 72 (`tools/list`) |

Install (already applied):

```powershell
cd C:\PS2CameraLab\vendor\PCSX2_MCP
C:\PS2CameraLab\python\venv\Scripts\python.exe -m pip install -e .
C:\PS2CameraLab\python\venv\Scripts\python.exe C:\PS2CameraLab\scripts\apply_compat_patches.py
```

The patch script is idempotent; re-run it after any reinstall.

## 2. Harness registration (official MCP client)

Package: `@deepseek-ai/dsh-mcp-client` (bundled with DeepSeek Harness
0.2.1-rc.3). Configuration format verified against the installed package
documentation (`vendor/dsh_src/.../dsh-mcp-client/README.md`): one entry per
server, fields `serverName`, `transport`, `command`, `args`, `cwd`, `env`,
`toolCallTimeoutMs`, `failOnStartupError`, `reconnect.*`.

The entry appended to `%USERPROFILE%\.dsh\profiles\desktop\cordis.patch.yml`
(backup: `cordis.patch.yml.bak-20261028-212440` and
`C:\PS2CameraLab\backups\`):

```yaml
# A NEW plugin must be inserted, not overridden: the patch loader
# only matches `- id:` rows against existing entries (see KB-19).
- insert:
    - id: mcp-pcsx2
      name: "@deepseek-ai/dsh-mcp-client"
  config:
    serverName: pcsx2
    transport: stdio
    command: 'C:\PS2CameraLab\python\venv\Scripts\python.exe'
    args: ['-m', 'pcsx2_mcp']
    cwd: 'C:\PS2CameraLab\vendor\PCSX2_MCP'
    env:
      PS2LAB_PCSX2_DIR: 'C:\PS2CameraLab\pcsx2\fork-B056de99'
      PYTHONUTF8: '1'
      PYTHONIOENCODING: 'utf-8'
    toolCallTimeoutMs: 180000
    failOnStartupError: false
    reconnect:
      enabled: true
      initialDelayMs: 500
      maxDelayMs: 30000
      maxAttempts: 10
```

Validation:

```powershell
C:\PS2CameraLab\python\venv\Scripts\python.exe -c "import yaml;d=yaml.safe_load(open(r'%USERPROFILE%\.dsh\profiles\desktop\cordis.patch.yml',encoding='utf-8'));print([e['id'] for e in d])"
# ['agent-default-model', 'ui-settings-account', 'ui-chat', 'ui-settings', 'mcp-pcsx2']
```

Tools then appear to the model as `mcp__pcsx2__<tool>` (for example
`mcp__pcsx2__status`, `mcp__pcsx2__read_memory`).

### Activation (verified)

After the corrected patch, the desktop application exposes the server's 72 tools to the
model as `mcp__pcsx2__*`. A full model-driven session is recorded in
`reports/model_native_mcp.json`: launch → connect (EE/IOP) → load state → status →
screenshot → registers → disassemble → button input (guest reacted) → pattern search →
save/load slot → memory diff → disconnect → reconnect.

### Activation note (historical)

The desktop profile is composed when the application starts; the running GUI
does not reload `cordis.patch.yml`. The CLI refuses to boot the `desktop`
profile (`profile "desktop" is managed exclusively by the Electron
application`), and a CLI profile cannot use the desktop account provider
(`ACCOUNT_SIGN_IN_REQUIRED` / `MISSING_CREDENTIAL`). Activating the entry in the
GUI therefore requires one DeepSeek Harness restart — the configuration is
already in place and validated. See `BLOCKERS.md` B-01.

The identical server definition is kept in `config/mcp_patch.yml` so any CLI
profile can be booted with `--patch` once credentials are available:

```powershell
dsh headless --patch C:\PS2CameraLab\config\mcp_patch.yml "call the pcsx2 status tool"
```

## 3. Protocol verification performed

`scripts/mcp_probe.py` drives a real stdio session (no shortcuts):

| Check | Result |
|---|---|
| `initialize` handshake | PASS — server `pcsx2-mcp` |
| `tools/list` | PASS — 72 tools |
| `tools/call` (`list_pcsx2_processes`) | PASS |
| `tools/call` (`status`, disconnected) | PASS — structured `ok:true` with both targets |
| Error path — connect to closed port | PASS — clean `ok:false` after 2.05 s |
| Unknown tool | PASS — rejected (`isError` result / exception) |
| Repeated start/stop cycles | PASS — 3 cycles, see `reports/mcp_protocol_test.json` |

Full feature matrix of the 72 tools against the live emulator:
`reports/feature_matrix.json` (MCP block: 28/28 PASS).

## 4. Recovery behaviour

* `reconnect.enabled: true` with 500 ms → 30 s exponential backoff, 10 attempts.
* The lab supervises the emulator side as well (`ps2lib/recovery.py`):
  process check, GDB port probe, PINE status, window responsiveness, disk/RAM.
* A dead EE listener is treated as a restart condition (KB-09).
* `toolCallTimeoutMs: 180000` covers `save_state_file`/`load_state_file`
  (savestate I/O on a 4 GB disc can take tens of seconds).

## 5. Rollback

```powershell
Copy-Item %USERPROFILE%\.dsh\profiles\desktop\cordis.patch.yml.bak-20261028-212440 `
          %USERPROFILE%\.dsh\profiles\desktop\cordis.patch.yml -Force
```

Restarting the application afterwards returns the harness to the pre-lab
configuration.
