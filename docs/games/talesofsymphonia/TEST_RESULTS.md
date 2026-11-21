# テイルズ オブ シンフォニア — 実施結果と制限

2026-11-07 / `SLPS-25400 / 830B6FB1` / branch `feature/talesofsymphonia-adapter`。
実装側の確認記録であり、独立レビューではない。
設計・アドレス・安全条件は [CAMERA](<CAMERA.md>)。

本書の `work/` と `sstates/` は開発ラボを基準とする保存先で、公開リポジトリには含まれません。

## 対象とデータ保護

既存fork `B056de99`、PCSX2 2.7.499、EE GDB10501／PINE28011を使用。
Python3.12 venv・既存Ghidra12.1.4＋R5900 languageを再利用した。
ISOは読取りのみ、原本8stateもloadのみで上書きしない。
開始時の実行状態は `work/symphonia/session_start_20261107.p2s` に別名保存した。
ELF・RAM・画像・decompile・raw JSONはGit外の `work/symphonia/` に保持する。

| 原本state | SHA256 |
|---|---|
| `sstates/テイルズオブシンフォニア/base.p2s` | `7C071A171DCAF807A5BE32421E9C1B866A903BABC3B49FB29D2FE240FBA96A08` |
| `sstates/テイルズオブシンフォニア/base_only_wait.p2s` | `E0E6F18B43519D3B46F64F502F8AB1C9C22824A9E5A7CCD2E08EAB017BA08E05` |
| `sstates/テイルズオブシンフォニア/base_chara_move.p2s` | `E00CD6D4A3AEB685A419990E1F63E72D5A75EA881314C5BB39BB828C85671199` |
| `sstates/テイルズオブシンフォニア/base_chara_and_camera_bigger_move.p2s` | `1741063E34685D9C8FB7B7E3020635C1378B5CA4D88503D1EAF25C835AB22762` |
| `sstates/テイルズオブシンフォニア/field_base.p2s` | `0CDB2BA25CCCEDCB4B48D25260F559244B3A1C0EB5E2F63A0043E871B9F83189` |
| `sstates/テイルズオブシンフォニア/field_base_only_wait.p2s` | `BD558F9ADC0EA95320E0190864527EA37B4CAD1319B00C708F879776791827B9` |
| `sstates/テイルズオブシンフォニア/field_base_only_camera_move.p2s` | `4834AD07E446A0689CCFDE558BAC8F47944074E3F952DD75851E33587340B8F5` |
| `sstates/テイルズオブシンフォニア/field_base_chara_move.p2s` | `5DE1CE7A6228521B729413B37DD2921FDADACDA46ED1EEDB12CF52DB1131F166` |

最終再計算で8原本＋開始backupのhash一致。
提供stateは町4つ／ワールド同地域4つで、8エリアの網羅ではない。
メモリーカードへのsave操作は行っていない。

## 合成単体・GUI回帰

```powershell
python -m pytest -o addopts= tests/test_talesofsymphonia.py tests/test_core.py tests/test_game_guard.py tests/test_pine_backend.py -q
# 566 passed in 9.74s（最終host cancel-race修正後）
python -m pytest -o addopts= tests/test_talesofsymphonia_gui.py tests/test_grandia2_gui.py tests/test_gui.py -q
# 127 passed in 55.11s
```

計 **693 passed**。うち [専用adapterテスト](<../../../tests/test_talesofsymphonia.py>) は473 parameterized case。
R5900小型interpreterでlook/lens/consumer/shared lifecycle/bootstrapを実命令実行し、native math／drawはstub。
Serial+CRC、town/world guard、94235 spawn timer=60受理、sequence・snapshot、nativeコピー保持、全consumerfallback、
13resource所有、11hook＋delay、128bit scratch／RA、data callback復元、timeout、TOS1拒否、hot lease／周期audit、
GuardedBackend・abandon・stockreload・FOVのHUD誤参照防止を含む。
[専用GUIテスト](<../../../tests/test_talesofsymphonia_gui.py>) は登録・範囲・非対応disable・settings隔離・再識別等。
これはnative renderer、recompiler scheduling、全scene、物理XInputを保証しない。

