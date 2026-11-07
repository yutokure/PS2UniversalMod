# グランディアII — Orbit・FOV・カメラ基準移動

2026-11-07。日本版 **SLPM-65081 / B6AB7BC2** のみ。Serial と CRC の両方を検査する。
実装は [adapter](<../../../adapters/grandia2/adapter.py>)、[memory map](<../../../adapters/grandia2/memory_map.py>)、[caves](<../../../adapters/grandia2/caves.py>)。
実行済み／保留は [TEST_RESULTS.md](<TEST_RESULTS.md>) に分ける。全エリア・イベント・戦闘対応の保証ではない。

## 対応機能・操作範囲

| 項目 | 範囲・仕様 |
|---|---|
| Orbit | 右スティック左右 yaw／上下 pitch。屋外追従・屋内固定の通常fieldが対象 |
| 距離 | **100〜10000** |
| Pitch表示 | **−25〜+89.5°**、正でカメラが上。内部角は **−89.5〜+25°** |
| 注視点高さ | **−1000〜+1000**、正が上 |
| eye／target XYZ | 独立6軸、各 **−3000〜+3000**、ワールド座標 |
| FOV | 水平 **20〜60°**、Orbitに付随。100°でnative packet buffer停止を確認したため上限を60°に制限。OriginalのFOV-onlyは非対応 |
| 移動 | 実際のeye→targetの水平視線を原作の移動・向き計算へ渡す |
| 非対応 | Free Camera、ゲーム内時計停止 |

座標は **Y-up**。共通Orbit数学の内部pitchは負でeyeが上になるため、表示・入力係数をともに−1にする。
yawはeyeがtargetの周りを回る角度で、0°ではeyeがtargetの+Z側、90°では+X側にある。
注視点はplayer＋高さ＋target offset。eye offsetはそこから計算したeyeだけに加算するため、offset使用時の実視線は設定yawと異なり得る。

既定設定は屋外に合わせ、距離2400、表示pitch30°（内部−30°）、注視点高さ180、yaw45°、FOV20°。
これは全屋内の原作値を表す既定値ではない。有効化時の中心化はその場のnative向きを使う。
原作に右スティックカメラはなく、入力遮断パッチを追加しない。確認した屋外の原作yaw操作はL1/R1、屋内は固定視点。

## 解析根拠・所有するデータ

提供6ステートを保護して差分を調べ、runtime watchpointと既存Ghidra解析でfield描画・移動consumerを追った。
ELFのロード範囲より低位にある動的overlayのfieldコードをstateから確認した。ELF内に対象がないことだけで経路を除外しない。

| 対象 | EEアドレス／型 | 意味 |
|---|---|---|
| native camera | `0x232B00`、size `0x70` | 原作所有。MODはこのstructへ書かない |
| eye／target | `0x232B04 / 0x232B44`、float XYZ | 原作の視点・注視点 |
| distance | `0x232B50`、float | 原作の距離入力 |
| pitch／yaw | `0x232B54 / 0x232B58`、int | 1周65536の原作角度。floatではない |
| native FOV angle | `0x232B20`、int | 同じ角度単位。ただし最終focalは別経路で上書きされる |
| field focal | `0x232B88`、float | 最終投影・frustumで一致させる焦点距離 |
| NJ camera | `0x2418A0`、size `0x40` | 描画builder入力。MODはコピーを渡す |
| field VIEW／WORLD | `0x233010 / 0x233050` | native fieldが生成するviewとその真の逆行列 |
| NJ numeric state | `0x2EA298`、size `0xC0` | focal・view・行列stack関連の描画数値 |
| player owner | `[0x23258C] → owner+0x24 → node+8` | 最新player XYZ。owner/nodeは4byte整列でよく、16byte整列を要求しない |

playerはprimary owner→nodeを使う。`0x232C80`側のsecondary mirrorをprimaryとして扱わない。
ホストは相対eye/targetとowner/nodeを公開し、guestがそのフレームのnode位置を加算する。
ホストの絶対座標連続書込みに依存せず追従し、sceneを跨ぐ古いplayer座標を復元しない。

## 描画transaction

