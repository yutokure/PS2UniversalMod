# Minstrel Song 検証結果

## 2026-11-21 — カクラム砂漠の反例と既存5状態

**日本版 SLPM-65920 / 2B9AF3C5。提供された6状態すべてでOrbitとOriginal復帰を確認。**
11月21日更新の `other_area_1` は、旧版ではhost判定から外れ、`read_scene().valid == False` となった。
原作camera modeは1。既存5状態はすべて2で、active camera/target owner、7本のfieldフラグ、native焦点距離の条件は同じだった。
原作は異なるpose計算後に同じfield描画処理へ合流する。モード以外の条件は緩めていない。

| 入力state | mode | 開始時の3hook / cave | 実機結果 |
|---|---:|---|---|
| `other_area_1`（カクラム砂漠） | 1 | stock / 解除済みの旧版 | 旧版を自動移行、2姿勢・解除成功。画面でも地形の構図とコンパスの変化を確認 |
| `playable1` | 2 | stock / 解除済みの旧版 | 旧版を自動移行、2姿勢・解除成功 |
| `base`、`base_only_wait`、`base_chara_move`、`base_chara_move_and_camera_big_move` | 2 | stock / 全zero | 各2姿勢・解除成功 |

- 各stateで (yaw, pitch, 距離, 水平FOV) を **(35°,16°,12,70°)** → **(−105°,29°,18,58°)** と変更。全12点で
  GUI要求値でなく実View行列 `0x00417410` と原作側yaw/distance、投影scale、guest heartbeat進行を照合した。
  player位置と要求した姿勢から再構成した4×4行列との最大要素誤差は砂漠 `0.000306` 未満、他5状態 `0.000016` 未満。
- 各stateで解除し、全hook＋delayがstock、flagsと投影所有が0、水平FOVが `53.0500335°`。原作Eye/Targetからの
  再構成と実Viewとの差は全状態 `0.000043` 未満。画像の目視は今回の砂漠のみ。全方向の歩行・イベント・メニュー・全エリアは追加検証していない。
- 専用単体 `python -m pytest tests/test_minstrelsong.py -q`：**110 passed**。mode1/2のcamera・angle・FOVと、mode0/3/4/高位bit、
  旧hook稼働中・旧新版混在・破損・不正な所有状態での書込み拒否を含む。
- 個別portable PCSX2（PINE 28191、cardなし、入力なし）で複製slotだけを使用。Serial/CRC照合後にGuardedBackend経由で適用/解除。
  全6原本のSHA-256が検証開始時の複製と一致し、このVMだけを終了した。ユーザーのPCSX2、state、cardへの書込みなし。

## 2026-11-04 — 当時のmode2版の結果

対象: **SLPM-65920 / 2B9AF3C5**。作業branch `feature/minstrelsong-adapter`。
この記録は今回のadapter sourceを対象とする。独立review/gateではなく、実装側の検証。
全エリア・全イベントへの対応を意味しない。方式と制限は [`CAMERA.md`](CAMERA.md)。

## データ保護・環境

- 提供4stateを読み取りで展開。終了前に元4ファイルのSHA-256と展開manifestの一致を確認。
- 開始時VMを別名 `sstates/minstrelsong/user_start_20261104_2140.p2s` へ退避。
- 原作を右スティック回転対応と仮定せず、camera行列・Eye/Target・writer・方位consumerを個別解析。
- PCSX2 fork-B056de99、EE GDB10501（MCPのみ）、PINE28011（GUIまたは検証scriptの1clientのみ）。
- 歩行前のcardコピーはPCSX2のexclusive lockで失敗。prototype解除後に正常終了し、
  原card2枚の完全backupと試験用2枚を作成して再起動。歩行/メニュー試験は試験用カードを使用。
- ISO・ELF・RAM・スクリーンショット・card・stateはrepo外。元ISOは読取りのみ。

## 合成単体・GUI・直接境界

```powershell
C:\PS2CameraLab\python\venv\Scripts\python.exe -m pytest `
  tests/test_minstrelsong.py tests/test_gui.py tests/test_core.py `
  tests/test_game_guard.py tests/test_pine_backend.py -q --tb=short
```

**267 passed / 59.53s**。うち新adapter専用92件。GUI全suiteを含む。

- Serial/CRC両一致、誤版read-only、ゲーム間誤認防止、起動Original、日英表示、範囲/機能無効表示、設定分離。
- host/guestの10guard、有限値、latest player加算、native eye/target/headingと第5引数t0保持。
- camera/angle/FOVの生成MIPSを小型interpreterで検証。PS2実機全命令/schedulingの代替ではない。
- seqlock奇数・bank途中再利用の拒否、cameraとangleの同一frame引数。
- 全resourceの未知命令/cave占有を最初の書込み前に拒否、解除・stock reload・guard abandon。
- 一度適用した後のcave破損をparameter発行前にも拒否。全zero caveはbank発行より先に再構築。
  この追加試験で初版の所有確認省略を発見し、`_publish`の毎回prepareへ修正した。
- FOV独立解除・native lens優先、メニュー相当のhost-invalid状態でも所有hookの解除。

オフラインscannerは合成self-testと4stateのlook-at数学検証をPASS。
全repository suite、他ゲームの実機回帰、独立reviewは今回未実施。
共通coreは変更せず、既存adapterとの直接GUI/runtime/guard境界を上記で確認した。

