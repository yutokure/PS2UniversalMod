# 新牧場物語 ピュア イノセントライフ — Orbit・FOV・移動・時計

2026-11-07。日本版 **SLPS-25763 / 9AC21F92** のみ。Serial と CRC の両方を検査する。
原作に右スティックカメラはない。原作入力の中立化・遮断パッチは追加しない。
実行した確認は [TEST_RESULTS.md](TEST_RESULTS.md)。本書は全マップ／全イベント対応の保証ではない。

## 解析根拠

ユーザー提供4ステートを原本のまま保護し、EE RAM をローカルへ展開して比較した。
順は base / wait / character / character+camera。時計表示は 06:09 / 06:36 / 07:10 / 07:53。
wait で変わらず、移動で変わる float32 と affine view を抽出し、MCP watchpoint・Ghidra のR5900解析・オンライン読戻しで消費経路を照合した。

| 項目 | アドレス／値 | 根拠 |
|---|---|---|
| player XYZ | `0x1BA640` | base/wait `(-388.0546875,0,432.9795532)`、character X `-371.2547302`、big `(-479.0632019,42.8377342,631.9862061)` |
| camera eye | `0x1BA400` | base/wait `(-388.0546265,-40,360.5226746)`、big `(-479.0631409,-40.7816048,559.5292969)`。view逆行列と一致 |
| native pitch/yaw/roll | camera `+0x10/+0x14/+0x18` | `FUN_001029E8` が回転行列を生成。4ステートはpitchだけ変化（−0.3322429→−0.7582028rad）、yaw回転の証拠ではない |
| camera root | `[0x2372C0] = 0x1BA400` | main renderの遅延slot load `lw a0,-0x7730(gp)` |
| player root | `[0x2372E8] = 0x1BA640` | camera追従先／native入力actor。移動consumer停止時の`s2`でも実測 |
| native forward | `0x1BA4A0` vec4 | builderが `(0,0,1)` をcamera rotationで変換 |
| view | `0x207210` | copied cameraを変えると実際の行列・画面の向きが変化 |
| focal | camera `+0x7C`、約443.40506 | 投影関数`0x1706F0`へ渡す値。描画コピーだけにFOVを適用、原作値は保持 |
| projection | `0x2071D0` | `m00 = focal * [0x236A30]`、X倍率約0.8。実際の水平FOV読戻し元 |
| 時計 hour/min/sec | `0x1BE7DC/E0/E4` u32 |4ステートで表示時刻と一致。minute書込みwatchpoint=`0x121B60`、`v1=0x1BE6B8` |
| main-loop count | `0x1BE7CC` | main loop末尾で+1。clock-only停止中も進行 |
| elapsed baseline | `0x1BE7F4` | 時計停止中も更新。解除時のcatch-upを避けるため止めない |

時刻writer `FUN_00121A98` は時刻正規化・明示設定にも使われるため、関数丸ごとの無効化はしない。
通常進行の`FUN_00121D40`→`FUN_00121CB8`（current+elapsed）だけに注目する。
原作は `0x1BE7F8 / 30` を秒として渡す。今回の場面は120/30=4ゲーム秒／30Hzフレーム。

## 描画コピー方式

1. main render call **`0x1695F0`** の `jal 0x1029E8` だけを host bootstrap でwrapperへ向ける。
   遅延slotの `lw a0,-0x7730(gp)` は保存する。
2. guestは原作camera `0xA0` bytesを専用scratchへコピーする。原作camera structは変更しない。
3. coherent bankの相対eye／targetへ、そのフレームのplayer XYZを加算。
4. scratchのeye、pitch/yaw、rollと任意のfocalだけを差替え、元のbuilderでview・投影関連出力を生成する。
5. builderが書く共通forward vec4は前後で保存／復元し、原作の次フレーム処理へ漏らさない。

座標は **Y-down**。coreのOrbit pitch正はeyeが上、注視点高さは負が上。
実視線`v=target-eye`から native pitch=`-atan2(v.y,hypot(v.x,v.z))`、yaw=`atan2(v.x,v.z)`。
位置・注視点オフセットを使っても移動基準は同じ実視線を参照する。

host publicationは二重bankのodd/even sequenceとactive slotで公開し、guestが安定性を再検査する。
毎回全コード・control所有を検査するが、同一adapterロック内の一取引ではimmutable inspectionを一度だけ使う。
取引を跨いだ安全検査キャッシュはない。重複検査削減前は短い入力を取りこぼす実測があったため整理した。

## FOV — 校正と投影経路

水平FOV **20〜110°**。`FUN_001029E8` は camera `+0x7C` のfocal、`[0x236A30/34]`のX/Y倍率、
near/farを `FUN_001706F0` へ渡す。watchpoint `0x2071D0` の実測writerは `0x19B9EC` の `sqc2 vf09,(s2)`、
backtraceは `0x170800 → 0x102A24 → 0x1695F8`。`f12=443.40506 / f13≈0.8 / f14≈0.9333333` と静的解析が一致した。

半幅 **256** はmain初期化の `FUN_001830C8(512,448,...)` と、正規化投影`0x207DA0`の
`m00 = 2*focal*X倍率/512`、`m11 = 2*focal*Y倍率/448` の両方で確認した。
PCSX2の表示アスペクト補正後のスクリーンショット寸法を投影式へ代入しない。

```text
actual horizontal FOV = degrees(2 * atan(256 / projection.m00))
focal request         = 256 / (native_X_factor * tan(radians(FOV) / 2))
```

4提供stateのnativeはfocal `443.405059814`、X倍率 `0.799999952316`、m00 `354.723999023`、
水平FOV **71.635048°**。以前のinformational値54.68°は未校正であり、現在の値・既定値として使わない。

