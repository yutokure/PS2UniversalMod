# グランディアII — Orbit・FOV・カメラ基準移動

2026-11-07。日本版 **SLPM-65081 / B6AB7BC2** のみ。Serial と CRC の両方を検査する。
実装は [adapter](<../../../adapters/grandia2/adapter.py>)、[memory map](<../../../adapters/grandia2/memory_map.py>)、[caves](<../../../adapters/grandia2/caves.py>)、[packets](<../../../adapters/grandia2/packets.py>)。
現行は**7site／5 code resources／G2C2、水平FOV20〜110°**。旧3hook／G2C1／20〜60°の結果は[過去記録](<TEST_RESULTS.md#過去記録--旧3hookg2c1fov2060-2026-11-07>)、今回の根拠は[現行追記](<TEST_RESULTS.md#現行追記--7siteg2c2packet-streaming-2026-11-07>)を参照する。
実行済み／保留は [TEST_RESULTS.md](<TEST_RESULTS.md>) に分ける。全エリア・イベント・戦闘対応の保証ではない。

## 対応機能・操作範囲

| 項目 | 範囲・仕様 |
|---|---|
| Orbit | 右スティック左右 yaw／上下 pitch。屋外追従・屋内固定の通常fieldが対象 |
| 距離 | **100〜10000** |
| Pitch表示 | **−25〜+89.5°**、正でカメラが上。内部角は **−89.5〜+25°** |
| 注視点高さ | **−1000〜+1000**、正が上 |
| eye／target XYZ | 独立6軸、各 **−3000〜+3000**、ワールド座標 |
| FOV | 水平 **20〜110°**、Orbitに付随。原作bank内の事前reserve／分割送信を使用。OriginalのFOV-onlyは非対応 |
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
   `NJ_FLAGS`は退避した値へ戻す。**`0x233C1C`をculling dirty flagとした旧根拠は誤り**で、そのアドレスへのMOD書込みは削除した。
   未同定のnative globalへdirty値を強制することで復元済みとはしない。
7. tailはqueue構築の終端であり、queued geometryのemit／submitはその後に行われる。
   解除要求があってもpacket hooksを残し、finish call **`0x25DEC0`**でnative frame submit **`0x260210`**から帰還してから全7siteを復元する。

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
旧3hook版では100°の数値読戻し一致後にnative packet buffer fatalが発生し、当時は20〜60°へ制限した。
その経緯・60°629frame・当時の3hook解除は[旧実績](<TEST_RESULTS.md#過去記録--旧3hookg2c1fov2060-2026-11-07>)として保持し、現行7siteの成功へ読み替えない。
現行の20〜110°は次節のpacket streamingを前提にする。最終最適化後、屋外／屋内で20／40／60／100／110°の読戻し、native reset、全7site解除とstock state再適用を確認した。
110°の4yaw×内部pitch4種・各約0.5秒と水平yaw45°・各約20秒は限定場面のフレーム進行確認で、全sceneの広角安全性・描画完全性を保証しない。
旧コンパス抜き部分のfield表示は比較した原作baselineと一致したが、これも全sceneの補助描画を保証しない（[現行結果・画像の範囲](<TEST_RESULTS.md#現行追記--7siteg2c2packet-streaming-2026-11-07>)）。

<a id="packet-streaming--2mibを拡張せず事前reserveする"></a>
## Packet streaming — 2MiBを拡張せず事前reserveする

### 原因と変更しない境界

原作は**END生成後**にbankの2MiB上限を検査する。bank0 **`[0x428380,0x628380)`** とbank1 **`[0x628380,0x828380)`** は隣接し、
直後の **`0x828380`** から管理globalがある。広角で可視geometryが増えた際、遅い検査まで無制限に蓄積させては隣bank／管理領域を破壊し得る。
容量定数・fatal分岐のbypassやbuffer拡張はしない。既存の2bank・2MiB上限・native fatal検査を維持する。

### Closed payload入口のreserveと順序

[packet emitter](<../../../adapters/grandia2/packets.py>)はCONTROL **`0x260A60`**、DIRECT **`0x260B38`**、UNPACK **`0x260BF8`** の入口をhookする。
未完のDIRECT／UNPACK内へ割り込まず、payloadが閉じている境界で次の書込みに必要な余裕を先に確保する。

| 入口 | 事前reserve | 根拠 |
|---|---|---|
| CONTROL | `0x100` B | 制御・alignment・終端等の余裕 |
| DIRECT | `0x100100` B | VIF DIRECT最大65535 QW＋alignment／終端・制御余裕 |
| UNPACK | `0x1100` B | 最大256 QW＋alignment／終端・制御余裕 |

使用量は **raw put `[0x8283A8]` − (`0x428380`＋bank index `[0x428300]`×`0x200000`)** で求める。
変動するCNT／payload基点をbank baseと誤認しない。余裕が足りなければ次の原作関数列を使用する。

```text
END 0x2610D8 → finalize 0x261268 → FlushCache(0) 0x2A5820
→ send 0x261358 → reset 0x260F50 → newCNT 0x261098
```

DIRECT-onlyでUNPACK work countが0でも必要なflushを行うため、そのcountで抑止される便利入口を使わない。
CPU側VU index **`[0x828398]`** は退避／復元する。queue・projection cache／count・描画順序を保持し、geometryの破棄やカリングでごまかさない。
追加のDIRECT前CNT境界 **`0x260D90`** により、累積mesh＋DIRECTのDMA tag **16-bit QWC** がbank容量とは別にoverflowするのを防ぐ。
ただしvalid native field writerのprotocol／source bounds（field source scratchは80000 **decimal** B、fontも有界）が前提で、
破損データや任意の巨大DIRECTを有効なpacketへ修復する機能ではない。

### Register透明性・性能・診断

追加native callを行う経路はuser GPRをfull128bitで保存し、HI／LO／HI1／LO1／SA、全32 FPU registerとFCSRも保持する。
kernel scratch k0/k1は変更せず、SPを元に戻す。元の第2命令はdelay slotで保持し、退避した第1命令を実行してnativeへ戻る。
no-flush CONTROL／UNPACKは6 scratch GPR保存とinteger checkだけのhot pathとし、実flush／DIRECTのfull-save callから分離する。
親担当は命令encoding照合に[PCSX2 opcode tables](<https://github.com/PCSX2/pcsx2/blob/master/pcsx2/R5900OpcodeTables.cpp>)を参照した。
これはversionが異なるmasterのencoding資料であり、game固有の根拠は対象state／実測に置く。実行検証の代用にはしない。

mailboxはflush回数・boundary highwater・stream busyを記録する。**highwaterはreserve入口の観測値であり、全writeの最高水位を計測した証明ではない。**
大可視量では送信／描画仕事量と負荷増が残る。最終raw runの屋外239frame／718flushと屋内600frame／0flushは各約20秒・固定sceneの結果で、速度保証ではない。

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

- 現行hookは次の**7site**。元のdelay slotを保持し、guestは変更前に全siteのstock／自所有exact pairを先に検査する。

  | site | EEアドレス | 役割 |
  |---|---|---|
  | render | `0x1F60DC` | native camera更新後の描画コピーtransaction |
  | tail | `0x1F6200` | native数値復元。ここでは最終解除しない |
  | move | `0x1C9E90` | 移動cameraコピー |
  | finish | `0x25DEC0` | `0x260210`から帰還後の最終解除 |
  | packet CONTROL | `0x260A60` | closed control入口reserve |
  | packet DIRECT | `0x260B38` | closed DIRECT入口reserve＋CNT境界 |
  | packet UNPACK | `0x260BF8` | closed UNPACK入口reserve |

- code resourcesは次の**5個**。control **`[0xFD000,0xFD800)`** は別のmailboxで、magicは **`G2C2 = 0x47324332`**。
  endは排他的。実長は今回の最終emitterに対する親担当報告で、将来変更時は生成長を優先する。

  | resource | 予約境界 | 現行生成範囲／words |
  |---|---|---|
  | render | `[0xB9000,0xBA000)` | `[0xB9000,0xB9AF0)`／700 |
  | tail | `[0xF5000,0xF5800)` | `[0xF5000,0xF5704)`／449 |
  | move | `[0xF5800,0xF6000)` | `[0xF5800,0xF5B64)`／217 |
  | packet shared＋entry wrappers | `0xBC100`からfinish `0xBD000`未満 | **`[0xBC100,0xBC928)`／522** |
  | finish | **`[0xBD000,0xBD800)`** | `[0xBD000,0xBD378)`／222 |

  `preflight()`のempty／exact code検査・初期書込みは**実生成範囲**が対象で、packet予約末尾まで全域を所有・検査したとは言わない。
  6保護stateで今回の最終5生成範囲が全ゼロ、snapshot上direct/KSEG pointer参照なしを再確認したが、全kernel/DMA・全生存期間の空き保証ではない。
- 初回・backend／接続epoch変更・state消失・約1秒ごとの`set_patch(True)`・解除時は、全7hook+delay、全5生成resource、controlをfull preflightする。
  hookはstock／自所有pair、caveは全ゼロ／現行exact code、controlは全ゼロ／現行magicに限る。未知所有はその取引の書込み前に拒否する。
- 通常の各bank publicationは、同じadapter/backend/epochでの準備済み状態に限り、**全7hookのexact pair・control magic・Orbit flags・ACK**を毎回確認する。
  所有確認を別backend／epochへ流用しない。**cave本体だけの破損は即時検知ではなく、次のfull auditで検知する**
  （通常約1秒＋runtime／通信遅延）。ホット経路の軽量検査を全cave毎回検証と誇張しない。
- hostがnative codeへ書くのは初回renderの1word bootstrapだけ。guest lifecycleは**全7siteを先に検査してから**適用／復元する。
  transaction中の解除要求は数値復元だけでは完了せず、**最終Orbit frameのsubmit帰還後**に全7siteを復元する。
  native queue tailでpacket hooksを解除するとqueued広角geometryが未送信のまま残るため早すぎる。ACKと全site読戻しを確認し、cave自体は消去しない。
- **旧G2C1は現行所有と認めずfail-closed**にする。旧adapterを正常解除して終了し、さらにstock state読込みまたはゲーム再起動で旧cave／controlを消してから新版を使う。
  正常解除だけでは旧cave／G2C1 magicが残り、新版preflightは拒否する。MOD入りstateはstockではないため、clean stockがなければ再起動する。
  旧adapterと新版を同時に走らせず、旧cave・未知命令を現行exactとして上書きしない。
- ACK待ちは最大1.5秒。**PCSX2一時停止中はguestが進まないため完了できない**。通常fieldを再開して再試行する。
  強制終了時の自動復元は保証しない。初回bootstrapのPINE code書込みは残り、PCSX2の全code-page競合を解消する保証ではない。
- host/guestはnative mode **8（屋外追従）と0（屋内固定）**を許可し、field words `0x23217C=0`、`0x2324FC=0`、
  `0x232538=1`、`0x232530=0`、`0x23253C=0`、owner/nodeを検査する。hostは不正geometry・特異な垂直視線も拒否する。
  これを全menu/event識別とは呼ばない。未確認場面ではOriginalへ戻す。
- runtimeの約1秒ごとの再確認でstock state後の再適用を行う。今回の最終raw runでも同じadapterで屋外→屋内stock state読込み後の再適用・全7site解除を確認。
  旧3hook版MainWindowのyaw120°／FOV45°再適用とは別runで、合算しない。測定条件・未網羅範囲は結果文書を優先する。
- 書込みは`self.backend`経由。GUIはSerial+CRCの既存[GuardedBackend](<../../../core/memory_backend/guard.py>)を使い、
  別ゲーム・識別不能・接続世代変更では旧adapterを復元書込みせず破棄する。既存guardの検出時間窓は残る。

## 制限・データ保護

Orbitには原作cameraの壁／地形衝突を追加しない。壁内部・裏面・屋内の未作成geometryや黒い空間が見える場合は距離・角度を調整する。
全エリア・イベント・メニュー・戦闘・長時間、広角時の全カリング／LOD・補助描画は未網羅。
屋外110°水平画像はgeometry／HUD表示を親担当が確認したが、屋内距離2000水平は小さな室内geometryと黒空間が見える条件で、全scene描画成功とはしない。
valid native field writerのprotocol／source boundsが前提であり、破損巨大DIRECT救済はしない。大可視量の負荷増は残る。
原本ISO・ELF・6提供ステート・RAM・画像はGitに入れない。提供ステートの場所・ユーザー開始状態の退避先は [検証記録](<TEST_RESULTS.md#データ保護と対象>) を参照。
