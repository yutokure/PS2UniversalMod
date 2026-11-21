# BLOCKERS — 親ラボでの未解決事項とその後の追記

各項目の OPEN / RESOLVED、next step は[親ラボ](README.md)の当該調査・ビルド時点の判断です。後日の追記を含めて経過を残しています。公開 GUI の既知の制限は[利用ガイド](../../README.md)、ゲーム固有の確認範囲は[文書索引](../README.md)の各タイトルを参照してください。

## B-01 — RESOLVED: `mcp__pcsx2__*` tools active in the GUI session

**Status**: resolved. The root cause was the patch syntax: a new plugin needs an
`insert` list, otherwise the loader treats the row as an override of a missing entry
and skips it (KB-19). After the fix and one application restart the harness exposed
72 tools to the model, which then drove the emulator end to end
(`reports/model_native_mcp.json`).

The historical description below is kept for traceability.

**What works today**: the MCP server is registered in the `desktop` profile
(`~/.dsh/profiles/desktop/cordis.patch.yml`, entry `mcp-pcsx2`, validated with
`yaml.safe_load`), the server itself is verified through a real stdio JSON-RPC
session (72 tools, `reports/mcp_protocol_test.json`, `reports/feature_matrix.json`),
and the same server definition is used by `scripts/e2e_run.py` for every E2E
cycle.

**Why it is blocked**: the desktop profile is composed at application start and
the running GUI does not watch `cordis.patch.yml`. The CLI refuses to boot the
`desktop` profile (`profile "desktop" is managed exclusively by the Electron
application`), and a CLI profile cannot use the desktop account provider
(`MISSING_CREDENTIAL` / `ACCOUNT_SIGN_IN_REQUIRED`).

**Next step** (one action, no technical work): restart DeepSeek Harness. The
startup log will show the `pcsx2` server connecting, and the tools appear as
`mcp__pcsx2__*` in the model's toolset. Rollback: restore
`cordis.patch.yml.bak-20261028-212440`.

**Risk**: none — the patch was validated before being written and a backup
exists in two locations.

## B-02 — Native `qPcsx2 input_set` verb is unusable in the pinned build

**Status**: replaced by a verified alternative (keyboard backend).

**Cause**: the compatible build rejects every argument set for
`debug_set_breakpoint`, `debug_disasm` and `input_set` ("ERR usage …"), while
`debug_set_watchpoint` accepts arguments. Sentinel-aligned probing ruled out
stream desynchronisation. See KB-04.

**Alternative in use**: Win32 `PostMessageW` keyboard events to the verified
render child window, with PCSX2 keyboard bindings written by
`configure_background_input` (Cross=K, Start=Return, RRight=H, RUp=T …).

**Difference from native input**: digital (full-deflection) stick movement
instead of 8-bit analog values. Camera experiments that need sub-degree
precision should use one of:
1. a virtual XInput device (ViGEmBus + `vgamepad`) — needs administrator
   approval and a driver install; asked before attempting;
2. PCSX2 input-recording playback (`.p2m2`) as a deterministic analog source;
3. rebuilding the fork with the argument-parsing fix (source available, GPL-3.0,
   but a full MSVC/Qt build).

**Next step**: decide which of the three is acceptable for PS2-CAM-01.

## B-03 — Virtual XInput controller (ViGEmBus) not installed

**Status**: not installed by design.

**Cause**: the driver requires administrator rights and a reboot; the brief
forbids elevating without consent and the keyboard path already satisfies the
gate.

**Next step**: if analog fidelity becomes mandatory, install ViGEmBus once (user
elevation) and set `backend="xinput"`; the MCP already supports it and degrades
to keyboard when the driver is absent.

## B-04 — Savestate *offline* analysis tooling

**PS2-CAM-00 時点：一部解決。** 下記は当時のオンライン抽出と未対応範囲。後の [FFX-2 差分解析](../../analysis/savestate_diff/run.py)には対象ステートから EE RAM を取り出す処理があるが、全ビルドの `.p2s` 用の汎用パーサーではない。

The parent lab's `scripts/savestate_extract.py` turns a slot into a raw
RAM image plus a SHA-256 manifest by loading it in the emulator (EE RAM 32 MB,
scratch, IOP RAM), which is what analysis actually needs. Parsing the `.p2s`
container offline (zstd + build-specific layout) is still out of scope.

**Cause**: PCSX2 savestates are zstd-compressed, version-tagged and contain
RAM/VRAM/SPU2/GS dumps with no stable public schema for this build. PINE's slot
savestate opcode also fails (KB-11). The gate does not require offline savestate
parsing — savestates are used live via qPcsx2, which works.

**Next step**: for PS2-CAM-01, extract RAM from a savestate by using the emulator
itself (load state → PINE read) instead of parsing the file, unless a parser is
adopted deliberately.

## B-05 — Ghidra decompiler output not exported