- 既存二重bankの`SLOT_FOCAL=0x38`とbank専用`FLAG_FOV=4`をcoherent snapshotへ含める。
  lifecycleは従来のOrbit/時計maskだけを使う。FOV単独でOrbit・移動hookを有効化しない。
- guestは安定snapshotのflagがあるときだけ**コピー**の`+0x7C`を変える。原作camera・near/farは変更しない。
  native builderが投影`0x2071D0`、view-projection`0x207250`、clip副行列`0x207D20/60/A0`とその合成を一括生成する。
  raw m00だけを後段で上書きする方式ではない。
- `read_fov_deg()`は実投影m00から算出、`fov_in_sync()`はhook所有・guest適用flag・実投影を照合する。
  NaN/Infや不正X倍率は公開前に拒否。全resource preflightとGuardedBackendは維持する。
- 「ゲーム値に戻す」はflagを落とし、次のrenderで**その時点のnative focal**から再生成する。保存した古い値を原作へ書き戻さない。
  Original・正常終了も解除。時計停止は独立したまま。共通runtimeのOriginal FOV-onlyは対象外。
- layout所有magicは **ILC2 (`0x494C4332`)**。旧ILC1 cave/controlを稼働中に上書きしない。
  旧controllerを正常終了してからstock stateを読み込むか、ゲームを再起動して新controllerを使う。

## 移動方向とキャラの向き

`FUN_00104DC8` が左入力（または方向キー）の`atan2(LX,-LY)`にcamera yawを足し、
`0x173008`で正規化した角度をnative移動・向き処理へ渡す。

- hookは **`0x104E9C`** の2 loadを`j cave; nop`へ。続く`jal`をjump遅延slotに入れない。
- caveはnative camera pointerを`v0`へ、yawを`f12`へ再現し、Orbit時・検証済みplayer consumer時だけbank yawへ差替える。
- `0x104EA4`の元のnormalize callと`add.s f12,f0,f12`遅延slotへ戻る。`f0`の入力角、速度・衝突・向きの平滑化は維持。
- mid-function caveで触るscratch GPRは128bit保存・復元。render wrapperはcalleeへのargument homeを空けてRAを保存する。

**player+0x30のbit2はscene gateではない。** idleで`0xBC`、入力consumer停止時は`0xBE`を実測した。
初期実装のbit2必須条件は通常待機を拒否したため撤去した。移動hookは元々native入力処理の許可後にだけ到達し、
追加のactor identityと下記構造guardを適用する。

## 時計停止

**`0x121D84`: `mflo a0` (`00002012`) → `move a0,zero` (`0000202D`)**。
経過秒だけをゼロにし、原作のcurrent時刻正規化・基準更新・main loopは継続する。
独立フラグなのでOriginal cameraでも利用できる。sleep・イベント等の明示時刻setterには触れない。
通常進行を停止する機能であり、時間システム全体のあらゆる状態遷移の凍結ではない。

runtime専用flag `pause_game_time` は最大4Hzでサービス、失敗は1秒後から再試行・専用エラー表示。
設定・presetに保存せず、起動／再接続は必ずoff。Originalラジオは時計選択保持、無効化・同一ゲーム正常終了は解除。

## 所有・適用／復元

| リソース | stock | Orbit時 | clock-only時 |
|---|---|---|---|
| main render `0x1695F0` | `0C040A7A / 8F8488D0` | wrapper call | wrapper call |
| move `0x104E9C` | `8F8288D0 / C44C0014` | cave jump/nop | stock |
| clock `0x121D84` | `00002012` | 時計選択に応じる | `0000202D` |

- reserved **`[0xA8000,0xAC000)`** は4ステートで全ゼロ、ELF最低segment `0x100000` より下。
  first-page scanでliteral/direct jump参照なし。ただし全kernel/DMA生存期間の形式的証明ではない。
  `0x80000` はkernel付近の参照・使用データがあるため候補から除外。
- render cave `0xA8000`、movement cave `0xA9000`、control `0xAA000` size`0x800`、scratch `0xAA400`。
- native site＋delayはstock/完全な自所有pair以外を拒否。空でない未知cave・control、損傷した到達可能caveは書き換えない。
- hostは既知のmain render bootstrap以外のnative codeへ書かず、guest render tailで全siteを先に検証してからmove/clock適用・復元。
  desired mask=0で最後にbootstrapを元へ戻す。実行中caveは消去しない。
- ACK待ち上限0.5秒。PCSX2がpausedなら再開を促して失敗を可視化する。未知命令を強制復元しない。
- Serial+CRCの`GuardedBackend`経由。ゲーム切替／識別不能では復元を書き込まず`abandon()`。
  接続guardの既存0.25秒lease窓は変えていない。

## 通常場面のguardと制限

host/guestがcamera/player roots、camera flags=8、event停止word=0、field owner非zero、
alternate camera target/player pointer=0、native reject flags`0x28008`、input拒否byte bit`0x20`を検査する。
geometryのNaN/Inf・極端値・singular viewをhostで拒否する。

これらは**全menu/event識別ではない**。提供された屋外場面・同一版state reloadの限定検証。
すべての屋内、乗物、会話、日付変更、睡眠、イベント、長時間・他版は未網羅。
Freeは未対応としてGUIで無効化する。FOVはOrbitに付随する。Orbitには壁／地形衝突を追加せず、
広角や回り込みでは裏面・木の板ポリが見えることがある。全mapの広角カリング・LOD・イベント投影は未網羅。

原本ISO・ELF・ステート・RAM・Ghidra project・スクリーンショットはGitに入れない。
ローカル作業先 `C:\PS2CameraLab\work\innocentlife`、証拠 `C:\PS2CameraLab\test_evidence\innocentlife`。
