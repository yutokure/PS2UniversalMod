# マグナカルタ — 日本版フィールド統合

対象は **SLPS-25401 / EB925207**。Serial と CRC の両方を確認する。
実装は [adapter](../../../adapters/magnacarta/adapter.py)、[memory map](../../../adapters/magnacarta/memory_map.py)、
[描画・lifecycle](../../../adapters/magnacarta/caves.py)、[移動](../../../adapters/magnacarta/directions.py)、
[ゲーム固有切替](../../../adapters/magnacarta/gameplay.py)。確認結果は [TEST_RESULTS](TEST_RESULTS.md)。

## 解析の基準

2026-11-07、提供された4state（`walking_base`、`walking_base_only_wait`、
`walking_base_chara_and_camera_move`、`running_base`）を保護してローカルへ展開。
ISO は原本を変更せず ELF を抽出し、Ghidra EE Reloaded、オンライン watchpoint、PINE 読戻しで照合した。
RAM・ELF・state・画面・大量の逆コンパイル結果はリポジトリに含めない。

walking/running はアナログの大小ではなく**ゲーム固有のモード**。
owner `0x5527BC` → `+0x330` → selector byte `+0x91` は walking=2 / running=1。
一方、反射情報と4stateのfull FName idから得た GameMagi active script-state は
walking=`MrtsFieldStateDetectMode`（`0x31CC`）、running=`MrtsFieldStateNormalMode`（`0x31D3`）。
初期の静的な名前対応推測に逆転があったため、実際のstate chainを正本とする。
モードを固定して視界を変える方法は速度・遭遇にも作用するため使わない。

## 座標・カメラ

native は XY 平面・Z 上。adapter 境界で `(X,-Z,Y)` に変換し共通数学を変更しない。
player global `0x53B868` → actor `+0xD0` が位置、`+0xDC/E0/E4` が Unreal rotator。
描画nodeの Z は actor より80低い場合があり、移動判定の位置と混同しない。

- field renderer `0x2B3940` の call `0x2B3B7C` → builder `0x2BD4B0`。
- A3=eye pointer、T0=整数 rotator pointer、F12=水平FOV（sample native 55°）、A2=player view actor。
- 描画専用 wrapper は最新 actor 位置に相対 eye/target を足し、**ローカルのeye・rotator・FOV引数だけ**を差し替える。
  原作 rig、camera yaw、input buffer、actor heading は保持する。
- native view `0x57FC90`、診断eye `0x5808D0` は host による連続上書き先ではない。
- FOV は builder が projection/frustum を同時生成する実引数。水平20〜110°、距離150〜6000、Pitch−25〜89.5°。
  eye/targetの独立6軸offsetに対応。Free Camera は非対応。
- 原作右スティックの専用 camera consumer は確認されず、追加の入力遮断パッチはない。

## 移動とミニマップ

`ProcessAnalog 0x445C30` は入力が継続すると native camera rotator を cache する。
axes builder の共通call `0x446314` → `0x192080` を wrap し、fresh/cache 両経路の
**関数ローカルrotator yawだけ**を差し替える。原作速度・衝突・heading slew を流用する。

実入力から、axes の「上」は描画 forward と逆の基底を使うことが分かったため、
consumer yaw は実視線 native yaw に `0x8000` を足す。描画 yaw 自体は変更しない。
actor/accepted snapshot/controller pawn の一致がない場合は native に戻す。
render ごとに accepted ownership を失効し、その frame で再受理した場合のみ再設定する。

`DrawMiniMap 0x395F60` の矢印は camera ではなく **Pawn `+0xE0` の実heading** を描く。
従って矢印に camera yaw を直接書かない。移動と原作の向きが同期すれば native 矢印も追従する。
静止中に camera だけを回しても actor 矢印は勝手に回さない。

## ゲーム固有の2スイッチ

### 走行中の広域表示

GameMagi `+0x378` の `fPlayerSightRange` は walking=960 / running=240。
`0x3FA780` の alpha consumer（`0x3FA7A8`）に渡す値だけを `max(native,960)` にする。
**mode、速度、Pawn DetectRange、native sight 値は変更しない**。
敵等の該当 alpha consumer の視認範囲を歩行相当に広げる。
地形の遠方描画を無制限にする機能ではない。別経路の `ProcessSpiderMineAlpha 0x41E6F0` は対象外。

### エンカウント無効／オレンジの丸枠非表示

monster `TickNative 0x3F67A0` の距離・接触判定後 `0x3F6B04` から
通常の proximity → detect-state 遷移を抑止する。敵object自体は破棄しない。
既に戦闘へ移行中・scripted/強制戦闘の取消しではない。

range mesh は `0x29890C` → `0x1D0470` で player 中心・半径を登録し、`0x1D04C0` が描画する。
`0x1D04DC` の**ローカル描画半径だけ**を0にして早期returnする。
登録global `0x53B864`、Pawn DetectRange、モード・移動速度は保持する。
**この枠を隠すのは no-encounters ON のときだけ**。Orbit や広域表示単独では隠さない。
OFF で native 命令・表示・遭遇判定に戻る。

2つともカメラから独立し Original でも使える。起動・再接続時OFF、設定・プリセットへ保存しない。
Original radio は選択を保持、無効化ボタン・正常終了は解除。ゲーム識別不能・別game時は
GuardedBackend と runtime abandon により別gameへの解除書込みも行わない。

## 適用と復元の安全

host codewrite bootstrap は使わない。renderer vtable の **data pointer `0x505C84`**
（元 `0x2B3940`）を一時 callback へ向け、EE thread が全5siteの stock/exact patched pair を
事前検査して適用・復元する。callback は自身のpointerを元へ戻し native methodへ tail-call する。
loop の途中で未知命令を見つけて半分適用することはない。

制御block `0xFF000`、magic `MCA1`。cameraパラメータは sequence付き二重bank。
空／自所有exact以外のcode caveは使わず、magicだけで未知caveを上書きしない。
4stateで空でも永久予約済み領域の証明ではない。

full preflight は初回・接続epoch変更・state消失・約1秒周期・解除時。
hot path は全hook pair、magic、flags/ACK/vtableを確認する。
cave bodyだけの破損は次のfull auditまで検出遅延がある。
pause中はEEが動かずACK不能。ゲームを再開して再試行する。
新版でcave生成内容が変わった場合、旧版を正常解除した後でもcaveは残るため、
**clean stock stateを読むかゲーム再起動してから**新版を使う。未知cave強制更新はしない。

## 制限

提供stateは同一フィールド付近の限定条件。selector1/2とplayer所有確認は全event/menu/battleを
完全に識別する保証ではない。全map、長時間、全特殊camera、強制戦闘は未網羅。
Orbit collision はなく、壁・樹木へのめり込み、裏面・map外の背景は残る。
機能の実装と今回の確認範囲を混同しない。