1. field render call **`0x1F60DC`** をwrapperへ向け、原作camera関数 **`0x20D808`を一度だけ**呼ぶ。
   native rig・平滑化・L1/R1等の更新は止めない。
2. 二重bankの安定snapshot、field guard、現在のowner/nodeを確認する。
   odd sequence・コピー前後のsequence不一致・所有変更ならOrbitを使わず原作へ戻る。
3. native NJ数値・stack・field focal・flags・current projection record pointerを退避する。
   退避用native VIEWは今回のNJ viewから取得し、`0x2599D8`で逆行列も作る。前フレームのfield出力を退避元にしない。
4. NJ cameraをscratchへコピーし、eyeと**正規化した実視線forward**を差し替え、rollを0にする。
   builder **`0x25C908`**へこのコピーを渡す。原作cameraと原作NJ cameraは変更しない。
5. builder後、最終focal setter **`0x25D4D8`**へ選択したfocalを渡し、`FIELD_FOCAL`も同じ値にする。
   その後のnative fieldがviewをコピーし、真の逆行列・frustum等を生成する。行列要素の単純差替えだけで済ませない。
6. field tail **`0x1F6200`**で数値・stack・native VIEW/WORLD・focal・flags・current projection pointerを戻す。
   **既にqueueされたprojection cache entriesとcountは巻き戻さない。** 描画packetが参照するrecordを破壊しないためである。
   次のculling consumerがnative数値から再構築するようdirty状態を戻す。

render中に選んだeye/target/focalはMOD mailboxへ記録する。
`read_game_pose()`／`read_fov_deg()`は適用時にこの診断値を使う。tail後にnativeへ戻った出力をOrbitの現在値と誤認しない。
これらの設計・synthetic testだけで、すべての補助描画／メニューへの副作用がないと証明したことにはならない。

## FOV — angleだけではなく最終focal

提供場面の原作値は次のとおり。角度fieldの量子化があるため、整数の20°／30°と実画角は少し異なる。

| 場面 | distance | pitch | 注視点高さ | final focal | 実水平FOV |
|---|---|---|---|---|---|
| 屋外 | 2400 | 30° | 180 | 約1815.2589 | 約19.995° |
| 屋内 | 1400 | 12° | 180 | 約1194.5603 | 約29.993° |

pitchは原作入力の度換算。focalは距離ではない。屋内の1194.5603をeye-target距離として使わない。
原作angleだけを書いても後段のfield focalで上書きされるため、FOV制御は最終focalとfrustumを一致させる。

```text
width  = [0x2EA29C]
aspect = [0x2EA350]
focal  = width / (2 * tan(radians(horizontal_FOV) / 2) * aspect)
actual horizontal_FOV = degrees(2 * atan(width / (2 * focal * aspect)))
```

実装はwidth/aspect/focalの有限値と範囲を検査する。表示用スクリーンショット幅をwidthの代用にしない。
FOVを上書きしないOrbitと「ゲーム値に戻す」は**そのフレームのnative focal**を使う。
過去のlens値をnative cameraへ書き戻さない。OriginalのFOV-onlyでは描画／移動hookを有効化しない。
探索時の20/60/100°は数値読戻しが一致したが、**100°ではnative packet bufferのfatal停止を確認したため、現在の上限は60°**。
100°をUI／保存設定・プリセットから使える範囲として残さない。上限2MiBの2bankと管理globalは原作のまま保持し、安全検査の迂回やbuffer拡張はしない。
stock stateで復旧後、60°を限定屋外場面で629フレーム継続し、3hook解除・native focal約1815.2589への復帰を確認した。
追加runで屋外／屋内とも20／40／60°の画面・読戻し、その場のnative FOVへのresetと3hook解除を確認。
**60°なら全sceneで安全という保証ではない。** コンパス抜き部分にfieldが見える表示は、提供された原作stateの画像とclean stock baselineでも一致した。
比較した画像の範囲ではnative HUDのclip／透明表現であり、MOD回帰の根拠とはしない。補助描画を全scene保証する確認ではない（[検証記録](<TEST_RESULTS.md>)）。

## カメラ基準移動