**Status**: CHANGES REQUESTED (deliberate scope cut).

**What exists**: function/symbol index (5 843 functions), R5900 language,
cross-check with live PCs, custom Java script execution.

**Cause**: exporting C-like decompilation for 5 843 functions produces a very
large artifact; the lab exported the listing index first and the decompiler is
available interactively (`analyzeHeadless ... -postScript Decompile.java` can be
added on demand).

**Next step**: add a targeted script that decompiles only the functions the
dynamic analysis points at (the cross-check already returns their entry points).

## B-06 — PS2-CAM-00 の対象ディスクは FFX-2 日本版のみ

当時の自動試験は ISO パスを引数に取るが、指定された *Final Fantasy X-2 (Japan)* だけで実施した。次段階で予定した FFX の試験結果ではない。また、この記録は現行アダプターが FFX-2 のみに対応するという意味ではない。[公開 GUI の対応ゲーム](../../README.md)と[ゲーム別の検証記録](../README.md)を参照。

## B-07 — One physical controller is attached

`SDLInputSource` reports an XInput controller (ROG Ally-style built-in). The lab
does not use it (keyboard path), but a real user pressing buttons during an
experiment would perturb observations. Recommendation: leave the controller
idle during automated runs.

## B-08 — FFX-2 field walking does not follow the orbit camera (resolved in part by the stock-camera hook)

