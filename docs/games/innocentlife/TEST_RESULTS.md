# Innocent Life — 実行した確認と制限

日付 **2026-11-07**。親baseline `50f82d1`、作業branch `feature/innocentlife-adapter` の未コミット実装。
日本版 **SLPS-25763 / 9AC21F92**、既存PCSX2 fork-B056de99。独立レビューではなく実装側の動作確認。
[方式・アドレス・安全条件](CAMERA.md)、[使い方](../../../README.md#59-新牧場物語-ピュア-イノセントライフ)。

## データ保護と場面

- 原本ISO・4つの提供ステートは変更しない。4ステートをoffline差分解析に使用した。
- 起動中のユーザー状態を別名savestateへ退避。
- activeカードが排他lockだったためPCSX2を正常終了し、両カード全471ファイルをハッシュ照合して別のlocal backupへ複製。
  実機試験は専用の複製カードslot1/2で実施。原本へのゲーム内保存操作はしない。
- 主な場面は提供baseの屋外道、再適用は提供character+cameraの湖畔。全世界／全時刻の保証ではない。
- dump、ELF、Ghidra project、各runのスクリーンショット・JSON・ログは全てrepository外。
  local evidence: `C:\PS2CameraLab\test_evidence\innocentlife`。

## 初期実装の確認（FOV追加前の記録）

以下は初期sourceでの結果です。FOV無効化の記述・hashは当時の条件で、現行FOV対応は後段の「FOV追加」で区別します。

### 自動テスト — PASS

```powershell
C:\PS2CameraLab\python\venv\Scripts\python.exe -m pytest -o addopts= `
  tests/test_innocentlife.py tests/test_innocentlife_gui.py tests/test_game_time.py `
  tests/test_core.py tests/test_gui.py tests/test_game_guard.py tests/test_pine_backend.py `
  tests/test_sfneo.py tests/test_suikoden5.py -q
```

**414 passed / 59.99秒**（local `regression_02.log`）。
親ラボのpytest.iniが未導入のtimeout plugin optionを指定するため、既存環境のまま`-o addopts=`でそのoptionだけを除外した。
依存の入替えはしていない。

- identity Serial+CRC、異CRC/異Serial拒否、GuardedBackend。
- native pair/delay・cave/control未知所有の書込みゼロ拒否、到達可能cave損傷拒否。
- 実際のemitted MIPSをsynthetic runnerで実行：cameraコピー、forward復元、movement yaw、F0/128bit scratch、callee argument-home、nested render。
- sequence odd/even・二重bank公開、NaN/Inf/singular拒否、offetsの実視線yaw。
- Orbit/時計の独立適用・解除、guest threadのみのmove/clock native書込み、ACK/paused timeout上限、stock再適用。
- 毎write transactionで全resourceを一度検査し、別取引へinspectionを持ち越さないこと。
- Originalでも時計service、最大4Hz、失敗retry、clock error表示、例外後のstale noticeのみ解除。
- 起動／reconnect／presetで時計を勝手に有効化しない、無効化と正常終了で時計も戻す、abandonは書込みなし。
- FOV/Freeの無効化と日英理由、未対応FOV保存値／presetがcontrolを迂回しない。
- 既存core・GUI・PINE・guard、SFNeo/Suikoden境界の局所回帰。既存全ゲームの実機再試験ではない。

### PCSX2実画面＋GUI/runtime統合 — PASS

最終runは **`live_05/checks.json`: completed=true, passed=true, 42 checks**。
`tools/innocentlife_live_check.py --move --reload-handshake <external-dir>` を使用。
MainWindowが唯一のPINE接続を所有、temporary APPDATA、inputは既存background keyboard経路。

| 確認 | 結果 |
|---|---|
| 起動 | exact ID/CRC、Original＋時計off、未知版writeなしはfakeで確認 |
| GUI | Orbit・時計・offset有効、FOV/Freeは理由付き無効 |
| 通常時計 | pause前はhour/min/sec進行 |
| 時計だけ停止 | Originalのまま時計固定、main-loop countは1.2秒で36増加（VM停止ではない） |
| yaw | 0 / 90 / 180 / −90°、画面とview逆行列・rendered eyeを照合。最大eye誤差 **0.000058** world units |
| pitch／距離 | pitch70°・distance120、pitch65°・distance110で実view照合 |
| native保持 | 静止中のnative eye/pitch/yaw/rollは角度変更前後でbit一致、時計固定 |
| offsets | 独立eye/target設定時、bank movement yawが実視線atan2と一致 |
| right stick | scripted右スティック0.6の短い入力でyaw約11.50°変化し、離すと保持 |
| 移動 | 4yaw×前後8測定。各0.5秒入力、XZ距離26.4〜36.0、視線との方向内積 **1.0**、最大向き誤差 **0.043°** |
| 移動中時計 | 8測定全て同一時刻 **07:56:04** を保持 |
| stock state読込 | 同じ版の別提供stateを外部からload/resume、Orbit＋時計を再適用。時刻07:53:48を保持、残留errorなし |
| Original | camera/movement stock、時計opt-inは保持 |
| 無効化／cleanup | clockも解除。render/move/clock命令を全てstockへ読戻し確認 |
| 時計再開 | 無効化後、通常速度で進行。停止中の経過時間をまとめて加算する挙動なし |

最終cleanup後、MCPでもrender `7a0a040cd088848f`、move `d088828f14004cc4`、clock `12200000` を読み戻した。
breakpoint/watchpointは残さない。

終了後は元のカードslot1/2設定へ戻し、退避したユーザー状態（ゲーム内 **14:03:52**）を再読込みしてPCSX2をpausedで残した。
カメラ・移動・時計の3箇所がstock命令であることを改めて読戻し、解析用GDBを切断した。
検証中の移動・経過時刻をユーザーの元プレイ状態に持ち越していない。専用カードとbackupはローカルに残す。

### 途中の失敗と修正（初期実装の最終PASSと混同しない）

- `live_01`: player transient bit2をscene許可と誤認し、通常待機を拒否。書込み開始前に停止した。
  idleBC／入力consumerBE、s2=playerを実測してscene共通gateから撤去。nativeの許可済みconsumerにのみ移動hookが到達する。
- `live_02`: 4yawの移動・時計・復元は成功、短いstick入力が約0.17°しか積分されなかった。
  同じ取引内の重複full-code検査を約5回から1回へ削減。全検査自体は毎取引保持。
- `live_03`: 短いstick応答と8方向測定は成功、外部state load待合せが期限切れ。cleanup成功。
- `live_04`: 最初の0.28秒の180°turnで向きだけ変わり移動量ゼロ、他7移動と時計/state/復元は成功。
  原作turn smoothingを変更せず、試験の入力を0.5秒に延長して最終runで8測定を確認。
- stock load直後の途中snapshot／pausedで一時的なpatch失敗通知が残ったため、成功後に同じlaneの古いエラーだけを解除する処理とテストを追加。
  新しいscene/clock/patch失敗を一律に隠す処理にはしない。
- `regression_01`: 406 pass/1 fail。追加したcoreテストがfake scene noticeとpatch noticeを混同していた。
  patch retryを独立して検査する形へ修正し、最終414件pass。

### 初期実装時の未実施・制限

- 全menu、会話、睡眠、日付跨ぎ、イベント、全屋内／全map、乗物、長時間、他版は未網羅。
- menu起動ボタンの限定probeでnegative menu sampleは得られていない。構造guardを全特殊scene識別と呼ばない。
- 時計停止は通常進行のelapsed秒のみ。明示的時刻setter（睡眠・イベント等）を止める仕様ではない。
- 初期実装時はFOV未校正・現在値0（後段のFOV追加で解消）。Freeは引き続き未対応。cameraの壁／地形衝突はなし。
- paused VMはguest ACKできないため再開が必要。強制process終了・異ゲーム時に旧gameへ強制復元はしない。
- caveの4stateゼロとELF非重複は確認したが、全kernel/DMA生存期間の形式的証明ではない。未知所有は拒否する。
- 実XInput物理controllerを人が動かす試験はしていない。既存InputPumpとscripted source→同じruntime経路を実測。

### 初期実装の検証対象コードの要約hash

最終liveに使用した主要sourceのSHA256（パス・hashのみ、ゲームデータなし）：

| source | SHA256 |
|---|---|
| adapter.py | `cebbcdbd67cc1cbb3465cea23aea76f0e90cd62690ce1d1d8ffae651807592bb` |
| caves.py | `23f42fd07f2aaa732709fa3adc7ab27d51013e5ce4733e037e1e725abd416dda` |
| memory_map.py | `eb9fd1a2cfd9f22c98e68bb2e0b08107b29b78bb24bff98aba000348787fd1fe` |
| engine.py | `c426822026be31031fd7b1b9e1bf2bb2fc92930094b762fcb25e2f804acf1a4f` |
| app.py | `97fc772308c6751bcf6e6ced1fd837592824c0cb1c010a63edb0a136ab6c8a9f` |

## FOV追加 — 2026-11-07、現行未コミット実装

### 解析・方式

- nativeの未校正54.68°ではなく、512×448描画・X倍率約0.8・実投影m00から **水平71.635048°** と校正。
  4state offline・既存Ghidra出力・実機投影write watchpoint/backtraceを照合（[詳細](CAMERA.md#fov--校正と投影経路)）。
- bankへfocalと任意FOV flagを加え、描画cameraコピーの`+0x7C`だけを差替える。
  native builderがrender投影とclip副行列をまとめて再生成し、native camera・near/far・時計は保持。
- 所有layoutをILC2へ更新。旧ILC1/未知caveは強制上書きしない。旧GUI正常終了後、stock state読込またはゲーム再起動が必要。
- GUIは既存feature境界でFOVを有効化。Freeは理由付き無効、起動Original・ゲーム別設定・値のみpresetは維持。
- 共通FOV serviceのリトライ成功時に、そのレーン自身が出した完全一致の古いエラーだけを解除。
  他の時計・scene・patch失敗は隠さない。

### 自動テスト — PASS（合計449件、2コマンド）

```powershell
C:\PS2CameraLab\python\venv\Scripts\python.exe -B -m pytest -p no:cacheprovider -o addopts= `
  tests/test_innocentlife.py tests/test_innocentlife_gui.py -q
# 152 passed in 1.20s — fov_adapter_tests.log

C:\PS2CameraLab\python\venv\Scripts\python.exe -m pytest -o addopts= `
  tests/test_game_time.py tests/test_core.py tests/test_gui.py tests/test_game_guard.py `
  tests/test_pine_backend.py tests/test_sfneo.py tests/test_suikoden5.py -q
# 297 passed in 59.37s — fov_regression.log
```

- emitted MIPS runnerのnative builder stubもcopied focalから実投影を作る。20/60/110°・native camera/forward保持、
  要求値だけで同期成功としない実投影読戻し、clamp・NaN/Inf・不正倍率・未知hook/cave/controlの書込み前拒否。
- scene fallback、coherent bankでfocal/flag/geometryを同時公開、builder内2回公開、state再適用、current native focalへの復帰。
- FOVはlifecycle maskへ混入せず、OriginalのFOV-onlyはcamera/移動hookを有効化しない。時計の独立性も保持。
- 日英GUIでFOV有効・Free無効、設定/preset/reopenでも値保持とOriginal起動、GUI→runtime→実投影readback/reset、
  Originalで時計選択保持・disableで全解除。異ゲームguard/abandonはFOV解除も書込みゼロ。
- FOV timeout後の成功は自身のエラーだけを解除するcore回帰。既存境界297件も成功。他ゲームの実機再試験は未実施。

### PCSX2実画面・GUI/runtime — PASS

最終 **`fov_live_02/checks.json`: completed=true, passed=true, 50 checks**。
実行は `tools/innocentlife_live_check.py --move --reload-handshake <external-dir>`。
唯一のPINE接続はMainWindow、temporary APPDATA、既存複製カード2slot、提供base屋外から開始。

| requested水平FOV | actual水平FOV | 投影m00 | clip正規化m00 |
|---|---|---|---|
| 20° | 20.000000° | 1451.848145 | 5.671282 |
| 40° | 40.000002° | 703.354187 | 2.747477 |
| 60° | 60.000001° | 443.404999 | 1.732051 |
| 100° | 100.000003° | 214.809494 | 0.839100 |
| 110° | 110.000005° | 179.253113 | 0.700207 |

- 各画角で実画面を保存し、40°の望遠と100°の広角を同じeye/targetで目視比較。3D画角は変化し、HUDの大きさは維持。
  native focalは全5設定でbit一致、m11もnative Y倍率比に一致。要求角誤差は最大 **0.000006°未満**。
- FOV reset後、16要素のraw projection全体がnative時と**完全一致**、画角約71.635°へ復帰。
- Orbit4yaw・pitch・距離・6offset・短い右入力も成功。4yaw×前後8歩行は24.0〜36.0 world units、
  方向内積1.0、最大向き誤差0.071°未満。時計固定、VM main-loopは進行。
- 同版の別提供state（湖畔）へload/resumeしてOrbit＋FOV60°＋時計停止を再適用。復旧後errorは空。
- Originalでnative画角・camera/movementへ戻り時計選択保持。disable/cleanupは時計も戻す。
  MCPでrender/move/clockをそれぞれ`7a0a040cd088848f / d088828f14004cc4 / 12200000`と読戻し。
- 最終、元カードslot1/2設定と今回開始時のユーザーstate（**06:51:32**）へ戻し、PCSX2をpausedで残した。
  復元後も3命令箇所stock・breakpoint/watchpoint無しを確認、GDB切断。原本ISO/state/カードを変更していない。

途中run `fov_live_01` は投影・復元を含む50check成功だったが、state読込中のpausedで出たFOV timeout通知が残った。
これを実装成功の最終状態とはせず、coreの限定的な通知回復と単体テストを追加し、`fov_live_02`でerror無しを再確認した。
テスト作成時はfloat32乗算の実機との差1ULPを許容範囲5e-5へ修正し、unknown magic時に所有不明diagnosticsを
クリアしない安全仕様をtestへ反映した。production安全条件を緩めた修正ではない。

制限: **Orbitに付随するFOVのみ**。Original FOV-only・Freeは非対応。全map/屋内/イベント/広角のLOD・カリング、
長時間は未網羅。今回のoffscreen GUI captureでは既存Qt環境のfont不足による豆腐表示があり、
テストはcontrol状態・日英文言・実行経路の確認で、フォント描画品質の合格を意味しない。

### FOV最終実機source SHA256

| source | SHA256 |
|---|---|
| adapters/innocentlife/adapter.py | `494c204f9a5ad3464579a2b54b32d013a659794266dd62969df78cc7e5801bc2` |
| adapters/innocentlife/caves.py | `7b465c27e3efcea16b75a1b5b784bf55fd836888ae8ade19e11ffe936c184a75` |
| adapters/innocentlife/memory_map.py | `31ae7b9931774ad289a029ac32535696ed1ee949e5a73c7354facc9c2050559d` |
| core/camera_runtime/engine.py | `cfdaedb13e2e5b45e44f87542f78e7dc685ebb24b6d62a869b659cbea62dcd79` |
| tools/innocentlife_live_check.py | `61d4ab6e6127f638498ed96380023a64383467564f00758567fca13a27864074` |
