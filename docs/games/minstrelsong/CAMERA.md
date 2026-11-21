# ロマンシング サガ -ミンストレルソング- カメラ解析

対象: 日本版 **SLPM-65920 / CRC 2B9AF3C5**。初回解析2026-11-04、フィールド追従モード1の追加2026-11-21。
ISO・ELF・RAM・画像・ステートはラボのGit管理外に置き、ここにはアドレスと測定要約だけを記す。

## 対応範囲

- 通常フィールドの追従モード1・2でOrbit、距離1〜80、Pitch −25〜89.5°（正が上）、注視点高さ−10〜10（負が上）。
- 独立した視点XYZ・注視点XYZオフセット（−30〜30）、水平FOV20〜110°。
- 原作のコンパス方位盤とキャラクターの針、カメラ基準の歩行方向へ連動する。
- Free Cameraは非対応。原作は右スティックでカメラ回転しないため入力遮断パッチは追加しない。
- 原作カメラの衝突補正はOrbitへ適用しない。壁の内側・柱・未描画面が見えることがある。
- 11月21日のOrbit・Original復帰の確認はカクラム砂漠（モード1）と既存5ステート（モード2）。メニューはモードだけでは識別できないので Original に戻す。全エリア・全イベント・戦闘・長時間は未検証。

## 4ステートからの発見

原本は `sstates/ミンサガ/` の `base`、`base_only_wait`、`base_chara_move`、
`base_chara_move_and_camera_big_move`。読み取りで展開し、元ファイルはSHA-256一致を確認した。
解析器は [`scan_ram.py`](../../../analysis/minstrelsong/scan_ram.py)。時間だけの差分を除外し、
4byte alignmentのaffine行列・float3・角度を探索する。候補順位はカメラ所有の証明ではない。

| 値 | base / wait | chara_move | big_move |
|---|---|---|---|
| Eye | (23.58605, −8, 49.20268) | (23.70593, −8, 49.46020) | (12.85530, −8, 44.68508) |
| Target | (25.53945, −5.5, 56.88401) | (23.80445, −5.5, 57.15674) | (25.65059, −5.5, 53.17947) |
| Actor heading rad | 3.1235154 | 1.6261259 | 0.3474504 |
| Orbit yaw rad | −2.8925667 | −3.1287930 | −2.1568594 |
| 距離 | 8.310754 | 8.092988 | 15.560340 |

`0x00396E20 / 0x00396EB0` はbase/wait/chara_moveで64byte完全一致の古い行列。
ライブwrite watchもヒットせず不採用。近似正規化の行列へtrace-acosを直接使うと同一行列でも
偽の微小角が出るため、scannerはSO(3)へ投影して回転差を求める。

実viewは `0x00417410`。`p_view = p_world @ V` のrow-vector形式、basisはcolumns、
最終rowは `−eye @ R`。全4状態でlook-at再構成との最大回転誤差 `1.244e−7`、translation誤差
`5.701e−6`。逆行列translationはEyeと `5.032e−6` 以内。`0x00483220 / 0x004AE280` は同一ミラー。

## ライブの書込み元・アドレス

`0x00417410` のwrite watchで `0x0027F124` のidentity初期化storeへ停止。
backtraceは `FUN_0027F0F0 → FUN_001875C0 → FUN_001108F0`。
Ghidraで後続のlook-at生成とfield専用callを確認した。共有builderそのものはパッチしない。

| アドレス | 意味 |
|---|---|
| `0x004172D0` | 静的フィールドcamera構造 |
| `0x00417410` | View行列 |
| `0x00417450 / 0x00417460` | 原作Target / Eye（変更しない） |
| `0x00417470 / 0x00417480` | up / view追加translation |
| `0x00417490` | cameraのtarget owner pointer |
| `0x00417520` | camera mode。フィールド追従1・2だけ受理 |
| `0x00417524` | 原作焦点距離。512.8956299、変更しない |
| `0x0041752C / 0x00417530` | 消費側へ渡るOrbit yaw(rad) / distance |
| `0x00417534 / 0x00417538` | 前frameのyaw / distance |
| `0x004173D0 / +0x14` | 投影のX / Y scale |
| `0x004189B0 / +0x14` | canonical player位置 / heading |
| `0x003910C0 / 0x003910B4` | 提供状態のactor node位置 / heading（adapterはここへ固定しない） |
| `0x004899D0` | active camera pointer |

## 方式: 原作リグを保持し、field最終引数だけ置換

[`memory_map.py`](../../../adapters/minstrelsong/memory_map.py)、
[`caves.py`](../../../adapters/minstrelsong/caves.py)、
[`adapter.py`](../../../adapters/minstrelsong/adapter.py)。