**2026-10-31 時点：一部解決。** 下記の `.pnach` は当時の試験方式。現行 GUI ではアダプターがフックを適用・解除するため、通常は外部パッチを入れない。歩き始め 0.3 秒での方位測定と、後日のルカでの20秒の場面遷移試験は別で、長時間の歩行追従を実証したものではない（[歩き始めの方位](../games/ffx2/WALK_DIRECTION_INVESTIGATION.md)、[ルカの演出切替](../games/ffx2/CAMERA_MEMORY_MAP.md#ルカのミニマップ-共有-look-at-ビルダへの副作用)）。

**Cause (partly known)**: the mod moves the render camera through the additive eye offset
`0x3403E0` and the aim slot `0x33FC40`. Walking direction is derived from the game's own camera
state instead, so turning the orbit does not turn the walk. Writes to the render yaw, the aim, the
aux yaw words `0x3312F0/F4`, and the camera sin/cos input `0x340480` did not change the walk heading.
Writing the base eye `0x340370` changed it only partly (+11.7° for a +90° base rotation), which
suggests the game overwrites that word before the walk reads it. The exact read site is not found yet.

**Next step**: locate the instruction in the walk path that loads `0x340370` (EE or VU0), then retarget
it with a `.pnach` patch to an unused slot the mod keeps up to date, as the aim patch does for
`0x33FC10`. Full notes: `docs/games/ffx2/WALK_DIRECTION_INVESTIGATION.md`.

2026-10-31 (latest): RESOLVED in part. The walk direction is normalize(look-at target 0x33FC20 - eye). The
mod now drives the game's eye routine (hook applied in `cheats/8A6D7F14.pnach`, toggle `tools/stock_hook.py`) and
writes the target as the orbit centre. Walking heading matches the orbit in the first 0.3 s (verified at yaw
0/+90/-90). Longer walks are not yet verified, because the test room has walls close by. The hook is only correct
while the mod is running. Details: `docs/games/ffx2/WALK_DIRECTION_INVESTIGATION.md` §9-10.

2026-10-31 (earlier): the stock field camera base has no yaw input in EE RAM (perturbation scans), and the
stick words `0x480080`/`0x480084` are not the walk input (overriding them did nothing). The real pad source
is not identified. The camera-switch centring problem is fixed separately (guard limits relaxed).

## B-09 — RESOLVED: physical pad right stick in the mod

**Status**: resolved on 2026-10-31.

The pad answered on XInput slot 1, while `XInputSource` read only slot 0, so the right stick did
nothing. The source now scans all four slots and remembers the one that answered
(`PS2UniversalMod/core/controller/sources.py`). Verified: the real `XInput1_4.dll` binds to slot 1.
A physical stick push is not yet verified.

## B-10 — OPEN: FOV has no effect while orbiting in scripted-camera areas

**Status**: RESOLVED in the runtime on 2026-11-01, with open items (see the 2026-11-01 notes below). In `other_area_base` the orbit moves the eye, the aim and the walk
direction correctly, but changing the projection scale (0x340B00) does not change the image while
the orbit is active. In ordinary field areas FOV works (mean image difference 33.5 between FOV 93
and FOV 54.7). Details: `docs/games/ffx2/WALK_DIRECTION_INVESTIGATION.md` §11.

2026-11-01: writers of the base `0x340370` and the walk target `0x33FC20` identified (copy loop at `0x1A977C`, source
eye `0x3403A0` written at `0x1AAEEC`). The writer of the projection scale `0x340B00` is not yet found. §12.
Stopping the copy store (`0x1A977C` = 0) freezes the base and the walk target stays under the mod's control, but the
FOV still has no visible effect in this area (difference 1.5 against 1.04 without it). §12.1.
The projection packet builder `0x1B0908` is also called during the orbit (§12.2). Gate word `0x342CB4` makes the FOV
visible but changes the picture itself, and `0x340B18` has no effect. Root cause still open.
Packet word `0x33F68C` carries the scale in fields (303.67 / 618.93) but stays 1024 in other_area whatever is written to
`0x340B00` or `0x340B48`. §12.3.
Input word `0x33F68C` (offset 0x1C of the projection input block at `0x33F670`) is rewritten by the game every frame, so
holding it from outside does not stick. Its writer is not yet found. §12.4.

2026-11-01 (later): the writer chain is traced (§12.5). In other_area the projection source load at `0x1A985C`
reads the centre (900) rather than the scale `0x340B00`, because the loop row used there is the one whose +8 slot is
the centre. Redirecting that load to `0x340B00` (`C6E00F40`) was tested live: the input word follows the scale, the
image changes clearly with FOV (difference 55 against about 3 frame noise), and orbit-off pass-through with scale 900
matches stock (difference 1.3). Applied from the runtime, not the `.pnach` (§12.6): the load is switched on while the orbit runs and put back when it
stops. Live check: FOV now changes the picture in other_area_base and in the field. GUI exit now stops the runtime and then
calls `restore()`, so the switch goes back to stock. A mod that is force-quit while orbiting still leaves it on.
Open: the centre hold (1024) still needs review. §12.6.

2026-11-01 (latest): the game patch is owned by the runtime (WALK §12.7). The look-at and stock-hook words are
applied while the orbit or the free camera is on and put back to stock in the original camera. The boot-time
`patch=` lines were removed from `cheats/8A6D7F14.pnach` (backup `8A6D7F14.pnach.bak-20261101`), and the GUI has
buttons to load or remove the patch by hand. Still open: a force-quit while orbiting leaves the words and the
projection redirect applied, and the centre hold (1024) is unchanged.

## B-11 — OPEN: patch reported as unapplied, and the game crashes more easily (2026-11-01)

**Status**: partly addressed. The crash itself was not reproduced.

**Cause (from logs and code)**: the patch words live in game RAM, and the .pnach wrote them only at boot and
on reload. A savestate load restores stock RAM, so the patch disappeared without any warning (observed on
`base.p2s`). A PINE reply that arrived after a timeout was read as the answer to the next request, which shifted
every later read by one (fixed, WALK §12.8). Without a live runtime, the patched loads read slots that nothing
updates. This is the suspected crash path and is not confirmed.

**Done**: runtime-managed patch (WALK §12.7); PINE socket reset after any transport failure
(`tests/test_pine_backend.py`); projection writes compare before writing, with a one-second backoff after a
failure; a 60-toggle stress run with no PINE errors and no crash.

**Next step**: reproduce the reported crash with the exact steps (area, mode, GUI open or closed, savestate or
boot). If it is the force-quit case, consider a watchdog that puts the stock words back when the PINE connection
drops.


---

## Update 2026-11-02 (Suikoden V work and the GUI fix)

### B-12 — RESOLVED: the GUI froze when PCSX2 was closed or killed

**Cause**: on Windows a connect to a closed local port waits the whole timeout (measured 2.03 s). The
GUI's 80 ms refresh made several PINE calls on the UI thread, so every tick queued 2 s waits, and
closing the window took 14 s. **Fix**: `PineBackend` fails at once for 1 s after a failed connect
(`PineUnavailable`, connect timeout 0.3 s); the GUI reads the game through a `StatusPoller` thread;
the window shows "not connected" and recovers by itself when PCSX2 returns. **Proof**:
`tools/gui_freeze_check.py --kill --relaunch` (longest UI stall 0.03 s, close 0.2 s, back after 6 s).

### B-13 — OPEN: Shining Force Neo: the camera direction after `restore()` is not the stock one

The game sets its own yaw after the smoothing gate is given back (−50° before, about 4° after, on the
baseline commit too). Not a regression of the Suikoden V work; see
`../games/shiningforceneo/CAMERA_ANALYSIS.md`.

### B-14 — OPEN: PCSX2 sometimes exits by itself right after a savestate load on a freshly started game

Seen four times while switching games on 2026-11-02 (no crash dump, no hook installed at that moment).
A relaunch fixes it. Waiting about 15 s after PINE first answers, and reconnecting the MCP
(`disconnect` then `connect`) before loading the state, avoided it.

### B-15 — OPEN: Suikoden V events, battles and menus not exercised

The adapter's heartbeat guard leaves non-field cameras alone, but no event or battle was played.
See `../games/suikoden5/TEST_RESULTS.md`.