`git diff --check` とtracked working-tree `python tools/audit_repo.py` 成功。
後者はuntracked新規ファイルやindexの監査ではない。加えて同auditの`Entry/check`を新規9ソース／文書へ直接適用し、禁止data／機密情報検査は全件0 findings。
README・文書索引・新規ゲーム文書のlocal link存在も確認。実装確認時点では未stageであり、後続のcommit前にはstaged監査を別途実行する。

## 最終TOS2 raw run — 77/77 checks

batch結果（`work/symphonia/batch/checks.json`） と
local実行script（`work/symphonia/batch_verify.py`）。

- **全8state**で同じadapterを再利用してstockload→再適用。yaw90°／pitch35°／distance1800／FOV60°。
  scene受理・render target・FOV係数・全11site解除・原本hash不変を確認。
- 町・worldそれぞれ **4yaw（0/90/180/270）×4pitch（−15/35/75/89）**、FOV110°で各約0.2秒のフレーム進行。
  町は各12frame、worldは各3〜4frame。短時間の進行確認であり長時間安定性試験ではない。
- 各sceneでFOV20/40/60/100/110°読戻し・全11site解除。
  FOV60のsx=1.732050776、syは町2.309401035／world2.474358082でnative aspectを保持。
- 4yawの35°／110°FOV画像を保存。worldの地形・海・コンパス・minimap、町のgeometryを親担当が目視。
  町110°ではmap外黒背景・屋根の裏面が明確に見える。これを全scene描画成功としない。
- TOS2で町4回のapply/releaseを繰返し、actor callback `0x13BA20` 復元。
  続く8state＋angle runでprocess継続、同じblock-clearing errorの再発は観測していない。

画像例: world yaw180 FOV110（`work/symphonia/batch/field_base_y180_p35_f110.png`）、
world yaw270 FOV110（`work/symphonia/batch/field_base_y270_p35_f110.png`）、
町yaw180 FOV110（`work/symphonia/batch/base_y180_p35_f110.png`）。

## MainWindow → GuardedBackend → runtime → EE

再現用 [限定live checker](<../../../tools/talesofsymphonia_live_check.py>)。
既に実行中の通常場面へ接続し、freshなGit外出力先を指定する。他PINE clientを閉じ、開始状態を保護する。
GUIはoffscreen、一時APPDATA/QSettings、scripted camera入力であり、移動・state操作はしない。

- 町の最終結果（`work/symphonia/gui_town_stock_final/checks.json`）: **15 checks成功**。
- worldの最終結果（`work/symphonia/gui_world_synced_final/checks.json`）: **15 checks成功**。

両方でOriginal起動・待機 **0write**、全11hook＋nativecallback返却、yaw40°／pitch+35°実geometry、
scripted inputでyaw/pitch更新、FOV20/60/110＋aspect、nativeFOV resetでOrbit pose保持、
6offset `[100,25,-80,-40,20,60]`、Original全11site／両callback復元、残したcave exact、native lens再開。
relative pose誤差は町0.000105未満／world0.000416未満。
Qt fontdirectory警告は出るがoffscreen検証は完了。物理パッドや目視GUIレイアウトを検証したとの意味ではない。

最初の町runはraw入力試験でOrbitが残った状態から起動したため、Original cleanupの2writeがあり0write assertion不成立。
stock開始backup読込後に0writeを確認した。world最初のrunはscripted停止直後にguest最終bankを待たずgeometryを比較して23.39差。
checkerをguest反映待ちへ修正して成功。production geometryをこの失敗のために改変していない。

## 実入力の移動・world RX

最終入力結果（`work/symphonia/final_input/checks.json`）。
PCSX2 keyboard pad binding `LUp=Keyboard/W` を実際に送る。backendの **y=+1がUp**（−1はDown）。
recovered processのframeadvance-onlyではkeyboard pollが進まずゼロ変位となったため、通常resume中に短時間保持して測定。
物理XInput入力ではない。stateは各試験前に読み直し、終了後開始backupへ戻した。