**`0x1C9E90`**の原作移動関数 **`FUN_001CB030`** 呼出をwrapperへ向ける。
pad引数はそのまま、camera引数だけをMOD専用コピーへ変える。コピーの`+0x58`だけを以下の角度にする。

```text
native_eye_yaw = round(atan2(eye.x-target.x, eye.z-target.z) * 65536 / (2*pi))
```

signed16の1周範囲へ正規化した値を32bit整数として保持する。
設定yawをそのまま流さず、eye/target offsetを含む実際の視線を使う。
analog・方向キー・速度・キャラheading・地形衝突は元の移動関数に任せる。
原作camera yawやactor座標・headingの直接書込み、raw入力の遮断はしない。guard不一致では元のcamera引数で原作を呼ぶ。
実機の短い歩行測定と、未測定の方向／地形は [TEST_RESULTS.md](<TEST_RESULTS.md>) で区別する。

## 所有・適用／解除と安全

- hookはrender `0x1F60DC`、tail `0x1F6200`、move `0x1C9E90` の3箇所。元のdelay slotは保持する。
- caveは **`[0xB9000,0xBA000)`**、**`[0xF5000,0xF6000)`**（tail `0xF5000`、move `0xF5800`）、
  controlは **`[0xFD000,0xFD800)`**、magicは`G2C1`。ELFより低位にある。
  6stateで全ゼロ、snapshot上のdirect/KSEG参照なしを確認したが、全kernel/DMA・全生存期間の空き保証ではない。
- 初回・backend／接続epoch変更・state消失・約1秒ごとの`set_patch(True)`・解除時は、全hook+delay、cave、controlをfull preflightする。
  hookはstock／自所有pair、caveは全ゼロ／現行exact code、controlは全ゼロ／自所有magicに限る。未知所有はその取引の書込み前に拒否する。
- 通常の各bank publicationは、同じadapter/backend/epochでの準備済み状態に限り、**3hookのexact pair・control magic・Orbit flags・ACK**を毎回確認する。
  所有確認を別backend／epochへ流用しない。**cave本体だけの破損は即時検知ではなく、次のfull auditで検知する**
  （通常約1秒＋runtime／通信遅延）。ホット経路の軽量検査を全cave毎回検証と誇張しない。
- hostがnative codeへ書くのは初回renderの1word bootstrapだけ。guest lifecycleは**3siteすべてを先に検査してから**適用／復元する。
  transaction中の解除要求はtailの数値復元後に処理する。ACKと全site読戻しを確認し、cave自体は消去しない。
- ACK待ちは最大1.5秒。**PCSX2一時停止中はguestが進まないため完了できない**。通常fieldを再開して再試行する。
  強制終了時の自動復元は保証しない。初回bootstrapのPINE code書込みは残り、PCSX2の全code-page競合を解消する保証ではない。
- host/guestはnative mode **8（屋外追従）と0（屋内固定）**を許可し、field words `0x23217C=0`、`0x2324FC=0`、
  `0x232538=1`、`0x232530=0`、`0x23253C=0`、owner/nodeを検査する。hostは不正geometry・特異な垂直視線も拒否する。
  これを全menu/event識別とは呼ばない。未確認場面ではOriginalへ戻す。
- runtimeの約1秒ごとの再確認でstock state後の再適用を行う。性能最適化後のMainWindow実機runでも、
  屋外→屋内state後のyaw120°／FOV45°再適用と解除を確認。測定条件・未網羅範囲は結果文書を優先する。
- 書込みは`self.backend`経由。GUIはSerial+CRCの既存[GuardedBackend](<../../../core/memory_backend/guard.py>)を使い、
  別ゲーム・識別不能・接続世代変更では旧adapterを復元書込みせず破棄する。既存guardの検出時間窓は残る。

## 制限・データ保護

Orbitには原作cameraの壁／地形衝突を追加しない。壁内部・裏面・屋内の未作成geometryや黒い空間が見える場合は距離・角度を調整する。
全エリア・イベント・戦闘・長時間、広角時の全カリング／LOD・補助描画は未網羅。
原本ISO・ELF・6提供ステート・RAM・画像はGitに入れない。提供ステートの場所・ユーザー開始状態の退避先は [検証記録](<TEST_RESULTS.md#データ保護と対象>) を参照。