### 1. Camera call `0x00110BB0`

stock `jal FUN_001875C0` の1wordだけをcaveへのjalへ置換し、delay `move a1,s3`は保持。
原作は毎frame native eye/targetを更新し続ける。guestはhostが公開した相対Eye/Targetへ
最新canonical player位置を加算し、**a1/a2だけ**をguest slotへ向ける。a0(view)、a3(up)、
t0(第5引数)を保持する。原作Target/Eye/headingは一切書き換えない。

hostは二bankをodd/even sequenceで公開。guestは選択bankを自分専用snapshotへコピーし、
sequenceを再確認する。途中のpublish・bank再利用で不整合ならnativeへ戻る。
angle hookは同じframeでcameraが受理したEye/Targetだけを使う。

### 2. 方位call `0x00110BD8`: コンパスと歩行

原作 `FUN_0022B430` はEye−Targetからyawをstack+0x14へ、distanceをf0へ返す。
まず原作引数で計算・記録し、cameraがOrbitを受理した場合だけrender Eye/Targetで再計算。
原作callerが `0x0041752C/530` へstoreするので、描画と方位の値が一致する。

- 方位盤: `FUN_001245D8` はcamera yawを使う。
- 針: `FUN_00124288` はplayer heading（`0x004189C4`）−camera yawを使う。
- 歩行: `FUN_0014ABF0` ほかの移動処理も同じcamera yawを読む。

したがって針をcamera変数と誤認して固定しない。カメラだけ回す場合とキャラだけ向きを変える場合を
別に確認する。独立eye offsetで実視線が変わった場合も、名目GUI yawでなく実Eye−Targetのyawを渡す。

### 3. FOV call `0x0010FA34`

原作投影登録 `FUN_002465F0` のfield専用call前でX/Y scaleだけを上書きする。
論理viewport幅512なので `focal_x = 256 / tan(horizontal_FOV/2)`、Yは原作比 `7/6`。
原作焦点距離 `0x00417524`、深度、投影中心は変更しない。実画面の画角変化を確認した。

guestは前回自己適用値と現在のscaleがbit一致する場合だけ前回native値へ戻し、その後の新native値を保存する。
別のnative書込みが入ればその値を優先する。FOV解除も最後の自己値と一致する場合だけ復元する。
FOVはOrbitに付随。共通runtimeはOriginalのFOV-onlyを実行しない。

## 安全条件・復元

- identifyはSerialとCRC両方。全adapter書込みはGUIのGuardedBackendを渡された `self.backend` 経由。
- guest/host双方が mode1または2、target owner=canonical player、camera pointer一致、従来のpause/load/field 7フラグを確認。
  カクラム砂漠の反例はmode1で原作poseを `0x001106B8` から、従来のmode2は別の分岐から作るが、どちらも同じfield look-at/angle callに合流する。
  mode0は入口を共有しても今回の反例に該当しないので許可しない。全special sceneを判別する保証ではない。
- **メニューはhostのread_sceneでは識別できない**。確認したメニューではfield専用hookが実行されず
  heartbeatが停止した。runtimeがheartbeat監視で安全を保証しているという意味ではない。
  メニューではOriginalへ戻すことを推奨。メニュー内での全hook/lens解除は実測した。
- 全hook+delay/cave/control blockを最初の書込み前に検査。未知命令・非zeroの別caveは強制上書きしない。
  毎parameter発行前も全resourceを検査・不足code再構築する。
- `other_area_1` と `playable1` は3hookこそstockだが、以前のmode2専用caveが残る。全3本の旧code全長が既知SHA-256と一致し、
  全hook＋delayがstock、control magicがMSG1、flags/applied/projection所有がすべて0の場合に限り、新しいOrbit要求時に同じ範囲へ移行する。
  Originalのままなら書かない。旧hook稼働中、一部混在、未知命令の場合は中止し、MOD未適用stateかゲーム再起動で復旧する。
- cave `0x000F0000..0x000F1000`、block `0x000F1000..0x000F1300` は4状態で全zero、
  ELF最小PT_LOAD `0x00100000` より下。全将来kernel/overlay配置まで保証するものではない。
- Original/通常終了で3hookをstockへ返し、projectionとnative eye/targetから求めたyaw/distanceを返す。
  古い場所の座標を丸ごと書き戻さない。cave自体は解除後も残す。
- stock state読込み後にcode/bank/flagsを再構築し再適用。ユーザー原本stateへは保存しない。
- 別ゲーム・不明identityではrestoreも書込みになるため行わず、既存runtime.abandonを使う。
  強制終了・途中でVMを停止したときの即時復元は保証しない。

実行した確認は [`TEST_RESULTS.md`](TEST_RESULTS.md) を参照。