## GUI実機: 22/22 PASS

```powershell
C:\PS2CameraLab\python\venv\Scripts\python.exe tools/minstrelsong_live_check.py `
  --move --out C:\PS2CameraLab\test_evidence\minstrelsong\live_2224 `
  --reload-handshake C:\PS2CameraLab\work\minstrelsong\reload_2224
```

証跡JSONは上記outの `checks.json`（22件、completed/passed=true）。
GUI一時APPDATA、入力scripted、既存GuardedBackend経由。原作base開始、
reload時は保護されたbig-camera stateを外部MCPで読み込みresumeし、handshakeを完了した。

| 確認 | 実測・結果 |
|---|---|
| 版識別/起動 | 正確版、Original、Free無効、offset/FOV有効、3hook stock |
| GUI enable | 3hook適用、runtime errorなし |
| yaw/pitch/d | (150,22,6)、(−165,22,10)、(150,60,10)、(−165,60,6)。角度誤差<0.00002°、距離誤差<0.000002 |
| コンパス方位 | 各Orbitの実Eye−Target yawと原作camera yaw一致。画像で方位盤と針の回転を確認 |
| 6axis+height | Eye誤差1.31e−6、Target誤差3.09e−6。独立offset後の実yawも原作方位へ反映 |
| FOV40° | 実39.9999985°、X703.35425、Y820.57990 |
| FOV65° | 実65.0000000°、X401.83951、Y468.81271 |
| FOV85° | 実85.0000014°、X279.37497、Y325.93744 |
| FOV解除 | Orbit保持、原作53.0500335°へ復帰。原作master焦点距離512.89563は不変 |
| right入力 | scripted入力でyaw−165→−149.55357、離すと保持。原作用keyboard右軸だけではcamera/actor不変 |
| 短いUp歩行 | 0.23秒、XZ=(−0.624313,+1.062080)、距離1.231983、実視線とのcos=0.99996944 |
| guest追従 | host camera出版freeze中にheartbeat389→404、Eye/Target-player相対誤差0 |
| actor針の独立性 | heading178.96425→149.55239°、camera yaw150.00001°を維持 |
| stock state再適用 | 別構図のbig state読込み後、3hook・yaw150/pitch22/d10/FOV40と原作方位を自動再適用 |
| Original/終了 | 3hook stock、flags0、native Eye/Target・lens53.0500335°・yaw−123.57894°へ復帰 |

FOV40/85・yaw150/−165のスクリーンショットを実際に読み、画角/構図/コンパス変化を確認した。
画像はwindow capture（1130×712、左右余白あり）。別途MCPのnative GS画像でもprototypeとadapterを確認。
自動画像認識で全UIを判定したわけではない。offscreen GUI画像はこの環境のQt font警告により文字が四角になったため、
GUI文字の可読性を画像PASSには含めない（日英文字列・機能表示はGUI unitで確認）。

## メニューの限定確認（別途）

通常フィールドでOrbit150/pitch22/d8/FOV65を適用後、Squareで原作メニューを開いた。
0.4秒のheartbeatは4183→4183で、field専用hookは非実行。
ただしhost `read_scene().valid` はtrueのまま。既存pause/load flagsはmenu判定の保証にならない。
メニュー内からOriginalへ返して全hook stock・FOV53.0500335°、Crossでフィールド復帰を確認した。
この1メニュー以外・全メニュー階層・戦闘は未検証。特殊場面ではOriginalを推奨する。

## 制限・未検証

- イスマス城内の限定場面・短い入力。全エリア/全方向/長時間/全ロード経路は未実施。
- 壁・柱の内部や裏面が見える場合がある（原作のcamera collisionをOrbitへ適用しない）。
- 原作右軸のraw pad addressは未特定。入力byte保持のreadback成功とは称さない。
  右入力遮断のpatch自体は存在せず、今回の原作右軸camera不変のみ実測。
- Original FOV-only、Free Cameraは対象外。
- live別ゲーム切替・未対応版起動は今回行わず、合成guard/GUI回帰で確認。
- 終了時は試験用card設定を元の2枚へ返し、開始時VM stateをロードして原作camera/全hook stockで復帰。
  元のミンストレルソングsave関連36ファイルは完全backupとSHA-256一致（変更なし）。
- 変更source/docの未追跡分を含む15ファイルをaudit_repoの検査関数で監査し、問題なし。
  `git diff --check`も問題なし。indexへstageしていないためstaged監査は未実施（commit前に必要）。
- 2026-11-04終了時点ではGit commit/push/PR/mergeは未実施。ゲーム由来データはGit対象へ追加しない。

## 再開・コミット前確認 — 2026-11-05

- 同じ5テストファイルを再実行し、**267 passed / 60.43s**。
- scannerの合成self-test、ミンストレルソング関連文書リンク、`git diff --check` はすべて問題なし。
- 2026-11-04の実機証跡JSONを再読し、22件すべてPASS、stock state再適用と復元の記録を確認。
  今回はGit反映の確認であり、ゲームの状態を変える実機試験は追加していない。
- 対象はadapter・GUI登録・合成tests・自作解析/実機ツール・文書の15ファイル。
  共通coreと既存adapterの実装は変更していない。
- 明示した15ファイルだけをstageし、indexの一覧・差分統計・`git diff --cached --check`と
  `python tools/audit_repo.py --staged`を確認してPASS。原本ゲームデータ・秘密情報の追加なし。
