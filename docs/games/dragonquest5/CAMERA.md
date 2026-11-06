# ドラゴンクエストV 天空の花嫁 — PS2 Orbit camera

## 版・範囲

- 日本版 **SLPM-65555 / B64E9939**。両方が一致した場合だけGUIの書込みガードを有効にする。
- 2026-11-05、提供された4ステート（`base`、`base_only_wait`、`base_only_camera_move`、`base_chara_and_camera_move`）を解析。
  いずれも同じ海辺の建物・庭の通常パーティ追従場面。4つの別エリアを検証したという意味ではない。
- 原作右スティックは左右回転のみ。MODは右Xをyaw、右Yをpitchに使う。
- Orbit、距離、Y-up注視点高さ、独立したeye/target XYZオフセット、水平FOVに対応。Free Cameraは非対応。
- 通常fieldの歩行・キャラの向きは**実際のOrbit視線基準**。原作のY回転・移動速度・衝突・向き計算を流用し、その2つのyaw consumerだけへOrbitの角度を渡す。Free Camera、別の移動モード、演出用cameraは非対応。
- 原作の通常field用yaw上限・下限・回転入力禁止は描画Orbitに適用しない。ただし**固定視点／イベント／別camera classを一律に解除する機能ではない**。報告された「一部の場所」の個別解除は、ユーザーの追加指示で別件・今回対象外とした。

## 解析の根拠

原本ISO・ステートは変更せず、展開データ・Ghidraプロジェクト・画像は親ラボの`work/dragonquest5`と`test_evidence/dragonquest5`へ保存した。
待機のみで不変、カメラのみで変化、移動を含む状態で追従する値を分離した。
既存の`analysis/minstrelsong/scan_ram.py`を4つの名称指定で再利用した（候補抽出のみ。ゲームの方式は別）。

| 対象 | EEアドレス | 実証・用途 |
|---|---|---|
| native eye / target | `0x81B430 / 0x81B440` | 4state差分。target = player + Y10（提供場面） |
| native yaw | `0x81B460` | 原作左右回転、歩行consumerが参照 |
| field camera update | `0x5800F0` | watchpoint backtrace。native rig・衝突等を更新 |
| field matrix | `0x81B5F0` | `0x695B70`からlook-at生成 |
| render world | `0x81B910` | 上のfield matrixを更新してコピー。guest transactionでのみ置換 |
| render camera/view | `0x81B480` | watchpoint `0x696AD0`、呼出元 `0x6944A0`→`0x4B2480`。逆行列のeye一致 |
| renderer | `0x72B880` | +`0x320`がcameraを所有 |
| player owner | `0x7B50A0` | actor+`0x128`がnode、node+`0x60`がworld position。提供state node=`0x9363A0` |
| lens | `0x81B5DC` | native rad=0.5235987306。描画生成時だけ変更して復元 |
| projection | `0x81B4C0` | `0x6943E0`がcos/sin半角から生成。X後段scale=0.7 |
| camera pad consumer | `0x57E250` | `0x57F370`から呼出。signed processed RX+`0x190`を読む |
| processed pad owner | `0x7058E8` | gp=`0x70C070`、gp−`0x6788`。実入力RX=127を読戻し |

watchpointはMCP/GDBのZ2を使用し、調査後に個別解除した。GhidraのEE Reloadedを既存構成のまま利用し、
見落された関数は対象アドレスだけdisassemble/createFunctionした。ELF load segmentは`0x480000..0x9CE180`。
現行v2は低位`0xF2000..0xF4400`を使用する。ELF外で、4stateとliveの使用領域でzeroを確認したが、全ゲーム状態の永久空き保証ではない。
適用前にexact code/zero以外の占有を拒否する。v1の停止後に残るcave/control blockを上書きしないよう領域とmagicを変更した。
旧controllerが動作中、または旧hookが残るstateでは、先に旧版でOriginalへ戻すかstock stateから起動する。未知hookを自動移行して上書きしない。

## 実装方式

### 描画更新の一時transaction

