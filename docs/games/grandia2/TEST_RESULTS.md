# グランディアII — 実行した確認と制限

日付 **2026-11-07**。日本版 **SLPM-65081 / B6AB7BC2**、branch `feature/grandia2-adapter` の実装を確認した記録。
[方式・アドレス・安全条件](<CAMERA.md>)、[使い方](<../../../README.md#510-グランディアii>)。
本書は親担当の解析・テスト・実機報告と指定evidenceの読取りをまとめたもので、文書担当による再実行・独立レビューではない。
**現行は7site／5 code resources／G2C2、水平FOV20〜110°。最終関連448 passed／61.62秒、最終raw runとMainWindow 14項目の限定確認を現行追記に記録する。全場面対応の保証ではない。**
現行結果・最終cleanupの正本は末尾の[現行追記](<#現行追記--7siteg2c2packet-streaming-2026-11-07>)。
以下の旧3hook／20〜60°記録は日付・条件・失敗・cleanupを保持し、7hook成功へ書き換えない。

<a id="過去記録--旧3hookg2c1fov2060-2026-11-07"></a>
## 過去記録 — 旧3hook／G2C1／FOV20〜60°（2026-11-07）

本節から現行追記の直前までは、packet streaming追加前の旧sourceに対する履歴。
旧性能最適化後の関連320テストと屋外／屋内・MainWindow／runtime統合の限定確認、当時のcleanupは成功したが、現行7siteを実証した結果ではない。

## データ保護と対象

- 提供6ステートは [保護stateディレクトリ](<C:/PS2CameraLab/sstates/グランディア II/>) 内で原本保護し、差分解析に使用した。
- 開始時のユーザー状態は別名 [user_start_20261107_1117.p2s](<C:/PS2CameraLab/sstates/grandia2/user_start_20261107_1117.p2s>) へ退避した。
  旧版検証後に同stateを読込み、ユーザー開始状態の復帰を確認した（[旧cleanup](<#旧3hook版の最終cleanup>)）。
- 実画面確認は提供場面の屋外と屋内。6stateを解析したことを6エリアすべての実機確認と言い換えない。
- 原本ISO・ステート、展開RAM・ELF・Ghidra project・スクリーンショット・ログはrepository外。ゲーム由来データをコピー／コミットしない。

## 旧3hook版の自動テスト — 親担当実行済み

当時の最終親担当実行は **320 passed / 60.44秒**。Grandia II固有は **125件**
（[synthetic 92件](<../../../tests/test_grandia2.py>)＋[GUI 14件](<../../../tests/test_grandia2_gui.py>)＋[性能・所有19件](<../../../tests/test_grandia2_perf.py>)）で、320件の内数。

```powershell
python -m pytest -o addopts='' -q tests/test_grandia2.py tests/test_grandia2_gui.py `
  tests/test_grandia2_perf.py tests/test_core.py tests/test_game_guard.py `
  tests/test_pine_backend.py tests/test_gui.py tests/test_innocentlife_gui.py
```

初期85件／関連aggregate263件・58.78秒は途中sourceでの結果。最終320件へ加算しない。
文書担当はテストを再実行していない。source hashによる固定や独立レビューの成功を意味しない。

主な検証契約:

- Serial+CRC、屋外mode8／屋内mode0、primary owner→node、4byte整列、geometry／focal／投影寸法の不正値拒否。
- emitted MIPSをsynthetic runnerで実行し、native cameraを一度だけ呼ぶ、NJコピーのeye／単位forward、copy内roll=0、最終focalへの引渡しを確認。
- native camera保持、render tailの数値／stack／VIEW・WORLD／focal／flags／current projection pointer復元、queued record/countは保持。
- 最新player加算、6offsetを含む実視線yaw、移動cameraコピーの`+0x58`以外とpad引数は保持。
- 二重bankのodd/torn検出、render中に二度publishしてもそのtransactionのsnapshotを維持、owner／node／guard不一致でnativeへ退避。
- 初回／backend・epoch変更／state消失／周期audit／解除で全resourceをpreflight。hot bank公開は3exact hook pair・magic・flags・ACKを毎回確認し、所有確認は同じadapter/backend/epoch内に限定。
- cave本体だけの改変は次のfull audit（通常約1秒＋通信／runtime遅延）で検知し、即時検知を主張しない。性能・所有19件でread数上限、cache無効化、周期検査・競合拒否を確認。
- guestが全3siteを検査してから適用／復元、hostはrender bootstrapだけ。transaction中解除は数値復元後、stock state再公開、FOV-onlyでhookを有効化しない、異ゲームではGuardedBackendが公開／復元とも書込みを拒否。

runnerのnative builder・inverse・projection cacheは**stub**。実際のPS2描画、真の逆行列／frustum数学、thread scheduling、
メニュー・イベントの網羅性をsynthetic成功だけで実証したことにはならない。

## PCSX2実機 — 確認済みの限定範囲

以下は親担当から受けた確認結果と、ローカル [validation.json](<C:/PS2CameraLab/test_evidence/grandia2/validation.json>) の読取りによる要約。
要求値やmemory変更だけでなく、記載した箇所では親担当が実画面も確認した。文書担当による実機再実行ではない。

| 確認 | 結果・条件 |
|---|---|
| 屋外native | distance2400、pitch30°、注視点高さ180、水平FOV約19.995°、focal約1815.2589 |
| 屋内native | distance1400、pitch12°、注視点高さ180、水平FOV約29.993°、focal約1194.5603。1194.5603は距離ではない |
| 原作入力 | 屋外L1/R1でyaw、屋内は固定。原作右スティックcameraなし、MODの入力遮断なし |
| 屋外Orbit画面 | yaw45°／表示pitch30°／distance2000／FOV40°で描画変化を確認 |
| 屋内Orbit画面 | yaw−45°／表示pitch50°／distance1600／FOV50°で描画変化を確認 |
| 屋外の短い前進 | yaw0／90／180／−90°、W入力各0.18秒でXZ距離150〜180 units。実視線forwardとの水平内積は約1.0、native yaw9271は不変。詳細は下表 |
| 屋内の短い前進 | 同じ4yaw、各0.18秒。yaw0°は衝突によりXZ内積0.971743、他は約1.0。地形の高さ変化・原作衝突を保持。native yaw8192は不変 |
| FOV20／40／60° | 屋外・屋内とも実画面と実水平FOV読戻しを確認。actualは20.000000017／40.000001056／59.999997475° |
| FOV「ゲーム値に戻す」 | 屋外19.995155790°／屋内29.992708299°へ復帰。各sceneのnativeと一致 |
| 両sceneの直接解除 | 3hook stock復帰を親が読戻し確認。ログのread poseもnative eye/targetと一致。最終GUI/runtime cleanupとは別 |
| FOV探索時の制限 | 100°は数値一致後に**native packet bufferのfatal停止**を確認。stock stateで復旧し、当時の上限を60°へ制限。数値一致を安定性PASSとはしない |
| FOV60°の継続 | 限定屋外場面で629フレーム継続、停止なし。3hook解除とnative focal約1815.2589への復帰を確認。全sceneの60°安定性を保証しない |
| stock state再適用の部分確認 | ログに`runtime_state_reapply: applied=true, error=""`、保持yaw45°／内部pitch−30°を記録。後段にMainWindow経由の別runを記載 |
| runtime入力の追加確認 | 新しい直接runtime試験で2秒安定待ち後、2秒のscripted入力によりyaw45→約75.57°、内部pitch−30→約−47.47°、actual FOV40°、errorなし。物理右スティックではなく、後段のMainWindow試験とも別run |
| cave候補 | `[0xB9000,0xBA000)`、`[0xF5000,0xF6000)`、`[0xFD000,0xFD800)` が6stateで全ゼロ。snapshot上direct/KSEG参照なし。永久空き保証ではない |

### 短い前進の測定値

XZはworld units、内積はOrbit実視線の水平forwardとの比較。すべて同一sceneのstock stateから4yawを個別に測定した短い前進で、
全入力方向・速度の長時間保証ではない。屋内0°の衝突による横滑りを「一致」に丸めない。

| scene | 設定yaw | ΔX | ΔZ | XZ距離 | forward内積 | actor heading / 実視線eye yaw（整数） |
|---|---|---|---|---|---|---|
| 屋外 | 0° | 0 | −150 | 150 | 1.000000 | 32768 / 0 |
| 屋外 | 90° | −149.999985 | 0 | 149.999985 | 1.000000 | 49152 / 16384 |
| 屋外 | 180° | 0.000076 | 150 | 150 | 1.000000 | 0 / 32768 |
| 屋外 | −90° | 180 | 0 | 180 | 1.000000 | 16384 / 49152 |
| 屋内 | 0° | 30.986023 | −127.564186 | 131.273589 | **0.971743** | 32768 / 0 |
| 屋内 | 90° | −180 | −0.000092 | 180 | 1.000000 | 49152 / 16384 |
| 屋内 | 180° | 0.108963 | 140.043732 | 140.043774 | 1.000000 | 57 / 32825 |
| 屋内 | −90° | 140.802734 | −0.010712 | 140.802735 | 1.000000 | 16390 / 49158 |

ログの`desired_heading`は実視線から作った**eye側のnative yaw**。actor headingはforward側なので、
全8測定で`heading = (desired_heading + 32768) & 65535`となり、180°差を向きの失敗と解釈しない。
屋内90°ではΔY約−59.304も記録しており、XZ距離と3D距離は区別する。

追加の [movement_extended.json](<C:/PS2CameraLab/test_evidence/grandia2/movement_extended.json>) はyaw25°／表示pitch40°／距離1800、
eye offset `(160,25,−100)`／target相対値 `(−30,200,70)`で、W/S/D/Aを各0.13秒入力。
屋外4方向は各約120 units、offset込みの期待方向との内積は全て0.999999999超。屋内S/D/Aも同程度だが、
Wは段差付近の衝突で17.786 units／内積0.867566、headingも衝突の影響を受けており、全方向成功とはしない。
方向キーUP probeは両sceneとも移動ゼロで、キーボード拡張flag等による実入力未到達の可能性があるため**実機方向キーは未検証**とする。
R1はnative yaw9271→4935へ変化しつつOrbitのrender eye変化0.0を確認。原作回転処理を止めず、描画Orbitには漏らさない。

### runtime短入力probeの扱い

[validation.json](<C:/PS2CameraLab/test_evidence/grandia2/validation.json>) の`runtime_stick`はyaw45°／内部pitch−30°のまま、
FOVもnative19.995155790°。初回適用に約1.5秒必要だったのに試験待ちが0.4秒と短く、入力変化を捉えていない。
`applied=true`だけを根拠に右スティック成功としない。上表の追加runtime入力確認は、新規runtimeで2秒待ってから2秒入力した別試験である。
これは最適化前のprobe。最終hot publicationの測定は次節の別条件として記録し、短い旧probeを成功へ読み替えない。

### 旧3hook版の最終publication性能・所有確認

親担当の実PINE測定は**hot 10更新で計52.0046ms／360 read**（1更新平均約5.20ms／36 read）。
最適化前は**1更新あたり約0.42秒／6952 read**だった。10更新合計と1更新の値を混同しない。
full cave auditは通常約1秒ごとのruntime再確認で実行し、その処理・通信遅延が加わる。
これはこの環境・限定場面の実測で、全GUIフレームの一定遅延やすべてのPCでの応答保証ではない。

高速化はcave検査の撤去ではなく検査頻度の分離。各bank publicationで3hook pair・control magic・flags・ACKを確認し、
full preflightは初回、backend／epoch変更、state消失、周期`set_patch(True)`、解除で実行する。
backend／epochを跨いだcache共有はせず、**cave本体だけの破損は次の周期auditまで即時検知されない**点を制限として残す。

## 旧3hook版MainWindow＋実PINE／runtime統合 — 確認済み

性能最適化後に親担当が再実行した最終GUI runは、ローカル [gui_validation.json](<C:/PS2CameraLab/test_evidence/grandia2/gui_validation.json>) の**11項目すべてpassed=true**。
文書担当は更新後の結果を読取り、実行は親担当。MainWindow→実PINE→PCSX2の経路で、入力はscripted source。
物理XInput controllerを人が操作した試験ではない。

| 確認 | 結果 |
|---|---|
| 起動・feature | Original起動、Free無効、FOV範囲20〜60° |
| 屋外scripted入力 | yaw約50.927→97.624°、内部pitch約−29.998→−55.469°、actual FOV40.000001056°、error空 |
| 屋内scripted入力 | yaw約45.000→90.982°、内部pitch約−11.997→−37.078°、actual FOV40.000001056°、error空 |
| 独立6offset | 両sceneでeye `(100,25,−80)`／target `(−40,20,60)` をGUIから設定し、render eye/targetへ反映 |
| GUI FOV reset | Orbitのeye/targetを保ったまま屋外19.995155790°／屋内29.992708299°へ復帰（pose保持は親の照合、ログはFOV値を記録） |
| Original | 両sceneで3site stock復帰、error空 |
| 同版stock state再適用 | Orbit中に屋外→屋内stateを読込み、約2秒以内に設定yaw120°／FOV45.000000006°を再適用、error空。続けて解除しnative29.992708299°へ復帰 |

最初のGUI probeは`FloatSlider.set_value()`がsignalを発行しないことを試験側で見落とし、設定変更をruntimeへ渡せなかった。
実ユーザーの数値入力と同じ`spin.setValue()`経路へ試験を修正して上記を再実行した。失敗したprobeを製品側の入力不具合や成功項目に混ぜない。

### 旧3hook版の再現用GUI検証ツール実績

[grandia2_live_check.py](<../../../tools/grandia2_live_check.py>) の当時の版を追加し、ユーザー開始時の屋外場面で親担当が実行した。**12項目すべて成功**。
現行ツールは後述の14項目へ更新されている。この12件は旧source条件の記録。
Original起動・起動書込み0、機能制限、field判定、Orbit適用待機、数値入力とscripted右軸、FOV20／40／60°、
native FOV reset時のpose保持、6offsetの同一actor描画幾何、3hook stock復帰を確認した。
6offsetの相対pose最大誤差は約0.000214 units。これはmailboxとgeometryの数値確認であり、画素比較のPASSではない。

```powershell
python tools/grandia2_live_check.py --out C:/PS2CameraLab/test_evidence/grandia2_reusable_20261107_1228
```

結果と対象source SHA256はローカル [checks.json](<C:/PS2CameraLab/test_evidence/grandia2_reusable_20261107_1228/checks.json>) に保存。
ツール自体はstate／card／GDBを操作せず、MainWindowが唯一のPINE clientを所有する。
任意の`--reload-handshake`／`--capture-window`はこのツールrunでは未使用。別runのstate再適用・実画面確認とは区別する。
実行後に再び開始stateを読込み、下記cleanup状態へ戻した。

## 旧3hook版時点の未網羅範囲・cleanup

| 項目 | 現状 |
|---|---|
| 移動の未網羅範囲 | 4yaw前進とoffset付きW/S/D/Aを限定測定済み。屋内Wは衝突の例外あり。実方向キー入力、全地形、長時間、定速比較は未網羅 |
| 全sceneの補助描画 | コンパス抜き部分にfieldが見える表示は、提供された原作屋外state画像と[clean stock baseline](<C:/PS2CameraLab/test_evidence/grandia2/clean_stock_baseline.png>)で一致。比較した画像ではnative HUDのclip／透明表現に整合し、MOD回帰の根拠ではない。全sceneの補助描画検証は未網羅 |
| メニュー | J/I/L/Kボタンprobeでは5guardは`0,0,1,0,0`、camera flags8のまま。実メニューへの到達や安全な抑止を証明しない。全メニューの描画・復帰は未確認 |
| 最終cleanup／ユーザー状態復帰 | 下記のとおり開始state・3site stock・native focalを読戻し、原作状態で実行中。breakpoint／watchpoint・入力・解析接続を解除 |

途中の失敗・調査中を最終PASSへ合算しない。pause中はguest ACKできないため、撮影／デバッガ接続後はVM実行状態を確認する。
100°の探索ではnative fatal `0x261150`を確認した。原作packet bufferは2MiB、bank `0x428380 / 0x628380`、管理global `0x828380`。
raw RSP撮影によるpauseだけではない停止であり、当時は上限60°へ制限して安全検査の迂回／buffer拡張は行わなかった。

## 旧3hook版の最終cleanup

親担当が開始時の [user_start_20261107_1117.p2s](<C:/PS2CameraLab/sstates/grandia2/user_start_20261107_1117.p2s>) を再読込みし、
Serial／CRC一致・runningを確認。render／tail／moveの3hookはすべてstock、MOD制御・診断flagの確認値は`0,0,0,0,0,0`。
native focalは1815.25891113、水平FOV19.9951557899°へ復帰した。

- actor約`(−412,0.0000998,2260)`、eye約`(995.605835,1379.933228,3789.315674)`、target約`(−412,180.000092,2260)`。
- [復帰画像](<C:/PS2CameraLab/test_evidence/grandia2/user_start_restored.png>)は開始時画像と同じ状態を確認。
- breakpoint／watchpointはいずれも0、試験入力の全キーを解放。MCPを切断し、active PINE clientなし、GUIを開いたまま残していない。
- PCSX2は原作cameraのまま**running**で残した。原本ISO・提供stateは上書きしていない。stage／commit／push／PR作成は行っていない。

## 旧3hook版時点の制限・未網羅

- **Free Camera・ゲーム内時計停止・OriginalのFOV-onlyは非対応**。FOVはOrbitに付随し、当時の範囲は**20〜60°**。100°のnative fatalを受けた制限で、全sceneの60°安全保証ではなかった。
- Orbitにcameraの壁／地形衝突は追加しない。壁内部・裏面・屋内geometryの外側や黒い空間が見える場合は距離・角度を調整する。
- 全エリア・イベント・戦闘・全メニュー・長時間、全カリング／LOD・補助描画、他版は未網羅。
- 6stateの空き領域と参照scanはsnapshotの根拠で、全kernel/DMA・全生存期間の形式的証明ではない。運用時もempty/exact preflightを行う。
- 強制終了・異ゲーム／識別不能時の旧game強制復元はしない。pause／field描画停止中の適用・解除は完了できず、通常場面の再開が必要。
- 結果は上記source・場面・実行条件に対する実装側確認であり、独立レビューではない。上記cleanup時点ではGit公開操作は未実施。その後のユーザー指示によるcommit／push／PR／mergeの状態はGit履歴・GitHubを正本とする。

---

<a id="現行追記--7siteg2c2packet-streaming-2026-11-07"></a>
## 現行追記 — 7site／G2C2／packet streaming（2026-11-07）

この節が今回の現行実装・結果の正本。旧3hook版、初期prototype、最適化前runの件数やframes／flushesを合算しない。
文書担当は現行source、最終raw script、指定JSONを読み整合しただけで、コード／テスト／実機／Git操作はしていない。
画像の内容は親担当が`read_image`で確認した報告として扱い、文書担当の独立検証や画素PASSとはしない。

### 現行の解決と安全境界

- 水平FOV **20〜110°**。render `0x1F60DC`／tail `0x1F6200`／move `0x1C9E90` に、finish **`0x25DEC0`**、
  packet CONTROL **`0x260A60`**／DIRECT **`0x260B38`**／UNPACK **`0x260BF8`** を加えた全**7site**、**5 code resources**、magic **G2C2**。
- 原作はEND生成後に2MiB上限を検査する。bank0/1 `0x428380 / 0x628380` は隣接し、後方管理globalは `0x828380`。
  capacity／fatal検査のbypassやbuffer拡張はしない。
- closed DIRECT／UNPACK入口で **`0x100100 / 0x1100` B**、CONTROLで **`0x100` B** を事前reserve。
  raw put−固定bank baseで使用量を計算し、END→finalize→FlushCache→send→reset→newCNTで原作bank内を分割送信する。
  CPU VU index、queue、projection records/count、描画順序を保持。DIRECT前の追加CNT境界でDMA tagの16-bit QWCも保護する。
- 追加call経路はfull128bit user GPRとHI／LO／HI1／LO1／SA、全FPU register／FCSRを保持し、k0/k1は触らない。
  no-flush CONTROL／UNPACKは6 scratch保存＋integer checkのhot pathに分離した。
- native queue tailは最終frame送信前なので解除には早い。native frame submit `0x260210`の帰還後に全7siteを復元し、ACK／stock exact読戻しを確認する。
  初回one-word render bootstrap、GUIのGuardedBackend、hot全7exact pair・magic・flags・ACK、周期full auditを維持する。
  cave本体のみの破損は次の周期audit（通常約1秒＋遅延）まで即時検知しない。
- 旧G2C1混在はfail-closed。旧adapterを正常解除して終了し、さらにstock state読込みまたはゲーム再起動で旧cave／controlを消してから新版を使う。
  正常解除だけでは旧cave／G2C1 magicが残り新版preflightは拒否する。MOD入りstateはstockではなく、clean stockがなければ再起動する。
  旧caveや未知命令を強制上書きしない。pause／field停止中はguest ACKできず、通常fieldの再開が必要。
- `0x233C1C`をculling dirty flagとした旧根拠は誤りとして訂正し、当該アドレスへのMOD書込みを削除した。
- 6保護stateの最終5生成resource範囲で全zero・direct/KSEG pointer参照なしを親担当が再scanし6件assert成功。
  conditional empty/exactは実生成範囲を検査する。packetは **`[0xBC100,0xBC928)`**、finish予約は **`[0xBD000,0xBD800)`**（実生成end `0xBD378`）。
  他3resourceの境界は[allocation表](<CAMERA.md#所有適用解除と安全>)。予約領域全体・全kernel/DMA・全生存期間の永久空き保証ではない。

### 最終自動テスト — 親担当実行済み

**最終関連aggregate: 448 passed／61.62秒。** 親担当報告のコマンドは次のとおり。

```powershell
python -m pytest -o addopts='' -q tests/test_grandia2_packets.py `
  tests/test_grandia2_stream_lifecycle.py tests/test_grandia2.py `
  tests/test_grandia2_perf.py tests/test_grandia2_gui.py tests/test_core.py `
  tests/test_game_guard.py tests/test_pine_backend.py tests/test_gui.py `
  tests/test_innocentlife_gui.py
```

- focused 5本は **253 passed／2.72秒**（packet24＋stream lifecycle3＋既存更新分226）。448件の内数で、別runの件数を加算しない。
- **435 passed／61.96秒は途中sourceの結果**（当時packet14を含む）。追加tests後の最終448へ更新したため、435を最終件数と呼ばない。
- emitted packet reservationはbank0/1・境界ちょうど／超過、DIRECT-only occupancy、full register保存、native call順、CPU VU index、CNT境界、未知magic／busy／bank拒否をsyntheticで確認。
  lifecycleは全7site所有、最終submitまで解除を待つこと、最初のbootstrap取消、旧G2C1の採用／書込み拒否等を確認した。
- runnerのnative DMA／VIF／GIF／VU・builder・inverse・projection cacheはstub。PS2描画hardware・全sceneの実証ではなく、独立レビューでもない。

### 最終最適化後raw実機run — 屋外／屋内

実行は親担当。ローカル [stream_live.py](<C:/PS2CameraLab/work/grandia2/stream_live.py>) と
[raw checks.json](<C:/PS2CameraLab/test_evidence/grandia2_buffer_20261107/checks.json>) を文書担当が読取り確認した。
protected stock stateを場面ごとに読込み、sole PINE＋GuardedBackendで適用。yaw／pitch／FOV設定・計測はscript、移動入力は行っていない。

| 条件 | 屋外 `outside_base` | 屋内 `inside_base` |
|---|---|---|
| FOV110°短測定 | yaw0／90／180／−90 × **内部**pitch0／25／−30／−89.5、16組各約0.5秒 | 同じ16組各約0.5秒 |
| フレーム進行 | 各6〜15frame | 各14〜16frame |
| 別の水平継続 | yaw45°／内部pitch0／distance2000、20.000秒 | 同条件、20.016秒 |
| 継続時frames／flushes | **239frame／718flush** | **600frame／0flush** |
| 観測boundary highwater | **1126008 B** | **1023844 B** |
| FOV110°読戻し | 110.000001436° | 110.000001436° |
| 最後の広角frameからの全7site解除 | **0.156秒**、stock=true | **0.109秒**、stock=true |
| native reset／解除後FOV | **19.995155790°** | **29.992708299°** |

highwaterはreserve入口の累積観測で、各短測定ごとの独立最大値でも**全write最高水位の証明でもない**。大可視量による負荷増は残る。
両sceneでFOV20／40／60／100／110°を各読戻し確認し、native resetを確認した（raw JSONにはこのループの各値を行として保存せず、script assertionと親報告を根拠とする）。
同じadapterで屋外stock→屋内stockを再loadして再適用成功、全7siteを解除。最後のstock state読込み後はfocal1815.25891113／FOV19.995155790°を記録した。

**初回live assertionの失敗を隠さない:** 初回は「0.5秒で5frame超」という根拠のない速度条件で失敗したが、4frameは進んでいた。
試験predicateをフレーム進行へ修正したうえで別runを成功させ、上表は最終最適化後のそのrunのみ。失敗や最適化前runを成功へ混ぜない。

親担当が同runの[屋外110°水平画像](<C:/PS2CameraLab/test_evidence/grandia2_buffer_20261107/outside_base_110_horizontal.png>)と
[屋内110°水平画像](<C:/PS2CameraLab/test_evidence/grandia2_buffer_20261107/inside_base_110_horizontal.png>)を`read_image`で確認した。
屋外ではgeometry／HUD表示を確認。屋内distance2000水平は小さな室内geometryと黒空間が見える状態であり、camera collisionを持たないOrbitの限界を含む。
この2画像・フレーム進行だけで**全scene描画成功・全geometry完全描画**とはしない。

### MainWindow＋実PINEの別run — 14項目成功

現行 [grandia2_live_check.py](<../../../tools/grandia2_live_check.py>) を親担当が実行し、
[GUI checks.json](<C:/PS2CameraLab/test_evidence/grandia2_buffer_gui_20261107/checks.json>) は `completed=true / passed=true`、**14項目成功**。
MainWindowが唯一のPINE clientを所有する通常field静止場面の別runで、入力はscripted。物理XInput操作・移動・pixel比較・menu/event・長時間の検証ではない。

| 確認 | 結果 |
|---|---|
| Original起動 | Serial+CRC／GuardedBackendを確認し、**0write** |
| feature／範囲 | Free・時計停止無効、6offset有効、GUI／adapterともFOV20〜110° |
| 適用・GUI入力 | ordinary field受理、Orbit開始、spin経由yaw／pitchとscripted右軸が描画mailboxへ反映。scripted差分yaw31.2493°／内部pitch−17.0451° |
| FOV20／40／60／100／110° | actual 20.000000017／40.000001056／59.999997475／100.000002236／110.000001436° |
| native FOV reset | native19.995155790°、Orbit相対pose error **0.0** |
| GUI 6offset | eye `(100,25,−80)`／target `(−40,20,60)`、同actor相対pose error **0.0001934256** units |
| Original復帰 | **全7site stock**、patch inactive |

同JSONは対象source SHA256を保存する。`captures=[]`で、このGUI run自体の画像PASSではない。
外部state再loadはraw runで確認した別条件で、旧GUI11項目・旧再利用ツール12項目を14項目に合算しない。

### 今回の最終cleanup — 親担当実施済み

親担当がprotected [user_start_20261107_1117.p2s](<C:/PS2CameraLab/sstates/grandia2/user_start_20261107_1117.p2s>)を再loadした。
文書担当は[final_stock.json](<C:/PS2CameraLab/test_evidence/grandia2_buffer_20261107/final_stock.json>)を読取り、
Serial `SLPM-65081`／CRC `b6ab7bc2`、全7siteのstock exact pair、control先頭96B全zero、native focal **1815.25891113**、PINE status **0（running）**を確認した。
control全0x800 B（2KiB）や全cave消去を確認したという意味ではない。

- 親担当報告: breakpoint2件を消去し残0、watchpoint0、input reset、MCP切断、sole PINE close。
- PCSX2は今回開始時には未起動で親担当が起動した。終了時はOriginal cameraで**running**のまま残した。
- 原本ISO・提供state／cardは変更していない。旧3hook版cleanupとは別の今回の後始末である。
- 文書担当はGit操作を行っていない。commit／push／PR等をこの記録から推定せず、必要時は親担当が実状態を別途報告する。

### 現行の限界・結果欄の扱い

- 全map・event・menu・battle・長時間、全カリング／LOD・補助描画は未網羅。実方向キー入力や全地形での歩行は旧記録からも未検証を保持する。
- valid native field writerのprotocol／source boundsが前提で、破損データの巨大DIRECT救済はしない。容量／fatal bypass不可、大可視量での負荷増は残る。
- camera collisionはなく、屋内geometry外の黒空間・壁／裏面は距離や角度で調整する。限定画像とframe progressを全scene成功へ拡張しない。
- 6state scanはsnapshotの根拠に限り、empty/exact preflightを維持する。旧G2C1混在はfail-closed、pause中のACK不能も維持する。
- **最終テスト結果欄**は上の448 passed／61.62秒、**今回の最終cleanup欄**は直前節で確定済み。追記待ちの件数／cleanupはない。
  以後sourceを変更・再実行した場合は、そのrunの件数・時間・対象source／evidence・全7site stockと開始state復帰を同欄に追記し、今回や旧版の結果へ合算しない。
- 以上は実装側確認の記録であり、**独立レビューは行っていない**。