| scene / yaw | canonical水平変位 (X,Z) | 視線とのcos類似度 | 判定 |
|---|---|---|---|
| 町0 | (−0.031,−323.919) | >0.99999 | 一致 |
| 町90 | (−323.918,+0.031) | >0.99999 | 一致 |
| 町180 | (0,+194.351) | 1 | 一致 |
| 町270 | (+323.917,−0.031) | >0.99999 | 一致 |
| world0 | (0,0) | 定義不可 | **未確定**（ゼロ変位、障害物／入力タイミング未分離） |
| world90 | (−71.999,−0.035) | >0.99999 | 一致 |
| world180 | (0,+726.953) | 1 | 一致 |
| world270 | (+107.852,+21.109) | 0.98138 | 概ね一致、横成分あり（地形衝突等未分離） |

距離・速度比較を目的とした同条件測定ではない。町は約0.35秒、worldは約1.5秒保持、実VM速度は異なる。
D-pad／全斜め／全移動モードは実入力未網羅。数学テストは8yaw×4directionを別途確認。
world RX実入力0.7秒ではOriginal nativeyaw `3.125→3.6445379`、Orbitでは `3.125→3.125`。
原作camera専用getterの中立化が効き、global yawをOrbitに書き換えていないことを確認。

追加の paused enable取消結果（`work/symphonia/pending_cancel.json`） では、VMpause中のenable→Originalが双方timeoutを返し、
flags0・全hook stockのまま再開後にnativecallbackへ復帰することを確認。解除完了を早まって返さないためのhost側修正で、generated guest codeは同じ。
追加合成testで、EEがFLAGS0 store直後にACKしてcallbackを返すraceも検出し、既存CMD_SYNCを再armしない方式に修正した。
この4case（町/world×再開済／pause継続）を含む最終473caseが成功。既にflags1を読んだEEとの競合時はACK不一致として安全失敗し、再開後offを再試行する。

コンパスは4yaw画像で方位盤／N-E-S-Wの回転を確認。minimap表示も保持。
**fullmapを実際に開く試験は未実施**で、fullmap consumerはnative引数解析＋合成命令テストの範囲。

## 開発中の失敗と対応

1. worldをbusyとして拒否: `root+0x94235=60` はenemy spawn timerで毎frame増加し0x3Cで飽和する。
   busy guardから除外し、現テストに0/1/30/60回帰を追加。
2. TOS1 PINE executable bootstrap: 繰返し有効化時にPCSX2が
   `Impossible block clearing failure`、Windows `c0000005` で終了。
   元backupからPCSX2を再起動、TOS2 data callback bootstrapに変更。
   TOS2ではhostからgame executable hookへ書かない。ゼロcave準備は未到達時だけ。
   同条件再発はその後観測しないが、全PCSX2 lifetime／全sceneのcrash無し保証ではない。
3. native `input_set` MCP commandはこのforkでusage error、keyboardを使用。fork/MCP自体を無関係に修正しない。
4. world global projectionはHUDで上書きされるため、従来mirror値を原作FOVとしない方式へ修正。

## 未実施・非対応・最終状態

Free Camera、ゲーム時間停止、乗り物／飛行camera、Original FOV-onlyは非対応。
全area/dungeon/event/menu/battle、長時間、全culling/LOD/billboard/particle、物理XInput、fullmap実表示は未網羅。
camera collisionなし。world0°前進のゼロ変位と270°の横成分は未分離。
ゲーム切替・PCSX2再起動の最終GUI stressは今回実施していない（guard単体／GUI合成回帰は実施）。

最終は保護した開始stateを再loadし、control magic=0、全11site stock、cave clean、held inputなし、
breakpoint/watchpointなしを確認してOriginalで再開する。ISO／8原本state不変。
ここまでが実装・動作確認時点の記録。後続のcommit・PR・main統合状態はGit履歴と対応PRを正本とする。