`0x4B2B6C`の`jal 0x4B2480`だけをcaveへ向ける（delay slotは変更しない）。

1. native renderer/camera/field mode・event関連guardとplayer ownershipを確認。
2. inactive host bankをsequence lockでguest snapshotへコピー。奇数・コピー前後のsequence相違ならnativeへ退避。
3. 最新player node位置をrelative eye/targetへ加算し、正規直交world matrixを構築する。
   hostが停止しても、guestが実行される間は最新player位置へ追従する。
4. 元WORLDとlensを退避し、描画用WORLD/lensだけ差し替えて原作render updateを呼ぶ。
   view、投影、clip関連の派生値は原作が生成する。
5. 呼出後、WORLD/lensを元へ戻してreturn。native rig・原作yaw・actor headingは変更しない。
   再入時は既存pending backupを上書きしない。復元対象はこの呼出が開始したtransactionだけ。

hookの切替は1word。全hook+delay・全cave命令・block占有を最初の書込み前に検査する。
unknown命令、破損cave、別用途のblockは強制上書きしない。
通常解除はflags=0→guest cleanup command→外側render transaction完了→EE threadで4hook復元→ACK読戻し。
PINEから稼働中のnative code pageへ解除書込みをせず、guestが全hook/delayを再検査してから描画hookを最後に外す。
途中で未知命令を検出した場合は一部だけ復元せず拒否する。元から全hookがstockならdataだけ解除する。
VM pause／描画停止では0.5秒で拒否しcleanup requestとhookを残す。再開後にguestが完了するまで再有効化は拒否する。
描画hookだけ欠けて他hookが残る状態ではPINEから強制復元せず、stock state読込みで復旧する。

適用も描画hookの1wordだけをPINEでbootstrapし、残る右入力・移動・向き3hookはguest lifecycleがEE threadで適用する。
hostはbank発行後にflags=0でACKと全4hookを確認してからOrbit/FOVを有効化する。
停止VMでは待機をタイムアウトし、flags=0のnative動作とpending requestを残す。再開・再試行で完了する。
active hookから到達可能なcaveがzero/不一致の状態では、稼働中codeの再構築をせず拒否する。

