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

### 2026-11-08 — エリア変更後にOrbitを拒否する原因と修正

追加の `other_area` / `other_area_2` を含む6stateを比較。旧 `MAGI_GLOBAL=0x56DB1C` は
専用globalではなく **UObject name-hash `0x56A5D0` のbucket `[0xD53]`** だった。
native insert `0x1B2100` は object `+0x20` のnameを `&0xFFF` し、bucket headを更新する。
元4stateでは偶然 `MrtsGameMagi0`、追加2stateでは `FinalBlend133` / `ConvexPrimitive174` が入り、
いずれも `+0x0C=0` のため旧host/guest guardは通常fieldでもscript frameなしとして拒否した。
renderer/vtableの違いや、field script名IDの変化が今回の原因ではない。

現行は**現在のPawnが所有する参照を毎回たどる**：

- `PLAYER_GLOBAL → Pawn +0x3E4 (Magi) → Magi +0x220 (DataManager)`。
- DataManagerはnative manager registry `0x5527B0[3] = 0x5527BC` と一致し、
  `DataManager +0x7D4 (Magi)` が同じMagiを指すことをhost/guest双方で確認する。
- 3つのpropertyはreflection metadataと6stateの実体で確認。native `0x3F8AA0` はPawn `+0x3E4` setter。
  registryは `0x19B4D0/0x19B4F0` のindex付きsetter/getterであり、hash bucketではない。
- PartyData mode1/2、Magi `+0x0C → frame +0x18 → State +0x20` の**full-u32** field script名判定は維持。
  `0x31CC/0x31D3` は今回6state共通。未知状態を単に許可する修正ではない。
- player/Magiのheap addressや生成instance名IDはキャッシュしない。新playerを含むbankを公開し、
  guestはA2/current player/snapshot player一致後だけ描画と移動の所有権を受理する。

元4stateのMagiは `0x12031B0`、追加2stateは `0x142E990` / `0x1A9F660`。
これらのheap値を製品の探索条件にはしない。native FOV診断もPawn `+0x1EC → controller +0x1F4` に訂正
（旧Pawn `+0x1F4` は6stateで非pointerの `0x3A04` であり、55°fallbackを読んでいた）。

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

consumer yaw は**実視線の native yaw を使い、半回転させない**。描画 yaw と同じく、位置offsetを
含む `target - eye` の水平角が基準であり、`0x8000` は加算しない。加算すると上下左右がすべて逆になる。
2026-11-08修正：旧実験は入力APIの `y=-1`（実際は LDown）を「上」と誤認し、
不要な半回転を導入していた。入力APIは `y=+1` が LUp、`y=-1` が LDown。
描画・actor heading・ミニマップには追加補正を入れない。

原作は4 turn-unit刻みのsin/cos tableと `acos(-y/length)` で移動headingを求める。
ちょうど軸方向の付近では丸め誤差でacos入力が範囲外になり、headingが巨大値になって
移動が止まる条件を確認した。移動consumerだけを90°境界から8 turn units以上離す
（実視線との差は最大8/65536回転、約0.044°）。描画yaw/pitchは正確な実視線のまま。
速度・衝突・向きの更新自体を置換せず、native経路を保持する。
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
追加2stateは旧MOD入りで、旧5hook・全6caveが既知exact、MCA1/ACKも整合していた。
今回版はその**完全一致する旧renderer body＋新版が延長する範囲のゼロ**だけを認識し、
他の全cave・hook pair・control/ACK・native callbackも検査したうえで自動移行する。
旧EE lifecycleへflags0を要求 → ACK・全5hook stock・callback nativeを再検査 →
到達不能となったrenderer caveだけを新版へ置換 → 現在playerのbankを公開・再適用、の順序を守る。
旧命令を実行中のままhostが上書きする方法ではない。pause中・旧transaction中は移行しない。
magic一致だけ、未知/破損したcave、認識外の版との混在、任意の将来版は対象外でfail-closed。
認識外の版では従来通り **clean stock stateまたはゲーム再起動** が必要。原本stateへ保存はしない。

## 制限

確認対象は元4state＋追加2state（2map/2Field・再訪状態）と通常歩行のmap境界越え1例。
所有参照はmapのheap address非依存だが、
selector1/2・active script・player所有確認は全event/menu/battleを完全に識別する保証ではない。
全map、長時間、全特殊camera、強制戦闘は未網羅。実行した条件は [TEST_RESULTS](TEST_RESULTS.md) を参照。
Orbit collision はなく、壁・樹木へのめり込み、裏面・map外の背景は残る。
機能の実装と今回の確認範囲を混同しない。
