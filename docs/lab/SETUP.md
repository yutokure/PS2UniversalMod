# SETUP — rebuild this lab from a bare Windows machine

Everything below was executed in this order on 2026-10-28. Commands are
idempotent unless marked.

## 0. Prerequisites

* Windows 11 x64, ≥ 8 GB RAM, ≥ 20 GB free on the target drive
* PowerShell 7 (`pwsh`)
* Python 3.12 (`C:\Program Files\Python312`) — 3.10+ works
* Git for Windows
* 7-Zip 26.x
* DeepSeek Harness 0.2.1-rc.3 (desktop)
* A legally obtained PS2 BIOS and game ISO (user-owned; not included)

## 1. Fix the TLS layer first (KB-01 / KB-02)

```powershell
git config --global http.sslBackend openssl
```

Do **not** use `Invoke-WebRequest` for downloads in this environment; use the
Python helper described below.

## 2. Create the tree and copy the emulator

```powershell
$Lab = 'C:\PS2CameraLab'
'bin','vendor','pcsx2','pcsx2\bios','pcsx2\iso','python','ghidra','config','scripts',
'tests','reports','logs','shots','sstates','work','docs','backups','downloads' |
  ForEach-Object { New-Item -ItemType Directory -Force -Path (Join-Path $Lab $_) | Out-Null }

# stock install (user-provided) — comparison artifact
robocopy 'G:\Software\EmuCR-Pcsx2-Git-20150515' "$Lab\pcsx2\stock-2.8.2" /E /NFL /NDL

# compatible build (GDB + qPcsx2), digest-verified
C:\PS2CameraLab\python\venv\Scripts\python.exe C:\PS2CameraLab\scripts\download_resumable.py `
  https://github.com/snowyegret23/pcsx2/releases/download/PCSX2_x64_B_056de99_C_7235a04/PCSX2_x64_B_056de99_C_7235a04.zip `
  C:\PS2CameraLab\downloads\PCSX2_fork.zip `
  75c4ece2eea7e504e68f037b3e72416d962226c6b9558e4875ad07d5afbe6dca
& 'C:\Program Files\7-Zip\7z.exe' x C:\PS2CameraLab\downloads\PCSX2_fork.zip -oC:\PS2CameraLab\pcsx2\fork-B056de99 -y

# BIOS and the working ISO copy
robocopy "$Lab\pcsx2\stock-2.8.2\bios" "$Lab\pcsx2\fork-B056de99\bios" /E /NFL /NDL
Copy-Item "$Lab\pcsx2\stock-2.8.2\portable.ini" "$Lab\pcsx2\fork-B056de99\portable.ini"
Copy-Item 'G:\Software\ps2\Final Fantasy X-2 (Japan).iso' "$Lab\pcsx2\iso\Final Fantasy X-2 (Japan).iso"
```

Verify: `fork-B056de99\pcsx2-qt.exe` contains the strings `qPcsx2:`,
`EnableEEGDBServer`, `screenshotPath` (KB-03 explains why).

## 3. Emulator configuration

`pcsx2\fork-B056de99\inis\PCSX2.ini` (portable install — the file lives next to
the executable, not in `Documents`):

```ini
[UI]
SettingsVersion = 1
ConfirmShutdown = false
PauseOnFocusLoss = false
[Folders]
Bios = bios
Savestates = sstates
Logs = logs
[EmuCore]
EnableEEGDBServer = true
EnableIOPGDBServer = true
EEGDBServerPort = 10501
IOPGDBServerPort = 10502
EnablePINE = true
PINESlot = 28011
[EmuCore/GS]
Renderer = -1
[Filenames]
BIOS = SCPH-70000_BIOS_V12_JAP_200.BIN
```

First run creates the folder skeleton; then close it with `WM_CLOSE` so the
settings are flushed. The MCP tool `configure_gdb_settings` can write the four
GDB keys for you:

```
$PY -c "from ps2lab.mcp_bridge import open_bridge; b=open_bridge(); print(b.call('configure_gdb_settings', {'config_path': r'C:\PS2CameraLab\pcsx2\fork-B056de99\inis\PCSX2.ini'}))"
```

Also write the background input bindings (needed for automated input):

```
$PY -c "from ps2lab.mcp_bridge import open_bridge; b=open_bridge(); print(b.call('configure_background_input', {'config_path': r'C:\PS2CameraLab\pcsx2\fork-B056de99\inis\PCSX2.ini'}))"
```

Restart PCSX2 afterwards so it loads the bindings.

## 4. Python environment

```powershell
$py = 'C:\Program Files\Python312\python.exe'
& $py -m venv C:\PS2CameraLab\python\venv
$vp = 'C:\PS2CameraLab\python\venv\Scripts\python.exe'
& $vp -m pip install --upgrade pip
& $vp -m pip install "mcp[cli]>=2.0.0,<3" "psutil>=5.9" pytest pytest-timeout capstone pillow pyyaml
git clone https://github.com/snowyegret23/PCSX2_MCP.git C:\PS2CameraLab\vendor\PCSX2_MCP
Push-Location C:\PS2CameraLab\vendor\PCSX2_MCP; & $vp -m pip install -e .; Pop-Location
& $vp C:\PS2CameraLab\scripts\apply_compat_patches.py
```

## 5. Ghidra stack

```powershell
& $vp C:\PS2CameraLab\scripts\install_ghidra.py
# then register the R5900 language for headless use (KB-18):
$gh = 'C:\PS2CameraLab\ghidra\ghidra_12.1.4_PUBLIC'
$ext = "$gh\Extensions\Ghidra\ghidra-emotionengine-reloaded\data\languages"
Push-Location $ext; & "$gh\support\sleigh.bat" r5900.slaspec; Pop-Location
Copy-Item "$ext\*" "$gh\Ghidra\Processors\MIPS\data\languages\" -Force
Copy-Item "$gh\Extensions\Ghidra\ghidra-emotionengine-reloaded\data\manuals" "$gh\Ghidra\Processors\MIPS\data\" -Recurse -Force
```

Verify:

```powershell
& "$gh\support\analyzeHeadless.bat" C:\PS2CameraLab\work\ghidra_projects probe `
  -import C:\PS2CameraLab\work\elf\SLPS_252.50 -processor r5900:LE:32:default -noanalysis
```

Expected: `Import succeeded`.

Extract the analysis target from the ISO:

```powershell
& 'C:\Program Files\7-Zip\7z.exe' x "C:\PS2CameraLab\pcsx2\iso\Final Fantasy X-2 (Japan).iso" -oC:\PS2CameraLab\work\elf -y
```

## 6. DeepSeek Harness registration

Follow `MCP_SETUP.md` (backup, append the `mcp-pcsx2` entry, validate YAML,
restart the application).

## 7. Smoke test

```powershell
$PY scripts\mcp_probe.py --cycles 2        # protocol
$PY scripts\feature_matrix.py              # capabilities
$PY scripts\pine_probe.py                  # PINE
$PY -m pytest -q                            # tests
$PY scripts\e2e_run.py --phases A,B,C,D     # end to end
```

## 8. Troubleshooting during setup

Read `TROUBLESHOOTING_KB.md` first. The three most likely surprises on a fresh
machine:

1. `git clone` fails with `SEC_E_NO_CREDENTIALS` → step 1.
2. GDB ports closed → the compatible build is not the one being launched, or the
   ini lives in `Documents\PCSX2` instead of the portable folder.
3. `python` cannot open a script path with non-ASCII characters → keep the lab
   under `C:\PS2CameraLab` (KB-13).

## 9. What is *not* restored by this document

* the user's BIOS/ISO (must come from the user),
* DeepSeek account credentials (managed by the harness),
* Windows-level tweaks (none were made).