この変更は、stock state再読込み後の解除・再適用で実測したPCSX2の`Impossible block clearing failure`対策。
公式の[PINEとCPUのprotected-page競合 issue #14589](https://github.com/PCSX2/pcsx2/issues/14589)と診断が一致するが、
当該Windows crashの完全stackは未取得。**描画hookのbootstrapはPINE code書込みが残る**ため、エミュレータの全競合を修正したとはしない。

### 右スティック競合

`0x57F370`のcamera専用consumer呼出だけをwrapperへ向ける。
Orbitかつ通常field guard一致時だけprocessed RXを退避して0にし、原作camera関数を呼んで元のRXへ戻す。
raw packet、RY、左軸、ボタンは変更しない。他のconsumerの右入力を一律に潰さない。
原作L/R系の回転入力やスクリプトyaw更新自体を停止するパッチではない。
Originalではhook自体を返し、原作右スティック左右回転が再び動く。

### 原作yawを流用する歩行・キャラの向き

原作yawは`atan2(target.x-eye.x, target.z-eye.z)`（radian）。GUIのeye-around-target yawと180°違う。
位置offsetを含めた**実際の視線**からnative yawを計算し、sequence付きbankの`+0x60`へ渡す。
原作のglobal yaw `0x81B460`や前回yaw `0x704AA0`は上書きしない。

- 真の移動関数は`0x546B50`。旧解析の`0x546D00`は途中のcall命令であり関数入口ではない。
- 移動ゲート`0x546CCC`と向きゲート`0x5470A8`を各1wordの`j`でcaveへ向ける。元delay storeは保持する。
  原作のmap別camera-relative flag `0x7B782C=0`でも、通常のユーザー歩行をOrbit基準へ合わせる。
- 移動は`0x693D00`の原作Y回転へyawを渡し、向きは原作の入力角+yaw加算へ同じyawを渡す。
  native速度・地形衝突・animationはその後の原作処理のまま。
- vector consumerがstable bankから選んだyawをguest専用latchへ保存し、同じstack frame/nodeの向きconsumerが一度だけ消費する。
  途中でhostがbankを2回再発行しても、同じ歩行内のvector/facingが別yawにならない。
- mid-functionで使うscratch GPRは128bitの`SQ/LQ`で保存・復元する。RA、その他GPR、無関係なFPU値を変えない。
- field guardに加え、movement manager、現在actor/node所有、normal input flags `0x00FFFFFF`、scripted byte `actor+0x28=0`を確認。
  不一致／FOV-onlyでは元の分岐へ戻す。スクリプト歩行・別locomotionを無理に変換しない。
- 描画2hookと合わせ、Original／通常終了では**4hook**を復元する。

### 場所依存の回転制限と未対応camera

原作の`0x57D630`はmap設定のraw limit（rig `+0x48C/+0x490`）を解釈する。
`0,0`は無制限、`1,1`は`+0x204`の回転入力veto、その他は度から`+0x21C/+0x220`のradian上限・下限へ変換する。
描画transactionのOrbitはこのveto/boundsに依存しない。これらの値を永久にzeroへ変更するパッチは不要。
ただし今回調べたISO内291個の有効FLSC headerはraw limitが全て`0,0`だったため、
この仕組みが報告場所の原因だとは断定しない。条件注入試験と実在する制限場所の試験を区別する。

固定eyeのfield mode1、script所有のmode2、actor-forwardのmode3、別familyのcameraは別経路。
固定cameraとイベントが同じscript setterを使用し、normal actor input flagsだけでは区別できない。
またnative入力permission `+0x200=0`はscript suspensionにも使われるため、これを無条件に許可しない。
既存follow/mode/transition/ownership guardを維持し、追加のsuspend `0x81B890!=0`も拒否する。
**特殊cameraの360°回転解除は未対応**。ユーザーの追加指示で別件・今回対象外。将来対応時に場所名／該当stateから個別調査する。

### 座標系・画角

- Yは正が上。内部pitchは共通Y-down数学に合わせ**負でカメラが上**。
  表示・入力係数−1で、GUIは正で上、反転なしの右スティック上でカメラが上がる。
- 表示pitch **−25..+89.5°**、距離 **20..600**、注視点高さ **−50..80**、各offset **−200..200**。
- 既定距離157.223、注視点Y10、表示pitch32°。有効化時の中心化はその場のnative向きを使う。
- 水平FOV `h = 2 atan(tan(native/2)/0.7)`。GUI指定からnative radへ逆変換する。
  rendered projectionのcos/sin比（X後段scale込み）を読み、設定値やミラーだけで同期成功にしない。
  stock水平FOVは約41.89214°。OriginalのFOV-onlyは現共通runtimeの対象外で、FOVはOrbitに付随する。

## 安全・制限

- 全書込みは渡された`self.backend`経由。GUIでは既存GuardedBackendを通し、Serial/CRC/接続世代の変更時は
  旧adapterをrestoreせずabandonする。ガードの検出時間窓は既存仕様どおり残る。
- hostとguest双方で原作通常follow設定、renderer→camera→WORLD所有、event関連値、player nodeを確認する。
  hostはgeometry/lensの有限値も確認。これは**全メニュー・イベント・戦闘判定の保証ではない**。
  特殊場面ではOriginalへ戻す。
- 原作の衝突制限・場所別camera制限はOrbitへ適用しない。壁、屋根、裏面や未描画部分が見えることがある。
  下側pitchや高いFOVでの表示欠けは全エリア未検証。距離・角度を調整する。
- 約1秒ごとのset_patchでstock state読込み後もhostに保持した同じOrbit/FOVを再発行する。
  新stateのplayer所有とnative lensを使用し、古いsceneの絶対座標を復元しない。
- 対応版以外・未知命令・guard不一致では安全側に止まる。強制終了・プロセスkillでは通常解除を実行できない。

実行結果・未検証範囲は[TEST_RESULTS.md](TEST_RESULTS.md)。
